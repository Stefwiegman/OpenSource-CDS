# SPDX-License-Identifier: MIT

"""Overlay-figuur voor de paper: alle metingen (16..80 mm) in een assenstelsel.

Voor elk meetbestand wordt dezelfde "prediction" gedraaid als in de UI
(ml.fit_confocal leert q en r0, ml.Im_func is het A6 forward-model). Alleen de
gefitte curves worden getekend (geen meetpunten), per brandpuntsafstand f1 een
eigen kleur. Elke curve wordt om zijn eigen top heen gecentreerd op x = 0 en
over de volle breedte van de x-as getekend, zodat je de breedtes direct
vergelijkt. Eindresultaat: een enkele PNG (assets/overlay_predictions.png).

De f1-waarde komt uit de bestandsnaam (zelfde conventie als ml.py __main__).
Stand-alone: `python paper_overlay.py`.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import ml


# --- Meetbestanden: f1 (mm) -> pad. f1 is fysiek de breedte-bepalende factor. ---
ROOT = Path(__file__).resolve().parent
FILES: dict[float, str] = {
    16.0: "metingen 16 mm.xlsx",
    25.0: "Metingen 25 mm.xlsx",
    40.0: "metingen 40mm.xlsx",
    60.0: "Metingen 60 mm.xlsx",
    80.0: "metingen 80mm.xlsx",
}

OUT_PATH = ROOT / "assets" / "overlay_predictions.png"

# Halve breedte van de x-as (mm). Elke curve loopt van -XLIM tot +XLIM, dus tot
# aan beide randen van het assenstelsel. Groter = meer van de brede curves (60/80
# mm) zichtbaar, maar de smalle (16 mm) wordt dan een dunne piek.
XLIM_MM = 10.0


def peak_dz1(res: "ml.FitResult", f1: float) -> float:
    """dz1 waar de confocale top zit (rdet = 0, daar geldt I_m = I0).

    Het A6-model is symmetrisch rond dit punt, dus dit is exact het midden van de
    top. Analytisch i.p.v. argmax, want bij verzadigde curves is de top een vlak
    plateau waar argmax zou zweven.
    """
    return res.q * f1**2 / (2.0 * (res.q * (f1 + res.f2 - res.L) + res.f2**2))


def _load_xy(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Lees (dz1, I_m) uit een Excel met twee kolommen, zonder header.

    Spiegelt het inlezen in ml.py __main__: kolom 0 = dz1 (mm), kolom 1 = I_m (V).
    """
    data = pd.read_excel(path, header=None)
    dz1 = np.asarray(data[0].tolist(), dtype=float)
    Im = np.asarray(data[1].tolist(), dtype=float)
    mask = np.isfinite(dz1) & np.isfinite(Im)
    return dz1[mask], Im[mask]


def main() -> None:
    # Een kleur per f1 uit een sequentiele colormap: lage f1 donker, hoge f1 licht.
    f1_values = sorted(FILES)
    colors = plt.cm.viridis(np.linspace(0.0, 0.85, len(f1_values)))

    fig, ax = plt.subplots(figsize=(8.5, 5.5))

    # Gedeelde x-as (gecentreerde coordinaat x' = dz1 - top): elke curve loopt
    # van rand tot rand.
    x_plot = np.linspace(-XLIM_MM, XLIM_MM, 800)

    for f1, color in zip(f1_values, colors):
        path = ROOT / FILES[f1]
        dz1, Im = _load_xy(path)

        # Zelfde "prediction" als de UI: fit q en r0 op de meetpunten.
        res = ml.fit_confocal(dz1, Im, f1=f1)

        # Top op x = 0 leggen: evalueer het model op dz1 = x' + top.
        top = peak_dz1(res, f1)
        with np.errstate(divide="ignore", invalid="ignore"):
            y_fit = ml.Im_func(
                x_plot + top, res.q, res.r0, f1, res.f2, res.L, res.r_d, res.I0
            )

        ax.plot(x_plot, y_fit, color=color, lw=2.0,
                label=f"f1 = {f1:.0f} mm")

        print(f"[f1={f1:.0f} mm] q={res.q:.3f}  r0={res.r0:.3f}  "
              f"I0={res.I0:.3f} V  top@dz1={top:.2f} mm  R²={res.R2:.4f}")

    ax.set_xlim(-XLIM_MM, XLIM_MM)
    ax.set_xlabel("Axial displacement relative to peak (mm)")
    ax.set_ylabel("Measured intensity I_m (V)")
    ax.set_title("Confocal response across focal lengths (16–80 mm), peaks aligned at 0")
    ax.grid(True, alpha=0.3)
    ax.legend(title="Measurement / fit", framealpha=0.9)
    fig.tight_layout()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_PATH, dpi=300)
    print(f"\nSaved overlay -> {OUT_PATH}")
    plt.show()


if __name__ == "__main__":
    main()
