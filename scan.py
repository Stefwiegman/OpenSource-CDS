"""Automatische raster-scan voor Bep-Project.

Doet wat een gebruiker handmatig zou doen, maar dan systematisch:
  voor elk (x, y) in het raster:
      stuur GOTO -> wacht op stilstand (BUSY?) -> settle -> verzamel N Moku-frames
      -> middel + log een rij -> volgende punt.

Optioneel Z-stack: herhaal het 2D-raster op meerdere Z-niveaus.

Schrijft naar data/scan_<datum>_<naam>/measurement.csv  (compatibel met viewer.py).
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
import yaml

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
)


PRESETS_PATH = Path("scan_presets.yaml")
DATA_ROOT = Path("data")

POLL_BUSY_MS = 80     # hoe vaak we BUSY? sturen tijdens MOVING
SETTLE_DEFAULT = 200
FRAMES_DEFAULT = 5

CSV_HEADER = [
    "t_iso", "scan_point", "ix", "iy", "iz",
    "motor1", "motor2", "motor3",
    "motor1_mm", "motor2_mm", "motor3_mm",
    "lamp",
    "V_mean", "V_min", "V_max", "V_std", "V_pp",
    "n_frames_averaged", "settle_ms",
]


def _fmt(v: float) -> str:
    return f"{v:.5f}".replace(".", ",")


# -------------------- Config + presets --------------------

@dataclass
class ScanConfig:
    name: str = "scan"
    size_x_mm: float = 5.0
    size_y_mm: float = 5.0
    points_x: int = 50
    points_y: int = 50
    settle_ms: int = SETTLE_DEFAULT
    frames_per_point: int = FRAMES_DEFAULT
    snake: bool = True
    z_enable: bool = False
    z_min_mm: float = 0.0
    z_max_mm: float = 0.0
    z_steps: int = 1

    def total_points(self) -> int:
        z = max(self.z_steps, 1) if self.z_enable else 1
        return self.points_x * self.points_y * z


def load_presets() -> List[dict]:
    if not PRESETS_PATH.exists():
        return _default_presets()
    try:
        data = yaml.safe_load(PRESETS_PATH.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return _default_presets()
    presets = data.get("presets") or []
    return presets if presets else _default_presets()


def save_presets(presets: List[dict]) -> None:
    PRESETS_PATH.write_text(
        yaml.safe_dump({"presets": presets}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _default_presets() -> List[dict]:
    return [
        {"name": "Klein 1×1 mm", "size_x_mm": 1.0, "size_y_mm": 1.0,
         "points_x": 20, "points_y": 20, "settle_ms": 100, "frames_per_point": 3,
         "snake": True, "z_enable": False, "z_min_mm": 0.0, "z_max_mm": 0.0, "z_steps": 1},
        {"name": "Middel 5×5 mm", "size_x_mm": 5.0, "size_y_mm": 5.0,
         "points_x": 50, "points_y": 50, "settle_ms": 200, "frames_per_point": 5,
         "snake": True, "z_enable": False, "z_min_mm": 0.0, "z_max_mm": 0.0, "z_steps": 1},
        {"name": "Groot 10×10 mm", "size_x_mm": 10.0, "size_y_mm": 10.0,
         "points_x": 100, "points_y": 100, "settle_ms": 200, "frames_per_point": 5,
         "snake": True, "z_enable": False, "z_min_mm": 0.0, "z_max_mm": 0.0, "z_steps": 1},
    ]


# -------------------- State machine --------------------

class ScanState(Enum):
    IDLE = "idle"
    MOVING = "moving"
    SETTLING = "settling"
    COLLECTING = "collecting"
    DONE = "done"


def build_path(cfg: ScanConfig) -> List[tuple[int, int, int]]:
    """Genereer (ix, iy, iz)-volgorde over het hele raster — snake-pad."""
    z_count = max(cfg.z_steps, 1) if cfg.z_enable else 1
    path: List[tuple[int, int, int]] = []
    for iz in range(z_count):
        for iy in range(cfg.points_y):
            xs = range(cfg.points_x)
            if cfg.snake and (iy % 2 == 1):
                xs = reversed(xs)
            for ix in xs:
                path.append((ix, iy, iz))
    return path


# -------------------- ScanPanel --------------------

class ScanPanel(QGroupBox):
    """UI + state-machine voor automatische scans."""

    scan_started = Signal(str)        # path naar measurement.csv
    scan_finished = Signal(str, int)  # path, n_points

    def __init__(self, motor_panel, lamp_panel, moku_panel) -> None:
        super().__init__("Automatische scan")
        self.motor_panel = motor_panel
        self.lamp_panel = lamp_panel
        self.moku_panel = moku_panel

        self._state = ScanState.IDLE
        self._path: List[tuple[int, int, int]] = []
        self._idx = 0
        self._origin: tuple[int, int, int] = (0, 0, 0)
        self._step_x = 0
        self._step_y = 0
        self._step_z = 0
        self._frame_buffer: list[np.ndarray] = []
        self._frames_needed = 0
        self._csv_file = None
        self._csv_writer = None
        self._run_dir: Path | None = None
        self._t0 = 0.0
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(POLL_BUSY_MS)
        self._poll_timer.timeout.connect(self._poll_busy)
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.timeout.connect(self._enter_collecting)

        self._build_ui()
        self._refresh_preset_combo()
        self.moku_panel.frame.connect(self._on_moku_frame)

    # ---------- UI bouw ----------

    def _build_ui(self) -> None:
        layout = QGridLayout(self)
        r = 0

        # Run-naam
        layout.addWidget(QLabel("Naam:"), r, 0)
        self.name_input = QLineEdit("scan")
        layout.addWidget(self.name_input, r, 1, 1, 3)
        r += 1

        # Preset
        layout.addWidget(QLabel("Preset:"), r, 0)
        self.preset_combo = QComboBox()
        self.preset_combo.activated.connect(self._on_preset_select)
        layout.addWidget(self.preset_combo, r, 1, 1, 2)
        self.save_preset_btn = QPushButton("Opslaan als preset…")
        self.save_preset_btn.clicked.connect(self._save_current_preset)
        layout.addWidget(self.save_preset_btn, r, 3)
        r += 1

        # Sample-grootte
        layout.addWidget(QLabel("Grootte X (mm):"), r, 0)
        self.size_x = QDoubleSpinBox(); self.size_x.setRange(0.001, 100.0)
        self.size_x.setDecimals(3); self.size_x.setValue(5.0)
        layout.addWidget(self.size_x, r, 1)
        layout.addWidget(QLabel("Grootte Y (mm):"), r, 2)
        self.size_y = QDoubleSpinBox(); self.size_y.setRange(0.001, 100.0)
        self.size_y.setDecimals(3); self.size_y.setValue(5.0)
        layout.addWidget(self.size_y, r, 3)
        r += 1

        # Resolutie
        layout.addWidget(QLabel("Punten X:"), r, 0)
        self.pts_x = QSpinBox(); self.pts_x.setRange(2, 1000); self.pts_x.setValue(50)
        layout.addWidget(self.pts_x, r, 1)
        layout.addWidget(QLabel("Punten Y:"), r, 2)
        self.pts_y = QSpinBox(); self.pts_y.setRange(2, 1000); self.pts_y.setValue(50)
        layout.addWidget(self.pts_y, r, 3)
        r += 1

        # Settle + frames
        layout.addWidget(QLabel("Settle (ms):"), r, 0)
        self.settle = QSpinBox(); self.settle.setRange(0, 5000)
        self.settle.setSingleStep(50); self.settle.setValue(SETTLE_DEFAULT)
        layout.addWidget(self.settle, r, 1)
        layout.addWidget(QLabel("Frames/punt:"), r, 2)
        self.frames = QSpinBox(); self.frames.setRange(1, 50)
        self.frames.setValue(FRAMES_DEFAULT)
        layout.addWidget(self.frames, r, 3)
        r += 1

        # Snake-toggle
        self.snake_cb = QCheckBox("Snake-pad (efficiënter dan raster)")
        self.snake_cb.setChecked(True)
        layout.addWidget(self.snake_cb, r, 0, 1, 4)
        r += 1

        # Z-stack
        self.z_enable_cb = QCheckBox("Z-stack (M3 sweept door focus)")
        self.z_enable_cb.toggled.connect(self._on_z_toggled)
        layout.addWidget(self.z_enable_cb, r, 0, 1, 4)
        r += 1

        layout.addWidget(QLabel("Z-min (mm):"), r, 0)
        self.z_min = QDoubleSpinBox(); self.z_min.setRange(-100.0, 100.0)
        self.z_min.setDecimals(3); self.z_min.setValue(0.0)
        layout.addWidget(self.z_min, r, 1)
        layout.addWidget(QLabel("Z-max (mm):"), r, 2)
        self.z_max = QDoubleSpinBox(); self.z_max.setRange(-100.0, 100.0)
        self.z_max.setDecimals(3); self.z_max.setValue(0.0)
        layout.addWidget(self.z_max, r, 3)
        r += 1

        layout.addWidget(QLabel("Z-stappen:"), r, 0)
        self.z_steps = QSpinBox(); self.z_steps.setRange(1, 200); self.z_steps.setValue(1)
        layout.addWidget(self.z_steps, r, 1)

        self.estimate_lbl = QLabel("—")
        self.estimate_lbl.setStyleSheet("color: #555;")
        layout.addWidget(self.estimate_lbl, r, 2, 1, 2)
        r += 1

        # Live-update van schatting
        for w in (self.size_x, self.size_y, self.pts_x, self.pts_y,
                  self.settle, self.frames, self.z_steps):
            w.valueChanged.connect(self._update_estimate)
        self.z_enable_cb.toggled.connect(self._update_estimate)

        # Start/Cancel
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("▶ Start scan")
        self.start_btn.setObjectName("PrimaryButton")
        self.start_btn.clicked.connect(self._start_scan)
        btn_row.addWidget(self.start_btn)

        self.cancel_btn = QPushButton("■ Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_scan)
        btn_row.addWidget(self.cancel_btn)
        layout.addLayout(btn_row, r, 0, 1, 4)
        r += 1

        # Progress
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress, r, 0, 1, 4)
        r += 1

        self.status = QLabel("Stand-by.")
        self.status.setStyleSheet("color: gray;")
        layout.addWidget(self.status, r, 0, 1, 4)
        r += 1

        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 1)
        layout.setRowStretch(r, 1)

        # Initial state
        self._on_z_toggled(False)
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
        self.size_x.setValue(p.get("size_x_mm", 5.0))
        self.size_y.setValue(p.get("size_y_mm", 5.0))
        self.pts_x.setValue(int(p.get("points_x", 50)))
        self.pts_y.setValue(int(p.get("points_y", 50)))
        self.settle.setValue(int(p.get("settle_ms", SETTLE_DEFAULT)))
        self.frames.setValue(int(p.get("frames_per_point", FRAMES_DEFAULT)))
        self.snake_cb.setChecked(bool(p.get("snake", True)))
        self.z_enable_cb.setChecked(bool(p.get("z_enable", False)))
        self.z_min.setValue(p.get("z_min_mm", 0.0))
        self.z_max.setValue(p.get("z_max_mm", 0.0))
        self.z_steps.setValue(int(p.get("z_steps", 1)))

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

    # ---------- Config-helpers ----------

    def _read_config(self, name: str | None = None) -> ScanConfig:
        return ScanConfig(
            name=name or self.name_input.text() or "scan",
            size_x_mm=self.size_x.value(),
            size_y_mm=self.size_y.value(),
            points_x=self.pts_x.value(),
            points_y=self.pts_y.value(),
            settle_ms=self.settle.value(),
            frames_per_point=self.frames.value(),
            snake=self.snake_cb.isChecked(),
            z_enable=self.z_enable_cb.isChecked(),
            z_min_mm=self.z_min.value(),
            z_max_mm=self.z_max.value(),
            z_steps=self.z_steps.value(),
        )

    def _on_z_toggled(self, on: bool) -> None:
        for w in (self.z_min, self.z_max, self.z_steps):
            w.setEnabled(on)

    def _update_estimate(self) -> None:
        cfg = self._read_config()
        n = cfg.total_points()
        # Heuristiek: tijd-per-punt ≈ settle + frames/10 (Moku 10fps) + 0.3s motor-beweging
        per_pt = cfg.settle_ms / 1000.0 + cfg.frames_per_point * 0.1 + 0.3
        total_s = n * per_pt
        mm = int(total_s // 60)
        ss = int(total_s - mm * 60)
        self.estimate_lbl.setText(f"{n} punten · ~{mm}m {ss}s")

    # ---------- Pre-flight checks ----------

    def _preflight(self, cfg: ScanConfig) -> str | None:
        """Geef foutmelding terug, of None als alles ok is."""
        if self._state != ScanState.IDLE:
            return "Scan is al actief."
        if not (self.motor_panel.serial and self.motor_panel.serial.is_open):
            return "Motoren niet verbonden — verbind eerst MotorPanel."
        for i in range(2 if not cfg.z_enable else 3):
            if self.motor_panel.mm_per_step(i) <= 0:
                return (f"Motor {i+1} heeft mm/stap = 0 — eik eerst "
                        "in MotorPanel of vul mm/stap-veld in.")
        if self.moku_panel.thread is None or not self.moku_panel.thread.isRunning():
            return "Moku niet verbonden — verbind eerst MokuPanel."
        if cfg.z_enable and cfg.z_steps < 2:
            return "Z-stack aan, maar Z-stappen < 2."
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
        mmps_z = self.motor_panel.mm_per_step(2) if cfg.z_enable else 0.0

        steps_x_total = round(cfg.size_x_mm / mmps_x)
        steps_y_total = round(cfg.size_y_mm / mmps_y)
        self._step_x = steps_x_total // (cfg.points_x - 1)
        self._step_y = steps_y_total // (cfg.points_y - 1)
        if cfg.z_enable and cfg.z_steps > 1 and mmps_z > 0:
            steps_z_total = round((cfg.z_max_mm - cfg.z_min_mm) / mmps_z)
            self._step_z = steps_z_total // (cfg.z_steps - 1)
        else:
            self._step_z = 0

        cur = self.motor_panel.targets
        # Origin = linksonder van het raster = huidige positie - halve grootte
        ox = cur[0] - steps_x_total // 2
        oy = cur[1] - steps_y_total // 2
        if cfg.z_enable and mmps_z > 0:
            oz = cur[2] + round(cfg.z_min_mm / mmps_z)
        else:
            oz = cur[2]
        self._origin = (ox, oy, oz)

        # CSV openen
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_name = (cfg.name or "scan").strip().replace(" ", "_")
        self._run_dir = DATA_ROOT / f"scan_{ts}_{safe_name}"
        self._run_dir.mkdir(parents=True, exist_ok=True)
        csv_path = self._run_dir / "measurement.csv"
        self._csv_file = open(csv_path, "w", newline="", encoding="utf-8")
        self._csv_writer = csv.writer(self._csv_file, delimiter=";")
        self._csv_writer.writerow(CSV_HEADER)

        # Metadata
        meta = self._run_dir / "metadata.txt"
        mp = self.moku_panel
        meta.write_text(
            "# Bep-Project automatische scan\n"
            f"start: {datetime.now().isoformat(timespec='seconds')}\n"
            f"name: {cfg.name}\n"
            f"size_x_mm: {cfg.size_x_mm}\n"
            f"size_y_mm: {cfg.size_y_mm}\n"
            f"points_x: {cfg.points_x}\n"
            f"points_y: {cfg.points_y}\n"
            f"step_x_steps: {self._step_x}\n"
            f"step_y_steps: {self._step_y}\n"
            f"settle_ms: {cfg.settle_ms}\n"
            f"frames_per_point: {cfg.frames_per_point}\n"
            f"snake: {cfg.snake}\n"
            f"z_enable: {cfg.z_enable}\n"
            f"z_min_mm: {cfg.z_min_mm}\n"
            f"z_max_mm: {cfg.z_max_mm}\n"
            f"z_steps: {cfg.z_steps}\n"
            f"origin_steps: {self._origin}\n"
            f"motor1_mm_per_step: {mmps_x:.6f}\n"
            f"motor2_mm_per_step: {mmps_y:.6f}\n"
            f"motor3_mm_per_step: {mmps_z:.6f}\n"
            f"moku_address: {mp.address_input.text()}\n"
            f"moku_channel: {mp.channel_combo.currentText()}\n"
            f"moku_range: {mp.range_combo.currentText()}\n"
            f"moku_coupling: {mp.coupling_combo.currentText()}\n",
            encoding="utf-8",
        )

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
            f"Scan gestart → {csv_path.name}  ({len(self._path)} punten)"
        )
        self.status.setStyleSheet("color: #1e8449; font-weight: bold;")
        self.scan_started.emit(str(csv_path))

        self._next_point()

    def _cancel_scan(self) -> None:
        if self._state == ScanState.IDLE:
            return
        self._poll_timer.stop()
        self._settle_timer.stop()
        self._frame_buffer.clear()
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
        ix, iy, iz = self._path[self._idx]
        ox, oy, oz = self._origin
        target_x = ox + ix * self._step_x
        target_y = oy + iy * self._step_y
        target_z = oz + iz * self._step_z

        # Update verwachte targets in motor_panel (zodat recording etc. consistent zijn)
        self.motor_panel.targets[0] = target_x
        self.motor_panel.targets[1] = target_y
        self.motor_panel.targets[2] = target_z
        for i in range(3):
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
        self._update_progress_label(ix, iy, iz)

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
        self._frame_buffer.clear()
        self._frames_needed = self._cfg.frames_per_point
        self._state = ScanState.COLLECTING
        # Wachten op _on_moku_frame; geen timer nodig — zelf-triggerend.

    def _on_moku_frame(self, t, values) -> None:
        if self._state != ScanState.COLLECTING:
            return
        try:
            arr = np.asarray(values, dtype=float)
            if arr.size == 0:
                return
            self._frame_buffer.append(arr)
            if len(self._frame_buffer) >= self._frames_needed:
                self._write_point_row()
                self._idx += 1
                self.progress.setValue(self._idx)
                self._next_point()
        except Exception as e:
            self.status.setText(f"Frame-fout: {e}")
            self._cancel_scan()

    def _write_point_row(self) -> None:
        if self._csv_writer is None:
            return
        ix, iy, iz = self._path[self._idx]
        # Aggregeer alle frames tot 1 sample-set
        all_samples = np.concatenate(self._frame_buffer)
        v_min = float(np.min(all_samples))
        v_max = float(np.max(all_samples))
        steps = list(self.motor_panel.targets)
        mms = [steps[i] * self.motor_panel.mm_per_step(i) for i in range(3)]
        row = [
            datetime.now().isoformat(timespec="milliseconds"),
            self._idx,
            ix, iy, iz,
            steps[0], steps[1], steps[2],
            _fmt(mms[0]), _fmt(mms[1]), _fmt(mms[2]),
            self.lamp_panel.slider.value(),
            _fmt(float(np.mean(all_samples))),
            _fmt(v_min),
            _fmt(v_max),
            _fmt(float(np.std(all_samples))),
            _fmt(v_max - v_min),
            len(self._frame_buffer),
            self._cfg.settle_ms,
        ]
        self._csv_writer.writerow(row)
        if self._csv_file is not None:
            self._csv_file.flush()

    def _finish(self, canceled: bool) -> None:
        self._poll_timer.stop()
        self._settle_timer.stop()
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
        path_str = str(self._run_dir / "measurement.csv") if self._run_dir else ""
        n = self._idx
        self._csv_file = None
        self._csv_writer = None
        self._frame_buffer.clear()
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

    def _update_progress_label(self, ix: int, iy: int, iz: int) -> None:
        total = len(self._path)
        if self._cfg.z_enable:
            self.status.setText(
                f"Punt {self._idx + 1}/{total}  (ix={ix}, iy={iy}, iz={iz})"
            )
        else:
            self.status.setText(
                f"Punt {self._idx + 1}/{total}  (ix={ix}, iy={iy})"
            )

    def _set_inputs_enabled(self, enabled: bool) -> None:
        for w in (
            self.name_input, self.preset_combo, self.save_preset_btn,
            self.size_x, self.size_y, self.pts_x, self.pts_y,
            self.settle, self.frames, self.snake_cb,
            self.z_enable_cb, self.z_min, self.z_max, self.z_steps,
        ):
            w.setEnabled(enabled)
        if enabled:
            self._on_z_toggled(self.z_enable_cb.isChecked())

    def cancel_if_running(self) -> None:
        if self._state != ScanState.IDLE:
            self._cancel_scan()
