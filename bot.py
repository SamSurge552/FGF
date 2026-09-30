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
import sys
import threading
import time

import cv2
import numpy as np
import pyautogui
from pynput import keyboard

import calibrate
import config
from capture import focus_window, grab, is_admin, list_windows, pick_game_window, screen_click, screen_drag, screen_key, screen_move, screen_wheel
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


def to_screen(rect, hit: Hit) -> tuple[int, int]:
    cx, cy = hit.center
    return (rect.left + cx, rect.top + cy)


def mouse_click(rect, sx: int, sy: int) -> None:
    ok = focus_window(rect)
    if not ok:
        log("游戏窗口没到前台，仍尝试点击")
    screen_click(sx, sy, config.CLICK_HOLD)
    time.sleep(config.CLICK_PAUSE)


def act(rect, hit: Hit, do_click: bool, why: str) -> None:
    sx, sy = to_screen(rect, hit)
    log(f"{'CLICK' if do_click else 'DRY '} {why}  {hit.name}={hit.score:.3f}  frame={hit.center}  screen=({sx},{sy})")
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
        log(f"没找到 {name}  最高分={score:.3f}@{loc}  阈值={t:.2f}")
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


def find_repair(matcher: Matcher, frame) -> Hit | None:
    return matcher.find(frame, "repair")


def _finish_rally(appear_s: float | None, duration_s: float, reason: str) -> None:
    nxt = calibrate.record_goal1(appear_s, duration_s, reason)
    logp(
        "集结",
        f"信号={reason}  总耗时{duration_s:.1f}s  "
        f"下次 出场{nxt['appear_wait']:.0f}s 最短{nxt['min_rally']:.0f}s 超时{nxt['gone_wait']:.0f}s",
    )


def wait_repair_as_signal(matcher: Matcher, rect, t0: float, appear_s: float | None, timeout: float, do_click: bool) -> bool:
    """没旗可跟时，用修理按钮当打完信号。"""
    logp("集结", f"没有过线的旗，改等修理按钮，最多 {timeout:.0f}s")
    deadline = time.time() + timeout
    last_log = 0.0
    while time.time() < deadline and not STOP.is_set():
        frame = grab(rect)
        mark_rois(matcher, frame)
        elapsed = time.time() - t0
        if time.time() - last_log >= 10.0:
            repair = find_repair(matcher, frame)
            logp(
                "集结",
                f"已等修理{elapsed:.0f}s  "
                f"{'修理有' if repair else '修理无'}  {weak_flag_hint(matcher, frame)}",
            )
            last_log = time.time()
        repair = find_repair(matcher, frame)
        if repair:
            logp("集结", f"看到修理按钮  分={repair.score:.3f} {repair.center}  {weak_flag_hint(matcher, frame)}")
            act(rect, repair, do_click, "自动修理")
            _finish_rally(appear_s, elapsed, "repair")
            return True
        time.sleep(0.6)
    logp("集结", f"等修理超时  {weak_flag_hint(matcher, grab(rect))}")
    return False


