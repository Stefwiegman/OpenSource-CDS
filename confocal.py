"""Confocal displacement sensor — paper equations only.

One function per equation in the derivation images (1-4, A3, A5, A6, B2, B4),
plus z2_offset and two versions each of sensitivity and linear_range so the
B2-analytical values can be compared against the slope/empirical values.
The __main__ block prints the comparison and plots equation 12 (= A6).

Convention: whenever `q` appears in a formula, it is the z2 offset from
equation B4.
"""

import numpy as np
import matplotlib.pyplot as plt


# --- Variables (edit these) ---
f1 = 20.0     # focal length of lens 1 (mm)
f2 = 150.0    # focal length of lens 2 (mm)
r1 = 4.0      # beam radius at lens 1 (mm)
r_d = 0.4     # diaphragm / pinhole radius (mm)
L = 170.0     # optical path length between lenses (mm)
I0 = 1.0      # source intensity


# --- Equations from the paper ---

def eq1_theta(r1, f1):
    """Equation 1: theta = arctan(r1 / f1)."""
    return np.arctan(r1 / f1)


def eq2_r1_prime(r1, f1, dz1):
    """Equation 2: r1' = (f1 + 2*dz1) * tan(theta) = (1 + 2*dz1/f1) * r1."""
    return (f1 + 2.0 * dz1) * np.tan(eq1_theta(r1, f1))


def eq3_tan_alpha(r1_prime, r1, f1):
    """Equation 3: tan(alpha) = (r1' - r1) / f1 = 2 * dz1 * r1 / f1**2."""
    return (r1_prime - r1) / f1


def eq4_r2(r1_prime, d, tan_alpha):
    """Equation 4: r2 = r1' - d * tan(alpha)."""
    return r1_prime - d * tan_alpha


def eqA3_dz2(dz1, f1, f2, L):
    """Equation A3: dz2 = -2*dz1*f2**2 / (2*L*dz1 - 2*dz1*f1 - 2*dz1*f2 + f1**2)."""
    denom = 2.0 * L * dz1 - 2.0 * dz1 * f1 - 2.0 * dz1 * f2 + f1**2
    return -2.0 * dz1 * f2**2 / denom


def eqA5_r_det(dz1, f1, f2, L, r0, q):
    """Equation A5: detector-plane spot radius."""
    num = r0 * (
        -2.0 * L * dz1 * q
        + 2.0 * dz1 * f1 * q
        + 2.0 * dz1 * f2**2
        + 2.0 * dz1 * f2 * q
        - f1**2 * q
    )
    return num / (f1**2 * f2)


