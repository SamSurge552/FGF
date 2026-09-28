"""游戏窗口上的检测框。点击会穿透，不抢焦点。"""
from __future__ import annotations

import ctypes
import threading
import time
import tkinter as tk
from dataclasses import dataclass

from vision import Hit, Matcher

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

# 纯黑当透明色；画框用别的颜色
TRANS = "#000000"

HIT_COLOR = {
    "search": "#7CFF3B",
    "search_go": "#C77DFF",
    "goal0_atk": "#FFD23B",
    "atk": "#FF3B3B",
    "repair": "#FF9F1C",
    "attack": "#FFD23B",
    "mail": "#4CC9F0",
    "rally_red": "#FF4D6D",
    "rally_yellow": "#FFE66D",
    "flag": "#FF6B6B",
    "ship": "#90E0EF",
    "team_btn": "#48CAE4",
    "invite": "#64DFDF",
    "invite_all": "#80FFDB",
    "back": "#B8C0FF",
    "tab_tribute": "#F72585",
    "win": "#FEE440",
    "new": "#9B5DE5",
    "loot": "#00F5D4",
    "time_on": "#80ED99",
    "time_off": "#8D99AE",
    "time_3": "#F4A261",
    "invite_yes": "#80ED99",
    "invite_no": "#F94144",
    "prayer_label": "#F9C74F",
    "teleport": "#ADB5BD",
    "chat_tab_on": "#BDE0FE",
    "mgmt_tab_on": "#FFAFCC",
}

HIT_LABEL = {
    "search": "搜寻",
    "search_go": "黄搜寻",
    "goal0_atk": "攻擊",
    "atk": "战斗中",
    "repair": "修理",
    "attack": "攻击",
    "mail": "邮件",
    "rally_red": "红集结",
    "rally_yellow": "黄确认",
    "flag": "组队旗",
    "ship": "船队栏",
    "team_btn": "组队",
    "invite": "邀请",
    "invite_all": "邀请全部",
    "back": "返回",
    "tab_tribute": "贡品页签",
    "win": "胜利",
    "new": "未读",
    "loot": "奖励",
    "time_on": "时间开",
    "time_off": "时间关",
    "time_3": "3分钟块",
    "invite_yes": "对勾",
    "invite_no": "拒绝",
    "prayer_label": "祈祷舰",
    "teleport": "传送",
    "chat_tab_on": "聊天页",
    "mgmt_tab_on": "管理页",
}

ENABLED = False
_lock = threading.Lock()
_pending: tuple | None = None
_view = None


@dataclass
class RegionMark:
    name: str
    x: int
    y: int
    w: int
    h: int


def attach(master: tk.Misc) -> None:
    global _view, ENABLED
    ENABLED = True
    if _view is None:
        _view = Overlay(master)


def detach() -> None:
    global ENABLED, _pending
    ENABLED = False
    with _lock:
        _pending = None
    view = _view
    if view is not None:
        try:
            view.clear()
            view.withdraw()
        except tk.TclError:
            pass


def push(rect, hits: list[Hit] | None = None, regions: list[tuple] | None = None) -> None:
    if not ENABLED:
        return
    regs = []
    for item in regions or []:
        if len(item) == 5:
            name, x, y, w, h = item
            regs.append(RegionMark(str(name), int(x), int(y), int(w), int(h)))
        elif len(item) == 4:
            x, y, w, h = item
            regs.append(RegionMark("区域", int(x), int(y), int(w), int(h)))
    with _lock:
        global _pending
        _pending = (rect, list(hits or []), regs)


