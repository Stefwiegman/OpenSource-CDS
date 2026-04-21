"""Confocal displacement sensing - forward and inverse model.

Implements equations A5 (detector-plane spot radius) and A6 (measured
intensity through the pinhole) from the reference confocal-setup derivation.

    A5:  r_det = r0 * (-2*L*dz1*q + 2*dz1*f1*q + 2*dz1*f1**2 + 2*dz1*f2*q
                       - f1**2 * q) / (f1**2 * f2)

    A6:  I_m = I0 * (1 - exp(-r_diaphragm**2 / r_det**2))

Since I_m depends only on r_det**2, the inverse (I_m -> dz1) has two
solutions symmetric around the peak position. `invert_intensity` returns
both; choose the physical one based on known displacement direction.
"""

import numpy as np


# --- Module presets ---
# Basis-geometrie van onze opstelling: f1=25 mm, f2=50 mm, confocaal (L=f1+f2),
# r0=8 mm laserbundel-straal bij F1, q=2 mm object-side aperture,
# detector-oppervlak fungeert als pinhole (diameter 0.4 mm -> r=0.2 mm).
# MODULE_MEDIUM = onze daadwerkelijke setup.
# MODULE_FINE / MODULE_COARSE = hypothetische varianten met krappere / ruimere
# effectieve aperture (bijv. door extra diafragma voor de detector te plakken),
# zelfde lens-geometrie, om te laten zien hoe het bereik meeschaalt.
MODULE_FINE = {
    "f1": 25.0, "f2": 50.0, "L": 75.0,
    "r0": 8.0, "q": 2.0, "r_diaphragm": 0.05, "I0": 1.0,
}
MODULE_MEDIUM = {
    "f1": 25.0, "f2": 50.0, "L": 75.0,
    "r0": 8.0, "q": 2.0, "r_diaphragm": 0.2, "I0": 1.0,
}
MODULE_COARSE = {
    "f1": 25.0, "f2": 50.0, "L": 75.0,
    "r0": 8.0, "q": 2.0, "r_diaphragm": 0.5, "I0": 1.0,
}


def r_det(dz1, f1, f2, L, r0, q):
    """Detector-plane spot radius (equation A5).

    Accepts scalar or array `dz1`; all other parameters are scalars.
    """
    numerator = r0 * (
        -2 * L * dz1 * q
        + 2 * dz1 * f1 * q
        + 2 * dz1 * f1**2
        + 2 * dz1 * f2 * q
        - f1**2 * q
    )
    return numerator / (f1**2 * f2)


