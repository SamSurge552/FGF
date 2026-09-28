from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

import config
from config import TEMPLATES

# 这些图要靠填充色区分 on/off，不能抠掉中间只留描边
NO_GLASS = {"time_3", "time_on", "time_off", "flag", "chat_tab_on", "mgmt_tab_on"}

# 玻璃按钮中间是半透明，背景会变。只拿和中位色差得开的像素（描边/图标）去匹配。
GLASS_DIST = 25.0
GLASS_MIN_FRAC = 0.05
GLASS_MAX_FRAC = 0.85
ALPHA_CUT = 16


@dataclass
class Needle:
    bgr: np.ndarray
    mask: np.ndarray | None

    @property
    def shape(self) -> tuple[int, ...]:
        return self.bgr.shape


def _structure_mask(bgr: np.ndarray, valid: np.ndarray) -> np.ndarray:
    pix = bgr[valid]
    if pix.size == 0:
        return valid
    med = np.median(pix.reshape(-1, 3), axis=0)
    dist = np.linalg.norm(bgr.astype(np.float32) - med, axis=2)
    struct = valid & (dist > GLASS_DIST)
    frac = float(struct.mean())
    if frac < GLASS_MIN_FRAC or frac > GLASS_MAX_FRAC:
        return valid
    return struct


def load_needle(path: str, glass: bool = True) -> Needle:
    im = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if im is None:
        raise FileNotFoundError(path)
    if im.ndim == 2:
        bgr = cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)
        return Needle(bgr, None)
    if im.shape[2] == 4:
        bgr = im[:, :, :3]
        alpha = im[:, :, 3]
        valid = alpha >= ALPHA_CUT
    else:
        bgr = im
        valid = np.ones(bgr.shape[:2], dtype=bool)
    if glass:
        valid = _structure_mask(bgr, valid)
    if bool(np.all(valid)):
        return Needle(bgr, None)
    return Needle(bgr, valid.astype(np.uint8) * 255)


def load_bgr(path: str, bg=(48, 96, 120)) -> np.ndarray:
    """场景图仍按不透明读取；模板请用 load_needle。"""
    im = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if im is None:
        raise FileNotFoundError(path)
    if im.ndim == 2:
        return cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)
    if im.shape[2] == 4:
        alpha = im[:, :, 3:4].astype(np.float32) / 255.0
        bgr = im[:, :, :3].astype(np.float32)
        bg_arr = np.array(bg, dtype=np.float32)
        return (bgr * alpha + bg_arr * (1.0 - alpha)).astype(np.uint8)
    return im


def score_map(frame: np.ndarray, needle: Needle) -> np.ndarray:
    if needle.bgr.shape[0] > frame.shape[0] or needle.bgr.shape[1] > frame.shape[1]:
        return np.zeros((1, 1), np.float32)
    if needle.mask is None:
        res = cv2.matchTemplate(frame, needle.bgr, cv2.TM_CCOEFF_NORMED)
    else:
        res = cv2.matchTemplate(frame, needle.bgr, cv2.TM_CCOEFF_NORMED, mask=needle.mask)
    return np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)


@dataclass
class Hit:
    name: str
    score: float
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def center(self) -> tuple[int, int]:
        return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)


class Matcher:
    def __init__(self) -> None:
        self.needles: dict[str, Needle] = {}
        for name, path in TEMPLATES.items():
            self.needles[name] = load_needle(path, glass=name not in NO_GLASS)

    def find(self, frame: np.ndarray, name: str, thresh: float | None = None) -> Hit | None:
        hits = self.find_all(frame, name, thresh)
        return hits[0] if hits else None

    def find_in(
        self,
        frame: np.ndarray,
        name: str,
        region: tuple[int, int, int, int],
        thresh: float | None = None,
    ) -> Hit | None:
        x, y, w, h = region
        crop = frame[y : y + h, x : x + w]
        hit = self.find(crop, name, thresh)
        if hit is None:
            return None
        return Hit(hit.name, hit.score, hit.x1 + x, hit.y1 + y, hit.x2 + x, hit.y2 + y)

    def find_all_in(
        self,
        frame: np.ndarray,
        name: str,
        region: tuple[int, int, int, int],
        thresh: float | None = None,
    ) -> list[Hit]:
        x, y, w, h = region
        crop = frame[y : y + h, x : x + w]
        hits = self.find_all(crop, name, thresh)
        return [
            Hit(hit.name, hit.score, hit.x1 + x, hit.y1 + y, hit.x2 + x, hit.y2 + y)
            for hit in hits
        ]

    def find_all(self, frame: np.ndarray, name: str, thresh: float | None = None) -> list[Hit]:
        if thresh is None:
            thresh = config.MATCH_THRESH
        needle = self.needles[name]
        if needle.bgr.shape[0] > frame.shape[0] or needle.bgr.shape[1] > frame.shape[1]:
            return []
        res = score_map(frame, needle)
        loc = np.where(res >= thresh)
        h, w = needle.bgr.shape[:2]
        raw: list[tuple[float, int, int]] = []
        for y, x in zip(loc[0].tolist(), loc[1].tolist()):
            raw.append((float(res[y, x]), int(x), int(y)))
        raw.sort(key=lambda t: -t[0])
        kept: list[Hit] = []
        for score, x1, y1 in raw:
            if any(abs(x1 - k.x1) < w // 2 and abs(y1 - k.y1) < h // 2 for k in kept):
                continue
            kept.append(Hit(name, score, x1, y1, x1 + w, y1 + h))
        return kept

    def best(self, frame: np.ndarray, name: str) -> tuple[float, tuple[int, int]]:
        needle = self.needles[name]
        if needle.bgr.shape[0] > frame.shape[0] or needle.bgr.shape[1] > frame.shape[1]:
            return 0.0, (-1, -1)
        res = score_map(frame, needle)
        _minv, maxv, _minl, maxl = cv2.minMaxLoc(res)
        return float(maxv), (int(maxl[0]), int(maxl[1]))

    def draw(self, frame: np.ndarray, hits: list[Hit]) -> np.ndarray:
        out = frame.copy()
        for hit in hits:
            cv2.rectangle(out, (hit.x1, hit.y1), (hit.x2, hit.y2), (0, 0, 255), 2)
            cx, cy = hit.center
            cv2.drawMarker(out, (cx, cy), (0, 255, 255), cv2.MARKER_CROSS, 12, 2)
            label = f"{hit.name} {hit.score:.2f}"
            cv2.putText(out, label, (hit.x1, max(16, hit.y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        return out
