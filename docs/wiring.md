# Wiring Guide

> Full pin-out and electrical connection reference for the confocal displacement sensor.
> Pair with the [BOM](OpenSource_CDS_BOM.xlsx) for part numbers and the [assembly video](../README.md#-project-hub) for visual reference.

> 🚧 **Status:** Skeleton, diagram and photos to be added.

---

## System overview

```
                ┌──────────────┐
   USB ─────────│ Arduino Nano │──── A2 ──► WS2812B-8 ring (lamp)
                │              │──── D2..D5  ──► ULN2003 #1 ──► Stepper X (28BYJ-48)
                │              │──── D6..D9  ──► ULN2003 #2 ──► Stepper Y (28BYJ-48)
                │              │──── D10..D13 ─► ULN2003 #3 ──► Stepper Z (28BYJ-48)
                └──────────────┘
   Ethernet ────► Moku:Go (192.168.73.1) ────► photodetector input
   USB ─────────► Webcam (index 0)
```

> ⚠️ This build uses the simple **ULN2003 + 28BYJ-48** combo, **not** an A4988 / CNC-shield setup. Pin assignments below assume that hardware.

---

## Pin map for the Arduino Nano

| Function | Pin | Notes |
|---|---|---|
| Stepper X IN1 | D2 | ULN2003 board #1 |
| Stepper X IN2 | **D4** | ⚠️ IN2/IN3 are swapped relative to the printed silk on most ULN2003 boards to match `AccelStepper` `FULL4WIRE` coil order |
| Stepper X IN3 | **D3** | swapped (see above) |
| Stepper X IN4 | D5 | |
| Stepper Y IN1 | D6 | ULN2003 board #2 |
| Stepper Y IN2 | **D8** | swapped |
| Stepper Y IN3 | **D7** | swapped |
| Stepper Y IN4 | D9 | |
| Stepper Z IN1 | D10 | ULN2003 board #3 |
| Stepper Z IN2 | **D12** | swapped |
| Stepper Z IN3 | **D11** | swapped |
| Stepper Z IN4 | D13 | also drives the on-board LED, fine, ignore the blink |
| LED ring data | A2 | WS2812B-8, single data line |
| GND | GND | Common ground for steppers, LEDs, Nano |
| 5 V (lamp) | 5V | WS2812B-8 power, fine from Nano USB for low brightness, external supply recommended at full brightness |

> 💡 The IN2/IN3 swap is intentional and matches the firmware. If your motors hum or twitch but don't rotate, you've probably wired straight-through, swap IN2 and IN3 on each driver.

---

## Power

> 🚧 TODO:
> - Stepper supply: USB 5 V is enough for low-load jogging; for sustained scans a separate 5 V / 2 A supply on the ULN2003 boards is recommended.
> - Common-ground note: tie all GNDs (Nano, stepper PSU, LED ring) together at one point.
> - Decoupling caps on the LED ring (1000 µF across VCC/GND close to the ring).

---

## Moku:Go connection

- Connect Moku:Go to your PC via Ethernet, set the PC's adapter to the same subnet as `192.168.73.1`.
- Photodetector signal → Moku:Go input 1 (BNC), <!-- TODO: confirm input number -->.
- The software auto-switches Moku between Oscilloscope (live view) and Datalogger (burst capture) modes. See [`datalogger.py`](../datalogger.py).

---

## Camera

- Any UVC-compatible USB webcam works. Default = index 0.
- For best confocal-spot imaging, fix the camera mechanically so its FOV is co-axial with the optical path. <!-- TODO: photo of mounting bracket -->

---

## Schematic

> 🚧 TODO: insert annotated schematic image (Fritzing / KiCad / hand-drawn). Suggested layout: top half = Arduino + drivers + steppers, bottom half = Moku:Go + camera + power supply.

## Photos

> 🚧 TODO: add reference photos of the wired electronics enclosure.
