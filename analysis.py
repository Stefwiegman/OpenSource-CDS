"""Vibration analysis helpers.

Takes a time-series of recovered displacements dz1(t) and returns its
amplitude spectrum. Useful for Fase-2 trillingsanalyse.
"""

import numpy as np


def vibration_spectrum(dz1_timeseries, sample_rate):
    """Single-sided amplitude spectrum of dz1(t).

    Parameters
    ----------
    dz1_timeseries : 1-D array
        Displacement samples (mm) at uniform intervals 1/sample_rate.
    sample_rate : float
        Sample rate in Hz.

    Returns
    -------
    freqs : ndarray
        Frequency bins (Hz), 0 .. Nyquist.
    amplitudes : ndarray
        Amplitude per bin in the same units as the input (mm).
        Scaled so that a pure sine of amplitude A maps to A at its bin.
    """
    x = np.asarray(dz1_timeseries, dtype=float)
    n = x.size
    if n < 2:
        raise ValueError("Need at least 2 samples for a spectrum.")
    x_centered = x - x.mean()
    spectrum = np.fft.rfft(x_centered)
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate)
    amplitudes = (2.0 / n) * np.abs(spectrum)
    return freqs, amplitudes


def dominant_frequency(dz1_timeseries, sample_rate):
    """Return the frequency bin with the largest amplitude (Hz)."""
    freqs, amps = vibration_spectrum(dz1_timeseries, sample_rate)
    return float(freqs[int(np.argmax(amps))])
