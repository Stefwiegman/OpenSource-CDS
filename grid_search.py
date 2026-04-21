"""Grid search over lens configurations to find the optimal confocal setup.

For each (f1, f2, r_d) combination computes:
  - hw50       : half-width at 50% intensity  (measurement range indicator)
  - hw95       : boundary of the flat top     (stay outside this)
  - bp_offset  : buigpunt offset from peak    (optimal working point)
  - det_offset : equivalent detector shift    (App. B alternative calibration)
  - sensitivity: max |dI/ddz1| at buigpunt   (higher = detect smaller motions)
  - usable_band: hw05 - hw95 per side         (full linear measurement window)

Two modes (set MODE below):
  "confocal" : L = f1 + f2 for every config  (theoretical comparison)
  "hardware" : L = SAMPLE_TO_F2 - f1, f2 fixed  (our actual rig constraint)

Sort column and top-N are configurable at the bottom of this file.

Run:  python grid_search.py
"""

import numpy as np
import matplotlib.pyplot as plt

from confocal import dz2_from_dz1, half_width, intensity_slope, peak_position

# ── Hardware constant ────────────────────────────────────────────────────────
SAMPLE_TO_F2 = 100.0   # mm: fixed distance sample -> f2 in our rig

# ── Fixed parameters ─────────────────────────────────────────────────────────
R0 = 8.0    # mm  laser beam radius at lens 1 (our setup: 0.8 cm)
Q  = 2.0    # mm  paper default (shifts peak to dz1 = q/2 in confocal case)
I0 = 1.0    # normalised source intensity

# ── Grid axes ────────────────────────────────────────────────────────────────
F1_VALUES = [5, 10, 15, 20, 25, 30, 40, 50]      # mm
F2_VALUES = [25, 50, 75, 100, 150]                # mm
RD_VALUES = [0.05, 0.1, 0.2, 0.3, 0.5, 1.0]      # mm

# ── Derived scale factors ────────────────────────────────────────────────────
def _hw_factor(frac):
    return float(np.sqrt(np.log(2) / np.log(1.0 / (1.0 - frac))))

HW95_FACTOR = _hw_factor(0.95)
HW05_FACTOR = _hw_factor(0.05)
BP_FACTOR   = float(np.sqrt(2.0 * np.log(2.0) / 3.0))   # buigpunt offset / hw50


# ── Core metrics function ────────────────────────────────────────────────────

def compute_metrics(f1, f2, r_d, mode="confocal"):
    """Return a dict of metrics for one (f1, f2, r_d) configuration."""
    L = (f1 + f2) if mode == "confocal" else (SAMPLE_TO_F2 - f1)
    confocal_flag = abs(L - (f1 + f2)) < 1e-9

    center  = peak_position(f1, f2, L, Q)
    hw50    = half_width(f1, f2, L, R0, Q, r_d)
    hw95    = hw50 * HW95_FACTOR
    hw05    = hw50 * HW05_FACTOR
    bp_off  = hw50 * BP_FACTOR

    dz1_wp  = center + bp_off
    sens    = abs(intensity_slope(dz1_wp, f1, f2, L, R0, Q, r_d, I0))
    det_off = abs(dz2_from_dz1(bp_off, f1, f2))
    usable  = hw05 - hw95

    return dict(
        f1=f1, f2=f2, r_d=r_d, L=round(L, 1),
        confocal=confocal_flag,
        hw50_mm=hw50,
        hw95_um=hw95 * 1e3,
        bp_mm=bp_off,
        det_mm=det_off,
        sens_per_mm=sens,
        usable_mm=usable,
    )


# ── Run grid ─────────────────────────────────────────────────────────────────

def run_grid(mode="confocal", sort_by="sens_per_mm", top_n=20, f2_fixed=None):
    """Run the full grid search and return sorted results.

    Args:
        mode      : "confocal" or "hardware"
        sort_by   : key to sort on (descending); options:
                      "sens_per_mm"  highest sensitivity first
                      "usable_mm"    widest usable range first
                      "hw50_mm"      widest 50%-range first
        top_n     : print only top N rows
        f2_fixed  : if given, only include this f2 value (mm)
    """
    f2_list = [f2_fixed] if f2_fixed else F2_VALUES
    f1_list = F1_VALUES

    results = []
    for f1 in f1_list:
        for f2 in f2_list:
            for r_d in RD_VALUES:
                try:
                    results.append(compute_metrics(f1, f2, r_d, mode=mode))
                except (ValueError, ZeroDivisionError):
                    pass

    results.sort(key=lambda r: r[sort_by], reverse=True)
    return results[:top_n] if top_n else results


