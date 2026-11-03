# Next steps

## Extension
- [ ] Module help (`parent.helpText`: inputs, outputs, link to the docs) and acknowledgement (`parent.acknowledgementText`: funding, VeScan citation).
- [ ] Module category (now "Chest Imaging").
- [ ] `EXTENSION_SCREENSHOTURLS` in the top-level `CMakeLists.txt` (raw GitHub URLs of `docs/screenshots/`, after the push).
- [ ] Rename the GitHub repo `SlicerVEScan` → `SlicerVeScan` (homepage and icon URLs already use the new name); optionally the local folder too (then update Slicer's additional module path).
- [ ] Test with a small sample case in `VeScanTest` (now: geometry and config only).

## VeScan-field
- [ ] At each new release: `python3 tools/sync_vescan.py <tag>`, review the reported config differences, commit.

## Later
- [ ] VMTK method (`vmtkRadio` is disabled): postponed.
