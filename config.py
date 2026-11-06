"""初版配置。超时、等级、人数以后再改。"""
from __future__ import annotations

import os
import threading

ROOT = os.path.dirname(os.path.abspath(__file__))
PIC = os.path.join(ROOT, "pic")
STABLE = os.path.join(PIC, "stable")
DEBUG_DIR = os.path.join(ROOT, "debug")

GAME_SIZE = (1920, 1080)
STOP_KEY = "f12"
SEARCH_THRESH = 0.80
MATCH_THRESH = 0.88
FLAG_THRESH = 0.75
TRADING_THRESH = 0.85
TIME_ON_THRESH = 0.90
TIME_OFF_THRESH = 0.95
MAIL_THRESH = 0.90
WIN_THRESH = 0.88
NEW_THRESH = 0.85
LOOT_THRESH = 0.88
ATK_THRESH = 0.95
ATK_APPEAR_WAIT = 25.0
ATK_GONE_WAIT = 180.0
ATK_GONE_CONFIRM = 3.0
# 重置校准、还没有样本时，爪牙和集结的平均耗时都用这个
DEFAULT_AVG_WAIT = 30.0
# 打完信号到了，离平均不超过这么多秒就可以收。记实际耗时，平均才会往短了移。
AVG_EARLY_SEC = 10.0
ATK_MIN_FIGHT = 30.0
ATK_STREAK = 2
ATK_CLICK_CONFIRM = 3.0
HUD_LOC_THRESH = 0.55
# 右HUD贴右边；底下留给底栏/小地图（1920x1080 上约 144px）
HUD_RIGHT_BOTTOM_GAP = 144
# 下方 HUD 只作区域。图在 pic/storage/hud_bottom.png，593x156。没对齐过时贴在 1920x1080 底部居中。
HUD_BOTTOM = os.path.join(STABLE, "hud_bottom.png")
HUD_BOTTOM_SIZE = (593, 156)
SHIP_ICON_THRESH = 0.50
# 船标模板：pic/ship/tpl/ship_000.png … ship_337.png，已是 HSV 二值。不再现场旋转彩色 icon。
SHIP_TPL = os.path.join(PIC, "ship", "tpl")
SHIP_HUD_NAMES = ("hud1.png", "hud2.png", "hud3.png")
SHIP_HUD_THRESH = 0.75
# OpenCV HSV。船体亮灰绿。
SHIP_HSV_LO = (28, 25, 110)
SHIP_HSV_HI = (45, 70, 210)
# 点「查看」之后整图认等级。灰度二值，和 pic/lvl/tpl 同一套。
LVL_TPL = os.path.join(PIC, "lvl", "tpl")
LVL_MIN = 16
LVL_MAX = 22
LVL_GRAY = 120
# 仓储：storage1 灰色部分大约 156–240。灰度 >= 200 后，storage1 能配上 storage0。
STORAGE_GRAY = 200
LVL_SCORE = 0.80
LVL_MARGIN = 0.08
# 前两名分差不够时，用各模板亮的比例挑关键格再判。比例差至少这么大才算关键格。
LVL_KEY_GAP = 0.80
LVL_KEY_SHIFT = 2
WHEEL_PAUSE = 0.2
WHEEL_MAX = 40
SHIP_STILL_SEC = 8.0
SHIP_STILL_PX = 50
# 等级不在范围、重开星系之后，离这个点这么近的船标视为刚查看过的那艘
SHIP_SKIP_PX = 80
# 船标离窗口左或上下边小于查看按钮对应边的这个倍数时，改到这条边上再点，避免查看跑出窗口。右边不改。
LOOK_EDGE_SCALE = 1.7
# 点船标时点在船心上方，避免鼠标和查看按钮挡住船标，造成船已消失的假判断
SHIP_CLICK_ABOVE = 50
PATROL_EXTRA_WHEEL = 10
PATROL_PAN_PX = 200
MARK_PREVIEW_SEC = 5
# 第一条邮件同一行：相对胜利标的 y 容差
MAIL_ROW_DY = 100

