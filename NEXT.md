# Next steps

Status: the module runs VE-SCAN field in Slicer. Slicer loads the inputs (nodes or files), vescan_field computes and
saves (VE-SCAN's output layout), each output is shown in 3D as soon as it is written. Every parameter not in the UI is
in [VEScan/Resources/vescan_field.json](VEScan/Resources/vescan_field.json) (loaded with `vescan_field.config`).

## Connect VE-SCAN
VE-SCAN field is the package `vescan-field` (`pyproject.toml` in VESCAN_develop). Development install into Slicer,
always with numpy pinned to Slicer's version (otherwise pip upgrades it to numpy 2 and breaks Slicer):
`/Applications/Slicer.app/Contents/bin/PythonSlicer -m pip install -e ~/Desktop/VESCAN_develop "numpy==1.26.4"`
- [x] Import `vescan_field` inside the logic methods (module opens without it).
- [x] `loadCT`, `loadStructure`, `loadStore`, `loadLobes`: Slicer loaders, masks as arrays on the CT grid.
- [x] `run`: stage by stage (`stages.<name>.run(ctx, cfg)`, no orchestrator), config from the bundled JSON.
- [x] `getGenerationRange`, `previewCut`, `applyCut` (`stages.clip.run`).
- [x] `loadResults`, `setVisibility`, `setColorBy`, `focusCrossing`, `exportStatistics`.
- [ ] For users: `requirements.txt` with `vescan-field @ git+...@<tag>` + `slicer.packaging.pip_ensure` on Run, pinning numpy to `numpy.__version__`.
- [ ] Cancel acts only between steps (a step can take ~25 s); a background run would also keep the UI fully responsive.
- [x] Colour tables: VE-SCAN's `ColorTable*_EN.csv` (copied in `VEScan/Resources/ColorTables/`, keep in sync with VESCAN_develop).
- [ ] Lobes are coloured by the `LobeSegment_*` array of the first structure run; a choice in the UI could be added.
- [x] CT optional: it is only the reference grid; without it, the grid of the first structure mask (as vescan).

## UI / parameter node
- [ ] Save the segment of each `qMRMLSegmentSelectorWidget` in the parameter node (segmentation node + segment ID).
- [ ] Save the lobe → segment mapping of `lobesTable` in the parameter node (the lobe file paths are saved, `lobesPaths`).
- [ ] Scene inputs (segment selectors) are not shown in 3D on selection, only file inputs are loaded and shown.
- [ ] Paths and generation sliders are synced by hand (see `VEScanWidget.setup`): keep them restored on scene load.
- [ ] VMTK method (`vmtkRadio` is disabled).
- [ ] Show the Cut tree / Results sections again when reopening a scene that already has results.

## Extension
- [ ] Module category (now "Chest Imaging") and help text with a link to the docs.
- [ ] Icon, screenshot, description and homepage in the top-level `CMakeLists.txt`.
- [ ] Test with a small sample case in `VEScanTest` (now: geometry and config only).
