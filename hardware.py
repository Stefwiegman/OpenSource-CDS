"""Hardware abstraction for the confocal rig.

Abstract interfaces (`Stage`, `Detector`) plus in-memory `MockStage` and
`MockDetector` that wrap the forward model so we can test the measurement
pipeline end-to-end without real hardware.

Real drivers (stepper/motor controllers, ADCs) will be added in Fase 3 as
concrete subclasses of `Stage` / `Detector`.
"""

from abc import ABC, abstractmethod

import numpy as np

from confocal import add_noise, intensity


class Stage(ABC):
    """Abstract 1-D translation stage."""

    @abstractmethod
    def move_to(self, position):
        """Move to `position` (mm). Blocks until the motion completes."""

    @abstractmethod
    def current_position(self):
        """Return the current stage position (mm)."""


class Detector(ABC):
    """Abstract single-channel intensity detector."""

    @abstractmethod
    def read(self):
        """Return the current intensity reading."""


class MockStage(Stage):
    """In-memory stage with optional positioning noise."""

    def __init__(self, initial_position=0.0, position_noise=0.0, rng=None):
        self._position = float(initial_position)
        self._position_noise = float(position_noise)
        self._rng = rng if rng is not None else np.random.default_rng()

    def move_to(self, position):
        target = float(position)
        if self._position_noise > 0:
            target += self._position_noise * self._rng.standard_normal()
        self._position = target

    def current_position(self):
        return self._position


class MockDetector(Detector):
    """Reads intensity by calling `confocal.intensity` at the stage position."""

    def __init__(self, stage, params, sigma_shot=0.0, sigma_read=0.0, rng=None):
        """`params` must contain f1, f2, L, r0, q, r_diaphragm, I0."""
        self._stage = stage
        self._params = dict(params)
        self._sigma_shot = float(sigma_shot)
        self._sigma_read = float(sigma_read)
        self._rng = rng if rng is not None else np.random.default_rng()

    def read(self):
        dz1 = self._stage.current_position()
        I_clean = intensity(dz1, **self._params)
        if self._sigma_shot == 0.0 and self._sigma_read == 0.0:
            return float(I_clean)
        return float(
            add_noise(
                I_clean,
                sigma_shot=self._sigma_shot,
                sigma_read=self._sigma_read,
                rng=self._rng,
            )
        )
