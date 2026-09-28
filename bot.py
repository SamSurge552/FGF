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
import pyautogui
from pynput import keyboard

import calibrate
import config
from capture import focus_window, grab, is_admin, list_windows, pick_game_window, screen_click, screen_key
import overlay
from vision import Hit, Matcher

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

STOP = threading.Event()
LOG_HOOK = None
_listener = None


def on_press(key) -> None:
    try:
        if key == keyboard.Key.f12:
            log("F12 停止")
            STOP.set()
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


def wait_hit(matcher: Matcher, rect, name: str, timeout: float, thresh: float | None = None) -> Hit | None:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline and not STOP.is_set():
        frame = grab(rect)
        last = frame
        hit = matcher.find(frame, name, thresh if thresh is not None else config.MATCH_THRESH)
        mark_rois(matcher, frame)
        if hit:
            return hit
        time.sleep(config.LOOP_SLEEP)
    if last is not None:
        score, loc = matcher.best(last, name)
        t = thresh if thresh is not None else config.MATCH_THRESH
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


def fleet_hud_region(matcher: Matcher, frame) -> tuple[int, int, int, int]:
    """左侧船队栏。优先用 ship.png 定位，对不上就用左列默认框。"""
    h, w = frame.shape[:2]
    default = (0, 140, min(140, w), min(520, h - 140))
    hit = matcher.find(frame, "ship", 0.55)
    if not hit:
        return default
    x1 = max(0, hit.x1 - 10)
    y1 = max(0, hit.y1 - 10)
    rw = min(w - x1, hit.x2 - hit.x1 + 20)
    rh = min(h - y1, hit.y2 - hit.y1 + 20)
    return (x1, y1, rw, rh)


FLAG_HINT_FLOOR = 0.40


def flag_candidates(matcher: Matcher, frame, thresh: float) -> list[Hit]:
    region = fleet_hud_region(matcher, frame)
    hits = matcher.find_all_in(frame, "flag", region, thresh)
    return _unique_hits(hits, d=16)


def flag_centers(matcher: Matcher, frame) -> list[tuple[int, int]]:
    return [h.center for h in flag_candidates(matcher, frame, config.FLAG_THRESH)]


def weak_flag_hint(matcher: Matcher, frame) -> str:
    """列出船队栏里看得到、但没过 FLAG_THRESH 的旗。"""
    region = fleet_hud_region(matcher, frame)
    x, y, rw, rh = region
    crop = frame[y : y + rh, x : x + rw]
    score, loc = matcher.best(crop, "flag") if crop.size else (0.0, (-1, -1))
    abs_loc = (loc[0] + x, loc[1] + y) if loc[0] >= 0 else loc
    weak = [h for h in flag_candidates(matcher, frame, FLAG_HINT_FLOOR) if h.score < config.FLAG_THRESH]
    if weak:
        bits = "  ".join(f"{h.score:.3f}@{h.center}" for h in weak[:4])
        return (
            f"低于阈值的旗 {bits}  阈值={config.FLAG_THRESH:.2f}  "
            f"船队栏最高={score:.3f}@{abs_loc}"
        )
    return f"船队栏无低分旗候选  最高={score:.3f}@{abs_loc}  阈值={config.FLAG_THRESH:.2f}"


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


