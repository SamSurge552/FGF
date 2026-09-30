"""工会/管理频道聊天 OCR 落盘。借鉴 DNF 项目 RapidOCR 参数。只读截图，不点鼠标。

  python chat_log.py --image pic/guild_chat1.png --once
  python chat_log.py
F12 停止。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from datetime import datetime

import cv2
import numpy as np
from pynput import keyboard

import config
from capture import grab, pick_game_window
from vision import Matcher

STOP = threading.Event()
LOG_HOOK = None
LOG_DIR = os.path.join(config.ROOT, "logs", "chat")
FILE_TS = re.compile(r"(\d{8})_(\d{6})")
HUD_CLOCK = re.compile(r"^\d{1,2}:\d{2}$")
SKIP_RE = re.compile(r"最多輸入|最多输入|個字元|个字符")
QUOTE_ONLY_RE = re.compile(r"^[不卜丶丄]+$")
QUOTE_LEAD_RE = re.compile(r"^[不卜]+\s*")
LEADER_ONLY_RE = re.compile(r"^山$")
LEADER_LEAD_RE = re.compile(r"^山\s*")
QUOTE_NEEDLE = os.path.join(config.STABLE, "chat_quote.png")
QUOTE_THRESH = 0.85
SPEAKER_RE = re.compile(
    r"^(會長|会长|招募官|外交官|戰神|战神|\[執行經理\]|\[执行經理\])\s*(.*)$"
)


def log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    hook = LOG_HOOK
    if hook is not None:
        try:
            hook(line)
        except Exception:
            pass


def on_press(key) -> None:
    try:
        if key == keyboard.Key.f12:
            log("F12 停止")
            STOP.set()
    except Exception:
        pass


def make_ocr():
    from rapidocr import RapidOCR

    common = {
        "Global.use_cls": False,
        "Global.text_score": 0.5,
        "Global.max_side_len": 4096,
        "Global.log_level": "error",
    }
    cpu = RapidOCR(params=common)
    # FGF 这边不搬 DNF 的 cuda_runtime；聊天框很小，CPU 够用。
    log("RapidOCR 使用 CPU")
    return cpu


def crop(frame, region: tuple[int, int, int, int]):
    x, y, w, h = region
    return frame[y : y + h, x : x + w]


def detect_channel(matcher: Matcher, frame) -> str | None:
    strip = crop(frame, config.CHAT_TAB_REGION)
    if strip.size == 0:
        return None
    chat = matcher.find(strip, "chat_tab_on", config.thresh_for("chat_tab_on"))
    mgmt = matcher.find(strip, "mgmt_tab_on", config.thresh_for("mgmt_tab_on"))
    if chat and mgmt:
        return "guild" if chat.score >= mgmt.score else "mgmt"
    if chat:
        return "guild"
    if mgmt:
        return "mgmt"
    return None


def quote_icon_ys(roi) -> list[float]:
    """引用条左侧小旗。OCR 常把这标认成「不」。"""
    needle = cv2.imread(QUOTE_NEEDLE)
    if needle is None or roi.size == 0:
        return []
    if needle.shape[0] > roi.shape[0] or needle.shape[1] > roi.shape[1]:
        return []
    res = cv2.matchTemplate(roi, needle, cv2.TM_CCOEFF_NORMED)
    loc = np.where(res >= QUOTE_THRESH)
    raw = list(zip(loc[1].tolist(), loc[0].tolist(), res[loc].tolist()))
    raw.sort(key=lambda t: -t[2])
    kept: list[tuple[int, int]] = []
    for x, y, _score in raw:
        if x > QUOTE_ICON_MAX_X:
            continue
        if any(abs(x - kx) < 16 and abs(y - ky) < 16 for kx, ky in kept):
            continue
        kept.append((x, y))
    h = int(needle.shape[0])
    return [y + h / 2 for _x, y in kept]


def replace_quote_bu(text: str) -> str:
    """引用旗 OCR 成「不」时，一律换成 quote:"""
    raw = text.strip()
    if not raw:
        return raw
    if QUOTE_ONLY_RE.match(raw):
        return "quote:"
    rest = QUOTE_LEAD_RE.sub("", raw, count=1)
    if rest == raw:
        if raw.startswith(">"):
            rest = raw[1:].strip()
            return f"quote: {rest}" if rest else "quote:"
        return raw
    if not rest:
        return "quote:"
    if rest.startswith("quote:"):
        return rest
    ch = rest[0]
    if ch.isascii() or ch in "@>[（(" or rest.endswith("...") or rest.endswith("…"):
        return f"quote: {rest}"
    return raw


def ensure_quote_prefix(line: str, quoted: bool) -> str:
    s = replace_quote_bu(line).strip()
    if s.startswith(">"):
        s = s[1:].strip()
        s = f"quote: {s}" if s else "quote:"
    if s.startswith("quote:"):
        return s
    if quoted:
        return f"quote: {s}" if s else "quote:"
    return s


def normalize_leader_badge(text: str) -> str:
    """橙冠会长标常被 OCR 成「山」，不是引用旗。"""
    raw = text.strip()
    if LEADER_ONLY_RE.match(raw):
        return "會長"
    if not LEADER_LEAD_RE.match(raw):
        return raw
    rest = LEADER_LEAD_RE.sub("", raw, count=1).strip()
    if not rest:
        return "會長"
    if rest.startswith("會長") or rest.startswith("会长"):
        return rest
    return "會長 " + rest


def ocr_lines(ocr, frame) -> list[str]:
    roi = crop(frame, config.CHAT_BODY_REGION)
    if roi.size == 0:
        return []
    result = ocr(roi)
    txts = list(getattr(result, "txts", None) or [])
    raw_boxes = getattr(result, "boxes", None)
    boxes = [] if raw_boxes is None else list(raw_boxes)
    raw_scores = getattr(result, "scores", None)
    scores = [] if raw_scores is None else list(raw_scores)
    if not txts:
        return []
    qys = quote_icon_ys(roi)
    rows: list[tuple[float, float, str, bool]] = []
    for i, text in enumerate(txts):
        raw = str(text or "").strip()
        if not raw or SKIP_RE.search(raw):
            continue
        if i < len(scores) and scores[i] is not None and float(scores[i]) < 0.45:
            continue
        cy, cx = 0.0, 0.0
        if i < len(boxes) and boxes[i] is not None:
            pts = np.asarray(boxes[i], dtype=float)
            cy = float(pts[:, 1].mean())
            cx = float(pts[:, 0].mean())
        on_icon = any(abs(cy - qy) <= 14 and cx <= QUOTE_ICON_MAX_X + 10 for qy in qys)
        quoted = any(abs(cy - qy) <= 16 for qy in qys)
        if on_icon or QUOTE_ONLY_RE.match(raw):
            rows.append((cy, cx, "quote:", True))
            continue
        cleaned = replace_quote_bu(raw)
        if not cleaned:
            continue
        if cleaned.startswith("quote:"):
            quoted = True
        cleaned = normalize_leader_badge(cleaned)
        rows.append((cy, cx, cleaned, quoted))
    rows.sort()
    lines: list[list[tuple[float, float, str, bool]]] = []
    for row in rows:
        if lines and abs(row[0] - lines[-1][0][0]) <= 22:
            lines[-1].append(row)
        else:
            lines.append([row])
    out: list[str] = []
    for group in lines:
        group.sort(key=lambda t: t[1])
        quoted = any(p[3] for p in group)
        parts = []
        for p in group:
            t = p[2]
            if t == "quote:" or t.startswith("quote:"):
                quoted = True
                t = t[len("quote:") :].strip()
                if t:
                    parts.append(t)
            else:
                parts.append(t)
        line = " ".join(parts).strip()
        line = normalize_leader_badge(line) if line else line
        line = ensure_quote_prefix(line, quoted)
        if not line or line == "quote:":
            continue
        out.append(line)
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def new_messages(prev: list[str], cur: list[str]) -> list[str]:
    if not cur:
        return []
    if not prev:
        return cur
    pn = [_norm(x) for x in prev]
    cn = [_norm(x) for x in cur]
    for k in range(min(len(pn), len(cn)), 0, -1):
        if pn[-k:] == cn[:k]:
            return cur[k:]
    seen = set(pn[-80:])
    return [line for line, n in zip(cur, cn) if n not in seen]


def append_log(channel: str, lines: list[str], ts: datetime) -> None:
    if not lines:
        return
    day = ts.strftime("%Y-%m-%d")
    folder = os.path.join(LOG_DIR, channel)
    os.makedirs(folder, exist_ok=True)
    txt_path = os.path.join(folder, f"{day}.txt")
    jsonl_path = os.path.join(folder, f"{day}.jsonl")
    stamp = ts.strftime("%H:%M:%S")
    with open(txt_path, "a", encoding="utf-8") as f:
        for line in lines:
            f.write(f"{stamp}  {line}\n")
    with open(jsonl_path, "a", encoding="utf-8") as f:
        for line in lines:
            f.write(
                json.dumps(
                    {"ts": ts.isoformat(timespec="seconds"), "channel": channel, "text": line},
                    ensure_ascii=False,
                )
                + "\n"
            )


def load_image(path: str) -> np.ndarray:
    data = np.fromfile(path, dtype=np.uint8)
    frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if frame is None:
        raise SystemExit(f"读不了图 {path}")
    return frame


def process_frame(
    matcher: Matcher,
    ocr,
    frame,
    prev: dict[str, list[str]],
    write: bool,
    ts: datetime | None = None,
    dump_all: bool = False,
) -> tuple[dict[str, list[str]], str | None, list[str]]:
    channel = detect_channel(matcher, frame)
    if not channel:
        log("未看到聊天/管理页签（面板可能没开）")
        return prev, None, []
    lines = ocr_lines(ocr, frame)
    fresh = new_messages(prev.get(channel) or [], lines)
    label = "工会聊天" if channel == "guild" else "管理频道"
    if write:
        stamp = ts or datetime.now()
        append_log(channel, fresh, stamp)
    if dump_all:
        log(f"[{label}] 本屏 {len(lines)} 行")
        for line in lines:
            log(f"  {line}")
    else:
        for line in fresh:
            log(f"[{label}] {line}")
        if not fresh:
            log(f"[{label}] 无新行  本屏{len(lines)}行")
    prev[channel] = lines
    return prev, channel, fresh


def parse_file_ts(path: str) -> datetime:
    m = FILE_TS.search(os.path.basename(path))
    if not m:
        return datetime.now()
    return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")


def list_sequence(folder: str) -> list[str]:
    out = []
    for name in os.listdir(folder):
        if FILE_TS.match(name) and name.lower().endswith(".png"):
            out.append(os.path.join(folder, name))
    return sorted(out)


def format_extract_line(text: str) -> str:
    return text.strip()


def is_hud_clock(line: str) -> bool:
    s = line.strip().strip("- ").strip()
    return bool(HUD_CLOCK.match(s))


def cjk_heavy(line: str) -> bool:
    n = len(re.findall(r"[\u4e00-\u9fff]", line))
    return n >= 4 and n / max(len(line), 1) >= 0.35


def clean_speaker_line(role: str, name: str) -> str:
    name = name.strip()
    name = re.sub(r"[\s口KkAaMmÈé]+$", "", name)
    name = re.sub(r"^I(?=[A-Za-z])", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return f"{role} {name}".strip()


def polish_transcript(lines: list[str]) -> list[str]:
    """按示例 txt：不要截图/HUD 时间，同一发言人不重复，引用为 quote: ，丢掉译文。"""
    out: list[str] = []
    last_speaker = None
    for raw in lines:
        s = raw.strip()
        if not s or is_hud_clock(s):
            continue
        if s.startswith("[截图") or s.startswith("#"):
            continue
        m = SPEAKER_RE.match(s)
        if m:
            sp = clean_speaker_line(m.group(1), m.group(2) or "")
            if not sp or sp == m.group(1):
                continue
            if sp == last_speaker:
                continue
            last_speaker = sp
            out.append(sp)
            continue
        if cjk_heavy(s) and not s.startswith("quote:"):
            continue
        if s.startswith("quote:") and not s.startswith("quote: "):
            s = "quote: " + s[6:].lstrip()
        out.append(s)
    return out


def run_folder(folder: str, write: bool) -> int:
    paths = list_sequence(folder)
    if not paths:
        log(f"文件夹里没有带时间戳的 png：{folder}")
        return ""
    matcher = Matcher()
    ocr = make_ocr()
    prev: dict[str, list[str]] = {}
    chunks: list[tuple[datetime, str, list[str]]] = []
    log(f"提取连续截图 {len(paths)} 张  {folder}")
    for path in paths:
        ts = parse_file_ts(path)
        log(f"图 {os.path.basename(path)}")
        frame = load_image(path)
        prev, channel, fresh = process_frame(matcher, ocr, frame, prev, write=write, ts=ts)
        if channel and fresh:
            chunks.append((ts, channel, fresh))
    os.makedirs(LOG_DIR, exist_ok=True)
    out_path = os.path.join(LOG_DIR, f"extract_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    grouped: list[list[str]] = []
    buf: list[str] = []
    last_ch: str | None = None
    for _ts, channel, lines in chunks:
        if last_ch is not None and channel != last_ch and buf:
            grouped.append(polish_transcript(buf))
            buf = []
        last_ch = channel
        buf.extend(lines)
    if buf:
        grouped.append(polish_transcript(buf))
    with open(out_path, "w", encoding="utf-8") as f:
        blocks = ["\n".join(g) for g in grouped if g]
        f.write("\n\n".join(blocks).rstrip() + "\n")
    log(f"已写出 {out_path}")
    return out_path


def run_once(image: str | None) -> int:
    matcher = Matcher()
    ocr = make_ocr()
    if image:
        frame = load_image(image)
    else:
        frame = grab(pick_game_window())
    process_frame(matcher, ocr, frame, {}, write=False, dump_all=True)
    return 0


def run_loop() -> int:
    matcher = Matcher()
    ocr = make_ocr()
    listener = keyboard.Listener(on_press=on_press)
    listener.daemon = True
    listener.start()
    prev: dict[str, list[str]] = {}
    log(f"开始记聊天  间隔{config.CHAT_OCR_INTERVAL:.1f}s  目录 {LOG_DIR}  F12停止")
    while not STOP.is_set():
        try:
            frame = grab(pick_game_window())
            process_frame(matcher, ocr, frame, prev, write=True)
        except Exception as exc:
            log(f"本轮失败: {exc}")
        deadline = time.time() + config.CHAT_OCR_INTERVAL
        while time.time() < deadline and not STOP.is_set():
            time.sleep(0.1)
    log("已停止")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FGF 聊天 OCR 落盘")
    parser.add_argument("--image", help="用这张图测一次，不截游戏")
    parser.add_argument("--folder", help="按文件名时间戳顺序提取连续截图")
    parser.add_argument("--once", action="store_true", help="只跑一帧/一批，不写入按天日志")
    args = parser.parse_args(argv)
    if args.folder:
        path = run_folder(args.folder, write=not args.once)
        return 0 if path else 1
    if args.image or args.once:
        return run_once(args.image)
    return run_loop()


if __name__ == "__main__":
    sys.exit(main())
