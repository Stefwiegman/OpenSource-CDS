# 3D-Print Guide

> Print settings, part list and assembly notes for the 3D-printed parts of the confocal displacement sensor.
> Pair with the [CAD files](../README.md#-project-hub), [BOM](bom.md) for non-printed hardware, and the [assembly video](../README.md#-project-hub) for build order.

> 🚧 **Status:** Skeleton — exact part list and tested settings to be filled in.

---

## Recommended print settings

> 🚧 TODO — confirm with what we actually printed.

| Setting | Value | Why |
|---|---|---|
| Material | PLA <!-- or PETG --> | Stiff enough at room temp; easy to print |
| Layer height | 0.2 mm | Good speed/accuracy compromise |
| Wall count | 4 | Stiffness for stepper mounts |
| Top / bottom layers | 5 / 5 | |
| Infill | 30–40 % gyroid | Stiffness without long print times |
| Supports | Only where overhangs > 50° | Minimise post-processing |
| Print speed | 50 mm/s outer wall, 80 mm/s infill | |
| Nozzle | 0.4 mm | |
| Bed adhesion | Brim, 5 mm | Some parts have small footprints |

> 💡 For optical-path parts (lens holders, beam-splitter mount) print in black filament to suppress stray light, or paint the inside matte black after printing.

---

## Part list

> 🚧 TODO — fill in once CAD is finalised.

| Part | Qty | File | Print time | Material | Notes |
|---|---:|---|---:|---|---|
| Base plate | 1 | `cad/base.stl` <!-- TODO --> | <!-- TODO --> | PLA | |
| X-axis stepper mount | 1 | <!-- TODO --> | <!-- TODO --> | PLA | |
| Y-axis stepper mount | 1 | <!-- TODO --> | <!-- TODO --> | PLA | |
| Z-axis stepper mount | 1 | <!-- TODO --> | <!-- TODO --> | PLA | |
| Sample carrier | 1 | <!-- TODO --> | <!-- TODO --> | PLA | |
| Lens holder f=25 mm | 1 | <!-- TODO --> | <!-- TODO --> | PLA (black) | |
| Lens holder f=150 mm | 1 | <!-- TODO --> | <!-- TODO --> | PLA (black) | |
| Detector mount | 1 | <!-- TODO --> | <!-- TODO --> | PLA (black) | |
| Lamp ring bracket | 1 | <!-- TODO --> | <!-- TODO --> | PLA | |
| Camera bracket | 1 | <!-- TODO --> | <!-- TODO --> | PLA | |
| Electronics enclosure | 1 | <!-- TODO --> | <!-- TODO --> | PLA | |
| Electronics enclosure lid | 1 | <!-- TODO --> | <!-- TODO --> | PLA | |

**Total estimated print time:** <!-- TODO --> h
**Total filament:** <!-- TODO --> g

---

## Tolerances and post-processing

> 🚧 TODO:
> - Note bores that need a 3.2 mm drill pass for M3 clearance.
> - Note any heat-set inserts.
> - Note where to ream / sand for stepper-shaft fit.

---

## Assembly notes (printed parts only)

For full assembly with electronics and optics, see the [assembly video](../README.md#-project-hub).

> 🚧 TODO — short order-of-assembly list once the build is verified.

1. Print all parts first, dry-fit before glueing anything.
2. Assemble axes bottom-up: base plate → Z mount → Y mount → X mount → sample carrier.
3. Mount steppers with M3×8 bolts; tighten in a star pattern.
4. <!-- TODO -->

---

## Known issues / revisions

> 🚧 TODO — log here when a part is revised, so anyone re-printing knows what version to use.

| Date | Part | Change | Reason |
|---|---|---|---|
| <!-- TODO --> | <!-- TODO --> | <!-- TODO --> | <!-- TODO --> |
