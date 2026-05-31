# SPDX-License-Identifier: MIT

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
    QDialog,
    QDoubleSpinBox,
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
    QVBoxLayout,
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


DATA_ROOT = Path("data")
FS_DEFAULT_KHZ = 1000  # 1000 kSa/s = 1 MHz (Moku:Go Datalogger-max) → Nyquist 500 kHz
T_DEFAULT_MS = 10      # 10 ms → FFT-bin 100 Hz
F1_DEFAULT_MM = 25.0   # spiegelt confocal.f1 — brandpuntsafstand lens 1 (mm)


def amplitude_spectrum(signal: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
    """Eenzijdig amplitudespectrum via Hann-window + reële FFT.

    Retourneert (frequenties_Hz, amplitude). De amplitude is de geschatte
    sinus-amplitude per frequentiecomponent (window-gecompenseerd, zelfde eenheid
    als het ingangssignaal). Het DC-gemiddelde wordt eerst verwijderd zodat de
    0 Hz-piek de trillingsamplitudes niet overstemt.
    """
    x = np.asarray(signal, dtype=np.float64)
    n = x.size
    if n < 2:
        return np.zeros(0), np.zeros(0)
    x = x - np.mean(x)
    window = np.hanning(n)
    spectrum = np.fft.rfft(x * window)
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    amp = np.abs(spectrum) * 2.0 / np.sum(window)
    return freqs, amp


class FFTWindow(QDialog):
    """Niet-modaal venster met het amplitudespectrum (dz1) van één burst."""

    def __init__(self, freqs: np.ndarray, amp: np.ndarray, title: str,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"FFT — {title}")
        self.resize(760, 440)

        layout = QVBoxLayout(self)
        fig = Figure(figsize=(7.2, 4.2))
        self.figure = fig
        canvas = FigureCanvas(fig)
        layout.addWidget(canvas)

        ax = fig.add_subplot(111)
        ax.plot(freqs, amp, lw=1.0, color="#2563eb")
        ax.set_xlabel("frequentie (Hz)")
        ax.set_ylabel("amplitude dz1 (µm)")
        ax.grid(True, alpha=0.3)
        if freqs.size:
            ax.set_xlim(0, float(freqs[-1]))

        # Markeer de dominante piek (DC-bin overgeslagen).
        if amp.size > 1:
            k = int(np.argmax(amp[1:])) + 1
            ax.annotate(
                f"{freqs[k]:.1f} Hz\n{amp[k]:.3g} µm",
                xy=(freqs[k], amp[k]),
                xytext=(0.62, 0.82), textcoords="axes fraction",
                arrowprops=dict(arrowstyle="->", color="#ef4444"),
            )

        fig.tight_layout()
        canvas.draw_idle()


class RecordingPanel(QGroupBox):
    def __init__(self, moku_panel, motor_panel, lamp_panel) -> None:
        super().__init__("Manual burst")
        self.moku_panel = moku_panel
        self.motor_panel = motor_panel
        self.lamp_panel = lamp_panel
        self._run_dir: Path | None = None
        self._fft_window: FFTWindow | None = None

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

        # ---- Optica: lens f1 (gaat in formule A6 voor V→dz1) ----
        f1_row = QHBoxLayout()
        f1_row.setSpacing(8)
        f1_row.addWidget(QLabel("Lens f1:"))
        self.f1_mm = QDoubleSpinBox()
        self.f1_mm.setRange(1.0, 1000.0)
        self.f1_mm.setDecimals(2)
        self.f1_mm.setSingleStep(0.5)
        self.f1_mm.setValue(F1_DEFAULT_MM)
        self.f1_mm.setSuffix(" mm")
        self.f1_mm.setToolTip(
            "Brandpuntsafstand van lens 1 (f1) in formule A6.\n"
            "Bepaalt de schaal van de V→verplaatsing (dz1) omrekening."
        )
        f1_row.addWidget(self.f1_mm)
        f1_row.addStretch(1)
        f1_wrap = QFrame()
        f1_wrap.setLayout(f1_row)
        layout.addWidget(f1_wrap, 4, 0, 1, 4)

        # ---- I0-baseline (handmatig invoeren) ----
        i0_row = QHBoxLayout()
        i0_row.setSpacing(8)
        i0_row.addWidget(QLabel("I0:"))
        self.i0_input = QDoubleSpinBox()
        self.i0_input.setRange(0.0, 50.0)
        self.i0_input.setDecimals(4)
        self.i0_input.setSingleStep(0.1)
        self.i0_input.setSuffix(" V")
        self.i0_input.setSpecialValueText("niet ingesteld")
        self.i0_input.setToolTip(
            "Baseline-spanning I0 (volledige reflectie) voor de V→dz1 omrekening.\n"
            "Vul de gemeten waarde zelf in. 0 = niet ingesteld → alleen burst.csv (voltage)."
        )
        if self.moku_panel.I0:
            self.i0_input.setValue(float(self.moku_panel.I0))
        self.i0_input.valueChanged.connect(self._on_i0_changed)
        i0_row.addWidget(self.i0_input)

        self.i0_label = QLabel("")
        self.i0_label.setStyleSheet("color: gray;")
        i0_row.addWidget(self.i0_label, stretch=1)

        i0_wrap = QFrame()
        i0_wrap.setLayout(i0_row)
        layout.addWidget(i0_wrap, 5, 0, 1, 4)
        self._refresh_i0_label()

        # ---- Recente runs ----
        runs_lbl = QLabel("Recente runs")
        runs_lbl.setProperty("role", "caption")
        layout.addWidget(runs_lbl, 6, 0, 1, 4)

        self.runs_list = QListWidget()
        self.runs_list.setToolTip("Dubbel-klik om de map te openen")
        self.runs_list.itemDoubleClicked.connect(self._open_run_folder)
        layout.addWidget(self.runs_list, 7, 0, 1, 4)

        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 1)
        layout.setRowStretch(7, 1)

        self._refresh_runs()

    # ---- I0-baseline ----

    def _on_i0_changed(self, value: float) -> None:
        self.moku_panel.I0 = value if value > 0.0 else None
        self._refresh_i0_label()

    def _refresh_i0_label(self) -> None:
        if self.moku_panel.I0:
            self.i0_label.setText("→ position.csv (dz1 in mm)")
            self.i0_label.setStyleSheet("color: #1e8449; font-weight: bold;")
        else:
            self.i0_label.setText("geen I0 → alleen voltage")
            self.i0_label.setStyleSheet("color: gray;")

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
        self._show_fft(samples, fs_hz, run_dir)

    def _show_fft(self, samples: np.ndarray, fs_hz: int, run_dir: Path) -> None:
        """Bereken het dz1-amplitudespectrum, sla fft.png op en toon de popup."""
        from datalogger import voltage_to_dz1
        dz1_um = voltage_to_dz1(samples, self.moku_panel.I0,
                                f1=self.f1_mm.value()) * 1000.0   # mm → µm
        freqs, amp = amplitude_spectrum(dz1_um, fs_hz)
        if freqs.size == 0:
            return
        if self._fft_window is not None:
            self._fft_window.close()
        self._fft_window = FFTWindow(freqs, amp, run_dir.name, parent=self)
        try:
            self._fft_window.figure.savefig(run_dir / "fft.png", dpi=150)
        except OSError as e:
            self.status.setText(f"{self.status.text()}\n   (fft.png niet opgeslagen: {e})")
        self._fft_window.show()

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
            dz1 = voltage_to_dz1(samples, I0, f1=self.f1_mm.value())
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
            f"lens_f1_mm: {self.f1_mm.value():.4f}\n"
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
