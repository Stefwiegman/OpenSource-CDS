# Bep-Project · Confocale MEMS-vibratiemeter

PySide6-desktopapp voor het aansturen en meten met een confocale verplaatsingssensor op een 3-assige stepper-stage. Doel: ruimtelijke kaart van MEMS-trillingsfrequenties via burst-acquisitie per rasterpunt.

## Hardware

| Onderdeel | Details |
|---|---|
| Stage | 3× 28BYJ-48 + ULN2003, Arduino Nano (COM4, 9600 baud). Motor 1 = X-as, motor 2 = Y-as, motor 3 = Z-as (focus) |
| Lamp | WS2812B-8 ring op pin A2, gedeelde serial-poort |
| Fotodetector | Moku:Go (Oscilloscope + Datalogger), IP 192.168.73.1 |
| Camera | USB-webcam index 0, MJPG @ 1080p/30 fps |

## Installeren

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python ui.py
```

## Bestanden

| Bestand | Rol |
|---|---|
| `ui.py` | Hoofdvenster — CameraThread, MotorPanel, MokuPanel, TopBar, layout |
| `scan.py` | Automatische raster-scan (burst per rasterpunt, snake-pad) |
| `recording.py` | Handmatige burst (één klik = één meting op huidige positie) |
| `lamp.py` | WS2812B-helderheid via slider, throttled @ 20 updates/s |
| `camera_settings.py` | Belichting/helderheid/contrast/zwart-wit (Camera-tab) |
| `datalogger.py` | Moku Datalogger wrapper — streaming burst-acquisitie + V→dz1 conversie |
| `calibration.py` | Persistentie van mm/stap + laatste positie → `calibration.yaml` |
| `confocal.py` | Fysica-kern: formule A6, compute\_q/Im/dz1/Sm (sympy + numpy) |
| `gridsearch.py` | Sweep over f1/f2 → meetbereik-analyse → CSV (standalone) |
| `viewer.py` | 3D-plot + heatmap van scandata (standalone CLI) |
| `styles.qss` | Qt-stylesheet (design-tokens afgeleid van mockup.html) |
| `arduino/firmware/firmware.ino` | Nano-firmware: AccelStepper + NeoPixel, ASCII-commandoprotocol |

## UI-layout

```
┌─ TopBar: brand · [Motors][Moku][Camera] pills · Save kalibratie ──┐
├──────────────────────────────┬────────────────────────────────────┤
│  Camera feed (● LIVE)        │  Tabs: Manual │ Auto Scan │ Setup  │
│                              │              │ Camera              │
│                              │  + Lamp-paneel (alleen Setup-tab)  │
├──────────────────────────────┴────────────────────────────────────┤
│  Moku:Go fotodetector — live spanning(t)-grafiek                  │
└───────────────────────────────────────────────────────────────────┘
```

### Tabs

**Manual** — één burst op de huidige motorpositie. Output: `data/manual_<ts>_<naam>/burst.csv` + `metadata.txt`. Bevat ook Set I0 / Clear voor de V→dz1-conversie.

**Auto Scan** — automatische raster-scan. Per punt: `GOTO` → poll `BUSY?` → settle → Datalogger-burst → opslaan. Output: `data/scan_<ts>_<naam>/index.csv` + `raw/point_NNNNN.csv`.

**Setup** — verbinden, jog, soft-home ("Zet 0 hier"), snelheid, kalibratie.

**Camera** — belichting, helderheid, contrast, auto-belichting, zwart-wit.

## Firmware-commando's (9600 baud, ASCII)

| Commando | Effect | Antwoord |
|---|---|---|
| `<n> <p>` | Motor n → absolute positie p stappen | `OK n p` |
| `GOTO m1 m2 m3` | Alle 3 tegelijk naar target | `OK GOTO …` |
| `SPEED v` | Max snelheid (stappen/s) | `OK SPEED v` |
| `STOP` | Noodstop | `OK STOP` |
| `LAMP 0-255` | LED-helderheid | `OK LAMP n` |
| `SETPOS m p` | Soft-home: zet teller zonder beweging | `OK SETPOS …` |
| `WHERE` | Actuele posities | `POS m1 m2 m3` |
| `BUSY?` | Rijden de motoren nog? | `BUSY 1` / `BUSY 0` |

## Kalibratie

`calibration.yaml` (project-root) onthoudt per motor de `mm_per_step` en `last_position`. Wordt automatisch geladen bij verbinden en opgeslagen bij ontkoppelen. Bij een positie-mismatch toont de UI een restore-prompt.

## Meetpijplijn

1. Stel I0 in (Manual-tab, "Set I0") — gemiddelde fotodetector-spanning als referentie
2. Kies scan-instellingen (grootte mm, resolutie, settle-tijd, sample-rate, burst-duur)
3. ▶ Start scan — de state machine rijdt elk rasterpunt langs, neemt een burst en schrijft `raw/point_NNNNN.csv`
4. Analyseer: elke burst bevat `t_s` + `dz1_mm` (of `voltage_V` zonder I0) — klaar voor FFT

## Confocaal model

`confocal.py` implementeert formule A6 uit het paper (symbolisch via sympy, numeriek via numpy):

```
I_m = I0 · (1 − exp(−r_d² / r_det²))
```

met r\_det lineair in dz1. Vier functies: `compute_q`, `compute_Im`, `compute_dz1` (twee takken), `compute_Sm` (gevoeligheid).

Parameters opstelling: f1=25 mm, f2=150 mm, r0=2.75 mm, r\_d=0.5 mm, L=66 mm.
