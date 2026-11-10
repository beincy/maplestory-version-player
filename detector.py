# coding: utf-8
"""怪物模板匹配检测：多模板单尺度匹配，返回命中列表。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app_config import MonsterEntry, TEMPLATE_DIR


@dataclass
class Detection:
    """一次模板命中。"""
    name: str
    key: str
    x: int
    y: int
    w: int
    h: int
    score: float


def read_image(path) -> np.ndarray | None:
    """读图片,兼容中文/非 ASCII 路径(cv2.imread 在 Windows 上读不了中文路径)。"""
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except OSError:
        return None


class MonsterDetector:
    """灰度模板匹配器。模板缺失自动跳过,加载失败不影响整体运行。"""

    def __init__(self) -> None:
        self._templates: dict[str, np.ndarray] = {}  # name -> 灰度模板图

    def reload(self, monsters: list[MonsterEntry]) -> None:
        """按配置加载全部启用的模板。"""
        self._templates.clear()
        for m in monsters:
            if not m.enabled:
                continue
            path = TEMPLATE_DIR / m.file
            if not path.exists():
                continue
            img_color = read_image(path)
            img = cv2.cvtColor(img_color, cv2.COLOR_BGR2GRAY) if img_color is not None else None
            if img is None:
                continue
            self._templates[m.name] = img

    def match(self, frame_bgr: np.ndarray, monsters: list[MonsterEntry],
              hud_ignore_top: int) -> list[Detection]:
        """在整帧中匹配所有模板。

        :param frame_bgr: BGR 原始帧
        :param monsters: 配置里的怪物列表(用于取 name -> key/threshold)
        :param hud_ignore_top: 忽略画面顶部像素行(HUD 区)
        :return: 命中列表(每个模板只取最高分位置)
        """
        if not self._templates:
            return []
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        cfg_by_name = {m.name: m for m in monsters}
        results: list[Detection] = []
        for name, tpl in self._templates.items():
            m = cfg_by_name.get(name)
            if m is None:
                continue
            th, tw = tpl.shape[:2]
            if th >= gray.shape[0] or tw >= gray.shape[1]:
                continue
            res = cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val < m.threshold:
                continue
            # 命中位置落在 HUD 忽略区内则不算(只挡顶部)
            if max_loc[1] < hud_ignore_top and max_loc[1] + th <= hud_ignore_top:
                continue
            results.append(Detection(
                name=name, key=m.key,
                x=max_loc[0], y=max_loc[1], w=tw, h=th,
                score=float(max_val),
            ))
        results.sort(key=lambda d: d.score, reverse=True)
        return results

    @staticmethod
    def draw_detections(frame_bgr: np.ndarray, detections: list[Detection]) -> np.ndarray:
        """在帧上画命中框(预览用,不改原图)。"""
        out = frame_bgr.copy()
        for d in detections:
            cv2.rectangle(out, (d.x, d.y), (d.x + d.w, d.y + d.h), (0, 255, 0), 2)
            cv2.putText(out, f'{d.name} {d.score:.2f}', (d.x, max(d.y - 6, 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        return out
