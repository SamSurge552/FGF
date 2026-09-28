from __future__ import annotations

import ctypes
import ctypes.wintypes
import time
from dataclasses import dataclass

import mss
import numpy as np

from config import GAME_SIZE

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32
shell32 = ctypes.windll.shell32
user32.SetProcessDPIAware()

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


def is_admin() -> bool:
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    """弹出 UAC，用管理员重新打开 gui.py。成功则返回 True（调用方应退出）。"""
    if is_admin():
        return False
    import os
    import sys

    script = os.path.abspath(os.path.join(os.path.dirname(__file__), "gui.py"))
    cwd = os.path.dirname(script)
    params = f'"{script}"'
    rc = int(shell32.ShellExecuteW(None, "runas", sys.executable, params, cwd, 1))
    return rc > 32


@dataclass
class WindowRect:
    left: int
    top: int
    width: int
    height: int
    title: str = ""
    hwnd: int = 0

    @property
    def bbox(self) -> dict:
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }


def _thread_id(hwnd: int) -> int:
    pid = ctypes.wintypes.DWORD()
    return int(user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)))


def focus_window(rect: WindowRect) -> bool:
    """把游戏拉到前台。后台线程点「开始」后 Windows 经常不让抢焦点，要点不进游戏。"""
    hwnd = int(rect.hwnd or 0)
    if not hwnd:
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)
    fg = user32.GetForegroundWindow()
    if fg == hwnd:
        return True
    cur = kernel32.GetCurrentThreadId()
    fg_tid = _thread_id(fg) if fg else 0
    tgt_tid = _thread_id(hwnd)
    if fg_tid:
        user32.AttachThreadInput(cur, fg_tid, True)
    user32.AttachThreadInput(cur, tgt_tid, True)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    if fg_tid:
        user32.AttachThreadInput(cur, fg_tid, False)
    user32.AttachThreadInput(cur, tgt_tid, False)
    if user32.GetForegroundWindow() != hwnd:
        user32.keybd_event(0x12, 0, 0, 0)
        user32.SetForegroundWindow(hwnd)
        user32.keybd_event(0x12, 0, 2, 0)
    return user32.GetForegroundWindow() == hwnd


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_ushort),
        ("wParamH", ctypes.c_ushort),
    ]


class _INPUTdata(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("data", _INPUTdata)]


def _abs_mouse(x: int, y: int) -> tuple[int, int]:
    vx = user32.GetSystemMetrics(76)
    vy = user32.GetSystemMetrics(77)
    vw = user32.GetSystemMetrics(78)
    vh = user32.GetSystemMetrics(79)
    ax = int(round((int(x) - vx) * 65535 / max(vw - 1, 1)))
    ay = int(round((int(y) - vy) * 65535 / max(vh - 1, 1)))
    return ax, ay


def screen_click(x: int, y: int, hold: float = 0.08) -> None:
    """SendInput；游戏若以管理员运行而脚本不是，点击会被系统丢掉。"""
    ax, ay = _abs_mouse(x, y)
    flags_move = 0x0001 | 0x8000 | 0x4000  # MOVE | ABSOLUTE | VIRTUALDESK
    extra = ULONG_PTR(0)

    def send(flags: int) -> None:
        inp = _INPUT()
        inp.type = 0
        inp.data.mi = _MOUSEINPUT(ax, ay, 0, flags, 0, extra)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))

    send(flags_move)
    time.sleep(0.05)
    send(flags_move | 0x0002)
    time.sleep(hold)
    send(flags_move | 0x0004)


def screen_key(vk: int, hold: float = 0.05) -> None:
    """SendInput 按键。和点击一样，游戏是管理员时脚本也必须是。"""
    extra = ULONG_PTR(0)

    def send(flags: int) -> None:
        inp = _INPUT()
        inp.type = 1
        inp.data.ki = _KEYBDINPUT(vk, 0, flags, 0, extra)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))

    send(0)
    time.sleep(hold)
    send(0x0002)


def _enum_windows() -> list[WindowRect]:
    out: list[WindowRect] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(hwnd, _lp):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        rect = ctypes.wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rect))
        pt = ctypes.wintypes.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(pt))
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w >= 800 and h >= 500:
            out.append(WindowRect(pt.x, pt.y, w, h, buf.value, int(hwnd)))
        return True

    user32.EnumWindows(cb, 0)
    return out


def list_windows() -> list[WindowRect]:
    return _enum_windows()


def pick_game_window() -> WindowRect:
    want_w, want_h = GAME_SIZE
    cands = [w for w in _enum_windows() if w.width == want_w and w.height == want_h]
    if not cands:
        # 主屏整屏也按 1920x1080 试
        with mss.mss() as sct:
            mon = sct.monitors[1]
            return WindowRect(mon["left"], mon["top"], mon["width"], mon["height"], "primary")
    for w in cands:
        t = w.title.lower()
        if "foundation" in t or "galactic" in t or "launcher" in t:
            return w
    return cands[0]


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


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER)]


def _grab_pixels(hdc_mem, hbmp, w: int, h: int) -> np.ndarray:
    bmi = _BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0
    buf = (ctypes.c_ubyte * (w * h * 4))()
    gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bmi), 0)
    arr = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)
    return arr[:, :, :3].copy()


def _grab_hwnd(hwnd: int, client_w: int, client_h: int) -> np.ndarray | None:
    win = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(win))
    ww, wh = win.right - win.left, win.bottom - win.top
    if ww <= 0 or wh <= 0:
        return None
    pt = ctypes.wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    ox, oy = pt.x - win.left, pt.y - win.top
    hdc_win = user32.GetDC(hwnd)
    if not hdc_win:
        return None
    hdc_mem = gdi32.CreateCompatibleDC(hdc_win)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_win, ww, wh)
    gdi32.SelectObject(hdc_mem, hbmp)
    ok = user32.PrintWindow(hwnd, hdc_mem, 2)
    if not ok:
        user32.PrintWindow(hwnd, hdc_mem, 0)
    full = _grab_pixels(hdc_mem, hbmp, ww, wh)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(hwnd, hdc_win)
    if float(full.mean()) < 2.0:
        return None
    x2, y2 = ox + client_w, oy + client_h
    if ox < 0 or oy < 0 or x2 > ww or y2 > wh:
        return None
    return full[oy:y2, ox:x2]


def grab(rect: WindowRect) -> np.ndarray:
    if rect.hwnd:
        img = _grab_hwnd(int(rect.hwnd), rect.width, rect.height)
        if img is not None:
            return img
    with mss.mss() as sct:
        raw = np.array(sct.grab(rect.bbox))
    return raw[:, :, :3]
