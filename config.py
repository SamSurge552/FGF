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
# 第一条邮件同一行：相对胜利标的 y 容差
MAIL_ROW_DY = 100

CLICK_PAUSE = 1.2
CLICK_HOLD = 0.08
PANEL_WAIT = 8.0
SHIP_WAIT = 10.0
SETTINGS_WAIT = 8.0
RALLY_RED_WAIT = 5.0
RALLY_WAIT = 300.0
INVITE_WAIT = 30.0
LOOP_SLEEP = 0.4
DEFAULT_COUNT = 10

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
    "ship": os.path.join(STABLE, "ship.png"),
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
}
