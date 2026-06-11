# SPDX-License-Identifier: MIT

"""Overlay-figuur van de trillingsspectra per motorsnelheid.

Leest de Moku:Go Spectrum Analyzer exports uit spectra/ (een CSV per
stappenmotor-snelheid) en legt ze in een assenstelsel: amplitude (Vpp)
verticaal, frequentie (Hz) horizontaal. Zo zie je per snelheid waar de
trillingslijnen zitten en hoe ze met de snelheid mee opschuiven.

De snelheid komt uit de bestandsnaam ("snelheid 200.csv" -> 200). Het
Moku-CSV-formaat heeft een %-commentaarblok als header en daarna twee
kolommen: Frequency (Hz), Input 1 (Vpp).

Stand-alone: `python spectra_overlay.py`. Resultaat: assets/spectra_overlay.png.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.transforms as mtransforms
from scipy.signal import find_peaks

ROOT = Path(__file__).resolve().parent
SPECTRA_DIR = ROOT / "spectra"
OUT_PATH = ROOT / "assets" / "spectra_overlay.png"

# Onder deze frequentie zit de DC/window-skirt van de analyzer (~0.02 Vpp),
# geen echte trilling. We tekenen vanaf hier zodat de motorlijnen de schaal
# bepalen en niet die randpiek.
F_MIN_HZ = 8.0

# Piekdetectie met absolute drempels, zodat alleen de duidelijke trillingslijnen
# gelabeld worden:
#  - onder MIN_PEAK_FREQ_HZ zit laagfrequente rommel (sub-harmonischen, drift);
#  - onder MIN_PEAK_AMP_UVPP zijn het kleine bobbels in de ruisvloer.
MIN_PEAK_FREQ_HZ = 50.0
MIN_PEAK_AMP_UVPP = 120.0
PEAK_PROMINENCE_UVPP = 50.0


def _speed_from_name(path: Path) -> int:
    """Haal de snelheid (stappen/s) uit de bestandsnaam, bv. 'snelheid 200'."""
    m = re.search(r"(\d+)", path.stem)
    return int(m.group(1)) if m else -1


def _load_spectrum(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Lees (frequentie Hz, amplitude Vpp) uit een Moku-export.

    Het %-teken markeert de headerregels; loadtxt slaat die over en leest de
    twee data-kolommen in een keer in.
    """
    data = np.loadtxt(path, comments="%", delimiter=",")
    return data[:, 0], data[:, 1]


def main() -> None:
    files = sorted(SPECTRA_DIR.glob("*.csv"), key=_speed_from_name)
    if not files:
        raise SystemExit(f"Geen CSV's gevonden in {SPECTRA_DIR}")

    speeds = [_speed_from_name(f) for f in files]
    # Een kleur per snelheid: laag donker, hoog licht (zelfde idee als paper_overlay).
    colors = plt.cm.viridis(np.linspace(0.0, 0.85, len(files)))

    fig, ax = plt.subplots(figsize=(9.0, 5.5))

    # Hz-labels op x-niveau: x in data-coordinaten (op de piek), y in as-fractie
    # (vast net boven de x-as), zodat ze niet meeschalen met de amplitude.
    label_tf = mtransforms.blended_transform_factory(ax.transData, ax.transAxes)

    for path, speed, color in zip(files, speeds, colors):
        freq, vpp = _load_spectrum(path)
        mask = freq >= F_MIN_HZ
        freq, vpp = freq[mask], vpp[mask]
        # Amplitude in micro-Vpp (1 Vpp = 1e6 uVpp).
        amp = vpp * 1e6

        ax.plot(freq, amp, color=color, lw=1.2, alpha=0.85,
                label=f"{speed} stappen/s")

        # Pieken zoeken met absolute drempels, daarna de laagfrequente rommel
        # onder MIN_PEAK_FREQ_HZ eruit filteren.
        peaks, _ = find_peaks(
            amp,
            height=MIN_PEAK_AMP_UVPP,
            prominence=PEAK_PROMINENCE_UVPP,
        )
        peaks = peaks[freq[peaks] >= MIN_PEAK_FREQ_HZ]
        for idx in peaks:
            f_peak = freq[idx]
            # Verticale stippellijn door de piek, in de kleur van deze snelheid.
            ax.axvline(f_peak, color=color, ls=":", lw=1.0, alpha=0.7, zorder=1)
            # Frequentie als verticaal label onder de x-as (clip_on uit zodat het
            # buiten het assenstelsel mag staan).
            ax.text(f_peak, -0.06, f"{f_peak:.0f} Hz", transform=label_tf,
                    color=color, fontsize=8, rotation=90,
                    ha="center", va="top", zorder=4, clip_on=False)

        peak_str = ", ".join(f"{freq[i]:.0f} Hz ({amp[i]:.0f} uVpp)"
                             for i in peaks)
        print(f"[{speed} stappen/s] pieken: {peak_str or 'geen'}")

    ax.set_xlim(F_MIN_HZ, 500.0)
    ax.set_ylim(bottom=0.0)
    ax.set_xlabel("Frequentie (Hz)")
    ax.set_ylabel("Amplitude (µVpp)")
    ax.set_title("Trillingsspectrum per motorsnelheid (overlay)")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(title="Motorsnelheid", framealpha=0.9)
    fig.tight_layout()
    # Extra ruimte onderaan voor de Hz-labels die onder de x-as staan.
    fig.subplots_adjust(bottom=0.20)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_PATH, dpi=300)
    print(f"Saved overlay -> {OUT_PATH}")
    plt.show()


if __name__ == "__main__":
    main()