def wait_flag_gone(matcher: Matcher, rect, before: list[tuple[int, int]], do_click: bool = True) -> None:
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
            return
        time.sleep(0.5)
    if appeared is None:
        now = flag_centers(matcher, grab(rect))
        if now:
            appeared = now[0]
            appear_s = time.time() - t0
            logp("集结", f"没有多出来的新位置，改为跟踪当前这面旗 {appeared}")
        else:
            logp("集结", f"一直没看到过线的旗  {weak_flag_hint(matcher, grab(rect))}")
            invite_allies(matcher, rect, do_click)
            wait_repair_as_signal(matcher, rect, t0, None, t["gone_wait"], do_click)
            return
    invite_allies(matcher, rect, do_click)
    logp("集结", f"等这面旗消失，最多 {t['gone_wait']:.0f}s（出场后至少 {t['min_rally']:.0f}s；也认修理）")
    t_flag = time.time()
    gone_since: float | None = None
    last_log = 0.0
    while time.time() - t_flag < t["gone_wait"] and not STOP.is_set():
        frame = grab(rect)
        now = flag_centers(matcher, frame)
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
            return
        still = any(_near(appeared, pt, 45) for pt in now)
        if still or elapsed < t["min_rally"]:
            gone_since = None
        else:
            if gone_since is None:
                gone_since = time.time()
                logp("集结", f"旗暂时没看到，确认中（需连续{t['gone_confirm']:.1f}s）  {weak_flag_hint(matcher, frame)}")
            elif time.time() - gone_since >= t["gone_confirm"]:
                _finish_rally(appear_s, time.time() - t0, "flag_gone")
                return
        time.sleep(0.8)
    logp("集结", f"等旗消失超时  {weak_flag_hint(matcher, grab(rect))}")


def team_btn_region(frame) -> tuple[int, int, int, int]:
    """组队入口：HUD 右侧、搜寻放大镜上方。"""
    h, w = frame.shape[:2]
    return (max(0, w - 320), 540, min(320, w), min(280, h - 540))


def wait_hit_in(matcher: Matcher, rect, name: str, region, timeout: float, thresh: float | None = None) -> Hit | None:
    deadline = time.time() + timeout
    last = None
    t = thresh if thresh is not None else config.MATCH_THRESH
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
    team = wait_hit_in(matcher, rect, "team_btn", team_btn_region(frame), config.PANEL_WAIT, 0.82)
    if not team:
        logp("邀请", "没有 team.png（组队入口），跳过拉人")
        return
    act(rect, team, do_click, "打开组队")
    invite = wait_hit(matcher, rect, "invite", config.PANEL_WAIT)
    if not invite:
        logp("邀请", "team_hud 里没有 invite.png，点返回")
        back = wait_hit(matcher, rect, "back", 4.0)
        if back:
            act(rect, back, do_click, "返回")
        return
    act(rect, invite, do_click, "打开邀请")
    all_btn = wait_hit(matcher, rect, "invite_all", config.PANEL_WAIT)
    if not all_btn:
        logp("邀请", "invite_hud 里没有邀请全部")
        back = wait_hit(matcher, rect, "back", 4.0)
        if back:
            act(rect, back, do_click, "返回")
        return
    act(rect, all_btn, do_click, "邀请全部")
    time.sleep(0.8)
    back = wait_hit(matcher, rect, "back", config.PANEL_WAIT)
    if not back:
        logp("邀请", "回到 team_hud 后没有 back.png")
        return
    act(rect, back, do_click, "返回地图")
    time.sleep(0.6)
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


def left_hud(frame) -> tuple[int, int, int, int]:
    h, w = frame.shape[:2]
    return (0, 0, min(360, w), h)


def mark_rois(matcher: Matcher, frame) -> None:
    extra = getattr(matcher, "extra_regions", None)
    if extra is None:
        return
    extra(
        [
            ("左HUD", *left_hud(frame)),
            ("船队栏", *fleet_hud_region(matcher, frame)),
            ("组队区", *team_btn_region(frame)),
        ]
    )


