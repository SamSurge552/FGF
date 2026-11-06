"""Foundation Galactic Frontier 初版。

默认干跑（只匹配画框，不点鼠标）。明天真测加 --click。
F12 随时停。

  python gui.py
  python bot.py --gui
  python bot.py --goal 0 --click --count 10
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import threading
import time

import cv2
import numpy as np
import pyautogui
from pynput import keyboard

import calibrate
import config
from capture import grab, hold_foreground, is_admin, list_windows, pick_game_window, screen_click, screen_drag, screen_key, screen_move, screen_wheel
import overlay
from vision import Hit, Matcher, hull_binary

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

STOP = threading.Event()
LOG_HOOK = None
_listener = None
_stop_sound_done = False
_sound_lock = threading.Lock()


def _play_tones(pairs: list[tuple[int, int]]) -> None:
    def work() -> None:
        try:
            import winsound

            for freq, dur in pairs:
                winsound.Beep(int(freq), int(dur))
        except Exception:
            try:
                import winsound

                winsound.MessageBeep()
            except Exception:
                pass

    threading.Thread(target=work, daemon=True).start()


def cue_start() -> None:
    global _stop_sound_done
    with _sound_lock:
        _stop_sound_done = False
    _play_tones([(988, 110), (1318, 180)])


def cue_stop() -> None:
    global _stop_sound_done
    with _sound_lock:
        if _stop_sound_done:
            return
        _stop_sound_done = True
    _play_tones([(784, 110), (523, 240)])


def halt(where: str, why: str) -> None:
    """停掉整个会话，并响停止音。"""
    logp(where, why)
    STOP.set()
    import overlay

    overlay.hide()
    cue_stop()


def halt_timeout(where: str) -> None:
    halt(where, "超时，停止，不再开下一轮")


def cue_found() -> None:
    global _stop_sound_done
    with _sound_lock:
        _stop_sound_done = True
    _play_tones([(880, 90), (1175, 90), (1568, 280), (1175, 90), (1568, 420)])


def on_press(key) -> None:
    try:
        if key == keyboard.Key.f12:
            log("F12 停止")
            STOP.set()
            overlay.hide()
            cue_stop()
    except Exception:
        pass


def ensure_stop_listener() -> None:
    global _listener
    if _listener is not None:
        return
    _listener = keyboard.Listener(on_press=on_press)
    _listener.daemon = True
    _listener.start()


def log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    hook = LOG_HOOK
    if hook is not None:
        try:
            hook(line)
        except Exception:
            pass


def _quota(done: int, count: int) -> str:
    if config.INFINITE:
        return f"{done}/无限"
    return f"{done}/{count}"


def logp(phase: str, msg: str) -> None:
    log(f"[{phase}] {msg}")


def note_odd(phase: str, msg: str) -> None:
    """非正常情况：界面日志一份，logs/odd/日期.txt 再记一份。"""
    logp(phase, msg)
    folder = os.path.join(config.ROOT, "logs", "odd")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, time.strftime("%Y%m%d") + ".txt")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{phase}\t{msg}\n")


def to_screen(rect, hit: Hit) -> tuple[int, int]:
    cx, cy = hit.center
    return (rect.left + cx, rect.top + cy)


def _click_nudge() -> tuple[int, int]:
    """横或竖偏 1 或 2 像素。"""
    step = random.choice((1, 2))
    sign = random.choice((-1, 1))
    if random.randrange(2):
        return step * sign, 0
    return 0, step * sign


def mouse_click(rect, sx: int, sy: int) -> None:
    with hold_foreground(rect) as ok:
        if not ok:
            log("游戏窗口没到前台，仍尝试点击")
        screen_click(sx, sy, config.CLICK_HOLD)
    time.sleep(config.CLICK_PAUSE)


def act(rect, hit: Hit, do_click: bool, why: str) -> None:
    sx, sy = to_screen(rect, hit)
    nudged = ""
    if do_click:
        dx, dy = _click_nudge()
        sx += dx
        sy += dy
        nudged = f"  偏移=({dx},{dy})"
    log(f"{'CLICK' if do_click else 'DRY '} {why}  {hit.name}={hit.score:.3f}  frame={hit.center}  screen=({sx},{sy}){nudged}")
    if do_click:
        mouse_click(rect, sx, sy)


_LOOK_SIZE: tuple[int, int] | None = None


def look_button_size() -> tuple[int, int]:
    """查看按钮的长、宽。长用于左边，宽用于上下边。"""
    global _LOOK_SIZE
    if _LOOK_SIZE is None:
        im = cv2.imread(config.TEMPLATES["look"])
        if im is None:
            _LOOK_SIZE = (133, 52)
        else:
            height, width = im.shape[:2]
            _LOOK_SIZE = (int(width), int(height))
    return _LOOK_SIZE


def ship_click_frame(rect, hit: Hit) -> tuple[int, int]:
    """靠左或上下边时改到 1.7 倍按钮处，保证查看出现在窗口内。"""
    x, y = hit.center
    y -= config.SHIP_CLICK_ABOVE
    length, width = look_button_size()
    margin_x = config.LOOK_EDGE_SCALE * length
    margin_y = config.LOOK_EDGE_SCALE * width
    nx, ny = x, y
    if x < margin_x:
        nx = int(round(margin_x))
    if y < margin_y:
        ny = int(round(margin_y))
    bottom = rect.height - margin_y
    if y > bottom:
        ny = int(round(bottom))
    nx = min(max(nx, 0), max(0, rect.width - 1))
    ny = min(max(ny, 0), max(0, rect.height - 1))
    return nx, ny


def act_frame(rect, hit: Hit, frame_xy: tuple[int, int], do_click: bool, why: str) -> None:
    sx, sy = rect.left + frame_xy[0], rect.top + frame_xy[1]
    moved = frame_xy != hit.center
    extra = f"  改点 frame={frame_xy}" if moved else ""
    log(
        f"{'CLICK' if do_click else 'DRY '} {why}  {hit.name}={hit.score:.3f}  "
        f"frame={hit.center}  screen=({sx},{sy}){extra}"
    )
    if do_click:
        mouse_click(rect, sx, sy)


def click_until_gone(
    matcher: Matcher,
    rect,
    hit: Hit,
    name: str,
    do_click: bool,
    why: str,
    tries: int = 3,
) -> bool:
    """点会关掉当前页的按钮。还在就再点，三次仍在就响一声并停止。"""
    current = hit
    for i in range(1, tries + 1):
        if STOP.is_set():
            return False
        act(rect, current, do_click, why if i == 1 else f"{why} 再点")
        time.sleep(0.6)
        if not do_click:
            return True
        still = matcher.find(grab(rect), name)
        if still is None:
            logp("确认", f"{why} 第{i}次后面已关掉")
            return True
        logp("确认", f"{why} 第{i}次后按钮还在 {still.score:.2f}@{still.center}")
        current = still
    logp("确认", f"{why} 点了{tries}次页面还在，停止")
    STOP.set()
    overlay.hide()
    cue_stop()
    return False


def require_hit(matcher: Matcher, rect, name: str, timeout: float, where: str, tries: int = 3) -> Hit | None:
    """找不到就再等。试满仍没有就停。"""
    for attempt in range(1, tries + 1):
        if STOP.is_set():
            return None
        hit = wait_hit(matcher, rect, name, timeout)
        if hit:
            return hit
        logp(where, f"第{attempt}次找不到 {name}")
    halt(where, f"找不到 {name}，已试{tries}次，停止")
    return None


def wait_hit(matcher: Matcher, rect, name: str, timeout: float, thresh: float | None = None) -> Hit | None:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline and not STOP.is_set():
        frame = grab(rect)
        last = frame
        hit = matcher.find(frame, name, thresh if thresh is not None else config.thresh_for(name))
        mark_rois(matcher, frame)
        if hit:
            return hit
        time.sleep(config.LOOP_SLEEP)
    if last is not None:
        score, loc = matcher.best(last, name)
        t = thresh if thresh is not None else config.thresh_for(name)
        floor = config.match_floor(name, t)
        line = f"没找到 {name}  最高分={score:.3f}@{loc}  阈值={t:.2f}"
        if abs(floor - t) >= 0.005:
            line += f"  采用{floor:.2f}"
        log(line)
        save_debug(matcher, last, [])
    return None


def save_debug(matcher: Matcher, frame, hits: list[Hit]) -> None:
    os.makedirs(config.DEBUG_DIR, exist_ok=True)
    vis = matcher.draw(frame, hits)
    path = os.path.join(config.DEBUG_DIR, "last_frame.png")
    cv2.imwrite(path, vis)


def act_xy(rect, fx: int, fy: int, do_click: bool, why: str) -> None:
    sx, sy = rect.left + fx, rect.top + fy
    log(f"{'CLICK' if do_click else 'DRY '} {why}  frame=({fx},{fy})  screen=({sx},{sy})")
    if do_click:
        mouse_click(rect, sx, sy)


def _near(a: tuple[int, int], b: tuple[int, int], d: int = 40) -> bool:
    return abs(a[0] - b[0]) <= d and abs(a[1] - b[1]) <= d


def _in_box(pt: tuple[int, int], box: tuple[int, int, int, int]) -> bool:
    x, y = pt
    x1, y1, x2, y2 = box
    return x1 <= x <= x2 and y1 <= y <= y2


def slot_boxes(yellow: Hit) -> list[tuple[int, int, int, int]]:
    """三艘船槽，相对 settings 面板。"""
    px = yellow.x1 - config.PANEL_YELLOW[0]
    py = yellow.y1 - config.PANEL_YELLOW[1]
    boxes = []
    for i in range(3):
        x1 = px + i * config.SLOT_W
        y1 = py + config.SLOT_TOP
        boxes.append((x1, y1, x1 + config.SLOT_W, y1 + config.SLOT_H))
    return boxes


def pick_idle_fleet(matcher: Matcher, rect, frame, do_click: bool) -> bool:
    """有旗=已在队伍中；trading=跑商运。选什么图标都没有的槽。"""
    yellow = matcher.find(frame, "rally_yellow")
    if not yellow:
        return False
    flags = matcher.find_all(frame, "flag", config.FLAG_THRESH)
    tradings = matcher.find_all(frame, "trading", config.TRADING_THRESH)
    busy_pts = [h.center for h in flags + tradings]
    for i, box in enumerate(slot_boxes(yellow)):
        busy = any(_in_box(pt, box) for pt in busy_pts)
        marks = []
        if any(_in_box(h.center, box) for h in flags):
            marks.append("旗(已在队)")
        if any(_in_box(h.center, box) for h in tradings):
            marks.append("商运")
        log(f"船槽{i + 1} {box} {'/'.join(marks) if marks else '空闲'}")
        if not busy:
            cx, cy = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
            act_xy(rect, cx, cy, do_click, f"选空闲船槽{i + 1}")
            time.sleep(0.5)
            return True
    log("没有空闲船槽")
    return False


def _unique_hits(hits: list[Hit], d: int = 28) -> list[Hit]:
    kept: list[Hit] = []
    for h in sorted(hits, key=lambda x: -x.score):
        if any(_near(h.center, k.center, d) for k in kept):
            continue
        kept.append(h)
    return kept


_RALLY_COL_DX = 190
_RALLY_ROW_DY = 68


def _assign_minute_points(pts: list[tuple[int, int]]) -> dict[int, tuple[int, int]] | None:
    """2x2：1/3 上一行，5/10 下一行。"""
    pts = sorted(pts, key=lambda p: (p[1], p[0]))
    rows: list[list[tuple[int, int]]] = []
    for p in pts:
        if not rows or p[1] - rows[-1][0][1] > 28:
            rows.append([p])
        else:
            rows[-1].append(p)
    for row in rows:
        row.sort(key=lambda p: p[0])
    if len(rows) >= 2 and len(rows[0]) >= 2 and len(rows[1]) >= 2:
        return {1: rows[0][0], 3: rows[0][1], 5: rows[1][0], 10: rows[1][1]}
    if len(rows) == 1 and len(rows[0]) >= 2:
        left, right = rows[0][0], rows[0][1]
        return {
            1: left,
            3: right,
            5: (left[0], left[1] + _RALLY_ROW_DY),
            10: (right[0], right[1] + _RALLY_ROW_DY),
        }
    return None


def _rally_radio_grid(matcher: Matcher, frame) -> dict[int, tuple[int, int]] | None:
    ons = matcher.find_all(frame, "time_on", config.TIME_ON_THRESH)
    offs = matcher.find_all(frame, "time_off", config.TIME_OFF_THRESH)
    pts = [h.center for h in _unique_hits(list(ons) + list(offs), d=22)]
    block3 = matcher.find(frame, "time_3")
    if block3:
        p3 = (block3.x1 + 18, block3.center[1])
        if not any(_near(p3, q, 22) for q in pts):
            pts.append(p3)
    grid = _assign_minute_points(pts) if len(pts) >= 2 else None
    if grid:
        return grid
    if block3:
        x3, y3 = block3.x1 + 18, block3.center[1]
        return {
            1: (x3 - _RALLY_COL_DX, y3),
            3: (x3, y3),
            5: (x3 - _RALLY_COL_DX, y3 + _RALLY_ROW_DY),
            10: (x3, y3 + _RALLY_ROW_DY),
        }
    return None


def ensure_rally_time(matcher: Matcher, rect, frame, do_click: bool) -> None:
    """按 RALLY_MINUTES 点 1/3/5/10 对应圆点。已是绿 on 就不再点。"""
    minutes = int(config.RALLY_MINUTES)
    if minutes not in config.RALLY_MINUTES_CHOICES:
        minutes = 1
    grid = _rally_radio_grid(matcher, frame)
    if not grid or minutes not in grid:
        logp("贡品", f"找不到集结时间格子，跳过选{minutes}分钟")
        return
    fx, fy = grid[minutes]
    on = matcher.find(frame, "time_on", config.TIME_ON_THRESH)
    if on and _near(on.center, (fx, fy), 40):
        logp("贡品", f"{minutes}分钟已是绿on  {on.center}")
        return
    logp("贡品", f"点集结{minutes}分钟  圆({fx},{fy})")
    act_xy(rect, fx, fy, do_click, f"集结{minutes}分钟")
    time.sleep(0.5)
    frame = grab(rect)
    on = matcher.find(frame, "time_on", config.TIME_ON_THRESH)
    if on and _near(on.center, (fx, fy), 40):
        logp("贡品", f"{minutes}分钟已是绿on  {on.center}")
        return
    logp("贡品", "还没变绿，再点一次圆点")
    act_xy(rect, fx, fy, do_click, f"集结{minutes}分钟再点")
    time.sleep(0.4)


def drag_level(rect, search_go: Hit, do_click: bool) -> None:
    """点住等级数字上下拖：上=+ 下=-。次数见 config.LEVEL_DRAGS。"""
    n = config.LEVEL_DRAGS
    if n == 0:
        log(f"不拖等级（LEVEL_DRAGS=0，目标等级 {config.TRIBUTE_LEVEL} 需先对齐「等级」两字）")
        return
    fx = search_go.x1 + 183
    fy = search_go.y1 - 237
    sx, sy = rect.left + fx, rect.top + fy
    dy = -config.LEVEL_DRAG_PX if n > 0 else config.LEVEL_DRAG_PX
    times = abs(n)
    log(f"{'DRAG' if do_click else 'DRY '} 等级 {'+' if n>0 else '-'} x{times}  from ({sx},{sy})")
    if not do_click:
        return
    for _ in range(times):
        if STOP.is_set():
            return
        pyautogui.moveTo(sx, sy)
        pyautogui.drag(0, dy, duration=0.35, button="left")
        time.sleep(0.35)


def right_hud(matcher: Matcher, frame) -> tuple[int, int, int, int]:
    """右边搜寻/邮件竖条，宽高跟 hud_right.png 一样，贴右边、底栏之上。"""
    return matcher.hud_ref("hud_right", frame)


def fleet_hud_region(matcher: Matcher, frame) -> tuple[int, int, int, int]:
    """左侧船队栏。优先用 hud_ship 定位，对不上就用左列默认框。"""
    return matcher.hud_ship_region(frame)


def team_btn_region(matcher: Matcher, frame) -> tuple[int, int, int, int]:
    """自动邀请入口在右侧 HUD 最上的红旗，不在左侧船队栏。"""
    return right_hud(matcher, frame)


FLAG_HINT_FLOOR = 0.40


def flag_candidates(matcher: Matcher, frame, thresh: float) -> list[Hit]:
    region = fleet_hud_region(matcher, frame)
    hits = matcher.find_all_in(frame, "flag", region, thresh)
    return _unique_hits(hits, d=16)


def flag_centers(matcher: Matcher, frame) -> list[tuple[int, int]]:
    return [h.center for h in flag_candidates(matcher, frame, config.FLAG_THRESH)]


def weak_flag_hint(matcher: Matcher, frame) -> str:
    """列出船队栏里看得到、但没过 FLAG_THRESH 的旗。best 自己锁在船队栏，不要先裁再锁。"""
    score, loc = matcher.best(frame, "flag")
    weak = [h for h in flag_candidates(matcher, frame, FLAG_HINT_FLOOR) if h.score < config.FLAG_THRESH]
    if weak:
        bits = "  ".join(f"{h.score:.3f}@{h.center}" for h in weak[:4])
        return (
            f"低于阈值的旗 {bits}  阈值={config.FLAG_THRESH:.2f}  "
            f"船队栏最高={score:.3f}@{loc}"
        )
    return f"船队栏无低分旗候选  最高={score:.3f}@{loc}  阈值={config.FLAG_THRESH:.2f}"


def avg_ready(elapsed: float, floor: float) -> bool:
    """离平均不超过 10 秒就可以收。再早的修理不当这场打完。"""
    return elapsed >= max(0.0, floor - config.AVG_EARLY_SEC)


def find_repair(matcher: Matcher, frame) -> Hit | None:
    return matcher.find(frame, "repair")


def _finish_rally(appear_s: float | None, duration_s: float, reason: str) -> None:
    nxt = calibrate.record_goal1(appear_s, duration_s, reason)
    logp(
        "集结",
        f"信号={reason}  总耗时{duration_s:.1f}s  "
        f"下次 出场{nxt['appear_wait']:.0f}s 平均{nxt['median']:.0f}s 超时{nxt['gone_wait']:.0f}s",
    )


def wait_repair_as_signal(
    matcher: Matcher,
    rect,
    t0: float,
    appear_s: float | None,
    timeout: float,
    do_click: bool,
    min_elapsed: float,
) -> bool:
    """没检测到新旗时，单独用修理当信号，但不得短于平均耗时。"""
    logp("集结", f"没检测到新旗，改用修理当信号。至少等到 {min_elapsed:.0f}s，最多 {timeout:.0f}s")
    deadline = t0 + timeout
    last_log = 0.0
    noted_early = False
    while time.time() < deadline and not STOP.is_set():
        frame = grab(rect)
        mark_rois(matcher, frame)
        elapsed = time.time() - t0
        repair = find_repair(matcher, frame)
        if time.time() - last_log >= 10.0:
            logp(
                "集结",
                f"已等修理{elapsed:.0f}s  平均至少{min_elapsed:.0f}s  "
                f"{'修理有' if repair else '修理无'}  {weak_flag_hint(matcher, frame)}",
            )
            last_log = time.time()
        if repair and not avg_ready(elapsed, min_elapsed):
            if not noted_early:
                note_odd(
                    "集结",
                    f"没新旗，修理已在，但未到平均前{config.AVG_EARLY_SEC:.0f}s"
                    f"（{max(0.0, min_elapsed - config.AVG_EARLY_SEC):.0f}s），继续等",
                )
                noted_early = True
        elif repair:
            logp("集结", f"没新旗，修理作为信号  分={repair.score:.3f} {repair.center}  耗时{elapsed:.0f}s")
            act(rect, repair, do_click, "自动修理")
            _finish_rally(appear_s, elapsed, "repair")
            return True
        time.sleep(0.6)
    note_odd("集结", f"没新旗，等修理超时  {weak_flag_hint(matcher, grab(rect))}")
    halt_timeout("集结")
    return False


def wait_flag_gone(matcher: Matcher, rect, before: list[tuple[int, int]], do_click: bool = True) -> bool:
    """点黄确认后等新旗。打完=这面旗消失并且出现修理。没新旗才单独等修理。"""
    t = calibrate.timeouts_goal1()
    floor = t["median"] if t["samples"] >= 1 else config.DEFAULT_AVG_WAIT
    logp(
        "集结",
        f"校准 样本{int(t['samples'])} 平均{t['median']:.1f}s  "
        f"出场等待{t['appear_wait']:.0f}s 平均{floor:.0f}s 最早平均前{config.AVG_EARLY_SEC:.0f}s 超时{t['gone_wait']:.0f}s  "
        f"确认前旗 {before if before else '无'}",
    )
    t0 = time.time()
    appear_s: float | None = None
    appeared: tuple[int, int] | None = None
    last_log = 0.0
    while time.time() - t0 < t["appear_wait"] and not STOP.is_set():
        frame = grab(rect)
        region = fleet_hud_region(matcher, frame)
        now = flag_centers(matcher, frame)
        mark_rois(matcher, frame)
        fresh = [pt for pt in now if not any(_near(pt, old, 40) for old in before)]
        elapsed = time.time() - t0
        if elapsed - last_log >= 5.0:
            logp(
                "集结",
                f"已等{elapsed:.0f}s  船队栏{region}  "
                f"当前旗={now or '无'}  新旗={fresh or '无'}  {weak_flag_hint(matcher, frame)}",
            )
            last_log = elapsed
        if fresh:
            appeared = fresh[0]
            appear_s = elapsed
            logp("集结", f"船队栏新旗 {appeared}  出场{appear_s:.1f}s")
            break
        time.sleep(0.5)
    if appeared is None:
        note_odd("集结", f"没检测到新旗，改用修理当备用信号  {weak_flag_hint(matcher, grab(rect))}")
        invite_allies(matcher, rect, do_click)
        if STOP.is_set():
            return False
        return wait_repair_as_signal(
            matcher, rect, t0, None, t["gone_wait"], do_click, floor
        )
    invite_allies(matcher, rect, do_click)
    logp(
        "集结",
        f"等新旗消失并且出现修理，最多 {t['gone_wait']:.0f}s，不早于平均前{config.AVG_EARLY_SEC:.0f}s",
    )
    t_flag = time.time()
    gone_since: float | None = None
    last_log = 0.0
    noted_wait = False
    while time.time() - t_flag < t["gone_wait"] and not STOP.is_set():
        frame = grab(rect)
        now = flag_centers(matcher, frame)
        mark_rois(matcher, frame)
        elapsed = time.time() - t0
        if time.time() - last_log >= 15.0:
            logp(
                "集结",
                f"已等{elapsed:.0f}s  当前旗={now or '无'}  "
                f"{'修理有' if find_repair(matcher, frame) else '修理无'}  {weak_flag_hint(matcher, frame)}",
            )
            last_log = time.time()
        still = any(_near(appeared, pt, 45) for pt in now)
        if still:
            gone_since = None
            noted_wait = False
        elif gone_since is None:
            gone_since = time.time()
            logp("集结", f"新旗暂时没看到，确认中（需连续{t['gone_confirm']:.1f}s）")
        elif time.time() - gone_since >= t["gone_confirm"]:
            repair = find_repair(matcher, frame)
            if not avg_ready(elapsed, floor):
                if not noted_wait:
                    note_odd(
                        "集结",
                        f"新旗已消失，未到平均前{config.AVG_EARLY_SEC:.0f}s"
                        f"（{max(0.0, floor - config.AVG_EARLY_SEC):.0f}s），继续等",
                    )
                    noted_wait = True
            elif not repair:
                if not noted_wait:
                    note_odd("集结", "新旗已消失，但修理还没出现，可疑，继续等")
                    noted_wait = True
            else:
                logp("集结", f"新旗消失且出现修理  分={repair.score:.3f} {repair.center}  耗时{elapsed:.0f}s")
                act(rect, repair, do_click, "自动修理")
                _finish_rally(appear_s, elapsed, "flag_and_repair")
                return True
        time.sleep(0.8)
    note_odd("集结", f"等新旗消失并出现修理超时  {weak_flag_hint(matcher, grab(rect))}")
    halt_timeout("集结")
    return False


def wait_hit_in(matcher: Matcher, rect, name: str, region, timeout: float, thresh: float | None = None) -> Hit | None:
    deadline = time.time() + timeout
    last = None
    t = thresh if thresh is not None else config.thresh_for(name)
    while time.time() < deadline and not STOP.is_set():
        frame = grab(rect)
        last = frame
        hit = matcher.find_in(frame, name, region, t)
        mark_rois(matcher, frame)
        if hit:
            return hit
        time.sleep(config.LOOP_SLEEP)
    if last is not None:
        x, y, rw, rh = region
        crop = last[y : y + rh, x : x + rw]
        score, loc = matcher.best(crop, name) if crop.size else (0.0, (-1, -1))
        logp("邀请", f"没找到 {name}  区域{region} 最高分={score:.3f}@{loc}  阈值={t:.2f}")
    return None


def invite_allies(matcher: Matcher, rect, do_click: bool) -> None:
    """新旗出现后：team.png → team_hud → invite.png → invite_hud → invite_all → back。失败则跳过，仍去等旗。"""
    logp("邀请", "开始拉人：点右侧组队入口")
    frame = grab(rect)
    team = wait_hit_in(matcher, rect, "team_btn", team_btn_region(matcher, frame), config.PANEL_WAIT)
    if not team:
        logp("邀请", "没有 team.png（组队入口），跳过拉人")
        return
    act(rect, team, do_click, "打开组队")
    invite = wait_hit(matcher, rect, "invite", config.PANEL_WAIT)
    if not invite:
        logp("邀请", "team_hud 里没有 invite.png，点返回")
        back = wait_hit(matcher, rect, "back", 4.0)
        if back:
            click_until_gone(matcher, rect, back, "back", do_click, "返回")
        return
    act(rect, invite, do_click, "打开邀请")
    all_btn = wait_hit(matcher, rect, "invite_all", config.PANEL_WAIT)
    if not all_btn:
        logp("邀请", "invite_hud 里没有邀请全部")
        back = wait_hit(matcher, rect, "back", 4.0)
        if back:
            click_until_gone(matcher, rect, back, "back", do_click, "返回")
        return
    if not click_until_gone(matcher, rect, all_btn, "invite_all", do_click, "邀请全部"):
        return
    time.sleep(0.4)
    back = wait_hit(matcher, rect, "back", config.PANEL_WAIT)
    if not back:
        logp("邀请", "回到 team_hud 后没有 back.png")
        return
    if not click_until_gone(matcher, rect, back, "back", do_click, "返回地图"):
        return
    logp("邀请", "拉人结束，开始等旗消失")


def press_esc(rect, why: str) -> None:
    logp("按键", f"ESC  {why}")
    with hold_foreground(rect) as ok:
        if not ok:
            log("游戏窗口没到前台，仍尝试 ESC")
        screen_key(0x1B)
    time.sleep(0.7)


def mail_panel_open(matcher: Matcher, frame) -> bool:
    return bool(
        matcher.find(frame, "win", config.WIN_THRESH)
        or matcher.find(frame, "loot", config.LOOT_THRESH)
        or matcher.find(frame, "new", config.NEW_THRESH)
    )


def close_mail_panel(matcher: Matcher, rect, do_click: bool, why: str, opened: bool = False) -> bool:
    """最多 ESC 两次，且第二次必须还能看到邮件痕迹。关了就不按，避免退出框。"""
    if not do_click:
        return True
    frame = grab(rect)
    search = matcher.find(frame, "search", config.SEARCH_THRESH)
    go = matcher.find(frame, "search_go")
    mailish = mail_panel_open(matcher, frame)
    if (search or go) and not mailish:
        return True
    if not mailish and not opened:
        return bool(search or go)

    esc_used = 0
    press_esc(rect, why)
    esc_used += 1
    time.sleep(0.4)
    deadline = time.time() + 2.5
    while time.time() < deadline and not STOP.is_set():
        frame = grab(rect)
        search = matcher.find(frame, "search", config.SEARCH_THRESH)
        go = matcher.find(frame, "search_go")
        mailish = mail_panel_open(matcher, frame)
        mark_rois(matcher, frame)
        if not mailish:
            if search or go:
                logp("邮件", "面板已关，搜寻回来了")
            else:
                logp("邮件", "邮件痕迹没了，不再 ESC")
            return True
        if esc_used >= 2:
            break
        press_esc(rect, f"{why}（邮件还开着，再关一次）")
        esc_used += 1
        time.sleep(0.5)
    frame = grab(rect)
    mailish = mail_panel_open(matcher, frame)
    if mailish:
        logp("邮件", "按了两次 ESC 邮件还在，停手，避免再按出退出框")
    return not mailish


def check_mail_success(matcher: Matcher, rect, do_click: bool) -> bool:
    """打完后点邮件箱。第一条同时有 WIN+NEW+LOOT 算成功。
    已知误判：若本来就有未读且带奖励的邮件，会当成成功。
    """
    mail = wait_hit(matcher, rect, "mail", config.PANEL_WAIT, config.MAIL_THRESH)
    if not mail:
        log("找不到邮件箱")
        return False
    if do_click:
        act(rect, mail, do_click, "开邮件箱")
    else:
        log("DRY  开邮件箱（不点）")
    deadline = time.time() + 6.0
    frame = None
    win = None
    while time.time() < deadline and not STOP.is_set():
        frame = grab(rect)
        win = matcher.find(frame, "win", config.WIN_THRESH)
        if win:
            break
        time.sleep(config.LOOP_SLEEP)
    if frame is None or win is None:
        log("邮件里没有胜利标，本轮失败")
        close_mail_panel(matcher, rect, do_click, "关邮件", opened=True)
        return False
    news = matcher.find_all(frame, "new", config.NEW_THRESH)
    loots = matcher.find_all(frame, "loot", config.LOOT_THRESH)
    # 只认第一条：取最靠上的胜利标，同一行再找未读和宝箱
    wins = matcher.find_all(frame, "win", config.WIN_THRESH)
    first = min(wins, key=lambda h: h.y1)
    def same_row(h: Hit) -> bool:
        return abs(h.center[1] - first.center[1]) <= config.MAIL_ROW_DY and h.y1 >= first.y1 - 20
    has_new = any(same_row(h) for h in news)
    has_loot = any(same_row(h) for h in loots)
    ok = has_new and has_loot
    log(
        f"第一条邮件 win={first.score:.3f}@{first.center}  "
        f"NEW={'有' if has_new else '无'}  LOOT={'有' if has_loot else '无'}  -> {'成功' if ok else '失败'}"
    )
    save_debug(matcher, frame, [first] + [h for h in news + loots if same_row(h)])
    close_mail_panel(matcher, rect, do_click, "关邮件", opened=True)
    return ok


def mark_rois(matcher: Matcher, frame) -> None:
    """左/右 HUD 和船队栏是对齐出来的范围，不是匹配结果，平时不画框。"""
    return


def find_atk(matcher: Matcher, frame) -> Hit | None:
    """只认船队栏 hud_ship 里的 ATK。全屏匹配容易把别的图标当成战斗中。"""
    return matcher.find_in(frame, "atk", fleet_hud_region(matcher, frame), config.ATK_THRESH)


def scene_flags(matcher: Matcher, frame) -> dict[str, Hit | None]:
    flags = {
        "search": matcher.find(frame, "search", config.SEARCH_THRESH),
        "search_go": matcher.find(frame, "search_go"),
        "goal0_atk": matcher.find(frame, "goal0_atk"),
        "atk": find_atk(matcher, frame),
        "repair": matcher.find(frame, "repair"),
    }
    mark_rois(matcher, frame)
    return flags


def describe_scene(flags: dict[str, Hit | None]) -> str:
    parts = []
    for name, hit in flags.items():
        if hit:
            parts.append(f"{name}有({hit.score:.2f}@{hit.center})")
        else:
            parts.append(f"{name}无")
    return "  ".join(parts)


def refill_ap(matcher: Matcher, rect, do_click: bool) -> bool:
    """点集结或攻击后若弹出获得更多，点使用再点关闭。没弹出就返回 False。"""
    more = wait_hit(matcher, rect, "ap_more", 2.0)
    if not more:
        return False
    logp("体力", f"看到获得更多  分={more.score:.3f} {more.center}")
    use = wait_hit(matcher, rect, "use2", config.PANEL_WAIT)
    if not use:
        logp("体力", "没有补充使用")
        return False
    act(rect, use, do_click, "补充使用")
    close = wait_hit(matcher, rect, "close_btn", config.PANEL_WAIT)
    if not close:
        logp("体力", "补充后没有关闭")
        return True
    if not click_until_gone(matcher, rect, close, "close_btn", do_click, "关闭补充"):
        return False
    logp("体力", "已补充并关闭")
    return True


def click_and_confirm_combat(matcher: Matcher, rect, do_click: bool) -> str:
    """点攻擊后确认是否真开战。
    combat=船队栏连续看到atk；fled=船跑了/按钮没了也没开战；miss=按钮还在点不中。
    """
    for attempt in range(1, 4):
        if STOP.is_set():
            return "stop"
        btn = wait_hit(matcher, rect, "goal0_atk", config.SHIP_WAIT if attempt == 1 else 3.0)
        if not btn:
            frame = grab(rect)
            flags = scene_flags(matcher, frame)
            logp("攻击", f"没找到攻擊按钮  {describe_scene(flags)}")
            if flags["search"] and not flags["goal0_atk"]:
                logp("攻击", "判定：船跑了或跳转失败（放大镜在，攻擊按钮不在）")
                return "fled"
            logp("攻击", "判定：超时没点到攻击")
            return "miss"
        logp("攻击", f"第{attempt}次点攻擊  分={btn.score:.3f} 画面{btn.center}")
        act(rect, btn, do_click, "爪牙攻擊")
        if refill_ap(matcher, rect, do_click):
            logp("攻击", "体力不足，已补充，再点攻击")
            continue
        atk_streak = 0
        t0 = time.time()
        last_note = ""
        while time.time() - t0 < config.ATK_CLICK_CONFIRM and not STOP.is_set():
            frame = grab(rect)
            flags = scene_flags(matcher, frame)
            note = describe_scene(flags)
            if note != last_note:
                logp("开战确认", f"点后{time.time() - t0:.1f}s  {note}")
                last_note = note
            if flags["atk"]:
                atk_streak += 1
                if atk_streak >= config.ATK_STREAK:
                    logp("开战确认", f"船队栏连续{atk_streak}帧看到atk，确认已开战")
                    return "combat"
            else:
                atk_streak = 0
            time.sleep(0.35)
        frame = grab(rect)
        flags = scene_flags(matcher, frame)
        if flags["atk"]:
            logp("开战确认", f"看到atk  {describe_scene(flags)}")
            return "combat"
        if flags["goal0_atk"]:
            logp("攻击", "攻擊按钮还在，这次没点中（船可能挪了），再点")
            continue
        logp("攻击", f"攻擊按钮消失，但船队栏还没有atk  {describe_scene(flags)}")
        extra = time.time() + 6.0
        while time.time() < extra and not STOP.is_set():
            frame = grab(rect)
            flags = scene_flags(matcher, frame)
            if flags["atk"]:
                logp("开战确认", f"补等到atk  {describe_scene(flags)}")
                return "combat"
            if flags["repair"]:
                note_odd("开战确认", f"没看到atk但出现修理，不当成这艘已打完  {describe_scene(flags)}")
            if flags["search"] and not flags["goal0_atk"]:
                logp("攻击", f"放大镜回来了，判定船跑了  {describe_scene(flags)}")
                return "fled"
            time.sleep(0.4)
        logp("攻击", "按钮没了、也一直没有atk，判定船跑了")
        return "fled"
    logp("攻击", "连点三次攻擊按钮仍在，放弃本轮")
    return "miss"


def wait_fight_over(matcher: Matcher, rect) -> bool:
    """点攻击后等打完。有 atk：消失并且出现修理。没 atk：才单独等修理。都不得短于平均耗时。"""
    t = calibrate.timeouts()
    floor = t["median"] if t["samples"] >= 1 else config.DEFAULT_AVG_WAIT
    logp(
        "战斗",
        f"开始等打完  校准样本{int(t['samples'])} 平均{t['median']:.1f}s  "
        f"出场等待{t['appear_wait']:.0f}s 最早平均前{config.AVG_EARLY_SEC:.0f}s 超时{t['gone_wait']:.0f}s",
    )
    t0 = time.time()
    appear_s: float | None = None
    last_beat = 0.0
    while time.time() - t0 < t["appear_wait"] and not STOP.is_set():
        frame = grab(rect)
        elapsed = time.time() - t0
        hit = find_atk(matcher, frame)
        repair = find_repair(matcher, frame)
        if elapsed - last_beat >= 5.0:
            logp(
                "战斗",
                f"已等{elapsed:.0f}s  "
                f"{'atk有' if hit else 'atk无'}"
                f"{f'({hit.score:.2f}@{hit.center})' if hit else ''}  "
                f"{'修理有' if repair else '修理无'}",
            )
            last_beat = elapsed
        if hit:
            appear_s = elapsed
            logp("战斗", f"船队栏出现atk  分={hit.score:.3f} 位置{hit.center}  开战{appear_s:.1f}s后")
            break
        time.sleep(0.4)
    if appear_s is None:
        note_odd("战斗", "没检测到atk，改用修理当备用信号")
        noted_early = False
        while time.time() - t0 < t["gone_wait"] and not STOP.is_set():
            elapsed = time.time() - t0
            frame = grab(rect)
            repair = find_repair(matcher, frame)
            if repair and not avg_ready(elapsed, floor):
                if not noted_early:
                    note_odd(
                        "战斗",
                        f"没atk，修理已在，但未到平均前{config.AVG_EARLY_SEC:.0f}s"
                        f"（{max(0.0, floor - config.AVG_EARLY_SEC):.0f}s），继续等",
                    )
                    noted_early = True
            elif repair:
                logp("结束", f"没atk，修理作为信号  分={repair.score:.3f} {repair.center}  耗时{elapsed:.0f}s")
                _finish_fight(None, elapsed, "repair")
                return True
            time.sleep(0.6)
        note_odd("战斗", "没atk，等修理超时，未写入校准")
        halt_timeout("战斗")
        return False
    gone_since: float | None = None
    noted = ""
    while time.time() - t0 < t["gone_wait"] and not STOP.is_set():
        frame = grab(rect)
        elapsed = time.time() - t0
        atk = find_atk(matcher, frame)
        repair = find_repair(matcher, frame)
        if elapsed - last_beat >= 5.0:
            logp(
                "战斗",
                f"已等{elapsed:.0f}s  "
                f"{'atk有' if atk else 'atk无'}"
                f"{f'({atk.score:.2f}@{atk.center})' if atk else ''}  "
                f"{'修理有' if repair else '修理无'}",
            )
            last_beat = elapsed
        if atk:
            gone_since = None
            noted = ""
        elif gone_since is None:
            gone_since = time.time()
            logp("战斗", f"atk消失，开始确认（需连续{t['gone_confirm']:.1f}s）")
        elif time.time() - gone_since >= t["gone_confirm"]:
            late = floor + 15.0
            if repair and avg_ready(elapsed, floor):
                logp("结束", f"atk消失且出现修理  分={repair.score:.3f} {repair.center}  耗时{elapsed:.0f}s")
                _finish_fight(appear_s, elapsed, "atk_and_repair")
                return True
            if not repair and elapsed >= late:
                note_odd("战斗", f"atk已连续消失且没有修理，已到平均+15s（{late:.0f}s），按打完处理")
                _finish_fight(appear_s, elapsed, "atk_gone_no_repair")
                return True
            if not avg_ready(elapsed, floor):
                msg = (
                    f"atk已消失，未到平均前{config.AVG_EARLY_SEC:.0f}s"
                    f"（{max(0.0, floor - config.AVG_EARLY_SEC):.0f}s），继续等"
                )
            elif not repair:
                msg = f"atk已连续消失，没有修理，等到平均+15s（{late:.0f}s）"
            else:
                msg = ""
            if msg and noted != msg:
                note_odd("战斗", msg)
                noted = msg
        time.sleep(0.4)
    note_odd("战斗", "等atk消失并出现修理超时，未写入校准")
    halt_timeout("战斗")
    return False


def _finish_fight(appear_s: float | None, duration_s: float, reason: str) -> None:
    nxt = calibrate.record_goal0(appear_s, duration_s, reason)
    logp(
        "结束",
        f"信号={reason}  耗时{duration_s:.1f}s  平均{nxt['median']:.0f}s 超时{nxt['gone_wait']:.0f}s",
    )


def repair_first(matcher: Matcher, rect, do_click: bool) -> bool:
    """每个功能每一轮开始：有修理就先修。False 表示该停。"""
    repair = find_repair(matcher, grab(rect))
    if not repair:
        return True
    logp("修理", f"开始前先修理  分={repair.score:.3f} {repair.center}")
    return click_until_gone(matcher, rect, repair, "repair", do_click, "自动修理")


def open_search(matcher: Matcher, rect, do_click: bool) -> Hit | None:
    """点放大镜直到黄搜寻出现。面板已开则不再点放大镜。修理在每轮开头统一做。"""
    frame = grab(rect)
    already = matcher.find(frame, "search_go")
    if already:
        logp("搜寻", f"面板已开 search_go={already.score:.3f} {already.center}")
        return already

    search = wait_hit(matcher, rect, "search", config.PANEL_WAIT, config.SEARCH_THRESH)
    if not search:
        frame = grab(rect)
        if mail_panel_open(matcher, frame):
            logp("搜寻", "找不到放大镜，邮件面板还开着，先关掉")
            close_mail_panel(matcher, rect, do_click, "搜寻前关邮件")
            search = wait_hit(matcher, rect, "search", 4.0, config.SEARCH_THRESH)
        if not search:
            halt("搜寻", "找不到搜寻放大镜，停止")
            return None
    go = None
    for _ in range(3):
        act(rect, search, do_click, "开搜寻")
        go = wait_hit(matcher, rect, "search_go", 3.5)
        if go:
            return go
        log("搜寻面板没开出来，再点一次放大镜")
        search = wait_hit(matcher, rect, "search", 2.0, config.SEARCH_THRESH) or search
    log("找不到黄搜寻")
    halt("搜寻", "黄搜寻试了3次仍没有，停止")
    return None


def run_goal0(matcher: Matcher, rect, do_click: bool, count: int) -> None:
    """爪牙·至高教：开搜索 → 点爪牙页签 → 黄搜寻 → 攻擊 → 等船队栏 atk 消失。"""
    done = 0
    while (config.INFINITE or done < count) and not STOP.is_set():
        label = f"第 {done + 1} 次" if config.INFINITE else f"第 {done + 1}/{count} 次"
        logp("目标0", label)
        if not repair_first(matcher, rect, do_click):
            break
        go = open_search(matcher, rect, do_click)
        if not go:
            break
        tab = require_hit(matcher, rect, "tab_claw", config.PANEL_WAIT, "目标0")
        if not tab:
            break
        act(rect, tab, do_click, "爪牙页签")
        go = wait_hit(matcher, rect, "search_go", config.PANEL_WAIT) or go
        logp("搜寻", "不拖等级（默认30），点黄搜寻跳转")
        if not click_until_gone(matcher, rect, go, "search_go", do_click, "确认搜寻"):
            break
        how = click_and_confirm_combat(matcher, rect, do_click)
        if how == "stop":
            break
        if how == "fled":
            logp("目标0", "船跑了或没跳到，本轮不算，重新搜寻")
            continue
        if how == "miss":
            logp("目标0", "攻击没点上，重新搜寻")
            continue
        if not wait_fight_over(matcher, rect):
            logp("目标0", "没等到打完，停止开下一轮搜寻")
            break
        repair = wait_hit(matcher, rect, "repair", config.PANEL_WAIT)
        if repair:
            act(rect, repair, do_click, "自动修理")
        else:
            logp("结束", "找不到修理按钮，跳过")
        done += 1
        logp("目标0", f"本轮完成 {_quota(done, count)}")
        time.sleep(1.0)
    log(f"目标0 结束，完成 {_quota(done, count)}")


def click_red_until_yellow(matcher: Matcher, rect, do_click: bool) -> Hit | None:
    """点红集结后 5s 内要看到黄确认；看不到就当没点到，再点红。"""
    for attempt in range(1, 4):
        if STOP.is_set():
            return None
        red = wait_hit(matcher, rect, "rally_red", config.RALLY_RED_WAIT)
        if not red:
            logp("贡品", f"第{attempt}次 {config.RALLY_RED_WAIT:.0f}s内没看到红集结")
            return None
        logp("贡品", f"第{attempt}次点红集结  分={red.score:.3f} 画面{red.center}")
        act(rect, red, do_click, "红集结")
        if refill_ap(matcher, rect, do_click):
            logp("贡品", "体力不足，已补充，再点集结")
            continue
        yellow = wait_hit(matcher, rect, "rally_yellow", config.RALLY_RED_WAIT)
        if yellow:
            logp("贡品", f"已出黄确认  分={yellow.score:.3f} {yellow.center}")
            return yellow
        logp("贡品", f"{config.RALLY_RED_WAIT:.0f}s内没有黄确认，判定没点到，再点红集结")
    logp("贡品", "红集结连点三次仍无黄确认")
    return None


def run_goal1(matcher: Matcher, rect, do_click: bool, count: int) -> None:
    done = 0
    while (config.INFINITE or done < count) and not STOP.is_set():
        logp("目标1", f"第 {done + 1} 次" if config.INFINITE else f"第 {done + 1}/{count} 次")
        if not repair_first(matcher, rect, do_click):
            break
        go = open_search(matcher, rect, do_click)
        if not go:
            break
        tab = require_hit(matcher, rect, "tab_tribute", config.PANEL_WAIT, "贡品")
        if not tab:
            break
        act(rect, tab, do_click, "贡品船")
        go = require_hit(matcher, rect, "search_go", config.PANEL_WAIT, "贡品")
        if not go:
            break
        drag_level(rect, go, do_click)
        go = matcher.find(grab(rect), "search_go") or go
        if not click_until_gone(matcher, rect, go, "search_go", do_click, "确认搜寻"):
            break
        time.sleep(1.0)
        pre = grab(rect)
        map_flags = flag_centers(matcher, pre)
        logp(
            "集结",
            f"打开设置前，左侧船队栏的旗 {map_flags if map_flags else '无'}  {weak_flag_hint(matcher, pre)}",
        )
        yellow = click_red_until_yellow(matcher, rect, do_click)
        if not yellow:
            halt("贡品", "红集结或黄确认试了3次仍没有，停止")
            break
        ensure_rally_time(matcher, rect, grab(rect), do_click)
        yellow = wait_hit(matcher, rect, "rally_yellow", config.RALLY_RED_WAIT)
        if not yellow:
            halt("贡品", "找不到黄确认，停止")
            break
        logp("贡品", f"点黄确认 rally_confirm  分={yellow.score:.3f} {yellow.center}")
        if not click_until_gone(matcher, rect, yellow, "rally_yellow", do_click, "黄确认集结"):
            break
        finished = wait_flag_gone(matcher, rect, map_flags, do_click)
        if STOP.is_set():
            break
        if config.MAIL_COUNT:
            ok = check_mail_success(matcher, rect, do_click)
        else:
            ok = finished
            logp("邮件", "邮件计数已停用，本轮按集结是否走完计")
        if ok:
            done += 1
            log(f"本轮成功，完成 {_quota(done, count)}")
        else:
            log(f"本轮未计成功，仍是 {_quota(done, count)}")
    log(f"目标1 结束，完成 {_quota(done, count)}")


def run_goal4(matcher: Matcher, rect, do_click: bool, count: int) -> None:
    """方舟：仓储 → 方舟券 → 使用 → 之后和贡品船的红集结一样。"""
    done = 0
    while (config.INFINITE or done < count) and not STOP.is_set():
        logp("目标4", f"第 {done + 1} 次" if config.INFINITE else f"第 {done + 1}/{count} 次")
        if not repair_first(matcher, rect, do_click):
            break
        storage = require_hit(matcher, rect, "storage", config.PANEL_WAIT, "方舟")
        if not storage:
            break
        act(rect, storage, do_click, "仓储")
        ticket = require_hit(matcher, rect, "ticket_ark", config.PANEL_WAIT, "方舟")
        if not ticket:
            break
        act(rect, ticket, do_click, "方舟券")
        use = require_hit(matcher, rect, "use", config.PANEL_WAIT, "方舟")
        if not use:
            break
        if not click_until_gone(matcher, rect, use, "use", do_click, "使用"):
            break
        time.sleep(1.0)
        pre = grab(rect)
        map_flags = flag_centers(matcher, pre)
        logp(
            "集结",
            f"打开设置前，左侧船队栏的旗 {map_flags if map_flags else '无'}  {weak_flag_hint(matcher, pre)}",
        )
        yellow = click_red_until_yellow(matcher, rect, do_click)
        if not yellow:
            halt("方舟", "红集结或黄确认试了3次仍没有，停止")
            break
        ensure_rally_time(matcher, rect, grab(rect), do_click)
        yellow = wait_hit(matcher, rect, "rally_yellow", config.RALLY_RED_WAIT)
        if not yellow:
            halt("方舟", "找不到黄确认，停止")
            break
        logp("方舟", f"点黄确认  分={yellow.score:.3f} {yellow.center}")
        if not click_until_gone(matcher, rect, yellow, "rally_yellow", do_click, "黄确认集结"):
            break
        finished = wait_flag_gone(matcher, rect, map_flags, do_click)
        if STOP.is_set():
            break
        if config.MAIL_COUNT:
            ok = check_mail_success(matcher, rect, do_click)
        else:
            ok = finished
            logp("邮件", "邮件计数已停用，本轮按集结是否走完计")
        if ok:
            done += 1
            log(f"本轮成功，完成 {_quota(done, count)}")
        else:
            log(f"本轮未计成功，仍是 {_quota(done, count)}")
    log(f"目标4 结束，完成 {_quota(done, count)}")


def run_goal5(matcher: Matcher, rect, do_click: bool, count: int) -> None:
    """金币活动：点 event1（不消失），等红色攻击，再跟爪牙一样等 atk 退出。"""
    done = 0
    while (config.INFINITE or done < count) and not STOP.is_set():
        logp("目标5", f"第 {done + 1} 次" if config.INFINITE else f"第 {done + 1}/{count} 次")
        if not repair_first(matcher, rect, do_click):
            break
        event = wait_hit(matcher, rect, "event1", config.PANEL_WAIT)
        if not event:
            logp("金币", "找不到 event1")
            break
        attack = None
        for attempt in range(1, 4):
            if STOP.is_set():
                return
            act(rect, event, do_click, "金币活动" if attempt == 1 else "金币活动 再点")
            attack = wait_hit(matcher, rect, "goal0_atk", 5.0)
            if attack:
                break
            logp("金币", f"第{attempt}次点 event1 后 5 秒没有红色攻击")
            event = matcher.find(grab(rect), "event1") or event
        if not attack:
            logp("金币", "点了3次仍没有红色攻击，当作完成")
            break
        tele = matcher.find(grab(rect), "teleport")
        if tele:
            logp("金币", f"传送在 {tele.center}，不点")
        landed = False
        for attempt in range(1, 4):
            if STOP.is_set():
                return
            current = attack if attempt == 1 else wait_hit(matcher, rect, "goal0_atk", 3.0)
            if not current:
                logp("金币", "攻击按钮已经不在")
                landed = True
                break
            act(rect, current, do_click, "红色攻击" if attempt == 1 else "红色攻击 再点")
            if refill_ap(matcher, rect, do_click):
                logp("金币", "体力不足，已补充，再点攻击")
                continue
            time.sleep(0.6)
            if matcher.find(grab(rect), "goal0_atk") is None:
                landed = True
                break
            logp("金币", f"第{attempt}次后攻击按钮还在")
        if not landed:
            logp("金币", "攻击点了3次还在，停止")
            halt("金币", "红色攻击试了3次仍在，停止")
            break
        if not wait_fight_over(matcher, rect):
            logp("金币", "没等到 atk 退出，停止下一轮")
            break
        done += 1
        logp("目标5", f"atk 已退出，完成 {_quota(done, count)}")
    log(f"目标5 结束，完成 {_quota(done, count)}")


def _thumb_until_good1(matcher: Matcher, rect, do_click: bool) -> Hit | None:
    """点一个点赞。出现 good1 才算点中。另一个 good 还在不算没点到。"""
    clicked = 0
    for attempt in range(1, 4):
        if STOP.is_set():
            return None
        good = wait_hit(matcher, rect, "good", 2.0 if attempt > 1 else config.PANEL_WAIT)
        if not good:
            logp("祈祷船", f"第{attempt}次没有点赞")
            break
        act(rect, good, do_click, "点赞" if attempt == 1 else "点赞 再点")
        clicked += 1
        good1 = wait_hit(matcher, rect, "good1", config.PANEL_WAIT)
        if good1:
            logp("祈祷船", f"点赞第{attempt}次后出现 good1  {good1.score:.3f} {good1.center}")
            return good1
        logp("祈祷船", f"点赞第{attempt}次后没有 good1")
    if clicked < 3:
        return None
    logp("祈祷船", "点赞点了3次仍没有 good1，停止")
    STOP.set()
    import overlay

    overlay.hide()
    cue_stop()
    return None


def run_goal2(matcher: Matcher, rect, do_click: bool, count: int) -> None:
    """100级祈祷船：点100，若先出100b就先点它，再点红色攻击。atk 确认开打，点赞变成 good1 后关闭，修理确认。"""
    done = 0
    while (config.INFINITE or done < count) and not STOP.is_set():
        logp("目标2", f"第 {done + 1} 次" if config.INFINITE else f"第 {done + 1}/{count} 次")
        if not repair_first(matcher, rect, do_click):
            break
        mark = wait_hit(matcher, rect, "pray100", config.PANEL_WAIT)
        if not mark:
            logp("祈祷船", "还没有 100，继续等")
            continue
        act(rect, mark, do_click, "100")
        opened = False
        for attempt in range(1, 4):
            if STOP.is_set():
                return
            attack = None
            banner = None
            deadline = time.time() + (5.0 if attempt > 1 else config.PANEL_WAIT)
            while time.time() < deadline and not STOP.is_set():
                frame = grab(rect)
                attack = matcher.find(frame, "attack")
                if attack:
                    break
                banner = matcher.find(frame, "pray100b")
                if banner:
                    break
                time.sleep(0.3)
            if banner and not attack:
                logp("祈祷船", f"100 和港湾重叠，先点 100b  分={banner.score:.3f} {banner.center}")
                act(rect, banner, do_click, "100b")
                attack = wait_hit(matcher, rect, "attack", 5.0)
            if not attack:
                logp("祈祷船", f"第{attempt}次没有红色攻击")
                break
            tele = matcher.find(grab(rect), "teleport")
            if tele:
                logp("祈祷船", f"传送在 {tele.center}，不点")
            act(rect, attack, do_click, "红色攻击" if attempt == 1 else "红色攻击 再点")
            streak = 0
            t0 = time.time()
            while time.time() - t0 < config.ATK_CLICK_CONFIRM and not STOP.is_set():
                if find_atk(matcher, grab(rect)):
                    streak += 1
                    if streak >= config.ATK_STREAK:
                        opened = True
                        break
                else:
                    streak = 0
                time.sleep(0.35)
            if opened:
                logp("祈祷船", "船队栏出现 atk，确认开打")
                break
            logp("祈祷船", "还没有 atk，攻击可能没点到")
        if not opened:
            logp("祈祷船", "没确认开打，本轮重来")
            continue
        fight_wait = calibrate.timeouts()["gone_wait"]
        good = wait_hit(matcher, rect, "good", fight_wait)
        if not good:
            logp("祈祷船", "没等到 good")
            note_odd("祈祷船", "等点赞超时，未写入本轮")
            halt_timeout("祈祷船")
            break
        if _thumb_until_good1(matcher, rect, do_click) is None:
            break
        frame = grab(rect)
        if find_atk(matcher, frame) or matcher.find(frame, "pray100"):
            logp("祈祷船", "good1 已出现，但 atk 或 100 还在")
        else:
            logp("祈祷船", "good1 已出现，atk 和 100 已消失")
        close = require_hit(matcher, rect, "close_btn", config.PANEL_WAIT, "祈祷船")
        if not close:
            break
        if not click_until_gone(matcher, rect, close, "close_btn", do_click, "关闭"):
            break
        repair = require_hit(matcher, rect, "repair", config.PANEL_WAIT, "祈祷船")
        if not repair:
            break
        act(rect, repair, do_click, "自动修理")
        done += 1
        logp("目标2", f"修理确认，完成 {_quota(done, count)}")
    log(f"目标2 结束，完成 {_quota(done, count)}")


HUNT_AREAS = (
    ("hunt_area1", "斯芬克斯"),
    ("hunt_area2", "坎沃"),
    ("hunt_area3", "克鲁格"),
    ("hunt_area4", "塞尔诺"),
)


def _map_cursor(rect, matcher: Matcher | None = None, frame=None) -> tuple[int, int]:
    """星图空白：靠左上，不要甩到屏幕正中。左 HUD 先不用。"""
    return rect.left + 360, rect.top + 220


def wheel_back(rect, notches: int = 1, park: bool = True, matcher: Matcher | None = None, frame=None) -> None:
    with hold_foreground(rect):
        if park:
            sx, sy = _map_cursor(rect, matcher, frame)
            screen_move(sx, sy)
            time.sleep(0.05)
        for _ in range(max(0, int(notches))):
            if STOP.is_set():
                return
            screen_wheel(-1)
            time.sleep(config.WHEEL_PAUSE)


def star_hud(matcher: Matcher, frame):
    return {
        "collection": matcher.find(frame, "collection"),
        "starview_1": matcher.find(frame, "starview_1"),
        "starview_2": matcher.find(frame, "starview_2"),
    }


def wait_star_hud(matcher: Matcher, rect, extra_notches: int = 0) -> bool:
    """后滚直到收藏+两个星图图标都在，再额外后滚 extra 格。"""
    parked = False
    for n in range(config.WHEEL_MAX + 1):
        if STOP.is_set():
            return False
        frame = grab(rect)
        flags = star_hud(matcher, frame)
        mark_rois(matcher, frame)
        ready = all(flags.values())
        if ready:
            bits = "  ".join(f"{k}={v.score:.2f}@{v.center}" for k, v in flags.items() if v)
            logp("巡逻", f"星图HUD齐  {bits}")
            if extra_notches:
                logp("巡逻", f"再后滚 {extra_notches} 格")
                wheel_back(rect, extra_notches, park=not parked, matcher=matcher, frame=frame)
            return True
        if n >= config.WHEEL_MAX:
            break
        logp("巡逻", f"后滚找星图HUD  {n + 1}/{config.WHEEL_MAX}  {describe_scene(flags)}")
        wheel_back(rect, 1, park=not parked, matcher=matcher, frame=frame)
        parked = True
    logp("巡逻", "滚了最多次仍没有收藏+星图图标")
    return False


def find_ship_icons(matcher: Matcher, frame) -> list[Hit]:
    hits = matcher.find_all(frame, "ship_icon", config.SHIP_ICON_THRESH)
    return _unique_hits(hits, d=18)


def log_ship_hits(hits: list[Hit], why: str) -> None:
    if not hits:
        logp("船标", f"{why}  无  阈值={config.SHIP_ICON_THRESH:.2f}")
        return
    bits = "  ".join(f"{h.score:.3f}@{h.center}" for h in hits[:12])
    logp("船标", f"{why}  {len(hits)}个  阈值={config.SHIP_ICON_THRESH:.2f}  {bits}")


_LVL_NEEDLES: dict[int, list] | None = None


def level_needles() -> dict[int, list]:
    global _LVL_NEEDLES
    if _LVL_NEEDLES is not None:
        return _LVL_NEEDLES
    groups: dict[int, list] = {}
    folder = config.LVL_TPL
    if os.path.isdir(folder):
        for name in os.listdir(folder):
            if not name.startswith("lvl_") or not name.endswith(".png"):
                continue
            head = name.split("_", 2)
            if len(head) < 2 or not head[1].isdigit():
                continue
            im = cv2.imread(os.path.join(folder, name), cv2.IMREAD_GRAYSCALE)
            if im is None:
                continue
            groups.setdefault(int(head[1]), []).append(im)
    _LVL_NEEDLES = groups
    return groups


def _bin_lvl(nd: np.ndarray) -> np.ndarray:
    return np.where(nd >= config.LVL_GRAY, 255, 0).astype(np.uint8)


def _shift_lvl(src: np.ndarray, dx: int, dy: int) -> tuple[np.ndarray, np.ndarray]:
    canvas = np.zeros_like(src)
    valid = np.zeros(src.shape, np.bool_)
    h, w = src.shape
    y0, y1 = max(0, dy), min(h, h + dy)
    x0, x1 = max(0, dx), min(w, w + dx)
    sy, sx = max(0, -dy), max(0, -dx)
    canvas[y0:y1, x0:x1] = src[sy:sy + (y1 - y0), sx:sx + (x1 - x0)]
    valid[y0:y1, x0:x1] = True
    return canvas, valid


def _align_lvl(src: np.ndarray, dst: np.ndarray, rad: int) -> tuple[int, int]:
    best = (-1.0, 0, 0)
    for dy in range(-rad, rad + 1):
        for dx in range(-rad, rad + 1):
            moved, valid = _shift_lvl(src, dx, dy)
            if not valid.any():
                continue
            score = float(np.mean(moved[valid] == dst[valid]))
            if score > best[0]:
                best = (score, dx, dy)
    return best[1], best[2]


class _KeyPair:
    def __init__(self, bright, dark, cells: list[tuple[int, int, int]]):
        self.bright = bright
        self.dark = dark
        self.cells = cells


_KEY_PAIRS: dict[tuple[int, int, int, int], _KeyPair | None] = {}


def _key_pair(groups: dict[int, list], lv_a: int, lv_b: int) -> _KeyPair | None:
    """按亮的比例挑关键格。样本不够就返回 None。"""
    if lv_a > lv_b:
        lv_a, lv_b = lv_b, lv_a
    needles_a = groups.get(lv_a) or []
    needles_b = groups.get(lv_b) or []
    key = (lv_a, lv_b, len(needles_a), len(needles_b))
    if key in _KEY_PAIRS:
        return _KEY_PAIRS[key]
    pair = None
    if len(needles_a) >= 2 and len(needles_b) >= 2:
        ref = _bin_lvl(needles_a[0])
        ratios = []
        counts = []
        for needles in (needles_a, needles_b):
            acc = np.zeros(ref.shape, np.float32)
            cnt = np.zeros(ref.shape, np.float32)
            for nd in needles:
                b = _bin_lvl(nd)
                if b.shape != ref.shape:
                    continue
                dx, dy = _align_lvl(b, ref, config.LVL_KEY_SHIFT)
                moved, valid = _shift_lvl(b, dx, dy)
                acc[valid] += (moved[valid] > 0).astype(np.float32)
                cnt[valid] += 1
            ratio = np.zeros(ref.shape, np.float32)
            ok = cnt > 0
            ratio[ok] = acc[ok] / cnt[ok]
            ratios.append(ratio)
            counts.append(cnt)
        pa, pb = ratios
        ca, cb = counts
        both = (ca >= 2) & (cb >= 2)
        gap = np.abs(pa - pb)
        ys, xs = np.where(both & (gap >= config.LVL_KEY_GAP))
        cells = []
        for y, x in zip(ys.tolist(), xs.tolist()):
            bright_lv = lv_a if pa[y, x] > pb[y, x] else lv_b
            cells.append((int(x), int(y), bright_lv))
        same = both & (gap < config.LVL_KEY_GAP)
        bright = same & (pa >= config.LVL_KEY_GAP) & (pb >= config.LVL_KEY_GAP)
        dark = same & (pa <= 1.0 - config.LVL_KEY_GAP) & (pb <= 1.0 - config.LVL_KEY_GAP)
        if len(cells) >= 3 and (bright.any() or dark.any()):
            pair = _KeyPair(bright, dark, cells)
    _KEY_PAIRS[key] = pair
    return pair


def key_vote(binary, x: int, y: int, groups: dict[int, list], lv_a: int, lv_b: int) -> tuple[int | None, str] | None:
    """分差不够时只看关键格。方法用不上返回 None。用得上返回 (改判等级或 None, 票数说明)。"""
    pair = _key_pair(groups, lv_a, lv_b)
    if pair is None:
        return None
    th, tw = pair.bright.shape
    h, w = binary.shape[:2]
    best = None
    rad = config.LVL_KEY_SHIFT
    for dy in range(-rad, rad + 1):
        for dx in range(-rad, rad + 1):
            x1, y1 = x + dx, y + dy
            if x1 < 0 or y1 < 0 or x1 + tw > w or y1 + th > h:
                continue
            window = binary[y1:y1 + th, x1:x1 + tw]
            mask = pair.bright | pair.dark
            ok = np.zeros(window.shape, np.bool_)
            ok[pair.bright] = window[pair.bright] > 0
            ok[pair.dark] = window[pair.dark] == 0
            score = float(ok[mask].mean())
            if best is None or score > best[0]:
                best = (score, window)
    if best is None:
        return None
    window = best[1]
    votes = {lv_a: 0, lv_b: 0}
    for cx, cy, bright_lv in pair.cells:
        lit = bool(window[cy, cx] > 0)
        other = lv_b if bright_lv == lv_a else lv_a
        votes[bright_lv if lit else other] += 1
    hi = max(votes[lv_a], votes[lv_b])
    lo = min(votes[lv_a], votes[lv_b])
    note = f"关键格 {lv_a} 得{votes[lv_a]}票  {lv_b} 得{votes[lv_b]}票"
    if hi - lo < 2 or hi * 3 < (hi + lo) * 2:
        return None, note
    winner = lv_a if votes[lv_a] > votes[lv_b] else lv_b
    return winner, note


def save_lvl_miss(binary, search, peaks: list[tuple[int, int, int, int, str]]) -> str:
    """没过线时留下二值匹配图：搜索范围 + 最高分位置。"""
    out_dir = os.path.join(config.PIC, "lvl", "match")
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{int((time.time() % 1) * 1_000_000):06d}"
    path = os.path.join(out_dir, f"{stamp}.png")
    vis = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
    if search is not None:
        x0, y0, x1, y1 = search
        cv2.rectangle(vis, (x0, y0), (max(x0, x1 - 1), max(y0, y1 - 1)), (0, 160, 255), 1)
    for x, y, tw, th, text in peaks:
        cv2.rectangle(vis, (x, y), (x + tw - 1, y + th - 1), (0, 0, 255), 1)
        cv2.putText(
            vis, text, (x, max(14, y - 4)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1, cv2.LINE_AA,
        )
    cv2.imwrite(path, vis)
    note_odd("巡逻", f"没有匹配到等级，图已存 pic/lvl/match/{stamp}.png")
    return path


def ship_level_near(frame, hit: Hit) -> tuple[int, float] | None:
    """查看之后整图认等级。多个命中取离这艘船最近的。返回 (等级, 分数)，没有过线的就 None。"""
    groups = level_needles()
    if not groups or frame is None or frame.size == 0:
        return None
    gray = cv2.cvtColor(frame[:, :, :3], cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    binary = np.where(gray >= config.LVL_GRAY, 255, 0).astype(np.uint8)
    h, w = binary.shape[:2]
    cx, cy = hit.center
    x0, y0 = 0, 0
    crop = binary
    if crop.size == 0:
        return None
    maps = []
    used = []
    box = (16, 16)
    for lv in sorted(groups):
        acc = None
        for nd in groups[lv]:
            if nd.shape[0] > crop.shape[0] or nd.shape[1] > crop.shape[1]:
                continue
            box = (int(nd.shape[1]), int(nd.shape[0]))
            res = cv2.matchTemplate(crop, nd, cv2.TM_CCOEFF_NORMED)
            acc = res if acc is None else np.maximum(acc, res)
        if acc is None:
            continue
        maps.append(acc)
        used.append(lv)
    if len(maps) < 2:
        save_lvl_miss(binary, None, [])
        return None
    stack = np.stack(maps, 0)
    order = np.argsort(-stack, axis=0)
    best = np.take_along_axis(stack, order[0][None], 0)[0]
    second = np.take_along_axis(stack, order[1][None], 0)[0]
    best_i = order[0]
    ys, xs = np.where((best >= config.LVL_SCORE) & ((best - second) >= config.LVL_MARGIN))
    if len(xs) == 0:
        y, x = np.unravel_index(int(np.argmax(best)), best.shape)
        lv = used[int(best_i[y, x])]
        lv2 = used[int(order[1][y, x])]
        if float(best[y, x]) >= config.LVL_SCORE:
            got = key_vote(binary, x0 + int(x), y0 + int(y), groups, lv, lv2)
            if got is not None:
                winner, note = got
                logp("巡逻", note)
                if winner is not None:
                    score = float(stack[used.index(winner), y, x])
                    logp("巡逻", f"关键格改判 {winner}（第一轮 {lv} {float(best[y, x]):.2f} / {lv2} {float(second[y, x]):.2f}）")
                    config.note_match("lvl", score)
                    return winner, score
        text = f"{lv} {float(best[y, x]):.2f}  {lv2} {float(second[y, x]):.2f}"
        tw, th = box
        save_lvl_miss(binary, None, [(int(x), int(y), tw, th, text)])
        return None
    cand = []
    for y, x in zip(ys.tolist(), xs.tolist()):
        cand.append((float(best[y, x]), used[int(best_i[y, x])], x0 + int(x) + 8, y0 + int(y) + 8))
    cand.sort(reverse=True)
    kept = []
    for sc, lv, px, py in cand:
        if any(abs(px - k[0]) < 12 and abs(py - k[1]) < 12 for k in kept):
            continue
        kept.append((px, py, sc, lv))
    nearest = min(kept, key=lambda item: abs(item[0] - cx) + abs(item[1] - cy))
    config.note_match("lvl", nearest[2])
    return nearest[3], nearest[2]


def scan_ships(matcher: Matcher | None = None, rect=None) -> None:
    if matcher is None:
        matcher = overlay.LiveMatcher()
        rect = pick_game_window()
        matcher.bind(rect)
        log(f"窗口 {rect.width}x{rect.height} at ({rect.left},{rect.top})  {rect.title!r}")
    frame = grab(rect)
    hits = find_ship_icons(matcher, frame)
    log_ship_hits(hits, "测试")
    binary = hull_binary(frame)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out = os.path.join(config.PIC, "ship", "test")
    os.makedirs(out, exist_ok=True)
    cv2.imwrite(os.path.join(out, f"{stamp}_original.png"), frame)
    cv2.imwrite(os.path.join(out, f"{stamp}_bw.png"), binary)
    cv2.imwrite(os.path.join(out, f"{stamp}_match.png"), matcher.draw(binary, hits))
    log(f"船标测试已写入 pic/ship/test/{stamp}_original.png / _bw.png / _match.png")
    overlay.push(rect, hits, [])
    save_debug(matcher, frame, hits)
    time.sleep(0.15)
    overlay.wait_dismiss(config.MARK_PREVIEW_SEC)


def ships_still(matcher: Matcher, rect, ships: list[Hit]) -> list[Hit]:
    """所有船一起等一次。每艘只配自己附近的新位置，别的船走过不算这艘在动。"""
    if not ships:
        return []
    logp("船标", f"等{config.SHIP_STILL_SEC:.0f}s看 {len(ships)} 艘是否还在原处  限{config.SHIP_STILL_PX}px")
    deadline = time.time() + config.SHIP_STILL_SEC
    while time.time() < deadline and not STOP.is_set():
        time.sleep(0.5)
    if STOP.is_set():
        return []
    frame = grab(rect)
    now = find_ship_icons(matcher, frame)
    mark_rois(matcher, frame)
    log_ship_hits(now, f"{config.SHIP_STILL_SEC:.0f}秒后")
    pairs: list[tuple[float, int, int]] = []
    for i, old in enumerate(ships):
        for j, new in enumerate(now):
            dist = ((old.center[0] - new.center[0]) ** 2 + (old.center[1] - new.center[1]) ** 2) ** 0.5
            pairs.append((dist, i, j))
    pairs.sort()
    used_old: set[int] = set()
    used_new: set[int] = set()
    stayed: list[Hit] = []
    for dist, i, j in pairs:
        if dist > config.SHIP_STILL_PX:
            break
        if i in used_old or j in used_new:
            continue
        used_old.add(i)
        used_new.add(j)
        stayed.append(now[j])
        logp("船标", f"未动 {ships[i].center} → {now[j].center}  位移{dist:.0f}px")
    for i, old in enumerate(ships):
        if i not in used_old:
            logp("船标", f"在动或消失，忽略 {old.center}")
    return stayed


def pan_map_up(rect, do_click: bool) -> None:
    """按住客户区正中往上拖，露出下面一块星图。"""
    px = config.PATROL_PAN_PX
    x = rect.left + rect.width // 2
    y = rect.top + rect.height // 2
    logp("巡逻", f"{'DRAG' if do_click else 'DRY '} 上拖{px}px  from ({x},{y})")
    if not do_click:
        return
    with hold_foreground(rect):
        screen_drag(x, y, x, y - px)
    time.sleep(0.4)


def _skipped_ship(hit: Hit, ignore: list[tuple[int, int]]) -> bool:
    limit = config.SHIP_SKIP_PX
    x, y = hit.center
    return any((x - ix) ** 2 + (y - iy) ** 2 <= limit ** 2 for ix, iy in ignore)


def ship_still_there(matcher: Matcher, rect, hit: Hit) -> bool:
    """刚点的那艘船标还在不在。消失就当作查看已经点进去。"""
    frame = grab(rect)
    ships = find_ship_icons(matcher, frame)
    x, y = hit.center
    limit = config.SHIP_SKIP_PX ** 2
    return any((s.center[0] - x) ** 2 + (s.center[1] - y) ** 2 <= limit for s in ships)


def note_seen_level(level: int, where: str) -> None:
    folder = os.path.join(config.ROOT, "logs", "patrol")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, time.strftime("%Y%m%d") + ".txt")
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{stamp}\t{level}\t{where}\n")
    logp("巡逻", f"记下 {level} 级  {where}  logs/patrol/{time.strftime('%Y%m%d')}.txt")


def inspect_stationary_ship(
    matcher: Matcher,
    rect,
    do_click: bool,
    ignore: list[tuple[int, int]] | None = None,
    where: str = "",
) -> str:
    """ok=等级在范围内并结束。range=不在范围。miss=没认出或只看不打，继续扫。none=没有可点的静止船。"""
    if ignore is None:
        ignore = []
    frame = grab(rect)
    ships = find_ship_icons(matcher, frame)
    mark_rois(matcher, frame)
    log_ship_hits(ships, "当前")
    if not ships:
        return "none"
    kept: list[Hit] = []
    for hit in ships:
        if _skipped_ship(hit, ignore):
            logp("巡逻", f"跳过刚查看的船 {hit.center}")
            continue
        kept.append(hit)
    ships = ships_still(matcher, rect, kept)
    for hit in ships:
        if STOP.is_set():
            return "none"
        logp("巡逻", f"船标未动，点 {hit.center}")
        look = None
        opened = False
        tries = 3 if do_click else 1
        for attempt in range(1, tries + 1):
            if STOP.is_set():
                return "none"
            act_frame(rect, hit, ship_click_frame(rect, hit), do_click, "点船标" if attempt == 1 else "再点船标")
            deadline = time.time() + config.PANEL_WAIT
            while time.time() < deadline and not STOP.is_set():
                frame = grab(rect)
                look = matcher.find(frame, "look")
                mark_rois(matcher, frame)
                if look:
                    break
                if do_click and not ship_still_there(matcher, rect, hit):
                    logp("巡逻", f"船标已从 {hit.center} 消失，当作已经点过查看")
                    opened = True
                    break
                time.sleep(config.LOOP_SLEEP)
            if look or opened:
                break
            score, loc = matcher.best(grab(rect), "look")
            logp(
                "巡逻",
                f"没找到查看  第{attempt}次  最高分={score:.3f}@{loc}  阈值={config.thresh_for('look'):.2f}",
            )
        if opened:
            pass
        elif not look:
            ignore.append(hit.center)
            logp("巡逻", f"点了{tries}次仍没有查看，船标还在，跳过这艘，继续搜")
            return "miss"
        else:
            current = look
            opened = False
            for i in range(1, 4):
                if STOP.is_set():
                    return "none"
                act(rect, current, do_click, "查看" if i == 1 else "查看 再点")
                time.sleep(0.6)
                if not do_click:
                    opened = True
                    break
                if not ship_still_there(matcher, rect, hit):
                    logp("巡逻", f"查看第{i}次后船标已从 {hit.center} 消失")
                    opened = True
                    break
                still = matcher.find(grab(rect), "look")
                if still is None:
                    logp("确认", f"查看 第{i}次后面已关掉")
                    opened = True
                    break
                logp("确认", f"查看 第{i}次后按钮还在，船标也还在 {still.score:.2f}@{still.center}")
                current = still
            if not opened:
                logp("确认", "查看点了3次，按钮还在且船标还在，停止")
                STOP.set()
                overlay.hide()
                cue_stop()
                return "none"
        time.sleep(0.4)
        found = ship_level_near(grab(rect), hit)
        lo, hi = int(config.LVL_MIN), int(config.LVL_MAX)
        if found is None:
            ignore.append(hit.center)
            logp("巡逻", "没有匹配到等级，已记入异常，继续搜")
            return "miss"
        level, score = found
        if config.WATCH_ONLY:
            note_seen_level(level, where)
            ignore.append(hit.center)
            logp("巡逻", f"只看不打  等级 {level}（{score:.2f}），继续搜")
            return "miss"
        if level < lo or level > hi:
            ignore.append(hit.center)
            logp("巡逻", f"查看后等级 {level}（{score:.2f}）不在 {lo}-{hi}，重开本星系并跳过这艘")
            return "range"
        logp("巡逻", f"查看后等级 {level}（{score:.2f}）在 {lo}-{hi}")
        cue_found()
        logp("巡逻", "已查看，结束巡逻")
        return "ok"
    return "none"


def click_hunt_area(matcher: Matcher, rect, do_click: bool, idx: int) -> bool:
    name, label = HUNT_AREAS[idx]
    frame = grab(rect)
    hit = matcher.find(frame, name)
    if not hit:
        col = matcher.find(frame, "collection")
        if not col:
            logp("巡逻", "列表没开，先点收藏")
            if not wait_star_hud(matcher, rect):
                return False
            col = matcher.find(grab(rect), "collection")
        if not col:
            logp("巡逻", "没有收藏按钮")
            return False
        act(rect, col, do_click, "开收藏清单")
        hit = wait_hit(matcher, rect, name, config.PANEL_WAIT)
    if not hit:
        logp("巡逻", f"找不到 {label} ({name})")
        return False
    logp("巡逻", f"点星系 {label}  分={hit.score:.3f} {hit.center}")
    act(rect, hit, do_click, f"星系 {label}")
    time.sleep(1.0)
    return True


def run_goal3(matcher: Matcher, rect, do_click: bool, count: int) -> None:
    """自动巡逻。次数=最多轮数。无限则一直转到找到船或停止。"""
    rnd = 0
    while not STOP.is_set():
        rnd += 1
        if not config.INFINITE and rnd > count:
            break
        logp("巡逻", f"第 {rnd} 轮" if config.INFINITE else f"第 {rnd}/{count} 轮")
        if not repair_first(matcher, rect, do_click):
            break
        if not wait_star_hud(matcher, rect):
            break
        col = matcher.find(grab(rect), "collection")
        if not col:
            logp("巡逻", "齐HUD却没有收藏")
            break
        act(rect, col, do_click, "开收藏清单")
        time.sleep(0.6)
        found = False
        for i, (_n, label) in enumerate(HUNT_AREAS):
            if STOP.is_set():
                break
            logp("巡逻", f"星系 {i + 1}/4  {label}")
            if not click_hunt_area(matcher, rect, do_click, i):
                continue
            if not wait_star_hud(matcher, rect, extra_notches=config.PATROL_EXTRA_WHEEL):
                continue
            ignored: list[tuple[int, int]] = []

            def scan_ships_here() -> str:
                status = "none"
                while not STOP.is_set():
                    status = inspect_stationary_ship(matcher, rect, do_click, ignored, label)
                    if status not in ("range", "miss"):
                        return status
                    if len(ignored) > 8:
                        logp("巡逻", f"{label} 连续多艘看过，不再重开")
                        return "none"
                    logp("巡逻", f"{label} 重新打开")
                    if not click_hunt_area(matcher, rect, do_click, i):
                        return "none"
                    if not wait_star_hud(matcher, rect, extra_notches=config.PATROL_EXTRA_WHEEL):
                        return "none"
                return status

            if scan_ships_here() == "ok":
                found = True
                break
            logp("巡逻", f"{label} 没有静止船，上拖再找一次")
            pan_map_up(rect, do_click)
            if scan_ships_here() == "ok":
                found = True
                break
            logp("巡逻", f"{label} 上拖后仍没有静止船")
        if found:
            log("目标3 结束，已查看静止船")
            return
        logp("巡逻", "四个星系都看过，没有静止船，再来一轮")
    log(f"目标3 结束，未找到静止船" + ("" if config.INFINITE else f"  轮次最多{count}"))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="FGF 初版：模板匹配点击")
    p.add_argument("--goal", type=int, choices=(0, 1, 2, 3, 4, 5, 6), default=0)
    p.add_argument("--click", action="store_true", help="真的点鼠标；默认只扫一帧")
    p.add_argument("--dry", action="store_true", help="走完整流程但不点击")
    p.add_argument("--count", type=int, default=config.DEFAULT_COUNT)
    p.add_argument("--list-windows", action="store_true")
    p.add_argument("--gui", action="store_true", help="打开图形界面")
    return p.parse_args()


def scan_once(matcher: Matcher, rect, preview: bool = False) -> None:
    frame = grab(rect)
    hits = []
    regions: list[tuple] = []
    seen_regions: set[tuple] = set()
    skip_scan = {"hud_left", "hud_right", "hud_ship", "chat_tab_on", "mgmt_tab_on"}
    region_label = {
        "atk": "船队栏",
        "flag": "船队栏",
        "team_btn": "右HUD",
        "storage": "下方HUD",
    }
    for name in matcher.needles:
        if name in skip_scan:
            continue
        thresh = config.thresh_for(name)
        region = matcher.search_region(name, frame)
        if region is None:
            found = Matcher.find_all(matcher, frame, name, thresh)
        else:
            found = Matcher.find_all_in(matcher, frame, name, region, thresh)
            key = (region_label.get(name, name),) + tuple(int(v) for v in region)
            if key not in seen_regions:
                seen_regions.add(key)
                regions.append(key)
        for hit in found:
            hits.append(hit)
            log(f"scan {hit.name}={hit.score:.3f} {hit.center}")
    kept: list[Hit] = []
    for hit in sorted(hits, key=lambda x: -x.score):
        if any(hit.name == k.name and _near(hit.center, k.center, 16) for k in kept):
            continue
        kept.append(hit)
    hits = kept
    save_debug(matcher, frame, hits)
    log(f"已写 debug/last_frame.png  命中 {len(hits)} 个")
    if preview:
        overlay.push(rect, hits, regions)
        log("标记已画出，点一下或 5 秒后关掉")
        time.sleep(0.2)
        overlay.wait_dismiss(config.MARK_PREVIEW_SEC)


def run_one(goal: int, matcher: Matcher, rect, do_click: bool, count: int) -> None:
    if goal == 0:
        run_goal0(matcher, rect, do_click, count)
    elif goal == 1:
        run_goal1(matcher, rect, do_click, count)
    elif goal == 2 or goal == 6:
        run_goal2(matcher, rect, do_click, count)
    elif goal == 3:
        run_goal3(matcher, rect, do_click, count)
    elif goal == 4:
        run_goal4(matcher, rect, do_click, count)
    elif goal == 5:
        run_goal5(matcher, rect, do_click, count)
    else:
        log(f"没有目标 {goal}")


def run_queue(matcher: Matcher, rect, do_click: bool, steps: list[dict], loop: bool) -> None:
    """按表顺序跑。无限时忽略每项次数，整表循环，每项按 1 次。"""
    names = {0: "爪牙", 1: "贡品", 2: "祈祷船", 3: "巡逻", 4: "方舟", 5: "金币"}
    previous = config.INFINITE
    config.INFINITE = False
    try:
        while not STOP.is_set():
            for index, step in enumerate(steps, start=1):
                if STOP.is_set():
                    return
                goal = int(step["goal"])
                count = 1 if loop else int(step["count"])
                log(f"编排 {index}/{len(steps)}  {names.get(goal, goal)}  次数{count}")
                run_one(goal, matcher, rect, do_click, count)
            if not loop or STOP.is_set():
                return
            log("编排一轮完了，从头再来")
    finally:
        config.INFINITE = previous


def run_session(
    goal: int = 0,
    count: int = 10,
    click: bool = False,
    dry: bool = False,
    queue: list[dict] | None = None,
    use_queue: bool = False,
) -> int:
    STOP.clear()
    ensure_stop_listener()
    matcher = overlay.LiveMatcher()
    rect = pick_game_window()
    matcher.bind(rect)
    log(f"窗口 {rect.width}x{rect.height} at ({rect.left},{rect.top})  {rect.title!r}")
    if is_admin():
        log("当前是管理员权限")
    else:
        log("当前不是管理员。游戏如果也是管理员启动，能移鼠标但点不进去，请点「以管理员运行」")
    if (rect.width, rect.height) != config.GAME_SIZE:
        log(f"警告：不是 {config.GAME_SIZE}，匹配可能偏")
    log("F12 或界面「停止」可停")
    if not click and not dry:
        scan_once(matcher, rect, preview=True)
        log("HUD测试：只扫了一帧，没有点鼠标。")
        return 0
    mode = "真点" if click else "干跑流程（sleep，不点）"
    if use_queue and queue:
        brief = "  ".join(f"{step['goal']}x{1 if config.INFINITE else step['count']}" for step in queue)
        log(f"{mode}  编排 {brief}" + ("  循环" if config.INFINITE else ""))
    else:
        log(f"{mode}  goal={goal} count={count}")
    log("地图需已是至高教。目标0不拖等级（搜索默认30）。")
    try:
        if use_queue and queue:
            run_queue(matcher, rect, click, queue, config.INFINITE)
        elif goal == 0:
            run_one(0, matcher, rect, click, count)
        elif goal == 1:
            run_one(1, matcher, rect, click, count)
        elif goal == 2 or goal == 6:
            run_one(2, matcher, rect, click, count)
        elif goal == 3:
            run_one(3, matcher, rect, click, count)
        elif goal == 4:
            run_one(4, matcher, rect, click, count)
        elif goal == 5:
            run_one(5, matcher, rect, click, count)
        else:
            log(f"没有目标 {goal}")
    except pyautogui.FailSafeException:
        log("鼠标移到屏幕角落，failsafe 停")
    if STOP.is_set():
        log("已停止")
        return 1
    log("跑完了")
    return 0


def main() -> int:
    args = parse_args()
    if args.gui:
        from gui import launch

        launch()
        return 0
    if args.list_windows:
        for w in list_windows():
            print(f"{w.width}x{w.height}  ({w.left},{w.top})  {w.title}")
        return 0
    return run_session(goal=args.goal, count=args.count, click=args.click, dry=args.dry)


if __name__ == "__main__":
    sys.exit(main())
