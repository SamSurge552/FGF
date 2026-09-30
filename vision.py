from __future__ import annotations

from dataclasses import dataclass

import json
import os

import cv2
import numpy as np

import config
from config import TEMPLATES

# 这些图要靠填充色区分 on/off，不能抠掉中间只留描边
NO_GLASS = {
    "time_3",
    "time_on",
    "time_off",
    "flag",
    "team_btn",
    "chat_tab_on",
    "mgmt_tab_on",
    "ship_icon",
}

# 玻璃按钮中间是半透明，背景会变。只拿和中位色差得开的像素（描边/图标）去匹配。
GLASS_DIST = 25.0
GLASS_MIN_FRAC = 0.05
GLASS_MAX_FRAC = 0.85
ALPHA_CUT = 16
# atk 和蓝色组队旗只在船队栏。组队入口 team.png 在右侧 HUD 最上的红旗，不在船队栏。
SHIP_BAR_ONLY = frozenset({"atk", "flag"})
RIGHT_HUD_ONLY = frozenset({"team_btn"})
ROTATE_TEMPLATES = frozenset()


def hud_layout() -> dict:
    path = os.path.join(config.ROOT, "hud_layout.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save_hud_layout(data: dict) -> None:
    path = os.path.join(config.ROOT, "hud_layout.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _placed(name: str, tw: int, th: int) -> tuple[int, int, int, int] | None:
    raw = hud_layout().get(name)
    if not (isinstance(raw, list) and len(raw) >= 2):
        return None
    return int(raw[0]), int(raw[1]), tw, th


def rotate_needle(needle: Needle, angle: float) -> Needle:
    """绕中心转一圈。黑边用 mask 裁掉，避免当图案去配。"""
    if abs(angle % 360.0) < 0.5:
        return needle
    bgr = needle.bgr
    h, w = bgr.shape[:2]
    mask = needle.mask if needle.mask is not None else np.full((h, w), 255, np.uint8)
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    mat = cv2.getRotationMatrix2D((cx, cy), float(angle), 1.0)
    cos_a, sin_a = abs(mat[0, 0]), abs(mat[0, 1])
    nw = max(1, int(h * sin_a + w * cos_a))
    nh = max(1, int(h * cos_a + w * sin_a))
    mat[0, 2] += nw / 2.0 - cx
    mat[1, 2] += nh / 2.0 - cy
    rot = cv2.warpAffine(bgr, mat, (nw, nh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
    rot_m = cv2.warpAffine(mask, mat, (nw, nh), flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    rot_m = (rot_m > 127).astype(np.uint8) * 255
    if int(rot_m.sum()) == 0 or bool(np.all(rot_m)):
        return Needle(rot, None if bool(np.all(rot_m)) else rot_m)
    return Needle(rot, rot_m)


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


def hull_binary(frame: np.ndarray) -> np.ndarray:
    """只给船标用。彩色画面按船体 HSV 变成白船黑底，其它模板不要走这里。"""
    if frame.ndim == 2:
        bgr = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    else:
        bgr = frame[:, :, :3]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    lo = np.array(config.SHIP_HSV_LO, np.uint8)
    hi = np.array(config.SHIP_HSV_HI, np.uint8)
    mask = cv2.inRange(hsv, lo, hi)
    return cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)


# 整张图都是这个色，全留下会变成小方块。只留图标本身。
COLOR_BINS = {
    "atk": (
        ((0, 80, 25), (15, 255, 150)),
        ((165, 80, 25), (179, 255, 150)),
    ),
    "flag": (
        ((96, 145, 160), (112, 230, 220)),
    ),
    # 组队红旗：浅粉底才是要留的。旗面更暗，不收。
    "team_btn": (
        ((0, 80, 220), (15, 160, 255)),
        ((165, 80, 220), (179, 160, 255)),
    ),
}


def color_binary(frame: np.ndarray, name: str) -> np.ndarray:
    """atk 只留暗红剑，flag 只留浅蓝旗面，team_btn 只留浅色底。其它颜色变黑。"""
    if frame.ndim == 2:
        bgr = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    else:
        bgr = frame[:, :, :3]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = np.zeros(hsv.shape[:2], np.uint8)
    for lo, hi in COLOR_BINS[name]:
        mask = cv2.bitwise_or(mask, cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8)))
    return cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)


def color_similarity(frame: np.ndarray, needle_bgr: np.ndarray) -> np.ndarray:
    """二值图全像素参与。黑的地方也必须是黑，否则一块同色就会配成 1.0。"""
    gray = cv2.cvtColor(needle_bgr, cv2.COLOR_BGR2GRAY)
    if int((gray > 127).sum()) == 0 or int((gray <= 127).sum()) == 0:
        return np.zeros((1, 1), np.float32)
    res = cv2.matchTemplate(frame, needle_bgr, cv2.TM_CCOEFF_NORMED)
    res = np.where(np.isfinite(res), res, 0.0).astype(np.float32)
    return res


def ship_similarity(frame: np.ndarray, needle: Needle) -> np.ndarray:
    """黑底不参与。像素差越小越像，返回 1-差，越大越好。"""
    gray = cv2.cvtColor(needle.bgr, cv2.COLOR_BGR2GRAY)
    mask = (gray > 127).astype(np.uint8) * 255
    if int(mask.sum()) == 0:
        return np.zeros((1, 1), np.float32)
    res = cv2.matchTemplate(frame, needle.bgr, cv2.TM_SQDIFF_NORMED, mask=mask)
    res = np.where(np.isfinite(res), res, 1.0).astype(np.float32)
    res = np.clip(res, 0.0, 1.0)
    return 1.0 - res


def load_ship_angles() -> list[Needle]:
    """pic/ship/tpl 里 ship_000.png 这种角度图。不收 ship_icon.png。"""
    folder = config.SHIP_TPL
    names = []
    if os.path.isdir(folder):
        names = sorted(
            name
            for name in os.listdir(folder)
            if len(name) == len("ship_000.png") and name.startswith("ship_") and name.endswith(".png") and name[5:8].isdigit()
        )
    out: list[Needle] = []
    for name in names:
        out.append(load_needle(os.path.join(folder, name), glass=False))
    return out


def load_ship_hud() -> list[Needle]:
    """误检排除：只认 tpl 里的 hud1/hud2/hud3。"""
    out: list[Needle] = []
    for name in config.SHIP_HUD_NAMES:
        path = os.path.join(config.SHIP_TPL, name)
        if os.path.isfile(path):
            out.append(load_needle(path, glass=False))
    return out


def _overlap(ax1: int, ay1: int, ax2: int, ay2: int, bx1: int, by1: int, bx2: int, by2: int) -> bool:
    return ax1 < bx2 and ax2 > bx1 and ay1 < by2 and ay2 > by1


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
        self._rotated: dict[str, list[Needle]] = {}
        self._ship_hud = load_ship_hud()
        div = int(getattr(config, "SHIP_ROTATE_DIV", 0) or 0)
        for name, path in TEMPLATES.items():
            needle = load_needle(path, glass=name not in NO_GLASS)
            self.needles[name] = needle
            if name == "ship_icon":
                angles = load_ship_angles()
                if angles:
                    self._rotated[name] = angles
                elif name in ROTATE_TEMPLATES and div > 0:
                    steps = [i * (360.0 / div) for i in range(div)]
                    self._rotated[name] = [rotate_needle(needle, a) for a in steps]
                continue
            if name in ROTATE_TEMPLATES and div > 0:
                steps = [i * (360.0 / div) for i in range(div)]
                self._rotated[name] = [rotate_needle(needle, a) for a in steps]

    def _needles_for(self, name: str) -> list[Needle]:
        return self._rotated.get(name) or [self.needles[name]]

    def hud_ship_region(self, frame: np.ndarray) -> tuple[int, int, int, int]:
        """船队栏位置。优先用对齐结果，否则按图的宽高放在左侧。整张图不去配。左 HUD 先不用。"""
        h, w = frame.shape[:2]
        ship = self.needles.get("hud_ship")
        if ship is None:
            return (0, 140, min(140, w), min(520, h - 140))
        nh, nw = ship.bgr.shape[:2]
        placed = _placed("hud_ship", min(nw, w), min(nh, h))
        if placed is not None:
            return placed
        y0 = 215
        return (0, y0, min(nw, w), min(nh, max(1, h - y0)))

    def hud_ref(self, name: str, frame: np.ndarray) -> tuple[int, int, int, int]:
        h, w = frame.shape[:2]
        needle = self.needles[name]
        th, tw = needle.bgr.shape[:2]
        rw, rh = min(tw, w), min(th, h)
        placed = _placed(name, rw, rh)
        if placed is not None:
            return placed
        if name == "hud_left":
            return (0, 0, rw, rh)
        x = max(0, w - rw)
        y = max(0, h - rh - config.HUD_RIGHT_BOTTOM_GAP)
        if y + rh > h:
            y = max(0, h - rh)
        return (x, y, rw, min(rh, h - y))

    def _locked_region(self, name: str, frame: np.ndarray) -> tuple[int, int, int, int] | None:
        if name in SHIP_BAR_ONLY:
            return self.hud_ship_region(frame)
        if name in RIGHT_HUD_ONLY:
            return self.hud_ref("hud_right", frame)
        return None

    def search_region(self, name: str, frame: np.ndarray) -> tuple[int, int, int, int] | None:
        """正式查找范围。None 表示整屏。HUD测试必须用同一份，不要另写一套。"""
        locked = self._locked_region(name, frame)
        if locked is not None:
            return locked
        return None

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
        if self._locked_region(name, frame) is not None:
            return self.find(frame, name, thresh)
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
        if self._locked_region(name, frame) is not None:
            return self.find_all(frame, name, thresh)
        x, y, w, h = region
        crop = frame[y : y + h, x : x + w]
        hits = self.find_all(crop, name, thresh)
        return [
            Hit(hit.name, hit.score, hit.x1 + x, hit.y1 + y, hit.x2 + x, hit.y2 + y)
            for hit in hits
        ]

    def find_all(self, frame: np.ndarray, name: str, thresh: float | None = None) -> list[Hit]:
        locked = self._locked_region(name, frame)
        if locked is not None:
            x, y, w, h = locked
            crop = frame[y : y + h, x : x + w]
            if crop.size == 0:
                return []
            raw = self._match_all(crop, name, thresh)
            return [
                Hit(hit.name, hit.score, hit.x1 + x, hit.y1 + y, hit.x2 + x, hit.y2 + y)
                for hit in raw
            ]
        hits = self._match_all(frame, name, thresh)
        if name == "ship_icon":
            hits = self._drop_ship_hud(frame, hits)
        return hits

    def _drop_ship_hud(self, frame: np.ndarray, hits: list[Hit]) -> list[Hit]:
        if not hits or not self._ship_hud:
            return hits
        binary = hull_binary(frame)
        boxes: list[tuple[int, int, int, int]] = []
        for needle in self._ship_hud:
            if needle.bgr.shape[0] > binary.shape[0] or needle.bgr.shape[1] > binary.shape[1]:
                continue
            res = score_map(binary, needle)
            ys, xs = np.where(res >= config.thresh_for("ship_hud"))
            nh, nw = needle.bgr.shape[:2]
            for y, x in zip(ys.tolist(), xs.tolist()):
                boxes.append((int(x), int(y), int(x) + nw, int(y) + nh))
        if not boxes:
            return hits
        kept = []
        for hit in hits:
            if any(_overlap(hit.x1, hit.y1, hit.x2, hit.y2, *box) for box in boxes):
                continue
            kept.append(hit)
        return kept

    def _match_all(self, frame: np.ndarray, name: str, thresh: float | None = None) -> list[Hit]:
        if thresh is None:
            thresh = config.thresh_for(name)
        if name == "ship_icon":
            frame = hull_binary(frame)
        elif name in COLOR_BINS:
            frame = color_binary(frame, name)
        cand: list[Hit] = []
        for needle in self._needles_for(name):
            if needle.bgr.shape[0] > frame.shape[0] or needle.bgr.shape[1] > frame.shape[1]:
                continue
            if name == "ship_icon":
                res = ship_similarity(frame, needle)
            elif name in COLOR_BINS:
                res = color_similarity(frame, color_binary(needle.bgr, name))
            else:
                res = score_map(frame, needle)
            loc = np.where(res >= thresh)
            if loc[0].size > 300:
                scores = res[loc]
                pick = np.argpartition(scores, -300)[-300:]
                loc = (loc[0][pick], loc[1][pick])
            nh, nw = needle.bgr.shape[:2]
            for y, x in zip(loc[0].tolist(), loc[1].tolist()):
                x1, y1 = int(x), int(y)
                cand.append(Hit(name, float(res[y, x]), x1, y1, x1 + nw, y1 + nh))
        cand.sort(key=lambda h: -h.score)
        kept: list[Hit] = []
        for hit in cand:
            cx, cy = hit.center
            rw = hit.x2 - hit.x1
            rh = hit.y2 - hit.y1
            if any(
                abs(cx - k.center[0]) < max(12, rw // 2) and abs(cy - k.center[1]) < max(12, rh // 2)
                for k in kept
            ):
                continue
            kept.append(hit)
        return kept

    def best(self, frame: np.ndarray, name: str) -> tuple[float, tuple[int, int]]:
        locked = self._locked_region(name, frame)
        if locked is not None:
            x, y, w, h = locked
            crop = frame[y : y + h, x : x + w]
            score, loc = self._best_raw(crop, name)
            if loc[0] < 0:
                return score, loc
            return score, (loc[0] + x, loc[1] + y)
        return self._best_raw(frame, name)

    def _best_raw(self, frame: np.ndarray, name: str) -> tuple[float, tuple[int, int]]:
        if name == "ship_icon":
            frame = hull_binary(frame)
        elif name in COLOR_BINS:
            frame = color_binary(frame, name)
        best_v, best_xy = 0.0, (-1, -1)
        for needle in self._needles_for(name):
            if needle.bgr.shape[0] > frame.shape[0] or needle.bgr.shape[1] > frame.shape[1]:
                continue
            if name == "ship_icon":
                res = ship_similarity(frame, needle)
            elif name in COLOR_BINS:
                res = color_similarity(frame, color_binary(needle.bgr, name))
            else:
                res = score_map(frame, needle)
            _minv, maxv, _minl, maxl = cv2.minMaxLoc(res)
            if float(maxv) > best_v:
                best_v = float(maxv)
                best_xy = (int(maxl[0]), int(maxl[1]))
        return best_v, best_xy

    def draw(self, frame: np.ndarray, hits: list[Hit]) -> np.ndarray:
        out = frame.copy()
        for hit in hits:
            cv2.rectangle(out, (hit.x1, hit.y1), (hit.x2, hit.y2), (0, 0, 255), 2)
            cx, cy = hit.center
            cv2.drawMarker(out, (cx, cy), (0, 255, 255), cv2.MARKER_CROSS, 12, 2)
            label = f"{hit.name} {hit.score:.2f}"
            cv2.putText(out, label, (hit.x1, max(16, hit.y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        return out
