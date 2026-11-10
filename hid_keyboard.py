# coding: utf-8
"""ESP32-S3 虚拟键盘客户端：串口发指令，ESP32 端固件转成真实 USB HID 键盘信号。

协议(与 firmware/esp32s3_hid/esp32s3_hid.ino 对应,行式文本):
    DOWN:<键名>\n      按下不放
    UP:<键名>\n        松开
    TAP:<键名>,<毫秒>\n  按下,延时,松开
串口留空 = 干跑模式:不连接任何设备,只打日志,方便无硬件调试。
"""
from __future__ import annotations

import threading
import time

try:
    import serial  # pyserial
except ImportError:  # 允许无 pyserial 环境下干跑
    serial = None  # type: ignore[assignment]

# 键名白名单(与固件映射表一致)
KEY_NAMES: list[str] = [
    'SPACE', 'ENTER', 'ESC', 'TAB', 'SHIFT', 'CTRL', 'ALT',
    'UP', 'DOWN', 'LEFT', 'RIGHT',
    'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M',
    'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z',
    '0', '1', '2', '3', '4', '5', '6', '7', '8', '9',
    'F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12',
    'INSERT', 'DELETE', 'HOME', 'END', 'PAGEUP', 'PAGEDOWN',
]
_VALID_KEYS = set(KEY_NAMES)


class Esp32Keyboard:
    """串口键盘客户端。线程安全(内部加锁)。"""

    def __init__(self) -> None:
        self._ser = None  # serial.Serial
        self._port: str = ''
        self._baud: int = 115200
        self._lock = threading.Lock()
        self.dry_run: bool = True
        self.last_error: str = ''

    def connect(self, port: str, baud: int = 115200) -> bool:
        """连接 ESP32。port 为空则进入干跑模式。"""
        self.disconnect()
        self._port, self._baud = port, baud
        if not port:
            self.dry_run = True
            return True
        if serial is None:
            self.last_error = '未安装 pyserial,进入干跑模式'
            self.dry_run = True
            return False
        try:
            self._ser = serial.Serial(port, baud, timeout=0.5)
            self.dry_run = False
            return True
        except Exception as e:  # noqa: BLE001 串口异常统一兜底
            self._ser = None
            self.dry_run = True
            self.last_error = f'串口打开失败: {e}'
            return False

    def disconnect(self) -> None:
        """断开连接并确保按键全部松开。"""
        with self._lock:
            if self._ser is not None:
                try:
                    self._ser.close()
                except Exception:  # noqa: BLE001
                    pass
            self._ser = None
            self.dry_run = True

    def is_dry_run(self) -> bool:
        return self._ser is None

    def _send(self, line: str) -> bool:
        with self._lock:
            ser = self._ser
            if ser is None:
                return True  # 干跑模式视为成功
            try:
                ser.write((line + '\n').encode('ascii'))
                return True
            except Exception as e:  # noqa: BLE001
                self.last_error = f'串口写入失败: {e}'
                return False

    def down(self, key: str) -> bool:
        """按下不放。"""
        key = key.upper()
        if key not in _VALID_KEYS:
            return False
        return self._send(f'DOWN:{key}')

    def up(self, key: str) -> bool:
        """松开。"""
        key = key.upper()
        if key not in _VALID_KEYS:
            return False
        return self._send(f'UP:{key}')

    def tap(self, key: str, duration_ms: int = 60) -> bool:
        """敲一下:按下 → duration_ms → 松开。"""
        key = key.upper()
        if key not in _VALID_KEYS:
            return False
        return self._send(f'TAP:{key},{max(20, int(duration_ms))}')

    def combo(self, keys: list[str], hold_ms: int = 400) -> None:
        """组合键:依次按下全部 → hold_ms → 反向依次松开。

        用于"跳跃+方向"这类操作,时序由本机控制。
        """
        for k in keys:
            self.down(k)
            time.sleep(0.02)
        time.sleep(hold_ms / 1000.0)
        for k in reversed(keys):
            self.up(k)
