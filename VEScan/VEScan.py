import contextlib
import csv
import dataclasses
import importlib
import json
import logging
import os
import pathlib
from typing import Annotated

import numpy as np
import qt
import vtk

import slicer
from slicer.i18n import tr as _
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
from slicer.parameterNodeWrapper import (
    parameterNodeWrapper,
    Choice,
)

from slicer import vtkMRMLScalarVolumeNode, vtkMRMLSegmentationNode


STRUCTURES = ["artery", "veins", "airways"]
INPUTS = ["ct", "artery", "veins", "airways", "airwayWall", "lobes"]
PATH_INPUTS = ["ct", "artery", "veins", "airways", "airwayWall"]  # one path each; lobes: several files
SEGMENTATION_FILES = "Segmentations (*.nii.gz *.nii *.nrrd *.seg.nrrd)"
LOBES = ["RUL", "RML", "RLL", "LUL", "LLL"]
# Color by combo -> (array, VE-SCAN colour table; None = continuous Rainbow)
COLOR_BY = [
    ("AnatomicalSegmentPoint", "ColorTableVessels_EN"),
    ("LobeLabelPoint", "ColorTableLobeLabel_EN"),
    ("CrossingTypePoint", "ColorTableCrossings_EN"),
    ("Generation", None),
]
COLOR_TABLES_DIR = pathlib.Path(__file__).parent / "Resources" / "ColorTables"
LOBES_TABLE = "ColorTableLobesFissures_EN"
# lobe_segments.vtk is labelled per vessel type: the array of the first structure run is shown
LOBE_SEGMENT_ARRAY = {"artery": "LobeSegment_Artery", "veins": "LobeSegment_Vein", "airways": "LobeSegment_Airway"}
CROSSING_COLUMNS = ["ID", "structure", "type", "lobes", "length mm", "angle deg"]

# vescan_field config: every parameter is in this JSON, the UI overwrites only a few keys (VEScanLogic.buildConfig)
CONFIG_PATH = pathlib.Path(__file__).parent / "Resources" / "vescan_field.json"
AIRWAY_WALL_CLASS = "lung_airways_wall"
RAS_TO_LPS = np.diag([-1.0, -1.0, 1.0])

# stage -> (model kind, PipelinePaths attribute) shown in 3D after the stage
STAGE_OUTPUT = {
    "surfaces": ("surface", "preprocessed"),
    "centerlines": ("centerline", "branch_tree"),
    "anatomy": ("centerline", "anatomical_segments"),
    "surface_labels": ("surface", "branch_labeled_surface"),
}
STRUCTURE_COLOR = {"artery": (0.85, 0.25, 0.25), "veins": (0.25, 0.4, 0.85), "airways": (0.85, 0.85, 0.7)}
# model kind -> (colour, None = the structure's; opacity)
MODEL_STYLE = {
    "surface": (None, 0.6),
    "centerline": ((1.0, 0.9, 0.2), 1.0),
    "lobes": ((0.8, 0.8, 0.8), 0.15),
    "fissures": ((1.0, 0.6, 0.1), 0.7),
}
# Results check box -> model kinds
VISIBILITY_KINDS = {"surfaces": ["surface"], "centerlines": ["centerline"], "lobes": ["lobes", "fissures"],
                    "cutPoints": ["cutPoints"]}


#
# VEScan
#


