# Next steps

## Extension
- [ ] README: review the first version (preamble, haversack inputs, install, usage, results, outputs).
- [ ] Module help (`parent.helpText`: inputs, outputs, link to the docs) and acknowledgement (`parent.acknowledgementText`: funding, VeScan citation).
- [ ] Module category (now "Chest Imaging").
- [ ] `EXTENSION_SCREENSHOTURLS` in the top-level `CMakeLists.txt` (raw GitHub URLs of `docs/screenshots/`, after the push).
- [ ] Rename the GitHub repo `SlicerVEScan` → `SlicerVeScan` (homepage and icon URLs already use the new name); optionally the local folder too (then update Slicer's additional module path).
- [ ] Test with a small sample case in `VeScanTest` (now: geometry and config only).

## VeScan-field
- [ ] Tag `v0.1.1` has `version = "0.1.0"` in `pyproject.toml`: bump the version in VESCAN_develop before the next public release.
- [ ] New release: new tag, update the URL in `VeScan/Resources/requirements.txt`, copy `ColorTable*_EN.csv` and check `configs/field/example.json` against `VeScan/Resources/vescan_field.json`.

## Later
- [ ] VMTK method (`vmtkRadio` is disabled): postponed.
