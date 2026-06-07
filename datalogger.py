# SPDX-License-Identifier: MIT

"""MokuDatalogger wrapper for burst acquisition per scan point.

Used by MokuPanel.acquire_burst() in ui.py. Testable standalone:

    from datalogger import MokuDatalogger, voltage_to_dz1
    with MokuDatalogger("192.168.73.1", 1, "50Vpp", "DC") as dl:
        voltage = dl.acquire_burst(fs=100_000, duration_s=0.5)
    dz1_mm = voltage_to_dz1(voltage, I0=2.5)   # optional: V -> displacement

Works in streaming mode: the Moku sends samples continuously over the network and
we collect them in memory until the requested duration is reached. For sample
rates above ~500 kSa/s you have to switch to file mode (see .start_logging).

Output:
    acquire_burst() ALWAYS returns raw voltage in V (1D float64 array).
    The conversion to displacement dz1 (mm) happens in the write layer
    (recording.py / scan.py) via voltage_to_dz1(), so the raw measurement data
    is always preserved.
"""
from __future__ import annotations

import time

import numpy as np


def voltage_to_dz1(voltage: np.ndarray, I0: float,
                   f1: float | None = None) -> np.ndarray:
    """Convert photodetector voltage (V) to displacement dz1 (mm) via formula A6.

    Uses the dz1_minus branch of A6 and clips to 0 < I_m < I0 so the inversion is
    always defined (AC coupling/noise can occasionally fall outside the range).

    f1 is the focal length of lens 1 (mm); None -> confocal default.
    """
    from confocal import compute_q, compute_dz1, f1 as f1_default
    v = np.asarray(voltage, dtype=np.float64)
    eps = 1e-9
    Im = np.clip(v, eps, I0 - eps)
    f1_val = f1_default if f1 is None else float(f1)
    q = compute_q(f1=f1_val)
    dz1_minus, _ = compute_dz1(Im, q, f1=f1_val, I0=I0)
    return dz1_minus


class MokuDatalogger:
    """Synchronous burst acquisition via moku.instruments.Datalogger."""

    def __init__(self, address: str, channel: int,
                 range_: str, coupling: str,
                 I0: float | None = None) -> None:
        self.address = address
        self.channel = channel
        self.range_ = range_
        self.coupling = coupling
        self.I0 = I0
        self._dl = None

    def open(self) -> None:
        from moku.instruments import Datalogger
        self._dl = Datalogger(self.address, force_connect=True)
        self._dl.set_frontend(
            self.channel,
            impedance="1MOhm",
            coupling=self.coupling,
            range=self.range_,
        )

    def close(self) -> None:
        if self._dl is None:
            return
        try:
            self._dl.stop_streaming()
        except Exception:
            pass
        try:
            self._dl.relinquish_ownership()
        except Exception:
            pass
        self._dl = None

    def __enter__(self) -> "MokuDatalogger":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def acquire_burst(self, fs: int, duration_s: float) -> np.ndarray:
        """Take one burst and return a 1D float64 array of fs x T samples."""
        if self._dl is None:
            raise RuntimeError("Datalogger not open, call .open() or use 'with'.")

        self._dl.set_samplerate(int(fs))
        self._dl.start_streaming(duration=float(duration_s))

        ch_key = f"ch{self.channel}"
        target_n = int(round(fs * duration_s))
        samples: list[float] = []
        deadline = time.monotonic() + duration_s + 3.0

        while time.monotonic() < deadline:
            try:
                chunk = self._dl.get_stream_data()
            except Exception:
                break
            if not chunk:
                if len(samples) >= target_n:
                    break
                time.sleep(0.02)
                continue
            data = chunk.get(ch_key)
            if data:
                samples.extend(data)
            if len(samples) >= target_n:
                break

        try:
            self._dl.stop_streaming()
        except Exception:
            pass

        if not samples:
            raise RuntimeError(
                "Datalogger returned 0 samples, check sample rate, channel and connection."
            )

        voltage = np.asarray(samples[:target_n] if target_n else samples,
                             dtype=np.float64)
        # Always raw voltage, conversion to dz1 happens in the write layer.
        return voltage
