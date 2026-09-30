"""游戏窗口上的检测框。点击会穿透，不抢焦点。"""
from __future__ import annotations

import ctypes
import threading
import time
import tkinter as tk
from dataclasses import dataclass

from vision import Hit, Matcher, RIGHT_HUD_ONLY, SHIP_BAR_ONLY

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
    "hud_left": "#4CC9F0",
    "hud_right": "#4895EF",
    "hud_ship": "#90E0EF",
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
    "collection": "#F4D35E",
    "starview_1": "#90BE6D",
    "starview_2": "#43AA8B",
    "hunt_area1": "#F94144",
    "hunt_area2": "#F3722C",
    "hunt_area3": "#F8961E",
    "hunt_area4": "#F9C74F",
    "ship_icon": "#277DA1",
    "look": "#577590",
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
    "hud_left": "左HUD",
    "hud_right": "右HUD",
    "hud_ship": "船队栏",
    "team_btn": "组队",
    "invite": "邀请",
    "invite_all": "邀请全部",
    "back": "返回",
    "tab_tribute": "贡品页签",
    "win": "胜利",
    "new": "未读",
    "loot": "奖励",
    "time_on": "集结开",
    "time_off": "集结关",
    "time_3": "3分钟块",
    "invite_yes": "对勾",
    "invite_no": "拒绝",
    "prayer_label": "祈祷舰",
    "teleport": "传送",
    "chat_tab_on": "聊天页",
    "mgmt_tab_on": "管理页",
    "collection": "收藏",
    "starview_1": "星图1",
    "starview_2": "星图2",
    "hunt_area1": "斯芬克斯",
    "hunt_area2": "坎沃",
    "hunt_area3": "克鲁格",
    "hunt_area4": "塞尔诺",
    "ship_icon": "船标",
    "look": "查看",
}

ENABLED = False
SHOWING = False
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
    global _view, ENABLED, SHOWING
    ENABLED = True
    SHOWING = True
    if _view is None:
        _view = Overlay(master)


def hide() -> None:
    global SHOWING, _pending
    SHOWING = False
    with _lock:
        _pending = None
    view = _view
    if view is not None:
        view._dismiss.set()


def wait_dismiss(seconds: float | None = None) -> None:
    """预览标记：点一下或到点后关掉。预览时标记层吃掉点击，避免点进游戏。"""
    if seconds is None:
        seconds = 5.0
    seconds = max(1.0, min(60.0, float(seconds)))
    view = _view
    if view is None:
        time.sleep(seconds)
        hide()
        return
    done = threading.Event()
    aid = {"id": None}

    def arm() -> None:
        global ENABLED, SHOWING
        ENABLED = True
        SHOWING = True
        view._pass_clicks = False
        view._click_ok = False
        view._painted = None
        with _lock:
            data = _pending
        if data is not None:
            rect, hits, regions = data
            view._paint(rect, hits, regions)
        view._apply_style()

        def close(_event=None) -> None:
            if aid["id"] is not None:
                try:
                    view.after_cancel(aid["id"])
                except tk.TclError:
                    pass
            done.set()

        view.bind("<Button-1>", close)
        view.canvas.bind("<Button-1>", close)
        aid["id"] = view.after(int(seconds * 1000), close)

    try:
        view.after(0, arm)
    except tk.TclError:
        time.sleep(seconds)
        hide()
        return
    while not done.wait(0.1):
        if not SHOWING:
            break
    hide()
    try:
        view.after(0, view._restore_pass)
    except tk.TclError:
        pass


def detach() -> None:
    global ENABLED
    ENABLED = False
    hide()


