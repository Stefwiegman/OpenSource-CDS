# Paper Knowledge Base

Interne kennisbank voor het schrijven van de wetenschappelijke paper over de confocale
verplaatsingssensor. Alle getallen hieronder zijn rechtstreeks uit de code en de meetdata
gehaald (met `file:regel`-referenties). Waarden die nog geverifieerd of nagemeten moeten
worden staan expliciet gemarkeerd onder "Nog te verifieren".

Project: TU Delft WBMT3BEP, projectcode PME-2026-A06. Inlevering 12 juni 2026.
Team: Dafne Gyselinck, Jayden Jhagru, Harmen Klerk, Ties van Lohuizen, Stef Wiegman.
Begeleiders: Ruben Guis, Gerard Verbiest.

---

## 0. Eennregel-samenvatting per outline-sectie

| Sectie | Kernboodschap | Belangrijkste bronnen |
|---|---|---|
| Introduction | Commerciele confocale verplaatsingssensoren zijn duur; wij bouwen een betaalbare bolt-on op de OpenFlexure Block Stage met Moku:Go als detector | `README.md`, projecthub |
| Theory | Formule A6: intensiteit door pinhole daalt als sample axiaal uit focus beweegt | `confocal.py` |
| Methods | OpenFlexure stage + 3x stepper + confocale optische toren + Moku:Go + PySide6-software | `ui.py`, `scan.py`, `recording.py`, `firmware.ino` |
| Results | Axiale focuscurves bij f1 = 25/40/60 mm gefit op A6 (R^2 = 0.92 tot 0.99); burst+FFT-pipeline werkt | `*.xlsx`, `*mm.png`, `data/` |
| Discussion | Principe werkt en model klopt qua vorm, maar gefitte r0/q wijken af van theorie; geen step->mm-kalibratie; actuatoren te grof voor sub-micron | `calibration.yaml`, fit-resultaten |
| Conclusion | Aangetoond dat een laagdrempelig confocaal meetprincipe meetbaar is; sub-micron en volledige MEMS-mapping vereisen kalibratie en betere actuatie | alles |

---

## 1. Introduction (0.5 pagina)

**Probleem.** Confocale verplaatsingssensoren meten zeer kleine axiale (Z) verplaatsingen
optisch en contactloos, maar commerciele systemen zijn duur en daardoor slecht toegankelijk
voor academische en kleine labs.