CLICK_PAUSE = 1.2
CLICK_HOLD = 0.08
# 切到游戏后、切回去前各等这么久。设置「切前台」可改。
FOCUS_SETTLE = 0.2
PANEL_WAIT = 8.0
SHIP_WAIT = 10.0
SETTINGS_WAIT = 8.0
RALLY_RED_WAIT = 5.0
RALLY_WAIT = 300.0
# 黄确认后一直没有过线的旗：只短等修理，不要占用整段集结超时
RALLY_NO_FLAG_WAIT = 20.0
# 贡品成功先不看邮件。别的舰队自动组队也会带进 WIN+NEW+LOOT。
MAIL_COUNT = False
INVITE_WAIT = 30.0
LOOP_SLEEP = 0.4
DEFAULT_COUNT = 10
INFINITE = False
# 巡逻只查看并记下等级，不按上下限结束
WATCH_ONLY = False

# 贡品船目标等级；数字与「等级」两字对齐。正数=向上拖（等级+）次数，0=不拖
TRIBUTE_LEVEL = 4
LEVEL_DRAGS = 0
LEVEL_DRAG_PX = 55
# 集结人数目标；初版用加减点击次数（正=点+），0=不改。图上常见已是 3
RALLY_PEOPLE_PLUS_CLICKS = 0
RALLY_MINUTES_CHOICES = (1, 3, 5, 10)
RALLY_MINUTES = 1

CHAT_TAB_THRESH = 0.88
CHAT_OCR_INTERVAL = 1.5
# 聊天面板页签条、正文（相对 1920x1080 客户区）
CHAT_TAB_REGION = (640, 105, 700, 75)
CHAT_BODY_REGION = (690, 185, 650, 720)

# settings.png 里黄集结相对面板的位置，用来推三艘船槽
PANEL_YELLOW = (114, 581)
PANEL_SIZE = (552, 795)
SLOT_TOP = 660
SLOT_H = 130
SLOT_W = 184

TEMPLATES = {
    "search": os.path.join(STABLE, "search.png"),
    "tab_tribute": os.path.join(STABLE, "button3.png"),
    "tab_claw": os.path.join(STABLE, "button7.png"),
    "search_go": os.path.join(STABLE, "button4.png"),
    "rally_red": os.path.join(STABLE, "button5.png"),
    "rally_yellow": os.path.join(STABLE, "rally_confirm.png"),
    "attack": os.path.join(STABLE, "button.png"),
    "event1": os.path.join(STABLE, "event1.png"),
    "goal0_atk": os.path.join(STABLE, "goal0_atk.png"),
    "atk": os.path.join(STABLE, "atk.png"),
    "repair": os.path.join(STABLE, "repair.png"),
    "teleport": os.path.join(STABLE, "button2.png"),
    "invite_yes": os.path.join(STABLE, "invite_yes.png"),
    "invite_no": os.path.join(STABLE, "invite_no.png"),
    "prayer_label": os.path.join(STABLE, "prayer_label.png"),
    "flag": os.path.join(STABLE, "flag.png"),
    "hud_left": os.path.join(STABLE, "hud_left.png"),
    "hud_right": os.path.join(STABLE, "hud_right.png"),
    "hud_ship": os.path.join(STABLE, "hud_ship.png"),
    "team_btn": os.path.join(STABLE, "team.png"),
    "invite": os.path.join(STABLE, "invite.png"),
    "invite_all": os.path.join(STABLE, "invite_all.png"),
    "back": os.path.join(STABLE, "back.png"),
    "trading": os.path.join(STABLE, "trading.png"),
    "time_on": os.path.join(STABLE, "rally_time_button_on.png"),
    "time_off": os.path.join(STABLE, "rally_time_button_off.png"),
    "time_3": os.path.join(STABLE, "rally_time_block3.png"),
    "mail": os.path.join(STABLE, "mail.png"),
    "win": os.path.join(STABLE, "win.png"),
    "new": os.path.join(STABLE, "new.png"),
    "loot": os.path.join(STABLE, "loot.png"),
    "chat_tab_on": os.path.join(STABLE, "chat_tab_on.png"),
    "mgmt_tab_on": os.path.join(STABLE, "mgmt_tab_on.png"),
    "collection": os.path.join(STABLE, "collection.png"),
    "starview_1": os.path.join(STABLE, "starview_1.png"),
    "starview_2": os.path.join(STABLE, "starview_2.png"),
    "hunt_area1": os.path.join(STABLE, "hunt_area1.png"),
    "hunt_area2": os.path.join(STABLE, "hunt_area2.png"),
    "hunt_area3": os.path.join(STABLE, "hunt_area3.png"),
    "hunt_area4": os.path.join(STABLE, "hunt_area4.png"),
    "ship_icon": os.path.join(PIC, "ship", "ship_icon.png"),
    "look": os.path.join(STABLE, "look.png"),
    "storage": os.path.join(STABLE, "storage1.png"),
    "ticket_ark": os.path.join(STABLE, "ticket_ark.png"),
    "use": os.path.join(STABLE, "use.png"),
    "use2": os.path.join(STABLE, "use2.png"),
    "ap_more": os.path.join(STABLE, "more.png"),
    "pray100": os.path.join(STABLE, "100.png"),
    "pray100b": os.path.join(STABLE, "100b.png"),
    "good": os.path.join(STABLE, "good.png"),
    "good1": os.path.join(STABLE, "good1.png"),
    "close_btn": os.path.join(STABLE, "close.png"),
}

