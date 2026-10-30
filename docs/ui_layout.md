# SlicerVEScan: UI layout and stub functions (mockup v1, 2026-10-30)

One scripted module `VEScan` (Extension Wizard template). Everything in `Resources/UI/VEScan.ui`, logic stubs in `VEScan.py`. For now the stubs only log their arguments and return `None` (or a fake value where the UI needs one to move on, marked **fake**).

## 1. Widget tree (`VEScan.ui`)

Object names are the ones the code uses (`self.ui.<name>`).

```
QWidget VEScan
├─ ctkCollapsibleButton  inputsCollapsibleButton      "Inputs"
│  ├─ (one row per input, same pattern) ─────────────────────────────────────────
│  │  QLabel "CT volume"
│  │  QRadioButton ctSceneRadio "Scene" / ctFileRadio "File"   (QButtonGroup ctSourceGroup)
│  │  QStackedWidget ctStack
│  │     page 0: qMRMLNodeComboBox ctNodeSelector   nodeTypes ["vtkMRMLScalarVolumeNode"], noneEnabled
│  │     page 1: ctkPathLineEdit   ctPathEdit       filters Files, nameFilters "*.nii.gz *.nii *.nrrd"
│  │
│  │  "Artery"   arterySceneRadio / arteryFileRadio,   arteryStack
│  │     page 0: qMRMLSegmentSelectorWidget arterySegmentSelector   (segmentation + segment in one widget)
│  │     page 1: ctkPathLineEdit arteryPathEdit                     "*.nii.gz *.nrrd *.seg.nrrd"
│  │  "Veins"    veinsSceneRadio / veinsFileRadio,     veinsStack    (same as artery)
│  │  "Airways"  airwaysSceneRadio / airwaysFileRadio, airwaysStack  (same as artery)
│  │  "Airway wall" airwayWallSceneRadio / ...FileRadio, airwayWallStack (same; optional)
│  │
│  ├─ QLabel "Field store"
│  │  ctkPathLineEdit storePathEdit       filters Files, nameFilters "*.duckn.zip *.zip"
│  │
│  ├─ QLabel "Lobes"
│  │  lobesSceneRadio / lobesFileRadio, lobesStack
│  │     page 0: qMRMLNodeComboBox lobesNodeSelector  ["vtkMRMLSegmentationNode"]
│  │     page 1: ctkPathLineEdit   lobesPathEdit      "*.nii.gz *.nrrd *.seg.nrrd"
│  │  QPushButton loadLobesButton "Load lobes"
│  │  QTableWidget lobesTable  (5 rows RUL RML RLL LUL LLL, 2 cols "Lobe" | "Label")
│  │     col 1 = QComboBox per row, filled after loading: segment names (Scene) or label values (File)
│  │     hidden until the lobes are loaded
│
├─ ctkCollapsibleButton  methodCollapsibleButton      "Method"
│  ├─ QRadioButton fieldRadio "Field" (checked) / vmtkRadio "VMTK (coming soon)" (disabled)
│  ├─ QCheckBox arteryCheck / veinsCheck / airwaysCheck          "Structures"
│  └─ QCheckBox preprocessCheck "Preprocess surfaces" / centerlinesCheck "Centerline extraction"
│               / anatomyCheck "Anatomy"
│     QLabel "Surface labels are always computed."
│
├─ ctkCollapsibleButton  outputCollapsibleButton      "Output"
│  ├─ ctkPathLineEdit outputPathEdit   filters Dirs
│  ├─ QPushButton runButton "Run"   QPushButton cancelButton "Cancel" (disabled while idle)
│  ├─ QProgressBar progressBar      QLabel statusLabel ("anatomy: artery 2/3")
│  └─ QPlainTextEdit logText (read-only)
│
├─ ctkCollapsibleButton  clipCollapsibleButton        "Cut tree"    ← hidden until centerlines exist
│  ├─ per structure one row (shown only for the structures that were run):
│  │    QLabel "Artery"  ctkSliderWidget arteryGenerationsSlider  decimals 0, singleStep 1,
│  │                     range [min, max] generations from the computed tree, value = max
│  │    (veinsGenerationsSlider, airwaysGenerationsSlider: same)
│  ├─ QCheckBox capCheck "Cap the clipped surface" (checked)
│  ├─ QCheckBox previewCheck "Live preview" : moving the slider hides the centerline cells
│  │    with Generation > value (cheap, no clipping)
│  └─ QPushButton applyCutButton "Apply cut"  → clips the labelled surface (expensive)
│
└─ ctkCollapsibleButton  resultsCollapsibleButton     "Results"    ← enabled after a run
   ├─ QCheckBox showSurfacesCheck "Labelled surfaces" / showCenterlinesCheck "Centerlines"
   │            / showLobesCheck "Lobes / fissures" / showCutPointsCheck "Cut points"
   ├─ QComboBox colorByCombo  "Anatomical segment" | "Lobe" | "Crossing type" | "Generation"
   ├─ qMRMLTableView crossingsTableView   (vtkMRMLTableNode: ID | structure | type | lobes |
   │                                        length mm | angle deg)
   └─ QPushButton exportStatsButton "Export statistics CSV"
```

The Scene/File switch is the same for every input: each radio pair is a `QButtonGroup`, its `buttonToggled` sets the `QStackedWidget` page. One helper `_connectSourceSwitch(sceneRadio, fileRadio, stack)` wires all six.

## 2. Parameter node (`@parameterNodeWrapper`)

