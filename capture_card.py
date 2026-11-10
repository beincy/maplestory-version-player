# coding: utf-8
"""HDMI 采集卡读取：独立线程持续抓帧，保留最新一帧供识别使用。"""
from __future__ import annotations

import threading
import time

import cv2
import numpy as np


class CaptureCard:
    """采集卡后台抓帧线程。

    用法：
        cap = CaptureCard(index=0)
        cap.start()
        frame = cap.get_frame()  # numpy BGR 图，无新帧时返回 None
        cap.stop()
    """

    # 后端名 -> OpenCV 常量(Windows 下 msmf 首开慢/兼容性差时可改 dshow)
    _BACKENDS: dict[str, int] = {
        'any': cv2.CAP_ANY,
        'msmf': cv2.CAP_MSMF,
        'dshow': cv2.CAP_DSHOW,
        'avfoundation': cv2.CAP_AVFOUNDATION,
        'v4l2': cv2.CAP_V4L2,
    }

    def __init__(self, index: int = 0, width: int = 1920, height: int = 1080,
                 backend: str = 'any') -> None:
        self.index: int = index
        self.width: int = width
        self.height: int = height
        self.backend: str = backend if backend in self._BACKENDS else 'any'
        self._cap: cv2.VideoCapture | None = None
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self.last_error: str = ''

    def _open(self) -> bool:
        """打开采集卡设备。"""
        try:
            cap = cv2.VideoCapture(self.index, self._BACKENDS[self.backend])
            if not cap.isOpened():
                cap.release()
                self.last_error = f'无法打开采集卡索引 {self.index}'
                return False
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            cap.set(cv2.CAP_PROP_FPS, 30)
            # 关闭自动曝光等干扰项(部分采集卡忽略,无害)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self._cap = cap
            return True
        except Exception as e:  # noqa: BLE001 设备层异常统一兜底
            self.last_error = f'打开采集卡异常: {e}'
            return False

    def start(self) -> bool:
        """启动抓帧线程,返回是否成功打开设备。"""
        if self._running:
            return True
        if not self._open():
            return False
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def _run(self) -> None:
        """抓帧主循环:失败自动重连。"""
        fail_count = 0
        while self._running:
            cap = self._cap
            if cap is None:
                break
            ok, frame = cap.read()
            if ok and frame is not None:
                with self._lock:
                    self._frame = frame
                fail_count = 0
            else:
                fail_count += 1
                if fail_count >= 30:  # 连续失败约 3 秒后重连
                    fail_count = 0
                    self.last_error = '读取失败,尝试重连采集卡'
                    try:
                        cap.release()
                    except Exception:  # noqa: BLE001
                        pass
                    if not self._open():
                        time.sleep(2)
                    continue
                time.sleep(0.1)

    def get_frame(self) -> np.ndarray | None:
        """取最新一帧(BGR),无帧返回 None。"""
        with self._lock:
            if self._frame is None:
                return None
            return self._frame.copy()

    def is_running(self) -> bool:
        return self._running

    def stop(self) -> None:
        """停止线程并释放设备。"""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:  # noqa: BLE001
                pass
            self._cap = None
        with self._lock:
            self._frame = None

    def reopen(self, index: int) -> bool:
        """更换设备索引重连。"""
        self.stop()
        self.index = index
        return self.start()
