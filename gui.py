"""FGF 本地控制台。双击 start.bat 或: python gui.py"""
from __future__ import annotations

import sys
import threading
import tkinter as tk
from tkinter import ttk

import bot
import calibrate
from capture import focus_window, is_admin, list_windows, pick_game_window, relaunch_as_admin


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
        self.geometry("480x520+12+12")
        self.minsize(420, 380)
        self.attributes("-topmost", True)
        self.running = False
        self._delay = None

        self.goal = tk.IntVar(value=0)
        self.count = tk.IntVar(value=10)
        self.mode = tk.StringVar(value="click")

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

        btns = ttk.Frame(frm)
        btns.pack(fill=tk.X, **pad)
        self.btn_start = ttk.Button(btns, text="开始", command=self.start)
        self.btn_start.pack(side=tk.LEFT)
        self.btn_stop = ttk.Button(btns, text="停止", command=self.stop, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=8)
        ttk.Button(btns, text="列出窗口", command=self.show_windows).pack(side=tk.LEFT, padx=4)
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
        self.append_log(f"开始  目标{goal}  次数{count}  模式={mode}")
        self._delay = None
        if click:
            rect = pick_game_window()
            focus_window(rect)
            self.append_log("已切到游戏，2 秒后动手（别点助手）")
            self._delay = self.after(2000, lambda: self._spawn(goal, count, click, dry))
        else:
            self._spawn(goal, count, click, dry)

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

    def on_close(self) -> None:
        bot.STOP.set()
        bot.LOG_HOOK = None
        self.destroy()


def launch() -> None:
    App().mainloop()


if __name__ == "__main__":
    sys.exit(launch() or 0)
