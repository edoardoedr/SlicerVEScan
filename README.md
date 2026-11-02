# SlicerVEScan

3D Slicer extension for [VE-SCAN](https://github.com/edoardoedr/VESCAN_develop): centerline trees of the pulmonary arteries, veins and airways, anatomical branch labels, crossing vessels and tree cutting.

Status: UI mockup. The module `VEScan` shows the full UI from [docs/ui_layout.md](docs/ui_layout.md); the logic functions are stubs that only log. Next steps in [NEXT.md](NEXT.md).

## Develop

1. Slicer: Edit → Application Settings → Developer → *Enable developer mode*, restart.
2. Application Settings → Modules → *Additional module paths*: add the `VEScan/` folder of this repo, restart.
3. Edit `VEScan/VEScan.py` or `VEScan/Resources/UI/VEScan.ui` (button *Edit UI* opens Qt Designer), then *Reload* in the module panel.
