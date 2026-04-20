"""Pytest suite for the confocal model and surrounding helpers."""

import os
import sys

import numpy as np
import pytest

# Make repo root importable when pytest is invoked from the tests/ dir.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from analysis import dominant_frequency, vibration_spectrum  # noqa: E402
from calibration import fit_parameters  # noqa: E402
from confocal import (  # noqa: E402
    MODULE_COARSE,
    MODULE_FINE,
    MODULE_MEDIUM,
    add_noise,
    directional_inverse,
    half_width,
    intensity,
    intensity_slope,
    inverse_uncertainty,
    invert_intensity,
    peak_position,
    r_det,
)
from hardware import MockDetector, MockStage  # noqa: E402
from sweep import run_sweep  # noqa: E402


ALL_MODULES = [MODULE_FINE, MODULE_MEDIUM, MODULE_COARSE]


@pytest.mark.parametrize("params", ALL_MODULES)
def test_round_trip(params):
    center = peak_position(params["f1"], params["f2"], params["L"], params["q"])
    hw = half_width(
        params["f1"], params["f2"], params["L"],
        params["r0"], params["q"], params["r_diaphragm"],
    )
    dz1 = center + 1.3 * hw
    I_m = intensity(dz1, **params)
    dz1_plus, dz1_minus = invert_intensity(I_m, **params)
    err = min(abs(dz1 - dz1_plus), abs(dz1 - dz1_minus))
    assert err < 1e-9


@pytest.mark.parametrize("params", ALL_MODULES)
def test_intensity_monotonic_away_from_peak(params):
    center = peak_position(params["f1"], params["f2"], params["L"], params["q"])
    hw = half_width(
        params["f1"], params["f2"], params["L"],
        params["r0"], params["q"], params["r_diaphragm"],
    )
    up = np.linspace(center, center + 3 * hw, 50)
    down = np.linspace(center, center - 3 * hw, 50)
    I_up = intensity(up, **params)
    I_down = intensity(down, **params)
    assert np.all(np.diff(I_up) <= 1e-12)
    assert np.all(np.diff(I_down) <= 1e-12)


def test_peak_intensity_confocal():
    params = MODULE_MEDIUM
    center = peak_position(params["f1"], params["f2"], params["L"], params["q"])
    rd = r_det(center, params["f1"], params["f2"], params["L"], params["r0"], params["q"])
    assert abs(rd) < 1e-12
    assert abs(intensity(center, **params) - params["I0"]) < 1e-12


def test_invert_intensity_rejects_out_of_range():
    params = MODULE_MEDIUM
    with pytest.raises(ValueError):
        invert_intensity(-0.1, **params)
    with pytest.raises(ValueError):
        invert_intensity(params["I0"], **params)  # I_m == I0 is excluded


def test_directional_inverse_picks_correct_branch():
    params = MODULE_MEDIUM
    center = peak_position(params["f1"], params["f2"], params["L"], params["q"])
    hw = half_width(
        params["f1"], params["f2"], params["L"],
        params["r0"], params["q"], params["r_diaphragm"],
    )
    dz1_true = center + 1.2 * hw
    I_m = intensity(dz1_true, **params)

    by_direction = directional_inverse(I_m, direction="up", **params)
    assert abs(by_direction - dz1_true) < 1e-9

    by_previous = directional_inverse(I_m, previous_dz1=dz1_true - 0.01, **params)
    assert abs(by_previous - dz1_true) < 1e-9


def test_directional_inverse_requires_hint():
    params = MODULE_MEDIUM
    I_m = 0.5
    with pytest.raises(ValueError):
        directional_inverse(I_m, **params)


def test_intensity_accepts_arrays():
    params = MODULE_MEDIUM
    dz1 = np.linspace(-1.0, 3.0, 17)
    I = intensity(dz1, **params)
    assert isinstance(I, np.ndarray)
    assert I.shape == dz1.shape


def test_calibration_recovers_parameters_noise_free():
    true_params = dict(MODULE_MEDIUM)
    center = peak_position(
        true_params["f1"], true_params["f2"], true_params["L"], true_params["q"]
    )
    hw = half_width(
        true_params["f1"], true_params["f2"], true_params["L"],
        true_params["r0"], true_params["q"], true_params["r_diaphragm"],
    )
    dz1 = np.linspace(center - 2 * hw, center + 2 * hw, 200)
    I_m = intensity(dz1, **true_params)

    known = {k: v for k, v in true_params.items() if k != "r_diaphragm"}
    fitted, residuals, _ = fit_parameters(
        dz1, I_m,
        known_params=known,
        free_params=["r_diaphragm"],
        initial_guess={"r_diaphragm": 0.05},
    )
    assert abs(fitted["r_diaphragm"] - true_params["r_diaphragm"]) < 1e-6
    assert np.max(np.abs(residuals)) < 1e-6


def test_add_noise_shapes_and_clipping():
    rng = np.random.default_rng(42)
    I_clean = np.full(1000, 0.5)
    I_noisy = add_noise(I_clean, sigma_shot=0.01, sigma_read=0.005, rng=rng)
    assert I_noisy.shape == I_clean.shape
    assert np.all(I_noisy >= 0.0)
    # Mean should be close to the clean value.
    assert abs(I_noisy.mean() - 0.5) < 0.01


def test_inverse_uncertainty_is_positive_and_finite():
    params = MODULE_MEDIUM
    sig_plus, sig_minus = inverse_uncertainty(0.4, 0.001, **params)
    assert sig_plus > 0 and np.isfinite(sig_plus)
    assert sig_minus > 0 and np.isfinite(sig_minus)


def test_intensity_slope_matches_numeric_derivative():
    params = MODULE_MEDIUM
    dz1 = peak_position(params["f1"], params["f2"], params["L"], params["q"]) + 2.0
    h = 1e-6
    numeric = (intensity(dz1 + h, **params) - intensity(dz1 - h, **params)) / (2 * h)
    analytic = intensity_slope(dz1, **params)
    assert abs(numeric - analytic) < 1e-6


def test_vibration_spectrum_finds_injected_tone():
    sample_rate = 1000.0
    t = np.arange(0, 1.0, 1.0 / sample_rate)
    signal = 0.01 * np.sin(2 * np.pi * 50.0 * t)
    assert abs(dominant_frequency(signal, sample_rate) - 50.0) < 1.0
    freqs, amps = vibration_spectrum(signal, sample_rate)
    assert amps[np.argmin(np.abs(freqs - 50.0))] > 0.5 * amps.max()


def test_mock_pipeline_round_trip():
    params = dict(MODULE_MEDIUM)
    center = peak_position(params["f1"], params["f2"], params["L"], params["q"])
    hw = half_width(
        params["f1"], params["f2"], params["L"],
        params["r0"], params["q"], params["r_diaphragm"],
    )
    positions = np.linspace(center - 2 * hw, center + 2 * hw, 50)
    stage = MockStage(initial_position=float(positions[0]))
    detector = MockDetector(stage, params)
    samples = run_sweep(stage, detector, positions)
    assert len(samples) == len(positions)
    # Near the peak I_m saturates at I0, so argmax can land anywhere in the
    # flat top. Check instead that samples far from the peak have lower intensity.
    pos_values = np.array([s[0] for s in samples])
    I_values = np.array([s[1] for s in samples])
    near_peak = np.abs(pos_values - center) < hw
    assert I_values[near_peak].min() > I_values[~near_peak].max()
