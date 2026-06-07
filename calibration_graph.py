# SPDX-License-Identifier: MIT

"""Calibration graph tab for the Bep-Project.

The user uploads an Excel or CSV file with two columns (dz1 in mm, I_m in V).
The confocal A6 model (ml.fit_confocal) fits q and r0 to the points; the tab
shows the data, the fitted curve and the theory curve in an embedded graph, plus
the fit metrics (q, r0, I0, R^2, RMSE).

The fit and the A6 model come entirely from ml.py, this tab only draws.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure

import ml


DATA_ROOT = Path("data")
F1_DEFAULT_MM = 40.0


def _read_raw(path: Path, header) -> pd.DataFrame:
    """Read an Excel or CSV file into a DataFrame with the given header.

    CSV detection: NL-locale CSV (like burst.csv) uses ';' as separator and a
    comma as decimal; standard CSV uses ',' and a dot. We look at the first
    non-empty line: if it contains a ';', it is NL locale.
    """
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(path, header=header)
    if suffix == ".csv":
        first = ""
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip():
                first = line
                break
        sep, dec = (";", ",") if ";" in first else (",", ".")
        return pd.read_csv(path, sep=sep, decimal=dec, header=header)
    raise ValueError(f"Unsupported file type: {suffix or '(no extension)'}")


def _load_xy(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Read (dz1, I_m) from an Excel or CSV file with two columns.

    Tries without a header first; if the first row turns out to be text (a
    header), retries with header=0. Non-numeric rows are filtered out. Returns
    (dz1_mm, Im_V) as float arrays.
    """
    df = _read_raw(path, header=None)
    try:
        float(df.iloc[0, 0])
        float(df.iloc[0, 1])
    except (ValueError, TypeError):
        df = _read_raw(path, header=0)
    x = pd.to_numeric(df.iloc[:, 0], errors="coerce").to_numpy(dtype=float)
    y = pd.to_numeric(df.iloc[:, 1], errors="coerce").to_numpy(dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    return x[mask], y[mask]


class CalibrationGraphPanel(QGroupBox):
    """Upload measurement points, fit the A6 model and show the calibration graph."""

    def __init__(self) -> None:
        super().__init__("Calibration graph")
        self._dz1: np.ndarray | None = None
        self._Im: np.ndarray | None = None
        self._loaded_name = ""
        self._src_path: Path | None = None
        self._last_res: ml.FitResult | None = None
        self._last_lin: ml.LinearizationResult | None = None
        # Artist groups per graph layer (filled in _fit_and_plot), so the toggles
        # can show/hide them live.
        self._artists: dict[str, list] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)

        # ---- control row ----
        controls = QHBoxLayout()
        self.upload_btn = QPushButton("Upload Excel")
        self.upload_btn.clicked.connect(self._upload)
        controls.addWidget(self.upload_btn)

        controls.addWidget(QLabel("f1:"))
        self.f1_input = QDoubleSpinBox()
        self.f1_input.setRange(1.0, 1000.0)
        self.f1_input.setDecimals(1)
        self.f1_input.setSingleStep(1.0)
        self.f1_input.setValue(F1_DEFAULT_MM)
        self.f1_input.setSuffix(" mm")
        controls.addWidget(self.f1_input)

        self.fit_btn = QPushButton("Fit & show")
        self.fit_btn.clicked.connect(self._fit_and_plot)
        self.fit_btn.setEnabled(False)
        controls.addWidget(self.fit_btn)

        self.save_btn = QPushButton("Save")
        self.save_btn.setToolTip(
            "Save the Excel copy, the graph (PNG) and the fit results in data/."
        )
        self.save_btn.clicked.connect(self._save)
        self.save_btn.setEnabled(False)
        controls.addWidget(self.save_btn)
        controls.addStretch(1)
        root.addLayout(controls)

        # ---- toggle row: turn graph layers on/off live ----
        toggles = QHBoxLayout()
        toggles.addWidget(QLabel("Show:"))
        self.layer_toggles: dict[str, QCheckBox] = {}
        for key, label in (
            ("data", "Data"),
            ("fit", "Fit"),
            ("theory", "Theory"),
            ("lin", "Linearization"),
        ):
            cb = QCheckBox(label)
            cb.setChecked(True)
            cb.toggled.connect(self._apply_visibility)
            toggles.addWidget(cb)
            self.layer_toggles[key] = cb
        toggles.addStretch(1)
        root.addLayout(toggles)

        # ---- status ----
        self.status = QLabel(
            "Upload an Excel or CSV with two columns: dz1 (mm), I_m (V)."
        )
        self.status.setStyleSheet("color: gray;")
        root.addWidget(self.status)

        # ---- graph ----
        self.figure = Figure(figsize=(7.2, 4.2))
        self.canvas = FigureCanvas(self.figure)
        self.toolbar = NavigationToolbar(self.canvas, self)
        root.addWidget(self.toolbar)
        root.addWidget(self.canvas, stretch=1)
        self.ax = self.figure.add_subplot(111)
        self._init_axes()

    def _init_axes(self) -> None:
        self.ax.set_xlabel("dz1 (mm)")
        self.ax.set_ylabel("I_m (V)")
        self.ax.grid(True, alpha=0.3)
        self.figure.tight_layout()
        self.canvas.draw_idle()

    # -----------------------------------------------------------
    #  Actions
    # -----------------------------------------------------------

    def _upload(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose measurement file", "", "Measurement data (*.xlsx *.xls *.csv)"
        )
        if not path:
            return
        try:
            x, y = _load_xy(Path(path))
        except Exception as e:  # pragma: no cover - file-error path
            self._error(f"Could not read file: {e}")
            return
        if x.size < 2:
            self._error("Too few data points (at least 2 needed).")
            return
        self._dz1, self._Im, self._loaded_name = x, y, Path(path).name
        self._src_path = Path(path)
        self._last_res = None
        self._last_lin = None
        self.fit_btn.setEnabled(True)
        self.save_btn.setEnabled(False)   # fit first, then save
        self.status.setText(
            f"Loaded: {self._loaded_name} ({x.size} points). Click 'Fit & show'."
        )
        self.status.setStyleSheet("color: green;")

    def _fit_and_plot(self) -> None:
        if self._dz1 is None or self._Im is None:
            return
        self.setCursor(Qt.WaitCursor)
        try:
            res = ml.fit_confocal(self._dz1, self._Im, f1=self.f1_input.value())
            lin = ml.linearize_midpoint(self._dz1, self._Im)
        except Exception as e:
            self.unsetCursor()
            self._error(f"Fit failed: {e}")
            return
        self.unsetCursor()
        self._last_res = res
        self._last_lin = lin
        self.save_btn.setEnabled(True)

        x = np.linspace(self._dz1.min() - 1.0, self._dz1.max() + 1.0, 600)
        with np.errstate(divide="ignore", invalid="ignore"):
            y_fit = ml.Im_func(
                x, res.q, res.r0, res.f1, res.f2, res.L, res.r_d, res.I0
            )
            y_theory = ml.Im_func(
                x, ml.q_theory, ml.r0_theory,
                res.f1, res.f2, res.L, res.r_d, res.I0,
            )

        self.ax.clear()
        sc = self.ax.scatter(self._dz1, self._Im, label="Data", zorder=3,
                             color="#2563eb")
        fit_line, = self.ax.plot(x, y_fit, color="red", lw=2,
                                 label=f"Fit (q={res.q:.2f}, r0={res.r0:.3f})")
        theory_line, = self.ax.plot(
            x, y_theory, color="green", ls="--", lw=2,
            label=f"Theory (q={ml.q_theory}, r0={ml.r0_theory})")
        # Linearization overlay: shaded band + straight a*x + b. The line is drawn
        # up to the band edges (y = lo and y = hi): from y = a*x + b it follows that
        # x = (y - b) / a. When a is near 0 it falls back to the dz1 range.
        band = self.ax.axhspan(lin.lo, lin.hi, color="orange", alpha=0.08,
                               label="Linearization band")
        if abs(lin.a) > 1e-12:
            x_lo, x_hi = (lin.lo - lin.b) / lin.a, (lin.hi - lin.b) / lin.a
        else:
            x_lo, x_hi = lin.x_lo, lin.x_hi
        xs = np.linspace(x_lo, x_hi, 100)
        lin_line, = self.ax.plot(
            xs, lin.a * xs + lin.b, color="purple", lw=2,
            label=f"Linearization (a={lin.a:.3f}, b={lin.b:.3f})")
        half = self.ax.axhline(res.I0 / 2, color="gray", ls=":", lw=1)

        # Group artists per toggle layer; the I0/2 reference hangs on 'lin'.
        self._artists = {
            "data": [sc],
            "fit": [fit_line],
            "theory": [theory_line],
            "lin": [band, lin_line, half],
        }

        self.ax.set_xlabel("dz1 (mm)")
        self.ax.set_ylabel("I_m (V)")
        self.ax.set_title(f"Confocal model — {self._loaded_name}")
        self.ax.grid(True, alpha=0.3)
        self._apply_visibility()   # sets visibility + legend, draws the canvas
        self.figure.tight_layout()
        self.canvas.draw_idle()

        self.status.setText(
            f"f1={res.f1:.1f} mm | q={res.q:.2f} mm | r0={res.r0:.3f} mm | "
            f"I0={res.I0:.3f} V | R²={res.R2:.4f} | RMSE={res.RMSE:.4f} V  ||  "
            f"linear a={lin.a:.4f} V/mm, b={lin.b:.4f} V "
            f"(n={lin.n}, R²={lin.R2:.4f})"
        )
        self.status.setStyleSheet("color: green;")

    def _apply_visibility(self) -> None:
        """Set each graph layer's visibility to its toggle state.

        Called both after a new fit and on every checkbox change so layers go
        on/off live. The legend is rebuilt from only the visible, labelled artists.
        """
        if not self._artists:
            return
        for key, arts in self._artists.items():
            visible = self.layer_toggles[key].isChecked()
            for art in arts:
                art.set_visible(visible)

        handles = [
            art for arts in self._artists.values() for art in arts
            if art.get_visible() and not art.get_label().startswith("_")
        ]
        if handles:
            self.ax.legend(handles=handles)
        elif self.ax.get_legend() is not None:
            self.ax.get_legend().remove()
        self.canvas.draw_idle()

    def _save(self) -> None:
        """Save the Excel copy, graph (PNG) and fit results in data/."""
        if self._last_res is None or self._src_path is None or self._dz1 is None:
            return
        res = self._last_res
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        stem = self._src_path.stem.strip().replace(" ", "_")
        out_dir = DATA_ROOT / f"calibration_{ts}_{stem}"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self._src_path, out_dir / self._src_path.name)
            self.figure.savefig(out_dir / "fit.png", dpi=150)
            text = (
                f"source: {self._src_path.name}\n"
                f"data points: {self._dz1.size}\n"
                f"f1: {res.f1:.1f} mm\n"
                f"f2: {res.f2:.1f} mm\n"
                f"L: {res.L:.1f} mm\n"
                f"r_d: {res.r_d:.3f} mm\n"
                f"q (learned): {res.q:.4f} mm\n"
                f"r0 (learned): {res.r0:.4f} mm\n"
                f"I0 (measurement max): {res.I0:.4f} V\n"
                f"R^2: {res.R2:.4f}\n"
                f"RMSE: {res.RMSE:.4f} V\n"
            )
            lin = self._last_lin
            if lin is not None:
                text += (
                    "\n--- linearization around I0/2 (a*x + b) ---\n"
                    f"linearization a (V/mm): {lin.a:.6f}\n"
                    f"linearization b (V): {lin.b:.6f}\n"
                    f"band lo (V): {lin.lo:.4f}   band hi (V): {lin.hi:.4f}\n"
                    f"points in band: {lin.n}   R^2 (line): {lin.R2:.4f}\n"
                )
            (out_dir / "results.txt").write_text(text, encoding="utf-8")
        except OSError as e:
            self._error(f"Save failed: {e}")
            return
        self.status.setText(f"Saved -> {out_dir}")
        self.status.setStyleSheet("color: green;")

    def get_linearization(self) -> "ml.LinearizationResult | None":
        """Return the most recent linearization (line a*x + b around I0/2), or None.

        Used by the manual tab to convert burst voltage to displacement and to
        check whether the measured voltage stays inside the linear band. Returns
        None until a calibration graph has been fitted in this session.
        """
        return self._last_lin

    def _error(self, msg: str) -> None:
        self.status.setText(msg)
        self.status.setStyleSheet("color: red;")