# 面板上每一项单独对应一个模板。改这里的默认值，再由助手设置覆盖。
THRESH_FIELDS = (
    ("search", "搜寻", 0.80),
    ("search_go", "黄搜寻", 0.88),
    ("tab_tribute", "贡品页签", 0.88),
    ("tab_claw", "爪牙页签", 0.88),
    ("rally_red", "红集结", 0.88),
    ("rally_yellow", "黄确认", 0.88),
    ("goal0_atk", "爪牙攻擊", 0.88),
    ("atk", "船队ATK", 0.95),
    ("repair", "修理", 0.88),
    ("attack", "攻击", 0.88),
    ("event1", "金币活动", 0.88),
    ("teleport", "传送", 0.88),
    ("invite_yes", "对勾", 0.88),
    ("invite_no", "拒绝", 0.88),
    ("prayer_label", "祈祷舰", 0.88),
    ("flag", "组队旗", 0.75),
    ("trading", "跑商", 0.85),
    ("team_btn", "组队", 0.82),
    ("invite", "邀请", 0.88),
    ("invite_all", "邀请全部", 0.88),
    ("back", "返回", 0.88),
    ("time_on", "集结开", 0.90),
    ("time_off", "集结关", 0.95),
    ("time_3", "3分钟块", 0.88),
    ("mail", "邮件", 0.90),
    ("win", "胜利", 0.88),
    ("new", "未读", 0.85),
    ("loot", "奖励", 0.88),
    ("collection", "收藏", 0.88),
    ("starview_1", "星图1", 0.88),
    ("starview_2", "星图2", 0.88),
    ("hunt_area1", "斯芬克斯", 0.88),
    ("hunt_area2", "坎沃", 0.88),
    ("hunt_area3", "克鲁格", 0.88),
    ("hunt_area4", "塞尔诺", 0.88),
    ("look", "查看", 0.88),
    ("storage", "仓储", 0.80),
    ("ticket_ark", "方舟券", 0.88),
    ("use", "使用", 0.88),
    ("use2", "补充使用", 0.88),
    ("ap_more", "获得更多", 0.88),
    ("pray100", "100", 0.88),
    ("pray100b", "100b", 0.88),
    ("good", "点赞", 0.88),
    ("good1", "点赞成功", 0.88),
    ("close_btn", "关闭", 0.88),
    ("ship_icon", "船标", 0.50),
    ("ship_hud", "船标误检", 0.75),
    ("lvl", "等级数字", 0.80),
    ("hud_ship", "船队栏", 0.55),
    ("chat_tab_on", "聊天页", 0.88),
    ("mgmt_tab_on", "管理页", 0.88),
)
THRESH = {key: value for key, _label, value in THRESH_FIELDS}


