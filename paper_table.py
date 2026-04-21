"""Paper-style tabel per meetbereik over alle (f1, f2) combinaties.

Per meetbereik (1 mm en 1 um):
  - f1 en f2 varieren onafhankelijk van 2 cm t/m 15 cm in stapjes van 0.5 cm
  - confocale setup: L = f1 + f2 (aanname)
  - r_d wordt per combinatie zo gekozen dat hw50 = meetbereik
  - kolommen: f1, f2, r_d (benodigde pinhole), offset (det-side),
              sensitivity (bij buigpunt), linear range (2*(hw05-hw95))

Conventies in dit script:
  - "meetbereik" = hw50 = afstand van piek waarop intensiteit naar 50% zakt.
    Dus meetbereik=1 mm betekent: +/- 1 mm vanaf focus brengt I_m van 100%
    naar 50%.
  - "linear range" = 2*(hw05 - hw95) = volledige bruikbare band waarin
    0.05 <= I_m <= 0.95 (symmetrisch rond piek, beide zijden samen).
  - "offset" = det_off = buigpunt-offset aan de detectorzijde,
    via dz2 = 2 * bp_off * (f2/f1)^2.

Belangrijke fysische observatie (uit het model):
  In confocale mode met q=2 vallen de f1-termen weg in r_det omdat A = 2*f1^2.
  Daardoor hangen hw50 en sensitivity uitsluitend van (r_d, f2) af. Na het
  vastpinnen van meetbereik (=hw50) zijn sensitivity en linear range dus
  *constanten* per meetbereik. Enkel r_d (hangt van f2 af om hw50 op target
  te krijgen) en offset (hangt van f1 en f2 af) verschillen per (f1, f2).

Run:  python paper_table.py
"""

import csv
import numpy as np

from confocal import (
    dz2_from_dz1,
    half_width,
    intensity_slope,
    peak_position,
)

# ── Vaste parameters ─────────────────────────────────────────────────────────
R0 = 8.0    # mm  laserbundel-straal bij lens 1
Q  = 2.0    # mm  paper-default (piek op dz1 = q/2 = 1 mm)
I0 = 1.0    # genormaliseerde intensiteit

# ── Grid-assen ───────────────────────────────────────────────────────────────
# 2 cm t/m 15 cm in stapjes van 0.5 cm  -> 20 mm t/m 150 mm in stapjes van 5 mm
F_VALUES_MM = np.arange(20.0, 155.0, 5.0)

# ── Meetbereiken ─────────────────────────────────────────────────────────────
#   T = hw50 (half-width at half max).
#   Voor elk (f1, f2) lossen we r_d op zodat hw50 = T.
MEETBEREIKEN_MM = [
    ("1 mm",   1.0),
    ("1 um",   1e-3),
]

# ── Afgeleide factoren ───────────────────────────────────────────────────────
def _hw_factor(fraction):
    return float(np.sqrt(np.log(2.0) / np.log(1.0 / (1.0 - fraction))))

HW95_FACTOR = _hw_factor(0.95)   # ~ 0.481
HW05_FACTOR = _hw_factor(0.05)   # ~ 3.676
BP_FACTOR   = float(np.sqrt(2.0 * np.log(2.0) / 3.0))   # ~ 0.680


# ── Kern ─────────────────────────────────────────────────────────────────────

def required_rd(target_hw50, f2, r0=R0):
    """r_d zodat hw50 = target_hw50 in confocale mode.

    Confocale afleiding (L = f1+f2, q=2 => A = 2*f1^2):
        hw50 = r_d * f2 / (2 * r0 * sqrt(ln 2))
    dus:
        r_d  = hw50 * 2 * r0 * sqrt(ln 2) / f2
    """
    return target_hw50 * 2.0 * r0 * np.sqrt(np.log(2.0)) / f2


