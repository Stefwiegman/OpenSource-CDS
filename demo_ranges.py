"""Compare multiple lens configurations for multi-range operation.

Two scenarios:
  1. Swap f1 only (keep f2, pinhole, L = f1+f2 adapts).
     -> Paper model A5/A6 predicts SAME sensitivity regardless of f1.

  2. Swap f1 + matched pinhole together (realistic "swappable module").
     -> Gives genuinely different ranges.

Run:  python demo_ranges.py
"""

import numpy as np
import matplotlib.pyplot as plt

from confocal import half_width, intensity, peak_position


def plot_configs(configs, title, filename):
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for label, params in configs.items():
        f1, f2, r_diaphragm = params["f1"], params["f2"], params["r_diaphragm"]
        L = f1 + f2
        r0, q, I0 = 1.0, 2.0, 1.0
        center = peak_position(f1, f2, L, q)
        hw = half_width(f1, f2, L, r0, q, r_diaphragm)
        dz1 = np.linspace(center - 4 * hw, center + 4 * hw, 500)
        I_m = intensity(dz1, f1, f2, L, r0, q, r_diaphragm, I0)
        ax.plot(
            dz1,
            I_m,
            label=f"{label}: f1={f1}mm, pinhole={r_diaphragm*1000:.0f}um  "
            f"(hw=\u00b1{hw:.3f}mm)",
        )
        print(f"  {label:12s}  peak={center:.3f}mm   half-width=\u00b1{hw:.4f}mm")
    ax.set_xlabel("dz1 [mm]")
    ax.set_ylabel("I_m (normalized)")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(filename, dpi=150)
    print(f"  Saved: {filename}\n")


# --- Scenario 1: swap f1 only ---
print("Scenario 1: swap f1 only (fixed f2=100mm, pinhole=100um)")
print("Expectation per paper model: half-width barely changes.\n")
configs_f1_only = {
    "short f1": {"f1": 25.0, "f2": 100.0, "r_diaphragm": 0.1},
    "medium f1": {"f1": 50.0, "f2": 100.0, "r_diaphragm": 0.1},
    "long f1": {"f1": 100.0, "f2": 100.0, "r_diaphragm": 0.1},
}
plot_configs(
    configs_f1_only,
    "Swap f1 only (fixed f2, fixed pinhole)",
    "ranges_f1_only.png",
)

# --- Scenario 2: swap f1 + matched pinhole (realistic multi-range module) ---
print("Scenario 2: swap f1 + matched pinhole together")
print("Expectation: three genuinely different measurement ranges.\n")
configs_matched = {
    "fine (um-mm)": {"f1": 25.0, "f2": 100.0, "r_diaphragm": 0.01},
    "medium (mm)": {"f1": 50.0, "f2": 100.0, "r_diaphragm": 0.1},
    "coarse (cm)": {"f1": 100.0, "f2": 100.0, "r_diaphragm": 0.5},
}
plot_configs(
    configs_matched,
    "Swap f1 + matched pinhole (realistic multi-range design)",
    "ranges_matched.png",
)

plt.show()
