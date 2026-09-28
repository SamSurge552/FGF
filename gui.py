"""FGF 本地控制台。双击 start.bat 或: python gui.py"""
from __future__ import annotations

import json
import os
import subprocess
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
    (0, "0  爪牙·至高教"),
    (1, "1  贡品船"),
    (2, "2  祈祷舰"),
)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        admin = is_admin()
        self.title("FGF 助手" + ("（管理员）" if admin else "（普通权限）"))
        self.geometry("500x760+12+12")
        self.minsize(460, 560)
        self.attributes("-topmost", True)
        self.running = False
        self._delay = None

        saved = load_gui_settings()
        self.goal = tk.IntVar(value=saved["goal"])
        self.count = tk.IntVar(value=saved["count"])
        self.mode = tk.StringVar(value=saved["mode"])
        self.rally_minutes = tk.IntVar(value=saved["rally_minutes"])
        self.search_thresh = tk.DoubleVar(value=saved["search_thresh"])
        self.match_thresh = tk.DoubleVar(value=saved["match_thresh"])
        self.atk_thresh = tk.DoubleVar(value=saved["atk_thresh"])
        self.flag_thresh = tk.DoubleVar(value=saved["flag_thresh"])
        self.time_on_thresh = tk.DoubleVar(value=saved["time_on_thresh"])
        self.time_off_thresh = tk.DoubleVar(value=saved["time_off_thresh"])
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
        ttk.Spinbox(row, from_=1, to=99, textvariable=self.count, width=6).pack(side=tk.LEFT, padx=8)

        mbox = ttk.LabelFrame(frm, text="动作")
        mbox.pack(fill=tk.X, **pad)
        ttk.Radiobutton(mbox, text="真点鼠标", variable=self.mode, value="click").pack(side=tk.LEFT, padx=8, pady=6)
        ttk.Radiobutton(mbox, text="干跑不点", variable=self.mode, value="dry").pack(side=tk.LEFT, padx=8, pady=6)
        ttk.Radiobutton(mbox, text="只扫一帧", variable=self.mode, value="scan").pack(side=tk.LEFT, padx=8, pady=6)
        ttk.Checkbutton(mbox, text="屏幕标记", variable=self.show_marks, command=self.on_marks).pack(
            side=tk.LEFT, padx=12, pady=6
        )

        sbox = ttk.LabelFrame(frm, text="设置")
        sbox.pack(fill=tk.X, **pad)
        trow = ttk.Frame(sbox)
        trow.pack(fill=tk.X, padx=8, pady=(6, 2))
        ttk.Label(trow, text="集结时间").pack(side=tk.LEFT)
        for mins in config.RALLY_MINUTES_CHOICES:
            ttk.Radiobutton(trow, text=f"{mins}分钟", variable=self.rally_minutes, value=mins).pack(
                side=tk.LEFT, padx=6
            )
        grid = ttk.Frame(sbox)
        grid.pack(fill=tk.X, padx=8, pady=(2, 6))
        fields = (
            ("搜寻", self.search_thresh),
            ("通用", self.match_thresh),
            ("左HUD攻击", self.atk_thresh),
            ("旗子", self.flag_thresh),
            ("时间开", self.time_on_thresh),
            ("时间关", self.time_off_thresh),
        )
        for i, (label, var) in enumerate(fields):
            cell = ttk.Frame(grid)
            cell.grid(row=i // 3, column=i % 3, sticky=tk.W, padx=(0, 10), pady=2)
            ttk.Label(cell, text=label).pack(side=tk.LEFT)
            ttk.Spinbox(cell, from_=0.50, to=0.99, increment=0.01, textvariable=var, width=5).pack(
                side=tk.LEFT, padx=4
            )

        btns = ttk.Frame(frm)
        btns.pack(fill=tk.X, **pad)
        self.btn_start = ttk.Button(btns, text="开始", command=self.start)
        self.btn_start.pack(side=tk.LEFT)
        self.btn_stop = ttk.Button(btns, text="停止", command=self.stop, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=8)
        ttk.Button(btns, text="列出窗口", command=self.show_windows).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="聊天提取", command=self.open_chat).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="重置校准", command=self.reset_cal).pack(side=tk.LEFT, padx=4)
        if not admin:
            ttk.Button(btns, text="以管理员运行", command=self.elevate).pack(side=tk.LEFT, padx=4)
        ttk.Label(btns, text="F12 也能停").pack(side=tk.RIGHT)

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
            f"搜寻{saved['search_thresh']:.2f} 通用{saved['match_thresh']:.2f} "
            f"攻击{saved['atk_thresh']:.2f} 旗{saved['flag_thresh']:.2f} "
            f"时间开/关{saved['time_on_thresh']:.2f}/{saved['time_off_thresh']:.2f}"
        )
        self.apply_settings()
        self.on_marks()
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

    def on_marks(self) -> None:
        import overlay

        if self.show_marks.get():
            overlay.attach(self)
        else:
            overlay.detach()

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
        mode = self.mode.get()
        goal = int(self.goal.get())
        click = mode == "click"
        dry = mode == "dry"
        self.set_running(True)
        applied = self.apply_settings()
        self.save_settings()
        self.append_log(
            f"开始  目标{goal}  次数{count}  模式={mode}  "
            f"集结{applied['minutes']}分钟  "
            f"置信度 搜寻{applied['search']:.2f} 通用{applied['match']:.2f} "
            f"攻击{applied['atk']:.2f} 旗{applied['flag']:.2f} "
            f"时间开/关{applied['time_on']:.2f}/{applied['time_off']:.2f}"
        )
        self._delay = None
        if click:
            rect = pick_game_window()
            focus_window(rect)
            self.append_log("已切到游戏，2 秒后动手（别点助手）")
            self._delay = self.after(2000, lambda: self._spawn(goal, count, click, dry))
        else:
            self._spawn(goal, count, click, dry)

    def _clamp_thresh(self, var: tk.DoubleVar, default: float) -> float:
        try:
            value = float(var.get())
        except (tk.TclError, ValueError):
            value = default
        value = max(0.50, min(0.99, value))
        var.set(round(value, 2))
        return value

    def apply_settings(self) -> dict[str, float]:
        try:
            minutes = int(self.rally_minutes.get())
        except (tk.TclError, ValueError):
            minutes = 1
        if minutes not in config.RALLY_MINUTES_CHOICES:
            minutes = 1
        self.rally_minutes.set(minutes)
        config.RALLY_MINUTES = minutes
        config.SEARCH_THRESH = self._clamp_thresh(self.search_thresh, 0.80)
        config.MATCH_THRESH = self._clamp_thresh(self.match_thresh, 0.88)
        config.ATK_THRESH = self._clamp_thresh(self.atk_thresh, 0.95)
        config.FLAG_THRESH = self._clamp_thresh(self.flag_thresh, 0.75)
        config.TIME_ON_THRESH = self._clamp_thresh(self.time_on_thresh, 0.90)
        config.TIME_OFF_THRESH = self._clamp_thresh(self.time_off_thresh, 0.95)
        return {
            "minutes": minutes,
            "search": config.SEARCH_THRESH,
            "match": config.MATCH_THRESH,
            "atk": config.ATK_THRESH,
            "flag": config.FLAG_THRESH,
            "time_on": config.TIME_ON_THRESH,
            "time_off": config.TIME_OFF_THRESH,
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

    def open_chat(self) -> None:
        script = os.path.join(config.ROOT, "chat_gui.py")
        subprocess.Popen([sys.executable, script], cwd=config.ROOT)
        self.append_log("已打开聊天提取窗口")

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
        if goal not in (0, 1, 2):
            goal = 0
        mode = self.mode.get()
        if mode not in ("click", "dry", "scan"):
            mode = "click"
        applied = self.apply_settings()
        return {
            "goal": goal,
            "count": count,
            "mode": mode,
            "rally_minutes": int(applied["minutes"]),
            "search_thresh": float(applied["search"]),
            "match_thresh": float(applied["match"]),
            "atk_thresh": float(applied["atk"]),
            "flag_thresh": float(applied["flag"]),
            "time_on_thresh": float(applied["time_on"]),
            "time_off_thresh": float(applied["time_off"]),
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
        bot.LOG_HOOK = None
        self.destroy()


def _default_settings() -> dict:
    return {
        "goal": 0,
        "count": 10,
        "mode": "click",
        "rally_minutes": int(config.RALLY_MINUTES),
        "search_thresh": float(config.SEARCH_THRESH),
        "match_thresh": float(config.MATCH_THRESH),
        "atk_thresh": float(config.ATK_THRESH),
        "flag_thresh": float(config.FLAG_THRESH),
        "time_on_thresh": float(config.TIME_ON_THRESH),
        "time_off_thresh": float(config.TIME_OFF_THRESH),
        "show_marks": True,
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
    data["goal"] = goal if goal in (0, 1, 2) else 0
    data["count"] = int(_clamp(raw.get("count", data["count"]), 1, 99, 10))
    mode = str(raw.get("mode", data["mode"]))
    data["mode"] = mode if mode in ("click", "dry", "scan") else "click"
    data["show_marks"] = bool(raw.get("show_marks", True))
    minutes = int(raw.get("rally_minutes", data["rally_minutes"]))
    data["rally_minutes"] = minutes if minutes in config.RALLY_MINUTES_CHOICES else 1
    for key in (
        "search_thresh",
        "match_thresh",
        "atk_thresh",
        "flag_thresh",
        "time_on_thresh",
        "time_off_thresh",
    ):
        data[key] = round(_clamp(raw.get(key, data[key]), 0.50, 0.99, data[key]), 2)
    return data


def write_gui_settings(data: dict) -> None:
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def launch() -> None:
    App().mainloop()


if __name__ == "__main__":
    sys.exit(launch() or 0)
