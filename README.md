# SlicerVeScan

3D Slicer extension for [VeScan](https://github.com/edoardoedr/VeScan-field): centerline trees of the pulmonary arteries, veins and airways, anatomical branch labels, crossing vessels and tree cutting.

Status: the module `VeScan` (UI from [docs/ui_layout.md](docs/ui_layout.md)) runs VeScan field in Slicer: Slicer loads the inputs, [vescan-field](https://github.com/edoardoedr/VeScan-field) computes and saves, the outputs are shown in 3D as they are written. Next steps in [NEXT.md](NEXT.md).

## VeScan package

The computation is the Python package `vescan-field` ([VeScan-field](https://github.com/edoardoedr/VeScan-field), version in [VeScan/Resources/requirements.txt](VeScan/Resources/requirements.txt)). On the first Run (or lobe loading) the module asks to install it into Slicer's Python, keeping Slicer's numpy.

## Develop

1. Slicer: Edit → Application Settings → Developer → *Enable developer mode*, restart.
2. Application Settings → Modules → *Additional module paths*: add the `VeScan/` folder of this repo, restart.
3. Optional, to work on VeScan too: editable install from a local clone, with Slicer's numpy pinned:
   `/Applications/Slicer.app/Contents/bin/PythonSlicer -m pip install -e <VeScan-field clone> "numpy==1.26.4"`
4. Edit `VeScan/VeScan.py` or `VeScan/Resources/UI/VeScan.ui` (button *Edit UI* opens Qt Designer), then *Reload* in the module panel.
