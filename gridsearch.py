"""Grid search over f1 and f2 for the confocal model in confocal.py.

Sweeps:
    f1: 0.5 - 4.0 cm in 0.5 cm steps  (5 - 40 mm, step 5 mm)
    f2: 10  - 25  cm in 5   cm steps  (100 - 250 mm, step 50 mm)
    L  = f1 + f2 (confocal geometry)

Per (f1, f2) the script reports values derived from equation A6:
    q                  - operating offset that makes I_m = I0/2 at dz1 = 0
    S_m at dz1 = 0     - slope of I_m at the operating point
    linear range       - dz1 distance between LINEAR_LOW*I0 and LINEAR_HIGH*I0
    amplitude metric   - dz1 distance between AMP_LOW*I0 and AMP_HIGH*I0

r0, r_d, I0 are taken from confocal.py.
"""

import numpy as np
import pandas as pd

import confocal as c


CSV_PATH = "gridsearch_results.csv"


# Grid in mm.
F1_VALUES = np.array([
    10,
    16,
    20,
    25,
    30,
    40,
    50,
    60
])
F2_VALUES = np.array([
    60,
    100,
    150,
    160,
    200
])

F1_VALUES_TEST = np.arange(5.0, 40.0 + 1e-9, 5.0)      # 0.5 - 4.0 cm, step 0.5 cm
F2_VALUES_TEST = np.arange(100.0, 250.0 + 1e-9, 50.0)  # 10 - 25 cm, step 5 cm


# Threshold fractions of I0. Adjust these to retune the reported ranges; the
# CSV column names follow the values so the output stays self-documenting.
LINEAR_LOW = 0.1
LINEAR_HIGH = 0.9
AMP_LOW = 0.5
AMP_HIGH = 0.9


def _dz1_through_zero(Im_level, q, f1, f2, L, r0, r_d, I0):
    """dz1 on the branch that passes through dz1 = 0 (where I_m = I0/2).

    compute_dz1 returns (minus, plus). At dz1 = 0, r_det = -q*r0/f2 < 0,
    which corresponds to the minus branch.
    """
    minus, _plus = c.compute_dz1(
        Im_level, q, f1=f1, f2=f2, L=L, r0=r0, r_d=r_d, I0=I0
    )
    return minus


def compute_row(f1, f2, r0=c.r0, r_d=c.r_d, I0=c.I0):
    """Confocal derived values for one (f1, f2) combination, with L = f1+f2."""
    L = 65 #f1 + f2
    q = c.compute_q(f1=f1, f2=f2, L=L, r0=r0, r_d=r_d, I0=I0)
    Sm0 = c.compute_Sm(0.0, q, f1=f1, f2=f2, L=L, r0=r0, r_d=r_d, I0=I0)

    dz1_lin_low = _dz1_through_zero(LINEAR_LOW * I0, q, f1, f2, L, r0, r_d, I0)
    dz1_lin_high = _dz1_through_zero(LINEAR_HIGH * I0, q, f1, f2, L, r0, r_d, I0)
    range_linear = abs(dz1_lin_low - dz1_lin_high)

    dz1_amp_low = _dz1_through_zero(AMP_LOW * I0, q, f1, f2, L, r0, r_d, I0)
    dz1_amp_high = _dz1_through_zero(AMP_HIGH * I0, q, f1, f2, L, r0, r_d, I0)
    range_amp = abs(dz1_amp_low - dz1_amp_high)

    lin_tag = f"{int(round(LINEAR_LOW * 100))}_{int(round(LINEAR_HIGH * 100))}"
    amp_tag = f"{int(round(AMP_LOW * 100))}_{int(round(AMP_HIGH * 100))}"
    return {
        "f1_mm": f1,
        "f2_mm": f2,
        "L_mm": L,
        "q_mm": q,
        "Sm_at_zero_per_mm": Sm0,
        f"range_lin_{lin_tag}_mm": range_linear,
        f"range_amp_{amp_tag}_mm": range_amp,
    }


def run_grid():
    return [compute_row(f1, f2) for f1 in F1_VALUES for f2 in F2_VALUES]


if __name__ == "__main__":
    print(
        f"Grid search over f1 and f2 (confocal.py), "
        f"L = f1+f2, r0={c.r0} mm, r_d={c.r_d} mm, I0={c.I0}"
    )
    print(
        f"Linear range: {LINEAR_LOW:.2f}*I0 to {LINEAR_HIGH:.2f}*I0  |  "
        f"Amplitude metric: {AMP_LOW:.2f}*I0 to {AMP_HIGH:.2f}*I0"
    )
    print()

    df = pd.DataFrame(run_grid())
    print(df.to_string(index=False, float_format=lambda x: f"{x:.5f}"))

    # Dutch Excel expects ; as column separator and , as decimal mark.
    df.to_csv(CSV_PATH, index=False, sep=";", decimal=",", float_format="%.5f")
    print(f"\nWrote {len(df)} rows to {CSV_PATH}")
