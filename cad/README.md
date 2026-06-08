# CAD files

STEP source files for the confocal extension that mounts to the unmodified [OpenFlexure Block Stage](https://openflexure.org/projects/blockstage/).

## What's here

| Folder | Contents |
|---|---|
| `step/` | 38 STEP source files for every part of the confocal extension. Open directly in your slicer (Cura, PrusaSlicer, OrcaSlicer) to print, or import in a CAD package (FreeCAD, SolidWorks, Onshape, Fusion 360) to modify. |

## Part naming

Files are grouped by category prefix:

| Prefix | Category | Examples |
|---|---|---|
| `BASE_*` | Base and structural parts | `BASE_base.step`, `BASE_bridge.step`, `BASE_electro.step` |
| `BLOCKS_*` | Modular optical blocks (camera, detector, lens, mirror, laser, spacers, red filter) | `BLOCKS_f1_block.step`, `BLOCKS_detector_block.step`, `BLOCKS_spacer_0.4.step` |
| `CALIBRATION_*` | Calibration jigs and tools | `CALIBRATION_table_calibrator.step` |

## You also need the block stage

This folder contains **only** our confocal extension parts. The 3-axis flexure stage that everything bolts onto is the **[OpenFlexure Block Stage](https://gitlab.com/openflexure/openflexure-block-stage)**: print and assemble that separately from their GitLab repo before adding our parts on top.

## How to print

1. Open the relevant `.step` file in your slicer (Cura, PrusaSlicer, OrcaSlicer)
2. Apply the recommended settings from [`../docs/OpenSource_CDS_Printing_Guide.pdf`](../docs/OpenSource_CDS_Printing_Guide.pdf)
3. Print, post-process, and assemble per the [assembly video](https://www.youtube.com/watch?v=UzMbLptgHZc)

## How to modify

Open the `.step` file in any parametric CAD package (FreeCAD is free and open-source; SolidWorks, Onshape, Fusion 360 also work). The feature tree is preserved so you can adjust dimensions, mounting points, etc. to fit your own setup.

## Licence

CC BY-SA 4.0. See [`../LICENSE.hardware`](../LICENSE.hardware) for the full text and the rationale for matching the upstream OpenFlexure licence.

When forking or remixing, please credit:

> *Confocal extension for the [OpenFlexure Block Stage](https://openflexure.org/projects/blockstage/) by the OpenFlexure project, (c) OpenFlexure, CC BY-SA 4.0.*
