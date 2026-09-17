"""离线验证：只拿固定按钮/图标去对画面，不拿整张 target。

名字、血量、等级数字、奖励、邀请人都不参与匹配。
在项目根目录运行: python verify_match.py
"""
from __future__ import annotations

import os

import cv2
import numpy as np

from vision import load_bgr, load_needle, score_map

ROOT = os.path.dirname(os.path.abspath(__file__))
PIC = os.path.join(ROOT, "pic", "stable")
THRESH = 0.90


def match(hay: np.ndarray, needle_path: str) -> tuple[float, tuple[int, int]]:
    needle = load_needle(needle_path)
    if needle.bgr.shape[0] > hay.shape[0] or needle.bgr.shape[1] > hay.shape[1]:
        return 0.0, (-1, -1)
    res = score_map(hay, needle)
    _minv, maxv, _minl, maxl = cv2.minMaxLoc(res)
    return float(maxv), (int(maxl[0]), int(maxl[1]))


def main() -> None:
    cases = [
        # 模板, 场景, 说明, 阈值
        ("search.png", "hud.png", "主界面搜寻放大镜", 0.90),
        ("button3.png", "goal0.png", "爪牙面板上也能找到贡品船页签", 0.90),
        ("button3.png", "target2_ok.png", "选中贡品船后页签仍能匹配", 0.90),
        ("button4.png", "goal0.png", "黄搜寻（爪牙面板，默认30不拖）", 0.90),
        ("button4.png", "target2_ok.png", "黄搜寻按钮（等级4）", 0.90),
        ("button5.png", "target3.png", "红集结按钮（血量/倒计时不在按钮上）", 0.90),
        ("button.png", "target.png", "攻击（玩家名不在按钮上）", 0.90),
        ("button2.png", "target.png", "传送（不要点）", 0.90),
        ("goal0_atk.png", "goal0_atk.png", "爪牙攻擊按钮自检", 0.99),
        ("repair.png", "repair.png", "修理按钮自检", 0.99),
        ("rally_confirm.png", "hud3.png", "黄确认集结", 0.90),
        ("rally_confirm.png", "settings.png", "新settings含战舰选择", 0.90),
        ("invite_yes.png", "quest.png", "邀请对勾（用户裁切）", 0.90),
        ("invite_no.png", "quest.png", "邀请叉（用户裁切）", 0.90),
        ("prayer_label.png", "quest.png", "至高祈祷舰（quest_name）", 0.90),
        ("flag.png", "settings.png", "组队旗(已在队)", 0.80),
        ("trading.png", "settings.png", "商运中舰队", 0.85),
        ("rally_time_block3.png", "settings.png", "3分钟选项（未选中时的圆+字）", 0.90),
        ("rally_time_block3.png", "hud3.png", "3分钟选项在完整HUD", 0.90),
        ("rally_time_button_off.png", "settings.png", "未选中的时间圆点", 0.95),
        ("mail.png", "hud.png", "HUD邮件箱", 0.90),
        ("win.png", "box.png", "邮件胜利标", 0.90),
        ("new.png", "box.png", "未读红点", 0.85),
        ("loot.png", "box.png", "邮件奖励箱", 0.90),
    ]
    print("offline match")
    print("-" * 72)
    failed = 0
    for tmpl_rel, scene_rel, note, thresh in cases:
        tmpl_path = os.path.join(PIC, tmpl_rel)
        scene_path = os.path.join(PIC, scene_rel)
        if not os.path.isfile(tmpl_path) or not os.path.isfile(scene_path):
            print(f"FAIL  missing  {tmpl_rel}  vs  {scene_rel}")
            failed += 1
            continue
        scene = load_bgr(scene_path)
        score, loc = match(scene, tmpl_path)
        ok = score >= thresh
        if not ok:
            failed += 1
        flag = "OK  " if ok else "FAIL"
        print(f"{flag}  {score:.3f}>={thresh:.2f}  {loc}  {tmpl_rel:28s} -> {scene_rel:16s}  {note}")

    print("-" * 72)
    print("不要拿整张去匹配（名字/等级会变）: target.png target2.png target3.png quest.png accepted.png settings.png")
    print("用: button*.png search.png stable/invite_yes.png stable/rally_confirm.png")
    if failed:
        raise SystemExit(f"{failed} failed")
    print("all passed")


if __name__ == "__main__":
    main()
