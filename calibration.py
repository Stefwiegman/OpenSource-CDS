"""Recover unknown system parameters from a measured intensity curve.

Given paired (dz1, I_m) measurements and a config with some parameters known,
fit the remaining parameters by non-linear least squares against the forward
model `confocal.intensity`.
"""

import numpy as np
from scipy.optimize import least_squares

from confocal import intensity


REQUIRED_KEYS = ("f1", "f2", "L", "r0", "q", "r_diaphragm", "I0")


def fit_parameters(dz1_measured, I_m_measured, known_params, free_params, initial_guess=None):
    """Fit a subset of model parameters from measurements.

    Parameters
    ----------
    dz1_measured : array-like
        Sample positions (mm).
    I_m_measured : array-like
        Measured intensities at those positions.
    known_params : dict
        Parameter values that are fixed during the fit. Must together with
        `free_params` cover every key in REQUIRED_KEYS.
    free_params : sequence[str]
        Names of parameters to fit (subset of REQUIRED_KEYS).
    initial_guess : dict, optional
        Starting values for free params. Defaults to 1.0 for each.

    Returns
    -------
    fitted : dict
        {name: value} for each free parameter.
    residuals : ndarray
        Final residuals (I_fit - I_m_measured).
    result : scipy.optimize.OptimizeResult
        Raw scipy result for inspection.
    """
    free_params = list(free_params)
    missing = set(REQUIRED_KEYS) - set(known_params) - set(free_params)
    if missing:
        raise ValueError(f"Parameters not covered by known+free: {sorted(missing)}")
    overlap = set(known_params) & set(free_params)
    if overlap:
        raise ValueError(f"Parameters appear in both known and free: {sorted(overlap)}")

    if initial_guess is None:
        initial_guess = {name: 1.0 for name in free_params}
    x0 = np.array([float(initial_guess[name]) for name in free_params])

    dz1_arr = np.asarray(dz1_measured, dtype=float)
    I_arr = np.asarray(I_m_measured, dtype=float)

    def residual(x):
        params = dict(known_params)
        for name, val in zip(free_params, x):
            params[name] = val
        I_pred = intensity(dz1_arr, **{k: params[k] for k in REQUIRED_KEYS})
        return np.asarray(I_pred) - I_arr

    result = least_squares(residual, x0)
    fitted = {name: float(val) for name, val in zip(free_params, result.x)}
    return fitted, result.fun, result