**Wat is er al.**
- Confocale verplaatsingsmeting is een gevestigd commercieel principe (referenties nog toe te voegen).
- De **OpenFlexure Block Stage** (open hardware, CC BY-SA 4.0, https://openflexure.org/projects/blockstage/)
  levert een sub-micron herhaalbare 3-assige flexure-stage. Wij gebruiken deze **ongewijzigd**
  als basis (`README.md:200-218`).
- De **Moku:Go** (Liquid Instruments) is een multifunctioneel meetinstrument; wij gebruiken de
  Oscilloscope-modus voor live uitlezing en de Datalogger-modus voor hoge-snelheid bursts als
  fotodetector-frontend (`README.md:135`, `datalogger.py`).

**Reden tot onderzoek.** Een betaalbare confocale verplaatsingssensor bouwen door deze drie
bouwstenen te combineren met zelfontworpen optiek, actuatie en software, als omkeerbare
clip-on uitbreiding op de Block Stage (`README.md:39-50`).

**Beoogd doel/methode (globaal).** Op een punt sub-micron axiale verplaatsing meten; daarna
de probe over een raster bewegen om een ruimtelijke kaart op te bouwen. Per stilstaand punt
neemt de fotodetector een korte burst (enkele ms bij >= 1 MSa/s) op; offline FFT zet elke
burst om in een trillingsspectrum. Demonstratiecasus: **trillingsfrequentie-mapping van
MEMS**, waarbij elk burst-spectrum een punt wordt in een 3D-dataset `(x, y, frequentie) -> amplitude`
(`README.md:46-50`, `README.md:169`).

**Onderzoeksvraag (NL).** In hoeverre is het mogelijk om met een kostenefficiente confocal
displacement sensing-opstelling verplaatsingen en trillingen te meten, over een aanpasbaar
bereik van um tot cm, met voldoende nauwkeurigheid voor toepassingen binnen micro-engineering?

**Research question (EN).** To what extent is it possible to measure displacements and
vibrations using a cost-efficient confocal displacement sensing setup, over an adjustable range
from um to cm, with sufficient accuracy for applications within micro-engineering?

---

## 2. Theory (0.5 pagina): `confocal.py`

Het hele optische model in de code komt uit **vergelijking A6** (appendix A van de paper).
`confocal.py` implementeert uitsluitend A6 en wat daaruit volgt (`confocal.py:3-16`).

**Vergelijking A6 (confocale respons):**

```
I_m = I0 - I0 * exp(-r_d^2 / r_det^2)
```

- `I_m`  : gemeten fotodetector-intensiteit (V)
- `I0`   : referentie-intensiteit in het referentievlak (V), eenmalig per sessie ingesteld
- `r_d`  : pinhole-/diafragmastraal = 0.5 mm
- `r_det`: effectieve detectiespotstraal, functie van axiale verplaatsing `dz1`

**Detectiespotstraal (A5, herschreven op gemene noemer f1^2 * f2)** (`confocal.py:36-38`):

```
r_det = r0/(f1^2 * f2) * ( 2*dz1*(q*(f1+f2-L) + f2^2) - q*f1^2 )
```

**Fysische betekenis.** Bij een confocale opstelling delen de belichtingsspot en het
detector-pinhole hetzelfde brandpunt. Staat het sample in focus (`dz1 = 0`), dan is de spot op
het pinhole minimaal en passeert maximaal licht. Beweegt het sample axiaal, dan groeit `r_det`,
valt een groter deel van de spot buiten het pinhole en daalt `I_m`. Dit geeft de hoge
axiale (Z) gevoeligheid.

**Werkpunt q** (`confocal.py:50-58`). `compute_q` lost A6 op bij `dz1 = 0` en `I_m = I0/2`:

```
q = f2 * r_d / (r0 * sqrt(ln 2))
```

Belangrijk: `q` hangt **alleen** af van `f2`, `r_d`, `r0`, niet van `f1`. Voor de
standaardwaarden (`f2 = 150`, `r_d = 0.5`, `r0 = 2.75`) geldt **q = 32.76 mm** (analytisch en
bevestigd via `gridsearch_results.csv`).

**Inversie (V -> verplaatsing)** (`confocal.py:66-80`). Gegeven `I_m`:

```
r_det^2 = r_d^2 / ln( I0 / (I0 - I_m) )
```

`r_det` is lineair in `dz1`, dus er zijn twee takken (`dz1_minus`, `dz1_plus`). In de praktijk
wordt de **minus-tak** gebruikt (loopt door `dz1 = 0` bij `I_m = I0/2`), zie
`datalogger.py` `voltage_to_dz1`. Geldigheid: `0 < I_m < I0` (`confocal.py:74`).

**Gevoeligheid** (`confocal.py:83-85`). `compute_Sm` geeft `S_m = d(I_m)/d(dz1)`, symbolisch
afgeleid met SymPy. Wordt gebruikt voor bereik- en ruisanalyse.

**Parameters (standaard in `confocal.py:23-29`):**

| Symbool | Betekenis | Waarde | Eenheid |
|---|---|---|---|
| f1 | brandpuntsafstand lens 1 (variabel, zie Methods) | 40 (default) | mm |
| f2 | brandpuntsafstand lens 2 | 150 | mm |
| r0 | bundelstraal bij lens 1 (r1 in de paper) | 2.75 | mm |
| r_d | pinhole-/diafragmastraal | 0.5 | mm |
| L | optische afstand (vast) | 66 | mm |
| I0 | referentie-intensiteit (genormaliseerd in code) | 1.0 | V |

> Let op: `f1` is in de praktijk een **ontwerpvariabele** die is gevarieerd (25, 40, 60 mm),
> zie Methods en Results. `confocal.py` heeft default 40 mm, de README noemt 25 mm
> (`README.md:133`) en `ml.py` gebruikt 60 mm (`ml.py:25`).

---

## 3. Methods (1 pagina)

### 3.1 Opstelling (Moku-detector, OpenFlexure, toren)

| Subsysteem | Details | Bron |
|---|---|---|
| **Stage** | OpenFlexure Block Stage, **ongewijzigd**, als 3-assige flexure-basis | `README.md:132` |
| **Actuatie** | 3x 28BYJ-48 stepper + ULN2003-driver. Motor 1 = X, 2 = Y, 3 = Z (focus). Arduino Nano, COM4, 9600 baud | `firmware.ino`, `ui.py:56-64` |
| **Optische toren** | Twee-lens confocaal pad (f1, f2), detector-apertuur r_d = 0.5 mm, verticaal boven de stage | `README.md:133` |
| **Belichting** | WS2812B-8 LED-ring op pin A2 (binnen) en A3 (buiten), helderheid 0-255 via serieel | `firmware.ino`, `lamp.py` |
| **Fotodetector** | Moku:Go, IP 192.168.73.1, Oscilloscope (live) + Datalogger (burst) | `README.md:135`, `datalogger.py` |
| **Camera** | USB-webcam, index 0, MJPG, 1080p, 30 fps, voor uitlijning | `ui.py` |
| **Mechanica** | 38 STEP-bestanden in `cad/step/`, groepen BASE (9) / BLOCKS (28) / CALIBRATION (1), 3D-geprint, omkeerbare clip-on | `cad/README.md`, `README.md:27` |

De "toren" is de optische kolom (laser/bron-block, lens-f1-block, lens-f2-block, mirror-block,
detector-block met pinhole, camera-block) opgebouwd uit de `BLOCKS_*`-onderdelen met
afstandsringen `BLOCKS_spacer_0.4` t/m `3.2` mm voor Z-uitlijning.

### 3.2 Monochromatic confocal

- Het systeem werkt met een enkele (rode) golflengte: in `cad/step/` zitten een
  `BLOCKS_laser_block` + `BLOCKS_laser_cap` + `BLOCKS_laser_spacer` en een
  `BLOCKS_redfilter_clamp_top`. Dit wijst op een (rode) laser- of roodgefilterde bron.
- **Nog te verifieren:** exacte bron (laser vs roodgefilterde LED) en golflengte (nm). De
  WS2812B-ring (`lamp.py`) is RGB en dient vermoedelijk als algemene belichting/uitlijning, niet
  als de monochrome meetbron. Dit moet het team bevestigen voor de Methods-tekst.
- Het A6-model gaat uit van een Gaussische bundel met straal `r0 = 2.75 mm` bij lens 1.

### 3.3 Software

Alle software is Python (PySide6) plus Arduino-firmware. Overzicht (`README.md:183-197`):

| Bestand | Rol |
|---|---|
| `confocal.py` | Fysicakern: A6, `compute_q/Im/dz1/Sm` (SymPy + NumPy) |
| `ui.py` | Hoofdvenster: CameraThread, MotorPanel, MokuPanel, TopBar, tabs |
| `recording.py` | Handmatige burst (1 klik = 1 meting op huidige positie) + FFT |
| `scan.py` | Automatische rasterscan (burst per gridpunt, snake-pad) |
| `datalogger.py` | Moku Datalogger-wrapper, streaming burst + V -> dz1 |
| `ml.py` | Gradient descent fit van q en r0 op focuscurve-Excel |
| `gridsearch.py` | Sweep over f1/f2 -> q, Sm, meetbereik -> CSV |
| `viewer.py` | 3D-plot + heatmap van scandata (standalone CLI) |
| `calibration.py` | Persistentie mm/step + laatste positie -> `calibration.yaml` |
| `lamp.py`, `camera_settings.py` | LED-helderheid en camera-instellingen |
| `arduino/firmware/firmware.ino` | Nano-firmware: AccelStepper + NeoPixel, ASCII-protocol |

**Firmware-protocol (serieel, 9600 baud):** `GOTO x y z`, `BUSY?`, `SPEED s`, `SETPOS m p`,
`WHERE`, `STOP`, `LAMP b`, `LAMP2 b`. Motoren in **FULL4WIRE** met bewust omgewisselde IN2/IN3
op de ULN2003 (anders zoemen ze maar bewegen niet). Versnelling = 4x snelheid; default 500
steps/s, max 2000, max 4096 steps per as (`firmware.ino`, `ui.py:56-64`).

**Handmatige burst** (`recording.py`): stel `I0` in, kies samplerate (tot 1000 kSa/s) en duur
(ms), neem burst op. Opslag in `data/manual_<ts>_<naam>/`: `burst.csv` (ruwe spanning),
`position.csv` (dz1 via A6, indien I0 gezet), `metadata.txt`. FFT: DC verwijderen, Hann-venster,
`rfft`, amplitude = `|spectrum| * 2 / sum(window)` (`recording.py:56-73`).

**Automatische scan** (`scan.py`): raster met snake-pad. Toestandsmachine per punt:
`GOTO` -> `BUSY?` pollen (elke 80 ms) -> settelen (200 ms) -> Datalogger-burst -> opslaan.
Output `data/scan_<ts>_<naam>/`: `index.csv` (1 rij per punt) + `raw/point_NNNNN.csv`.
CSV in NL-locale (`;` scheidingsteken, `,` decimaal).

**Moku-acquisitielimieten (belangrijk voor Methods/Discussion):** de Datalogger (het burst-pad
dat de UI gebruikt) haalt max ~1 MSa/s. De Oscilloscope-modus kan tot 125 MSa/s. Trillingen
> ~500 kHz vereisen dus een overstap naar de Oscilloscope-modus; met het huidige burst-pad is de
Nyquist-grens ~500 kHz.

### 3.4 Kalibratie (step -> micron)

De step->micron-omrekening is gemeten en hiermee kan `dz1` in micrometers gerapporteerd worden.

| As | Kalibratie-meting | Resolutie | mm_per_step | Bewegingsbereik |
|---|---|---|---|---|
| X | 300 um over 13000 stappen | 0.02308 um/step (23.1 nm) | 2.308e-5 | +-500 um |
| Y | 300 um over 13000 stappen | 0.02308 um/step (23.1 nm) | 2.308e-5 | +-500 um |
| Z (focus) | 200 um over 17000 stappen | 0.01176 um/step (11.8 nm) | 1.176e-5 | +-300 um |

Twee implicaties voor de paper:
- De **per-stap resolutie is sub-micron** (12 tot 23 nm/step via de flexure-reductie), dus de
  actuatie zelf is fijn genoeg voor het sub-micron-doel.
- Het **bewegingsbereik is beperkt**: +-500 um (X/Y) en +-300 um (Z) vanaf nul, dus ~1 mm resp.
  ~0.6 mm totale slag. Dit begrenst de maximale scangrootte en de axiale focus-sweep.

**Gemeten axiale gevoeligheid.** Twee kalibratiepunten op de steile flank van de focuscurve:

| dz1 (mm) | I_m (V) |
|---|---|
| 4.0 | 5.24 |
| 4.2 | 2.33 |

Lokale helling = (2.33 - 5.24) / (4.2 - 4.0) = **-14.6 V/mm** (oftewel ~-14.6 mV/um) over dit
interval van 200 um. Dit is een direct gemeten `S_m` op de steile flank en koppelt spanning aan
verplaatsing voor de Results.

---

## 4. Results (0.5 pagina): type metingen + plots

### 4.1 Axiale focuscurves (kernresultaat)

Bij drie lensconfiguraties (f1 = 25/40/60 mm, telkens f2 = 150 mm) is de respons `I_m(dz1)`
gemeten en met `ml.py` (gradient descent, 20000 epochs) op A6 gefit. **Geverifieerde fits**
(zelf nagerekend op de Excel-data, `f2 = 150`, `L = 66`, `r_d = 0.5`):

| f1 (mm) | Databron / plot | n | dz1-bereik (mm) | I_m-bereik (V) | I0 (V) | q_fit (mm) | r0_fit (mm) | R^2 | RMSE (V) |
|---|---|---|---|---|---|---|---|---|---|
| 25 | `Metingen 25 mm.xlsx` / `25mm.png` | 21 | -4 .. 4 | 0.33 .. 6.10 | 6.10 | 108.4 | 0.737 | 0.979 | 0.27 |
| 40 | `metingen netter.xlsx` / `40mm.png` | 21 | -4 .. 4 | 0.94 .. 6.05 | 6.05 | 80.7 | 0.881 | 0.920 | 0.49 |
| 60 | `Metingen 60 mm.xlsx` / `60mm.png` | 21 | -4 .. 4 | 1.85 .. 8.04 | 8.04 | 138.9 | 0.630 | 0.993 | 0.17 |

Theorie-overlay in alle plots: `q = 32.75 mm`, `r0 = 2.75 mm` (`ml.py:34-35`).
`metingen.xlsx` is een aparte/eerdere dataset (41 punten, eenzijdig dz1 = 0..8 mm, q_fit = 19.2);
`metingen netter.xlsx` is de opgeschoonde 40 mm-set.

### 4.2 Theoretische ontwerptabel (gridsearch)

`gridsearch.py` -> `gridsearch_results.csv`. Voor f2 = 150 mm (vaste q = 32.76 mm) toont de
trade-off tussen gevoeligheid en bereik:

| f1 (mm) | S_m bij 0 (per mm) | lineair bereik 10-90% (mm) | amplitudebereik 50-90% (mm) |
|---|---|---|---|
| 25 | 3.476 | 0.792 | 0.177 |
| 40 | 1.376 | 1.989 | 0.445 |
| 60 | 0.641 | 4.368 | 0.978 |

Kortere f1 = hogere gevoeligheid maar kleiner meetbereik; langere f1 = omgekeerd. (S_m is hier
genormaliseerd op I0 = 1; schaal met de werkelijke I0 in volts voor V/mm.)

### 4.3 Burst- en FFT-metingen (trillingen)

Op 28 mei zijn 12 opeenvolgende bursts opgenomen (10 ms bij 10 kSa/s, dus 100 samples,
FFT-bin = 100 Hz, Nyquist = 5 kHz), met vaste `I0 = 5.4 V`, motoren op nul, lamp 128. **Zelf
nagerekende FFT-pieken** (uit `burst.csv`, niet uit de plot afgelezen):

- Gemiddelde spanning verloopt van 2.22 tot 2.81 V over de 12 bursts.
- Ruis (std) 1 tot 9 mV; piek-piek 5 tot 29 mV.
- Dominante FFT-piek **verspreid over 100 tot 400 Hz** (geen schone, herhaalbare resonantie);
  amplitudes 0.4 tot 14 mV. Bij 100 Hz binbreedte ligt de piek vaak in de laagste paar bins,
  wat wijst op laagfrequente drift/ruis in plaats van een duidelijke sample-trilling.

Langere bursts (100 kSa/s, 500 ms, ~50000 samples) zijn ook opgenomen
(`data/manual_2026-05-19_*`, `data/manual_2026-05-27_16-00-16_test_5.6_V`) met I0 tot 5.70 V.

### 4.4 Step->micron-kalibratie

De assen zijn gekalibreerd (zie sectie 3.4): X/Y = 23.1 nm/step (300 um over 13000 steps),
Z = 11.8 nm/step (200 um over 17000 steps). De gemeten axiale gevoeligheid op de steile flank is
-14.6 V/mm (200 um van 4.0 naar 4.2 mm: 5.24 -> 2.33 V).

### 4.5 Scan-pipeline

De automatische scan-pipeline is gedemonstreerd (`data/2026-05-06_...`, `data/2026-05-13_...`,
~105 punten). Die vroege runs draaiden nog met `mm_per_step = 0` in `calibration.yaml`; met de
nu bekende step->micron-factoren (sectie 3.4) kunnen scans wel als metrische kaart in micrometers
worden weergegeven.

---

## 5. Discussion (0.5 pagina)

**Wat werkt / wat kan het wel.**
- Het confocale principe is meetbaar: de axiale respons `I_m(dz1)` volgt de A6-vorm en is bij
  alle drie lensconfiguraties goed te fitten (R^2 = 0.92 tot 0.99).
- De keten Moku:Go-burst -> V -> dz1 -> FFT werkt end-to-end, evenals de automatische rasterscan.
- Lage kosten en omkeerbare bolt-on op open hardware (OpenFlexure), reproduceerbaar via repo.
- De gevoeligheid/bereik-trade-off met f1 klopt kwalitatief met de gridsearch-voorspelling.

**Wat kan beter / wat kan het (nog) niet.**
- **Fijne resolutie, begrensd bereik.** De step->micron-kalibratie (sectie 3.4) laat een fijne
  per-stap resolutie zien (Z = 11.8 nm/step, X/Y = 23.1 nm/step), ruim sub-micron. De praktische
  beperking is het bewegingsbereik (+-500 um X/Y, +-300 um Z), niet de stapgrootte.
- **Modelafwijking:** gefitte `r0` (0.63 tot 0.88 mm) is veel kleiner dan de theoretische
  2.75 mm, en gefitte `q` (80 tot 139 mm) veel groter dan de theoretische 32.76 mm. Dit wijst op
  optische misuitlijning/aberratie of een bundelprofiel dat afwijkt van de modelaanname.
- **Actuatie:** 28BYJ-48 steppers geven via de flexure-reductie sub-micron stappen, maar speling
  en hysterese maken absolute, herhaalbare sub-micron positionering nog lastig.
- **FFT-trillingen:** de gemeten pieken (100 tot 400 Hz, grof opgelost bij 100 Hz bins) zijn
  waarschijnlijk stage-/motorresonantie of laagfrequente drift, niet aantoonbaar sample-trilling.
  De 10 ms-bursts geven te lage frequentieresolutie.
- Lamp/bron is niet teruggekoppeld; I0-stabiliteit en bronruis zijn niet gekarakteriseerd.

**Hoe verder ontwikkelen.**
- Motoren kalibreren (`CALIBRATION_table_calibrator`) zodat dz1 in micrometers volgt.
- Optiek beter uitlijnen en bron/golflengte karakteriseren om r0/q richting theorie te brengen.
- Betere actuatie (bijv. piezo) en trillingsisolatie voor echte sub-micron metingen.
- Langere bursts / hogere samplerate (Oscilloscope-modus tot 125 MSa/s) voor fijnere spectra.
- Volledige MEMS-trillingskaart `(x, y, f) -> amplitude` als einddemonstratie.

---

## 6. Conclusion (0.25 pagina)

De onderzoeksvraag kan bevestigend-met-nuance beantwoord worden: een laagdrempelige confocale
verplaatsingssensor op basis van de OpenFlexure Block Stage met een Moku:Go als detector
**toont een meetbare axiale respons die het confocale A6-model volgt** (R^2 = 0.92 tot 0.99 over
drie lensconfiguraties), met een gevoeligheid/bereik-gedrag dat overeenkomt met de theorie. De
volledige stap naar gekalibreerde sub-micron metingen en complete MEMS-trillingsmapping vereist
nog step->mm-kalibratie, betere optische uitlijning en fijnere actuatie.

---

## 7. Parameter- en getallenreferentie (paper-ready)

| Grootheid | Waarde | Bron |
|---|---|---|
| f1 (gevarieerd) | 25 / 40 / 60 | mm | Excel-sets, README, ml.py |
| f2 | 150 mm | `confocal.py:25` |
| r0 (theorie) | 2.75 mm | `confocal.py:26` |
| r_d (pinhole) | 0.5 mm | `confocal.py:27` |
| L | 66 mm | `confocal.py:28` |
| q (theorie, f2=150) | 32.76 mm | `compute_q`, gridsearch |
| q_fit (25/40/60 mm) | 108.4 / 80.7 / 138.9 mm | sectie 4.1 |
| r0_fit (25/40/60 mm) | 0.737 / 0.881 / 0.630 mm | sectie 4.1 |
| R^2 (25/40/60 mm) | 0.979 / 0.920 / 0.993 | sectie 4.1 |
| S_m bij 0, f2=150 (25/40/60) | 3.476 / 1.376 / 0.641 per mm | gridsearch |
| Lineair bereik 10-90%, f2=150 (25/40/60) | 0.79 / 1.99 / 4.37 mm | gridsearch |
| Resolutie X/Y | 23.1 nm/step (300 um / 13000 steps) | sectie 3.4 |
| Resolutie Z (focus) | 11.8 nm/step (200 um / 17000 steps) | sectie 3.4 |
| Bewegingsbereik X/Y, Z | +-500 um, +-300 um | sectie 3.4 |
| Gemeten S_m (steile flank) | -14.6 V/mm (4.0->4.2 mm: 5.24->2.33 V) | sectie 3.4 |
| Max samplerate (Datalogger/burst) | 1 MSa/s (Nyquist 500 kHz) | `recording.py`, Moku-limiet |
| Max samplerate (Oscilloscope) | 125 MSa/s | Moku-limiet |
| Burst-FFT pieken (12x 10 ms) | 100-400 Hz, amp 0.4-14 mV | sectie 4.3 |
| Fotodetector-spanning (typisch) | 0.01-8.04 V | data/, Excel |
| Ruis (std, 10 ms burst) | ~1-9 mV | sectie 4.3 |
| Steppers | 3x 28BYJ-48 + ULN2003, FULL4WIRE | firmware |
| Motor default/max snelheid | 500 / 2000 steps/s | `ui.py:59-60` |
| Moku IP | 192.168.73.1 | `README.md:135` |
| Licenties | software MIT, hardware+docs CC BY-SA 4.0 | `README.md:243-249` |

---

## 8. Nog te verifieren voor publicatie

1. **Bron en golflengte** van de monochrome belichting (laser vs roodgefilterde LED, nm). CAD
   bevat laser- en roodfilter-onderdelen; team bevestigen.
2. **Onderzoeksvraag** is vastgesteld (sectie 1, NL + EN). Nog afstemmen of de paper de range
   "um tot cm" hard claimt: het gemeten focuscurve-bereik is ~mm (dz1 = -4..4 mm) en het
   actuatie-/scanbereik +-500 um (X/Y) / +-300 um (Z); de cm-bovenkant en um-onderkant moeten
   onderbouwd of genuanceerd worden.
3. **Appendix A / referenties:** de paper-derivatie van A5/A6 en literatuurreferenties voor
   confocale verplaatsingsmeting en MEMS-trillingen (nog niet in de repo aanwezig; geen `.tex`/`.bib`).
4. **Mechanische speling/hysterese** kwantificeren (heen-en-terug-meting): dit is de resterende
   positioneringsonzekerheid nu het bewegingsbereik bekend is (+-500 um X/Y, +-300 um Z).
5. **Bouwkosten** (BOM-totaal in `docs/OpenSource_CDS_BOM.xlsx`) voor de "betaalbaar"-claim in Introduction.
6. **r0/q-afwijking** verklaren: meet werkelijke bundelstraal en lensafstand L om de fit-versus-
   theorie-discrepantie te onderbouwen.
7. **Welke f1 is de eindopstelling?** README zegt 25 mm, `confocal.py` default 40 mm; consistent maken.

---

## 9. Bestandskaart (waar staat wat)

- Fysica/model: `confocal.py`, `ml.py`, `gridsearch.py`, `gridsearch_results.csv`
- Focuscurve-data: `Metingen 25 mm.xlsx`, `metingen netter.xlsx` (40 mm), `Metingen 60 mm.xlsx`,
  `metingen.xlsx`; plots `25mm.png`, `40mm.png`, `60mm.png`
- Burst/scan-data: `data/manual_*`, `data/2026-05-*_*` (incl. `fft.png` per burst)
- Software: `ui.py`, `recording.py`, `scan.py`, `datalogger.py`, `viewer.py`, `lamp.py`,
  `camera_settings.py`, `calibration.py`, `calibration.yaml`
- Firmware: `arduino/firmware/firmware.ino`
- Hardware/docs: `cad/` (38 STEP + `cad/README.md`), `docs/wiring.md`, `docs/OpenSource_CDS_User_Guide.pdf`,
  `docs/OpenSource_CDS_BOM.xlsx`, `docs/OpenSource_CDS_Printing_Guide.pdf`, `README.md`, `assets/MAIN_ASSEMBLY.png`