def thresh_for(name: str) -> float:
    return float(THRESH.get(name, MATCH_THRESH))


_MATCH_SLACK = 0.10
_MATCH_FLOOR = 0.70
# 这几项分差本来就小，或者分数不是同一套，不放宽
_NO_SLACK = {"lvl", "ship_icon", "atk", "flag", "team_btn", "storage", "ship_hud"}


def match_floor(name: str, thresh: float) -> float:
    """自动阈值偏低 0.1 以内、并且不低于 0.7，也算命中。"""
    base = float(thresh)
    if name in _NO_SLACK:
        return base
    return max(_MATCH_FLOOR, round(base - _MATCH_SLACK, 2))


_RECENT_KEEP = 5
_recent_scores: dict[str, list[float]] = {}
_recent_lock = threading.Lock()


_ADAPT_GAP = 0.10
_ADAPT_JUMP = 0.15
_ADAPT_LO = 0.40
_ADAPT_HI = 0.99
_ADAPT_SHIFT = 3
_ADAPT_CAP = {"search": 0.80}
_THRESH_LABEL = {key: label for key, label, _default in THRESH_FIELDS}
_thresh_hooks: list = []
_score_hold: dict[str, int] = {}


def watch_thresh(fn) -> None:
    _thresh_hooks.append(fn)


