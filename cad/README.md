# CAD files

Print files for the confocal displacement sensor: our confocal extension (STEP source) plus the OpenFlexure Block Stage it mounts to (STL).

## What's here

| Folder | Contents |
|---|---|
| `step/` | 51 STEP source files for every part of our confocal extension. Open directly in your slicer (Cura, PrusaSlicer, OrcaSlicer) to print, or import in a CAD package (FreeCAD, SolidWorks, Onshape, Fusion 360) to modify. |
| `stl/` | 6 STL meshes of the OpenFlexure Block Stage (the 3-axis flexure base), redistributed unmodified so you can print a complete instrument from one place. Slice and print as-is. |

## Part naming

Files are grouped by category prefix:

| Prefix | Category | Examples |
|---|---|---|
| `BASE_*` | Base and structural parts | `BASE_base.step`, `BASE_bridge.step`, `BASE_electro.step` |
| `BLOCKS_*` | Modular optical blocks (camera, detector, lens, mirror, laser, spacers, red filter) | `BLOCKS_f1_block.step`, `BLOCKS_detector_block.step`, `BLOCKS_spacer_0.4.step` |
| `CALIBRATION_*` | Calibration jigs, spacers and tools | `CALIBRATION_spacer_0.4.step`, `CALIBRATION_table_calibrator.step` |
| `STAGE_*` | OpenFlexure Block Stage parts, in `stl/` | `STAGE_main_body.stl`, `STAGE_gears.stl`, `STAGE_moving_platform.stl` |

## The block stage

The `stl/` folder holds the **[OpenFlexure Block Stage](https://gitlab.com/openflexure/openflexure-block-stage)** parts, redistributed **unmodified** under CC BY-SA 4.0. If you already own a printed and assembled block stage, skip the `STAGE_*` STL and print only the `step/` extension parts. For the latest stage sources, parameters and updates, use the upstream OpenFlexure repo.

## How to print

1. Open the relevant `.step` (extension) or `.stl` (stage) file in your slicer (Cura, PrusaSlicer, OrcaSlicer)
2. Apply the recommended settings from [`../docs/OpenSource_CDS_Printing_Guide.pdf`](../docs/OpenSource_CDS_Printing_Guide.pdf)
3. Print, post-process, and assemble per the [assembly video](https://www.youtube.com/watch?v=UzMbLptgHZc)

## How to modify

Open a `.step` file in any parametric CAD package (FreeCAD is free and open-source; SolidWorks, Onshape, Fusion 360 also work). The feature tree is preserved so you can adjust dimensions, mounting points, etc. to fit your own setup. The `STAGE_*` parts are provided as STL meshes only; modify those via the upstream OpenFlexure sources.

## Licence

CC BY-SA 4.0. See [`../LICENSE.hardware`](../LICENSE.hardware) for the full text and the rationale for matching the upstream OpenFlexure licence.

When forking or remixing, please credit:

> *Confocal extension for the [OpenFlexure Block Stage](https://openflexure.org/projects/blockstage/) by the OpenFlexure project, (c) OpenFlexure, CC BY-SA 4.0.*

The bundled `stl/STAGE_*` parts are the OpenFlexure Block Stage by the OpenFlexure project (CC BY-SA 4.0), redistributed unmodified.
