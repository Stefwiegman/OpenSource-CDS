"""Grid search over f1 and f2 for the confocal model in confocal.py.

Sweeps:
    f1: 0.5 - 4.0 cm in 0.5 cm steps  (5 - 40 mm, step 5 mm)
    f2: 10  - 25  cm in 5   cm steps  (100 - 250 mm, step 50 mm)
    L  = f1 + f2 (confocal geometry)

For each (f1, f2) the script reports the derived values that confocal.py
prints in its __main__ block: z2 offset, sensitivity (B2 + slope), and
linear range (FWHM + empirical). r1, r_d and I0 are taken from confocal.py.
"""

import numpy as np
import pandas as pd

import confocal as c


CSV_PATH = "gridsearch_results.csv"


# Grid in mm.
F1_VALUES = np.arange(5.0, 40.0 + 1e-9, 5.0)      # 0.5 - 4.0 cm, step 0.5 cm
F2_VALUES = np.arange(100.0, 250.0 + 1e-9, 50.0)  # 10 - 25 cm, step 5 cm


def compute_row(f1, f2, r1=c.r1, r_d=c.r_d, I0=c.I0):
    """Confocal derived values for one (f1, f2) combination, with L = f1+f2."""
    L = f1 + f2
    # r2 at the operating point dz1 = 0 via the eq 1-4 chain (matches confocal.py).
    r1_prime_0 = c.eq2_r1_prime(r1, f1, 0.0)
    tan_alpha_0 = c.eq3_tan_alpha(r1_prime_0, r1, f1)
    r2_0 = c.eq4_r2(r1_prime_0, L, tan_alpha_0)

    # Evaluate B2 at its peak location: dz1* = f1**2 * r_d / (2*r2*f2*sqrt(3/2)).
    dz1_peak_b2 = (f1**2 * r_d) / (2.0 * r2_0 * f2 * np.sqrt(1.5))
    return {
        "f1_mm": f1,
        "f2_mm": f2,
        "L_mm": L,
        "offset_mm": c.z2_offset(f2, r_d, r2_0),
        "sens_b2": c.sensitivity_b2(I0, f1, f2, r_d, r2_0, dz1_peak_b2),
        "sens_slope_per_mm": c.sensitivity_slope(I0, f1, f2, r_d, r2_0),
        "range_fwhm_mm": c.linear_range_fwhm(f1, f2, r_d, r2_0, I0),
        "range_empirical_mm": c.linear_range_empirical(f1, f2, r_d, r2_0, I0),
    }


def run_grid():
    return [compute_row(f1, f2) for f1 in F1_VALUES for f2 in F2_VALUES]


if __name__ == "__main__":
    print(
        f"Grid search over f1 and f2 (confocal.py), "
        f"L = f1+f2, r1={c.r1} mm, r_d={c.r_d} mm, I0={c.I0}"
    )
    print()

    df = pd.DataFrame(run_grid())
    print(df.to_string(index=False, float_format=lambda x: f"{x:.5f}"))

    # Dutch Excel expects ; as column separator and , as decimal mark.
    df.to_csv(CSV_PATH, index=False, sep=";", decimal=",", float_format="%.5f")
    print(f"\nWrote {len(df)} rows to {CSV_PATH}")