def push(rect, hits: list[Hit] | None = None, regions: list[tuple] | None = None) -> None:
    if not ENABLED or not SHOWING:
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
        self._click_ok = False
        self._geom = ""
        self._painted = None
        self._pass_clicks = True
        self._dismiss = threading.Event()
        self._aligning = False
        self.after(20, self._apply_style)
        self.after(80, self._poll)
        self.withdraw()

    def _hwnd_of(self) -> int:
        user32 = ctypes.windll.user32
        hwnd = int(self.winfo_id())
        parent = int(user32.GetParent(hwnd) or 0)
        return parent or hwnd

    def _apply_style(self) -> None:
        try:
            self.update_idletasks()
            hwnd = self._hwnd_of()
            self._hwnd = hwnd
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= WS_EX_LAYERED
            if self._pass_clicks:
                style |= WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
            else:
                style &= ~WS_EX_TRANSPARENT
                style &= ~WS_EX_NOACTIVATE
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            user32.SetWindowPos(
                hwnd,
                HWND_TOPMOST,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
            )
            self._click_ok = True
        except Exception:
            pass

    def _restore_pass(self) -> None:
        try:
            self.unbind("<Button-1>")
            self.canvas.unbind("<Button-1>")
        except tk.TclError:
            pass
        self._pass_clicks = True
        self._click_ok = False
        self._apply_style()

    def _poll(self) -> None:
        if self._aligning:
            self.after(120, self._poll)
            return
        if not SHOWING or not ENABLED:
            if self.state() != "withdrawn":
                try:
                    self._painted = None
                    self.clear()
                    self.withdraw()
                except tk.TclError:
                    pass
            self.after(120, self._poll)
            return
        with _lock:
            data = _pending
        if data is not None:
            rect, hits, regions = data
            self._paint(rect, hits, regions)
        self.after(120, self._poll)

    def clear(self) -> None:
        self.canvas.delete("all")

    def _paint(self, rect, hits: list[Hit], regions: list[RegionMark]) -> None:
        key = (
            rect.left,
            rect.top,
            rect.width,
            rect.height,
            tuple((r.name, r.x, r.y, r.w, r.h) for r in regions),
            tuple((h.name, round(h.score, 2), h.x1, h.y1, h.x2, h.y2) for h in hits),
        )
        if key == self._painted:
            return
        try:
            geom = f"{rect.width}x{rect.height}+{rect.left}+{rect.top}"
            if geom != self._geom:
                self.geometry(geom)
                self._geom = geom
            if self.state() == "withdrawn":
                self.deiconify()
            if not self._click_ok:
                self._apply_style()
        except tk.TclError:
            return
        self._painted = key
        self.canvas.delete("all")
        for reg in regions:
            x2, y2 = reg.x + reg.w, reg.y + reg.h
            self.canvas.create_rectangle(
                reg.x, reg.y, x2, y2, outline="#00D4FF", width=3, dash=(8, 5)
            )
            self._label(reg.x + 6, reg.y + 6, f"区域 {reg.name}", "#00D4FF")
        for hit in hits:
            color = HIT_COLOR.get(hit.name, "#FFFFFF")
            self.canvas.create_rectangle(hit.x1, hit.y1, hit.x2, hit.y2, outline=color, width=5)
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
        self._fid = 0

    def bind(self, rect) -> None:
        self.rect = rect

    def extra_regions(self, regions: list[tuple]) -> None:
        self._merge([], regions)
        self.flush()

    def flush(self) -> None:
        if not ENABLED or not SHOWING or self.rect is None:
            return
        push(self.rect, self._hits, self._regions)

    def _note_frame(self, frame) -> None:
        fid = id(frame)
        if fid != self._fid:
            self._fid = fid
            self._hits = []
            self._regions = []

    def _merge(self, hits: list[Hit], regions: list[tuple]) -> None:
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

    def find(self, frame, name: str, thresh: float | None = None) -> Hit | None:
        self._note_frame(frame)
        hits = Matcher.find_all(self, frame, name, thresh)
        if name != "hud_ship":
            self._merge(hits[:1], [])
        self.flush()
        return hits[0] if hits else None

    def find_all(self, frame, name: str, thresh: float | None = None) -> list[Hit]:
        self._note_frame(frame)
        hits = Matcher.find_all(self, frame, name, thresh)
        if name != "hud_ship":
            self._merge(hits, [])
        self.flush()
        return hits

    def find_in(self, frame, name: str, region, thresh: float | None = None) -> Hit | None:
        hits = self._hits_in(frame, name, region, thresh)
        return hits[0] if hits else None

    def find_all_in(self, frame, name: str, region, thresh: float | None = None) -> list[Hit]:
        return self._hits_in(frame, name, region, thresh)

    def _hits_in(self, frame, name: str, region, thresh: float | None) -> list[Hit]:
        self._note_frame(frame)
        if name in SHIP_BAR_ONLY or name in RIGHT_HUD_ONLY:
            hits = Matcher.find_all(self, frame, name, thresh)
            self._merge(hits, [])
            return hits
        x, y, w, h = region
        crop = frame[y : y + h, x : x + w]
        raw = Matcher.find_all(self, crop, name, thresh) if crop.size else []
        hits = [
            Hit(hit.name, hit.score, hit.x1 + x, hit.y1 + y, hit.x2 + x, hit.y2 + y)
            for hit in raw
        ]
        # 船队栏已由 mark_rois 画过，旗子搜索窗不要再套一层同名框
        extra = [] if name == "flag" else [(HIT_LABEL.get(name, name), x, y, w, h)]
        self._merge(hits, extra)
        self.flush()
        return hits


