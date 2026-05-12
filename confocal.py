"""Confocal sensor — only formula A6 and what we derive from it.

Equation A6:
    I_m = I0 - I0 * exp(-r_diaphragm**2 / r_det**2)

with r_det (equation A5) rewritten on the common denominator f1**2 * f2:
    r_det = r0/(f1**2*f2) * (2*dz1*(q*(f1+f2-L) + f2**2) - q*f1**2)

Four functions:
  * compute_q   — solve A6 for q with dz1 = 0 and I_m = I0/2
  * compute_Im  — evaluate A6
  * compute_dz1 — invert A6 for dz1 given I_m (returns both branches)
  * compute_Sm  — S_m = d(I_m)/d(dz1), derived symbolically
"""

import numpy as np
import sympy as sp
import matplotlib.pyplot as plt


# --- Default parameters (mm) ---
f1 = 25.0
f2 = 150.0
r0 = 2.75           # beam radius at lens 1 (r1 in the paper)
r_d = 0.5          # diaphragm radius (r_diaphragm)
L = 66.0
I0 = 1.0


# --- Symbolic model of A6 ---
_dz1, _q, _f1, _f2, _L, _r0, _rd, _I0 = sp.symbols(
    "dz1 q f1 f2 L r0 rd I0", real=True
)
_rdet_sym = _r0 / (_f1**2 * _f2) * (
    2 * _dz1 * (_q * (_f1 + _f2 - _L) + _f2**2) - _q * _f1**2
)
_Im_sym = _I0 - _I0 * sp.exp(-_rd**2 / _rdet_sym**2)
_Sm_sym = sp.diff(_Im_sym, _dz1)

_Im_func = sp.lambdify(
    (_dz1, _q, _f1, _f2, _L, _r0, _rd, _I0), _Im_sym, "numpy"
)
_Sm_func = sp.lambdify(
    (_dz1, _q, _f1, _f2, _L, _r0, _rd, _I0), _Sm_sym, "numpy"
)


def compute_q(f1=f1, f2=f2, L=L, r0=r0, r_d=r_d, I0=I0):
    """Solve A6 for q at dz1 = 0, I_m = I0/2.

    At dz1 = 0:  r_det = -q*r0/f2, so r_det**2 = q**2 * r0**2 / f2**2.
    I_m = I0/2  =>  exp(-r_d**2 / r_det**2) = 1/2
                =>  r_det**2 = r_d**2 / ln 2
                =>  q = f2 * r_d / (r0 * sqrt(ln 2)).
    """
    return f2 * r_d / (r0 * np.sqrt(np.log(2.0)))


def compute_Im(dz1, q, f1=f1, f2=f2, L=L, r0=r0, r_d=r_d, I0=I0):
    """Equation A6: I_m as a function of dz1."""
    return _Im_func(dz1, q, f1, f2, L, r0, r_d, I0)


def compute_dz1(Im, q, f1=f1, f2=f2, L=L, r0=r0, r_d=r_d, I0=I0):
    """Invert A6 for dz1 given I_m.

    From A6:  r_det**2 = r_d**2 / ln(I0 / (I0 - I_m)).
    r_det is linear in dz1, so there are two branches (±|r_det|).
    Returns (dz1_minus, dz1_plus).
    """
    Im_arr = np.asarray(Im, dtype=float)
    if np.any(Im_arr <= 0.0) or np.any(Im_arr >= I0):
        raise ValueError("I_m must satisfy 0 < I_m < I0.")
    rdet_abs = r_d / np.sqrt(np.log(I0 / (I0 - Im_arr)))
    A = 2.0 * (q * (f1 + f2 - L) + f2**2)
    base = q * f1**2 / A
    offset = rdet_abs * f1**2 * f2 / (r0 * A)
    return base - offset, base + offset


def compute_Sm(dz1, q, f1=f1, f2=f2, L=L, r0=r0, r_d=r_d, I0=I0):
    """S_m = d(I_m)/d(dz1), obtained by symbolic differentiation of A6."""
    return _Sm_func(dz1, q, f1, f2, L, r0, r_d, I0)


if __name__ == "__main__":
    q_val = compute_q()
    print(f"q (dz1=0, I_m=0.5*I0): {q_val:.6f} mm")

    dz1 = np.linspace(-0.05, 0.05, 1001)   # ±50 µm in mm
    Im = compute_Im(dz1, q_val)
    Sm = compute_Sm(dz1, q_val)

    fig, ax1 = plt.subplots(figsize=(9, 5))
    l1, = ax1.plot(dz1 * 1e3, Im, "C0", label=r"$I_m$ (A6)")
    ax1.set_xlabel(r"$\delta z_1$ ($\mu$m)")
    ax1.set_ylabel(r"$I_m$", color="C0")
    ax1.tick_params(axis="y", labelcolor="C0")
    ax1.grid(True)

    ax2 = ax1.twinx()
    l2, = ax2.plot(dz1 * 1e3, Sm, "C3", label=r"$S_m = dI_m/d\delta z_1$")
    ax2.set_ylabel(r"$S_m$ (1/mm)", color="C3")
    ax2.tick_params(axis="y", labelcolor="C3")

    ax1.legend(handles=[l1, l2], loc="best")
    plt.title("Equation A6 and its derivative")
    plt.tight_layout()
    plt.show()
