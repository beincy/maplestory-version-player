# coding: utf-8
"""自动化主引擎：采集 → 识别 → 决策 → 按键 的节拍循环。"""
from __future__ import annotations

import random
import time

import numpy as np
from PySide6.QtCore import QThread, Signal

from app_config import AppConfig
from capture_card import CaptureCard
from detector import Detection, MonsterDetector
from hid_keyboard import Esp32Keyboard
from vitals import draw_vital_rect, get_ratio


class AutoEngine(QThread):
    """后台节拍循环线程。

    信号:
        frame_ready: 预览帧(已叠加识别框)
        log_msg:     日志行
        status:      状态字典 {monsters, hp_ratio, mp_ratio, casts, potions, dry_run}
    """

    frame_ready = Signal(np.ndarray)
    log_msg = Signal(str)
    status = Signal(dict)

    def __init__(self, cfg: AppConfig) -> None:
        super().__init__()
        self.cfg: AppConfig = cfg
        self.capture: CaptureCard = CaptureCard(cfg.capture_index, backend=cfg.capture_backend)
        self.keyboard: Esp32Keyboard = Esp32Keyboard()
        self.detector: MonsterDetector = MonsterDetector()
        self._running = False
        # 统计
        self.cast_count: int = 0
        self.potion_count: int = 0
        self._last_cast_time: float = 0.0
        self._last_hp_time: float = 0.0
        self._last_mp_time: float = 0.0
        self._next_sim_time: float = 0.0

    # ---------- 生命周期 ----------

    def start_engine(self) -> bool:
        """启动引擎。返回 False 表示采集卡打开失败。"""
        self.detector.reload(self.cfg.monsters)
        self.keyboard.connect(self.cfg.serial_port, self.cfg.serial_baud)
        if not self.capture.start():
            self.log_msg.emit(f'❌ 采集卡打开失败: {self.capture.last_error}')
            return False
        self.log_msg.emit('✅ 采集卡已启动')
        if self.keyboard.is_dry_run():
            self.log_msg.emit('⚠️ 干跑模式:未连接 ESP32 串口,只识别不按键')
        else:
            self.log_msg.emit(f'✅ ESP32 键盘已连接 {self.cfg.serial_port}')
        self.cast_count = 0
        self.potion_count = 0
        self._last_cast_time = 0.0
        self._last_hp_time = 0.0
        self._last_mp_time = 0.0
        self._schedule_next_sim(time.time())
        self._running = True
        self.start()
        return True

    def stop_engine(self) -> None:
        """停止引擎并释放资源。"""
        self._running = False
        self.wait(3000)
        self.capture.stop()
        self.keyboard.disconnect()
        self.log_msg.emit('⏹ 引擎已停止')

    def refresh_templates(self) -> None:
        """配置变更后重载模板。"""
        self.detector.reload(self.cfg.monsters)
        self.log_msg.emit(f'🔄 模板已重载,启用 {len(self.detector._templates)} 个')  # noqa: SLF001

    # ---------- 主循环 ----------

    def run(self) -> None:
        interval_s = max(self.cfg.detect_interval_ms, 100) / 1000.0
        while self._running:
            loop_start = time.time()
            frame = self.capture.get_frame()
            if frame is None:
                time.sleep(0.05)
                continue

            # 1. 怪物检测 + 技能
            detections = self.detector.match(frame, self.cfg.monsters,
                                             self.cfg.hud_ignore_top)
            if detections:
                self._maybe_cast(detections)

            # 2. 血蓝检测 + 喝药
            hp_ratio = self._maybe_potion(frame, self.cfg.hp, is_hp=True)
            mp_ratio = self._maybe_potion(frame, self.cfg.mp, is_hp=False)

            # 3. 仿真微动
            self._maybe_simulate(hp_ratio, mp_ratio, detections)

            # 4. 预览帧
            self._emit_preview(frame, detections, self.cfg.hp, hp_ratio, self.cfg.mp, mp_ratio)
            self.status.emit({
                'monsters': len(detections),
                'hp_ratio': hp_ratio,
                'mp_ratio': mp_ratio,
                'casts': self.cast_count,
                'potions': self.potion_count,
                'dry_run': self.keyboard.is_dry_run(),
            })

            # 5. 节拍控制
            elapsed = time.time() - loop_start
            remain = interval_s - elapsed
            if remain > 0:
                time.sleep(min(remain, 0.05) if remain > 0.05 else remain)

    # ---------- 决策动作 ----------

    def _maybe_cast(self, detections: list[Detection]) -> None:
        """检测到怪物且技能冷却已到 → 放对应技能。"""
        now = time.time()
        if now - self._last_cast_time < self.cfg.cast_cooldown_s:
            return
        target = detections[0]  # 分数最高的
        if self.keyboard.tap(target.key, 60):
            self._last_cast_time = now
            self.cast_count += 1
            dry = '(干跑)' if self.keyboard.is_dry_run() else ''
            self.log_msg.emit(f'⚔️ 检测到 [{target.name}] 分数{target.score:.2f} → 放技能 {target.key} {dry}')

    def _maybe_potion(self, frame: np.ndarray, cfg, is_hp: bool) -> float | None:
        """血/蓝低于阈值且冷却已到 → 按喝药键。返回当前比例供预览。"""
        if not cfg.enabled:
            return None
        ratio = get_ratio(frame, cfg)
        if ratio is None:
            return None
        now = time.time()
        last = self._last_hp_time if is_hp else self._last_mp_time
        if ratio < cfg.ratio_threshold and now - last >= cfg.cooldown_s:
            if is_hp:
                self._last_hp_time = now
            else:
                self._last_mp_time = now
            if self.keyboard.tap(cfg.key, 60):
                self.potion_count += 1
                tag = '血' if is_hp else '蓝'
                dry = '(干跑)' if self.keyboard.is_dry_run() else ''
                self.log_msg.emit(f'🧪 {tag}量 {ratio * 100:.0f}% < {cfg.ratio_threshold * 100:.0f}% → 按 {cfg.key} {dry}')
        return ratio

    def _schedule_next_sim(self, now: float) -> None:
        """安排下一次微动时间。"""
        cfg = self.cfg.sim
        interval = random.uniform(cfg.min_interval_s, cfg.max_interval_s)
        self._next_sim_time = now + interval

    def _maybe_simulate(self, hp_ratio: float | None, mp_ratio: float | None,
                        detections: list[Detection]) -> None:
        """仿真微动:随机小幅移动/跳跃,降低机器感。血蓝过低时不乱动。"""
        cfg = self.cfg.sim
        if not cfg.enabled or not cfg.actions:
            return
        now = time.time()
        if now < self._next_sim_time:
            return
        self._schedule_next_sim(now)
        # 刚放过技能/正在喝药的安静期不动
        if now - self._last_cast_time < cfg.quiet_after_cast_s:
            return
        if (hp_ratio is not None and hp_ratio < self.cfg.hp.ratio_threshold) or \
           (mp_ratio is not None and mp_ratio < self.cfg.mp.ratio_threshold):
            return
        action = random.choice(cfg.actions)
        dry = '(干跑)' if self.keyboard.is_dry_run() else ''
        if action == 'JUMP':
            self.keyboard.tap('SPACE', 60)
            self.log_msg.emit(f'🤖 仿真: 跳跃 {dry}')
        else:
            move_ms = random.randint(80, 160)
            self.keyboard.tap(action, move_ms)
            self.log_msg.emit(f'🤖 仿真: {action} {move_ms}ms {dry}')

    def _emit_preview(self, frame: np.ndarray, detections: list[Detection],
                      hp_cfg, hp_ratio: float | None, mp_cfg, mp_ratio: float | None) -> None:
        """叠加识别框与监控框后发出预览帧。"""
        out = frame.copy()
        if hp_cfg.enabled:
            out = draw_vital_rect(out, hp_cfg, hp_ratio, (0, 0, 255))
        if mp_cfg.enabled:
            out = draw_vital_rect(out, mp_cfg, mp_ratio, (255, 144, 30))
        out = MonsterDetector.draw_detections(out, detections)
        self.frame_ready.emit(out)
