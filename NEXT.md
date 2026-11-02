# Next steps

Status: UI mockup done (all widgets from [docs/ui_layout.md](docs/ui_layout.md), logic stubs only log).

## Connect VE-SCAN
- [ ] `loadCT`, `loadStructure`, `loadStore`, `loadLobes`: real loading (scene node or file).
- [ ] `run`: call the VE-SCAN pipeline; build the config from `VEScanParameterNode`.
- [ ] Run in the background (process / thread) so the UI does not freeze; real `cancel`.
- [ ] `getGenerationRange`, `previewCut`, `applyCut` on the computed centerlines.
- [ ] `loadResults`: models, centerlines, crossings table filled from the output folder.
- [ ] `setVisibility`, `setColorBy`, `focusCrossing`, `exportStatistics`.

## UI / parameter node
- [ ] Save the segment of each `qMRMLSegmentSelectorWidget` in the parameter node (segmentation node + segment ID).
- [ ] Save the lobe → label mapping of `lobesTable` in the parameter node.
- [ ] Paths and generation sliders are synced by hand (see `VEScanWidget.setup`): keep them restored on scene load.
- [ ] VMTK method (`vmtkRadio` is disabled).
- [ ] Show the Cut tree / Results sections again when reopening a scene that already has results.

## Extension
- [ ] Module category (now "Chest Imaging") and help text with a link to the docs.
- [ ] Icon, screenshot, description and homepage in the top-level `CMakeLists.txt`.
- [ ] Real tests with a small sample case in `VEScanTest`.