class VEScan(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("VE-SCAN")
        self.parent.categories = [_("Chest Imaging")]
        self.parent.dependencies = []
        self.parent.contributors = ["Edoardo De Rose (KIT, IBT)"]
        self.parent.helpText = _("""
Centerline trees of the pulmonary arteries, veins and airways, anatomical branch labels,
crossing vessels and tree cutting. See <a href="https://github.com/edoardoedr/VESCAN_develop">VE-SCAN</a>.
""")
        self.parent.acknowledgementText = _("""
Developed at the Institute of Biomedical Engineering (IBT), Karlsruhe Institute of Technology (KIT).
""")


#
# VEScanParameterNode
#


@parameterNodeWrapper
class VEScanParameterNode:
    # Inputs: source ("scene" | "file") + node + path, per input
    ctSource: Annotated[str, Choice(["scene", "file"])] = "scene"
    ctVolume: vtkMRMLScalarVolumeNode
    ctPath: pathlib.Path
    arterySource: Annotated[str, Choice(["scene", "file"])] = "scene"
    veinsSource: Annotated[str, Choice(["scene", "file"])] = "scene"
    airwaysSource: Annotated[str, Choice(["scene", "file"])] = "scene"
    airwayWallSource: Annotated[str, Choice(["scene", "file"])] = "scene"
    lobesSource: Annotated[str, Choice(["scene", "file"])] = "scene"
    arteryPath: pathlib.Path
    veinsPath: pathlib.Path
    airwaysPath: pathlib.Path
    airwayWallPath: pathlib.Path
    lobesPaths: str = ""  # one label map or one file per lobe, separated by ";"
    lobesSegmentation: vtkMRMLSegmentationNode
    storePath: pathlib.Path
    # Method
    method: Annotated[str, Choice(["field", "vmtk"])] = "field"
    runArtery: bool = True
    runVeins: bool = True
    runAirways: bool = True
    stagePreprocess: bool = True
    stageCenterlines: bool = True
    stageAnatomy: bool = True
    # Output
    outputDir: pathlib.Path
    # Cut tree
    arteryGenerations: int = 6
    veinsGenerations: int = 6
    airwaysGenerations: int = 6
    capSurface: bool = True


def isPathSet(path) -> bool:
    # An empty pathlib.Path is "."
    return str(path) not in ("", ".")


#
# VEScanWidget
#


class VEScanWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    def __init__(self, parent=None) -> None:
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.logic = None
        self._parameterNode = None
        self._parameterNodeGuiTag = None

    def setup(self) -> None:
        ScriptedLoadableModuleWidget.setup(self)

        uiWidget = slicer.util.loadUI(self.resourcePath("UI/VEScan.ui"))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)
        uiWidget.setMRMLScene(slicer.mrmlScene)

        self.logic = VEScanLogic()

        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

        # Path edits and generation sliders are synced by hand: the automatic binding shows an
        # empty path as "." and forces a fixed slider range. Paths use the edit text because
        # currentPathChanged is not emitted for double extensions like "*.nii.gz".
        self._pathEdits = {f"{name}Path": getattr(self.ui, f"{name}PathEdit") for name in PATH_INPUTS}
        self._pathEdits["storePath"] = self.ui.storePathEdit
        self._pathEdits["outputDir"] = self.ui.outputPathEdit
        for paramName, pathEdit in self._pathEdits.items():
            pathEdit.comboBox().editTextChanged.connect(
                lambda path, n=paramName: self._setParameter(n, pathlib.Path(path)))

        # Inputs: a file is loaded and shown as soon as its path is set
        for name in INPUTS:
            self._connectSourceSwitch(name)
        for name in PATH_INPUTS:
            getattr(self.ui, f"{name}PathEdit").comboBox().editTextChanged.connect(
                lambda path, n=name: self._onInputPathChanged(n, path))
        self.ui.lobesPathsEdit.textChanged.connect(lambda text: self._setParameter("lobesPaths", text))
        self.ui.lobesPathsEdit.editingFinished.connect(self.onLoadLobes)
        self.ui.lobesBrowseButton.clicked.connect(self.onBrowseLobes)
        for name in STRUCTURES + ["airwayWall"]:
            getattr(self.ui, f"{name}SegmentSelector").connect(
                "currentNodeChanged(vtkMRMLNode*)", self._updateRunButtonState)
        self.ui.lobesTable.setRowCount(len(LOBES))
        for row, lobe in enumerate(LOBES):
            item = qt.QTableWidgetItem(lobe)
            item.setFlags(qt.Qt.ItemIsEnabled)
            self.ui.lobesTable.setItem(row, 0, item)
        self.ui.lobesTable.hide()
        self.ui.loadLobesButton.clicked.connect(self.onLoadLobes)

        # Method
        self.ui.fieldRadio.toggled.connect(self.onMethodChanged)

        # Output
        self.ui.runButton.clicked.connect(self.onRun)
        self.ui.cancelButton.clicked.connect(self.onCancel)

        # Cut tree
        self.ui.clipCollapsibleButton.hide()
        for name in STRUCTURES:
            getattr(self.ui, f"{name}GenerationsSlider").valueChanged.connect(
                lambda value, n=name: self.onGenerationsChanged(n, value))
        self.ui.previewCheck.toggled.connect(self.onPreviewToggled)
        self.ui.applyCutButton.clicked.connect(self.onApplyCut)

        # Results
        for kind, check in [("surfaces", self.ui.showSurfacesCheck), ("centerlines", self.ui.showCenterlinesCheck),
                            ("lobes", self.ui.showLobesCheck), ("cutPoints", self.ui.showCutPointsCheck)]:
            check.toggled.connect(lambda visible, k=kind: self.onDisplayChanged(k, visible))
        self.ui.colorByCombo.currentIndexChanged.connect(self.onColorByChanged)
        self.ui.crossingsTableView.clicked.connect(lambda index: self.onCrossingSelected(index.row()))
        self.ui.exportStatsButton.clicked.connect(self.onExportStatistics)

        self.initializeParameterNode()

    def cleanup(self) -> None:
        self.removeObservers()

    def enter(self) -> None:
        self.initializeParameterNode()

    def exit(self) -> None:
        if self._parameterNode:
            self._parameterNode.disconnectGui(self._parameterNodeGuiTag)
            self._parameterNodeGuiTag = None
            self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self._updateRunButtonState)

    def onSceneStartClose(self, caller, event) -> None:
        self.setParameterNode(None)

    def onSceneEndClose(self, caller, event) -> None:
        if self.parent.isEntered:
            self.initializeParameterNode()

    def initializeParameterNode(self) -> None:
        self.setParameterNode(self.logic.getParameterNode())

    def setParameterNode(self, inputParameterNode: VEScanParameterNode | None) -> None:
        if self._parameterNode:
            self._parameterNode.disconnectGui(self._parameterNodeGuiTag)
            self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self._updateRunButtonState)
        self._parameterNode = inputParameterNode
        if self._parameterNode:
            self._parameterNodeGuiTag = self._parameterNode.connectGui(self.ui)
            self.addObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self._updateRunButtonState)
            # Restore what is not bound automatically
            for paramName, pathEdit in self._pathEdits.items():
                path = getattr(self._parameterNode, paramName)
                pathEdit.currentPath = str(path) if isPathSet(path) else ""
            self.ui.lobesPathsEdit.text = self._parameterNode.lobesPaths
            for name in INPUTS:
                isFile = getattr(self._parameterNode, f"{name}Source") == "file"
                getattr(self.ui, f"{name}FileRadio" if isFile else f"{name}SceneRadio").checked = True
            self._updateRunButtonState()

    def _setParameter(self, name, value) -> None:
        if self._parameterNode:
            setattr(self._parameterNode, name, value)

    #
    # Inputs
    #

    def _connectSourceSwitch(self, name) -> None:
        stack = getattr(self.ui, f"{name}Stack")
        getattr(self.ui, f"{name}FileRadio").toggled.connect(lambda isFile: self._onSourceToggled(name, stack, isFile))
        self._onSourceToggled(name, stack, False)

    def _onSourceToggled(self, name, stack, isFile) -> None:
        stack.currentIndex = 1 if isFile else 0
        # Size the stack to the visible page only
        for i in range(stack.count):
            policy = qt.QSizePolicy.Preferred if i == stack.currentIndex else qt.QSizePolicy.Ignored
            stack.widget(i).setSizePolicy(qt.QSizePolicy.Preferred, policy)
        self._setParameter(f"{name}Source", "file" if isFile else "scene")

    def _isInputSet(self, name) -> bool:
        p = self._parameterNode
        if name == "lobes":
            return bool(self._lobesPaths()) if p.lobesSource == "file" else p.lobesSegmentation is not None
        if getattr(p, f"{name}Source") == "file":
            return isPathSet(getattr(p, f"{name}Path"))
        if name == "ct":
            return p.ctVolume is not None
        return getattr(self.ui, f"{name}SegmentSelector").currentNode() is not None

    def _onInputPathChanged(self, name, path) -> None:
        """Load and show a file input as soon as its path points to an existing file."""
        if getattr(self._parameterNode, f"{name}Source", None) != "file" or not os.path.isfile(path):
            return
        with slicer.util.tryWithErrorDisplay(_("Failed to load {path}.").format(path=path), waitCursor=True):
            if name == "ct":
                self.logic.loadCT("file", path=path)
            else:
                self.logic.loadStructure(name, "file", path=path)

    def _lobesPaths(self) -> list:
        return [p.strip() for p in self._parameterNode.lobesPaths.split(";") if p.strip()]

    def onBrowseLobes(self) -> None:
        paths = qt.QFileDialog.getOpenFileNames(slicer.util.mainWindow(), _("Lobes: one label map or one file per lobe"),
                                                "", SEGMENTATION_FILES)
        if paths:
            self.ui.lobesPathsEdit.text = "; ".join(paths)
            self.onLoadLobes()

    def _structureInput(self, name):
        selector = getattr(self.ui, f"{name}SegmentSelector")
        return self.logic.loadStructure(name, getattr(self._parameterNode, f"{name}Source"),
                                        selector.currentNode(), selector.currentSegmentID(),
                                        getattr(self._parameterNode, f"{name}Path"))

    def onLoadLobes(self) -> None:
        """Load the lobes and fill the table; a segment named as the lobe or as its TotalSegmentator
        mask (e.g. lung_upper_lobe_right) is mapped automatically."""
        p = self._parameterNode
        if p.lobesSource == "file" and not self._lobesPaths():
            return
        with slicer.util.tryWithErrorDisplay(_("Failed to load lobes."), waitCursor=True):
            from vescan_field.lobes import LOBE_SEGMENTATION_NAME
            names = self.logic.loadLobes(p.lobesSource, p.lobesSegmentation, self._lobesPaths())
            for row, lobe in enumerate(LOBES):
                combo = qt.QComboBox()
                combo.addItems(names)
                matches = [n for n in (lobe, LOBE_SEGMENTATION_NAME[lobe]) if n in names]
                combo.currentIndex = names.index(matches[0]) if matches else min(row, len(names) - 1)
                combo.currentIndexChanged.connect(lambda _index: self.logic.colorLobes(self._lobeSegments()))
                self.ui.lobesTable.setCellWidget(row, 1, combo)
            self.ui.lobesTable.show()
            self.logic.colorLobes(self._lobeSegments())

    def _lobeSegments(self) -> dict:
        """lobe -> segment ID in the lobe segmentation, from the lobe table."""
        if self.ui.lobesTable.isHidden():
            self.onLoadLobes()
        segmentation = self.logic.lobesNode.GetSegmentation()
        return {lobe: segmentation.GetSegmentIdBySegmentName(self.ui.lobesTable.cellWidget(row, 1).currentText)
                for row, lobe in enumerate(LOBES)}

    #
    # Method / Output
    #

    def onMethodChanged(self) -> None:
        self._setParameter("method", "field" if self.ui.fieldRadio.checked else "vmtk")

    def _updateRunButtonState(self, caller=None, event=None) -> None:
        p = self._parameterNode
        if not p:
            return
        structures = self._runStructures()
        missing = []
        if not structures:
            missing.append(_("a structure"))
        missing += [name for name in structures if not self._isInputSet(name)]  # CT optional
        if p.method == "field" and not isPathSet(p.storePath):
            missing.append(_("field store"))
        if (p.stagePreprocess or p.stageAnatomy) and not self._isInputSet("lobes"):
            missing.append(_("lobes"))
        if not isPathSet(p.outputDir):
            missing.append(_("output folder"))
        self.ui.runButton.enabled = not missing and not self.ui.cancelButton.enabled
        self.ui.runButton.toolTip = _("Missing: ") + ", ".join(missing) if missing else _("Run VE-SCAN")

    def onRun(self) -> None:
        p = self._parameterNode
        self.ui.logText.clear()
        self.ui.cancelButton.enabled = True
        self.ui.runButton.enabled = False
        try:
            with slicer.util.tryWithErrorDisplay(_("VE-SCAN failed."), waitCursor=True):
                ctNode = self.logic.loadCT(p.ctSource, p.ctVolume, p.ctPath) if self._isInputSet("ct") else None
                structures = {name: [self._structureInput(name)] for name in self._runStructures()}
                if "airways" in structures and self._isInputSet("airwayWall"):
                    structures["airways"].append(self._structureInput("airwayWall"))
                lobeSegments = self._lobeSegments() if p.stagePreprocess else {}
                finished = self.logic.run(p, ctNode, structures, lobeSegments, self._onProgress,
                                          self.ui.logText.appendPlainText)
                if finished:
                    self._onCenterlinesDone()
                    self._onRunFinished()
        finally:
            self.ui.cancelButton.enabled = False
            self._updateRunButtonState()

    def onCancel(self) -> None:
        self.logic.cancel()

    def _onProgress(self, stage, structure, i, n) -> None:
        self.ui.progressBar.maximum = n
        self.ui.progressBar.value = i
        self.ui.statusLabel.text = f"{stage}: {structure} ({i}/{n})" if structure else f"{stage} ({i}/{n})"

    def _runStructures(self):
        return [s for s in STRUCTURES if getattr(self._parameterNode, f"run{s.capitalize()}")]

    #
    # Cut tree
    #

    def _onCenterlinesDone(self) -> None:
        withTree = [s for s in STRUCTURES if self.logic.hasCenterline(s)]
        for name in STRUCTURES:
            visible = name in withTree
            getattr(self.ui, f"{name}GenerationsLabel").visible = visible
            slider = getattr(self.ui, f"{name}GenerationsSlider")
            slider.visible = visible
            if visible:
                slider.minimum, slider.maximum = self.logic.getGenerationRange(name)
                slider.value = slider.maximum
        self.ui.clipCollapsibleButton.visible = bool(withTree)
        self.ui.clipCollapsibleButton.collapsed = False

    def onGenerationsChanged(self, structure, value) -> None:
        self._setParameter(f"{structure}Generations", int(value))
        if self.ui.previewCheck.checked:
            self.logic.previewCut(structure, int(value))

    def onPreviewToggled(self, enabled) -> None:
        for name in STRUCTURES:
            if self.logic.hasCenterline(name):
                generations = getattr(self._parameterNode, f"{name}Generations") if enabled else None
                self.logic.previewCut(name, generations)
        if not enabled:
            self.logic.setColorBy(*COLOR_BY[self.ui.colorByCombo.currentIndex])

    def onApplyCut(self) -> None:
        with slicer.util.tryWithErrorDisplay(_("Failed to cut the tree."), waitCursor=True):
            for name in STRUCTURES:
                if self.logic.hasCenterline(name):
                    self.logic.applyCut(name, getattr(self._parameterNode, f"{name}Generations"),
                                        self._parameterNode.capSurface)
            self.onDisplayChanged("cutPoints", self.ui.showCutPointsCheck.checked)

    #
    # Results
    #

    def _onRunFinished(self) -> None:
        tableNode = self.logic.loadResults()
        self.ui.crossingsTableView.setMRMLTableNode(tableNode)
        self.ui.resultsCollapsibleButton.enabled = True
        self.ui.resultsCollapsibleButton.collapsed = False
        for kind, check in [("surfaces", self.ui.showSurfacesCheck), ("centerlines", self.ui.showCenterlinesCheck),
                            ("lobes", self.ui.showLobesCheck), ("cutPoints", self.ui.showCutPointsCheck)]:
            self.onDisplayChanged(kind, check.checked)

    def onDisplayChanged(self, kind, visible) -> None:
        self.logic.setVisibility(kind, visible)

    def onColorByChanged(self, index) -> None:
        self.ui.previewCheck.checked = False  # the preview colours by Generation
        self.logic.setColorBy(*COLOR_BY[index])

    def onCrossingSelected(self, row) -> None:
        tableNode = self.ui.crossingsTableView.mrmlTableNode()
        if tableNode and row < tableNode.GetNumberOfRows():
            self.logic.focusCrossing(tableNode.GetCellText(row, 1), int(tableNode.GetCellText(row, 0)))

    def onExportStatistics(self) -> None:
        path = qt.QFileDialog.getSaveFileName(slicer.util.mainWindow(), _("Export statistics"), "", "CSV (*.csv)")
        if path:
            self.logic.exportStatistics(path)


