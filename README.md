# SlicerVEScan

3D Slicer extension for [VE-SCAN](https://github.com/edoardoedr/VESCAN_develop): centerline trees of the pulmonary arteries, veins and airways, anatomical branch labels, crossing vessels and tree cutting.

Status: mockup. The module `VEScan` is the Extension Wizard template (Slicer `main`); the UI and the stub functions are being built from [docs/ui_layout.md](docs/ui_layout.md), and the VE-SCAN core will be connected afterwards.

## Develop

1. Slicer: Edit → Application Settings → Developer → *Enable developer mode*, restart.
2. Application Settings → Modules → *Additional module paths*: add the `VEScan/` folder of this repo, restart.
3. Edit `VEScan/VEScan.py` or `VEScan/Resources/UI/VEScan.ui` (button *Edit UI* opens Qt Designer), then *Reload* in the module panel.