class Overlay(tk.Toplevel):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=TRANS)
        try:
            self.attributes("-transparentcolor", TRANS)
        except tk.TclError:
            pass
        self.canvas = tk.Canvas(self, bg=TRANS, highlightthickness=0, bd=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self._hwnd = 0
        self.after(20, self._clickthrough)
        self.after(50, self._poll)
        self.withdraw()

    def _hwnd_of(self) -> int:
        user32 = ctypes.windll.user32
        hwnd = int(self.winfo_id())
        parent = int(user32.GetParent(hwnd) or 0)
        return parent or hwnd

    def _clickthrough(self) -> None:
        try:
            self.update_idletasks()
            hwnd = self._hwnd_of()
            self._hwnd = hwnd
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(
                hwnd,
                GWL_EXSTYLE,
                style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE,
            )
            user32.SetWindowPos(
                hwnd,
                HWND_TOPMOST,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
            )
        except Exception:
            pass

    def _poll(self) -> None:
        if not ENABLED:
            self.after(80, self._poll)
            return
        with _lock:
            data = _pending
        if data is not None:
            rect, hits, regions = data
            self._paint(rect, hits, regions)
        try:
            master = self.master
            if master is not None:
                master.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.after(80, self._poll)

    def clear(self) -> None:
        self.canvas.delete("all")

    def _paint(self, rect, hits: list[Hit], regions: list[RegionMark]) -> None:
        try:
            self.geometry(f"{rect.width}x{rect.height}+{rect.left}+{rect.top}")
            if self.state() == "withdrawn":
                self.deiconify()
            self._clickthrough()
        except tk.TclError:
            return
        self.canvas.delete("all")
        for reg in regions:
            x2, y2 = reg.x + reg.w, reg.y + reg.h
            self.canvas.create_rectangle(
                reg.x, reg.y, x2, y2, outline="#00D4FF", width=3, dash=(8, 5)
            )
            self._label(reg.x + 6, reg.y + 6, f"区域 {reg.name}", "#00D4FF")
        for hit in hits:
            color = HIT_COLOR.get(hit.name, "#FFFFFF")
            self.canvas.create_rectangle(hit.x1, hit.y1, hit.x2, hit.y2, outline=color, width=4)
            cx, cy = hit.center
            r = 8
            self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, outline=color, width=3)
            self.canvas.create_line(cx - 16, cy, cx + 16, cy, fill=color, width=3)
            self.canvas.create_line(cx, cy - 16, cx, cy + 16, fill=color, width=3)
            name = HIT_LABEL.get(hit.name, hit.name)
            self._label(hit.x1, max(4, hit.y1 - 28), f"{name} {hit.score:.2f}", color)

    def _label(self, x: int, y: int, text: str, color: str) -> None:
        pad = 4
        tag = self.canvas.create_text(x + pad, y + pad, text=text, fill=color, anchor="nw", font=("Segoe UI", 12, "bold"))
        box = self.canvas.bbox(tag)
        if box:
            self.canvas.create_rectangle(
                box[0] - 3, box[1] - 2, box[2] + 3, box[3] + 2, fill="#101010", outline=color, width=1
            )
            self.canvas.tag_raise(tag)


class LiveMatcher(Matcher):
    """在每一次 find / find_in 时把区域和命中推到屏幕上。"""

    def __init__(self) -> None:
        super().__init__()
        self.rect = None
        self._hits: list[Hit] = []
        self._regions: list[tuple] = []
        self._t = 0.0

    def bind(self, rect) -> None:
        self.rect = rect

    def extra_regions(self, regions: list[tuple]) -> None:
        self._emit([], regions)

    def _emit(self, hits: list[Hit], regions: list[tuple]) -> None:
        if not ENABLED or self.rect is None:
            return
        now = time.time()
        if now - self._t > 0.25:
            self._hits = []
            self._regions = []
        for hit in hits:
            self._hits = [
                old
                for old in self._hits
                if not (old.name == hit.name and abs(old.x1 - hit.x1) < 6 and abs(old.y1 - hit.y1) < 6)
            ]
            self._hits.append(hit)
        for item in regions:
            if item not in self._regions:
                self._regions.append(item)
        self._t = now
        push(self.rect, self._hits, self._regions)

    def find(self, frame, name: str, thresh: float | None = None) -> Hit | None:
        hits = Matcher.find_all(self, frame, name, thresh)
        self._emit(hits[:1], [])
        return hits[0] if hits else None

    def find_all(self, frame, name: str, thresh: float | None = None) -> list[Hit]:
        hits = Matcher.find_all(self, frame, name, thresh)
        self._emit(hits, [])
        return hits

    def find_in(self, frame, name: str, region, thresh: float | None = None) -> Hit | None:
        hits = self._hits_in(frame, name, region, thresh)
        return hits[0] if hits else None

    def find_all_in(self, frame, name: str, region, thresh: float | None = None) -> list[Hit]:
        return self._hits_in(frame, name, region, thresh)

    def _hits_in(self, frame, name: str, region, thresh: float | None) -> list[Hit]:
        x, y, w, h = region
        crop = frame[y : y + h, x : x + w]
        raw = Matcher.find_all(self, crop, name, thresh) if crop.size else []
        hits = [
            Hit(hit.name, hit.score, hit.x1 + x, hit.y1 + y, hit.x2 + x, hit.y2 + y)
            for hit in raw
        ]
        label = HIT_LABEL.get(name, name)
        self._emit(hits, [(label, x, y, w, h)])
        return hits