#
# VEScanLogic
#


class RunCancelled(Exception):
    pass


class UiLogHandler(logging.Handler):
    """Forwards the vescan_field messages to the module log and keeps the GUI responsive."""

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def emit(self, record):
        self.callback(f"{record.name.removeprefix('vescan_field.')}: {record.getMessage()}")
        slicer.app.processEvents()


class VEScanLogic(ScriptedLoadableModuleLogic):
    """Inputs are loaded with Slicer, vescan_field computes and saves (VE-SCAN's output layout),
    and each output is shown in 3D as soon as it is written."""

    def __init__(self) -> None:
        ScriptedLoadableModuleLogic.__init__(self)
        self._cancelRequested = False
        self._inputs = {}          # input name -> (file path(s), node loaded from them)
        self._models = {}          # (kind, structure) -> displayed node
        self.lobesNode = None
        self.contexts = {}         # structure -> vescan StructureContext of the last run
        self.statisticsRows = []
        self.crossingsTableNode = None
        self.colorBy = COLOR_BY[0]      # (array, colour table) of the surfaces and centerlines
        self._lobeArray = LOBE_SEGMENT_ARRAY["artery"]

    def getParameterNode(self):
        return VEScanParameterNode(super().getParameterNode())

    # Inputs

    def _loadInput(self, name, key, load):
        """Node of a file input: loaded and shown once, replaced when its path changes."""
        oldKey, old = self._inputs.get(name, (None, None))
        if old and slicer.mrmlScene.IsNodePresent(old):
            if oldKey == key:
                return old
            slicer.mrmlScene.RemoveNode(old)
        node = load()
        self._inputs[name] = (key, node)
        self.showInput(name, node)
        return node

    def showInput(self, name, node):
        """CT in the slice views, a segmentation in 3D (structures in their colour)."""
        if node.IsA("vtkMRMLScalarVolumeNode"):
            slicer.util.setSliceViewerLayers(background=node, fit=True)
            return
        node.CreateClosedSurfaceRepresentation()
        color = STRUCTURE_COLOR.get("airways" if name == "airwayWall" else name)
        segmentation = node.GetSegmentation()
        for i in range(segmentation.GetNumberOfSegments()):
            if color:
                segmentation.GetNthSegment(i).SetColor(*color)
        node.GetDisplayNode().SetOpacity3D(0.3 if name == "lobes" else 1.0)
        slicer.app.layoutManager().threeDWidget(0).threeDView().resetFocalPoint()

    def loadCT(self, source, node=None, path=None):
        if source == "scene":
            return node
        return self._loadInput("ct", str(path), lambda: slicer.util.loadVolume(str(path)))

    def loadStructure(self, name, source, segmentation=None, segmentId=None, path=None):
        """(segmentation node, segment ID) of a structure mask."""
        if source == "file":
            segmentation = self._loadInput(name, str(path), lambda: slicer.util.loadSegmentation(str(path)))
            segmentId = segmentation.GetSegmentation().GetNthSegmentID(0)
        if not segmentation or not segmentId:
            raise ValueError(f"No segment selected for {name}")
        return segmentation, segmentId

    def loadStore(self, path):
        from vescan_field.store import Store
        return Store(path)

    def loadLobes(self, source, segmentation=None, paths=()):
        """Segment names of the lobe segmentation. From files: one segmentation "Lobes" with a segment
        per label of a label map, or one segment per file named as the file (e.g. lung_upper_lobe_right)."""
        if source == "scene":
            self.lobesNode = segmentation
        else:
            self.lobesNode = self._loadInput("lobes", tuple(map(str, paths)), lambda: self._mergeSegmentations(paths))
        segments = self.lobesNode.GetSegmentation()
        return [segments.GetNthSegment(i).GetName() for i in range(segments.GetNumberOfSegments())]

    def colorLobes(self, lobeSegments):
        """Lobe segments in the colours of VE-SCAN's LobeLabel table (value = position in LOBE_ORDER + 1)."""
        from vescan_field.lobes import LOBE_ORDER
        table, rgba = self.colorTable("ColorTableLobeLabel_EN"), [0.0] * 4
        for lobe, segmentId in lobeSegments.items():
            segment = self.lobesNode.GetSegmentation().GetSegment(segmentId)
            if segment and table.GetColor(LOBE_ORDER.index(lobe) + 1, rgba):
                segment.SetColor(*rgba[:3])

    @staticmethod
    def _mergeSegmentations(paths):
        merged = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "Lobes")
        merged.CreateDefaultDisplayNodes()
        for path in paths:
            loaded = slicer.util.loadSegmentation(str(path))
            segments = loaded.GetSegmentation()
            if segments.GetNumberOfSegments() == 1:
                segments.GetNthSegment(0).SetName(pathlib.Path(path).name.split(".")[0])
            for i in range(segments.GetNumberOfSegments()):
                merged.GetSegmentation().CopySegmentFromSegmentation(segments, segments.GetNthSegmentID(i))
            slicer.mrmlScene.RemoveNode(loaded)
        return merged

    @staticmethod
    def geometry(volumeNode):
        """vescan Geometry of a volume node: LPS, as SimpleITK reads the same image."""
        from vescan_field.field import Geometry
        m = vtk.vtkMatrix4x4()
        volumeNode.GetIJKToRASDirectionMatrix(m)
        directions = np.array([[m.GetElement(r, c) for c in range(3)] for r in range(3)])
        return Geometry(np.array(volumeNode.GetSpacing())[::-1], RAS_TO_LPS @ np.array(volumeNode.GetOrigin()),
                        RAS_TO_LPS @ directions)

    @staticmethod
    def mask(segmentation, segmentId, referenceNode):
        """Segment as a boolean array (z,y,x) on the reference grid."""
        return slicer.util.arrayFromSegmentBinaryLabelmap(segmentation, segmentId, referenceNode) > 0

    @staticmethod
    def referenceGrid(segmentation, segmentId):
        """Without a CT: a label map on the segmentation's full grid (the grid of the mask file, which is
        what vescan uses as CT geometry)."""
        labelmap = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "VE-SCAN reference grid")
        segmentIds = vtk.vtkStringArray()
        segmentIds.InsertNextValue(segmentId)
        slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
            segmentation, segmentIds, labelmap, None, slicer.vtkSegmentation.EXTENT_REFERENCE_GEOMETRY)
        return labelmap

    def buildConfig(self, params, outputDir, airwayWall=False):
        """The bundled JSON with the keys set by the UI, saved in the output folder and validated by vescan."""
        from vescan_field import config, io
        data = json.loads(CONFIG_PATH.read_text())
        batch = data["batch"]
        batch.update(patients_root_dir=str(outputDir), surfaces_root_dir=str(outputDir / "surfaces"),
                     results_root_dir=str(outputDir), store=pathlib.Path(params.storePath).name)
        for name in STRUCTURES:
            batch["structures"][name]["enabled"] = getattr(params, f"run{name.capitalize()}")
        if not airwayWall:
            airways = batch["structures"]["airways"]
            airways["classes"] = [c for c in airways["classes"] if c != AIRWAY_WALL_CLASS]
        data["pipeline"]["stages"] = dict(surfaces=params.stagePreprocess, centerlines=params.stageCenterlines,
                                          anatomy=params.stageAnatomy, surface_labels=True, clip=False)
        data["pipeline"]["clip"]["cap"] = params.capSurface
        outputDir.mkdir(parents=True, exist_ok=True)
        io.write_json(outputDir / "vescan_config.json", data)
        return config.build(data, base_dir=outputDir)

    # Run

    def run(self, params, ctNode, structures, lobeSegments, progressCallback, logCallback=None) -> bool:
        """ctNode: reference grid, optional (None: the grid of the first structure's mask);
        structures: name -> [(segmentation, segment ID), ...] (airways: + airway wall);
        lobeSegments: lobe -> segment ID in self.lobesNode. Returns False if cancelled."""
        from vescan_field import io, log
        from vescan_field.lobes import lobe_mask_names
        from vescan_field.orchestrator import STAGES
        from vescan_field.paths import SurfacePaths

        self._cancelRequested = False
        self.contexts = {}
        outputDir = pathlib.Path(params.outputDir)
        cfg = self.buildConfig(params, outputDir, airwayWall=len(structures.get("airways", [])) > 1)
        stages = [name for name in STAGES if getattr(cfg.pipeline.stages, name)]
        enabled = cfg.enabled_structures()
        self._lobeArray = LOBE_SEGMENT_ARRAY[next(iter(enabled), "artery")]
        # the VE-SCAN models replace the input segmentations in 3D (still shown in the slice views)
        for segmentation in {seg for inputs in structures.values() for seg, _ in inputs} | {self.lobesNode} - {None}:
            segmentation.GetDisplayNode().SetVisibility3D(False)
        steps = int(cfg.pipeline.stages.surfaces) + len(enabled) * (1 + len(stages))
        done = 0

        def begin(stage, structure=""):
            nonlocal done
            if self._cancelRequested:
                raise RunCancelled()
            progressCallback(stage, structure, done, steps)
            slicer.app.processEvents()
            done += 1

        log.setup(cfg.logging.level)
        vescanLogger = logging.getLogger(log.ROOT)
        handler = UiLogHandler(logCallback) if logCallback else None
        if handler:
            vescanLogger.addHandler(handler)
        store = self.loadStore(params.storePath)
        firstSegmentation, firstSegmentId = next(iter(structures.values()))[0]
        reference = ctNode or self.referenceGrid(firstSegmentation, firstSegmentId)
        patient = ctNode.GetName() if ctNode else outputDir.name  # vescan: the patient folder's name
        fileLog = log.to_file(outputDir / cfg.logging.file_name) if cfg.logging.file_name else contextlib.nullcontext()
        try:
            with fileLog:
                ctGeom = self.geometry(reference)
                lobes = lobe_mask_names(cfg.pipeline.lobes.enabled, cfg.pipeline.lobes.names)
                surfaces = SurfacePaths(cfg.batch.surfaces_root_dir)
                if cfg.pipeline.stages.surfaces:
                    begin("lobes")
                    self._runLobes(cfg, lobes, lobeSegments, reference, ctGeom, surfaces)
                for structure, classes in enabled.items():
                    begin("field", structure)
                    mask = np.logical_or.reduce([self.mask(seg, sid, reference) for seg, sid in structures[structure]])
                    ctx = self._buildContext(cfg, patient, structure, classes, store, mask, ctGeom,
                                             lobes, surfaces, outputDir)
                    self.contexts[structure] = ctx
                    summary = dict(pipeline="field", patient=ctx.patient, structure=structure, store_classes=classes,
                                   store=str(store.path), field=dataclasses.asdict(cfg.pipeline.field), qa_mask=ctx.qa)
                    for name in stages:
                        begin(name, structure)
                        stage = importlib.import_module(f"vescan_field.stages.{name}")
                        summary[name] = stage.run(ctx, getattr(cfg.pipeline, name))
                        self._showStageOutput(name, ctx)
                    summary["timings_s"] = ctx.timings
                    io.write_json(ctx.paths.summary, summary)
            progressCallback("done", "", steps, steps)
            return True
        except RunCancelled:
            vescanLogger.warning("cancelled")
            return False
        finally:
            store.close()
            if reference is not ctNode:
                slicer.mrmlScene.RemoveNode(reference)
            if handler:
                vescanLogger.removeHandler(handler)

    def _runLobes(self, cfg, lobes, lobeSegments, referenceNode, ctGeom, surfaces):
        """As vescan's stages.surfaces.run_patient, with the lobe masks from the lobe segmentation:
        one surface per lobe (read again by anatomy), lobe_segments.vtk, lobe_fissures.vtk and the legend."""
        from vescan_field import io
        from vescan_field.stages.surfaces import lobe_segments
        from vescan_field.stages.surfaces.convert import convert_mask
        from vescan_field.surface import save_surface

        surfaces.surfaces_dir.mkdir(parents=True, exist_ok=True)
        c = cfg.pipeline.surfaces.convert
        polys = {}
        for lobe, maskName in lobes.items():
            poly = convert_mask(self.mask(self.lobesNode, lobeSegments[lobe], referenceNode), ctGeom, method=c.method,
                                smoothing_factor=c.smoothing_factor, decimation_factor=c.decimation_factor,
                                compute_normals=c.compute_normals)
            if poly is None:
                logging.getLogger("vescan_field.slicer").warning(f"empty lobe {lobe}")
                continue
            save_surface(poly, surfaces.surface(maskName))
            polys[lobe] = poly
        l = cfg.pipeline.surfaces.lobe_segments
        if not (l.enabled and polys):
            return
        combined, fissures = lobe_segments.build_combined_lobes(
            polys, extract_fissures_too=l.extract_fissures, tolerance=l.fissure_contact_tolerance,
            min_component_area=l.min_fissure_component_area, min_fissure_area=l.min_fissure_area)
        save_surface(combined, surfaces.segments)
        self._showModel("lobes", "", surfaces.segments)
        sheets = lobe_segments.build_fissure_surface(fissures)
        if sheets is not None:
            save_surface(sheets, surfaces.fissures)
            self._showModel("fissures", "", surfaces.fissures)
        io.write_json(surfaces.segments_legend, lobe_segments.legend(fissures))

    def _buildContext(self, cfg, patient, structure, classes, store, mask, ctGeom, lobes, surfaces, outputDir):
        """As vescan's orchestrator.build_context, with the mask from Slicer."""
        from vescan_field import io
        from vescan_field.field import margin_from_store
        from vescan_field.orchestrator import StructureContext
        from vescan_field.paths import PipelinePaths, final_export_dir

        paths = PipelinePaths(final_export_dir(outputDir, structure), debug=cfg.pipeline.debug_files)
        paths.make_dirs()
        margin, geom, qa, timings = margin_from_store(store, [store.class_index[c] for c in classes], ctGeom,
                                                      mask.shape, mask=mask, pad_voxels=cfg.pipeline.field.pad_voxels)
        if paths.debug:
            io.write_margin_image(paths.margin, margin, geom)
        return StructureContext(patient=patient, structure=structure, classes=classes, store=store,
                                patient_dir=outputDir, results_dir=outputDir, surfaces=surfaces, paths=paths,
                                mask=mask, ct_geom=ctGeom, lobes=lobes, margin=margin, geom=geom, qa=qa,
                                timings=dict(timings),
                                keep_largest_component=cfg.pipeline.surfaces.preprocess.keep_largest_component)

    def cancel(self):
        self._cancelRequested = True

    # 3D display

    def _showStageOutput(self, stage, ctx):
        kind, attr = STAGE_OUTPUT[stage]
        path = getattr(ctx.paths, attr)
        if path.exists():
            self._showModel(kind, ctx.structure, path)

    def _showModel(self, kind, structure, path):
        """Load the file into the model of (kind, structure), creating it the first time."""
        node = self._models.get((kind, structure))
        if node and slicer.mrmlScene.IsNodePresent(node):
            node.GetStorageNode().SetFileName(str(path))
            node.GetStorageNode().ReadData(node)
        else:
            node = self._models[(kind, structure)] = slicer.util.loadModel(str(path))
            node.SetName(f"VE-SCAN {structure} {kind}" if structure else f"VE-SCAN {kind}")
            color, opacity = MODEL_STYLE[kind]
            display = node.GetDisplayNode()
            display.SetColor(STRUCTURE_COLOR.get(structure, color) if color is None else color)
            display.SetOpacity(opacity)
            display.SetLineWidth(3)
            self._addToFolder(node)
        if kind in ("surface", "centerline"):
            self._colorModel(node, *self.colorBy)
        elif kind == "lobes":
            self._colorModel(node, self._lobeArray, LOBES_TABLE)
        elif kind == "fissures":
            self._colorModel(node, "Fissure", LOBES_TABLE)
        slicer.app.processEvents()
        return node

    def colorTable(self, name):
        """VE-SCAN colour table node, loaded once from Resources/ColorTables."""
        node = slicer.mrmlScene.GetFirstNode(name, "vtkMRMLColorTableNode")
        return node or slicer.util.loadColorTable(str(COLOR_TABLES_DIR / f"{name}.csv"))

    def _colorModel(self, node, arrayName, tableName):
        """Colour a model by a point or cell array with a VE-SCAN table (None: Rainbow on the data
        range); a model without the array keeps its plain colour."""
        polyData = node.GetPolyData()
        if polyData.GetPointData().GetArray(arrayName) is not None:
            association = vtk.vtkAssignAttribute.POINT_DATA
        elif polyData.GetCellData().GetArray(arrayName) is not None:
            association = vtk.vtkAssignAttribute.CELL_DATA
        else:
            node.GetDisplayNode().SetScalarVisibility(False)
            return
        display = node.GetDisplayNode()
        display.SetActiveScalar(arrayName, association)
        if tableName:
            display.SetAndObserveColorNodeID(self.colorTable(tableName).GetID())
            display.SetScalarRangeFlag(slicer.vtkMRMLDisplayNode.UseColorNodeScalarRange)
        else:
            display.SetAndObserveColorNodeID("vtkMRMLColorTableNodeRainbow")
            display.SetScalarRangeFlag(slicer.vtkMRMLDisplayNode.UseDataScalarRange)
        display.SetScalarVisibility(True)

    def _showMarkups(self, kind, structure, path):
        old = self._models.get((kind, structure))
        if old and slicer.mrmlScene.IsNodePresent(old):
            slicer.mrmlScene.RemoveNode(old)
        node = self._models[(kind, structure)] = slicer.util.loadMarkups(str(path))
        node.SetName(f"VE-SCAN {structure} {kind}")
        node.GetDisplayNode().SetPointLabelsVisibility(False)
        self._addToFolder(node)

    def _addToFolder(self, node):
        sh = slicer.mrmlScene.GetSubjectHierarchyNode()
        folder = sh.GetItemChildWithName(sh.GetSceneItemID(), "VE-SCAN") or sh.CreateFolderItem(sh.GetSceneItemID(), "VE-SCAN")
        sh.SetItemParent(sh.GetItemByDataNode(node), folder)

    # Cut tree

    def hasCenterline(self, structure) -> bool:
        node = self._models.get(("centerline", structure))
        return bool(node) and slicer.mrmlScene.IsNodePresent(node) and structure in self.contexts

    def getGenerationRange(self, structure):
        generation = slicer.util.arrayFromModelCellData(self._models[("centerline", structure)], "Generation")
        return int(generation.min()), int(generation.max())

    def previewCut(self, structure, generations):
        """Hide the centerline cells with Generation > generations (None: show all). The display
        threshold works only with scalars shown, so the preview colours the centerline by Generation."""
        display = self._models[("centerline", structure)].GetDisplayNode()
        if generations is None:
            display.SetThresholdEnabled(False)
            return
        display.SetActiveScalar("Generation", vtk.vtkAssignAttribute.CELL_DATA)
        display.SetAndObserveColorNodeID("vtkMRMLColorTableNodeRainbow")
        display.SetScalarRangeFlag(slicer.vtkMRMLDisplayNode.UseDataScalarRange)
        display.SetScalarVisibility(True)
        display.SetThresholdRange(-1, generations)
        display.SetThresholdEnabled(True)

    def applyCut(self, structure, generations, cap=True):
        from vescan_field.config import ClipConfig
        from vescan_field.stages import clip
        ctx = self.contexts[structure]
        clip.run(ctx, ClipConfig(max_generations=generations, cap=cap))
        self._showModel("surface", structure, ctx.paths.clipped_surface)
        self._showMarkups("cutPoints", structure, ctx.paths.cut_points)

    # Results

    def loadResults(self):
        """Crossing vessels of every structure (vescan's statistics.csv) in one table node."""
        self.statisticsRows = []
        for ctx in self.contexts.values():
            if ctx.paths.statistics_csv.exists():
                with open(ctx.paths.statistics_csv, newline="") as f:
                    self.statisticsRows += [row for row in csv.DictReader(f) if row.get("crossing")]
        if not self.crossingsTableNode or not slicer.mrmlScene.IsNodePresent(self.crossingsTableNode):
            self.crossingsTableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "VE-SCAN crossings")
            self.crossingsTableNode.SetUseColumnTitleAsColumnHeader(True)
            self.crossingsTableNode.SetLocked(True)
            for name in CROSSING_COLUMNS:
                self.crossingsTableNode.AddColumn().SetName(name)
        table = self.crossingsTableNode
        table.GetTable().SetNumberOfRows(0)
        for row in self.statisticsRows:
            r = table.AddEmptyRow()
            values = [row["crossing"], row["structure"], row["crossing_type"], f"{row['from_lobe']} > {row['to_lobe']}",
                      row["length_mm"], row["angle_median_deg"]]
            for c, value in enumerate(values):
                table.SetCellText(r, c, value)
        table.Modified()
        return table

    def setVisibility(self, kind, visible):
        for (k, _structure), node in self._models.items():
            if k in VISIBILITY_KINDS[kind] and slicer.mrmlScene.IsNodePresent(node):
                node.SetDisplayVisibility(visible)

    def setColorBy(self, arrayName, tableName):
        """Colour the surfaces and centerlines (now and the ones shown later) by this array."""
        self.colorBy = (arrayName, tableName)
        for (kind, _structure), node in self._models.items():
            if kind in ("surface", "centerline") and slicer.mrmlScene.IsNodePresent(node):
                self._colorModel(node, arrayName, tableName)

    def focusCrossing(self, structure, crossingId):
        """Centre the slice views and the 3D camera on a crossing vessel."""
        node = self._models.get(("centerline", structure))
        if not node:
            return
        ids = slicer.util.arrayFromModelPointData(node, "CrossingIdPoint")
        points = slicer.util.arrayFromModelPoints(node)[ids == crossingId]
        if not len(points):
            return
        center = points.mean(0)
        slicer.modules.markups.logic().JumpSlicesToLocation(*center, True)
        viewNode = slicer.app.layoutManager().threeDWidget(0).mrmlViewNode()
        slicer.modules.cameras.logic().GetViewActiveCameraNode(viewNode).SetFocalPoint(*center)

    def exportStatistics(self, path):
        """All the columns of vescan's statistics.csv, every structure in one file."""
        if not self.statisticsRows:
            raise ValueError("No statistics to export")
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(self.statisticsRows[0]))
            writer.writeheader()
            writer.writerows(self.statisticsRows)


