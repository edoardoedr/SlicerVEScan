import logging
import pathlib
import time
from typing import Annotated

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
LOBES = ["RUL", "RML", "RLL", "LUL", "LLL"]
COLOR_BY_ARRAYS = ["AnatomicalSegment", "LobeLabel", "CrossingType", "Generation"]
CROSSING_COLUMNS = ["ID", "structure", "type", "lobes", "length mm", "angle deg"]


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
    lobesPath: pathlib.Path
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
        self._pathEdits = {f"{name}Path": getattr(self.ui, f"{name}PathEdit") for name in INPUTS}
        self._pathEdits["storePath"] = self.ui.storePathEdit
        self._pathEdits["outputDir"] = self.ui.outputPathEdit
        for paramName, pathEdit in self._pathEdits.items():
            pathEdit.comboBox().editTextChanged.connect(
                lambda path, n=paramName: self._setParameter(n, pathlib.Path(path)))

        # Inputs
        for name in INPUTS:
            self._connectSourceSwitch(name)
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
        if getattr(p, f"{name}Source") == "file":
            return isPathSet(getattr(p, f"{name}Path"))
        if name == "ct":
            return p.ctVolume is not None
        if name == "lobes":
            return p.lobesSegmentation is not None
        return getattr(self.ui, f"{name}SegmentSelector").currentNode() is not None

    def onLoadLobes(self) -> None:
        p = self._parameterNode
        with slicer.util.tryWithErrorDisplay(_("Failed to load lobes."), waitCursor=True):
            labels = self.logic.loadLobes(p.lobesSource, p.lobesSegmentation, p.lobesPath)
            for row in range(len(LOBES)):
                combo = qt.QComboBox()
                combo.addItems([str(label) for label in labels])
                combo.currentIndex = row
                self.ui.lobesTable.setCellWidget(row, 1, combo)
            self.ui.lobesTable.show()

    #
    # Method / Output
    #

    def onMethodChanged(self) -> None:
        self._setParameter("method", "field" if self.ui.fieldRadio.checked else "vmtk")

    def _updateRunButtonState(self, caller=None, event=None) -> None:
        p = self._parameterNode
        if not p:
            return
        structures = [s for s in STRUCTURES if getattr(p, f"run{s.capitalize()}")]
        missing = []
        if not structures:
            missing.append(_("a structure"))
        missing += [name for name in ["ct"] + structures if not self._isInputSet(name)]
        if p.method == "field" and not isPathSet(p.storePath):
            missing.append(_("field store"))
        if p.stageAnatomy and not self._isInputSet("lobes"):
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
                finished = self.logic.run(p, self._onProgress)
                if finished and p.stageCenterlines:
                    self._onCenterlinesDone()
                if finished:
                    self._onRunFinished()
        finally:
            self.ui.cancelButton.enabled = False
            self._updateRunButtonState()

    def onCancel(self) -> None:
        self.logic.cancel()

    def _onProgress(self, stage, structure, i, n, message) -> None:
        self.ui.progressBar.maximum = n
        self.ui.progressBar.value = i
        self.ui.statusLabel.text = f"{stage}: {structure} {i}/{n}"
        self.ui.logText.appendPlainText(message)

    def _runStructures(self):
        return [s for s in STRUCTURES if getattr(self._parameterNode, f"run{s.capitalize()}")]

    #
    # Cut tree
    #

    def _onCenterlinesDone(self) -> None:
        runStructures = self._runStructures()
        for name in STRUCTURES:
            visible = name in runStructures
            getattr(self.ui, f"{name}GenerationsLabel").visible = visible
            slider = getattr(self.ui, f"{name}GenerationsSlider")
            slider.visible = visible
            if visible:
                slider.minimum, slider.maximum = self.logic.getGenerationRange(name)
                slider.value = slider.maximum
        self.ui.clipCollapsibleButton.show()
        self.ui.clipCollapsibleButton.collapsed = False

    def onGenerationsChanged(self, structure, value) -> None:
        self._setParameter(f"{structure}Generations", int(value))
        if self.ui.previewCheck.checked:
            self.logic.previewCut(structure, int(value))

    def onApplyCut(self) -> None:
        with slicer.util.tryWithErrorDisplay(_("Failed to cut the tree."), waitCursor=True):
            for name in self._runStructures():
                self.logic.applyCut(name, getattr(self._parameterNode, f"{name}Generations"),
                                    self._parameterNode.capSurface)

    #
    # Results
    #

    def _onRunFinished(self) -> None:
        tableNode = self.logic.loadResults(self._parameterNode.outputDir)
        self.ui.crossingsTableView.setMRMLTableNode(tableNode)
        self.ui.resultsCollapsibleButton.enabled = True
        self.ui.resultsCollapsibleButton.collapsed = False

    def onDisplayChanged(self, kind, visible) -> None:
        self.logic.setVisibility(kind, visible)

    def onColorByChanged(self, index) -> None:
        self.logic.setColorBy(COLOR_BY_ARRAYS[index])

    def onCrossingSelected(self, row) -> None:
        tableNode = self.ui.crossingsTableView.mrmlTableNode()
        if tableNode and row < tableNode.GetNumberOfRows():
            self.logic.focusCrossing(tableNode.GetCellText(row, 0))

    def onExportStatistics(self) -> None:
        path = qt.QFileDialog.getSaveFileName(slicer.util.mainWindow(), _("Export statistics"), "", "CSV (*.csv)")
        if path:
            self.logic.exportStatistics(path)