def intensity(dz1, f1, f2, L, r0, q, r_diaphragm, I0):
    """Intensity transmitted through the pinhole (equation A6).

    At r_det -> 0 (perfect focus on the pinhole) the limit is I_m = I0.
    """
    rd = np.asarray(r_det(dz1, f1, f2, L, r0, q), dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        result = I0 * (1.0 - np.exp(-r_diaphragm**2 / rd**2))
    # r_det == 0 -> exp(-inf) = 0 -> result = I0, numpy handles this correctly;
    # the errstate above just silences the divide-by-zero warning.
    if rd.ndim == 0:
        return float(result)
    return result


def invert_intensity(I_m, f1, f2, L, r0, q, r_diaphragm, I0):
    """Solve A6 + A5 for dz1 given a measured intensity I_m.

    Returns a tuple (dz1_plus, dz1_minus) of the two solutions, symmetric
    around the peak position dz1_center = f1**2 * q / A (see A below).
    Raises ValueError if I_m is outside [0, I0).
    """
    if not (0.0 <= I_m < I0):
        raise ValueError(
            f"I_m must satisfy 0 <= I_m < I0 (got I_m={I_m}, I0={I0})."
        )

    # A5 is linear in dz1: r_det = (A*dz1 + B) * r0 / (f1**2 * f2)
    A = -2 * L * q + 2 * f1 * q + 2 * f1**2 + 2 * f2 * q
    B = -(f1**2) * q
    if A == 0:
        raise ValueError("Degenerate lens configuration (A=0); cannot solve for dz1.")

    if I_m == 0.0:
        # r_det -> infinity; dz1 -> +/- infinity. Degenerate edge case.
        return (float("inf"), float("-inf"))

    # Invert A6: r_det**2 = -r_diaphragm**2 / ln(1 - I_m/I0)
    r_det_sq = -(r_diaphragm**2) / np.log(1.0 - I_m / I0)
    r_det_val = float(np.sqrt(r_det_sq))

    scale = f1**2 * f2 / r0
    dz1_plus = (r_det_val * scale - B) / A
    dz1_minus = (-r_det_val * scale - B) / A
    return (dz1_plus, dz1_minus)


def dz2_from_dz1(dz1, f1, f2):
    """Image-plane displacement for a reflective target at L = f1 + f2.

    Factor of 2 accounts for the round-trip (reflection) so the virtual
    object point shifts by 2*dz1 before imaging through the lens pair.
    """
    return -2 * dz1 * (f2 / f1) ** 2


def _A_B(f1, f2, L, q):
    """Linear-form coefficients: r_det = (A*dz1 + B) * r0 / (f1**2 * f2)."""
    A = -2 * L * q + 2 * f1 * q + 2 * f1**2 + 2 * f2 * q
    B = -(f1**2) * q
    return A, B


def peak_position(f1, f2, L, q):
    """dz1 where r_det = 0 (intensity peaks at I0)."""
    A, B = _A_B(f1, f2, L, q)
    if A == 0:
        raise ValueError("Degenerate lens configuration (A=0).")
    return -B / A


def half_width(f1, f2, L, r0, q, r_diaphragm):
    """Half-max half-width of I_m(dz1) around the peak.

    I_m = I0/2 <=> r_det = r_diaphragm / sqrt(ln 2). Since r_det is linear
    in dz1, the half-width in dz1 is hw_r_det / |slope of r_det w.r.t. dz1|.
    """
    A, _ = _A_B(f1, f2, L, q)
    if A == 0:
        raise ValueError("Degenerate lens configuration (A=0).")
    hw_rd = r_diaphragm / np.sqrt(np.log(2))
    return hw_rd * f1**2 * f2 / (r0 * abs(A))


def intensity_slope(dz1, f1, f2, L, r0, q, r_diaphragm, I0):
    """Analytical dI_m/ddz1.

    I_m = I0 * (1 - exp(-r_d**2 / r_det**2))
    d/ddz1 = I0 * exp(-r_d**2/r_det**2) * (-2 * r_d**2 / r_det**3) * d(r_det)/ddz1
    With r_det = (A*dz1 + B) * r0 / (f1**2 * f2), so d(r_det)/ddz1 = A*r0/(f1**2*f2).
    """
    A, _ = _A_B(f1, f2, L, q)
    rd = np.asarray(r_det(dz1, f1, f2, L, r0, q), dtype=float)
    drd_ddz1 = A * r0 / (f1**2 * f2)
    with np.errstate(divide="ignore", invalid="ignore"):
        exp_term = np.exp(-(r_diaphragm**2) / rd**2)
        result = I0 * exp_term * (-2.0 * r_diaphragm**2 / rd**3) * drd_ddz1
    # At rd == 0, exp_term -> 0 faster than 1/rd**3 diverges, so slope -> 0.
    result = np.where(rd == 0, 0.0, result)
    if rd.ndim == 0:
        return float(result)
    return result


def add_noise(I_m, sigma_shot=0.0, sigma_read=0.0, rng=None):
    """Apply shot + read noise to a measured intensity.

    - sigma_shot: scales as sqrt(I_m) (Poisson-like in the Gaussian limit).
    - sigma_read: constant per-sample Gaussian noise floor.

    Both sigmas are in the same units as I_m (normalized intensity here).
    Result is clipped to [0, inf) to avoid negative "intensities".
    """
    if rng is None:
        rng = np.random.default_rng()
    I_arr = np.asarray(I_m, dtype=float)
    shot = sigma_shot * np.sqrt(np.clip(I_arr, 0.0, None)) * rng.standard_normal(I_arr.shape)
    read = sigma_read * rng.standard_normal(I_arr.shape)
    noisy = np.clip(I_arr + shot + read, 0.0, None)
    if I_arr.ndim == 0:
        return float(noisy)
    return noisy


def inverse_uncertainty(I_m, sigma_I, f1, f2, L, r0, q, r_diaphragm, I0):
    """Propagate intensity uncertainty to dz1 uncertainty on both inverse branches.

    sigma_dz1 ~ sigma_I / |dI/ddz1| evaluated at each of the two dz1 solutions.
    Returns (sigma_plus, sigma_minus) matching the order of `invert_intensity`.
    """
    dz1_plus, dz1_minus = invert_intensity(I_m, f1, f2, L, r0, q, r_diaphragm, I0)
    slope_plus = intensity_slope(dz1_plus, f1, f2, L, r0, q, r_diaphragm, I0)
    slope_minus = intensity_slope(dz1_minus, f1, f2, L, r0, q, r_diaphragm, I0)
    sig_plus = float("inf") if slope_plus == 0 else abs(sigma_I / slope_plus)
    sig_minus = float("inf") if slope_minus == 0 else abs(sigma_I / slope_minus)
    return (sig_plus, sig_minus)


def directional_inverse(
    I_m, f1, f2, L, r0, q, r_diaphragm, I0,
    previous_dz1=None, direction=None,
):
    """Pick one branch of `invert_intensity` using prior knowledge.

    - direction="up"   -> return dz1 > peak_position.
    - direction="down" -> return dz1 < peak_position.
    - Otherwise, if previous_dz1 is given, return whichever solution is closest.
    - If neither is given, raise ValueError.
    """
    dz1_plus, dz1_minus = invert_intensity(I_m, f1, f2, L, r0, q, r_diaphragm, I0)
    if direction == "up":
        return max(dz1_plus, dz1_minus)
    if direction == "down":
        return min(dz1_plus, dz1_minus)
    if previous_dz1 is not None:
        if abs(dz1_plus - previous_dz1) <= abs(dz1_minus - previous_dz1):
            return dz1_plus
        return dz1_minus
    raise ValueError("directional_inverse needs `direction` or `previous_dz1`.")
