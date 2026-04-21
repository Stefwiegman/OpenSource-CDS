"""Demo: forward and inverse confocal displacement model.

Sweeps displacement over a range, plots the intensity response, and checks
round-trip consistency (dz1 -> I_m -> dz1).

Run:  python demo.py
"""

import numpy as np
import matplotlib.pyplot as plt

from confocal import (
    r_det,
    intensity,
    invert_intensity,
    dz2_from_dz1,
    half_width,
    peak_position,
)


# --- Parameters (all lengths in mm, intensity normalized) ---
# Echte opstelling: f1=25 mm, f2=50 mm, confocaal, r0=8 mm, detector-Ø=0.4 mm.
f1 = 25.0           # focal length lens 1 (sample side)
f2 = 50.0           # focal length lens 2 (detector side)
L = f1 + f2         # confocal setup: L = f1 + f2
r0 = 8.0            # beam radius at lens 1 entrance (0.8 cm)
q = 2.0             # object-side aperture parameter (paper default)
r_diaphragm = 0.2   # detector-oppervlak als aperture (Ø 0.4 mm -> r=0.2 mm)
I0 = 1.0            # source intensity (genormaliseerd; slikt BS-verlies etc.)

# --- Peak position and half-width (derived) ---
dz1_center = peak_position(f1, f2, L, q)
half_width_dz1 = half_width(f1, f2, L, r0, q, r_diaphragm)

print("--- System characterization ---")
print(f"Peak position (dz1_center)     = {dz1_center:.6f} mm")
print(f"Half-max width (+/-)           = {half_width_dz1:.6f} mm")
print(f"-> System is sensitive on the ~{half_width_dz1:.2f} mm scale.")
print("   (Smaller pinhole or larger f2/f1 ratio -> finer sensitivity.)\n")

# --- Forward sweep ---
sweep_range = 4 * half_width_dz1
dz1_values = np.linspace(
    dz1_center - sweep_range,
    dz1_center + sweep_range,
    500,
)
I_m_values = intensity(dz1_values, f1, f2, L, r0, q, r_diaphragm, I0)

# --- Plot ---
fig, ax = plt.subplots(figsize=(8, 5))
ax.plot(dz1_values, I_m_values, color="C0")
ax.axvline(
    dz1_center,
    color="C3",
    linestyle="--",
    label=f"peak at dz1 = {dz1_center:.3f} mm",
)
ax.axhline(0.5 * I0, color="gray", linestyle=":", alpha=0.5, label="half max")
ax.set_xlabel("dz1 [mm]")
ax.set_ylabel("I_m (normalized)")
ax.set_title("Confocal intensity response vs. object displacement")
ax.grid(True, alpha=0.3)
ax.legend()
fig.tight_layout()
fig.savefig("intensity_curve.png", dpi=150)
print("Saved plot: intensity_curve.png")

# --- Round-trip test: dz1 -> I_m -> dz1 ---
print("\n--- Round-trip test ---")
dz1_test = dz1_center + 1.5 * half_width_dz1
I_m_test = intensity(dz1_test, f1, f2, L, r0, q, r_diaphragm, I0)
dz1_recovered = invert_intensity(I_m_test, f1, f2, L, r0, q, r_diaphragm, I0)
print(f"Original dz1   = {dz1_test:.9f} mm")
print(f"Forward I_m    = {I_m_test:.9f}")
print(f"Inverse dz1(+) = {dz1_recovered[0]:.9f} mm")
print(f"Inverse dz1(-) = {dz1_recovered[1]:.9f} mm")
err = min(abs(s - dz1_test) for s in dz1_recovered)
print(f"Min error      = {err:.2e} mm  ({'OK' if err < 1e-9 else 'FAIL'})")

# --- Inverse example: given measured intensity, recover dz1 ---
print("\n--- Inverse example ---")
I_m_measured = 0.5
dz1_solutions = invert_intensity(
    I_m_measured, f1, f2, L, r0, q, r_diaphragm, I0
)
print(f"Measured I_m = {I_m_measured}")
print(
    f"Possible dz1 values: {dz1_solutions[0]:.6f} mm  and  "
    f"{dz1_solutions[1]:.6f} mm"
)
print(f"(Symmetric around dz1_center = {dz1_center:.6f} mm)")

# --- Sanity check: A5 simplifies to r_det = r0*(2*dz1 - q)/f2 when L = f1+f2 ---
print("\n--- Sanity check (confocal L = f1 + f2) ---")
dz1_check = 1.234
r_det_full = float(r_det(dz1_check, f1, f2, L, r0, q))
r_det_simplified = r0 * (2 * dz1_check - q) / f2
print(f"r_det (full A5)    = {r_det_full:.12f}")
print(f"r_det (simplified) = {r_det_simplified:.12f}")
print(f"Match: {np.isclose(r_det_full, r_det_simplified)}")

# --- Image-plane conjugate displacement ---
print(f"\ndz2 for dz1 = 1.0 mm: {dz2_from_dz1(1.0, f1, f2):.6f} mm")

plt.show()
