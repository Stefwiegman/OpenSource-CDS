"""Compare multiple lens configurations for multi-range operation.

Hardware constraint of onze opstelling: f2 en sample zitten mechanisch vast op
100 mm afstand. f1 wordt op een brandpuntsafstand voor de sample geplaatst, dus
L (afstand f1-f2) = 100 - f1. Alleen f1 = 25 mm levert dan een confocale
geometrie (L = f1 + f2 = 75); andere f1-waarden doen dat niet.

Scenario: swap f1 only - L = 100 - f1 schuift mee, f2 en aperture vast.
De gearceerde band is de *bruikbare* zone waar 0.05 <= I_m <= 0.95
(symmetrisch rond 50%). Binnen die band is er genoeg helling om dz1 terug
te rekenen zonder dat we te dicht op piek of op ruisvloer zitten.

Run:  python demo_ranges.py
"""

import numpy as np
import matplotlib.pyplot as plt

from confocal import half_width, intensity, peak_position


SAMPLE_TO_F2 = 100.0   # mm, vaste afstand sample -> f2 in onze opstelling

# Half-width op andere intensiteits-fractie schaalt als
#   hw_f = hw_50 * sqrt(ln 2 / ln(1/(1-f)))
# (want I_m = f  <->  r_det = r_d / sqrt(ln(1/(1-f))))
def _hw_factor(fraction):
    return float(np.sqrt(np.log(2) / np.log(1.0 / (1.0 - fraction))))


HW95_FACTOR = _hw_factor(0.95)   # ~ 0.481
HW05_FACTOR = _hw_factor(0.05)   # ~ 3.676

# Buigpunt (inflection point) van I_m(dz1): r_det = r_d * sqrt(2/3),
# I_m = 1 - exp(-3/2) ~ 0.7769, dz1-offset = sqrt(2*ln2/3) * hw50 ~ 0.680*hw50.
# Dit is waar |dI/ddz1| maximaal is EN de tweede afgeleide 0 is - dus lokaal
# meest lineair, beste werkpunt voor kleine-uitslag metingen.
BP_OFFSET_FACTOR = float(np.sqrt(2.0 * np.log(2.0) / 3.0))
BP_INTENSITY = float(1.0 - np.exp(-1.5))


def plot_configs(configs, title, filename, show_band=True):
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for label, params in configs.items():
        f1, f2, r_diaphragm = params["f1"], params["f2"], params["r_diaphragm"]
        L = params.get("L", SAMPLE_TO_F2 - f1)
        r0, q, I0 = 8.0, 2.0, 1.0   # r0 = 0.8 cm laserbundel op F1
        center = peak_position(f1, f2, L, q)
        hw = half_width(f1, f2, L, r0, q, r_diaphragm)
        hw95 = hw * HW95_FACTOR
        hw05 = hw * HW05_FACTOR
        bp_off = hw * BP_OFFSET_FACTOR
        x_min, x_max = center - 1.1 * hw05, center + 1.1 * hw05
        dz1 = np.linspace(x_min, x_max, 800)
        I_m = intensity(dz1, f1, f2, L, r0, q, r_diaphragm, I0)
        confocal = "confocaal" if abs(L - (f1 + f2)) < 1e-9 else "NIET-confocaal"
        (line,) = ax.plot(
            dz1,
            I_m,
            label=(
                f"{label}: f1={f1}mm, L={L:.0f}mm ({confocal}), "
                f"pinhole={r_diaphragm*1000:.0f}um  "
                f"(band=±[{hw95:.3f}..{hw05:.3f}]mm)"
            ),
        )
        if show_band:
            color = line.get_color()
            ax.axvspan(center - hw05, center - hw95, color=color, alpha=0.15, lw=0)
            ax.axvspan(center + hw95, center + hw05, color=color, alpha=0.15, lw=0)
            for x in (center - hw05, center - hw95, center + hw95, center + hw05):
                ax.axvline(x, color=color, linestyle="--", alpha=0.6, lw=1)
            # Buigpunt-markers op beide takken (werkpunten voor afstellen).
            ax.scatter(
                [center - bp_off, center + bp_off],
                [BP_INTENSITY, BP_INTENSITY],
                marker="*", s=140, color=color,
                edgecolor="black", linewidth=0.8, zorder=5,
            )
        print(
            f"  {label:18s}  L={L:5.1f}mm  peak={center:+.3f}mm  ({confocal})  "
            f"hw50=±{hw:.4f}mm  hw95=±{hw95:.4f}mm  hw05=±{hw05:.4f}mm  "
            f"buigpunt=±{bp_off:.4f}mm (werkpunten: "
            f"{center - bp_off:+.3f}, {center + bp_off:+.3f} mm)"
        )
    if show_band:
        ax.axhline(0.95, color="gray", linestyle=":", alpha=0.6, lw=1,
                   label="I_m = 0.95")
        ax.axhline(0.05, color="gray", linestyle=":", alpha=0.6, lw=1,
                   label="I_m = 0.05")
        ax.axhline(BP_INTENSITY, color="black", linestyle=":", alpha=0.5, lw=1,
                   label=f"buigpunt I_m = {BP_INTENSITY:.3f} (werkpunt *)")
    ax.set_xlabel("dz1 [mm]")
    ax.set_ylabel("I_m (normalized)")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8, loc="lower center")
    fig.tight_layout()
    fig.savefig(filename, dpi=150)
    print(f"  Saved: {filename}\n")


# --- Swap f1 only (f2=50 mm en sample-tot-f2 vast op 100 mm) ---
print(f"Scenario: swap f1 only (fixed f2=50mm, sample-tot-f2={SAMPLE_TO_F2}mm)")
print("L = sample_to_f2 - f1, dus L verandert mee. Niet altijd confocaal.\n")
configs_f1_only = {
    "short f1 (15mm)": {"f1": 15.0, "f2": 50.0, "r_diaphragm": 0.2},
    "our f1 (25mm)":   {"f1": 25.0, "f2": 50.0, "r_diaphragm": 0.2},
    "long f1 (50mm)":  {"f1": 50.0, "f2": 50.0, "r_diaphragm": 0.2},
}
plot_configs(
    configs_f1_only,
    "Swap f1 only - bruikbare band 5%-95%, * = buigpunt werkpunt",
    "ranges_f1_only.png",
    show_band=True,
)

plt.show()
