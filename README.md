# Confocal Displacement Sensing

> **Affordable confocal displacement measurement.**
> *Confocal Displacements Sensing voor betaalbare verplaatsingsmetingen*

<!-- TODO: add a hero image — render of the assembled instrument, or a screenshot of the UI mid-scan. Place under assets/hero.png and reference it here: -->
<!-- ![Confocal Displacement Sensor](assets/hero.png) -->

![Status](https://img.shields.io/badge/status-active-success) ![Python](https://img.shields.io/badge/python-3.10%2B-blue) ![UI](https://img.shields.io/badge/UI-PySide6-41cd52) ![Hardware](https://img.shields.io/badge/hardware-Arduino%20Nano%20%2B%20Moku%3AGo-orange) ![Course](https://img.shields.io/badge/TU%20Delft-WBMT3BEP%20%C2%B7%20PME--2026--A06-00a6d6)

A Bachelor End Project (BEP) for the **Precision and Micro-Engineering** track at TU Delft (course `WBMT3BEP`, project code `PME-2026-A06`).
Submission: <!-- TODO: confirm date, screenshot showed "March 25th 2026" -->.

**Team:** Dafne Gyselinck · Jayden Jhagru · Harmen Klerk · Ties van Lohuizen · Stef Wiegman

---

## 🔗 Project Hub

Everything we made for this project lives behind one of these links.

| Deliverable | Link | For whom |
|---|---|---|
| 📄 Research paper | [🚧 TODO](#) <!-- TODO: paste paper URL (Overleaf share / PDF on Drive) --> | Researchers, examiners |
| 🎥 Assembly video | [🚧 TODO](#) <!-- TODO: paste YouTube URL --> | Builders following along |
| 📐 CAD files | [🚧 TODO](#) <!-- TODO: paste Drive / GrabCAD / Onshape URL --> | Fabrication, modification |
| 🔧 Wiring guide | [`docs/wiring.md`](docs/wiring.md) | Electronics assembly |
| 🛒 Parts list (BOM) | [`docs/bom.md`](docs/bom.md) | Procurement |
| 🖨️ 3D-print guide | [`docs/print-guide.md`](docs/print-guide.md) | Makers, print-farm operators |
| 📖 Use guide | [`docs/use-guide.md`](docs/use-guide.md) | End users running measurements |
| 💻 Source code | this repository | Software contributors |

---

## What is this?

A desktop application plus custom hardware that **measures sub-micron axial displacement** at a single point, and walks the probe over a sample to build a spatial map. A confocal optical path converts axial displacement into a photodetector voltage; a 3-axis stepper stage positions the sample; at each programmed stand-still point the system records a high-speed voltage burst. The goal is to deliver this capability **at a small fraction of the cost of commercial confocal displacement sensors**.

A natural application — and our demonstration case — is **vibration-frequency mapping of MEMS devices**: each burst is FFT-analysed to yield the spectrum at that grid point, producing a 3D dataset `(x, y, frequency) → amplitude`.

### Pick your starting point

- **Reading the paper?** Start with the [research paper](#-project-hub), then the [confocal model](#confocal-model).
- **Building a copy?** Open the [3D-print guide](docs/print-guide.md), [BOM](docs/bom.md), [wiring guide](docs/wiring.md), and watch the [assembly video](#-project-hub).
- **Running an existing instrument?** Jump to [Quickstart](#quickstart), then the [use guide](docs/use-guide.md).
- **Hacking the software?** See [Repository layout](#repository-layout) and [For developers](#for-developers).

---

## Quickstart

```powershell
git clone https://github.com/Stefwiegman/Bep-Project.git
cd Bep-Project
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python ui.py
```

**Defaults:** Arduino Nano on `COM4 @ 9600 baud`, Moku:Go reachable at `192.168.73.1`, USB webcam on index 0 (MJPG @ 1080p/30 fps). Change in the Setup tab of the UI.

---

## Hardware overview

| Subsystem | Details |
|---|---|
| Stage | 3× 28BYJ-48 stepper + ULN2003 driver, Arduino Nano (`COM4`, 9600 baud). Motor 1 = X-axis, motor 2 = Y-axis, motor 3 = Z-axis (focus) |
| Lamp | WS2812B-8 LED ring on pin A2, shared serial port |
| Photodetector | Moku:Go (Oscilloscope + Datalogger modes), IP `192.168.73.1` |
| Camera | USB webcam, index 0, MJPG @ 1080p / 30 fps |

Full pin-out, schematic and connector list → [`docs/wiring.md`](docs/wiring.md). Parts and suppliers → [`docs/bom.md`](docs/bom.md).

---

## UI layout

```
┌─ TopBar: brand · [Motors][Moku][Camera] status pills · Save calibration ──┐
├──────────────────────────────┬────────────────────────────────────────────┤
│  Camera feed (● LIVE)        │  Tabs: Manual │ Auto Scan │ Setup │ Camera │
│                              │  + Lamp panel (Setup tab only)             │
├──────────────────────────────┴────────────────────────────────────────────┤
│  Moku:Go photodetector — live voltage(t) plot                             │
└───────────────────────────────────────────────────────────────────────────┘
```

| Tab | What it does |
|---|---|
| **Manual** | One burst at the current motor position. Output: `data/manual_<ts>_<name>/burst.csv` + `metadata.txt`. Also hosts Set I0 / Clear for the V → dz1 conversion. |
| **Auto Scan** | Automatic raster scan. Per point: `GOTO` → poll `BUSY?` → settle → Datalogger burst → save. Output: `data/scan_<ts>_<name>/index.csv` + `raw/point_NNNNN.csv`. |
| **Setup** | Connect, jog, soft-home ("Set 0 here"), speed, calibration. |
| **Camera** | Exposure, brightness, contrast, auto-exposure, black-and-white. |

Step-by-step operating instructions → [`docs/use-guide.md`](docs/use-guide.md).

---

## How it works

At every grid point the stage settles to a halt, the Moku:Go records a high-sample-rate voltage burst from the photodetector, and the burst is saved as raw CSV. The confocal optical model (see below) converts photodetector voltage to a Z-axis displacement `dz1`. After the scan, each burst is FFT-analysed offline to yield the vibration spectrum at that point — the full scan therefore produces a 3D dataset `(x, y, frequency) → amplitude`.

Full theoretical background and derivations: see the [research paper](#-project-hub).

---

## Repository layout

| File | Role |
|---|---|
| `ui.py` | Main window — CameraThread, MotorPanel, MokuPanel, TopBar, layout |
| `scan.py` | Automatic raster scan (burst per grid point, snake path) |
| `recording.py` | Manual burst (one click = one measurement at current position) |
| `lamp.py` | WS2812B brightness via slider, throttled @ 20 updates/s |
| `camera_settings.py` | Exposure / brightness / contrast / black-and-white (Camera tab) |
| `datalogger.py` | Moku Datalogger wrapper — streaming burst acquisition + V → dz1 conversion |
| `calibration.py` | Persistence of mm/step + last position → `calibration.yaml` |
| `confocal.py` | Physics core: formula A6, `compute_q` / `Im` / `dz1` / `Sm` (sympy + numpy) |
| `gridsearch.py` | Sweep over f1/f2 → measurement-range analysis → CSV (standalone) |
| `viewer.py` | 3D plot + heatmap of scan data (standalone CLI) |
| `styles.qss` | Qt stylesheet (design tokens derived from `mockup.html`) |
| `arduino/firmware/firmware.ino` | Nano firmware: AccelStepper + NeoPixel, ASCII command protocol |

---

## For developers

### Firmware command protocol

9600 baud, ASCII, line-delimited.

| Command | Effect | Reply |
|---|---|---|
| `<n> <p>` | Motor `n` → absolute position `p` (steps) | `OK n p` |
| `GOTO m1 m2 m3` | All three motors to target simultaneously | `OK GOTO …` |
| `SPEED v` | Max speed (steps/s) | `OK SPEED v` |
| `STOP` | Emergency stop | `OK STOP` |
| `LAMP 0-255` | LED brightness | `OK LAMP n` |
| `SETPOS m p` | Soft-home: set counter without moving | `OK SETPOS …` |
| `WHERE` | Current positions | `POS m1 m2 m3` |
| `BUSY?` | Are motors still moving? | `BUSY 1` / `BUSY 0` |

### Calibration

`calibration.yaml` (project root) stores per motor the `mm_per_step` and `last_position`. Loaded automatically on connect, saved on disconnect. On a position mismatch the UI shows a restore prompt.

### Measurement pipeline

1. Set I0 (Manual tab, "Set I0") — average photodetector voltage as reference
2. Choose scan settings (size mm, resolution, settle time, sample rate, burst duration)
3. ▶ Start scan — the state machine drives each grid point, takes a burst, writes `raw/point_NNNNN.csv`
4. Analyse: each burst contains `t_s` + `dz1_mm` (or `voltage_V` if no I0) — ready for FFT

### Confocal model

`confocal.py` implements formula A6 from the paper (symbolic via sympy, numeric via numpy):

```
I_m = I0 · (1 − exp(−r_d² / r_det²))
```

with `r_det` linear in `dz1`. Four functions: `compute_q`, `compute_Im`, `compute_dz1` (two branches), `compute_Sm` (sensitivity).

Optical setup parameters: `f1 = 25 mm`, `f2 = 150 mm`, `r0 = 2.75 mm`, `r_d = 0.5 mm`, `L = 66 mm`.

---

## Project status

| Component | State |
|---|---|
| Software (this repo) | ✅ Working |
| Firmware | ✅ Working |
| Wiring guide | 🚧 In progress — see [`docs/wiring.md`](docs/wiring.md) |
| BOM | 🚧 In progress — see [`docs/bom.md`](docs/bom.md) |
| 3D-print guide | 🚧 In progress — see [`docs/print-guide.md`](docs/print-guide.md) |
| Use guide | 🚧 In progress — see [`docs/use-guide.md`](docs/use-guide.md) |
| Assembly video | 🚧 To be recorded / uploaded to YouTube |
| CAD release | 🚧 To be packaged + uploaded |
| Research paper | 🚧 In writing |

---

## Credits

Bachelor End Project — *Precision and Micro-Engineering* track, **TU Delft**, academic year 2025–2026.
Course `WBMT3BEP`, project code `PME-2026-A06`.

**Team:** Dafne Gyselinck · Jayden Jhagru · Harmen Klerk · Ties van Lohuizen · Stef Wiegman.

**Supervisor(s):** <!-- TODO: fill in supervisor name(s) + department -->.

Software architecture by Stef Wiegman.

## License

<!-- TODO: pick a license. For an academic deliverable that doubles as an open hardware project, MIT (code) + CERN-OHL-S or CC-BY-SA (hardware / CAD / docs) is a common combination. Add LICENSE file(s) at repo root. -->
🚧 To be added.
