"""FGF 本地控制台。双击 start.bat 或: python gui.py"""
from __future__ import annotations

import json
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk

import bot
import calibrate
import config
from capture import focus_window, is_admin, list_windows, pick_game_window, relaunch_as_admin

SETTINGS_PATH = os.path.join(config.ROOT, "gui_settings.json")


GOALS = (
    (0, "0  爪牙"),
    (1, "1  贡品"),
    (2, "2  祈祷"),
    (3, "3  巡逻"),
)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        admin = is_admin()
        self.title("FGF 助手" + ("（管理员）" if admin else "（普通权限）"))
        self.geometry("520x620+12+12")
        self.minsize(480, 480)
        self.attributes("-topmost", True)
        self.running = False
        self._delay = None

        self._spins: list[ttk.Spinbox] = []
        saved = load_gui_settings()
        self.goal = tk.IntVar(value=saved["goal"])
        self.count = tk.IntVar(value=saved["count"])
        self.mode = tk.StringVar(value="scan" if saved.get("mode") == "scan" or saved.get("hud_test") else "click")
        self.hud_test = tk.BooleanVar(value=self.mode.get() == "scan")
        self.infinite = tk.BooleanVar(value=bool(saved.get("infinite", False)))
        self.rally_minutes = tk.IntVar(value=saved["rally_minutes"])
        self.thresh_vars: dict[str, tk.DoubleVar] = {}
        saved_thresh = saved.get("thresh") or {}
        for key, _label, default in config.THRESH_FIELDS:
            self.thresh_vars[key] = tk.DoubleVar(value=float(saved_thresh.get(key, default)))
        self.ship_still_sec = tk.IntVar(value=int(saved.get("ship_still_sec", 8)))
        self.ship_still_px = tk.IntVar(value=int(saved.get("ship_still_px", 50)))
        self.lvl_min = tk.IntVar(value=int(saved.get("lvl_min", 16)))
        self.lvl_max = tk.IntVar(value=int(saved.get("lvl_max", 22)))
        self.wheel_pause = tk.DoubleVar(value=float(saved.get("wheel_pause", 0.2)))
        self.mark_preview_sec = tk.IntVar(value=int(saved.get("mark_preview_sec", 5)))
        self.show_marks = tk.BooleanVar(value=bool(saved.get("show_marks", True)))

        pad = {"padx": 10, "pady": 6}
        frm = ttk.Frame(self, padding=8)
        frm.pack(fill=tk.BOTH, expand=True)

        gbox = ttk.LabelFrame(frm, text="目标")
        gbox.pack(fill=tk.X, **pad)
        for val, label in GOALS:
            ttk.Radiobutton(gbox, text=label, variable=self.goal, value=val).pack(side=tk.LEFT, padx=8, pady=6)

        row = ttk.Frame(frm)
        row.pack(fill=tk.X, **pad)
        ttk.Label(row, text="次数").pack(side=tk.LEFT)
        self._spin(row, from_=1, to=99, textvariable=self.count, width=6).pack(side=tk.LEFT, padx=8)

        mbox = ttk.LabelFrame(frm, text="动作")
        mbox.pack(fill=tk.X, **pad)
        ttk.Checkbutton(mbox, text="HUD测试", variable=self.hud_test).pack(side=tk.LEFT, padx=8, pady=6)
        ttk.Checkbutton(mbox, text="无限", variable=self.infinite).pack(side=tk.LEFT, padx=8, pady=6)
        ttk.Checkbutton(mbox, text="屏幕标记", variable=self.show_marks, command=self.on_marks).pack(
            side=tk.LEFT, padx=12, pady=6
        )

        btns = ttk.Frame(frm)
        btns.pack(fill=tk.X, **pad)
        self.btn_start = ttk.Button(btns, text="开始", command=self.start)
        self.btn_start.pack(side=tk.LEFT)
        self.btn_stop = ttk.Button(btns, text="停止", command=self.stop, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=8)
        ttk.Label(btns, text="F12 也能停").pack(side=tk.LEFT, padx=8)
        tools = ttk.Frame(frm)
        tools.pack(fill=tk.X, **pad)
        ttk.Button(tools, text="设置", command=self.open_settings).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(tools, text="对齐HUD", command=self.align_panels).pack(side=tk.LEFT, padx=4)
        ttk.Button(tools, text="重置校准", command=self.reset_cal).pack(side=tk.LEFT, padx=4)
        if not admin:
            ttk.Button(tools, text="以管理员运行", command=self.elevate).pack(side=tk.LEFT, padx=4)

        logbox = ttk.LabelFrame(frm, text="日志")
        logbox.pack(fill=tk.BOTH, expand=True, **pad)
        self.log = tk.Text(logbox, height=16, wrap=tk.WORD, state=tk.DISABLED)
        scroll = ttk.Scrollbar(logbox, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.pack(fill=tk.BOTH, expand=True)

        bot.LOG_HOOK = self.append_log
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        if admin:
            self.append_log("已是管理员。窗口会留在左上角，不再最小化。")
        else:
            self.append_log("现在是普通权限。若游戏是管理员启动，点「以管理员运行」后再开始，否则经常能移鼠标却点不进去。")
        self.append_log("开始后别点助手，让游戏保持前台。窗口尽量别挡住右下角搜寻。")
        self.append_log(
            f"已恢复上次设置  目标{saved['goal']}  次数{saved['count']}  "
            f"模式={saved['mode']}  集结{saved['rally_minutes']}分钟  "
            f"船标{float(saved.get('thresh', {}).get('ship_icon', 0.50)):.2f}  "
            f"组队{float(saved.get('thresh', {}).get('team_btn', 0.82)):.2f}  "
            f"静止{int(saved.get('ship_still_sec', 8))}s/{int(saved.get('ship_still_px', 50))}px  "
            f"等级{int(saved.get('lvl_min', 16))}-{int(saved.get('lvl_max', 22))}  "
            f"滚轮{float(saved.get('wheel_pause', 0.2)):.2f}s"
        )
        self.apply_settings()
        t0 = calibrate.timeouts_goal0()
        t1 = calibrate.timeouts_goal1()
        self.append_log(
            f"爪牙校准 样本{int(t0['samples'])} 中位{t0['median']:.1f}s  "
            f"最短{t0['min_fight']:.0f}s 超时{t0['gone_wait']:.0f}s"
        )
        self.append_log(
            f"贡品校准 样本{int(t1['samples'])} 中位{t1['median']:.1f}s  "
            f"出场{t1['appear_wait']:.0f}s 最短{t1['min_rally']:.0f}s 超时{t1['gone_wait']:.0f}s"
        )
        self.show_windows()

    def append_log(self, line: str) -> None:
        def _write() -> None:
            self.log.configure(state=tk.NORMAL)
            self.log.insert(tk.END, line.rstrip() + "\n")
            self.log.see(tk.END)
            self.log.configure(state=tk.DISABLED)

        self.after(0, _write)

    def set_running(self, on: bool) -> None:
        self.running = on
        self.btn_start.configure(state=tk.DISABLED if on else tk.NORMAL)
        self.btn_stop.configure(state=tk.NORMAL if on else tk.DISABLED)
        import overlay

        if on:
            if self.show_marks.get():
                overlay.attach(self)
        else:
            overlay.hide()
            bot.cue_stop()

    def on_marks(self) -> None:
        import overlay

        if not self.show_marks.get():
            overlay.detach()
        elif self.running:
            overlay.attach(self)
        else:
            overlay.hide()

    def elevate(self) -> None:
        self.append_log("正在申请管理员…同意 UAC 后会再开一个窗口，把这个关掉即可。")
        if relaunch_as_admin():
            self.on_close()
        else:
            self.append_log("没要到管理员权限（取消了 UAC？）")

    def start(self) -> None:
        if self.running:
            return
        try:
            count = int(self.count.get())
        except (tk.TclError, ValueError):
            count = 10
        count = max(1, min(99, count))
        self.count.set(count)
        mode = "scan" if self.hud_test.get() else "click"
        goal = int(self.goal.get())
        click = mode == "click"
        self.set_running(True)
        bot.cue_start()
        applied = self.apply_settings()
        self.save_settings()
        self.append_log(
            f"开始  目标{goal}  次数{count}{'  无限' if applied.get('infinite') else ''}  模式={mode}"
        )
        self._delay = None
        if click:
            rect = pick_game_window()
            focus_window(rect)
            self.append_log("已切到游戏，2 秒后动手（别点助手）")
            self._delay = self.after(2000, lambda: self._spawn(goal, count, click, False))
        else:
            import overlay

            overlay.attach(self)
            self.append_log("HUD测试：标出当前能匹配到的组件，到测试显示秒数或点一下后关")
            self._spawn(goal, count, click, False)

    def _spin(self, parent, **kwargs) -> ttk.Spinbox:
        spin = ttk.Spinbox(parent, **kwargs)
        self._spins.append(spin)
        return spin

    def _commit_spins(self) -> None:
        """数字框里刚改的值，要点别的地方才会写进变量。存盘前先读框里的字。"""
        for spin in self._spins:
            try:
                raw = spin.get()
            except tk.TclError:
                continue
            name = str(spin.cget("textvariable"))
            if name:
                self.setvar(name, raw)

    def _clamp_thresh(self, var: tk.DoubleVar, default: float) -> float:
        try:
            value = float(var.get())
        except (tk.TclError, ValueError):
            value = default
        value = max(0.40, min(0.99, value))
        var.set(round(value, 2))
        return value

    def _clamp_int(self, var: tk.IntVar, lo: int, hi: int, default: int) -> int:
        try:
            value = int(var.get())
        except (tk.TclError, ValueError):
            value = default
        value = max(lo, min(hi, value))
        var.set(value)
        return value

    def _clamp_span(self, var: tk.DoubleVar, lo: float, hi: float, default: float) -> float:
        try:
            value = float(var.get())
        except (tk.TclError, ValueError):
            value = default
        value = max(lo, min(hi, value))
        value = round(value, 2)
        var.set(value)
        return value

    def open_settings(self) -> None:
        win = tk.Toplevel(self)
        win.title("设置")
        win.geometry("760x820+40+20")
        win.minsize(760, 640)
        win.transient(self)
        spins: list[ttk.Spinbox] = []

        def spin(parent, **kwargs) -> ttk.Spinbox:
            box = ttk.Spinbox(parent, **kwargs)
            spins.append(box)
            return box

        top = ttk.Frame(win, padding=12)
        top.pack(fill=tk.X)
        ttk.Label(top, text="集结时间").pack(side=tk.LEFT)
        for mins in config.RALLY_MINUTES_CHOICES:
            ttk.Radiobutton(top, text=f"{mins}分钟", variable=self.rally_minutes, value=mins).pack(side=tk.LEFT, padx=8)

        canvas = tk.Canvas(win, highlightthickness=0)
        scroll = ttk.Scrollbar(win, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        inner = ttk.Frame(canvas, padding=12)
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def fit(event) -> None:
            canvas.itemconfigure(window_id, width=event.width)
            canvas.configure(scrollregion=canvas.bbox("all"))

        canvas.bind("<Configure>", fit)
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))

        thresh_box = ttk.LabelFrame(inner, text="阈值（越大越严）")
        thresh_box.pack(fill=tk.X, pady=(0, 8))
        for i, (key, label, _default) in enumerate(config.THRESH_FIELDS):
            cell = ttk.Frame(thresh_box)
            cell.grid(row=i // 2, column=i % 2, sticky=tk.W, padx=12, pady=3)
            ttk.Label(cell, text=label, width=10, anchor=tk.W).pack(side=tk.LEFT)
            spin(cell, from_=0.40, to=0.99, increment=0.01, textvariable=self.thresh_vars[key], width=6).pack(side=tk.LEFT, padx=6)

        misc = ttk.LabelFrame(inner, text="其它")
        misc.pack(fill=tk.X, pady=(0, 8))
        row1 = ttk.Frame(misc)
        row1.pack(fill=tk.X, padx=12, pady=6)
        ttk.Label(row1, text="静止").pack(side=tk.LEFT)
        spin(row1, from_=1, to=30, textvariable=self.ship_still_sec, width=4).pack(side=tk.LEFT, padx=4)
        ttk.Label(row1, text="秒").pack(side=tk.LEFT)
        ttk.Label(row1, text="位移").pack(side=tk.LEFT, padx=(16, 4))
        spin(row1, from_=1, to=300, textvariable=self.ship_still_px, width=5).pack(side=tk.LEFT)
        ttk.Label(row1, text="px").pack(side=tk.LEFT, padx=4)
        ttk.Label(row1, text="等级").pack(side=tk.LEFT, padx=(16, 4))
        spin(row1, from_=1, to=99, textvariable=self.lvl_min, width=4).pack(side=tk.LEFT)
        ttk.Label(row1, text="-").pack(side=tk.LEFT, padx=4)
        spin(row1, from_=1, to=99, textvariable=self.lvl_max, width=4).pack(side=tk.LEFT)
        row2 = ttk.Frame(misc)
        row2.pack(fill=tk.X, padx=12, pady=(0, 8))
        ttk.Label(row2, text="滚轮").pack(side=tk.LEFT)
        spin(row2, from_=0.05, to=1.00, increment=0.05, textvariable=self.wheel_pause, width=5).pack(side=tk.LEFT, padx=4)
        ttk.Label(row2, text="秒/格").pack(side=tk.LEFT)
        ttk.Label(row2, text="测试显示").pack(side=tk.LEFT, padx=(16, 4))
        spin(row2, from_=1, to=30, textvariable=self.mark_preview_sec, width=4).pack(side=tk.LEFT)
        ttk.Label(row2, text="秒").pack(side=tk.LEFT, padx=4)

        def ok() -> None:
            for box in spins:
                try:
                    name = str(box.cget("textvariable"))
                    if name:
                        self.setvar(name, box.get())
                except tk.TclError:
                    pass
            self.apply_settings()
            self.save_settings()
            win.destroy()

        bar = ttk.Frame(inner)
        bar.pack(fill=tk.X, pady=8)
        ttk.Button(bar, text="确定", command=ok).pack(side=tk.LEFT)

    def apply_settings(self) -> dict[str, float]:
        self._commit_spins()
        try:
            minutes = int(self.rally_minutes.get())
        except (tk.TclError, ValueError):
            minutes = 1
        if minutes not in config.RALLY_MINUTES_CHOICES:
            minutes = 1
        self.rally_minutes.set(minutes)
        config.RALLY_MINUTES = minutes
        thresh: dict[str, float] = {}
        for key, _label, default in config.THRESH_FIELDS:
            value = self._clamp_thresh(self.thresh_vars[key], default)
            config.THRESH[key] = value
            thresh[key] = value
        config.publish_thresh()
        still_sec = self._clamp_int(self.ship_still_sec, 1, 30, 8)
        still_px = self._clamp_int(self.ship_still_px, 1, 300, 50)
        config.SHIP_STILL_SEC = float(still_sec)
        config.SHIP_STILL_PX = still_px
        lvl_min = self._clamp_int(self.lvl_min, 1, 99, 16)
        lvl_max = self._clamp_int(self.lvl_max, 1, 99, 22)
        if lvl_min > lvl_max:
            lvl_min, lvl_max = lvl_max, lvl_min
            self.lvl_min.set(lvl_min)
            self.lvl_max.set(lvl_max)
        config.LVL_MIN = lvl_min
        config.LVL_MAX = lvl_max
        wheel = self._clamp_span(self.wheel_pause, 0.05, 1.00, 0.20)
        config.WHEEL_PAUSE = wheel
        preview = self._clamp_int(self.mark_preview_sec, 1, 30, 5)
        config.MARK_PREVIEW_SEC = preview
        config.INFINITE = bool(self.infinite.get())
        return {
            "minutes": minutes,
            "thresh": thresh,
            "still_sec": still_sec,
            "still_px": still_px,
            "lvl_min": lvl_min,
            "lvl_max": lvl_max,
            "wheel": wheel,
            "preview": preview,
            "infinite": config.INFINITE,
        }

    def _spawn(self, goal: int, count: int, click: bool, dry: bool) -> None:
        self._delay = None

        def work() -> None:
            try:
                bot.run_session(goal=goal, count=count, click=click, dry=dry)
            except Exception as exc:
                bot.log(f"出错: {exc}")
            finally:
                self.after(0, lambda: self.set_running(False))

        threading.Thread(target=work, daemon=True).start()

    def stop(self) -> None:
        bot.STOP.set()
        import overlay

        overlay.hide()
        bot.cue_stop()
        if self._delay is not None:
            self.after_cancel(self._delay)
            self._delay = None
            self.set_running(False)
        self.append_log("正在停止…")

    def reset_cal(self) -> None:
        calibrate.reset()
        t0 = calibrate.timeouts_goal0()
        t1 = calibrate.timeouts_goal1()
        self.append_log(
            f"已清空校准  爪牙超时{t0['gone_wait']:.0f}s  贡品超时{t1['gone_wait']:.0f}s"
        )

    def show_windows(self) -> None:
        wins = list_windows()
        if not wins:
            self.append_log("没有找到足够大的窗口")
            return
        self.append_log("窗口列表:")
        for w in wins:
            self.append_log(f"  {w.width}x{w.height}  ({w.left},{w.top})  {w.title}")

    def align_panels(self) -> None:
        import numpy as np
        from capture import pick_game_window
        import overlay
        from vision import Matcher

        rect = pick_game_window()
        matcher = Matcher()
        frame = np.zeros((rect.height, rect.width, 3), np.uint8)
        specs = []
        for name in ("hud_ship", "hud_right"):
            if name == "hud_ship":
                x, y, _w, _h = matcher.hud_ship_region(frame)
            else:
                x, y, _w, _h = matcher.hud_ref(name, frame)
            specs.append((name, config.TEMPLATES[name], x, y))
        self.append_log("拖动半透明 HUD 对齐游戏，点「完成」保存。平时不再画这三块框。")

        def done(data) -> None:
            if not data:
                self.append_log("取消对齐")
                return
            from vision import save_hud_layout

            save_hud_layout(data)
            self.append_log("HUD 位置已保存  " + "  ".join(f"{k}={v}" for k, v in data.items()))

        overlay.align_hud(self, rect, specs, done)

    def test_ships(self) -> None:
        if self.running:
            return
        self.save_settings()
        import overlay

        overlay.attach(self)
        self.append_log(
            f"测试船标  阈值{config.SHIP_ICON_THRESH:.2f}  "
            f"显示{config.MARK_PREVIEW_SEC}秒，点一下也可关"
        )

        def work() -> None:
            try:
                bot.scan_ships()
            except Exception as exc:
                bot.log(f"出错: {exc}")
            finally:
                overlay.hide()

        threading.Thread(target=work, daemon=True).start()

    def collect_settings(self) -> dict:
        try:
            count = int(self.count.get())
        except (tk.TclError, ValueError):
            count = 10
        count = max(1, min(99, count))
        try:
            goal = int(self.goal.get())
        except (tk.TclError, ValueError):
            goal = 0
        if goal not in (0, 1, 2, 3):
            goal = 0
        mode = "scan" if self.hud_test.get() else "click"
        applied = self.apply_settings()
        return {
            "goal": goal,
            "count": count,
            "mode": mode,
            "hud_test": mode == "scan",
            "rally_minutes": int(applied["minutes"]),
            "thresh": applied["thresh"],
            "ship_still_sec": int(applied["still_sec"]),
            "ship_still_px": int(applied["still_px"]),
            "lvl_min": int(applied["lvl_min"]),
            "lvl_max": int(applied["lvl_max"]),
            "wheel_pause": float(applied["wheel"]),
            "mark_preview_sec": int(applied["preview"]),
            "infinite": bool(applied["infinite"]),
            "show_marks": bool(self.show_marks.get()),
        }

    def save_settings(self) -> None:
        write_gui_settings(self.collect_settings())

    def on_close(self) -> None:
        try:
            self.save_settings()
        except Exception:
            pass
        try:
            import overlay

            overlay.detach()
        except Exception:
            pass
        bot.STOP.set()
        if self.running:
            bot.cue_stop()
        bot.LOG_HOOK = None
        self.destroy()


def _default_settings() -> dict:
    return {
        "goal": 0,
        "count": 10,
        "mode": "click",
        "rally_minutes": int(config.RALLY_MINUTES),
        "thresh": {key: float(value) for key, _label, value in config.THRESH_FIELDS},
        "ship_still_sec": int(config.SHIP_STILL_SEC),
        "ship_still_px": int(config.SHIP_STILL_PX),
        "lvl_min": int(config.LVL_MIN),
        "lvl_max": int(config.LVL_MAX),
        "wheel_pause": float(config.WHEEL_PAUSE),
        "mark_preview_sec": int(config.MARK_PREVIEW_SEC),
        "show_marks": True,
        "infinite": False,
    }


def _clamp(value: float, lo: float, hi: float, default: float) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        n = default
    return max(lo, min(hi, n))


def load_gui_settings() -> dict:
    data = _default_settings()
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return data
    except (OSError, json.JSONDecodeError):
        return data
    goal = int(raw.get("goal", data["goal"]))
    data["goal"] = goal if goal in (0, 1, 2, 3) else 0
    data["count"] = int(_clamp(raw.get("count", data["count"]), 1, 99, 10))
    if "hud_test" in raw:
        data["mode"] = "scan" if raw.get("hud_test") else "click"
    else:
        mode = str(raw.get("mode", data["mode"]))
        data["mode"] = mode if mode in ("click", "scan") else "click"
    data["show_marks"] = bool(raw.get("show_marks", True))
    data["infinite"] = bool(raw.get("infinite", False))
    minutes = int(raw.get("rally_minutes", data["rally_minutes"]))
    data["rally_minutes"] = minutes if minutes in config.RALLY_MINUTES_CHOICES else 1
    data["mark_preview_sec"] = int(_clamp(raw.get("mark_preview_sec", data["mark_preview_sec"]), 1, 30, 5))
    data["ship_still_sec"] = int(_clamp(raw.get("ship_still_sec", data["ship_still_sec"]), 1, 30, 8))
    data["ship_still_px"] = int(_clamp(raw.get("ship_still_px", data["ship_still_px"]), 1, 300, 50))
    data["lvl_min"] = int(_clamp(raw.get("lvl_min", data["lvl_min"]), 1, 99, 16))
    data["lvl_max"] = int(_clamp(raw.get("lvl_max", data["lvl_max"]), 1, 99, 22))
    if data["lvl_min"] > data["lvl_max"]:
        data["lvl_min"], data["lvl_max"] = data["lvl_max"], data["lvl_min"]
    data["wheel_pause"] = round(_clamp(raw.get("wheel_pause", data["wheel_pause"]), 0.05, 1.00, 0.20), 2)
    legacy = {
        "search_thresh": "search",
        "atk_thresh": "atk",
        "flag_thresh": "flag",
        "time_on_thresh": "time_on",
        "time_off_thresh": "time_off",
        "ship_icon_thresh": "ship_icon",
    }
    incoming = raw.get("thresh") if isinstance(raw.get("thresh"), dict) else {}
    match_old = raw.get("match_thresh")
    generic = {key for key, _label, value in config.THRESH_FIELDS if value == 0.88}
    merged = {}
    for key, _label, default in config.THRESH_FIELDS:
        if key in incoming:
            merged[key] = round(_clamp(incoming.get(key), 0.40, 0.99, default), 2)
            continue
        old_key = next((ok for ok, nk in legacy.items() if nk == key and ok in raw), None)
        if old_key is not None:
            merged[key] = round(_clamp(raw.get(old_key), 0.40, 0.99, default), 2)
        elif key in generic and match_old is not None:
            merged[key] = round(_clamp(match_old, 0.40, 0.99, default), 2)
        else:
            merged[key] = default
    data["thresh"] = merged
    return data


def write_gui_settings(data: dict) -> None:
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def launch() -> None:
    App().mainloop()


if __name__ == "__main__":
    sys.exit(launch() or 0)
