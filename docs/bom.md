# Bill of Materials (BOM)

> Everything you need to build one confocal displacement sensor.
> Pair with the [wiring guide](wiring.md) for connections and the [3D-print guide](print-guide.md) for printed parts.

> 🚧 **Status:** Skeleton — prices and supplier links to be filled in.

Last updated: <!-- TODO: date -->

---

## Electronics

| Qty | Item | Notes | Supplier | Approx. price |
|---:|---|---|---|---:|
| 1 | Arduino Nano (ATmega328P, USB-B mini) | The brain | <!-- TODO --> | <!-- TODO --> |
| 3 | 28BYJ-48 stepper motor (5 V) | X, Y, Z axes | <!-- TODO --> | <!-- TODO --> |
| 3 | ULN2003 driver board | One per stepper, usually sold paired with the motor | <!-- TODO --> | <!-- TODO --> |
| 1 | WS2812B 8-LED ring | Sample illumination | <!-- TODO --> | <!-- TODO --> |
| 1 | Moku:Go | Photodetector front-end (Oscilloscope + Datalogger) | Liquid Instruments | <!-- TODO --> |
| 1 | USB webcam (UVC, ≥1080p/30 fps) | Visual feedback in UI | <!-- TODO --> | <!-- TODO --> |
| 1 | Photodetector | <!-- TODO: exact PD model + spec --> | <!-- TODO --> | <!-- TODO --> |
| 1 | 5 V / 2 A power supply | For LED ring + steppers under load | <!-- TODO --> | <!-- TODO --> |
| — | Jumper wires, dupont cables | At least 3× 4-way ribbons for the steppers | <!-- TODO --> | <!-- TODO --> |
| — | USB-B mini cable | Nano ↔ PC | any | low |
| — | Ethernet cable | Moku:Go ↔ PC | any | low |

## Optics

> 🚧 TODO — list lenses, mirrors, beam-splitter, pinhole/aperture, laser/LED source, mounts. Include focal lengths used in the model (`f1 = 25 mm`, `f2 = 150 mm`).

| Qty | Item | Spec | Supplier | Approx. price |
|---:|---|---|---|---:|
| 1 | Lens 1 | f = 25 mm | <!-- TODO --> | <!-- TODO --> |
| 1 | Lens 2 | f = 150 mm | <!-- TODO --> | <!-- TODO --> |
| 1 | Pinhole / detector aperture | r_d = 0.5 mm | <!-- TODO --> | <!-- TODO --> |
| 1 | Light source | <!-- TODO: laser diode / LED + wavelength --> | <!-- TODO --> | <!-- TODO --> |

## Mechanical / structural

> See the [3D-print guide](print-guide.md) for printed parts.

| Qty | Item | Notes | Supplier | Approx. price |
|---:|---|---|---|---:|
| — | M3 / M4 bolts + nuts | <!-- TODO: full hardware list --> | <!-- TODO --> | <!-- TODO --> |
| — | Linear rails / guides | <!-- TODO: if any --> | <!-- TODO --> | <!-- TODO --> |
| 1 | Base plate | <!-- TODO: material, dimensions --> | <!-- TODO --> | <!-- TODO --> |

## Sample

| Qty | Item | Notes |
|---:|---|---|
| 1 | MEMS device under test | <!-- TODO: example device + how it's driven --> |

---

## Total estimated cost

> 🚧 TODO — tally once supplier prices are in.

---

## Notes on substitutions

- **Stepper choice:** the 28BYJ-48 is cheap and quiet but limited in torque and resolution. A NEMA-17 + A4988/DRV8825 + 32-bit driver board would be a drop-in upgrade with a firmware change (different pin map + `AccelStepper` constructor). See `arduino/firmware/firmware.ino`.
- **Moku:Go:** the most expensive item by far. Any 2-channel oscilloscope + DAQ with ≥1 MSa/s streaming would work, but the software is currently tightly coupled to the `moku` Python SDK.
