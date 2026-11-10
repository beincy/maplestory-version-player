# coding: utf-8
"""血条/蓝条监控：按配置区域统计条色像素占比，估算剩余比例。"""
from __future__ import annotations

import cv2
import numpy as np

from app_config import VitalConfig

# HSV 颜色范围:条色像素的判定区间(H: 0-179, S/V: 0-255)
_COLOR_RANGES: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {
    'red': [
        (np.array([0, 80, 80]), np.array([10, 255, 255])),
        (np.array([170, 80, 80]), np.array([179, 255, 255])),
    ],
    'blue': [
        (np.array([95, 80, 80]), np.array([130, 255, 255])),
    ],
    'green': [
        (np.array([40, 80, 80]), np.array([90, 255, 255])),
    ],
    'yellow': [
        (np.array([20, 80, 80]), np.array([38, 255, 255])),
    ],
}


def get_ratio(frame_bgr: np.ndarray, cfg: VitalConfig) -> float | None:
    """计算指定区域的条色像素占比(0~1)。

    前提:条是"纯色填充",剩余比例 ≈ 条色像素占区域比例。
    区域无效或图像过小返回 None。
    """
    fh, fw = frame_bgr.shape[:2]
    x2, y2 = cfg.x + cfg.w, cfg.y + cfg.h
    if cfg.x < 0 or cfg.y < 0 or x2 > fw or y2 > fh or cfg.w <= 0 or cfg.h <= 0:
        return None
    roi = frame_bgr[cfg.y:y2, cfg.x:x2]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    ranges = _COLOR_RANGES.get(cfg.color)
    if not ranges:
        return None
    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for low, high in ranges:
        mask |= cv2.inRange(hsv, low, high)
    total = mask.size
    if total == 0:
        return None
    return float(np.count_nonzero(mask)) / float(total)


def draw_vital_rect(frame_bgr: np.ndarray, cfg: VitalConfig, ratio: float | None,
                    color_bgr: tuple[int, int, int]) -> np.ndarray:
    """在帧上画监控区域框和比例文字(预览用)。"""
    out = frame_bgr
    cv2.rectangle(out, (cfg.x, cfg.y), (cfg.x + cfg.w, cfg.y + cfg.h), color_bgr, 2)
    text = 'N/A' if ratio is None else f'{ratio * 100:.0f}%'
    cv2.putText(out, text, (cfg.x, max(cfg.y - 6, 12)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color_bgr, 1)
    return out
