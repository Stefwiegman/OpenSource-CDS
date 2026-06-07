# SPDX-License-Identifier: MIT

"""Calibration persistence for the Bep-Project.

Stores per motor:
  - mm_per_step: how large a step is physically (mm). 0 = not calibrated.
  - last_position: last known position in steps, read via the firmware
                   "WHERE" command on disconnect / Save.
  - note: free text, e.g. "crosshair on sample corner X".

File: calibration.yaml in the project root.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List

import yaml


CALIBRATION_PATH = Path("calibration.yaml")


@dataclass
class MotorCal:
    mm_per_step: float = 0.0           # 0 = not calibrated
    last_position: int = 0             # steps
    note: str = ""

    def is_calibrated(self) -> bool:
        return self.mm_per_step > 0

    def steps_to_mm(self, steps: int) -> float:
        return steps * self.mm_per_step if self.is_calibrated() else 0.0


@dataclass
class Calibration:
    motors: List[MotorCal] = field(
        default_factory=lambda: [MotorCal(), MotorCal(), MotorCal()]
    )
    saved_at: str = ""

    def all_calibrated(self) -> bool:
        return all(m.is_calibrated() for m in self.motors)

    def any_known_position(self) -> bool:
        return any(m.last_position != 0 for m in self.motors)


def load(path: Path = CALIBRATION_PATH) -> Calibration:
    """Load an existing calibration file or return defaults."""
    if not path.exists():
        return Calibration()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return Calibration()
    motors = []
    for entry in (data.get("motors") or [{}, {}, {}]):
        motors.append(MotorCal(
            mm_per_step=float(entry.get("mm_per_step", 0.0) or 0.0),
            last_position=int(entry.get("last_position", 0) or 0),
            note=str(entry.get("note", "") or ""),
        ))
    while len(motors) < 3:
        motors.append(MotorCal())
    return Calibration(motors=motors[:3], saved_at=str(data.get("saved_at", "")))


def save(cal: Calibration, path: Path = CALIBRATION_PATH) -> None:
    cal.saved_at = datetime.now().isoformat(timespec="seconds")
    payload = asdict(cal)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