def find_atk(matcher: Matcher, frame) -> Hit | None:
    """只认左 HUD。全屏匹配容易把别的图标当成战斗中。"""
    return matcher.find_in(frame, "atk", left_hud(frame), config.ATK_THRESH)


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
    combat=左HUD连续看到atk；fled=船跑了/按钮没了也没开战；miss=按钮还在点不中。
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
                    logp("开战确认", f"左HUD连续{atk_streak}帧看到atk，确认已开战")
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
        logp("攻击", f"攻擊按钮消失，但左HUD还没有atk  {describe_scene(flags)}")
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
                logp("战斗", f"左HUD出现atk  分={hit.score:.3f} 位置{hit.center}  开战{appear_s:.1f}s后")
            gone_since = None
        elif appear_s is None:
            if elapsed >= t["appear_wait"] and not logged_no_atk:
                logp("战斗", f"等了{elapsed:.0f}s仍无左HUD-atk，会继续等修理或atk（不是已经在战斗里）  {describe_scene(flags)}")
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
    """点放大镜直到黄搜寻出现。面板已开则不再点放大镜。"""
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
    """爪牙·至高教：开搜索（默认已是 30）→ 黄搜寻 → 攻擊 → 等左 HUD atk 消失。"""
    done = 0
    while done < count and not STOP.is_set():
        logp("目标0", f"第 {done + 1}/{count} 次")
        go = open_search(matcher, rect, do_click)
        if not go:
            break
        logp("搜寻", "不拖等级（默认30），点黄搜寻跳转")
        act(rect, go, do_click, "确认搜寻")
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
        logp("目标0", f"本轮完成 {done}/{count}")
        time.sleep(1.0)
    log(f"目标0 结束，完成 {done}/{count}")


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
    while done < count and not STOP.is_set():
        logp("目标1", f"第 {done + 1}/{count} 次")
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
        act(rect, go, do_click, "确认搜寻")
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
        act(rect, yellow, do_click, "黄确认集结")
        time.sleep(0.6)
        still = matcher.find(grab(rect), "rally_yellow")
        if still:
            logp("贡品", "黄确认还在，再点一次")
            act(rect, still, do_click, "黄确认集结再点")
        wait_flag_gone(matcher, rect, map_flags, do_click)
        if check_mail_success(matcher, rect, do_click):
            done += 1
            log(f"本轮成功，完成 {done}/{count}")
        else:
            log(f"本轮未计成功，仍是 {done}/{count}")
    log(f"目标1 结束，完成 {done}/{count}")


def run_goal2(matcher: Matcher, rect, do_click: bool, count: int) -> None:
    done = 0
    while done < count and not STOP.is_set():
        log(f"目标2 第 {done + 1}/{count} 次，等邀请")
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
        log(f"已点攻击，完成 {done}")
        time.sleep(2.0)
    log(f"目标2 结束，完成 {done}/{count}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="FGF 初版：模板匹配点击")
    p.add_argument("--goal", type=int, choices=(0, 1, 2), default=0)
    p.add_argument("--click", action="store_true", help="真的点鼠标；默认只扫一帧")
    p.add_argument("--dry", action="store_true", help="走完整流程但不点击")
    p.add_argument("--count", type=int, default=config.DEFAULT_COUNT)
    p.add_argument("--list-windows", action="store_true")
    p.add_argument("--gui", action="store_true", help="打开图形界面")
    return p.parse_args()


def scan_once(matcher: Matcher, rect) -> None:
    frame = grab(rect)
    hits = []
    for name in matcher.needles:
        thresh = config.FLAG_THRESH if name in ("flag", "trading") else config.MATCH_THRESH
        if name == "time_on":
            thresh = config.TIME_ON_THRESH
        if name == "time_off":
            thresh = config.TIME_OFF_THRESH
        if name == "mail":
            thresh = config.MAIL_THRESH
        if name == "new":
            thresh = config.NEW_THRESH
        if name == "atk":
            thresh = config.ATK_THRESH
        hit = matcher.find(frame, name, thresh)
        if hit:
            hits.append(hit)
            log(f"scan {hit.name}={hit.score:.3f} {hit.center}")
    mark_rois(matcher, frame)
    save_debug(matcher, frame, hits)
    log(f"已写 debug/last_frame.png  命中 {len(hits)} 个")


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
    scan_once(matcher, rect)
    if not click and not dry:
        log("只扫了一帧。要跑流程请选「真点」或「干跑」。")
        return 0
    mode = "真点" if click else "干跑流程（sleep，不点）"
    log(f"{mode}  goal={goal} count={count}")
    log("地图需已是至高教。目标0不拖等级（搜索默认30）。")
    try:
        if goal == 0:
            run_goal0(matcher, rect, click, count)
        elif goal == 1:
            run_goal1(matcher, rect, click, count)
        else:
            run_goal2(matcher, rect, click, count)
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