def wait_flag_gone(matcher: Matcher, rect, before: list[tuple[int, int]], do_click: bool = True) -> bool:
    """点黄确认后，看左侧船队栏的旗。没有过线的旗则改等修理。"""
    t = calibrate.timeouts_goal1()
    logp(
        "集结",
        f"校准 样本{int(t['samples'])} 中位{t['median']:.1f}s  "
        f"出场等待{t['appear_wait']:.0f}s 最短{t['min_rally']:.0f}s 超时{t['gone_wait']:.0f}s  "
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
        repair = find_repair(matcher, frame)
        if repair and elapsed >= 4.0:
            logp("集结", f"等旗时先看到修理  分={repair.score:.3f} {repair.center}  {weak_flag_hint(matcher, frame)}")
            act(rect, repair, do_click, "自动修理")
            _finish_rally(None, elapsed, "repair")
            return True
        time.sleep(0.5)
    if appeared is None:
        now = flag_centers(matcher, grab(rect))
        if now:
            appeared = now[0]
            appear_s = time.time() - t0
            logp("集结", f"没有多出来的新位置，改为跟踪当前这面旗 {appeared}")
        else:
            logp("集结", f"一直没看到过线的旗，先试拉人，再短等修理  {weak_flag_hint(matcher, grab(rect))}")
            invite_allies(matcher, rect, do_click)
            if STOP.is_set():
                return False
            return wait_repair_as_signal(matcher, rect, t0, None, config.RALLY_NO_FLAG_WAIT, do_click)
    invite_allies(matcher, rect, do_click)
    logp("集结", f"等这面旗消失，最多 {t['gone_wait']:.0f}s（出场后至少 {t['min_rally']:.0f}s；也认修理）")
    t_flag = time.time()
    gone_since: float | None = None
    last_log = 0.0
    while time.time() - t_flag < t["gone_wait"] and not STOP.is_set():
        frame = grab(rect)
        now = flag_centers(matcher, frame)
        mark_rois(matcher, frame)
        elapsed = time.time() - t_flag
        if elapsed - last_log >= 15.0:
            logp(
                "集结",
                f"已等消失{elapsed:.0f}s  当前旗={now or '无'}  {weak_flag_hint(matcher, frame)}",
            )
            last_log = elapsed
        repair = find_repair(matcher, frame)
        if repair and elapsed >= 4.0:
            logp("集结", f"等旗消失时看到修理  分={repair.score:.3f} {repair.center}")
            act(rect, repair, do_click, "自动修理")
            _finish_rally(appear_s, time.time() - t0, "repair")
            return True
        still = any(_near(appeared, pt, 45) for pt in now)
        if still or elapsed < t["min_rally"]:
            gone_since = None
        else:
            if gone_since is None:
                gone_since = time.time()
                logp("集结", f"旗暂时没看到，确认中（需连续{t['gone_confirm']:.1f}s）  {weak_flag_hint(matcher, frame)}")
            elif time.time() - gone_since >= t["gone_confirm"]:
                _finish_rally(appear_s, time.time() - t0, "flag_gone")
                return True
        time.sleep(0.8)
    logp("集结", f"等旗消失超时  {weak_flag_hint(matcher, grab(rect))}")
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
    ok = focus_window(rect)
    if not ok:
        log("游戏窗口没到前台，仍尝试 ESC")
    logp("按键", f"ESC  {why}")
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
                logp("开战确认", f"没看到atk但出现修理，当作打完/已打过  {describe_scene(flags)}")
                return "combat"
            if flags["search"] and not flags["goal0_atk"]:
                logp("攻击", f"放大镜回来了，判定船跑了  {describe_scene(flags)}")
                return "fled"
            time.sleep(0.4)
        logp("攻击", "按钮没了、也一直没有atk，判定船跑了")
        return "fled"
    logp("攻击", "连点三次攻擊按钮仍在，放弃本轮")
    return "miss"


def wait_fight_over(matcher: Matcher, rect) -> bool:
    """点攻击后等打完。优先：修理按钮出现；其次：atk 出现后再连续消失。
    成功结束会记一条耗时，用来改最短战斗时间和超时。
    """
    t = calibrate.timeouts()
    logp(
        "战斗",
        f"开始等打完  校准样本{int(t['samples'])} 中位{t['median']:.1f}s  "
        f"出场等待{t['appear_wait']:.0f}s 最短{t['min_fight']:.0f}s 超时{t['gone_wait']:.0f}s",
    )
    t0 = time.time()
    appear_s: float | None = None
    gone_since: float | None = None
    logged_no_atk = False
    last_beat = 0.0
    while time.time() - t0 < t["gone_wait"] and not STOP.is_set():
        frame = grab(rect)
        elapsed = time.time() - t0
        flags = scene_flags(matcher, frame)
        if elapsed - last_beat >= 5.0:
            logp("战斗", f"已等{elapsed:.0f}s  {describe_scene(flags)}")
            last_beat = elapsed
        if flags["repair"] and elapsed >= 4.0:
            logp("结束", f"看到修理按钮  {describe_scene(flags)}")
            _finish_fight(appear_s, elapsed, "repair")
            return True
        hit = flags["atk"]
        if hit:
            if appear_s is None:
                appear_s = elapsed
                logp("战斗", f"船队栏出现atk  分={hit.score:.3f} 位置{hit.center}  开战{appear_s:.1f}s后")
            gone_since = None
        elif appear_s is None:
            if elapsed >= t["appear_wait"] and not logged_no_atk:
                logp("战斗", f"等了{elapsed:.0f}s仍无船队栏atk，会继续等修理或atk（不是已经在战斗里）  {describe_scene(flags)}")
                logged_no_atk = True
            gone_since = None
        elif elapsed < t["min_fight"]:
            gone_since = None
        else:
            if gone_since is None:
                gone_since = time.time()
                logp("战斗", f"atk消失，开始确认（需连续{t['gone_confirm']:.1f}s）  {describe_scene(flags)}")
            elif time.time() - gone_since >= t["gone_confirm"]:
                logp("结束", f"atk已连续消失  {describe_scene(flags)}")
                _finish_fight(appear_s, elapsed, "atk_gone")
                return True
        time.sleep(0.4)
    logp("结束", "等打完超时，未写入校准")
    return False


def _finish_fight(appear_s: float | None, duration_s: float, reason: str) -> None:
    nxt = calibrate.record_goal0(appear_s, duration_s, reason)
    logp(
        "结束",
        f"信号={reason}  耗时{duration_s:.1f}s  下次最短{nxt['min_fight']:.0f}s 超时{nxt['gone_wait']:.0f}s",
    )


def open_search(matcher: Matcher, rect, do_click: bool) -> Hit | None:
    """点放大镜直到黄搜寻出现。面板已开则不再点放大镜。已有修理则先修。"""
    frame = grab(rect)
    repair = find_repair(matcher, frame)
    if repair:
        logp("修理", f"搜寻前先修理  分={repair.score:.3f} {repair.center}")
        if not click_until_gone(matcher, rect, repair, "repair", do_click, "自动修理"):
            return None
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
            log("找不到搜寻放大镜")
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
    return None


def run_goal0(matcher: Matcher, rect, do_click: bool, count: int) -> None:
    """爪牙·至高教：开搜索（默认已是 30）→ 黄搜寻 → 攻擊 → 等船队栏 atk 消失。"""
    done = 0
    while (config.INFINITE or done < count) and not STOP.is_set():
        label = f"第 {done + 1} 次" if config.INFINITE else f"第 {done + 1}/{count} 次"
        logp("目标0", label)
        go = open_search(matcher, rect, do_click)
        if not go:
            break
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
        go = open_search(matcher, rect, do_click)
        if not go:
            break
        tab = wait_hit(matcher, rect, "tab_tribute", config.PANEL_WAIT)
        if not tab:
            logp("贡品", "找不到贡品船页签")
            break
        act(rect, tab, do_click, "贡品船")
        go = wait_hit(matcher, rect, "search_go", config.PANEL_WAIT)
        if not go:
            logp("贡品", "找不到黄搜寻")
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
            logp("目标1", "红集结没点上，重新搜寻")
            continue
        ensure_rally_time(matcher, rect, grab(rect), do_click)
        yellow = wait_hit(matcher, rect, "rally_yellow", config.RALLY_RED_WAIT)
        if not yellow:
            logp("贡品", "找不到黄确认 rally_confirm，重新搜寻")
            continue
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


def run_goal2(matcher: Matcher, rect, do_click: bool, count: int) -> None:
    done = 0
    while (config.INFINITE or done < count) and not STOP.is_set():
        log(f"目标2 第 {done + 1} 次，等邀请" if config.INFINITE else f"目标2 第 {done + 1}/{count} 次，等邀请")
        deadline = time.time() + config.INVITE_WAIT
        hit_yes = None
        while time.time() < deadline and not STOP.is_set():
            frame = grab(rect)
            label = matcher.find(frame, "prayer_label")
            yes = matcher.find(frame, "invite_yes")
            if label and yes:
                hit_yes = yes
                log(f"至高祈祷舰 {label.score:.3f}  对勾 {yes.score:.3f}")
                break
            time.sleep(config.LOOP_SLEEP)
        if not hit_yes:
            log("本轮没等到邀请")
            continue
        act(rect, hit_yes, do_click, "接受邀请")
        atk = wait_hit(matcher, rect, "attack", config.SHIP_WAIT)
        if not atk:
            log("没有攻击按钮，放弃本次")
            continue
        tele = matcher.find(grab(rect), "teleport")
        if tele:
            log(f"传送在 {tele.center}，不点")
        act(rect, atk, do_click, "攻击")
        done += 1
        log(f"已点攻击，完成 {_quota(done, count)}")
        time.sleep(2.0)
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


def ship_level_near(frame, hit: Hit) -> tuple[int, float] | None:
    """查看之后，在这艘船附近认等级。返回 (等级, 分数)，没有过线的就 None。"""
    groups = level_needles()
    if not groups or frame is None or frame.size == 0:
        return None
    gray = cv2.cvtColor(frame[:, :, :3], cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    binary = np.where(gray >= config.LVL_GRAY, 255, 0).astype(np.uint8)
    h, w = binary.shape[:2]
    cx, cy = hit.center
    left, up, right, down = config.LVL_NEAR
    x0 = max(0, cx - left)
    y0 = max(0, cy - up)
    x1 = min(w, cx + right)
    y1 = min(h, cy + down)
    crop = binary[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    maps = []
    used = []
    for lv in levels:
        acc = None
        for nd in groups[lv]:
            if nd.shape[0] > crop.shape[0] or nd.shape[1] > crop.shape[1]:
                continue
            res = cv2.matchTemplate(crop, nd, cv2.TM_CCOEFF_NORMED)
            acc = res if acc is None else np.maximum(acc, res)
        if acc is None:
            continue
        maps.append(acc)
        used.append(lv)
    if len(maps) < 2:
        return None
    stack = np.stack(maps, 0)
    order = np.argsort(-stack, axis=0)
    best = np.take_along_axis(stack, order[0][None], 0)[0]
    second = np.take_along_axis(stack, order[1][None], 0)[0]
    best_i = order[0]
    ys, xs = np.where((best >= config.LVL_SCORE) & ((best - second) >= config.LVL_MARGIN))
    if len(xs) == 0:
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


def ship_still_after(matcher: Matcher, rect, hit: Hit) -> bool:
    x0, y0 = hit.center
    logp("船标", f"等{config.SHIP_STILL_SEC:.0f}s看是否还在 ({x0},{y0}) 附近")
    deadline = time.time() + config.SHIP_STILL_SEC
    while time.time() < deadline and not STOP.is_set():
        time.sleep(0.5)
    if STOP.is_set():
        return False
    frame = grab(rect)
    now = find_ship_icons(matcher, frame)
    mark_rois(matcher, frame)
    log_ship_hits(now, f"{config.SHIP_STILL_SEC:.0f}秒后")
    if not now:
        return False
    nearest = min(now, key=lambda h: abs(h.center[0] - x0) + abs(h.center[1] - y0))
    dist = ((nearest.center[0] - x0) ** 2 + (nearest.center[1] - y0) ** 2) ** 0.5
    logp("船标", f"最近 {nearest.score:.3f}@{nearest.center}  位移{dist:.0f}px  限{config.SHIP_STILL_PX}px")
    return dist <= config.SHIP_STILL_PX


def pan_map_up(rect, do_click: bool) -> None:
    """按住客户区正中往上拖，露出下面一块星图。"""
    px = config.PATROL_PAN_PX
    x = rect.left + rect.width // 2
    y = rect.top + rect.height // 2
    logp("巡逻", f"{'DRAG' if do_click else 'DRY '} 上拖{px}px  from ({x},{y})")
    if not do_click:
        return
    screen_drag(x, y, x, y - px)
    time.sleep(0.4)


def inspect_stationary_ship(matcher: Matcher, rect, do_click: bool) -> bool:
    frame = grab(rect)
    ships = find_ship_icons(matcher, frame)
    mark_rois(matcher, frame)
    log_ship_hits(ships, "当前")
    if not ships:
        return False
    for hit in ships:
        if STOP.is_set():
            return False
        if not ship_still_after(matcher, rect, hit):
            logp("巡逻", f"船标在动，忽略 {hit.center}")
            continue
        logp("巡逻", f"船标未动，点 {hit.center}")
        act(rect, hit, do_click, "点船标")
        look = wait_hit(matcher, rect, "look", config.PANEL_WAIT)
        if not look:
            logp("巡逻", "没找到查看")
        elif not click_until_gone(matcher, rect, look, "look", do_click, "查看"):
            return False
        time.sleep(0.4)
        found = ship_level_near(grab(rect), hit)
        lo, hi = int(config.LVL_MIN), int(config.LVL_MAX)
        if found is None:
            logp("巡逻", f"没有匹配到等级，请自己核对这艘船是不是 {lo}-{hi} 级。暂时算成功")
        else:
            level, score = found
            if level < lo or level > hi:
                logp("巡逻", f"查看后等级 {level}（{score:.2f}）不在 {lo}-{hi}，继续找")
                return False
            logp("巡逻", f"查看后等级 {level}（{score:.2f}）在 {lo}-{hi}")
        cue_found()
        logp("巡逻", "已查看，结束巡逻")
        return True
    return False


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
            if inspect_stationary_ship(matcher, rect, do_click):
                found = True
                break
            logp("巡逻", f"{label} 没有静止船，上拖再找一次")
            pan_map_up(rect, do_click)
            if inspect_stationary_ship(matcher, rect, do_click):
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
    p.add_argument("--goal", type=int, choices=(0, 1, 2, 3), default=0)
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


def run_session(goal: int = 0, count: int = 10, click: bool = False, dry: bool = False) -> int:
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
    if click or dry:
        focus_window(rect)
        time.sleep(0.4)
    log("F12 或界面「停止」可停")
    if not click and not dry:
        scan_once(matcher, rect, preview=True)
        log("HUD测试：只扫了一帧，没有点鼠标。")
        return 0
    mode = "真点" if click else "干跑流程（sleep，不点）"
    log(f"{mode}  goal={goal} count={count}")
    log("地图需已是至高教。目标0不拖等级（搜索默认30）。")
    try:
        if goal == 0:
            run_goal0(matcher, rect, click, count)
        elif goal == 1:
            run_goal1(matcher, rect, click, count)
        elif goal == 2:
            run_goal2(matcher, rect, click, count)
        else:
            run_goal3(matcher, rect, click, count)
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
