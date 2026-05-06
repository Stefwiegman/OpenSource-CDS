"""Live recorder voor Bep-Project: per Moku-frame een CSV-rij wegschrijven met
motor-positie, lamp-helderheid en spannings-samenvatting. Voor post-hoc
3D-analyse via viewer.py.

CSV-formaat volgt gridsearch.py: ';' als separator en ',' als decimaal,
direct te openen in Excel met NL-locale.
"""
from __future__ import annotations

import csv
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QGroupBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
)


CSV_HEADER = [
    "t_iso", "t_elapsed_s",
    "motor1", "motor2", "motor3",
    "motor1_mm", "motor2_mm", "motor3_mm",
    "lamp",
    "V_mean", "V_min", "V_max", "V_std", "V_pp", "n_samples",
]
DATA_ROOT = Path("data")
STATUS_REFRESH_MS = 500


def _fmt(v: float) -> str:
    """NL-locale: punt -> komma, 5 decimalen."""
    return f"{v:.5f}".replace(".", ",")


class RecordingPanel(QGroupBox):
    def __init__(self, moku_panel, motor_panel, lamp_panel) -> None:
        super().__init__("Opname")
        self.moku_panel = moku_panel
        self.motor_panel = motor_panel
        self.lamp_panel = lamp_panel

        self._file = None
        self._writer = None
        self._t_start = 0.0
        self._n_rows = 0
        self._run_dir: Path | None = None

        layout = QGridLayout(self)

        layout.addWidget(QLabel("Run-naam:"), 0, 0)
        self.name_input = QLineEdit("scan")
        layout.addWidget(self.name_input, 0, 1, 1, 2)

        self.record_btn = QPushButton("● Record")
        self.record_btn.setCheckable(True)
        self.record_btn.setObjectName("DangerButton")
        self.record_btn.toggled.connect(self._toggle_record)
        layout.addWidget(self.record_btn, 1, 0, 1, 2)

        self.open_btn = QPushButton("Open folder")
        self.open_btn.clicked.connect(self._open_folder)
        self.open_btn.setEnabled(False)
        layout.addWidget(self.open_btn, 1, 2)

        self.status = QLabel("Niet aan het opnemen.")
        self.status.setStyleSheet("color: gray;")
        layout.addWidget(self.status, 2, 0, 1, 3)

        # ---- Recente runs ----
        runs_lbl = QLabel("Recente runs")
        runs_lbl.setProperty("role", "caption")
        layout.addWidget(runs_lbl, 3, 0, 1, 3)

        self.runs_list = QListWidget()
        self.runs_list.setToolTip("Dubbel-klik om de map te openen")
        self.runs_list.itemDoubleClicked.connect(self._open_run_folder)
        layout.addWidget(self.runs_list, 4, 0, 1, 3)

        layout.setColumnStretch(1, 1)
        layout.setRowStretch(4, 1)

        self._tick = QTimer(self)
        self._tick.setInterval(STATUS_REFRESH_MS)
        self._tick.timeout.connect(self._refresh_status)

        # Luister naar elk Moku-frame
        self.moku_panel.frame.connect(self._on_frame)

        # Eerste populatie van de runs-lijst
        self._refresh_runs()

    # ---- record-toggle --------------------------------------------

    def _toggle_record(self, on: bool) -> None:
        if on:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self) -> None:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        name = (self.name_input.text() or "scan").strip().replace(" ", "_")
        self._run_dir = DATA_ROOT / f"{ts}_{name}"
        self._run_dir.mkdir(parents=True, exist_ok=True)

        csv_path = self._run_dir / "measurement.csv"
        self._file = open(csv_path, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file, delimiter=";")
        self._writer.writerow(CSV_HEADER)
        self._file.flush()

        meta = self._run_dir / "metadata.txt"
        meta.write_text(self._build_metadata(start=True), encoding="utf-8")

        self._t_start = time.monotonic()
        self._n_rows = 0
        self.record_btn.setText("■ Stop")
        self.open_btn.setEnabled(True)
        self._tick.start()
        self.status.setText(f"Opname loopt -> {csv_path}")
        self.status.setStyleSheet("color: #c0392b; font-weight: bold;")

    def _stop_recording(self) -> None:
        self._tick.stop()
        if self._file is not None:
            try:
                self._file.flush()
                self._file.close()
            except Exception:
                pass
            if self._run_dir is not None:
                meta = self._run_dir / "metadata.txt"
                try:
                    with meta.open("a", encoding="utf-8") as f:
                        f.write(self._build_metadata(start=False))
                except Exception:
                    pass
        self._file = None
        self._writer = None
        self.record_btn.setText("● Record")
        self.status.setText(f"Opname gestopt — {self._n_rows} rijen.")
        self.status.setStyleSheet("color: gray;")
        self._refresh_runs()

    # ---- per-frame schrijven --------------------------------------

    def _on_frame(self, t, values) -> None:
        if self._writer is None:
            return
        try:
            arr = np.asarray(values, dtype=float)
            if arr.size == 0:
                return
            v_min = float(np.min(arr))
            v_max = float(np.max(arr))
            steps = [self.motor_panel.targets[i] for i in range(3)]
            mms = [steps[i] * self.motor_panel.mm_per_step(i) for i in range(3)]
            row = [
                datetime.now().isoformat(timespec="milliseconds"),
                _fmt(time.monotonic() - self._t_start),
                steps[0], steps[1], steps[2],
                _fmt(mms[0]), _fmt(mms[1]), _fmt(mms[2]),
                self.lamp_panel.slider.value(),
                _fmt(float(np.mean(arr))),
                _fmt(v_min),
                _fmt(v_max),
                _fmt(float(np.std(arr))),
                _fmt(v_max - v_min),
                arr.size,
            ]
            self._writer.writerow(row)
            self._n_rows += 1
        except Exception as e:
            self.status.setText(f"Schrijf-fout: {e}")
            self.status.setStyleSheet("color: red;")

    # ---- status / housekeeping ------------------------------------

    def _refresh_status(self) -> None:
        if self._writer is None:
            return
        elapsed = time.monotonic() - self._t_start
        self.status.setText(
            f"Opname loopt — {self._n_rows} rijen, {elapsed:.1f}s"
        )
        if self._file is not None:
            try:
                self._file.flush()
            except Exception:
                pass

    def _open_folder(self) -> None:
        if self._run_dir is None or not self._run_dir.exists():
            return
        self._open_path(self._run_dir)

    # ---- recente runs ---------------------------------------------

    def _refresh_runs(self) -> None:
        """Vul de lijst met de 30 meest-recente run-folders uit data/."""
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
        """Parse 'YYYY-MM-DD_HH-MM-SS_naam' of 'scan_<...>' tot 'naam — datum tijd'."""
        name = path.name
        body = name[5:] if name.startswith("scan_") else name
        parts = body.split("_", 2)
        if len(parts) >= 3:
            date_part, time_part, run_name = parts
            time_readable = time_part.replace("-", ":")
            prefix = "scan: " if name.startswith("scan_") else ""
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

    # ---- tab-zichtbaarheid hook -----------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_runs()

    def _build_metadata(self, start: bool) -> str:
        if start:
            mp = self.moku_panel
            mt = self.motor_panel
            return (
                "# Bep-Project measurement\n"
                f"start: {datetime.now().isoformat(timespec='seconds')}\n"
                f"run_name: {self.name_input.text()}\n"
                f"moku_address: {mp.address_input.text()}\n"
                f"moku_channel: {mp.channel_combo.currentText()}\n"
                f"moku_range: {mp.range_combo.currentText()}\n"
                f"moku_coupling: {mp.coupling_combo.currentText()}\n"
                f"motor1_mm_per_step: {mt.mm_per_step(0):.6f}\n"
                f"motor2_mm_per_step: {mt.mm_per_step(1):.6f}\n"
                f"motor3_mm_per_step: {mt.mm_per_step(2):.6f}\n"
                f"motor1_start_step: {mt.targets[0]}\n"
                f"motor2_start_step: {mt.targets[1]}\n"
                f"motor3_start_step: {mt.targets[2]}\n"
            )
        return (
            f"end: {datetime.now().isoformat(timespec='seconds')}\n"
            f"row_count: {self._n_rows}\n"
        )

    def close_recording(self) -> None:
        if self._file is not None:
            self._stop_recording()
