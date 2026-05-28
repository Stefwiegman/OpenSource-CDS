"""Automatische raster-scan voor Bep-Project — burst-mode voor MEMS vibratie.

Voor elk raster-punt:
  GOTO → BUSY?-poll → settle → één Moku Datalogger burst (fs × T samples)
       → opslaan als raw/point_NNNNN.csv + 1 rij in index.csv → volgend punt.

Output per scan-run:
    data/scan_<datum>_<naam>/
        metadata.txt
        index.csv                # 1 rij per scan-punt (motor-positie, file-ref)
        raw/point_00000.csv      # 2 kolommen: t_s, (dz1_mm | voltage_V), NL-locale
        raw/point_00001.csv
        ...
"""
from __future__ import annotations

import csv
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd
import yaml

from PySide6.QtCore import Qt, QEvent, QRect, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStyle,
    QStyledItemDelegate,
)


PRESETS_PATH = Path("scan_presets.yaml")
DATA_ROOT = Path("data")

POLL_BUSY_MS = 80     # hoe vaak we BUSY? sturen tijdens MOVING
SETTLE_DEFAULT = 200
FS_DEFAULT_KHZ = 1000  # 1000 kSa/s = 1 MHz (Moku:Go Datalogger-max) → Nyquist 500 kHz
T_DEFAULT_MS = 10      # 10 ms → FFT-bin 100 Hz

INDEX_CSV_HEADER = [
    "t_iso", "i", "ix", "iy",
    "motor1", "motor2", "motor3",
    "motor1_mm", "motor2_mm", "motor3_mm",
    "lamp",
    "fs_Hz", "T_ms", "n_samples",
    "raw_file",
    "settle_ms",
]


def _fmt(v: float) -> str:
    return f"{v:.5f}".replace(".", ",")


# -------------------- Config + presets --------------------

@dataclass
class ScanConfig:
    name: str = "scan"
    size_x_mm: float = 5.0
    size_y_mm: float = 5.0
    points_x: int = 25
    points_y: int = 25
    settle_ms: int = SETTLE_DEFAULT
    fs_khz: int = FS_DEFAULT_KHZ
    burst_T_ms: int = T_DEFAULT_MS
    snake: bool = True

    def total_points(self) -> int:
        return self.points_x * self.points_y

    def samples_per_point(self) -> int:
        return int(self.fs_khz * 1000 * self.burst_T_ms / 1000)


