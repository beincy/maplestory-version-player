# coding: utf-8
"""小工具主界面：采集预览、怪物模板管理、血蓝设置、仿真微动、启停控制。"""
from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QGroupBox,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app_config import AppConfig, MonsterEntry, TEMPLATE_DIR
from auto_engine import AutoEngine
from detector import read_image
from hid_keyboard import KEY_NAMES

try:
    from serial.tools import list_ports
except ImportError:
    list_ports = None  # type: ignore[assignment]

IMAGE_FILTER = '图片 (*.png *.jpg *.jpeg *.bmp)'


def frame_to_pixmap(frame_bgr: np.ndarray, width: int = 0) -> QPixmap:
    """BGR ndarray → QPixmap。width>0 时按宽缩放。"""
    frame = np.ascontiguousarray(frame_bgr)
    h, w, _ = frame.shape
    img = QImage(frame.data, w, h, w * 3, QImage.Format.Format_BGR888)
    pm = QPixmap.fromImage(img)
    if width > 0 and w > width:
        pm = pm.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
    return pm


class RegionPickerDialog(QDialog):
    """在当前帧上点两下框选区域,返回原始分辨率坐标 (x, y, w, h)。"""

    def __init__(self, frame_bgr: np.ndarray, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f'{title} - 点击左上角和右下角')
        self._frame = frame_bgr
        fh, fw = frame_bgr.shape[:2]
        disp_w = min(960, fw)
        self._scale = disp_w / fw
        disp_h = int(fh * self._scale)
        pm = frame_to_pixmap(frame_bgr, width=disp_w)
        self._label = QLabel()
        self._label.setPixmap(pm)
        self._label.setFixedSize(disp_w, disp_h)
        self._points: list[tuple[int, int]] = []
        layout = QVBoxLayout(self)
        layout.addWidget(self._label)
        hint = QLabel('第 1 次点击 = 区域左上角,第 2 次点击 = 区域右下角')
        layout.addWidget(hint)

    def mousePressEvent(self, event) -> None:  # noqa: N802 Qt 约定命名
        pos = self._label.mapFrom(self, event.position().toPoint())
        x = min(max(int(pos.x() / self._scale), 0), self._frame.shape[1] - 1)
        y = min(max(int(pos.y() / self._scale), 0), self._frame.shape[0] - 1)
        self._points.append((x, y))
        if len(self._points) < 2:
            self.setWindowTitle(f'{title_of(self)} - 已选 1 点,再点右下角')
            return
        (x1, y1), (x2, y2) = self._points[0], self._points[1]
        rx, ry = min(x1, x2), min(y1, y2)
        rw, rh = abs(x2 - x1), abs(y2 - y1)
        if rw < 4 or rh < 3:
            self.setWindowTitle('区域太小,请重新点两下')
            self._points = [self._points[-1]]
            return
        self.result_rect = (rx, ry, rw, rh)
        self.accept()


def title_of(dialog: 'RegionPickerDialog') -> str:
    return dialog.windowTitle().split(' - ')[0]


