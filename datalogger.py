"""MokuDatalogger wrapper voor burst-acquisitie per scan-punt.

Wordt gebruikt door MokuPanel.acquire_burst() in ui.py. Standalone testbaar:

    from datalogger import MokuDatalogger
    with MokuDatalogger("192.168.73.1", 1, "10Vpp", "DC", I0=2.5) as dl:
        dz1_mm = dl.acquire_burst(fs=100_000, duration_s=0.5)
    print(dz1_mm.shape, dz1_mm.dtype)

Werkt in streaming-mode: Moku stuurt continu samples over het netwerk, wij
verzamelen ze in-memory tot de gevraagde duur is bereikt. Voor sample-rates
boven ~500 kSa/s moet je naar file-mode overstappen (zie .start_logging).

Output:
    - I0 = None  →  voltage in V (1D float64 array)
    - I0 > 0     →  verplaatsing dz1 in mm (1D float64 array, dz1_minus tak van A6)
"""
from __future__ import annotations

import time

import numpy as np


class MokuDatalogger:
    """Synchrone burst-acquisitie via moku.instruments.Datalogger."""

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
        """Doe één burst en retourneer een 1D float64-array van fs×T samples."""
        if self._dl is None:
            raise RuntimeError("Datalogger niet open — roep .open() of gebruik 'with'.")

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
                "Datalogger gaf 0 samples terug — check sample-rate, kanaal en verbinding."
            )

        voltage = np.asarray(samples[:target_n] if target_n else samples,
                             dtype=np.float64)

        if self.I0 is None or self.I0 <= 0:
            return voltage

        # V → dz1 (mm) via confocale formule A6, dz1_minus tak.
        # Clippen om de bounds 0 < I_m < I0 hard te garanderen — bij MEMS rond
        # focus zit V ruim binnen die range, maar AC-coupling of ruis kan
        # incidenteel buiten vallen.
        from confocal import compute_q, compute_dz1
        eps = 1e-9
        Im = np.clip(voltage, eps, self.I0 - eps)
        q = compute_q()
        dz1_minus, _ = compute_dz1(Im, q, I0=self.I0)
        return dz1_minus
