# SPDX-License-Identifier: MIT

"""Confocaal sensor-model (A6): fit van q en r0 op meetpunten.

Kern: `fit_confocal(dz1, Im, f1, ...)` fit q en r0 (gradient descent) op
gemeten (dz1, I_m)-punten en geeft een FitResult terug. Géén plot, géén
bestand-IO — zo is de fit herbruikbaar vanuit de UI (calibration_graph.py)
en vanuit het __main__-blok onderaan.

  * input  : dz1 = verplaatsing (mm), I_m = gemeten intensiteit (V)
  * geleerd : q, r0
  * vast    : f1, f2, L, r_d ; I0 = max(meting)

Het A6-model en de symbolische gradients staan op module-niveau (één keer
gelambdify'd), zodat herhaald fitten goedkoop is.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import sympy as sp


# --- Vaste default-parameters (mm), spiegelt confocal.py ---
F2_DEFAULT = 150.0
L_DEFAULT = 66.0
RD_DEFAULT = 0.5

# --- Theoretische parameters (confocal.py), voor de overlay-vergelijking ---
q_theory = 32.75    # mm
r0_theory = 2.75    # mm


# --- Symbolisch FORWARD model A6: I_m(dz1) (zie confocal.py regels 36-39) ---
_dz1, _q, _r0, _f1, _f2, _L, _rd, _I0 = sp.symbols(
    "dz1 q r0 f1 f2 L rd I0", real=True
)
_rdet = _r0 / (_f1**2 * _f2) * (
    2 * _dz1 * (_q * (_f1 + _f2 - _L) + _f2**2) - _q * _f1**2
)
_Im = _I0 - _I0 * sp.exp(-_rd**2 / _rdet**2)

_args = (_dz1, _q, _r0, _f1, _f2, _L, _rd, _I0)
Im_func = sp.lambdify(_args, _Im, "numpy")
dIm_dq = sp.lambdify(_args, sp.diff(_Im, _q), "numpy")
dIm_dr0 = sp.lambdify(_args, sp.diff(_Im, _r0), "numpy")


@dataclass
class FitResult:
    """Resultaat van fit_confocal — geleerde parameters + fit-kwaliteit."""
    q: float
    r0: float
    I0: float
    R2: float
    RMSE: float
    f1: float
    f2: float
    L: float
    r_d: float


@dataclass
class LinearizationResult:
    """Resultaat van linearize_midpoint — rechte a*x + b rond I0/2.

    a = helling (V/mm), b = intercept (V). lo/hi begrenzen de spanningsband
    waarbinnen de meetpunten zijn meegenomen; n = aantal gebruikte punten;
    x_lo/x_hi = dz1-bereik van die punten (handig om de lijn te tekenen).
    """
    a: float
    b: float
    I0: float
    lo: float
    hi: float
    n: int
    R2: float
    x_lo: float
    x_hi: float


def fit_confocal(
    dz1, Im, f1,
    f2: float = F2_DEFAULT, L: float = L_DEFAULT, r_d: float = RD_DEFAULT,
    q0: float = q_theory, r0_0: float = 1.0,
    epochs: int = 20000, lr_q: float = 1.0, lr_r0: float = 1e-3,
) -> FitResult:
    """Fit q en r0 op (dz1, Im)-punten via gradient descent. I0 = max(Im).

    q heeft een veel kleinere gradient dan r0 (zit diep in de noemer van
    r_det), dus q krijgt een eigen, grotere learning rate (lr_q), anders kruipt
    hij. r0 mag niet 0 zijn (staat in de noemer van r_det).
    """
    dz1 = np.asarray(dz1, dtype=np.float64)
    Im = np.asarray(Im, dtype=np.float64)
    n = dz1.size
    if n < 2:
        raise ValueError("At least 2 data points needed for a fit.")

    I0 = float(Im.max())
    q = float(q0)
    r0 = float(r0_0)

    for _ in range(epochs):
        with np.errstate(divide="ignore", invalid="ignore"):
            y_pred = Im_func(dz1, q, r0, f1, f2, L, r_d, I0)
            grad_q = dIm_dq(dz1, q, r0, f1, f2, L, r_d, I0)
            grad_r0 = dIm_dr0(dz1, q, r0, f1, f2, L, r_d, I0)
        error = y_pred - Im
        q -= lr_q * (2 / n) * np.dot(error, grad_q)
        r0 -= lr_r0 * (2 / n) * np.dot(error, grad_r0)

    with np.errstate(divide="ignore", invalid="ignore"):
        y_pred = Im_func(dz1, q, r0, f1, f2, L, r_d, I0)
    error = y_pred - Im
    ss_tot = float(np.sum((Im - np.mean(Im)) ** 2))
    R2 = float(1 - np.sum(error**2) / ss_tot) if ss_tot > 0 else float("nan")
    RMSE = float(np.sqrt(np.mean(error**2)))

    return FitResult(
        q=float(q), r0=float(r0), I0=I0, R2=R2, RMSE=RMSE,
        f1=float(f1), f2=float(f2), L=float(L), r_d=float(r_d),
    )


def linearize_midpoint(
    dz1, Im, lo_frac: float = 0.2, hi_frac: float = 0.4, side: str = "left",
) -> LinearizationResult:
    """Lineariseer (a*x + b) het steile midden van de confocale curve rond I0/2.

    Selecteert enkel de meetpunten waarvan de spanning binnen de band
    [I0/2 - lo_frac*I0, I0/2 + hi_frac*I0] valt (I0 = max van de meting) en fit
    daarop een rechte met kleinste-kwadraten (np.polyfit). Punten buiten de band
    tellen niet mee. Geeft a (V/mm), b (V) en de bandgrenzen terug.

    De confocale curve heeft twee flanken; dezelfde spanning komt links en rechts
    van de piek voor. `side` kiest welke flank wordt gefit ("left" = links van de
    top, "right" = rechts, "both" = beide). De top is het punt met max spanning.
    """
    dz1 = np.asarray(dz1, dtype=np.float64)
    Im = np.asarray(Im, dtype=np.float64)

    I0 = float(Im.max())
    lo = I0 / 2 - lo_frac * I0
    hi = I0 / 2 + hi_frac * I0
    mask = (Im >= lo) & (Im <= hi)

    # Beperk tot één flank: de top ligt bij dz1 van het maximum.
    dz1_peak = float(dz1[int(np.argmax(Im))])
    if side == "left":
        mask &= dz1 <= dz1_peak
    elif side == "right":
        mask &= dz1 >= dz1_peak
    elif side != "both":
        raise ValueError(f"Unknown side: {side!r} (expected left/right/both).")

    if int(mask.sum()) < 2:
        raise ValueError(
            "Too few points within the band for linearization "
            f"(found {int(mask.sum())}, at least 2 needed)."
        )

    x_in, y_in = dz1[mask], Im[mask]
    a, b = np.polyfit(x_in, y_in, 1)

    y_pred = a * x_in + b
    ss_res = float(np.sum((y_in - y_pred) ** 2))
    ss_tot = float(np.sum((y_in - y_in.mean()) ** 2))
    R2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else float("nan")

    return LinearizationResult(
        a=float(a), b=float(b), I0=I0, lo=lo, hi=hi,
        n=int(mask.sum()), R2=R2,
        x_lo=float(x_in.min()), x_hi=float(x_in.max()),
    )


if __name__ == "__main__":
    # Stand-alone demo op één meetbestand (zelfde gedrag als voorheen).
    import pandas as pd
    import matplotlib.pyplot as plt

    F1 = 60.0
    data = pd.read_excel("metingen 60 mm.xlsx", header=None)
    dz1 = np.array(data[0].tolist())        # input x (mm), ruwe as
    Im_meas = np.array(data[1].tolist())    # output y (volts)

    res = fit_confocal(dz1, Im_meas, f1=F1)
    print(f"[Fit] q (geleerd): {res.q:.4f}")
    print(f"[Fit] r0 (geleerd): {res.r0:.4f}")
    print(f"[Fit] I0 (max meting): {res.I0:.4f}")
    print(f"[Fit] R^2: {res.R2:.4f}, RMSE: {res.RMSE:.4f}")

    lin = linearize_midpoint(dz1, Im_meas)
    print(f"[Lin] a: {lin.a:.4f} V/mm, b: {lin.b:.4f} V "
          f"(n={lin.n}, R^2={lin.R2:.4f})")

    x = np.linspace(dz1.min() - 1.0, dz1.max() + 1.0, 600)
    with np.errstate(divide="ignore", invalid="ignore"):
        y_red = Im_func(x, res.q, res.r0, F1, res.f2, res.L, res.r_d, res.I0)
        y_green = Im_func(x, q_theory, r0_theory, F1, res.f2, res.L, res.r_d, res.I0)

    plt.scatter(dz1, Im_meas, label="Data", zorder=3)
    plt.plot(x, y_red, color="red", lw=2,
             label=f"Fit (q={res.q:.2f}, r0={res.r0:.3f})")
    plt.plot(x, y_green, color="green", ls="--", lw=2,
             label=f"Theorie (q={q_theory}, r0={r0_theory})")
    plt.axhspan(lin.lo, lin.hi, color="orange", alpha=0.08)   # linearisatieband
    xs = np.linspace(lin.x_lo, lin.x_hi, 100)
    plt.plot(xs, lin.a * xs + lin.b, color="purple", lw=2,
             label=f"Linearisatie (a={lin.a:.3f}, b={lin.b:.3f})")
    plt.axhline(res.I0 / 2, color="gray", ls=":", lw=1)   # I0/2 referentie
    plt.xlabel("dz1 (mm)")
    plt.ylabel("I_m (V)")
    plt.legend()
    plt.title("Confocaal model: fit (q en r0 geleerd) vs theorie")
    plt.grid(True)
    plt.show()