def row_for(f1, f2, target_hw50, r0=R0, q=Q, I0_val=I0):
    L = f1 + f2
    r_d = required_rd(target_hw50, f2, r0=r0)

    # Verifieer via de "echte" helpers (voor numerieke consistentie)
    hw50 = half_width(f1, f2, L, r0, q, r_d)
    bp_off = hw50 * BP_FACTOR
    center = peak_position(f1, f2, L, q)
    dz1_wp = center + bp_off

    sens    = abs(intensity_slope(dz1_wp, f1, f2, L, r0, q, r_d, I0_val))
    det_off = abs(dz2_from_dz1(bp_off, f1, f2))
    lin_range = 2.0 * hw50 * (HW05_FACTOR - HW95_FACTOR)

    return {
        "f1_cm":      f1 / 10.0,
        "f2_cm":      f2 / 10.0,
        "r_d_um":     r_d * 1000.0,
        "offset_mm":  det_off,
        "sens_per_mm": sens,
        "linear_mm":  lin_range,
    }


def build_table(target_hw50_mm):
    rows = []
    for f1 in F_VALUES_MM:
        for f2 in F_VALUES_MM:
            rows.append(row_for(f1, f2, target_hw50_mm))
    return rows


# ── Printen ──────────────────────────────────────────────────────────────────

def print_header(label, T):
    print(f"\n{'='*86}")
    print(f"  Meetbereik (hw50) = {label}    (L = f1 + f2, q = 2 mm, r0 = 8 mm)")
    print(f"{'='*86}")
    # Sens en lin.range hangen in confocale mode alleen van T af; probe een
    # willekeurige (f1, f2) om exacte numerieke waarden te laten zien.
    probe = row_for(f1=50.0, f2=50.0, target_hw50=T)
    print(f"  -> sensitivity (bij buigpunt, constant over alle f1,f2): "
          f"{probe['sens_per_mm']:.4g} per mm")
    print(f"  -> linear range  (2*(hw05-hw95), constant over alle f1,f2): "
          f"{probe['linear_mm']:.4g} mm")
    print(f"  -> offset varieert per (f1, f2) -> zie tabel onder.")
    print(f"{'-'*86}")


def print_long_table(rows):
    print(f"{'f1(cm)':>7} {'f2(cm)':>7} {'r_d(um)':>11} "
          f"{'offset(mm)':>13} {'sens(/mm)':>12} {'lin.range(mm)':>15}")
    print("-" * 86)
    last_f1 = None
    for r in rows:
        # dunne witregel tussen f1-blokken
        if last_f1 is not None and r["f1_cm"] != last_f1:
            print()
        last_f1 = r["f1_cm"]
        # voor extreme r_d (< 0.01 um of > 10 mm) markeer onrealistisch
        warn = ""
        if r["r_d_um"] < 0.01:
            warn = "  [r_d < 10 nm: niet fabriceerbaar]"
        elif r["r_d_um"] > 10_000:
            warn = "  [r_d > 10 mm: geen pinhole]"
        print(f"{r['f1_cm']:>7.1f} {r['f2_cm']:>7.1f} {r['r_d_um']:>11.4g} "
              f"{r['offset_mm']:>13.4g} {r['sens_per_mm']:>12.4g} "
              f"{r['linear_mm']:>15.4g}{warn}")


def save_csv(rows, filename, T_label):
    with open(filename, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["meetbereik(hw50)", "f1(cm)", "f2(cm)", "r_d(um)",
                    "offset(mm)", "sens(/mm)", "linear_range(mm)"])
        for r in rows:
            w.writerow([
                T_label,
                f"{r['f1_cm']:.1f}",
                f"{r['f2_cm']:.1f}",
                f"{r['r_d_um']:.6g}",
                f"{r['offset_mm']:.6g}",
                f"{r['sens_per_mm']:.6g}",
                f"{r['linear_mm']:.6g}",
            ])
    print(f"\n  CSV opgeslagen: {filename}  ({len(rows)} rijen)")


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\nPaper-style tabel per meetbereik.")
    print(f"f1 en f2 lopen elk van {F_VALUES_MM[0]/10:.1f} cm tot "
          f"{F_VALUES_MM[-1]/10:.1f} cm in stapjes van "
          f"{(F_VALUES_MM[1]-F_VALUES_MM[0])/10:.1f} cm  "
          f"({len(F_VALUES_MM)} waarden, {len(F_VALUES_MM)**2} combinaties per "
          f"meetbereik).")

    for label, T in MEETBEREIKEN_MM:
        rows = build_table(T)
        print_header(label, T)
        print_long_table(rows)
        fname = f"paper_table_{label.replace(' ', '').replace('.', 'p')}.csv"
        save_csv(rows, fname, label)

    print()