#
# VEScanLogic
#


class VEScanLogic(ScriptedLoadableModuleLogic):
    """Stubs: they only log their arguments. Values marked "fake" let the UI move on."""

    def __init__(self) -> None:
        ScriptedLoadableModuleLogic.__init__(self)
        self._cancelRequested = False
        self.crossingsTableNode = None

    def getParameterNode(self):
        return VEScanParameterNode(super().getParameterNode())

    # Inputs

    def loadCT(self, source, node=None, path=None):
        logging.info(f"loadCT({source}, {node}, {path})")

    def loadStructure(self, name, source, segmentation=None, segmentId=None, path=None):
        logging.info(f"loadStructure({name}, {source}, {segmentation}, {segmentId}, {path})")

    def loadStore(self, path):
        logging.info(f"loadStore({path})")

    def loadLobes(self, source, segmentation=None, path=None):
        logging.info(f"loadLobes({source}, {segmentation}, {path})")
        # fake
        return [f"Segment_{i}" for i in range(1, 6)] if source == "scene" else [1, 2, 3, 4, 5]

    # Run

    def run(self, params, progressCallback) -> bool:
        """Fake run: report progress for each stage and structure. Returns False if cancelled."""
        self._cancelRequested = False
        stages = [stage for stage, enabled in [("preprocess", params.stagePreprocess),
                                               ("centerlines", params.stageCenterlines),
                                               ("anatomy", params.stageAnatomy)] if enabled]
        stages.append("surface labels")
        structures = [s for s in STRUCTURES if getattr(params, f"run{s.capitalize()}")]
        for stage in stages:
            for i, structure in enumerate(structures, start=1):
                if self._cancelRequested:
                    progressCallback(stage, structure, i - 1, len(structures), "Cancelled.")
                    return False
                progressCallback(stage, structure, i, len(structures), f"{stage}: {structure} done")
                slicer.app.processEvents()
                time.sleep(0.2)
        return True

    def cancel(self):
        logging.info("cancel()")
        self._cancelRequested = True

    # Cut tree

    def getGenerationRange(self, structure):
        logging.info(f"getGenerationRange({structure})")
        return (1, 12)  # fake

    def previewCut(self, structure, generations):
        logging.info(f"previewCut({structure}, {generations})")

    def applyCut(self, structure, generations, cap=True):
        logging.info(f"applyCut({structure}, {generations}, {cap})")

    # Results

    def loadResults(self, outputDir):
        """Fake: an empty crossings table with the final columns."""
        logging.info(f"loadResults({outputDir})")
        if not self.crossingsTableNode or not slicer.mrmlScene.IsNodePresent(self.crossingsTableNode):
            self.crossingsTableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "VE-SCAN crossings")
            self.crossingsTableNode.SetUseColumnTitleAsColumnHeader(True)
            self.crossingsTableNode.SetLocked(True)
            for name in CROSSING_COLUMNS:
                self.crossingsTableNode.AddColumn().SetName(name)
        return self.crossingsTableNode

    def setVisibility(self, kind, visible):
        logging.info(f"setVisibility({kind}, {visible})")

    def setColorBy(self, arrayName):
        logging.info(f"setColorBy({arrayName})")

    def focusCrossing(self, crossingId):
        logging.info(f"focusCrossing({crossingId})")

    def exportStatistics(self, path):
        logging.info(f"exportStatistics({path})")


#
# VEScanTest
#


class VEScanTest(ScriptedLoadableModuleTest):
    def setUp(self):
        slicer.mrmlScene.Clear()

    def runTest(self):
        self.setUp()
        self.test_FakeRun()

    def test_FakeRun(self):
        logic = VEScanLogic()
        params = logic.getParameterNode()
        steps = []
        self.assertTrue(logic.run(params, lambda *args: steps.append(args)))
        self.assertEqual(len(steps), 4 * 3)  # 3 stages + surface labels, 3 structures
        self.assertEqual(logic.getGenerationRange("artery"), (1, 12))
        self.assertEqual(logic.loadResults("").GetNumberOfColumns(), len(CROSSING_COLUMNS))
        self.delayDisplay("Test passed")
