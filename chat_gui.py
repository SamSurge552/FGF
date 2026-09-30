"""聊天提取界面。python chat_gui.py"""
from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, ttk

import chat_log
import config


class ChatApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("FGF 聊天提取")
        self.geometry("560x620+540+12")
        self.minsize(480, 420)
        self.attributes("-topmost", True)
        self.busy = False
        self.last_txt = ""
        default_dir = os.path.join(config.PIC, "chat")
        if not os.path.isdir(default_dir):
            default_dir = config.PIC
        self.folder = tk.StringVar(value=default_dir)

        pad = {"padx": 10, "pady": 6}
        frm = ttk.Frame(self, padding=8)
        frm.pack(fill=tk.BOTH, expand=True)

        box = ttk.LabelFrame(frm, text="连续截图提取")
        box.pack(fill=tk.X, **pad)
        row = ttk.Frame(box)
        row.pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(row, text="文件夹").pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.folder).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        ttk.Button(row, text="浏览", command=self.browse).pack(side=tk.LEFT)
        btns = ttk.Frame(box)
        btns.pack(fill=tk.X, padx=8, pady=(0, 8))
        self.btn_extract = ttk.Button(btns, text="开始提取", command=self.extract)
        self.btn_extract.pack(side=tk.LEFT)
        ttk.Button(btns, text="打开结果TXT", command=self.open_txt).pack(side=tk.LEFT, padx=8)
        ttk.Button(btns, text="打开日志目录", command=self.open_dir).pack(side=tk.LEFT)

        live = ttk.LabelFrame(frm, text="实时记录（只读当前游戏页签）")
        live.pack(fill=tk.X, **pad)
        lrow = ttk.Frame(live)
        lrow.pack(fill=tk.X, padx=8, pady=6)
        self.btn_live = ttk.Button(lrow, text="开始记录", command=self.start_live)
        self.btn_live.pack(side=tk.LEFT)
        self.btn_stop = ttk.Button(lrow, text="停止", command=self.stop_live, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=8)
        ttk.Label(lrow, text="F12 也能停").pack(side=tk.RIGHT)

        self.path_var = tk.StringVar(value=f"提取完成后的 TXT 在：{chat_log.LOG_DIR}")
        ttk.Label(frm, textvariable=self.path_var, wraplength=520, justify=tk.LEFT).pack(fill=tk.X, **pad)

        logbox = ttk.LabelFrame(frm, text="日志")
        logbox.pack(fill=tk.BOTH, expand=True, **pad)
        self.log = tk.Text(logbox, height=16, wrap=tk.WORD, state=tk.DISABLED)
        scroll = ttk.Scrollbar(logbox, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.pack(fill=tk.BOTH, expand=True)

        chat_log.LOG_HOOK = self.append_log
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.append_log(f"连续提取写出 extract_时间.txt")
        self.append_log(f"实时记录写出 guild/或 mgmt/日期.txt 和 .jsonl")
        self.append_log(f"目录 {chat_log.LOG_DIR}")

    def append_log(self, line: str) -> None:
        def _write() -> None:
            self.log.configure(state=tk.NORMAL)
            self.log.insert(tk.END, line.rstrip() + "\n")
            self.log.see(tk.END)
            self.log.configure(state=tk.DISABLED)

        self.after(0, _write)

    def set_busy(self, on: bool) -> None:
        self.busy = on
        state = tk.DISABLED if on else tk.NORMAL
        self.btn_extract.configure(state=state)
        if not on:
            self.btn_live.configure(state=tk.NORMAL)
            self.btn_stop.configure(state=tk.DISABLED)
        else:
            self.btn_live.configure(state=tk.DISABLED)

    def browse(self) -> None:
        path = filedialog.askdirectory(initialdir=self.folder.get() or config.PIC)
        if path:
            self.folder.set(path)

    def extract(self) -> None:
        if self.busy:
            return
        folder = self.folder.get().strip()
        if not folder or not os.path.isdir(folder):
            self.append_log("文件夹不存在")
            return
        self.set_busy(True)
        chat_log.STOP.clear()

        def work() -> None:
            try:
                path = chat_log.run_folder(folder, write=False)
                if path:
                    self.last_txt = path
                    self.after(0, lambda: self.path_var.set(f"本次 TXT：{path}"))
            except Exception as exc:
                chat_log.log(f"出错: {exc}")
            finally:
                self.after(0, lambda: self.set_busy(False))

        threading.Thread(target=work, daemon=True).start()

    def start_live(self) -> None:
        if self.busy:
            return
        self.set_busy(True)
        self.btn_stop.configure(state=tk.NORMAL)
        chat_log.STOP.clear()
        self.path_var.set(f"实时记录写入 {chat_log.LOG_DIR}\\guild 或 mgmt")

        def work() -> None:
            try:
                chat_log.run_loop()
            except Exception as exc:
                chat_log.log(f"出错: {exc}")
            finally:
                self.after(0, lambda: self.set_busy(False))

        threading.Thread(target=work, daemon=True).start()

    def stop_live(self) -> None:
        chat_log.STOP.set()
        self.append_log("正在停止…")

    def open_txt(self) -> None:
        path = self.last_txt
        if not path or not os.path.isfile(path):
            newest = _newest_extract()
            path = newest or ""
        if not path:
            self.append_log("还没有提取出的 TXT")
            return
        os.startfile(path)

    def open_dir(self) -> None:
        os.makedirs(chat_log.LOG_DIR, exist_ok=True)
        os.startfile(chat_log.LOG_DIR)

    def on_close(self) -> None:
        chat_log.STOP.set()
        chat_log.LOG_HOOK = None
        self.destroy()


def _newest_extract() -> str:
    folder = chat_log.LOG_DIR
    if not os.path.isdir(folder):
        return ""
    files = [
        os.path.join(folder, n)
        for n in os.listdir(folder)
        if n.startswith("extract_") and n.endswith(".txt")
    ]
    return max(files, key=os.path.getmtime) if files else ""


def launch() -> None:
    ChatApp().mainloop()


if __name__ == "__main__":
    sys.exit(launch() or 0)
