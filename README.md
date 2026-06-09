# Confocal Displacement Sensing

> **Affordable confocal displacement measurement.**
> *Confocal Displacements Sensing voor betaalbare verplaatsingsmetingen*

![Confocal Displacement Sensor, CAD render of the assembled instrument](assets/MAIN_ASSEMBLY.png)

![Status](https://img.shields.io/badge/status-active-success) ![Python](https://img.shields.io/badge/python-3.10%2B-blue) ![UI](https://img.shields.io/badge/UI-PySide6-41cd52) ![Hardware](https://img.shields.io/badge/hardware-Arduino%20Nano%20%2B%20Moku%3AGo-orange) ![Course](https://img.shields.io/badge/TU%20Delft-WBMT3BEP%20%C2%B7%20PME--2026--A06-00a6d6)

A Bachelor End Project (BEP) for the **Precision and Micro-Engineering** track at TU Delft (course `WBMT3BEP`, project code `PME-2026-A06`).
Submission: **June 12th 2026**.

**Team:** Dafne Gyselinck · Jayden Jhagru · Harmen Klerk · Ties van Lohuizen · Stef Wiegman

> 🧱 **Built on top of the [OpenFlexure Block Stage](https://openflexure.org/projects/blockstage/)** (CC BY-SA 4.0), used **unmodified** as our 3-axis flexure base. See [Built on top of](#-built-on-top-of) for what this means for builders, and for attribution.

---

## 🔗 Project Hub

Everything we made for this project lives behind one of these links.

| Deliverable | Link | What's inside |
|---|---|---|
| 📄 Research paper | [🚧 TODO](#) <!-- TODO: paste paper URL (Overleaf share / PDF on Drive) --> | Theoretical background, confocal model derivation (appendix A), measurement results, discussion |
| 🎥 Assembly video | [YouTube](https://www.youtube.com/watch?v=UzMbLptgHZc) | Step-by-step build from printed parts and electronics to a working instrument |
| 📐 CAD files | [`cad/`](cad/) | 38 STEP source files for every printed part of the confocal extension, grouped by category (BASE / BLOCKS / CALIBRATION) |
| 🧩 Assembly viewer | [Onshape](https://cad.onshape.com/documents/87fafcc64806dd978cd8e8a6/w/b53780b5a9e32836df5ce22e/e/844e572a161a9db474edfe58) | Interactive 3D model of the full assembly: rotate and inspect in the browser, or export STEP / STL yourself |
| 🔧 Circuit diagram | [`docs/circuit-diagram.pdf`](docs/circuit-diagram.pdf) | Arduino pin-out, ULN2003 IN2/IN3-swap, power, Moku and camera connections (PDF, download to view) |
| 🛒 Parts list (BOM) | [`docs/OpenSource_CDS_BOM.xlsx`](docs/OpenSource_CDS_BOM.xlsx) | Electronics, optics, mechanical hardware, quantities, suppliers, prices (Excel, download to view) |
| 🖨️ 3D-print guide | [`docs/OpenSource_CDS_Printing_Guide.pdf`](docs/OpenSource_CDS_Printing_Guide.pdf) | Printer settings, per-part list with print times, filament estimates, tolerances |
| 📖 Use guide | [`docs/OpenSource_CDS_User_Guide.pdf`](docs/OpenSource_CDS_User_Guide.pdf) | Optical alignment (tower, LED, mirror, detector), laser calibration, powering on, homing the stage, finding I0 and the calibration sweep (PDF, download to view) |
| 🧱 Block stage origin | [openflexure.org/projects/blockstage](https://openflexure.org/projects/blockstage/) | Upstream open-hardware base, required reading before fabrication |
| 💻 Source code | this repository | PySide6 desktop UI, Arduino firmware, burst pipeline, confocal physics model |

---

## What is this?

A complete, low-cost **confocal displacement measurement instrument**, built from four parts:

- An **unmodified [OpenFlexure Block Stage](https://openflexure.org/projects/blockstage/)** as the 3-axis flexure base
- Our custom **confocal optical column** (two lenses, pinhole aperture, photodetector) that bolts onto the block stage
- Our **stepper actuators, electronics, and illumination** that also mount to the unmodified stage
- A desktop application that ties it all together for live alignment, calibration, and manual point measurements

The instrument **measures sub-micron axial displacement** (vertical position changes smaller than 1 µm) at one point on a sample. Repositioning the probe across a grid builds a spatial map: at each stand-still point the photodetector records a high-speed voltage burst (a few milliseconds at ≥1 MSa/s), and offline FFT analysis turns each burst into a vibration spectrum.

The goal is to deliver this capability at a small fraction of the cost of commercial confocal displacement sensors, making the technology accessible for academic and small-lab settings.

A natural application, and our demonstration case, is **vibration-frequency mapping of MEMS devices**: each burst's spectrum becomes one point in a 3D dataset `(x, y, frequency) → amplitude`.

### Glossary

If terms below are new to you, this short table covers the rest of the README:

| Term | What it means here |
|---|---|
| **Confocal** | Optical setup where the illumination spot and detector pinhole share a common focus, gives the system its high axial (Z-axis) sensitivity |
| **Burst** | A short (few ms) high-rate sample of photodetector voltage taken at one stand-still position |
| **dz1** | Axial (Z) displacement of the sample from a reference plane, in mm |
| **I0** | Photodetector voltage at full reflection (the maximum of the calibration curve); the linear region sits around I0/2 |
| **Calibration line** | A straight line `I_m = a·dz1 + b` fitted to the steep middle of the confocal curve; inverting it (`dz1 = (V - b) / a`) turns measured voltage into displacement |
| **MEMS** | Micro-Electro-Mechanical Systems, micrometer-scale moving structures whose vibrations we characterise |
| **Moku:Go** | Liquid Instruments' multifunction lab instrument; it is the acquisition **back-end** that digitises the photodetector signal (Oscilloscope mode for live view, Datalogger mode for burst capture) |
| **Flexure stage** | A stage that moves via elastic flexion of monolithic features instead of sliding bearings, sub-micron repeatable, see OpenFlexure |

### Pick your starting point

- **Reading the paper?** Start with the [research paper](#-project-hub), then the [Hardware overview](#hardware-overview) for the optical setup.
- **Building a copy?** Read [Built on top of](#-built-on-top-of) first, then open the [3D-print guide](docs/OpenSource_CDS_Printing_Guide.pdf), [BOM](docs/OpenSource_CDS_BOM.xlsx), [circuit diagram](docs/circuit-diagram.pdf), and watch the [assembly video](https://www.youtube.com/watch?v=UzMbLptgHZc).
- **Running an existing instrument?** Jump to [Prerequisites](#prerequisites) and [Setup](#setup), then the [use guide](docs/OpenSource_CDS_User_Guide.pdf).
- **Hacking the software?** See [Repository layout](#repository-layout).

---

## Prerequisites

Before the software will do anything useful, make sure you have:

| Need | Why | How to verify |
|---|---|---|
| **Python ≥ 3.10** | UI + burst pipeline | `python --version` |
| **Git** | clone repo | `git --version` |
| **Arduino IDE** (or `arduino-cli`) | flash the Nano firmware once | open IDE, plug in Nano |
| **Moku:Go** + Liquid Instruments account | photodetector readout | reachable at `192.168.73.1` after connecting to its Access-Point Wi-Fi or Ethernet |
| **USB microscope camera** (UVC, ≥1080p) | live view of the sample on the Camera tab | the laptop's built-in webcam is never used; only an external camera is opened |
| **Assembled hardware** | otherwise the UI starts but cannot measure | see [3D-print guide](docs/OpenSource_CDS_Printing_Guide.pdf), [circuit diagram](docs/circuit-diagram.pdf), and the [assembly video](https://www.youtube.com/watch?v=UzMbLptgHZc) |

Estimated total build cost: **≈ €1600**, dominated by the Moku:Go (≈ €689) and the optics (lens and red filter, listed as approximate prices); see the [BOM](docs/OpenSource_CDS_BOM.xlsx) for the full breakdown.

---

## Setup

This chapter takes you from a fresh clone to all three TopBar status pills (`Motors / Moku / Camera`) turning green. For aligning and calibrating the instrument afterwards (optical alignment, laser calibration, finding I0, calibration sweep) see the [use guide](docs/OpenSource_CDS_User_Guide.pdf).

### 1. Clone and create a Python environment

**Windows (PowerShell):**

```powershell
git clone https://github.com/Stefwiegman/Bep-Project.git
cd Bep-Project
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**Linux / macOS (bash/zsh):**

```bash
git clone https://github.com/Stefwiegman/Bep-Project.git
cd Bep-Project
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

This pulls in the UI and pipeline stack: PySide6 (Qt UI), pyserial (Arduino link), the `moku` client, NumPy + matplotlib (math and plots), SymPy (confocal model), OpenCV + pygrabber (camera), pandas (Excel/CSV import in the Calibration graph tab) and PyYAML (calibration persistence).

### 3. Flash the Arduino firmware (one-time)

The stage motors and lamp are driven by an Arduino Nano. Flash it once with the Arduino IDE (or `arduino-cli`):

1. Open `arduino/firmware/firmware.ino`.
2. Install the required libraries via the Library Manager: **AccelStepper** and **Adafruit NeoPixel**.
3. Select board **Arduino Nano** and the correct COM-port, then **Upload**.

Note the port the Nano enumerates on, you pick it in the app later (the defaults assume `COM4`). Wiring, including the ULN2003 IN2/IN3 swap, is in the [wiring guide](docs/wiring.md).

### 4. Set up the Moku:Go (one-time)

The `moku` Python client deploys an instrument bitstream (Oscilloscope / Datalogger) to the Moku:Go's FPGA at runtime, and that bitstream must match the device's MokuOS version. Install the Liquid Instruments CLI and cache the matching bitstreams once:

1. **Connect to the device.** Join the Moku:Go's Wi-Fi Access Point or wire it over Ethernet, put your PC's network adapter on the same subnet (`192.168.73.x`), and confirm it responds:
   ```bash
   ping 192.168.73.1
   ```
2. **Install the CLI.** Download and install `mokucli` from Liquid Instruments: [liquidinstruments.com/software/utilities](https://liquidinstruments.com/software/utilities/).
3. **Read the MokuOS version.** With the device reachable, list it and note the firmware version reported:
   ```bash
   mokucli list
   ```
4. **Download the matching bitstreams.** Use the version from the previous step:
   ```bash
   mokucli instrument download <mokuos_version>
   ```

Stuck on any of these? Liquid Instruments' AI support assistant covers CLI install and firmware issues: [liquidinstruments.com/support](https://liquidinstruments.com/support/).

### 5. Connect the microscope camera

Plug in the external USB microscope camera (UVC, ≥1080p). The laptop's built-in webcam (index 0) is never opened, so it stays off until a microscope camera is connected on index 1+.

### 6. Launch and connect

```bash
python ui.py
```

In the app, open the **Setup tab**, pick your Arduino COM-port and click **Connect**. The TopBar pills `Motors / Moku / Camera` should all turn green. If one stays red, recheck the cabling and power for that subsystem; the [use guide](docs/OpenSource_CDS_User_Guide.pdf) walks through the full power-on sequence.

**Defaults:** Arduino on `COM4 @ 9600 baud`, Moku at `192.168.73.1` (50 Vpp range), external microscope camera auto-detected (MJPG @ 1080p/30 fps). The laptop's built-in webcam (index 0) is never opened.

With all pills green, continue in the [use guide](docs/OpenSource_CDS_User_Guide.pdf) to align the optics, find the I0 reference, and run the calibration sweep. Recording measurements afterwards is done in the app (see [UI layout](#ui-layout) and [How it works](#how-it-works)).

---

## Hardware overview

| Subsystem | Details |
|---|---|
| **Stage** | **Unmodified [OpenFlexure Block Stage](https://openflexure.org/projects/blockstage/)** as the flexure base, with our 3× 28BYJ-48 stepper + ULN2003 driver actuators bolted on. Driven by an Arduino Nano (`COM4`, 9600 baud). Motor 1 = X, motor 2 = Y, motor 3 = Z (focus). |
| **Optical column** | Two-lens confocal path: interchangeable F1 lens (16-80 mm, code default 40 mm) with a fixed `f2 = 150 mm`, detector aperture (`r_d = 0.5 mm`), mounted vertically above the stage. Full derivation in the [research paper](#-project-hub), implementation in [`confocal.py`](confocal.py). |
| **Lamp** | Two WS2812B-8 LED rings (inner on Arduino pin A2, outer on pin A3), brightness controlled over the shared serial port |
| **Photodetector** | Moku:Go (Oscilloscope mode for live view, Datalogger mode for burst capture), IP `192.168.73.1`, 50 Vpp range |
| **Camera** | External USB microscope camera, auto-detected on indices 1+, MJPG @ 1080p / 30 fps. The laptop's built-in webcam (index 0) is never opened, so it stays off until a microscope camera is connected. |

Full pin-out, schematic and connector list → [`docs/circuit-diagram.pdf`](docs/circuit-diagram.pdf). Parts and suppliers → [`docs/OpenSource_CDS_BOM.xlsx`](docs/OpenSource_CDS_BOM.xlsx). 3D-print files and settings → [`docs/OpenSource_CDS_Printing_Guide.pdf`](docs/OpenSource_CDS_Printing_Guide.pdf).

---

## UI layout

![Confocal Displacement Sensor UI: TopBar status pills, camera feed (OFFLINE until connected), the Calibration graph tab with the fitted confocal model, and the live Moku:Go photodetector plot](assets/ui-scanning.png)

| Tab | What it does |
|---|---|
| **Manual** | One burst at the current motor position. Converts voltage to displacement with the linearized calibration line (`dz1 = (V - b) / a`) and warns if the signal leaves the linear band. Output: `data/manual_<ts>_<name>/` with `burst.csv` (raw voltage), `position.csv` (dz1), `fft.png`, and `metadata.txt`. |
| **Calibration graph** | Upload measurement points (dz1, I_m) as Excel/CSV, fit the confocal A6 model and linearize around I0/2. The fitted line is the source of truth the Manual tab uses for the voltage to displacement conversion. |
| **Setup** | Connect, jog in exact micron steps, soft-home ("Set 0 here"), set speed, restore the last saved position. |
| **Camera** | Exposure, brightness, contrast, auto-exposure, grayscale, plus the inner and outer lamp brightness controls. |

Step-by-step optical alignment and calibration → [`docs/OpenSource_CDS_User_Guide.pdf`](docs/OpenSource_CDS_User_Guide.pdf).

---

## How it works

The voltage to displacement conversion is built in two steps.

1. **Calibrate (once per setup).** In the **Calibration graph** tab you upload measured `(dz1, I_m)` points. The confocal A6 model is fitted to them, and the steep middle of the curve (around I0/2) is linearized into a straight line `I_m = a·dz1 + b`. That line, with its valid voltage band `[lo, hi]`, is what every later measurement uses.

2. **Measure (per point).** In the **Manual** tab the stage settles to a halt, the Moku:Go records a high-sample-rate voltage burst from the photodetector, and the burst is saved as raw CSV. Each sample is converted to an axial displacement with the inverted line `dz1 = (V - b) / a`. If part of the burst leaves the linear band, the UI raises a warning, because the displacement there would be an extrapolation. Each burst is FFT-analysed to show the vibration spectrum at that point.

Repeating step 2 across a grid of positions (repositioned with the Setup tab jog controls) builds the 3D dataset `(x, y, frequency) → amplitude`.

Full theoretical background and derivations: see the [research paper](#-project-hub).

---

## Repository layout

| File | Role |
|---|---|
| `ui.py` | Main window, CameraThread (microscope-camera auto-detect), MotorPanel, MokuPanel, TopBar, layout |
| `recording.py` | Manual burst (one click = one measurement), voltage to dz1 via the calibration line, FFT popup |
| `calibration_graph.py` | Calibration graph tab: upload points, fit the A6 model + linearization, plot, save results |
| `ml.py` | Confocal A6 model fit (learns q, r0) and the linearization around I0/2 |
| `lamp.py` | WS2812B brightness via slider, throttled @ 20 updates/s (inner + outer rings) |
| `camera_settings.py` | Exposure / brightness / contrast / auto-exposure / grayscale (Camera tab) |
| `datalogger.py` | Moku Datalogger wrapper, streaming burst acquisition (raw voltage) |
| `calibration.py` | Persistence of mm/step + last position → `calibration.yaml` |
| `confocal.py` | Physics core: formula A6, `compute_q` / `Im` / `dz1` / `Sm` (sympy + numpy) |
| `gridsearch.py` | Sweep over f1/f2 → measurement-range analysis → CSV (standalone) |
| `viewer.py` | 3D plot + heatmap of scan data (standalone CLI) |
| `styles.qss` | Qt stylesheet (design tokens) |
| `arduino/firmware/firmware.ino` | Nano firmware: AccelStepper + NeoPixel, ASCII command protocol |

---

## 🧱 Built on top of

This instrument uses the open-hardware **[OpenFlexure Block Stage](https://openflexure.org/projects/blockstage/)** ([GitLab source](https://gitlab.com/openflexure/openflexure-block-stage)) by the OpenFlexure project as its 3-axis flexure base. We use the block stage **completely unmodified**: our confocal optical column, stepper actuators, electronics housing, and illumination are designed as a **bolt-on extension** that mounts to the standard block stage without any changes to its parts.

Two practical consequences:

- **If you already own an OpenFlexure Block Stage**, you only need to print our additional confocal-extension parts and bolt them on. No re-print or modification of the stage itself.
- **The extension is reversible**: unbolt our parts and the block stage returns to its original state and original use cases (microscopy, etc.).

Every part of our confocal setup is deliberately designed to be straightforward to modify for users with non-standard requirements (different optics, sample sizes, illumination, mounting).

| Aspect | Source |
|---|---|
| 3-axis flexure stage | **OpenFlexure Block Stage** (used unmodified) |
| Stepper actuators + electronics | Our own design (mounts to the unmodified stage) |
| Confocal optical column (f1, f2, aperture, photodetector) | Our own design |
| Software (UI, firmware, analysis, paper) | Our own work |

**Licensing.** The OpenFlexure Block Stage is licensed under **CC BY-SA 4.0** (Attribution + ShareAlike). Because we use it unmodified, our extension parts are technically not a "derivative" of the stage's CAD. We still release our extension under **CC BY-SA 4.0** to keep the open-hardware chain intact and to match the upstream licence. Our software is independent and uses the permissive MIT licence (see [License](#license)).

**Attribution.** When using or referencing this project's hardware:

> *Confocal extension for the [OpenFlexure Block Stage](https://openflexure.org/projects/blockstage/) by the OpenFlexure project, © OpenFlexure, CC BY-SA 4.0.*

---

## Credits

Bachelor End Project for the *Precision and Micro-Engineering* track, **TU Delft**, academic year 2025–2026.
Course `WBMT3BEP`, project code `PME-2026-A06`.

**Team:** Dafne Gyselinck · Jayden Jhagru · Harmen Klerk · Ties van Lohuizen · Stef Wiegman.

**Supervisors:** Ruben Guis & Gerard Verbiest.

Hardware base: **OpenFlexure Block Stage** by the OpenFlexure project (CC BY-SA 4.0).

---

## License

This project combines our own software with hardware derived from an open-hardware base, so it uses **two licences**:

| Part | Licence | File |
|---|---|---|
| **Software** (Python, Arduino firmware, Qt stylesheets) | **MIT** | [`LICENSE`](LICENSE) |
| **Hardware / CAD** (3D-print files, STEP/STL release) | **CC BY-SA 4.0** | [`LICENSE.hardware`](LICENSE.hardware) |
| **Documentation** (this README, `docs/`, research paper) | **CC BY-SA 4.0** | [`LICENSE.hardware`](LICENSE.hardware) |

The hardware and documentation use CC BY-SA 4.0 to match the upstream [OpenFlexure Block Stage](#-built-on-top-of); the software is independent and uses the permissive MIT licence. See [Built on top of](#-built-on-top-of) for the rationale.

Copyright held jointly by the BEP team (Dafne Gyselinck, Jayden Jhagru, Harmen Klerk, Ties van Lohuizen, Stef Wiegman), 2026.