def _core_mean(buf: list[float]) -> float:
    center = sorted(buf)[len(buf) // 2]
    core = [score for score in buf if abs(score - center) < _ADAPT_JUMP]
    if len(core) < 3:
        core = buf
    return sum(core) / len(core)


def note_match(name: str, score: float) -> None:
    """记下一次命中的最高分，只留最近 5 次。满 5 次后把阈值放到均分低 0.1。"""
    value = round(float(score), 3)
    odd = None
    changed = None
    with _recent_lock:
        buf = _recent_scores.setdefault(name, [])
        if len(buf) >= _RECENT_KEEP:
            mean = _core_mean(buf)
            if abs(value - mean) >= _ADAPT_JUMP:
                hold = _score_hold.get(name, 0) + 1
                _score_hold[name] = hold
                if hold == 1:
                    label = _THRESH_LABEL.get(name, name)
                    odd = f"{label} 最近均分 {mean:.2f}，这次 {value:.2f}，偏了 {value - mean:+.2f}"
                if hold >= _ADAPT_SHIFT:
                    buf.clear()
                    buf.append(value)
                    _score_hold[name] = 0
            else:
                _score_hold[name] = 0
                buf.append(value)
                del buf[:-_RECENT_KEEP]
        else:
            buf.append(value)
            del buf[:-_RECENT_KEEP]
        if len(buf) >= _RECENT_KEEP and name in THRESH:
            target = round(min(_ADAPT_HI, max(_ADAPT_LO, _core_mean(buf) - _ADAPT_GAP)), 2)
            cap = _ADAPT_CAP.get(name)
            if cap is not None:
                target = min(target, cap)
            if abs(float(THRESH[name]) - target) >= 0.005:
                THRESH[name] = target
                changed = target
    if changed is not None:
        publish_thresh()
        for fn in list(_thresh_hooks):
            fn(name, changed)
    if odd:
        import bot

        bot.note_odd("阈值", odd)


def recent_text(name: str) -> str:
    with _recent_lock:
        buf = list(_recent_scores.get(name) or [])
    if not buf:
        return "均 —"
    mean = sum(buf) / len(buf)
    if len(buf) < _RECENT_KEEP:
        return f"均{mean:.2f}/{len(buf)}"
    return f"均{mean:.2f}"


def recent_snapshot() -> dict[str, list[float]]:
    with _recent_lock:
        return {key: list(values) for key, values in _recent_scores.items()}


_PLACE_NEAR = 50
_PLACE_READY = 5
_PLACE_JUMP = 120
_PLACE_CAP = 30
_place_clusters: dict[str, list[list[float]]] = {}


def note_place(name: str, x: int, y: int) -> str | None:
    """记住这个元素出现过的每一处。离所有已知位置都远时，返回一句异常说明。"""
    clusters = _place_clusters.setdefault(name, [])
    x, y = float(int(x)), float(int(y))
    best = None
    best_d = None
    for cluster in clusters:
        dist = ((x - cluster[0]) ** 2 + (y - cluster[1]) ** 2) ** 0.5
        if best_d is None or dist < best_d:
            best, best_d = cluster, dist
    if best is not None and best_d <= _PLACE_NEAR:
        count = best[2]
        best[0] = (best[0] * count + x) / (count + 1)
        best[1] = (best[1] * count + y) / (count + 1)
        best[2] = count + 1
        return None
    total = sum(cluster[2] for cluster in clusters)
    clusters.append([x, y, 1.0])
    if len(clusters) > _PLACE_CAP:
        victim = min(range(len(clusters) - 1), key=lambda i: clusters[i][2])
        del clusters[victim]
    if best is None or total < _PLACE_READY or best_d < _PLACE_JUMP:
        return None
    known = clusters[:-1]
    shown = "、".join(f"({c[0]:.0f},{c[1]:.0f})" for c in known[:6])
    if len(known) > 6:
        shown += f" 等{len(known)}处"
    return f"{name} 已知位置 {shown}，这次在 ({x:.0f},{y:.0f})，离最近一处 {best_d:.0f}px"


def load_recent_scores(raw) -> None:
    if not isinstance(raw, dict):
        return
    cleaned: dict[str, list[float]] = {}
    for key, values in raw.items():
        if not isinstance(key, str) or not isinstance(values, list):
            continue
        scores = []
        for value in values[-_RECENT_KEEP:]:
            try:
                scores.append(round(float(value), 3))
            except (TypeError, ValueError):
                continue
        if scores:
            cleaned[key] = scores
    with _recent_lock:
        _recent_scores.clear()
        _recent_scores.update(cleaned)


def publish_thresh() -> None:
    """旧代码还在读这些名字。设置改完后同步过去。"""
    global SEARCH_THRESH, FLAG_THRESH, TRADING_THRESH, TIME_ON_THRESH, TIME_OFF_THRESH
    global MAIL_THRESH, WIN_THRESH, NEW_THRESH, LOOT_THRESH, ATK_THRESH
    global SHIP_ICON_THRESH, SHIP_HUD_THRESH, LVL_SCORE, HUD_LOC_THRESH, CHAT_TAB_THRESH
    SEARCH_THRESH = THRESH["search"]
    FLAG_THRESH = THRESH["flag"]
    TRADING_THRESH = THRESH["trading"]
    TIME_ON_THRESH = THRESH["time_on"]
    TIME_OFF_THRESH = THRESH["time_off"]
    MAIL_THRESH = THRESH["mail"]
    WIN_THRESH = THRESH["win"]
    NEW_THRESH = THRESH["new"]
    LOOT_THRESH = THRESH["loot"]
    ATK_THRESH = THRESH["atk"]
    SHIP_ICON_THRESH = THRESH["ship_icon"]
    SHIP_HUD_THRESH = THRESH["ship_hud"]
    LVL_SCORE = THRESH["lvl"]
    HUD_LOC_THRESH = THRESH["hud_ship"]
    CHAT_TAB_THRESH = THRESH["chat_tab_on"]