def load_presets() -> List[dict]:
    # Bestand ontbreekt → eerste keer: toon de ingebouwde defaults.
    if not PRESETS_PATH.exists():
        return _default_presets()
    try:
        data = yaml.safe_load(PRESETS_PATH.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return _default_presets()
    presets = data.get("presets")
    # Sleutel afwezig → defaults. Expliciet lege lijst → respecteer (alles verwijderd).
    if presets is None:
        return _default_presets()
    return presets


def save_presets(presets: List[dict]) -> None:
    PRESETS_PATH.write_text(
        yaml.safe_dump({"presets": presets}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _default_presets() -> List[dict]:
    return [
        {"name": "MEMS Verkennend 1×1 mm  (10×10)",
         "size_x_mm": 1.0, "size_y_mm": 1.0,
         "points_x": 10, "points_y": 10, "settle_ms": 100,
         "fs_khz": 100, "burst_T_ms": 200, "snake": True},
        {"name": "MEMS Standaard 2×2 mm  (25×25)",
         "size_x_mm": 2.0, "size_y_mm": 2.0,
         "points_x": 25, "points_y": 25, "settle_ms": 200,
         "fs_khz": 100, "burst_T_ms": 500, "snake": True},
        {"name": "MEMS Diep 5×5 mm  (25×25, hoge Q)",
         "size_x_mm": 5.0, "size_y_mm": 5.0,
         "points_x": 25, "points_y": 25, "settle_ms": 200,
         "fs_khz": 250, "burst_T_ms": 1000, "snake": True},
    ]


# -------------------- State machine --------------------

class ScanState(Enum):
    IDLE = "idle"
    MOVING = "moving"
    SETTLING = "settling"
    COLLECTING = "collecting"
    DONE = "done"


def build_path(cfg: ScanConfig) -> List[tuple[int, int]]:
    """Genereer (ix, iy)-volgorde over het hele raster — snake-pad."""
    path: List[tuple[int, int]] = []
    for iy in range(cfg.points_y):
        xs = range(cfg.points_x)
        if cfg.snake and (iy % 2 == 1):
            xs = reversed(xs)
        for ix in xs:
            path.append((ix, iy))
    return path


# -------------------- Preset-dropdown met verwijder-kruisje --------------------

class _PresetItemDelegate(QStyledItemDelegate):
    """Tekent een ✕ rechts in elke verwijderbare preset-rij (rij ≥ 1)."""

    HIT_W = 26  # breedte van het klik-gebied voor het kruisje (px)

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        if index.row() < 1:
            return  # rij 0 = "(custom)" → niet verwijderbaar
        rect = option.rect
        hit = QRect(rect.right() - self.HIT_W, rect.top(), self.HIT_W, rect.height())
        painter.save()
        painter.setPen(QColor("#e06c75") if (option.state & QStyle.State_MouseOver)
                       else QColor("#8a939d"))
        painter.drawText(hit, Qt.AlignCenter, "✕")
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(size.height(), 28))  # ruimer = makkelijker klikken
        return size


# -------------------- ScanPanel --------------------

class ScanPanel(QGroupBox):
    """UI + state-machine voor automatische scans."""

    scan_started = Signal(str)        # path naar index.csv
    scan_finished = Signal(str, int)  # path, n_points

    def __init__(self, motor_panel, lamp_panel, moku_panel) -> None:
        super().__init__("Automatische scan")
        self.motor_panel = motor_panel
        self.lamp_panel = lamp_panel
        self.moku_panel = moku_panel

        self._state = ScanState.IDLE
        self._path: List[tuple[int, int]] = []
        self._idx = 0
        self._origin: tuple[int, int] = (0, 0)
        self._step_x = 0
        self._step_y = 0
        self._csv_file = None
        self._csv_writer = None
        self._run_dir: Path | None = None
        self._raw_dir: Path | None = None
        self._t0 = 0.0
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(POLL_BUSY_MS)
        self._poll_timer.timeout.connect(self._poll_busy)
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.timeout.connect(self._enter_collecting)

        self._build_ui()
        self._refresh_preset_combo()

    # ---------- UI bouw ----------

    def _build_ui(self) -> None:
        layout = QGridLayout(self)
        layout.setVerticalSpacing(12)
        layout.setHorizontalSpacing(10)
        r = 0

        # Run-naam
        layout.addWidget(QLabel("Naam:"), r, 0)
        self.name_input = QLineEdit("scan")
        layout.addWidget(self.name_input, r, 1, 1, 3)
        r += 1

        # Preset
        layout.addWidget(QLabel("Preset:"), r, 0)
        self.preset_combo = QComboBox()
        self.preset_combo.setToolTip("Kies een preset. Klik het ✕ in de lijst om te verwijderen.")
        self.preset_combo.activated.connect(self._on_preset_select)
        # Custom delegate tekent een ✕ per verwijderbare rij; een event-filter op
        # de viewport vangt de klik erop af (zonder de preset te selecteren).
        self.preset_combo.setItemDelegate(_PresetItemDelegate(self.preset_combo))
        self.preset_combo.view().viewport().installEventFilter(self)
        layout.addWidget(self.preset_combo, r, 1, 1, 2)
        self.save_preset_btn = QPushButton("Opslaan…")
        self.save_preset_btn.setToolTip("Sla de huidige instellingen op als preset")
        self.save_preset_btn.clicked.connect(self._save_current_preset)
        layout.addWidget(self.save_preset_btn, r, 3)
        r += 1

        # Sample-grootte (X-as | Y-as)
        layout.addWidget(QLabel("Grootte X-as (mm):"), r, 0)
        self.size_x = QDoubleSpinBox(); self.size_x.setRange(0.001, 100.0)
        self.size_x.setDecimals(3); self.size_x.setValue(5.0)
        layout.addWidget(self.size_x, r, 1)
        layout.addWidget(QLabel("Grootte Y-as (mm):"), r, 2)
        self.size_y = QDoubleSpinBox(); self.size_y.setRange(0.001, 100.0)
        self.size_y.setDecimals(3); self.size_y.setValue(5.0)
        layout.addWidget(self.size_y, r, 3)
        r += 1

        # Resolutie (N×N raster)
        layout.addWidget(QLabel("Resolutie:"), r, 0)
        self.resolution = QSpinBox()
        self.resolution.setRange(2, 1000)
        self.resolution.setValue(25)
        self.resolution.setToolTip("N × N raster (25 = 625 punten)")
        layout.addWidget(self.resolution, r, 1)
        # Settle-tijd is een vaste waarde (SETTLE_DEFAULT) — geen UI-veld meer.
        r += 1

        # Burst-parameters: sample-rate en duur
        layout.addWidget(QLabel("Sample-rate (kSa/s):"), r, 0)
        self.fs_khz = QSpinBox(); self.fs_khz.setRange(1, 1000)
        self.fs_khz.setSingleStep(10)
        self.fs_khz.setValue(FS_DEFAULT_KHZ)
        self.fs_khz.setToolTip("Hoger = hogere maximale frequentie (Nyquist = fs/2)")
        layout.addWidget(self.fs_khz, r, 1)
        layout.addWidget(QLabel("Burst (ms):"), r, 2)
        self.T_ms = QSpinBox(); self.T_ms.setRange(10, 10000)
        self.T_ms.setSingleStep(50)
        self.T_ms.setValue(T_DEFAULT_MS)
        self.T_ms.setToolTip("Langer = fijnere FFT-frequentie-resolutie (1/T)")
        layout.addWidget(self.T_ms, r, 3)
        r += 1

        # ETA-kaart — eigen rij, prominent gestyled
        self.estimate_lbl = QLabel("—")
        self.estimate_lbl.setObjectName("EtaCard")
        self.estimate_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.estimate_lbl, r, 0, 1, 4)
        r += 1

        # Live-update van schatting
        for w in (self.size_x, self.size_y, self.resolution,
                  self.fs_khz, self.T_ms):
            w.valueChanged.connect(self._update_estimate)

        # Start / Cancel — exact gelijke breedte via QGridLayout-kolommen,
        # exact gelijke hoogte via setFixedHeight
        btn_grid = QGridLayout()
        btn_grid.setContentsMargins(0, 0, 0, 0)
        btn_grid.setSpacing(10)
        btn_grid.setColumnStretch(0, 1)
        btn_grid.setColumnStretch(1, 1)

        self.start_btn = QPushButton("▶ Start scan")
        self.start_btn.setObjectName("PrimaryButton")
        self.start_btn.setFixedHeight(52)
        self.start_btn.clicked.connect(self._start_scan)
        btn_grid.addWidget(self.start_btn, 0, 0)

        self.cancel_btn = QPushButton("■ Cancel")
        self.cancel_btn.setFixedHeight(52)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_scan)
        btn_grid.addWidget(self.cancel_btn, 0, 1)

        layout.addLayout(btn_grid, r, 0, 1, 4)
        r += 1

        # Progress (ONDER de start/cancel rij)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress, r, 0, 1, 4)
        r += 1

        self.status = QLabel("Stand-by.")
        self.status.setStyleSheet("color: gray;")
        layout.addWidget(self.status, r, 0, 1, 4)
        r += 1

        # Spacer onderaan — duwt alles naar boven i.p.v. uitrekken
        layout.setRowStretch(r, 1)

        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 1)

        # Iets ruimere inputs voor luchtigere uitstraling
        for w in (self.name_input, self.preset_combo, self.save_preset_btn,
                  self.size_x, self.size_y, self.resolution,
                  self.fs_khz, self.T_ms):
            w.setMinimumHeight(34)

        # Initial state
        self._update_estimate()

    # ---------- Preset-handling ----------

    def _refresh_preset_combo(self) -> None:
        self.preset_combo.clear()
        self.preset_combo.addItem("(custom)")
        for p in load_presets():
            self.preset_combo.addItem(p.get("name", "(naamloos)"))

    def _on_preset_select(self, idx: int) -> None:
        if idx <= 0:
            return
        presets = load_presets()
        if idx - 1 >= len(presets):
            return
        p = presets[idx - 1]
        self.size_x.setValue(p.get("size_x_mm", 2.0))
        self.size_y.setValue(p.get("size_y_mm", 2.0))
        # Resolutie = points_x (oude presets met aparte points_y nemen we als points_x over)
        self.resolution.setValue(int(p.get("points_x", 25)))
        # settle_ms uit oude presets negeren we — settle is nu een vaste waarde.
        self.fs_khz.setValue(int(p.get("fs_khz", FS_DEFAULT_KHZ)))
        self.T_ms.setValue(int(p.get("burst_T_ms", T_DEFAULT_MS)))

    def _save_current_preset(self) -> None:
        name, ok = QInputDialog.getText(self, "Preset opslaan",
                                        "Naam voor deze preset:")
        if not ok or not name.strip():
            return
        preset = asdict(self._read_config(name=name.strip()))
        presets = load_presets()
        # vervang als naam al bestaat
        presets = [p for p in presets if p.get("name") != name.strip()]
        presets.append(preset)
        save_presets(presets)
        self._refresh_preset_combo()
        self.status.setText(f"Preset '{name.strip()}' opgeslagen.")

    def eventFilter(self, obj, event):
        """Vang klikken op het ✕-kruisje in de preset-dropdown af."""
        view = self.preset_combo.view()
        if obj is view.viewport() and event.type() == QEvent.MouseButtonRelease:
            pos = event.position().toPoint()
            idx = view.indexAt(pos)
            if idx.isValid() and idx.row() >= 1:
                rect = view.visualRect(idx)
                if pos.x() >= rect.right() - _PresetItemDelegate.HIT_W:
                    self._delete_preset_at(idx.row())
                    return True  # klik niet doorgeven → preset wordt niet geselecteerd
        return super().eventFilter(obj, event)

    def _delete_preset_at(self, row: int) -> None:
        presets = load_presets()
        pi = row - 1                       # rij 0 = "(custom)"
        if pi < 0 or pi >= len(presets):
            return
        name = presets[pi].get("name", "(naamloos)")
        reply = QMessageBox.question(
            self, "Preset verwijderen?", f"Preset '{name}' verwijderen?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        del presets[pi]
        save_presets(presets)
        self.preset_combo.hidePopup()
        self._refresh_preset_combo()
        self.preset_combo.setCurrentIndex(0)
        self.status.setText(f"Preset '{name}' verwijderd.")
        self.status.setStyleSheet("color: gray;")

    # ---------- Config-helpers ----------

    def _read_config(self, name: str | None = None) -> ScanConfig:
        res = self.resolution.value()
        return ScanConfig(
            name=name or self.name_input.text() or "scan",
            size_x_mm=self.size_x.value(),
            size_y_mm=self.size_y.value(),
            points_x=res,
            points_y=res,
            settle_ms=SETTLE_DEFAULT,
            fs_khz=self.fs_khz.value(),
            burst_T_ms=self.T_ms.value(),
            snake=True,
        )

    def _update_estimate(self) -> None:
        cfg = self._read_config()
        n = cfg.total_points()
        # Heuristiek: settle + burst-T + 0.3s motor + 0.2s overhead per punt
        per_pt = (cfg.settle_ms + cfg.burst_T_ms) / 1000.0 + 0.5
        total_s = n * per_pt
        mm = int(total_s // 60)
        ss = int(total_s - mm * 60)
        # Schatting disk-grootte: fs × T × 4 bytes (float32) per punt
        mb = n * cfg.samples_per_point() * 4 / (1024 * 1024)
        self.estimate_lbl.setText(
            f"ETA: ~{mm}m {ss}s   ·   {n} punten   ·   ~{mb:.1f} MB"
        )

    # ---------- Pre-flight checks ----------

    def _preflight(self, cfg: ScanConfig) -> str | None:
        """Geef foutmelding terug, of None als alles ok is."""
        if self._state != ScanState.IDLE:
            return "Scan is al actief."
        if not (self.motor_panel.serial and self.motor_panel.serial.is_open):
            return "Motoren niet verbonden — verbind eerst MotorPanel."
        axes = ("X", "Y")
        for i in range(2):
            if self.motor_panel.mm_per_step(i) <= 0:
                return (f"Motor {i+1} ({axes[i]}-as) heeft mm/stap = 0 — eik eerst "
                        "in MotorPanel of vul mm/stap-veld in.")
        if self.moku_panel.thread is None or not self.moku_panel.thread.isRunning():
            return "Moku niet verbonden — verbind eerst MokuPanel."
        if not self.moku_panel.I0:
            return (
                "I0 niet ingesteld — ga naar de Manual-tab en vul de I0-baseline "
                "(referentie-intensiteit) in."
            )
        return None

    # ---------- Start / cancel ----------

    def _start_scan(self) -> None:
        cfg = self._read_config()
        err = self._preflight(cfg)
        if err is not None:
            QMessageBox.warning(self, "Kan scan niet starten", err)
            return

        # Bereken stappen-per-rasterpunt en oorsprong (huidige motor-positie = midden)
        mmps_x = self.motor_panel.mm_per_step(0)
        mmps_y = self.motor_panel.mm_per_step(1)

        steps_x_total = round(cfg.size_x_mm / mmps_x)
        steps_y_total = round(cfg.size_y_mm / mmps_y)
        self._step_x = steps_x_total // (cfg.points_x - 1)
        self._step_y = steps_y_total // (cfg.points_y - 1)

        cur = self.motor_panel.targets
        # Origin = linksonder van het raster = huidige positie - halve grootte
        ox = cur[0] - steps_x_total // 2
        oy = cur[1] - steps_y_total // 2
        self._origin = (ox, oy)

        # Run-dir + raw/ subfolder + index.csv openen
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_name = (cfg.name or "scan").strip().replace(" ", "_")
        self._run_dir = DATA_ROOT / f"scan_{ts}_{safe_name}"
        self._run_dir.mkdir(parents=True, exist_ok=True)
        self._raw_dir = self._run_dir / "raw"
        self._raw_dir.mkdir(exist_ok=True)
        csv_path = self._run_dir / "index.csv"
        self._csv_file = open(csv_path, "w", newline="", encoding="utf-8")
        self._csv_writer = csv.writer(self._csv_file, delimiter=";")
        self._csv_writer.writerow(INDEX_CSV_HEADER)

        # Metadata
        meta = self._run_dir / "metadata.txt"
        mp = self.moku_panel
        fs_hz = cfg.fs_khz * 1000
        I0_str = f"{mp.I0:.6f}" if mp.I0 is not None else "not_set"
        sample_unit = "mm (dz1, dz1_minus tak van A6)" if mp.I0 else "V"
        meta.write_text(
            "# Bep-Project automatische scan (burst-mode)\n"
            "# as-mapping: motor1 = X-as, motor2 = Y-as, motor3 = Z-as (focus)\n"
            f"start: {datetime.now().isoformat(timespec='seconds')}\n"
            f"name: {cfg.name}\n"
            f"mode: datalogger_burst_per_point\n"
            f"size_x_mm: {cfg.size_x_mm}\n"
            f"size_y_mm: {cfg.size_y_mm}\n"
            f"points_x: {cfg.points_x}\n"
            f"points_y: {cfg.points_y}\n"
            f"step_x_steps: {self._step_x}\n"
            f"step_y_steps: {self._step_y}\n"
            f"settle_ms: {cfg.settle_ms}\n"
            f"fs_Hz: {fs_hz}\n"
            f"burst_T_ms: {cfg.burst_T_ms}\n"
            f"samples_per_point: {cfg.samples_per_point()}\n"
            f"sample_format: csv per punt (t_s, value), NL-locale (; sep, , decimal)\n"
            f"sample_unit: {sample_unit}\n"
            f"I0_V: {I0_str}\n"
            f"snake: {cfg.snake}\n"
            f"origin_steps: {self._origin}\n"
            f"motor1_mm_per_step: {mmps_x:.6f}\n"
            f"motor2_mm_per_step: {mmps_y:.6f}\n"
            f"moku_address: {mp.address_input.text()}\n"
            f"moku_channel: {mp.channel_combo.currentText()}\n"
            f"moku_range: {mp.range_combo.currentText()}\n"
            f"moku_coupling: {mp.coupling_combo.currentText()}\n",
            encoding="utf-8",
        )

        # Switch Moku naar Datalogger-mode (eenmalig, live preview pauzeert)
        try:
            self.moku_panel.start_burst_mode()
        except Exception as e:
            self._csv_file.close()
            self._csv_file = None
            self._csv_writer = None
            QMessageBox.critical(
                self, "Burst-mode mislukt",
                f"Kan Moku niet in Datalogger-mode zetten:\n{e}",
            )
            return

        # Path bouwen
        self._cfg = cfg
        self._path = build_path(cfg)
        self._idx = 0
        self._t0 = time.monotonic()

        self.progress.setRange(0, len(self._path))
        self.progress.setValue(0)
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self._set_inputs_enabled(False)
        self.status.setText(
            f"Scan gestart → {csv_path.name}  ({len(self._path)} punten, "
            f"{cfg.samples_per_point()} samples/punt)"
        )
        self.status.setStyleSheet("color: #1e8449; font-weight: bold;")
        self.scan_started.emit(str(csv_path))

        self._next_point()

    def _cancel_scan(self) -> None:
        if self._state == ScanState.IDLE:
            return
        self._poll_timer.stop()
        self._settle_timer.stop()
        # Stuur STOP zodat motoren netjes uitlopen
        try:
            if self.motor_panel.serial and self.motor_panel.serial.is_open:
                self.motor_panel.serial.write(b"STOP\n")
                self.motor_panel.serial.flush()
        except Exception:
            pass
        self._finish(canceled=True)

    # ---------- State machine ----------

    def _next_point(self) -> None:
        if self._idx >= len(self._path):
            self._finish(canceled=False)
            return
        ix, iy = self._path[self._idx]
        ox, oy = self._origin
        target_x = ox + ix * self._step_x
        target_y = oy + iy * self._step_y
        # Motor 3 (focus) blijft staan op huidige positie
        target_z = self.motor_panel.targets[2]

        # Update verwachte targets in motor_panel (zodat recording etc. consistent zijn)
        self.motor_panel.targets[0] = target_x
        self.motor_panel.targets[1] = target_y
        for i in range(2):
            self.motor_panel._refresh_target_label(i)

        cmd = f"GOTO {target_x} {target_y} {target_z}\n"
        try:
            self.motor_panel.serial.write(cmd.encode("ascii"))
            self.motor_panel.serial.flush()
        except Exception as e:
            self.status.setText(f"Schrijf-fout: {e}")
            self._cancel_scan()
            return

        self._state = ScanState.MOVING
        self._poll_timer.start()
        self._update_progress_label(ix, iy)

    def _poll_busy(self) -> None:
        if self._state != ScanState.MOVING:
            return
        ser = self.motor_panel.serial
        if ser is None or not ser.is_open:
            self._cancel_scan()
            return
        try:
            ser.reset_input_buffer()
            ser.write(b"BUSY?\n")
            ser.flush()
            for _ in range(8):
                line = ser.readline().decode("ascii", errors="ignore").strip()
                if not line:
                    return  # nog niet klaar — probeer in volgende tick
                if line.startswith("BUSY "):
                    busy = line.split()[-1] == "1"
                    if not busy:
                        self._poll_timer.stop()
                        self._enter_settling()
                    return
        except Exception as e:
            self.status.setText(f"Polling-fout: {e}")
            self._cancel_scan()

    def _enter_settling(self) -> None:
        self._state = ScanState.SETTLING
        self._settle_timer.start(self._cfg.settle_ms)

    def _enter_collecting(self) -> None:
        """Doe één Datalogger-burst voor het huidige punt en ga door."""
        if self._state == ScanState.IDLE:
            return  # geannuleerd tijdens settle
        self._state = ScanState.COLLECTING
        ix, iy = self._path[self._idx]
        try:
            fs_hz = self._cfg.fs_khz * 1000
            T_s = self._cfg.burst_T_ms / 1000.0
            samples = self.moku_panel.acquire_burst(fs_hz, T_s)
        except Exception as e:
            self.status.setText(f"Burst-fout op punt {self._idx}: {e}")
            self._cancel_scan()
            return

        try:
            self._save_point(ix, iy, samples)
        except Exception as e:
            self.status.setText(f"Schrijf-fout: {e}")
            self._cancel_scan()
            return

        self._idx += 1
        self.progress.setValue(self._idx)
        self._next_point()

    def _save_point(self, ix: int, iy: int, samples: np.ndarray) -> None:
        if self._csv_writer is None or self._raw_dir is None:
            return
        raw_file = f"point_{self._idx:05d}.csv"
        # CSV per punt: t_s + dz1_mm (of voltage_V), NL-locale.
        # samples = ruwe voltage; met I0 rekenen we om naar verplaatsing via A6.
        fs_hz = self._cfg.fs_khz * 1000
        t = np.arange(samples.size, dtype=np.float64) / fs_hz
        I0 = self.moku_panel.I0
        if I0:
            from datalogger import voltage_to_dz1
            value_col, values = "dz1_mm", voltage_to_dz1(samples, I0)
        else:
            value_col, values = "voltage_V", samples
        df = pd.DataFrame({"t_s": t, value_col: values})
        df.to_csv(self._raw_dir / raw_file, sep=";", decimal=",",
                  index=False, float_format="%.7e")

        steps = list(self.motor_panel.targets)
        mms = [steps[i] * self.motor_panel.mm_per_step(i) for i in range(3)]
        row = [
            datetime.now().isoformat(timespec="milliseconds"),
            self._idx,
            ix, iy,
            steps[0], steps[1], steps[2],
            _fmt(mms[0]), _fmt(mms[1]), _fmt(mms[2]),
            self.lamp_panel.slider.value(),
            self._cfg.fs_khz * 1000,
            self._cfg.burst_T_ms,
            int(samples.size),
            raw_file,
            self._cfg.settle_ms,
        ]
        self._csv_writer.writerow(row)
        if self._csv_file is not None:
            self._csv_file.flush()

    def _finish(self, canceled: bool) -> None:
        self._poll_timer.stop()
        self._settle_timer.stop()
        # Sluit Moku burst-mode af (herstart live preview)
        try:
            self.moku_panel.end_burst_mode()
        except Exception:
            pass
        if self._csv_file is not None:
            try:
                self._csv_file.flush()
                self._csv_file.close()
            except Exception:
                pass
            if self._run_dir is not None:
                try:
                    elapsed = time.monotonic() - self._t0
                    with (self._run_dir / "metadata.txt").open("a", encoding="utf-8") as f:
                        f.write(
                            f"end: {datetime.now().isoformat(timespec='seconds')}\n"
                            f"canceled: {canceled}\n"
                            f"completed_points: {self._idx}\n"
                            f"elapsed_s: {elapsed:.1f}\n"
                        )
                except Exception:
                    pass
        path_str = str(self._run_dir / "index.csv") if self._run_dir else ""
        n = self._idx
        self._csv_file = None
        self._csv_writer = None
        self._state = ScanState.IDLE
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self._set_inputs_enabled(True)
        if canceled:
            self.status.setText(f"Scan geannuleerd na {n} punten.")
            self.status.setStyleSheet("color: #b8860b;")
        else:
            self.status.setText(f"Scan voltooid — {n} punten → {path_str}")
            self.status.setStyleSheet("color: #1e8449; font-weight: bold;")
        self.scan_finished.emit(path_str, n)

    def _update_progress_label(self, ix: int, iy: int) -> None:
        total = len(self._path)
        self.status.setText(
            f"Punt {self._idx + 1}/{total}  (ix={ix}, iy={iy})"
        )

    def _set_inputs_enabled(self, enabled: bool) -> None:
        for w in (
            self.name_input, self.preset_combo, self.save_preset_btn,
            self.size_x, self.size_y, self.resolution,
            self.fs_khz, self.T_ms,
        ):
            w.setEnabled(enabled)

    def cancel_if_running(self) -> None:
        if self._state != ScanState.IDLE:
            self._cancel_scan()