Settings saved with the scene; later this object is what gets turned into the VE-SCAN config.

```python
@parameterNodeWrapper
class VEScanParameterNode:
    # inputs: source ("scene" | "file") + node + path, per input
    ctSource: Annotated[str, Choice(["scene", "file"])] = "scene"
    ctVolume: vtkMRMLScalarVolumeNode
    ctPath: pathlib.Path
    arterySource / veinsSource / airwaysSource / airwayWallSource / lobesSource: str = "scene"
    arteryPath / veinsPath / airwaysPath / airwayWallPath / lobesPath: pathlib.Path
    lobesSegmentation: vtkMRMLSegmentationNode
    storePath: pathlib.Path
    # method
    method: Annotated[str, Choice(["field", "vmtk"])] = "field"
    runArtery: bool = True
    runVeins: bool = True
    runAirways: bool = True
    stagePreprocess: bool = True
    stageCenterlines: bool = True
    stageAnatomy: bool = True
    # output
    outputDir: pathlib.Path
    # clip
    arteryGenerations: int = 6
    veinsGenerations: int = 6
    airwaysGenerations: int = 6
    capSurface: bool = True
```

`str`, `bool`, `int`, `pathlib.Path` and MRML nodes bind to widgets with `parameterNodeGuiTag` / `SlicerParameterName` in the `.ui`. Not bound automatically, to wire by hand: the segment of `qMRMLSegmentSelectorWidget` (store segmentation node + segment ID as strings), the radio groups, the lobe table.

## 3. Widget slots (`VEScanWidget`)

| Signal | Slot | Does |
|---|---|---|
| any radio pair toggled | `_onSourceToggled(stack, isFile)` | switch the stack page, store the source |
| `loadLobesButton.clicked` | `onLoadLobes()` | `logic.loadLobes(...)` → fill `lobesTable` combos, show the table |
| `fieldRadio` / `vmtkRadio` | `onMethodChanged()` | (VMTK disabled for now) |
| any input / checkbox changed | `_updateRunButtonState()` | enable Run only when the needed inputs are set (store required for field, lobes required for anatomy, output folder) |
| `runButton.clicked` | `onRun()` | build the inputs, `logic.run(...)`, then `_onCenterlinesDone()` / `_onRunFinished()` |
| `cancelButton.clicked` | `onCancel()` | `logic.cancel()` |
| — | `_onProgress(stage, structure, i, n, message)` | progress bar, status label, log line |
| — | `_onCenterlinesDone()` | `logic.getGenerationRange(structure)` per structure → set slider ranges, show `clipCollapsibleButton` |
| `*GenerationsSlider.valueChanged` | `onGenerationsChanged(structure, value)` | if preview: `logic.previewCut(structure, value)` |
| `applyCutButton.clicked` | `onApplyCut()` | `logic.applyCut(structure, generations, cap)` per structure |
| — | `_onRunFinished()` | `logic.loadResults(...)`, enable Results, fill the table |
| `show*Check.toggled` | `onDisplayChanged()` | `logic.setVisibility(kind, visible)` |
| `colorByCombo.currentIndexChanged` | `onColorByChanged()` | `logic.setColorBy(arrayName)` |
| `crossingsTableView` row selected | `onCrossingSelected(row)` | `logic.focusCrossing(crossingId)` |
| `exportStatsButton.clicked` | `onExportStatistics()` | file dialog → `logic.exportStatistics(path)` |

## 4. Logic stubs (`VEScanLogic`)

These are the functions to connect to VE-SCAN later.

```python
class VEScanLogic(ScriptedLoadableModuleLogic):
    # inputs
    def loadCT(self, source, node=None, path=None): ...            # -> CT image (or path) for the pipeline
    def loadStructure(self, name, source, segmentation=None, segmentId=None, path=None): ...  # -> mask
    def loadStore(self, path): ...                                  # check the store opens
    def loadLobes(self, source, segmentation=None, path=None): ...
        # fake: return ["Segment_1", ..., "Segment_5"] (Scene) or [1, 2, 3, 4, 5] (File)
    # run
    def run(self, params, progressCallback): ...                    # stages: preprocess, centerlines,
                                                                    # anatomy (+ surface labels always)
    def cancel(self): ...
    # clip
    def getGenerationRange(self, structure): ...                    # fake: return (1, 12)
    def previewCut(self, structure, generations): ...
    def applyCut(self, structure, generations, cap=True): ...
    # results
    def loadResults(self, outputDir): ...                           # models, centerlines, table node
    def setVisibility(self, kind, visible): ...
    def setColorBy(self, arrayName): ...                            # AnatomicalSegment, LobeLabel,
                                                                    # CrossingType, Generation
    def focusCrossing(self, crossingId): ...
    def exportStatistics(self, path): ...
```

For the mockup: `run()` calls `progressCallback` a few times with `slicer.app.processEvents()` in between (fake progress), then the widget calls `_onCenterlinesDone()` with the fake range so the Cut tree section can be tried.

## 5. Order to build it

1. Extension Wizard: extension `SlicerVEScan`, scripted module `VEScan`.
2. Inputs section in Designer (Edit UI) + `_connectSourceSwitch`, Reload.
3. Method + Output, `_updateRunButtonState`.
4. Fake `run()` with progress, then Cut tree appearing with the fake range.
5. Results with an empty `vtkMRMLTableNode` with the right columns.
6. Later: replace the stubs one by one with VE-SCAN calls.
