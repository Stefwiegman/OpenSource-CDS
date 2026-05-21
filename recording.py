"""Manual burst-recording voor Bep-Project.

Eén klik op 'Burst' → één Datalogger-burst (fs × T samples) bij de huidige
motor-positie. Output:

    data/manual_<timestamp>_<naam>/
        burst.csv         # ruwe meting: t_s, voltage_V — NL-locale
        position.csv      # afgeleid: t_s, dz1_mm (alleen met I0 gezet) via A6
        metadata.txt      # Moku-config, I0, motor-positie, statistics

Werkt als snelle handmatige test van de hele pipeline (Moku-frontend →
Datalogger → V→dz1 conversie) — dezelfde acquisitie als ScanPanel doet per
punt, maar nu één klik = één punt. Als dit werkt, werkt de auto-scan ook.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
)


DATA_ROOT = Path("data")
FS_DEFAULT_KHZ = 100
T_DEFAULT_MS = 500


class RecordingPanel(QGroupBox):
    def __init__(self, moku_panel, motor_panel, lamp_panel) -> None:
        super().__init__("Manual burst")
        self.moku_panel = moku_panel
        self.motor_panel = motor_panel
        self.lamp_panel = lamp_panel
        self._run_dir: Path | None = None

        layout = QGridLayout(self)

        # ---- Run-naam ----
        layout.addWidget(QLabel("Naam:"), 0, 0)
        self.name_input = QLineEdit("manual")
        layout.addWidget(self.name_input, 0, 1, 1, 3)

        # ---- Burst parameters ----
        layout.addWidget(QLabel("Sample-rate:"), 1, 0)
        self.fs_khz = QSpinBox()
        self.fs_khz.setRange(1, 1000)
        self.fs_khz.setSingleStep(10)
        self.fs_khz.setValue(FS_DEFAULT_KHZ)
        self.fs_khz.setSuffix(" kSa/s")
        self.fs_khz.setToolTip("Hoger = hogere maximale frequentie (Nyquist = fs/2)")
        layout.addWidget(self.fs_khz, 1, 1)

        layout.addWidget(QLabel("Burst-duur:"), 1, 2)
        self.T_ms = QSpinBox()
        self.T_ms.setRange(10, 10000)
        self.T_ms.setSingleStep(50)
        self.T_ms.setValue(T_DEFAULT_MS)
        self.T_ms.setSuffix(" ms")
        self.T_ms.setToolTip("Langer = fijnere FFT-frequentie-resolutie (1/T)")
        layout.addWidget(self.T_ms, 1, 3)

        # ---- Burst-knop + Open folder ----
        self.record_btn = QPushButton("● Burst")
        self.record_btn.setObjectName("DangerButton")
        self.record_btn.setToolTip(
            "Doe één Datalogger-burst bij de huidige motor-positie.\n"
            "Vereist een I0-baseline (klik eerst 'Set I0').\n"
            "Output: burst.csv (ruwe voltage) + position.csv (dz1 in mm)."
        )
        self.record_btn.clicked.connect(self._take_burst)
        layout.addWidget(self.record_btn, 2, 0, 1, 2)

        self.open_btn = QPushButton("Open folder")
        self.open_btn.clicked.connect(self._open_folder)
        self.open_btn.setEnabled(False)
        layout.addWidget(self.open_btn, 2, 2, 1, 2)

        # ---- Status ----
        self.status = QLabel("Klaar — klik 'Burst' om één meting te doen.")
        self.status.setStyleSheet("color: gray;")
        self.status.setWordWrap(True)
        layout.addWidget(self.status, 3, 0, 1, 4)

        # ---- I0-calibratie ----
        i0_row = QHBoxLayout()
        i0_row.setSpacing(8)
        self.set_i0_btn = QPushButton("Set I0")
        self.set_i0_btn.setToolTip(
            "Snapshot de huidige gemiddelde fotodetector-spanning als I0-baseline.\n"
            "Daarna schrijft elke burst ook een position.csv (dz1 in mm) via formule A6."
        )
        self.set_i0_btn.clicked.connect(self._set_I0)
        i0_row.addWidget(self.set_i0_btn)

        self.clear_i0_btn = QPushButton("Clear")
        self.clear_i0_btn.setToolTip("Wis I0 — alleen burst.csv (voltage), geen position.csv.")
        self.clear_i0_btn.clicked.connect(self._clear_I0)
        i0_row.addWidget(self.clear_i0_btn)

        self.i0_label = QLabel("I0 = niet ingesteld")
        self.i0_label.setStyleSheet("color: gray;")
        i0_row.addWidget(self.i0_label, stretch=1)

        i0_wrap = QFrame()
        i0_wrap.setLayout(i0_row)
        layout.addWidget(i0_wrap, 4, 0, 1, 4)

        # ---- Recente runs ----
        runs_lbl = QLabel("Recente runs")
        runs_lbl.setProperty("role", "caption")
        layout.addWidget(runs_lbl, 5, 0, 1, 4)

        self.runs_list = QListWidget()
        self.runs_list.setToolTip("Dubbel-klik om de map te openen")
        self.runs_list.itemDoubleClicked.connect(self._open_run_folder)
        layout.addWidget(self.runs_list, 6, 0, 1, 4)

        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 1)
        layout.setRowStretch(6, 1)

        self._refresh_runs()

    # ---- I0-calibratie ----

    def _set_I0(self) -> None:
        I0 = self.moku_panel.set_I0_from_current()
        if I0 is None:
            self.status.setText(
                "Geen Moku-data — verbind eerst en wacht op een live frame."
            )
            self.status.setStyleSheet("color: #b8860b;")
            return
        self._refresh_i0_label()
        self.status.setText(f"I0 ingesteld op {I0:.4f} V.")
        self.status.setStyleSheet("color: #1e8449;")

    def _clear_I0(self) -> None:
        self.moku_panel.clear_I0()
        self._refresh_i0_label()
        self.status.setText("I0 gewist — burst geeft voltage terug.")
        self.status.setStyleSheet("color: gray;")

    def _refresh_i0_label(self) -> None:
        I0 = self.moku_panel.I0
        if I0 is None:
            self.i0_label.setText("I0 = niet ingesteld")
            self.i0_label.setStyleSheet("color: gray;")
        else:
            self.i0_label.setText(f"I0 = {I0:.4f} V  (+position.csv → dz1 in mm)")
            self.i0_label.setStyleSheet("color: #1e8449; font-weight: bold;")

    # ---- Burst ----

    def _take_burst(self) -> None:
        if self.moku_panel.thread is None or not self.moku_panel.thread.isRunning():
            self.status.setText("Moku niet verbonden — verbind eerst MokuPanel.")
            self.status.setStyleSheet("color: red;")
            return
        if not self.moku_panel.I0:
            self.status.setText(
                "Stel eerst I0 in (klik 'Set I0') — zonder baseline geen verplaatsing."
            )
            self.status.setStyleSheet("color: red;")
            return

        fs_hz = self.fs_khz.value() * 1000
        T = self.T_ms.value() / 1000.0

        self.record_btn.setEnabled(False)
        self.status.setText("Burst-mode openen (instrument-switch ~3-5s)…")
        self.status.setStyleSheet("color: #b8860b;")
        QApplication.processEvents()

        samples: np.ndarray | None = None
        try:
            self.moku_panel.start_burst_mode()
            self.status.setText(
                f"Burst loopt — {fs_hz/1000:.0f} kSa/s × {self.T_ms.value()} ms…"
            )
            QApplication.processEvents()
            samples = self.moku_panel.acquire_burst(fs_hz, T)
        except Exception as e:
            self.status.setText(f"Burst-fout: {e}")
            self.status.setStyleSheet("color: red;")
        finally:
            try:
                self.moku_panel.end_burst_mode()
            except Exception:
                pass

        if samples is None:
            self.record_btn.setEnabled(True)
            return

        try:
            run_dir = self._save_burst(samples, fs_hz)
        except Exception as e:
            self.record_btn.setEnabled(True)
            self.status.setText(f"Schrijf-fout: {e}")
            self.status.setStyleSheet("color: red;")
            return

        mean = float(np.mean(samples))
        pp = float(np.max(samples) - np.min(samples))
        std = float(np.std(samples))
        self._run_dir = run_dir
        self.open_btn.setEnabled(True)
        pos_note = ("  +position.csv (dz1 mm)" if getattr(self, "_wrote_position", False)
                    else "  (geen I0 → geen position.csv)")
        self.status.setText(
            f"✓ {samples.size} samples → {run_dir.name}{pos_note}\n"
            f"   mean={mean:+.4e} V   pp={pp:.4e} V   std={std:.4e} V"
        )
        self.status.setStyleSheet("color: #1e8449; font-weight: bold;")
        self.record_btn.setEnabled(True)
        self._refresh_runs()

    def _save_burst(self, samples: np.ndarray, fs_hz: int) -> Path:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        name = (self.name_input.text() or "manual").strip().replace(" ", "_")
        run_dir = DATA_ROOT / f"manual_{ts}_{name}"
        run_dir.mkdir(parents=True, exist_ok=True)

        # burst.csv — ALTIJD ruwe voltage (t_s, voltage_V). NL-locale (; , ).
        t = np.arange(samples.size, dtype=np.float64) / fs_hz
        df = pd.DataFrame({"t_s": t, "voltage_V": samples})
        df.to_csv(run_dir / "burst.csv", sep=";", decimal=",",
                  index=False, float_format="%.7e")

        # position.csv — afgeleide verplaatsing dz1 (mm) per row, via formule A6.
        # Alleen mogelijk met een I0-baseline; anders overslaan.
        I0 = self.moku_panel.I0
        wrote_position = False
        if I0:
            from datalogger import voltage_to_dz1
            dz1 = voltage_to_dz1(samples, I0)
            df_pos = pd.DataFrame({"t_s": t, "dz1_mm": dz1})
            df_pos.to_csv(run_dir / "position.csv", sep=";", decimal=",",
                          index=False, float_format="%.7e")
            wrote_position = True
        self._wrote_position = wrote_position

        mp = self.moku_panel
        mt = self.motor_panel
        I0_str = f"{mp.I0:.6f}" if mp.I0 is not None else "not_set"
        position_note = ("position.csv (t_s, dz1_mm via formule A6)"
                         if wrote_position else "geen — I0 niet ingesteld")
        meta = (
            "# Bep-Project manual burst\n"
            "# as-mapping: motor1 = X-as, motor2 = Y-as, motor3 = Z-as (focus)\n"
            f"timestamp: {datetime.now().isoformat(timespec='seconds')}\n"
            f"name: {name}\n"
            f"fs_Hz: {fs_hz}\n"
            f"T_ms: {self.T_ms.value()}\n"
            f"n_samples: {samples.size}\n"
            f"raw_format: burst.csv (t_s, voltage_V), NL-locale (; sep, , decimal)\n"
            f"position_file: {position_note}\n"
            f"I0_V: {I0_str}\n"
            f"moku_address: {mp.address_input.text()}\n"
            f"moku_channel: {mp.channel_combo.currentText()}\n"
            f"moku_range: {mp.range_combo.currentText()}\n"
            f"moku_coupling: {mp.coupling_combo.currentText()}\n"
            f"motor1_steps: {mt.targets[0]}\n"
            f"motor2_steps: {mt.targets[1]}\n"
            f"motor3_steps: {mt.targets[2]}\n"
            f"motor1_mm: {mt.targets[0] * mt.mm_per_step(0):.6f}\n"
            f"motor2_mm: {mt.targets[1] * mt.mm_per_step(1):.6f}\n"
            f"motor3_mm: {mt.targets[2] * mt.mm_per_step(2):.6f}\n"
            f"lamp: {self.lamp_panel.slider.value()}\n"
            "\n"
            "# Statistics\n"
            f"mean: {float(np.mean(samples)):.6e}\n"
            f"std: {float(np.std(samples)):.6e}\n"
            f"min: {float(np.min(samples)):.6e}\n"
            f"max: {float(np.max(samples)):.6e}\n"
            f"peak_to_peak: {float(np.max(samples) - np.min(samples)):.6e}\n"
        )
        (run_dir / "metadata.txt").write_text(meta, encoding="utf-8")
        return run_dir

    # ---- Open / runs-lijst ----

    def _open_folder(self) -> None:
        if self._run_dir is None or not self._run_dir.exists():
            return
        self._open_path(self._run_dir)

    def _refresh_runs(self) -> None:
        self.runs_list.clear()
        if not DATA_ROOT.exists():
            return
        runs = []
        for path in DATA_ROOT.iterdir():
            if not path.is_dir():
                continue
            runs.append((path.stat().st_mtime, path))
        runs.sort(key=lambda x: x[0], reverse=True)
        for _, path in runs[:30]:
            item = QListWidgetItem(self._format_run_label(path))
            item.setData(Qt.UserRole, str(path))
            self.runs_list.addItem(item)

    @staticmethod
    def _format_run_label(path: Path) -> str:
        name = path.name
        prefix = ""
        if name.startswith("scan_"):
            body = name[5:]
            prefix = "scan: "
        elif name.startswith("manual_"):
            body = name[7:]
            prefix = "manual: "
        else:
            body = name
        parts = body.split("_", 2)
        if len(parts) >= 3:
            date_part, time_part, run_name = parts
            time_readable = time_part.replace("-", ":")
            return f"{prefix}{run_name}   —   {date_part}  {time_readable}"
        return name

    def _open_run_folder(self, item: QListWidgetItem) -> None:
        path = Path(item.data(Qt.UserRole))
        if path.exists():
            self._open_path(path)

    @staticmethod
    def _open_path(path: Path) -> None:
        if sys.platform == "win32":
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    # ---- Lifecycle ----

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_runs()

    def close_recording(self) -> None:
        # Bursts zijn synchroon — niets persistents om te sluiten bij afsluiten.
        return None
