# Confocal Displacement Sensing — Python model

Python-model voor ons BEP (PME-2026-A06). Rekent uit wat de intensiteit op de
photodetector wordt voor een gegeven verplaatsing van de sample (forward), en
rekent omgekeerd uit welke verplaatsing bij een gemeten intensiteit hoort
(inverse).

## Wat zit erin

| Bestand | Doel |
|---|---|
| `confocal.py` | Core module — A5/A6, analytische inverse, slope, ruis, richtings-inverse, module-presets |
| `analysis.py` | FFT-spectrum + dominant-frequency voor trillingsanalyse |
| `calibration.py` | `scipy.optimize.least_squares` fit voor onbekende systeem-parameters |
| `config.py` | YAML load/save van een parameter-config |
| `hardware.py` | Abstracte `Stage`/`Detector` + `MockStage`/`MockDetector` |
| `sweep.py` | CLI sweep die met Mock-hardware een CSV schrijft |
| `demo.py` | Basis-demo: sweep, plot, round-trip test voor één lens-config |
| `demo_ranges.py` | Vergelijking van meerdere lens/pinhole configuraties |
| `tests/` | pytest regressiesuite (17 tests) |
| `requirements.txt` | `numpy`, `matplotlib`, `scipy`, `pyyaml`, `pytest` |
| `intensity_curve.png` | Output van `demo.py` |
| `ranges_f1_only.png`, `ranges_matched.png` | Output van `demo_ranges.py` |

## Installeren en draaien

```bash
pip install -r requirements.txt
python demo.py          # basis: één config, sweep + round-trip
python demo_ranges.py   # vergelijking van drie bereiken
python sweep.py         # mock-sweep -> sweep_output.csv
pytest tests/           # regressiesuite
```

## Formules (uit het paper, appendix A)

**A5** — straal van de lichtvlek op de detector:

```
r_det = r0 · (−2·L·dz1·q + 2·dz1·f1·q + 2·dz1·f1² + 2·dz1·f2·q − f1²·q) / (f1² · f2)
```

**A6** — intensiteit die door het pinhole op de detector komt:

```
I_m = I0 · (1 − exp(−r_diaphragm² / r_det²))
```

Parameters:
- `dz1` — verplaatsing van de sample (wat we willen meten)
- `f1`, `f2` — brandpuntsafstanden van de twee lenzen (f1 = dichtst bij sample)
- `L` — afstand tussen de lenzen (`L = f1 + f2` voor confocale geometrie)
- `r0` — straal van de laserbundel bij de eerste lens
- `q` — object-side aperture parameter
- `r_diaphragm` — straal van het pinhole vóór de detector
- `I0` — intensiteit van de laser

Alle lengtes in **millimeter**, intensiteit genormaliseerd op `I0 = 1`.

## Hoe de functies te gebruiken

```python
from confocal import intensity, invert_intensity

# Forward: verplaatsing -> intensiteit
I = intensity(dz1=1.5, f1=50, f2=100, L=150,
              r0=1.0, q=2.0, r_diaphragm=0.1, I0=1.0)

# Inverse: gemeten intensiteit -> twee mogelijke verplaatsingen
dz1_plus, dz1_minus = invert_intensity(
    I_m=0.3, f1=50, f2=100, L=150,
    r0=1.0, q=2.0, r_diaphragm=0.1, I0=1.0,
)
```

`dz1` mag ook een NumPy array zijn — dan krijg je een heel intensiteitsprofiel
in één keer (handig voor plotten).

### Teken-ambiguïteit van de inverse

I_m hangt alleen af van `r_det²` en is dus even in dz1 rond het piek-punt. Voor
één gemeten intensiteit zijn er **twee** mogelijke verplaatsingen, symmetrisch
rond het piek-punt. `invert_intensity` geeft ze allebei terug. De fysische
oplossing kies je op basis van:

- bekende bewegingsrichting van de sample, of
- een tweede meting bij een iets verschoven positie.

## Belangrijkste fysische inzicht (uit `demo_ranges.py`)

In confocale setup (L = f1+f2) vereenvoudigt A5 tot:

```
r_det = r0 · (2·dz1 − q) / f2
```

Dit bevat **geen f1**. Consequentie: volgens het paper-model geeft alleen de
sample-side lens (f1) wisselen **geen verschillend meetbereik**. De half-max
breedte van de respons-curve schaalt als `r_diaphragm · f2 / r0`.

Concrete getallen (f2 = 100 mm, pinhole = 100 µm, r0 = 1 mm):

| f1 | half-width |
|---|---|
| 25 mm | ±6.01 mm |
| 50 mm | ±6.01 mm |
| 100 mm | ±6.01 mm |

Om wél verschillende bereiken te krijgen moeten we **module-paren** ontwerpen
(objectieflens + bijpassend pinhole, eventueel ook andere f2). `demo_ranges.py`
laat dat zien:

| Module | f1 | pinhole | half-width |
|---|---|---|---|
| fine | 25 mm | 10 µm | ±0.6 mm |
| medium | 50 mm | 100 µm | ±6 mm |
| coarse | 100 mm | 500 µm | ±30 mm |

**Let op:** de paper-formule is een ray-optics benadering. In werkelijkheid zit
er ook diffractie in (depth-of-focus schaalt met f1²) die dit model niet vangt,
dus in de praktijk doet f1 wél iets voor de laterale spot-grootte. We moeten
nog bepalen hoe groot dat effect is voor onze opstelling.

De module-parameters zijn nu ook hergebruikbaar beschikbaar als
`MODULE_FINE`, `MODULE_MEDIUM`, `MODULE_COARSE` in [confocal.py](confocal.py).

## Ruis en onzekerheid