#
# VEScanTest
#


class VEScanTest(ScriptedLoadableModuleTest):
    def setUp(self):
        slicer.mrmlScene.Clear()

    def runTest(self):
        self.setUp()
        self.test_Geometry()
        self.test_Config()

    def test_Geometry(self):
        """A volume node gives the same Geometry as vescan reading its file with SimpleITK."""
        import tempfile
        from vescan_field.field import load_reference
        node = slicer.util.addVolumeFromArray(np.zeros((4, 5, 6), np.uint8))
        node.SetSpacing(0.7, 0.8, 2.5)
        node.SetOrigin(-10, 20, 30)
        node.SetIJKToRASDirections(-1, 0, 0, 0, 0, 1, 0, -1, 0)
        path = pathlib.Path(tempfile.mkdtemp()) / "volume.nii.gz"
        slicer.util.saveNode(node, str(path))
        geom, reference = VEScanLogic.geometry(node), load_reference(path)[0]
        for attr in ("spacing", "origin", "direction"):
            self.assertTrue(np.allclose(getattr(geom, attr), getattr(reference, attr)), attr)
        self.delayDisplay("Geometry test passed")

    def test_Config(self):
        """The bundled JSON with the UI keys is a valid vescan config."""
        import tempfile
        logic = VEScanLogic()
        params = logic.getParameterNode()
        params.storePath = pathlib.Path("store.duckn.zip")
        params.stageAnatomy = False
        outputDir = pathlib.Path(tempfile.mkdtemp())
        cfg = logic.buildConfig(params, outputDir)
        self.assertFalse(cfg.pipeline.stages.anatomy)
        self.assertEqual(cfg.batch.structures.airways.classes, ["lung_airways"])
        self.assertTrue((outputDir / "vescan_config.json").exists())
        self.delayDisplay("Config test passed")
