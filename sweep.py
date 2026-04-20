"""Automated position sweep against a Stage + Detector pair.

CLI mode writes a CSV of (position_mm, intensity) using the Mock hardware
so the pipeline can be tested end-to-end without physical equipment.

Run:
    python sweep.py                    # uses MODULE_MEDIUM preset, writes sweep_output.csv
    python sweep.py --config my.yaml   # uses a YAML config
"""

import argparse
import csv

import numpy as np

from confocal import MODULE_MEDIUM, half_width, peak_position
from hardware import MockDetector, MockStage


def run_sweep(stage, detector, positions):
    """Move the stage through `positions` and record the detector reading at each."""
    samples = []
    for pos in positions:
        stage.move_to(float(pos))
        samples.append((float(pos), float(detector.read())))
    return samples


def write_csv(samples, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["position_mm", "intensity"])
        writer.writerows(samples)


def _default_positions(params, n_points=500, span_halfwidths=4.0):
    center = peak_position(params["f1"], params["f2"], params["L"], params["q"])
    hw = half_width(
        params["f1"], params["f2"], params["L"],
        params["r0"], params["q"], params["r_diaphragm"],
    )
    return np.linspace(center - span_halfwidths * hw, center + span_halfwidths * hw, n_points)


def main():
    parser = argparse.ArgumentParser(description="Run a mock confocal sweep.")
    parser.add_argument("--config", help="YAML config path (defaults to MODULE_MEDIUM).")
    parser.add_argument("--output", default="sweep_output.csv", help="CSV output path.")
    parser.add_argument("--points", type=int, default=500, help="Number of sweep points.")
    parser.add_argument("--sigma-shot", type=float, default=0.0, help="Shot-noise sigma.")
    parser.add_argument("--sigma-read", type=float, default=0.0, help="Read-noise sigma.")
    args = parser.parse_args()

    if args.config:
        from config import load_config
        params = load_config(args.config)
    else:
        params = dict(MODULE_MEDIUM)

    positions = _default_positions(params, n_points=args.points)
    stage = MockStage(initial_position=float(positions[0]))
    detector = MockDetector(
        stage, params,
        sigma_shot=args.sigma_shot,
        sigma_read=args.sigma_read,
    )

    samples = run_sweep(stage, detector, positions)
    write_csv(samples, args.output)
    peak_idx = int(np.argmax([s[1] for s in samples]))
    print(f"Wrote {len(samples)} rows to {args.output}")
    print(f"Peak intensity {samples[peak_idx][1]:.6f} at position {samples[peak_idx][0]:.4f} mm")


if __name__ == "__main__":
    main()