def print_table(rows, title=""):
    """Print results as a formatted table."""
    cols = [
        ("f1",       "f1\n(mm)",          5,  "d"),
        ("f2",       "f2\n(mm)",          5,  "d"),
        ("r_d",      "r_d\n(mm)",         6,  ".2f"),
        ("L",        "L\n(mm)",           6,  ".0f"),
        ("hw50_mm",  "hw50\n(mm)",        9,  ".4f"),
        ("hw95_um",  "hw95\n(um)",        8,  ".1f"),
        ("bp_mm",    "buigpunt\n(mm)",   10,  ".4f"),
        ("det_mm",   "det-off\n(mm)",     9,  ".3f"),
        ("sens_per_mm", "sens\n(/mm)",   10,  ".4f"),
        ("usable_mm","usable/side\n(mm)",13,  ".4f"),
    ]

    if title:
        print(f"\n{'-'*80}")
        print(f"  {title}")
        print(f"{'-'*80}")

    # Header (two-line)
    line1 = "  ".join(h.split("\n")[0].rjust(w) for _, h, w, _ in cols)
    line2 = "  ".join(h.split("\n")[1].rjust(w) for _, h, w, _ in cols)
    sep   = "  ".join("-" * w for _, _, w, _ in cols)
    print(line1)
    print(line2)
    print(sep)

    for r in rows:
        cells = []
        for key, _, w, fmt in cols:
            val = r[key]
            if fmt == "d":
                cells.append(f"{int(val):>{w}d}")
            else:
                cells.append(f"{float(val):>{w}{fmt}}")
        print("  ".join(cells))
    print()


def plot_pareto(rows_all, highlight=None, filename="grid_pareto.png"):
    """Sensitivity vs usable-range trade-off (Pareto front)."""
    fig, ax = plt.subplots(figsize=(8, 5))

    # Group by r_d for colour coding
    rd_vals = sorted(set(r["r_d"] for r in rows_all))
    colors  = plt.cm.tab10(np.linspace(0, 0.9, len(rd_vals)))

    for r_d, color in zip(rd_vals, colors):
        sub = [r for r in rows_all if r["r_d"] == r_d]
        x   = [r["usable_mm"] * 1e3 for r in sub]   # µm
        y   = [r["sens_per_mm"] for r in sub]
        ax.scatter(x, y, color=color, alpha=0.7, s=30,
                   label=f"r_d = {r_d} mm")

    if highlight:
        xh = highlight["usable_mm"] * 1e3
        yh = highlight["sens_per_mm"]
        ax.scatter([xh], [yh], color="red", s=120, zorder=5,
                   marker="*", label=(
                       f"onze config  f1={highlight['f1']} f2={highlight['f2']} "
                       f"r_d={highlight['r_d']}"
                   ))

    ax.set_xlabel("Bruikbaar meetbereik per kant (um)  [hw05 - hw95]")
    ax.set_ylabel("|dI/ddz1| op buigpunt  (per mm)")
    ax.set_title("Pareto-front: gevoeligheid vs. meetbereik")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=8, loc="upper right")
    fig.tight_layout()
    fig.savefig(filename, dpi=150)
    print(f"  Pareto-plot saved: {filename}")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # ── Confocal grid (paper style) ──────────────────────────────────────────
    print("\n=== CONFOCAL GRID  (L = f1 + f2) ===")

    top_sens = run_grid(mode="confocal", sort_by="sens_per_mm", top_n=15)
    print_table(top_sens, "Top 15 - gesorteerd op gevoeligheid (hoogste eerst)")

    top_range = run_grid(mode="confocal", sort_by="usable_mm", top_n=15)
    print_table(top_range, "Top 15 - gesorteerd op bruikbaar bereik (breedste eerst)")

    # ── Hardware grid (our rig: L = 100 - f1, f2 = 50 mm fixed) ─────────────
    print("\n=== HARDWARE GRID  (L = 100 - f1, f2 = 50 mm vast) ===")

    top_hw_sens = run_grid(mode="hardware", sort_by="sens_per_mm",
                           top_n=15, f2_fixed=50)
    print_table(top_hw_sens, "Top 15 (hardware-constraint) - gevoeligheid")

    top_hw_range = run_grid(mode="hardware", sort_by="usable_mm",
                            top_n=15, f2_fixed=50)
    print_table(top_hw_range, "Top 15 (hardware-constraint) - bereik")

    # ── Pareto plot (confocal, all configs) ───────────────────────────────────
    all_confocal = run_grid(mode="confocal", top_n=None)
    our_config   = compute_metrics(f1=25, f2=50, r_d=0.2, mode="confocal")
    plot_pareto(all_confocal, highlight=our_config)

    plt.show()
