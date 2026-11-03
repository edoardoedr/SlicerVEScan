# Next steps

Status: the module runs VeScan field in Slicer. Slicer loads the inputs (nodes or files), vescan_field computes and
saves (VeScan's output layout), each output is shown in 3D as soon as it is written. Every parameter not in the UI is
in [VeScan/Resources/vescan_field.json](VeScan/Resources/vescan_field.json) (loaded with `vescan_field.config`).

## Connect VeScan
VeScan field is the package `vescan-field` (`pyproject.toml` in VESCAN_develop). Development install into Slicer,
always with numpy pinned to Slicer's version (otherwise pip upgrades it to numpy 2 and breaks Slicer):
`/Applications/Slicer.app/Contents/bin/PythonSlicer -m pip install -e ~/Desktop/VESCAN_develop "numpy==1.26.4"`
- [x] Import `vescan_field` inside the logic methods (module opens without it).
- [x] `loadCT`, `loadStructure`, `loadStore`, `loadLobes`: Slicer loaders, masks as arrays on the CT grid.
- [x] `run`: stage by stage (`stages.<name>.run(ctx, cfg)`, no orchestrator), config from the bundled JSON.
- [x] `getGenerationRange`, `previewCut`, `applyCut` (`stages.clip.run`).
- [x] `loadResults`, `setVisibility`, `setColorBy`, `focusCrossing`, `exportStatistics`.
- [x] Public VeScan repo: https://github.com/edoardoedr/VeScan-field (public copy of VESCAN_develop, `vescan-field` 0.1.0).
- [x] Tag `v0.1.0` (commit 31fe9eb); `vescan_field.json` and colour tables are in sync with its `configs/field/example.json` and `ColorTable*_EN.csv`.
- [x] README links VeScan-field (extension homepage stays the SlicerVeScan repo).
- [x] For users: `Resources/requirements.txt` (tag archive `v0.1.0`, no git needed) installed by `ensureVescanField` on the first Run / lobe loading, after confirmation, with numpy pinned to `numpy.__version__` (`slicer.packaging` is not in Slicer 5.10). New VeScan version: new tag + update the URL.
- [x] Colour tables: VeScan's `ColorTable*_EN.csv` (copied in `VeScan/Resources/ColorTables/`, keep in sync with VESCAN_develop).
- [x] Lobes colour: "Lobes color by" in Results (`LobeSegment_Artery` / `_Vein` / `_Airway`, `FissureContact`), table `ColorTableLobesFissures_EN`.
- [x] Colour legends in 3D (`updateLegends`): Color by on the right, Lobes color by on the left (only the classes of the chosen array); "Color legends" in Results → Show.
- [x] CT optional: it is only the reference grid; without it, the grid of the first structure mask (as vescan).
- [x] Output folder optional: empty = temporary folder in Slicer's temporary path (vescan's stages exchange files),
  removed on scene close or with the next run; required when Preprocess or Centerlines is off (reads a previous run).

## UI / parameter node
- [x] Segment selectors saved in the parameter node (`<input>Segmentation` + `<input>SegmentId`, synced in `_onSegmentChanged`, restored in `setParameterNode`); a segmentation alone selects its first segment.
- [x] Lobe table: a lobe without a file/label is None (status under the table); VeScan runs on the set lobes (`pipeline.lobes.enabled`, partial lobe scheme), Run needs at least one.
- [x] Lobe table saved in the parameter node (`lobesMapping`, segment names), restored when the lobes are loaded again if its segments exist; new lobe files map automatically.
- [x] Scene inputs shown on selection (`showSceneSegments`): only the chosen segments of a segmentation in 3D (colours
  unchanged), its 3D visibility restored when no input uses it; CT in the slice views, lobes at 30% opacity.
- [x] Paths and generation sliders are synced by hand (see `VeScanWidget.setup`) and restored on scene load.
- [ ] VMTK method (`vmtkRadio` is disabled): postponed, not planned for now.
- [x] Scene reopened: the module's nodes carry attributes (`VeScan.Input`, `VeScan.Model`, `VeScan.Table`) and
  `restoreFromScene` rebuilds the logic (no file loaded twice), the lobe table, Cut tree and Results; Apply cut only if
  the run's files are still in the output folder.

## Extension
- [ ] Write the module help (`parent.helpText`: inputs, outputs, link to the docs) and the acknowledgement (`parent.acknowledgementText`: funding, VeScan citation).
- [ ] Module category (now "Chest Imaging").
- [x] Logo: `docs/logo/vescan_logo_512.png`; its 128 px version is the extension icon (`SlicerVeScan.png`) and the module icon.
- [x] Screenshots (patient R01-015) in `docs/screenshots/`, clipping GIF `docs/screenshots/clipping.gif`.
- [ ] README with logo, screenshots and GIF; `EXTENSION_SCREENSHOTURLS` in the top-level `CMakeLists.txt` (raw GitHub URLs, after the push).
- [ ] Test with a small sample case in `VeScanTest` (now: geometry and config only).