# 对齐用的小窗。检测框仍走色键；色键做不到像素级半透明，图会变成一块实心盖住游戏。
WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
ULW_ALPHA = 0x00000002
AC_SRC_ALPHA = 0x01
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001
SWP_NOSIZE = 0x0001
HWND_TOPMOST_PTR = ctypes.c_void_p(-1)
_ghost_proc = None
_ghosts: dict[int, dict] = {}


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_byte),
        ("BlendFlags", ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte),
        ("AlphaFormat", ctypes.c_byte),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", ctypes.c_uint),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", ctypes.c_void_p),
        ("hIcon", ctypes.c_void_p),
        ("hCursor", ctypes.c_void_p),
        ("hbrBackground", ctypes.c_void_p),
        ("lpszMenuName", ctypes.c_wchar_p),
        ("lpszClassName", ctypes.c_wchar_p),
    ]


def _win32():
    """单独一份 user32，避免改到检测框那层用的全局函数签名。"""
    lib = getattr(_win32, "lib", None)
    if lib is not None:
        return lib
    lib = ctypes.WinDLL("user32", use_last_error=True)
    lib.DefWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    lib.DefWindowProcW.restype = ctypes.c_ssize_t
    lib.CreateWindowExW.restype = ctypes.c_void_p
    lib.CreateWindowExW.argtypes = [
        ctypes.c_uint32,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    lib.DestroyWindow.argtypes = [ctypes.c_void_p]
    lib.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(_RECT)]
    lib.SetWindowPos.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    lib.SetCapture.argtypes = [ctypes.c_void_p]
    lib.GetCursorPos.argtypes = [ctypes.POINTER(_POINT)]
    lib.UpdateLayeredWindow.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(_POINT),
        ctypes.POINTER(_SIZE),
        ctypes.c_void_p,
        ctypes.POINTER(_POINT),
        ctypes.c_uint32,
        ctypes.POINTER(_BLENDFUNCTION),
        ctypes.c_uint32,
    ]
    lib.UpdateLayeredWindow.restype = ctypes.c_int
    lib.GetDC.restype = ctypes.c_void_p
    lib.GetDC.argtypes = [ctypes.c_void_p]
    lib.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    _win32.lib = lib
    return lib


def _ghost_wnd_proc(hwnd, msg, wparam, lparam):
    user32 = _win32()
    key = int(hwnd)
    st = _ghosts.get(key)
    if st is not None and msg == WM_LBUTTONDOWN:
        lp = int(lparam) & 0xFFFFFFFF
        st["ox"] = ctypes.c_short(lp & 0xFFFF).value
        st["oy"] = ctypes.c_short((lp >> 16) & 0xFFFF).value
        st["drag"] = True
        user32.SetCapture(hwnd)
        return 0
    if st is not None and msg == WM_MOUSEMOVE and st.get("drag") and (int(wparam) & MK_LBUTTON):
        pt = _POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetWindowPos(
            hwnd,
            HWND_TOPMOST_PTR,
            pt.x - st["ox"],
            pt.y - st["oy"],
            0,
            0,
            SWP_NOSIZE | SWP_NOACTIVATE,
        )
        return 0
    if st is not None and msg == WM_LBUTTONUP:
        st["drag"] = False
        user32.ReleaseCapture()
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def _ensure_ghost_class() -> None:
    global _ghost_proc
    if _ghost_proc is not None:
        return
    _ghost_proc = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t
    )(_ghost_wnd_proc)
    user32 = _win32()
    wc = _WNDCLASSW()
    wc.lpfnWndProc = ctypes.cast(_ghost_proc, ctypes.c_void_p)
    wc.hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)
    wc.hCursor = user32.LoadCursorW(None, 32512)
    wc.lpszClassName = "FgfHudAlign"
    user32.RegisterClassW(ctypes.byref(wc))


def _gdi32():
    lib = getattr(_gdi32, "lib", None)
    if lib is not None:
        return lib
    lib = ctypes.WinDLL("gdi32", use_last_error=True)
    lib.CreateCompatibleDC.restype = ctypes.c_void_p
    lib.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    lib.DeleteDC.argtypes = [ctypes.c_void_p]
    lib.CreateDIBSection.restype = ctypes.c_void_p
    lib.CreateDIBSection.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    lib.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.SelectObject.restype = ctypes.c_void_p
    lib.DeleteObject.argtypes = [ctypes.c_void_p]
    _gdi32.lib = lib
    return lib


