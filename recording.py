# SPDX-License-Identifier: MIT

"""Manual burst recording for the Bep-Project.

One click on 'Burst' -> one Datalogger burst (fs x T samples) at the current
motor position. Output:

    data/manual_<timestamp>_<name>/
        burst.csv         # raw measurement: t_s, voltage_V (NL locale)
        position.csv      # derived: t_s, dz1_mm via the calibration line
        metadata.txt      # Moku config, calibration line, motor position, stats

The voltage -> displacement conversion uses the linearized calibration line
(dz1 = (V - b) / a) fitted in the 'Calibration graph' tab. That line is only
valid inside its voltage band [lo, hi]; if the burst leaves that band a warning
is shown because the displacement would be an extrapolation.

Works as a quick manual test of the whole pipeline (Moku frontend ->
Datalogger -> calibration line), the same acquisition ScanPanel does per point,
but now one click = one point. If this works, the auto-scan works too.
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
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


DATA_ROOT = Path("data")
FS_DEFAULT_KHZ = 1000  # 1000 kSa/s = 1 MHz (Moku:Go Datalogger max) -> Nyquist 500 kHz
T_DEFAULT_MS = 10      # 10 ms -> FFT bin 100 Hz


def amplitude_spectrum(signal: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
    """One-sided amplitude spectrum via Hann window + real FFT.

    Returns (frequencies_Hz, amplitude). The amplitude is the estimated sine
    amplitude per frequency component (window-compensated, same unit as the input
    signal). The DC mean is removed first so the 0 Hz peak does not drown out the
    vibration amplitudes.
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
    """Non-modal window with the amplitude spectrum (dz1) of one burst."""

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
        ax.set_xlabel("frequency (Hz)")
        ax.set_ylabel("amplitude dz1 (µm)")
        ax.grid(True, alpha=0.3)
        if freqs.size:
            ax.set_xlim(0, float(freqs[-1]))

        # Mark the dominant peak (DC bin skipped).
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
    def __init__(self, moku_panel, motor_panel, lamp_panel,
                 calibration_graph_panel=None) -> None:
        super().__init__("Manual burst")
        self.moku_panel = moku_panel
        self.motor_panel = motor_panel
        self.lamp_panel = lamp_panel
        # Source of the linearized calibration line used for V -> dz1 conversion.
        self.calibration_graph_panel = calibration_graph_panel
        self._run_dir: Path | None = None
        self._fft_window: FFTWindow | None = None

        layout = QGridLayout(self)

        # ---- Run name ----
        layout.addWidget(QLabel("Name:"), 0, 0)
        self.name_input = QLineEdit("manual")
        layout.addWidget(self.name_input, 0, 1, 1, 3)

        # ---- Burst parameters ----
        layout.addWidget(QLabel("Sample rate:"), 1, 0)
        self.fs_khz = QSpinBox()
        self.fs_khz.setRange(1, 1000)
        self.fs_khz.setSingleStep(10)
        self.fs_khz.setValue(FS_DEFAULT_KHZ)
        self.fs_khz.setSuffix(" kSa/s")
        self.fs_khz.setToolTip("Higher = higher maximum frequency (Nyquist = fs/2)")
        layout.addWidget(self.fs_khz, 1, 1)

        layout.addWidget(QLabel("Burst duration:"), 1, 2)
        self.T_ms = QSpinBox()
        self.T_ms.setRange(10, 10000)
        self.T_ms.setSingleStep(50)
        self.T_ms.setValue(T_DEFAULT_MS)
        self.T_ms.setSuffix(" ms")
        self.T_ms.setToolTip("Longer = finer FFT frequency resolution (1/T)")
        layout.addWidget(self.T_ms, 1, 3)

        # ---- Burst button + Open folder ----
        self.record_btn = QPushButton("● Burst")
        self.record_btn.setObjectName("DangerButton")
        self.record_btn.setToolTip(
            "Take one Datalogger burst at the current motor position.\n"
            "Requires a fitted calibration line (Calibration graph tab).\n"
            "Output: burst.csv (raw voltage) + position.csv (dz1 via the line)."
        )
        self.record_btn.clicked.connect(self._take_burst)
        layout.addWidget(self.record_btn, 2, 0, 1, 2)

        self.open_btn = QPushButton("Open folder")
        self.open_btn.clicked.connect(self._open_folder)
        self.open_btn.setEnabled(False)
        layout.addWidget(self.open_btn, 2, 2, 1, 2)

        # ---- Status ----
        self.status = QLabel("Ready, click 'Burst' to take one measurement.")
        self.status.setStyleSheet("color: gray;")
        self.status.setWordWrap(True)
        layout.addWidget(self.status, 3, 0, 1, 4)

        # ---- Recent runs ----
        runs_lbl = QLabel("Recent runs")
        runs_lbl.setProperty("role", "caption")
        layout.addWidget(runs_lbl, 4, 0, 1, 4)

        self.runs_list = QListWidget()
        self.runs_list.setToolTip("Double-click to open the folder")
        self.runs_list.itemDoubleClicked.connect(self._open_run_folder)
        layout.addWidget(self.runs_list, 5, 0, 1, 4)

        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 1)
        layout.setRowStretch(5, 1)

        self._refresh_runs()

    # ---- Calibration line ----

    def _get_linearization(self):
        """Return the latest linearization from the calibration graph, or None."""
        if self.calibration_graph_panel is None:
            return None
        return self.calibration_graph_panel.get_linearization()

    @staticmethod
    def _dz1_mm_from_voltage(samples: np.ndarray, lin) -> np.ndarray:
        """Convert voltage (V) to displacement dz1 (mm) via the line dz1 = (V - b) / a."""
        return (np.asarray(samples, dtype=np.float64) - lin.b) / lin.a

    @staticmethod
    def _count_out_of_band(samples: np.ndarray, lin) -> int:
        """Number of samples whose voltage falls outside the linear band [lo, hi]."""
        s = np.asarray(samples, dtype=np.float64)
        return int(np.count_nonzero((s < lin.lo) | (s > lin.hi)))

    # ---- Burst ----

    def _take_burst(self) -> None:
        if self.moku_panel.thread is None or not self.moku_panel.thread.isRunning():
            self.status.setText("Moku not connected, connect MokuPanel first.")
            self.status.setStyleSheet("color: red;")
            return

        lin = self._get_linearization()
        if lin is None:
            self.status.setText(
                "No calibration line yet. Fit one in the 'Calibration graph' tab first."
            )
            self.status.setStyleSheet("color: red;")
            return
        if abs(lin.a) < 1e-12:
            self.status.setText(
                "Calibration line slope is ~0, cannot convert voltage to position."
            )
            self.status.setStyleSheet("color: red;")
            return

        fs_hz = self.fs_khz.value() * 1000
        T = self.T_ms.value() / 1000.0

        self.record_btn.setEnabled(False)
        self.status.setText("Opening burst mode (instrument switch ~3-5s)...")
        self.status.setStyleSheet("color: #b8860b;")
        QApplication.processEvents()

        samples: np.ndarray | None = None
        try:
            self.moku_panel.start_burst_mode()
            self.status.setText(
                f"Burst running, {fs_hz/1000:.0f} kSa/s x {self.T_ms.value()} ms..."
            )
            QApplication.processEvents()
            samples = self.moku_panel.acquire_burst(fs_hz, T)
        except Exception as e:
            self.status.setText(f"Burst error: {e}")
            self.status.setStyleSheet("color: red;")
        finally:
            try:
                self.moku_panel.end_burst_mode()
            except Exception:
                pass

        if samples is None:
            self.record_btn.setEnabled(True)
            return

        # Notify when the measurement leaves the band where the line is valid.
        n_out = self._count_out_of_band(samples, lin)
        self._maybe_warn_out_of_band(samples, lin, n_out)

        try:
            run_dir = self._save_burst(samples, fs_hz, lin, n_out)
        except Exception as e:
            self.record_btn.setEnabled(True)
            self.status.setText(f"Write error: {e}")
            self.status.setStyleSheet("color: red;")
            return

        mean = float(np.mean(samples))
        pp = float(np.max(samples) - np.min(samples))
        std = float(np.std(samples))
        self._run_dir = run_dir
        self.open_btn.setEnabled(True)
        band_note = (f"  ⚠ {n_out} samples outside linear band"
                     if n_out else "  (all samples in linear band)")
        self.status.setText(
            f"✓ {samples.size} samples -> {run_dir.name}{band_note}\n"
            f"   position via line dz1=(V-b)/a (a={lin.a:.4f} V/mm)\n"
            f"   mean={mean:+.4e} V   pp={pp:.4e} V   std={std:.4e} V"
        )
        self.status.setStyleSheet(
            "color: #c0392b; font-weight: bold;" if n_out
            else "color: #1e8449; font-weight: bold;"
        )
        self.record_btn.setEnabled(True)
        self._refresh_runs()
        self._show_fft(samples, fs_hz, run_dir, lin)

    def _maybe_warn_out_of_band(self, samples: np.ndarray, lin, n_out: int) -> None:
        """Pop a warning if the burst voltage left the linear calibration band."""
        if not n_out:
            return
        pct = 100.0 * n_out / samples.size
        v_min, v_max = float(np.min(samples)), float(np.max(samples))
        QMessageBox.warning(
            self, "Outside linear range",
            f"{n_out} of {samples.size} samples ({pct:.1f}%) fell outside the "
            f"linear calibration band.\n\n"
            f"  Linear band:    [{lin.lo:.4f}, {lin.hi:.4f}] V\n"
            f"  Measured range: [{v_min:.4f}, {v_max:.4f}] V\n\n"
            "The displacement from the calibration line is only valid inside the "
            "band; values outside it are extrapolated and may be inaccurate. "
            "Adjust the operating point (focus) so the signal stays within the band."
        )

    def _show_fft(self, samples: np.ndarray, fs_hz: int, run_dir: Path, lin) -> None:
        """Compute the dz1 amplitude spectrum, save fft.png and show the popup."""
        dz1_um = self._dz1_mm_from_voltage(samples, lin) * 1000.0   # mm -> µm
        freqs, amp = amplitude_spectrum(dz1_um, fs_hz)
        if freqs.size == 0:
            return
        if self._fft_window is not None:
            self._fft_window.close()
        self._fft_window = FFTWindow(freqs, amp, run_dir.name, parent=self)
        try:
            self._fft_window.figure.savefig(run_dir / "fft.png", dpi=150)
        except OSError as e:
            self.status.setText(f"{self.status.text()}\n   (fft.png not saved: {e})")
        self._fft_window.show()

    def _save_burst(self, samples: np.ndarray, fs_hz: int, lin, n_out: int) -> Path:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        name = (self.name_input.text() or "manual").strip().replace(" ", "_")
        run_dir = DATA_ROOT / f"manual_{ts}_{name}"
        run_dir.mkdir(parents=True, exist_ok=True)

        # burst.csv, ALWAYS raw voltage (t_s, voltage_V). NL locale (; , ).
        t = np.arange(samples.size, dtype=np.float64) / fs_hz
        df = pd.DataFrame({"t_s": t, "voltage_V": samples})
        df.to_csv(run_dir / "burst.csv", sep=";", decimal=",",
                  index=False, float_format="%.7e")

        # position.csv, derived displacement dz1 (mm) per row via the calibration
        # line dz1 = (V - b) / a.
        dz1 = self._dz1_mm_from_voltage(samples, lin)
        df_pos = pd.DataFrame({"t_s": t, "dz1_mm": dz1})
        df_pos.to_csv(run_dir / "position.csv", sep=";", decimal=",",
                      index=False, float_format="%.7e")

        mp = self.moku_panel
        mt = self.motor_panel
        pct_out = 100.0 * n_out / samples.size if samples.size else 0.0
        meta = (
            "# Bep-Project manual burst\n"
            "# axis mapping: motor1 = X axis, motor2 = Y axis, motor3 = Z axis (focus)\n"
            f"timestamp: {datetime.now().isoformat(timespec='seconds')}\n"
            f"name: {name}\n"
            f"fs_Hz: {fs_hz}\n"
            f"T_ms: {self.T_ms.value()}\n"
            f"n_samples: {samples.size}\n"
            f"raw_format: burst.csv (t_s, voltage_V), NL locale (; sep, , decimal)\n"
            f"position_file: position.csv (t_s, dz1_mm via calibration line)\n"
            f"position_method: linearized calibration line dz1 = (V - b) / a\n"
            f"lin_a_V_per_mm: {lin.a:.8f}\n"
            f"lin_b_V: {lin.b:.8f}\n"
            f"lin_band_lo_V: {lin.lo:.6f}\n"
            f"lin_band_hi_V: {lin.hi:.6f}\n"
            f"lin_R2: {lin.R2:.6f}\n"
            f"samples_outside_band: {n_out} ({pct_out:.1f}%)\n"
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

    # ---- Open / runs list ----

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
        # Bursts are synchronous, nothing persistent to close on shutdown.
        return None
