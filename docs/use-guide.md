# Use Guide

> How to operate the confocal displacement sensor once it is assembled and connected.
> If you are building one, start with the [3D-print guide](print-guide.md), [BOM](bom.md) and [wiring guide](wiring.md) first.

> 🚧 **Status:** Skeleton — screenshots and step-by-step procedures to be filled in.

---

## 1. First-time setup

> 🚧 TODO — fill in once verified end-to-end.

Checklist:
- [ ] Arduino Nano connected via USB (default `COM4`)
- [ ] Moku:Go reachable at `192.168.73.1` (ping from the PC)
- [ ] USB webcam visible as device 0
- [ ] Sample mounted on the stage
- [ ] Photodetector aligned, lamp on at moderate brightness

Launch the app:

```powershell
.venv\Scripts\Activate.ps1
python ui.py
```

---

## 2. Connect

In the **Setup** tab:

1. Pick the correct COM-port (default `COM4`) and click **Connect**.
2. The TopBar status pills (`Motors`, `Moku`, `Camera`) should all turn green.
3. The previous calibration (`calibration.yaml`) is restored automatically. If positions don't match what's stored, the UI shows a restore prompt — confirm if the stage is physically still where you left it, otherwise reject and re-home.

---

## 3. Calibrate

> 🚧 TODO — describe the mm-per-step calibration procedure for each axis.

In short:
1. Jog the stage by a known number of steps using the **Setup** tab jog buttons.
2. Measure the physical displacement.
3. Enter `mm_per_step = displacement_mm / steps` for each axis.
4. Click **Save calibration** in the TopBar.

The values persist in `calibration.yaml`.

---

## 4. Set I0 (zero reference)

The conversion from photodetector voltage to displacement `dz1` needs a reference intensity `I0`.

1. Position the sample so the confocal spot is at the desired reference plane.
2. Go to the **Manual** tab.
3. Click **Set I0** — the app averages the current photodetector voltage and stores it.
4. Subsequent bursts will be saved with both `voltage_V` and `dz1_mm` columns.

> Without `I0`, bursts still record `voltage_V` — you can compute `dz1` offline later.

---

## 5. Run a manual burst

In the **Manual** tab:

1. Jog the stage to the point of interest.
2. Enter a name (optional) and burst settings (sample rate, duration).
3. Click ▶ **Record**.

**Output:**

```
data/manual_<timestamp>_<name>/
├── burst.csv          # columns: t_s, voltage_V, dz1_mm (if I0 set)
└── metadata.txt       # position, settings, I0, calibration
```

---

## 6. Run an automatic scan

In the **Auto Scan** tab:

1. Set the scan area in mm, resolution (number of points per axis), settle time, sample rate and burst duration.
2. Click ▶ **Start scan**.

The state machine drives each grid point in a snake pattern: `GOTO target → poll BUSY? → settle → Datalogger burst → save → next point`.

**Output:**

```
data/scan_<timestamp>_<name>/
├── index.csv          # one row per point: x_mm, y_mm, file
└── raw/
    ├── point_00000.csv
    ├── point_00001.csv
    └── …
```

You can stop a scan at any time — already-recorded points are preserved.

---

## 7. Analyse data

> 🚧 TODO — document the FFT / spectrum workflow.

- Each `point_NNNNN.csv` is a time-series ready for FFT.
- Use `viewer.py` (standalone CLI) for a quick 3D plot or heatmap of a scan.
- For the per-point frequency analysis, <!-- TODO: link or describe the analysis script -->.

---

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Status pill stays red after Connect | Wrong COM port / Arduino not flashed | Check Device Manager; re-flash `arduino/firmware/firmware.ino` |
| Motors hum but don't move | IN2/IN3 not swapped on the ULN2003 | See [wiring guide](wiring.md#pin-map--arduino-nano) |
| Moku pill red | Moku:Go on a different subnet | Set PC adapter to `192.168.73.x`; confirm with `ping 192.168.73.1` |
| Camera black | Another app holds the webcam (Teams, Zoom) | Close it, restart `ui.py` |
| Position-mismatch prompt on connect | Stage was moved while disconnected | Reject the restore, re-home with **Set 0 here** |

> 🚧 TODO — add more entries as you encounter them.