def eqA6_Im(dz1, f1, f2, L, r0, q, r_diaphragm, I0):
    """Equation A6 (= equation 12): I_m = I0 - I0*exp(-r_diaphragm**2 / r_det**2)."""
    rd = np.asarray(eqA5_r_det(dz1, f1, f2, L, r0, q), dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        Im = I0 - I0 * np.exp(-(r_diaphragm**2) / rd**2)
    # rd == 0 => exp(-inf) = 0 => Im = I0, which numpy handles correctly.
    if rd.ndim == 0:
        return float(Im)
    return Im


def eqB2_Sm(dz1, I0, f1, f2, r_d, r2):
    """Equation B2: S_m(dz1) = -I0 * u**3 * exp(-u**2) with u = f1**2*r_d / (2*r2*f2*dz1)."""
    dz1_arr = np.asarray(dz1, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        u = (f1**2 * r_d) / (2.0 * r2 * f2 * dz1_arr)
        Sm = -I0 * u**3 * np.exp(-(u**2))
    Sm = np.where(dz1_arr == 0, 0.0, Sm)
    if dz1_arr.ndim == 0:
        return float(Sm)
    return Sm


def eqB4_dz2_offset(f2, r_d, r2):
    """Equation B4: dz2_offset = (f2 * r_d / r2) / sqrt(ln 2)."""
    return (f2 * r_d / r2) / (np.log(2.0))


# --- Derived scalar values ---

def z2_offset(f2, r_d, r2):
    """z2 offset — equation B4."""
    return eqB4_dz2_offset(f2, r_d, r2)


def sensitivity_b2(I0, f1, f2, r_d, r2):
    """Version 1 — peak magnitude of equation B2 as written in the paper:
    max |S_m| = I0 * (3/2)^(3/2) * exp(-3/2). Dimensionless."""
    return I0 * (1.5 ** 1.5) * np.exp(-1.5)


def sensitivity_slope(I0, f1, f2, r_d, r2):
    """Version 2 — peak of |dI_m/d(dz1)|: 2*sqrt(2) * (3/2)^(3/2) * exp(-3/2) * I0 / A_val,
    with A_val = f1**2 * r_d / (2 * r2 * f2). Units: intensity per mm."""
    A_val = (f1**2 * r_d) / (2.0 * r2 * f2)
    return 2.0 * np.sqrt(2.0) * (1.5 ** 1.5) * np.exp(-1.5) * I0 / A_val


def linear_range_fwhm(f1, f2, r_d, r2, I0=1.0):
    """Version 1 — FWHM of |S_m(dz1)| from equation B2 (numerical sweep)."""
    prefactor = f1**2 * r_d / (2.0 * r2 * f2)
    peak_dz1 = prefactor / np.sqrt(1.5)
    dz1 = np.linspace(0.01 * peak_dz1, 8.0 * peak_dz1, 20000)
    Sm = np.abs(eqB2_Sm(dz1, I0, f1, f2, r_d, r2))
    half_max = 0.5 * Sm.max()
    mask = Sm >= half_max
    if not mask.any():
        return 0.0
    idx = np.where(mask)[0]
    return float(dz1[idx[-1]] - dz1[idx[0]])


def linear_range_empirical(f1, f2, r_d, r2, I0=1.0):
    """Version 2 — empirical width: 1.88538975 * A_val, A_val = f1**2*r_d/(2*r2*f2)."""
    A_val = (f1**2 * r_d) / (2.0 * r2 * f2)
    return 1.88538975 * A_val


# --- Values computed from the initial parameters above ---
# r2 at the operating point dz1 = 0, derived via equations 1-4.
_r1_prime_0 = eq2_r1_prime(r1, f1, 0.0)
_tan_alpha_0 = eq3_tan_alpha(_r1_prime_0, r1, f1)
_r2_0 = eq4_r2(_r1_prime_0, L, _tan_alpha_0)

offset = z2_offset(f2, r_d, _r2_0)
peak_sensitivity_b2    = sensitivity_b2(I0, f1, f2, r_d, _r2_0)
peak_sensitivity_slope = sensitivity_slope(I0, f1, f2, r_d, _r2_0)
range_fwhm             = linear_range_fwhm(f1, f2, r_d, _r2_0, I0)
range_empirical        = linear_range_empirical(f1, f2, r_d, _r2_0, I0)


# --- Visualisation ---

if __name__ == "__main__":
    print("=== Confocal derived values ===")
    print(f"z2 offset               : {offset:.5f} mm")
    print(f"sensitivity (B2 peak)   : {peak_sensitivity_b2:.5f}")
    print(f"sensitivity (dIm slope) : {peak_sensitivity_slope:.5f} / mm")
    print(f"linear range (B2 FWHM)  : {range_fwhm:.5f} mm")
    print(f"linear range (empirical): {range_empirical:.5f} mm")
    print("===============================")

    dz1 = np.linspace(-5.0, 5.0, 1000)

    # r2 is always calculated via the equation 1-4 chain.
    r1_prime = eq2_r1_prime(r1, f1, dz1)
    tan_alpha = eq3_tan_alpha(r1_prime, r1, f1)
    r2 = eq4_r2(r1_prime, L, tan_alpha)

    # q per the convention stated at the top of this file: q == z2 offset (equation B4).
    q = z2_offset(f2, r_d, r2)
    Im = eqA6_Im(dz1, f1, f2, L, r1, q, r_d, I0)

    plt.figure(figsize=(8, 5))
    plt.plot(dz1, Im, label=r"Equation 12: $I_m(\delta z_1)$")
    plt.title("Confocal intensity response")
    plt.xlabel(r"$\delta z_1$ (mm)")
    plt.ylabel(r"Intensity $I_m$")
    plt.legend()
    plt.grid(True)
    plt.show()