class MainWindow(QMainWindow):
    """主窗口。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle('冒险岛挂机小工具 (scroll_od)')
        self.cfg: AppConfig = AppConfig.load()
        self.engine: AutoEngine | None = None
        self._last_frame: np.ndarray | None = None
        self._init_ui()
        self._load_monsters_to_table()

    # ---------- UI 构建 ----------

    def _init_ui(self) -> None:
        central = QWidget()
        root = QHBoxLayout(central)

        # 左列: 预览 + 日志
        left = QVBoxLayout()
        self.preview = QLabel('预览区(点「开始」后显示采集画面)')
        self.preview.setFixedHeight(480)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet('background:#222; color:#aaa;')
        left.addWidget(self.preview)
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFixedHeight(160)
        left.addWidget(self.log_box)
        root.addLayout(left, stretch=7)

        # 右列: 控制面板
        right = QVBoxLayout()
        right.addWidget(self._build_device_group())
        right.addWidget(self._build_monster_group())
        right.addWidget(self._build_vitals_group())
        right.addWidget(self._build_sim_group())
        right.addWidget(self._build_run_group())
        right.addStretch(1)
        root.addLayout(right, stretch=3)
        self.setCentralWidget(central)

    def _build_device_group(self) -> QGroupBox:
        box = QGroupBox('① 设备')
        layout = QHBoxLayout(box)
        layout.addWidget(QLabel('采集卡:'))
        self.capture_index = QSpinBox()
        self.capture_index.setRange(0, 9)
        self.capture_index.setValue(self.cfg.capture_index)
        layout.addWidget(self.capture_index)
        layout.addWidget(QLabel('串口:'))
        self.serial_combo = QComboBox()
        self.serial_combo.addItem('(干跑模式)')  # 空串口 = 干跑
        self._refresh_serial_ports()
        layout.addWidget(self.serial_combo, stretch=1)
        refresh_btn = QPushButton('刷新')
        refresh_btn.clicked.connect(self._refresh_serial_ports)
        layout.addWidget(refresh_btn)
        return box

    def _build_monster_group(self) -> QGroupBox:
        box = QGroupBox('② 怪物模板 (上传怪物图 → 分配技能键)')
        layout = QVBoxLayout(box)
        btn_row = QHBoxLayout()
        upload_btn = QPushButton('上传怪物图片')
        upload_btn.clicked.connect(self._upload_monsters)
        btn_row.addWidget(upload_btn)
        btn_row.addWidget(QLabel('技能全局冷却(秒):'))
        self.cast_cooldown = QDoubleSpinBox()
        self.cast_cooldown.setRange(0.1, 30.0)
        self.cast_cooldown.setSingleStep(0.1)
        self.cast_cooldown.setValue(self.cfg.cast_cooldown_s)
        btn_row.addWidget(self.cast_cooldown)
        layout.addLayout(btn_row)

        self.monster_table = QTableWidget(0, 6)
        self.monster_table.setHorizontalHeaderLabels(['预览', '名称', '按键', '阈值', '换图', '删除'])
        self.monster_table.setColumnWidth(0, 60)
        self.monster_table.setColumnWidth(1, 84)
        self.monster_table.setColumnWidth(2, 84)
        self.monster_table.setColumnWidth(3, 50)
        self.monster_table.setColumnWidth(4, 44)
        self.monster_table.setColumnWidth(5, 44)
        layout.addWidget(self.monster_table)
        return box

    def _build_vital_widgets(self, prefix: str, vital_cfg) -> dict:
        """构建一组血/蓝控件。"""
        w = {}
        w['enabled'] = QCheckBox()
        w['enabled'].setChecked(vital_cfg.enabled)
        w['pick'] = QPushButton('框选区域')
        w['pick'].clicked.connect(lambda: self._pick_vital_region(prefix))
        w['region_label'] = QLabel(self._region_text(vital_cfg))
        w['ratio'] = QDoubleSpinBox()
        w['ratio'].setRange(1.0, 99.0)
        w['ratio'].setSuffix('%')
        w['ratio'].setValue(vital_cfg.ratio_threshold * 100)
        w['key'] = QComboBox()
        w['key'].addItems(KEY_NAMES)
        w['key'].setCurrentText(vital_cfg.key)
        return w

    def _build_vitals_group(self) -> QGroupBox:
        box = QGroupBox('③ 血蓝保护 (低于阈值自动按键)')
        layout = QVBoxLayout(box)
        self.hp_widgets = self._build_vital_widgets('hp', self.cfg.hp)
        self.mp_widgets = self._build_vital_widgets('mp', self.cfg.mp)
        for title, w in (('血量', self.hp_widgets), ('蓝量', self.mp_widgets)):
            row = QHBoxLayout()
            row.addWidget(QLabel(title))
            row.addWidget(w['enabled'])
            row.addWidget(w['pick'])
            row.addWidget(w['region_label'], stretch=1)
            row.addWidget(QLabel('低于'))
            row.addWidget(w['ratio'])
            row.addWidget(QLabel('按键'))
            row.addWidget(w['key'])
            layout.addLayout(row)
        tip = QLabel('先点「开始」看到画面后,再点「框选区域」圈住血条/蓝条')
        tip.setStyleSheet('color:#888;')
        layout.addWidget(tip)
        return box

    def _build_sim_group(self) -> QGroupBox:
        box = QGroupBox('④ 仿真微动 (随机小幅移动/跳跃)')
        layout = QHBoxLayout(box)
        self.sim_enabled = QCheckBox('启用')
        self.sim_enabled.setChecked(self.cfg.sim.enabled)
        layout.addWidget(self.sim_enabled)
        layout.addWidget(QLabel('间隔(秒)'))
        self.sim_min = QDoubleSpinBox()
        self.sim_min.setRange(1.0, 600.0)
        self.sim_min.setValue(self.cfg.sim.min_interval_s)
        self.sim_max = QDoubleSpinBox()
        self.sim_max.setRange(2.0, 600.0)
        self.sim_max.setValue(self.cfg.sim.max_interval_s)
        layout.addWidget(self.sim_min)
        layout.addWidget(QLabel('~'))
        layout.addWidget(self.sim_max)
        layout.addWidget(QLabel('动作'))
        self.sim_left = QCheckBox('左移')
        self.sim_right = QCheckBox('右移')
        self.sim_jump = QCheckBox('跳跃')
        self.sim_left.setChecked('LEFT' in self.cfg.sim.actions)
        self.sim_right.setChecked('RIGHT' in self.cfg.sim.actions)
        self.sim_jump.setChecked('JUMP' in self.cfg.sim.actions)
        for w in (self.sim_left, self.sim_right, self.sim_jump):
            layout.addWidget(w)
        return box

    def _build_run_group(self) -> QGroupBox:
        box = QGroupBox('⑤ 运行')
        layout = QVBoxLayout(box)
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton('开始')
        self.start_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton('停止')
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        layout.addLayout(btn_row)
        self.status_label = QLabel('状态: 未运行')
        layout.addWidget(self.status_label)
        return box

    # ---------- 怪物表 ----------

    def _load_monsters_to_table(self) -> None:
        table = self.monster_table
        table.setRowCount(0)
        for m in self.cfg.monsters:
            self._append_monster_row(m)

    def _append_monster_row(self, m: MonsterEntry) -> None:
        table = self.monster_table
        row = table.rowCount()
        table.insertRow(row)
        # 预览缩略图
        img_cell = QLabel()
        img = read_image(TEMPLATE_DIR / m.file)
        if img is not None:
            img_cell.setPixmap(frame_to_pixmap(img, width=56))
        img_cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
        table.setCellWidget(row, 0, img_cell)
        table.setItem(row, 1, QTableWidgetItem(m.name))
        key_combo = QComboBox()
        key_combo.addItems(KEY_NAMES)
        key_combo.setCurrentText(m.key)
        table.setCellWidget(row, 2, key_combo)
        thr_spin = QDoubleSpinBox()
        thr_spin.setRange(0.5, 0.99)
        thr_spin.setSingleStep(0.01)
        thr_spin.setValue(m.threshold)
        table.setCellWidget(row, 3, thr_spin)
        rep_btn = QPushButton('换图')
        rep_btn.clicked.connect(lambda _, r=row: self._replace_monster_image(r))
        table.setCellWidget(row, 4, rep_btn)
        del_btn = QPushButton('删')
        del_btn.clicked.connect(lambda _, r=row: self._delete_monster_row(r))
        table.setCellWidget(row, 5, del_btn)

    def _find_monster_row(self, name: str) -> int | None:
        """按名称找表格行号,找不到返回 None。"""
        for row in range(self.monster_table.rowCount()):
            item = self.monster_table.item(row, 1)
            if item is not None and item.text() == name:
                return row
        return None

    def _refresh_row_thumbnail(self, row: int, m: MonsterEntry) -> None:
        """重画某行的缩略图。"""
        img_cell = QLabel()
        img = read_image(TEMPLATE_DIR / m.file)
        if img is not None:
            img_cell.setPixmap(frame_to_pixmap(img, width=56))
        img_cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.monster_table.setCellWidget(row, 0, img_cell)

    def _replace_monster_image(self, row: int) -> None:
        """替换某行模板的图片文件,保留名称/按键/阈值等设置。"""
        name_item = self.monster_table.item(row, 1)
        if name_item is None:
            return
        name = name_item.text()
        entry = next((m for m in self.cfg.monsters if m.name == name), None)
        if entry is None:
            return
        files, _ = QFileDialog.getOpenFileNames(self, f'替换 [{name}] 的模板图', '', IMAGE_FILTER)
        if not files:
            return
        src = Path(files[0])
        if read_image(src) is None:
            QMessageBox.warning(self, '错误', f'无法读取图片: {src.name}')
            return
        dst = TEMPLATE_DIR / f'{name}{src.suffix.lower()}'
        old = TEMPLATE_DIR / entry.file
        if old.exists() and old.resolve() != dst.resolve():
            old.unlink()  # 后缀变了才需要删旧文件,同后缀直接覆盖
        shutil.copy(src, dst)
        entry.file = dst.name
        self._refresh_row_thumbnail(row, entry)
        self.cfg.save()
        self._refresh_engine_templates()
        self._log(f'🔄 已替换模板 [{name}] ← {src.name}')

    def _delete_monster_row(self, row: int, confirm: bool = True) -> None:
        name_item = self.monster_table.item(row, 1)
        name = name_item.text() if name_item else ''
        if confirm and name:
            ans = QMessageBox.question(
                self, '删除模板',
                f'确定删除 [{name}] 吗?\n配置条目和模板图片文件会一起删除。',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ans != QMessageBox.StandardButton.Yes:
                return
        self.monster_table.removeRow(row)
        entry = next((m for m in self.cfg.monsters if m.name == name), None)
        if entry is not None:
            img_path = TEMPLATE_DIR / entry.file
            if img_path.exists():
                img_path.unlink()  # 连图片文件一起删,避免孤儿文件
            self.cfg.monsters.remove(entry)
        self.cfg.save()
        self._refresh_engine_templates()
        if name:
            self._log(f'🗑 已删除模板 [{name}] 及其图片')

    def _upload_monsters(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, '选择怪物图片', '', IMAGE_FILTER)
        if not files:
            return
        TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
        for f in files:
            src = Path(f)
            name = src.stem
            if read_image(f) is None:
                self._log(f'❌ 无法读取图片: {src.name}')
                continue
            existing = next((m for m in self.cfg.monsters if m.name == name), None)
            dst = TEMPLATE_DIR / f'{name}{src.suffix.lower()}'
            if existing is not None:
                ans = QMessageBox.question(
                    self, '模板已存在',
                    f'[{name}] 已存在,是否用新图替换?\n按键/阈值等设置保持不变。',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if ans != QMessageBox.StandardButton.Yes:
                    self._log(f'⏭ 已跳过 [{name}]')
                    continue
                old = TEMPLATE_DIR / existing.file
                if old.exists() and old.resolve() != dst.resolve():
                    old.unlink()
                shutil.copy(src, dst)
                existing.file = dst.name
                row = self._find_monster_row(name)
                if row is not None:
                    self._refresh_row_thumbnail(row, existing)
                self._log(f'🔄 已替换模板 [{name}]')
                continue
            shutil.copy(src, dst)
            entry = MonsterEntry(name=name, file=dst.name)
            self.cfg.monsters.append(entry)
            self._append_monster_row(entry)
            self._log(f'✅ 已上传怪物模板 [{name}],请在表格里分配技能按键')
        self.cfg.save()
        self._refresh_engine_templates()

    # ---------- 血蓝区域 ----------

    def _region_text(self, cfg) -> str:
        if not cfg.enabled:
            return '(未启用)'
        return f'({cfg.x},{cfg.y},{cfg.w}x{cfg.h})'

    def _pick_vital_region(self, prefix: str) -> None:
        if self._last_frame is None:
            QMessageBox.warning(self, '提示', '还没有画面。先点「开始」(干跑也可以),看到预览后再框选。')
            return
        title = '框选血条' if prefix == 'hp' else '框选蓝条'
        dialog = RegionPickerDialog(self._last_frame, title, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        rect = dialog.result_rect
        cfg = self.cfg.hp if prefix == 'hp' else self.cfg.mp
        cfg.x, cfg.y, cfg.w, cfg.h = rect
        cfg.enabled = True
        widgets = self.hp_widgets if prefix == 'hp' else self.mp_widgets
        widgets['enabled'].setChecked(True)
        widgets['region_label'].setText(self._region_text(cfg))
        self.cfg.save()
        self._log(f'✅ {title}区域已设置: {rect}')

    # ---------- 运行控制 ----------

    def _collect_cfg(self) -> None:
        """把界面上的值收回到配置对象。"""
        self.cfg.capture_index = self.capture_index.value()
        self.cfg.serial_port = '' if self.serial_combo.currentIndex() == 0 else self.serial_combo.currentText()
        self.cfg.cast_cooldown_s = self.cast_cooldown.value()
        # 怪物表
        table = self.monster_table
        by_name = {m.name: m for m in self.cfg.monsters}
        new_list: list[MonsterEntry] = []
        for row in range(table.rowCount()):
            name_item = table.item(row, 1)
            if name_item is None:
                continue
            name = name_item.text()
            m = by_name.get(name)
            if m is None:
                continue
            m.key = table.cellWidget(row, 2).currentText()
            m.threshold = table.cellWidget(row, 3).value()
            new_list.append(m)
        self.cfg.monsters = new_list
        # 血蓝
        for prefix, w in (('hp', self.hp_widgets), ('mp', self.mp_widgets)):
            cfg = self.cfg.hp if prefix == 'hp' else self.cfg.mp
            cfg.enabled = w['enabled'].isChecked()
            cfg.ratio_threshold = w['ratio'].value() / 100.0
            cfg.key = w['key'].currentText()
        # 仿真
        self.cfg.sim.enabled = self.sim_enabled.isChecked()
        self.cfg.sim.min_interval_s = self.sim_min.value()
        self.cfg.sim.max_interval_s = self.sim_max.value()
        actions = []
        if self.sim_left.isChecked():
            actions.append('LEFT')
        if self.sim_right.isChecked():
            actions.append('RIGHT')
        if self.sim_jump.isChecked():
            actions.append('JUMP')
        self.cfg.sim.actions = actions
        self.cfg.save()

    def _start(self) -> None:
        if self.engine is not None and self.engine.isRunning():
            return
        self._collect_cfg()
        self.engine = AutoEngine(self.cfg)
        self.engine.frame_ready.connect(self._on_frame)
        self.engine.log_msg.connect(self._log)
        self.engine.status.connect(self._on_status)
        if not self.engine.start_engine():
            self.engine = None
            return
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def _stop(self) -> None:
        if self.engine is not None:
            self.engine.stop_engine()
            self.engine = None
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText('状态: 未运行')

    def _refresh_engine_templates(self) -> None:
        if self.engine is not None and self.engine.isRunning():
            self._collect_cfg()
            self.engine.refresh_templates()

    # ---------- 信号处理 ----------

    def _on_frame(self, frame: np.ndarray) -> None:
        self._last_frame = frame
        self.preview.setPixmap(frame_to_pixmap(frame, width=720))

    def _on_status(self, s: dict) -> None:
        hp = 'N/A' if s['hp_ratio'] is None else f"{s['hp_ratio'] * 100:.0f}%"
        mp = 'N/A' if s['mp_ratio'] is None else f"{s['mp_ratio'] * 100:.0f}%"
        mode = '干跑' if s['dry_run'] else '实机'
        self.status_label.setText(
            f'状态: 运行中[{mode}] 怪物:{s["monsters"]} 血:{hp} 蓝:{mp} '
            f'技能:{s["casts"]} 喝药:{s["potions"]}'
        )

    def _log(self, msg: str) -> None:
        self.log_box.appendPlainText(msg)

    def _refresh_serial_ports(self) -> None:
        """刷新串口列表,保留干跑项在第一位。"""
        current = self.serial_combo.currentText()
        self.serial_combo.clear()
        self.serial_combo.addItem('(干跑模式)')
        if list_ports is not None:
            for p in list_ports.comports():
                self.serial_combo.addItem(p.device)
        if current:
            idx = self.serial_combo.findText(current)
            if idx >= 0:
                self.serial_combo.setCurrentIndex(idx)

    def closeEvent(self, event) -> None:  # noqa: N802 Qt 约定命名
        self._stop()
        super().closeEvent(event)