def _present_ghost(hwnd: int, bgra) -> bool:
    """bgra 已预乘。UpdateLayeredWindow 把透明像素真正合成到游戏上。"""
    import numpy as np

    user32 = _win32()
    gdi32 = _gdi32()
    h, w = bgra.shape[:2]
    bmi = _BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    hdc_screen = user32.GetDC(None)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    bits = ctypes.c_void_p()
    hbmp = gdi32.CreateDIBSection(hdc_screen, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    if not hbmp or not bits:
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(None, hdc_screen)
        return False
    buf = np.ascontiguousarray(bgra)
    ctypes.memmove(bits, buf.ctypes.data, buf.nbytes)
    old = gdi32.SelectObject(hdc_mem, hbmp)
    blend = _BLENDFUNCTION(0, 0, 255, AC_SRC_ALPHA)
    dst = _POINT(0, 0)
    src = _POINT(0, 0)
    size = _SIZE(w, h)
    wr = _RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(wr))
    dst.x = wr.left
    dst.y = wr.top
    ok = user32.UpdateLayeredWindow(
        hwnd, hdc_screen, ctypes.byref(dst), ctypes.byref(size), hdc_mem, ctypes.byref(src), 0, ctypes.byref(blend), ULW_ALPHA
    )
    gdi32.SelectObject(hdc_mem, old)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(None, hdc_screen)
    return bool(ok)


def _ghost_bitmap(path: str):
    import cv2
    import numpy as np

    im = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if im is None:
        return None
    if im.ndim == 2:
        im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGRA)
    elif im.shape[2] == 3:
        im = cv2.cvtColor(im, cv2.COLOR_BGR2BGRA)
    h, w = im.shape[:2]
    bgr = im[:, :, :3].astype(np.float32)
    src_a = im[:, :, 3].astype(np.float32) / 255.0
    alpha = np.clip(src_a * 0.32 * 255.0, 0, 255).astype(np.uint8)
    # 边上留一圈，方便对准，中间仍透出游戏
    alpha[0, :] = 210
    alpha[-1, :] = 210
    alpha[:, 0] = 210
    alpha[:, -1] = 210
    bgr[0, :] = (80, 255, 255)
    bgr[-1, :] = (80, 255, 255)
    bgr[:, 0] = (80, 255, 255)
    bgr[:, -1] = (80, 255, 255)
    af = alpha.astype(np.float32) / 255.0
    out = np.zeros((h, w, 4), np.uint8)
    out[:, :, 0] = np.clip(bgr[:, :, 0] * af, 0, 255).astype(np.uint8)
    out[:, :, 1] = np.clip(bgr[:, :, 1] * af, 0, 255).astype(np.uint8)
    out[:, :, 2] = np.clip(bgr[:, :, 2] * af, 0, 255).astype(np.uint8)
    out[:, :, 3] = alpha
    return out


def align_hud(master, rect, specs: list[tuple], on_done) -> None:
    """每张 HUD 一个真透明小窗，拖到游戏上。完成时 on_done({名字: [x, y]})，取消为 None。"""
    hide()
    _ensure_ghost_class()
    user32 = _win32()
    made: list[tuple[str, int]] = []
    for name, path, x, y in specs:
        bgra = _ghost_bitmap(path)
        if bgra is None:
            continue
        h, w = bgra.shape[:2]
        hwnd = user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            "FgfHudAlign",
            name,
            WS_POPUP,
            int(rect.left + x),
            int(rect.top + y),
            w,
            h,
            None,
            None,
            ctypes.windll.kernel32.GetModuleHandleW(None),
            None,
        )
        if not hwnd:
            continue
        _ghosts[int(hwnd)] = {"drag": False, "ox": 0, "oy": 0}
        if not _present_ghost(int(hwnd), bgra):
            user32.DestroyWindow(hwnd)
            _ghosts.pop(int(hwnd), None)
            continue
        user32.ShowWindow(hwnd, 8)
        made.append((name, int(hwnd)))

    dlg = tk.Toplevel(master)
    dlg.title("对齐HUD")
    dlg.attributes("-topmost", True)
    dlg.resizable(False, False)
    tk.Label(dlg, text="拖画面上的图对准游戏。透明处能看见游戏。").pack(padx=12, pady=(10, 4))
    row = tk.Frame(dlg)
    row.pack(padx=12, pady=(0, 10))
    alive = {"on": True}

    def finish(save: bool) -> None:
        if not alive["on"]:
            return
        alive["on"] = False
        data = {}
        for name, hwnd in made:
            box = _RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(box))
            data[name] = [int(box.left - rect.left), int(box.top - rect.top)]
            _ghosts.pop(hwnd, None)
            user32.DestroyWindow(hwnd)
        made.clear()
        try:
            dlg.destroy()
        except tk.TclError:
            pass
        on_done(data if save else None)

    tk.Button(row, text="完成", command=lambda: finish(True), width=10).pack(side=tk.LEFT, padx=4)
    tk.Button(row, text="取消", command=lambda: finish(False), width=10).pack(side=tk.LEFT, padx=4)
    dlg.protocol("WM_DELETE_WINDOW", lambda: finish(False))
    try:
        dlg.geometry(f"+{master.winfo_rootx() + 40}+{master.winfo_rooty() + 80}")
    except tk.TclError:
        pass
    if not made:
        finish(False)

