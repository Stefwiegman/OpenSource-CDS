# SPDX-License-Identifier: MIT

"""Confocaal sensor-model (A6) op metingen.xlsx, zonder enige verschuiving.

  * q en r0 worden beide gefit (gradient descent) op de meetdata; de waarde
    bij q hieronder is de startwaarde voor het leren.
  * Geen recenter, geen piek-uitlijning, geen dz0-translatie: alle curves en de
    data staan op hun eigen dz1-as (dz0 = 0).
  * Zowel de gefitte (rode) curve als de theoretische (groene) curve worden
    geplot.

  * input  (x):  dz1   = verplaatsing (kolom A, mm)
  * output (y):  I_m   = gemeten intensiteit (kolom B, volts)
  * geleerd:     q, r0
  * vast:        f1, f2, L, r_d ; I0 = max(meting)
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import sympy as sp


# --- Vaste, instelbare parameters (mm) ---
f1 = 60.0
f2 = 150.0
L = 66.0
r_d = 0.5          # diaphragm radius

# --- q: startwaarde voor het leren (wordt nu wel geleerd) ---
q = 32.75       # mm

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


# --- Data inlezen (geen header: kolom 0 = dz1, kolom 1 = I_m) ---
data = pd.read_excel("metingen 60 mm.xlsx", header=None)
dz1 = np.array(data[0].tolist())        # input x (mm), ruwe as (geen recenter)
Im_meas = np.array(data[1].tolist())    # output y (volts)

# --- I0 = hoogste meetwaarde (de piek/asymptoot van I_m) ---
I0 = Im_meas.max()


# --- Te leren parameter initialiseren ---
r0 = 1          # mag niet 0 zijn (zit in noemer van r_det)

# --- Hyperparameters ---
# q heeft een veel kleinere gradient dan r0 (zit diep in de noemer van r_det),
# dus q krijgt een eigen, grotere learning rate, anders kruipt hij.
learning_rate = 1e-3        # voor r0
learning_rate_q = 1.0       # voor q
epochs = 20000
n = len(dz1)

# === Regressie (gradient descent) -> q en r0 ===
for epoch in range(epochs):
    with np.errstate(divide="ignore", invalid="ignore"):
        y_pred = Im_func(dz1, q, r0, f1, f2, L, r_d, I0)
        grad_q = dIm_dq(dz1, q, r0, f1, f2, L, r_d, I0)
        grad_r0 = dIm_dr0(dz1, q, r0, f1, f2, L, r_d, I0)
    error = y_pred - Im_meas

    dq = (2 / n) * np.dot(error, grad_q)
    dr0 = (2 / n) * np.dot(error, grad_r0)
    q -= learning_rate_q * dq
    r0 -= learning_rate * dr0

    if epoch % 2000 == 0:
        loss = (error**2).mean()
        print(f"Epoch {epoch}, Loss: {loss:.4f}, q: {q:.4f}, r0: {r0:.4f}")

# --- Eindwaarden + metrics ---
with np.errstate(divide="ignore", invalid="ignore"):
    y_pred = Im_func(dz1, q, r0, f1, f2, L, r_d, I0)
error = y_pred - Im_meas
R_squared = 1 - np.sum(error**2) / np.sum((Im_meas - np.mean(Im_meas)) ** 2)
RMSE = np.sqrt(np.mean(error**2))

print(f"\n[Fit] q (geleerd): {q:.4f}")
print(f"[Fit] r0 (geleerd): {r0:.4f}")
print(f"[Fit] I0 (max meting): {I0:.4f}")
print(f"[Fit] R^2: {R_squared:.4f}, RMSE: {RMSE:.4f}")

# --- Plot: data + gefitte curve + theoretische curve (alles op eigen dz1-as) ---
# r_det = 0 op de piek geeft een onschuldige deling door nul (exp(-inf) -> 0);
# afvangen zodat de console schoon blijft.
x = np.linspace(dz1.min() - 1.0, dz1.max() + 1.0, 600)
with np.errstate(divide="ignore", invalid="ignore"):
    y_red = Im_func(x, q, r0, f1, f2, L, r_d, I0)
    y_green = Im_func(x, q_theory, r0_theory, f1, f2, L, r_d, I0)

plt.scatter(dz1, Im_meas, label="Data", zorder=3)
plt.plot(
    x, y_red,
    color="red",
    lw=2,
    label=f"Fit (q={q:.2f}, r0={r0:.3f})",
)
plt.plot(
    x, y_green,
    color="green",
    ls="--",
    lw=2,
    label=f"Theorie (q={q_theory}, r0={r0_theory})",
)
plt.axhline(I0 / 2, color="gray", ls=":", lw=1)   # I0/2 referentie
plt.xlabel("dz1 (mm)")
plt.ylabel("I_m (V)")
plt.legend()
plt.title("Confocaal model: fit (q en r0 geleerd) vs theorie")
plt.grid(True)
plt.show()
