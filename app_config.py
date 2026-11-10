# coding: utf-8
"""配置管理：JSON 持久化，整个文件夹自包含，拷走即可用。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / 'config.json'
TEMPLATE_DIR = Path(__file__).resolve().parent / 'assets' / 'templates'


@dataclass
class MonsterEntry:
    """一条怪物模板：图片文件 + 对应技能按键。"""
    name: str
    file: str  # 相对 assets/templates 的文件名
    key: str = 'A'
    enabled: bool = True
    threshold: float = 0.8

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'file': self.file,
            'key': self.key,
            'enabled': self.enabled,
            'threshold': self.threshold,
        }

    @staticmethod
    def from_dict(d: dict) -> 'MonsterEntry':
        return MonsterEntry(
            name=str(d.get('name', '')),
            file=str(d.get('file', '')),
            key=str(d.get('key', 'A')),
            enabled=bool(d.get('enabled', True)),
            threshold=float(d.get('threshold', 0.8)),
        )


@dataclass
class VitalConfig:
    """血条/蓝条配置：屏幕区域 + 颜色 + 低于阈值时按的键。"""
    enabled: bool = False
    x: int = 0
    y: int = 0
    w: int = 100
    h: int = 12
    color: str = 'red'  # red=血条 blue=蓝条
    ratio_threshold: float = 0.3  # 低于该比例(0~1)触发喝药
    key: str = 'SHIFT'
    cooldown_s: float = 2.0  # 两次喝药最小间隔

    def to_dict(self) -> dict:
        return {
            'enabled': self.enabled,
            'x': self.x, 'y': self.y, 'w': self.w, 'h': self.h,
            'color': self.color,
            'ratio_threshold': self.ratio_threshold,
            'key': self.key,
            'cooldown_s': self.cooldown_s,
        }

    @staticmethod
    def from_dict(d: dict, default_color: str) -> 'VitalConfig':
        return VitalConfig(
            enabled=bool(d.get('enabled', False)),
            x=int(d.get('x', 0)),
            y=int(d.get('y', 0)),
            w=int(d.get('w', 100)),
            h=int(d.get('h', 12)),
            color=str(d.get('color', default_color)),
            ratio_threshold=float(d.get('ratio_threshold', 0.3)),
            key=str(d.get('key', 'SHIFT')),
            cooldown_s=float(d.get('cooldown_s', 2.0)),
        )


@dataclass
class SimConfig:
    """仿真微动配置：没人操作时小幅移动/跳跃，让行为更像人。"""
    enabled: bool = True
    min_interval_s: float = 8.0
    max_interval_s: float = 20.0
    quiet_after_cast_s: float = 3.0  # 刚放过技能的安静期内不动
    actions: list[str] = field(default_factory=lambda: ['LEFT', 'RIGHT', 'JUMP'])

    def to_dict(self) -> dict:
        return {
            'enabled': self.enabled,
            'min_interval_s': self.min_interval_s,
            'max_interval_s': self.max_interval_s,
            'quiet_after_cast_s': self.quiet_after_cast_s,
            'actions': list(self.actions),
        }

    @staticmethod
    def from_dict(d: dict) -> 'SimConfig':
        return SimConfig(
            enabled=bool(d.get('enabled', True)),
            min_interval_s=float(d.get('min_interval_s', 8.0)),
            max_interval_s=float(d.get('max_interval_s', 20.0)),
            quiet_after_cast_s=float(d.get('quiet_after_cast_s', 3.0)),
            actions=list(d.get('actions', ['LEFT', 'RIGHT', 'JUMP'])),
        )


@dataclass
class AppConfig:
    """全局配置。"""
    capture_index: int = 0
    capture_backend: str = 'any'  # any/msmf/dshow/avfoundation/v4l2, Windows 无画面时改 dshow
    serial_port: str = ''  # 留空 = 干跑模式(只识别不按键)
    serial_baud: int = 115200
    detect_interval_ms: int = 250
    hud_ignore_top: int = 120  # 忽略画面顶部像素行(HUD区,避免误识别)
    cast_cooldown_s: float = 0.8  # 两次技能施放最小间隔
    monsters: list[MonsterEntry] = field(default_factory=list)
    hp: VitalConfig = field(default_factory=lambda: VitalConfig(color='red'))
    mp: VitalConfig = field(default_factory=lambda: VitalConfig(color='blue', key='SHIFT'))
    sim: SimConfig = field(default_factory=SimConfig)

    def to_dict(self) -> dict:
        return {
            'capture_index': self.capture_index,
            'capture_backend': self.capture_backend,
            'serial_port': self.serial_port,
            'serial_baud': self.serial_baud,
            'detect_interval_ms': self.detect_interval_ms,
            'hud_ignore_top': self.hud_ignore_top,
            'cast_cooldown_s': self.cast_cooldown_s,
            'monsters': [m.to_dict() for m in self.monsters],
            'hp': self.hp.to_dict(),
            'mp': self.mp.to_dict(),
            'sim': self.sim.to_dict(),
        }

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @staticmethod
    def load() -> 'AppConfig':
        if not CONFIG_PATH.exists():
            return AppConfig()
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                d = json.load(f)
        except (json.JSONDecodeError, OSError):
            return AppConfig()
        cfg = AppConfig()
        cfg.capture_index = int(d.get('capture_index', 0))
        cfg.capture_backend = str(d.get('capture_backend', 'any'))
        cfg.serial_port = str(d.get('serial_port', ''))
        cfg.serial_baud = int(d.get('serial_baud', 115200))
        cfg.detect_interval_ms = int(d.get('detect_interval_ms', 250))
        cfg.hud_ignore_top = int(d.get('hud_ignore_top', 120))
        cfg.cast_cooldown_s = float(d.get('cast_cooldown_s', 0.8))
        cfg.monsters = [MonsterEntry.from_dict(m) for m in d.get('monsters', [])]
        cfg.hp = VitalConfig.from_dict(d.get('hp', {}), default_color='red')
        cfg.mp = VitalConfig.from_dict(d.get('mp', {}), default_color='blue')
        cfg.sim = SimConfig.from_dict(d.get('sim', {}))
        return cfg


def list_template_files() -> list[Path]:
    """列出已上传的模板图片。"""
    if not TEMPLATE_DIR.exists():
        return []
    return sorted(p for p in TEMPLATE_DIR.iterdir()
                  if p.suffix.lower() in ('.png', '.jpg', '.jpeg', '.bmp'))
