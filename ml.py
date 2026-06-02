# SPDX-License-Identifier: MIT

"""Fit van het confocale sensor-model op metingen.xlsx, met een q op dezelfde
(fysieke) schaal als de theorie, zodat I0/2 op de STIJGENDE (linker) flank op
dz1 = 0 valt, net als de theorie-curve.

Workflow (wat dit script doet):

  1. Regressie (gradient descent) op het FORWARD model A6 uit confocal.py.
     Levert een vorm-fit. I0 wordt gelijk gezet aan de hoogste meetwaarde.
  2. q is NIET door de data alleen bepaald. De curve hangt af van
         r_det = S * (dz1 - dz0) - r0*q/f2
     dus alleen van de helling S = 2*r0*c1/(f1**2*f2) en de piekpositie. Elk
     (q, r0)-paar met dezelfde S geeft exact dezelfde curve (degeneratie). De
     theorie breekt die met compute_q (confocal.py): q*r0 = f2*r_d/sqrt(ln2),
     de eis I_m(0) = I0/2. Combineer "zelfde vorm S" + die eis en je krijgt een
     uniek (q_cal, r0_cal) op dezelfde manifold (en schaal) als de theorie:
         r0_cal = (S*f1**2*f2/2 - K*(f1+f2-L)) / f2**2,  K = f2*r_d/sqrt(ln2)
         q_cal  = K / r0_cal
     De curve heeft dan dezelfde vorm als de fit, maar I_m(0) = I0/2 (stijgende
     flank op dz1 = 0) en q op de theorie-schaal.
  3. De theoretische curve wordt overlayd. Zijn I0 wordt gelijk gezet aan de
     I0 van de regressie; zijn positie (dz0_theory = 0) volgt volledig uit
     compute_q, los van de rode lijn. Beide linker flanken gaan door (0, I0/2).

  * input  (x):  dz1   = verplaatsing (kolom A, mm)
  * output (y):  I_m   = gemeten intensiteit (kolom B, volts)
  * geleerd:     vorm S (via q, r0) -> herparametriseerd naar (q_cal, r0_cal)
  * vast:        f1, f2, L, r_d ; I0 = max(meting)
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import sympy as sp


# --- Vaste, instelbare parameters (mm) ---
f1 = 40.0
f2 = 150.0
L = 66.0
r_d = 0.5          # diaphragm radius

# --- Theoretische parameters (confocal.py), voor de overlay-vergelijking ---
q_theory = 32.75    # mm
r0_theory = 2.75    # mm


# --- Symbolisch FORWARD model A6: I_m(dz1) (zie confocal.py regels 36-39) ---
# dz1 komt alleen voor als (dz1 - dz0): dz0 verschuift de hele curve rigide.
_dz1, _q, _r0, _f1, _f2, _L, _rd, _I0, _dz0 = sp.symbols(
    "dz1 q r0 f1 f2 L rd I0 dz0", real=True
)
_d = _dz1 - _dz0
_rdet = _r0 / (_f1**2 * _f2) * (
    2 * _d * (_q * (_f1 + _f2 - _L) + _f2**2) - _q * _f1**2
)
_Im = _I0 - _I0 * sp.exp(-_rd**2 / _rdet**2)

_args = (_dz1, _q, _r0, _f1, _f2, _L, _rd, _I0, _dz0)
Im_func = sp.lambdify(_args, _Im, "numpy")
dIm_dq = sp.lambdify(_args, sp.diff(_Im, _q), "numpy")
dIm_dr0 = sp.lambdify(_args, sp.diff(_Im, _r0), "numpy")


def slope_S(q, r0):
    """Helling van r_det t.o.v. dz1: S = 2*r0*c1/(f1**2*f2). Bepaalt de vorm."""
    return 2.0 * r0 * (q * (f1 + f2 - L) + f2**2) / (f1**2 * f2)


# --- Data inlezen (geen header: kolom 0 = dz1, kolom 1 = I_m) ---
data = pd.read_excel("metingen.xlsx", header=None)
dz1 = np.array(data[0].tolist())        # input x (mm)
Im_meas = np.array(data[1].tolist())    # output y (volts)

# --- I0 = hoogste meetwaarde (de piek/asymptoot van I_m) ---
I0 = Im_meas.max()
focus_pos = dz1[Im_meas.argmax()]       # dz1 waar de intensiteitspiek ligt

# --- Recenter: datapiek op dz1 = 0 zodat de fit op de modelpiek (base ~ 0) valt ---
dz1 = dz1 - focus_pos
dz0 = 0.0


# --- Te leren parameters initialiseren ---
q = 0.30           # orde van compute_q() uit confocal.py
r0 = 2.75          # mag niet 0 zijn (zit in noemer van r_det)

# --- Hyperparameters ---
learning_rate = 1e-3
epochs = 4000
n = len(dz1)

# === STAP 1: Regressie (gradient descent) -> vorm-fit ===
for epoch in range(epochs):
    y_pred = Im_func(dz1, q, r0, f1, f2, L, r_d, I0, dz0)
    error = y_pred - Im_meas

    dq = (2 / n) * np.dot(error, dIm_dq(dz1, q, r0, f1, f2, L, r_d, I0, dz0))
    dr0 = (2 / n) * np.dot(error, dIm_dr0(dz1, q, r0, f1, f2, L, r_d, I0, dz0))

    q -= learning_rate * dq
    r0 -= learning_rate * dr0

    if epoch % 500 == 0:
        loss = (error**2).mean()
        print(f"Epoch {epoch}, Loss: {loss:.4f}, q: {q:.4f}, r0: {r0:.4f}")

q_reg = q
S = slope_S(q_reg, r0)                 # het enige vorm-getal dat de data vastlegt

print(f"\n[Regressie] q_reg: {q_reg:.4f}, r0: {r0:.4f}  (vorm S = {S:.5f})")
print(f"[Regressie] I0 (max meting): {I0:.4f}")

# === STAP 2: Herparametriseren naar de theorie-manifold (compute_q) ===
# Zelfde vorm S, maar q*r0 = K = f2*r_d/sqrt(ln2) zodat I_m(0) = I0/2 en q op
# dezelfde schaal als de theorie komt.
K = f2 * r_d / np.sqrt(np.log(2.0))
r0_cal = (S * f1**2 * f2 / 2.0 - K * (f1 + f2 - L)) / f2**2
q_cal = K / r0_cal
peak_cal = K / (S * f2)                 # dz1-positie van de piek bij dz0 = 0

# Data uitlijnen op de gekalibreerde piek (zelfde vorm, dus blijft op de curve).
dz1 = dz1 + peak_cal

# Metrics op de gekalibreerde curve (datapiek valt op r_det = 0 -> deling door
# nul met exp(-inf) = 0, dus I_m = I0; onschuldig, afvangen).
with np.errstate(divide="ignore", invalid="ignore"):
    y_pred = Im_func(dz1, q_cal, r0_cal, f1, f2, L, r_d, I0, dz0)
error = y_pred - Im_meas
R_squared = 1 - np.sum(error**2) / np.sum((Im_meas - np.mean(Im_meas)) ** 2)
RMSE = np.sqrt(np.mean(error**2))

print(f"\n[Kalibratie] q_cal: {q_cal:.4f}, r0_cal: {r0_cal:.4f}  (zelfde vorm S = {slope_S(q_cal, r0_cal):.5f})")
print(f"[Kalibratie] schaal-check vs theorie: q_cal={q_cal:.2f}  q_theory={q_theory}")
print(f"[Kalibratie] R^2: {R_squared:.4f}, RMSE: {RMSE:.4f}")
print(f"[Kalibratie] check I_m(0) = {Im_func(0.0, q_cal, r0_cal, f1, f2, L, r_d, I0, dz0):.4f}"
      f"  (I0/2 = {I0 / 2:.4f})")

# === STAP 3: Theorie-overlay, positie volledig door de theorie bepaald ===
# compute_q koos q_theory zo dat I_m(0) = I0/2; dz0_theory = 0 legt de theorie
# op zijn eigen nulpunt, los van rood. I0_theory = regressie-I0 (schaling).
I0_theory = I0
dz0_theory = 0.0
print(f"\n[Theorie] dz0_theory = {dz0_theory:.4f} (zelf bepaald door compute_q)")
print(f"[Theorie] check I_m(0) = "
      f"{Im_func(0.0, q_theory, r0_theory, f1, f2, L, r_d, I0_theory, dz0_theory):.4f}"
      f"  (I0/2 = {I0 / 2:.4f})")

# --- Plot: data + gekalibreerde curve + theoretische curve ---
# r_det = 0 op de piek geeft een onschuldige deling door nul (exp(-inf) -> 0);
# afvangen zodat de console schoon blijft.
x = np.linspace(dz1.min() - 1.0, dz1.max() + 1.0, 600)
with np.errstate(divide="ignore", invalid="ignore"):
    y_red = Im_func(x, q_cal, r0_cal, f1, f2, L, r_d, I0, dz0)
    y_green = Im_func(x, q_theory, r0_theory, f1, f2, L, r_d, I0_theory, dz0_theory)

plt.scatter(dz1, Im_meas, label="Data", zorder=3)
plt.plot(
    x, y_red,
    color="red",
    lw=2,
    label=f"Regressie (q={q_cal:.2f}, r0={r0_cal:.3f})",
)
plt.plot(
    x, y_green,
    color="green",
    ls="--",
    lw=2,
    label=f"Theorie (q={q_theory}, r0={r0_theory})",
)
plt.axhline(I0 / 2, color="gray", ls=":", lw=1)   # I0/2 referentie
plt.axvline(0.0, color="gray", ls=":", lw=1)      # dz1 = 0 (I0/2 op stijgende flank)
plt.xlabel("dz1 (mm)")
plt.ylabel("I_m (V)")
plt.legend()
plt.title("Confocaal model: regressie vs theorie (I0/2 op stijgende flank bij dz1 = 0)")
plt.grid(True)
plt.show()
