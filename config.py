"""初版配置。超时、等级、人数以后再改。"""
from __future__ import annotations

import os

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
ATK_MIN_FIGHT = 12.0
ATK_STREAK = 2
ATK_CLICK_CONFIRM = 3.0
HUD_LOC_THRESH = 0.55
# 右HUD贴右边；底下留给底栏/小地图（1920x1080 上约 144px）
HUD_RIGHT_BOTTOM_GAP = 144
SHIP_ICON_THRESH = 0.50
# 船标模板：pic/ship/tpl/ship_000.png … ship_337.png，已是 HSV 二值。不再现场旋转彩色 icon。
SHIP_TPL = os.path.join(PIC, "ship", "tpl")
SHIP_HUD_NAMES = ("hud1.png", "hud2.png", "hud3.png")
SHIP_HUD_THRESH = 0.75
# OpenCV HSV。船体亮灰绿。
SHIP_HSV_LO = (28, 25, 110)
SHIP_HSV_HI = (45, 70, 210)
# 点「查看」之后，在船标附近认等级。灰度二值，和 pic/lvl/tpl 同一套。
LVL_TPL = os.path.join(PIC, "lvl", "tpl")
LVL_MIN = 16
LVL_MAX = 22
LVL_GRAY = 120
LVL_SCORE = 0.80
LVL_MARGIN = 0.08
# 相对船标中心：左、上、右、下
LVL_NEAR = (160, 140, 160, 80)
WHEEL_PAUSE = 0.2
WHEEL_MAX = 40
SHIP_STILL_SEC = 8.0
SHIP_STILL_PX = 50
PATROL_EXTRA_WHEEL = 10
PATROL_PAN_PX = 200
MARK_PREVIEW_SEC = 5
# 第一条邮件同一行：相对胜利标的 y 容差
MAIL_ROW_DY = 100

CLICK_PAUSE = 1.2
CLICK_HOLD = 0.08
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
    "search_go": os.path.join(STABLE, "button4.png"),
    "rally_red": os.path.join(STABLE, "button5.png"),
    "rally_yellow": os.path.join(STABLE, "rally_confirm.png"),
    "attack": os.path.join(STABLE, "button.png"),
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
}

# 面板上每一项单独对应一个模板。改这里的默认值，再由助手设置覆盖。
THRESH_FIELDS = (
    ("search", "搜寻", 0.80),
    ("search_go", "黄搜寻", 0.88),
    ("tab_tribute", "贡品页签", 0.88),
    ("rally_red", "红集结", 0.88),
    ("rally_yellow", "黄确认", 0.88),
    ("goal0_atk", "爪牙攻擊", 0.88),
    ("atk", "船队ATK", 0.95),
    ("repair", "修理", 0.88),
    ("attack", "攻击", 0.88),
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
    ("ship_icon", "船标", 0.50),
    ("ship_hud", "船标误检", 0.75),
    ("lvl", "等级", 0.80),
    ("hud_ship", "船队栏", 0.55),
    ("chat_tab_on", "聊天页", 0.88),
    ("mgmt_tab_on", "管理页", 0.88),
)
THRESH = {key: value for key, _label, value in THRESH_FIELDS}


def thresh_for(name: str) -> float:
    return float(THRESH.get(name, MATCH_THRESH))


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