`confocal.add_noise` voegt shot-ruis (σ schaalt met √I) en lees-ruis
(constante σ) toe aan een gemeten intensiteit. `confocal.inverse_uncertainty`
propageert een σ_I naar een σ_dz1 via de analytische helling ∂I/∂dz1
(`intensity_slope`), geëvalueerd op beide inverse-takken:

```python
from confocal import MODULE_MEDIUM, inverse_uncertainty, add_noise

sig_plus, sig_minus = inverse_uncertainty(I_m=0.4, sigma_I=1e-3, **MODULE_MEDIUM)
# -> σ_dz1 in mm voor elk van de twee mogelijke dz1-oplossingen

I_noisy = add_noise(0.5, sigma_shot=0.01, sigma_read=0.005)
```

Bij het piek-punt (I_m → I0) gaat de helling naar nul en explodeert de
onzekerheid — meet dus bij voorkeur op de flanken, niet op de top.

## Richtings-bewuste inverse

Omdat de inverse twee oplossingen geeft, voegt `directional_inverse` een
eenduidige keuze toe op basis van bekende context:

```python
from confocal import MODULE_MEDIUM, directional_inverse

# Weet dat de sample "omhoog" beweegt vanaf het piek-punt:
dz1 = directional_inverse(I_m=0.4, direction="up", **MODULE_MEDIUM)

# Of: neem de oplossing die het dichtst bij de vorige meting ligt (tracking):
dz1 = directional_inverse(I_m=0.4, previous_dz1=5.2, **MODULE_MEDIUM)
```

## Hardware-pijplijn (Mock)

`hardware.py` definieert abstracte klassen `Stage` en `Detector`, plus
`MockStage`/`MockDetector` die intern de forward-functie aanroepen. Zo kan
de hele meetpijplijn end-to-end getest worden zonder fysieke opstelling.
Echte drivers (stepper/ADC) komen in Fase 3 als concrete subclasses.

`sweep.py` koppelt een stage + detector aan een positie-range en schrijft
de resultaten naar een CSV:

```bash
python sweep.py                          # MODULE_MEDIUM, 500 punten
python sweep.py --config my_rig.yaml     # eigen YAML-config
python sweep.py --sigma-read 0.005       # met gesimuleerde lees-ruis
```

YAML-configs worden geladen via [config.py](config.py) — één dict met de
keys `f1, f2, L, r0, q, r_diaphragm, I0`.

## Kalibratie

Onbekende parameters (bv. de echte `r_diaphragm`, `r0`, of `q` van onze
opstelling) kunnen uit een gemeten curve worden teruggerekend met
`calibration.fit_parameters` (scipy non-linear least squares):

```python
from calibration import fit_parameters

fitted, residuals, result = fit_parameters(
    dz1_measured, I_m_measured,
    known_params={"f1": 50, "f2": 100, "L": 150, "r0": 1.0, "q": 2.0, "I0": 1.0},
    free_params=["r_diaphragm"],
    initial_guess={"r_diaphragm": 0.05},
)
print(fitted["r_diaphragm"])  # in mm
```

De testsuite verifieert dat de fit op synthetische ruis-vrije data de exacte
input-parameter terugvindt (tolerantie 1e-6).

## Trillingsanalyse

Met een tijdreeks van teruggerekende dz1-waardes levert `analysis.py` het
amplitude-spectrum:

```python
from analysis import vibration_spectrum, dominant_frequency

freqs, amps = vibration_spectrum(dz1_series, sample_rate=1000.0)
f_peak = dominant_frequency(dz1_series, sample_rate=1000.0)
```

## Benchmark

Indicatieve tijden op Windows 11 / Python 3.11 / laptop-CPU:

| Operatie | Tijd |
|---|---|
| `intensity(scalar, ...)` | ~4.5 µs |
| `intensity(array_10k, ...)` | ~0.1 ms |
| `invert_intensity(...)` | ~2 µs |
| 500-stappen Mock-sweep | ~2.5 ms |

Reproduceerbaar via `python -c "import timeit; ..."` constructies zoals die
gebruikt zijn voor deze tabel — zie de commit-geschiedenis van deze sectie.

## Sanity checks

`demo.py` controleert dat:
- Round-trip dz1 → I_m → dz1 klopt tot floating-point precisie (~1e-15 mm)
- A5 (volledig) geeft hetzelfde als de vereenvoudigde vorm voor L = f1+f2
- Bij dz1 = q/2 is r_det = 0 en I_m = I0 (perfecte focus op pinhole)

## Status en TODO

**Af:**
- Forward/inverse model werkt en is geverifieerd
- Multi-range vergelijking gemaakt en het "f1 alleen wisselen"-inzicht gevonden
- Demo scripts met plots
- Module-presets (`MODULE_FINE/MEDIUM/COARSE`) centraal in `confocal.py`
- Ruis-model (`add_noise`) + analytische onzekerheidspropagatie (`inverse_uncertainty`)
- Richtings-bewuste inverse (`directional_inverse`) voor tracking
- YAML-configs (`config.py`)
- Hardware-abstractie + Mock-implementatie voor end-to-end pipeline test
- Automatische sweep-to-CSV (`sweep.py`)
- Kalibratie van onbekende parameters via scipy least-squares (`calibration.py`)
- FFT-trillingsanalyse (`analysis.py`)
- Pytest regressiesuite (17 tests)

**Nog te doen:**
- Echte parameter-waardes bepalen uit onze lens-keuze (laser bundel r0, aperture q)
- Echte hardware-drivers implementeren als concrete `Stage`/`Detector` subclasses (Fase 3)
- Validatie tegen echte metingen (Fase 2–4 van het primaire onderzoek)
- Diffractie-correctie op het ray-optics model (depth-of-focus ∝ f1²)


