# SPDX-License-Identifier: MIT

"""Calibration graph tab for the Bep-Project.

The user uploads an Excel or CSV file with two columns (dz1 in mm, I_m in V).
The confocal A6 model (ml.fit_confocal) fits q and r0 to the points; the tab
shows the data, the fitted curve and the theory curve in an embedded graph, plus
the fit metrics (q, r0, I0, R^2, RMSE).

I0 reuse: in the A6 model I0 is purely an amplitude scale factor (the curve
shape depends only on the lens geometry). So one sweep per lens is enough. The
fitted formula is saved per lens (keyed by f1) in confocal_fits.yaml. To measure
the same lens at a different I0, the user only enters the new I0 and the graph
plus linearization rescale linearly, no new sweep needed.

The fit and the A6 model come entirely from ml.py, this tab only draws.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

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
# Per-lens store of fitted confocal formulas, keyed by f1. Lets the user reuse a
# sweep at a different I0 without re-measuring.
CONFOCAL_FITS_PATH = Path("confocal_fits.yaml")


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
        # Base fit at its native I0 (the reference), and the currently shown /
        # rescaled version. get_linearization() returns the latter.
        self._base_res: ml.FitResult | None = None
        self._base_lin: ml.LinearizationResult | None = None
        self._last_res: ml.FitResult | None = None
        self._last_lin: ml.LinearizationResult | None = None
        # Guards the I0 spinbox against feedback loops when we set it in code.
        self._suppress_i0 = False
        # Artist groups per graph layer (filled in _render), so the toggles can
        # show/hide them live.
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
        self.f1_input.setToolTip("Lens focal length, the key under which a fitted formula is saved/loaded.")
        controls.addWidget(self.f1_input)

        self.fit_btn = QPushButton("Fit & show")
        self.fit_btn.clicked.connect(self._fit_and_plot)
        self.fit_btn.setEnabled(False)
        controls.addWidget(self.fit_btn)

        controls.addWidget(QLabel("I0:"))
        self.i0_input = QDoubleSpinBox()
        self.i0_input.setRange(0.0, 50.0)
        self.i0_input.setDecimals(4)
        self.i0_input.setSingleStep(0.1)
        self.i0_input.setSuffix(" V")
        self.i0_input.setSpecialValueText("not set")
        self.i0_input.setToolTip(
            "Reference voltage at full reflection. After one sweep per lens, just\n"
            "enter a new I0 here to rescale the curve and the linearization to a\n"
            "new operating point, without doing another sweep."
        )
        self.i0_input.valueChanged.connect(self._on_i0_changed)
        controls.addWidget(self.i0_input)

        self.load_btn = QPushButton("Load formula")
        self.load_btn.setToolTip(
            "Load the saved formula for the current f1 (no data file needed),\n"
            "then enter an I0 to rescale it."
        )
        self.load_btn.clicked.connect(lambda: self._load_formula(silent=False, set_spin=True))
        controls.addWidget(self.load_btn)

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
            "Upload an Excel or CSV with two columns: dz1 (mm), I_m (V). "
            "Already swept this lens? Set f1, click 'Load formula', enter I0."
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

        # If a formula for the default lens is already saved, load it silently so
        # the manual tab has a linearization right away after a restart.
        self._load_formula(silent=True, set_spin=True)

    def _init_axes(self) -> None:
        self.ax.set_xlabel("dz1 (mm)")
        self.ax.set_ylabel("I_m (V)")
        self.ax.grid(True, alpha=0.3)
        self.figure.tight_layout()
        self.canvas.draw_idle()

    # -----------------------------------------------------------
    #  Upload + fit
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
        self._base_res, self._base_lin = res, lin
        self._last_res, self._last_lin = res, lin
        self.save_btn.setEnabled(True)
        self._set_i0_spin(res.I0)
        self._render(res, lin, self._dz1, self._Im)
        self._persist_formula(res, lin)   # save the formula for this lens
        self._status_for(res, lin, scaled=False)

    # -----------------------------------------------------------
    #  I0 reuse: rescale + persistence
    # -----------------------------------------------------------

    def _set_i0_spin(self, value: float) -> None:
        """Set the I0 spinbox without triggering a rescale."""
        self._suppress_i0 = True
        self.i0_input.setValue(float(value))
        self._suppress_i0 = False

    def _on_i0_changed(self, value: float) -> None:
        if self._suppress_i0 or value <= 0.0:
            return
        # No fit yet? Try to auto-load a saved formula for the current f1, so the
        # user can rescale by only entering an I0.
        if self._base_res is None:
            if not self._load_formula(silent=True, set_spin=False):
                self.status.setText(
                    f"No fit/formula for f1={self.f1_input.value():.1f} mm yet. "
                    "Click 'Load formula' or do a sweep + 'Fit & show' first."
                )
                self.status.setStyleSheet("color: #b8860b;")
                return
        if self._base_res is None or self._base_res.I0 <= 0.0:
            return

        res, lin = self._rescale(self._base_res, self._base_lin, value)
        self._last_res, self._last_lin = res, lin
        ratio = value / self._base_res.I0
        if self._dz1 is not None and self._Im is not None:
            # Data was measured at the base I0; show it scaled so it lies on the
            # rescaled curve.
            self._render(res, lin, self._dz1, self._Im * ratio)
        else:
            self._render(res, lin, None, None,
                         title=f"Confocal model (saved formula, f1={res.f1:.1f} mm)")
        self._status_for(res, lin, scaled=abs(ratio - 1.0) > 1e-9)

    @staticmethod
    def _rescale(res: "ml.FitResult", lin: "ml.LinearizationResult",
                 i0_new: float) -> tuple["ml.FitResult", "ml.LinearizationResult"]:
        """Scale a fit + linearization to a new I0 (everything scales linearly)."""
        ratio = i0_new / res.I0
        res2 = ml.FitResult(
            q=res.q, r0=res.r0, I0=i0_new, R2=res.R2, RMSE=res.RMSE * ratio,
            f1=res.f1, f2=res.f2, L=res.L, r_d=res.r_d,
        )
        lin2 = ml.LinearizationResult(
            a=lin.a * ratio, b=lin.b * ratio, I0=i0_new,
            lo=lin.lo * ratio, hi=lin.hi * ratio,
            n=lin.n, R2=lin.R2, x_lo=lin.x_lo, x_hi=lin.x_hi,
        )
        return res2, lin2

    def _persist_formula(self, res: "ml.FitResult", lin: "ml.LinearizationResult") -> None:
        """Save the fitted formula for this lens (keyed by f1) to confocal_fits.yaml."""
        key = f"{res.f1:.1f}"
        data = self._load_fits_file()
        fits = data.get("fits") or {}
        fits[key] = {
            "q": float(res.q), "r0": float(res.r0),
            "f1": float(res.f1), "f2": float(res.f2),
            "L": float(res.L), "r_d": float(res.r_d),
            "I0": float(res.I0), "R2": float(res.R2), "RMSE": float(res.RMSE),
            "lin": {
                "a": float(lin.a), "b": float(lin.b), "I0": float(lin.I0),
                "lo": float(lin.lo), "hi": float(lin.hi), "n": int(lin.n),
                "R2": float(lin.R2), "x_lo": float(lin.x_lo), "x_hi": float(lin.x_hi),
            },
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        }
        data["fits"] = fits
        self._save_fits_file(data)

    def _load_formula(self, silent: bool, set_spin: bool) -> bool:
        """Load the saved formula for the current f1. Returns True on success."""
        key = f"{self.f1_input.value():.1f}"
        entry = (self._load_fits_file().get("fits") or {}).get(key)
        if not entry:
            if not silent:
                self._error(
                    f"No saved formula for f1={key} mm. Do a sweep + 'Fit & show' "
                    "once for this lens first."
                )
            return False
        try:
            res = ml.FitResult(
                q=entry["q"], r0=entry["r0"], I0=entry["I0"],
                R2=entry.get("R2", float("nan")), RMSE=entry.get("RMSE", 0.0),
                f1=entry["f1"], f2=entry["f2"], L=entry["L"], r_d=entry["r_d"],
            )
            le = entry["lin"]
            lin = ml.LinearizationResult(
                a=le["a"], b=le["b"], I0=le["I0"], lo=le["lo"], hi=le["hi"],
                n=le["n"], R2=le["R2"], x_lo=le["x_lo"], x_hi=le["x_hi"],
            )
        except (KeyError, TypeError):
            if not silent:
                self._error(f"Saved formula for f1={key} mm is incomplete or corrupt.")
            return False

        # A loaded formula has no underlying data file.
        self._dz1 = None
        self._Im = None
        self._src_path = None
        self._loaded_name = f"saved f1={key}"
        self._base_res, self._base_lin = res, lin
        self._last_res, self._last_lin = res, lin
        self.save_btn.setEnabled(False)   # nothing new to export
        if set_spin:
            self._set_i0_spin(res.I0)
            self._render(res, lin, None, None,
                         title=f"Confocal model (saved formula, f1={res.f1:.1f} mm)")
            self.status.setText(
                f"Loaded saved formula for f1={key} mm (reference I0={res.I0:.4f} V). "
                "Enter a new I0 to rescale."
            )
            self.status.setStyleSheet("color: green;")
        return True

    @staticmethod
    def _load_fits_file() -> dict:
        if not CONFOCAL_FITS_PATH.exists():
            return {}
        try:
            return yaml.safe_load(CONFOCAL_FITS_PATH.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            return {}

    @staticmethod
    def _save_fits_file(data: dict) -> None:
        CONFOCAL_FITS_PATH.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    # -----------------------------------------------------------
    #  Drawing
    # -----------------------------------------------------------

    def _render(self, res: "ml.FitResult", lin: "ml.LinearizationResult",
                data_dz1: np.ndarray | None, data_Im: np.ndarray | None,
                title: str | None = None) -> None:
        """Draw the model curve, optional data points and the linearization."""
        self.ax.clear()

        if data_dz1 is not None and data_dz1.size:
            x = np.linspace(data_dz1.min() - 1.0, data_dz1.max() + 1.0, 600)
        else:
            lo_x, hi_x = sorted((lin.x_lo, lin.x_hi))
            pad = max(1.0, hi_x - lo_x)
            x = np.linspace(lo_x - pad, hi_x + pad, 600)

        with np.errstate(divide="ignore", invalid="ignore"):
            y_fit = ml.Im_func(
                x, res.q, res.r0, res.f1, res.f2, res.L, res.r_d, res.I0
            )
            y_theory = ml.Im_func(
                x, ml.q_theory, ml.r0_theory,
                res.f1, res.f2, res.L, res.r_d, res.I0,
            )

        data_arts = []
        if data_dz1 is not None and data_Im is not None and data_dz1.size:
            sc = self.ax.scatter(data_dz1, data_Im, label="Data", zorder=3,
                                 color="#2563eb")
            data_arts = [sc]
        fit_line, = self.ax.plot(x, y_fit, color="red", lw=2,
                                 label=f"Fit (q={res.q:.2f}, r0={res.r0:.3f})")
        theory_line, = self.ax.plot(
            x, y_theory, color="green", ls="--", lw=2,
            label=f"Theory (q={ml.q_theory}, r0={ml.r0_theory})")
        # Linearization overlay: shaded band + straight a*x + b. The line is drawn
        # up to the band edges (y = lo and y = hi): from y = a*x + b it follows
        # that x = (y - b) / a. When a is near 0 it falls back to the dz1 range.
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
            "data": data_arts,
            "fit": [fit_line],
            "theory": [theory_line],
            "lin": [band, lin_line, half],
        }

        self.ax.set_xlabel("dz1 (mm)")
        self.ax.set_ylabel("I_m (V)")
        self.ax.set_title(title or f"Confocal model — {self._loaded_name}")
        self.ax.grid(True, alpha=0.3)
        self._apply_visibility()   # sets visibility + legend, draws the canvas
        self.figure.tight_layout()
        self.canvas.draw_idle()

    def _status_for(self, res: "ml.FitResult", lin: "ml.LinearizationResult",
                    scaled: bool) -> None:
        tag = "rescaled to I0" if scaled else "fit"
        self.status.setText(
            f"[{tag}] f1={res.f1:.1f} mm | q={res.q:.2f} mm | r0={res.r0:.3f} mm | "
            f"I0={res.I0:.3f} V | R²={res.R2:.4f}  ||  linear a={lin.a:.4f} V/mm, "
            f"b={lin.b:.4f} V (band [{lin.lo:.3f}, {lin.hi:.3f}] V, n={lin.n}, "
            f"R²={lin.R2:.4f})"
        )
        self.status.setStyleSheet("color: green;")

    def _apply_visibility(self) -> None:
        """Set each graph layer's visibility to its toggle state.

        Called both after a new render and on every checkbox change so layers go
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

    # -----------------------------------------------------------
    #  Export + public API
    # -----------------------------------------------------------

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
        """Return the current linearization (line a*x + b around I0/2), or None.

        Reflects any I0 rescaling, so the manual tab automatically uses the line
        scaled to the operating point selected here. Returns None until a graph
        has been fitted or a saved formula has been loaded.
        """
        return self._last_lin

    def _error(self, msg: str) -> None:
        self.status.setText(msg)
        self.status.setStyleSheet("color: red;")
