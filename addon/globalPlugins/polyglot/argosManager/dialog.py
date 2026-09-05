# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""wx dialog for managing Argos Translate offline models."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, TypeVar

import addonHandler
import gui
import wx
from gui import nvdaControls
from gui.guiHelper import wxCallOnMain
from logHandler import log

from ..modelManager.installer import InstallProgress, isFileInUseFailure
from .catalog import (
	DEFAULT_INDEX_URL,
	ArgosCatalog,
	ArgosPackage,
	normalizeIndexUrl,
	pairDisplayName,
	resolveInitialIndexUrl,
)
from .installer import (
	ARGOS_OPERATION_LOCK,
	ArgosInstaller,
	InstalledPackage,
	formatFileInUseFailure,
)
from .service import DIALOG_TITLE, formatSize, getArgosService
from .settings import ArgosManagerSettings

addonHandler.initTranslation()

_WorkerResult = TypeVar("_WorkerResult")
_ClearCacheResult = tuple[Literal["empty", "cancelled", "cleared"], float]


@dataclass(frozen=True)
class PendingOperations:
	"""Pending operation counts for the current checklist state."""

	installCount: int
	removeCount: int
	updateCount: int
	cleanupCount: int

	@property
	def total(self) -> int:
		"""Return the total pending operation count."""
		return self.installCount + self.removeCount + self.updateCount + self.cleanupCount


class ThrottledWxProgress:
	"""Throttles worker-thread progress updates before posting them to wx."""

	def __init__(self, callback: Callable[[InstallProgress], None]) -> None:
		"""Initialize throttling for progress sent to the supplied UI callback."""
		self._callback = callback
		self._lastPostTime = 0.0
		self._lastPercent = -1

	def report(self, progress: InstallProgress) -> None:
		"""Post meaningful progress updates to the wx main thread."""
		now = time.monotonic()
		percent = progress.percent if progress.percent is not None else -1
		isImportant = progress.percent is None or percent in (0, 100)
		hasPercentMoved = percent >= 0 and abs(percent - self._lastPercent) >= 5
		if not isImportant and not hasPercentMoved and now - self._lastPostTime < 0.25:
			return
		if not isImportant and now - self._lastPostTime < 0.1:
			return
		self._lastPostTime = now
		self._lastPercent = percent
		wx.CallAfter(self._callback, progress)


class ArgosModelManagerDialog(nvdaControls.DPIScaledDialog):
	"""Modeless dialog for installing, updating, and removing Argos models."""

	def __init__(self, parent: wx.Window) -> None:
		"""Initialize the Argos model manager and its persisted settings."""
		super().__init__(
			parent,
			title=DIALOG_TITLE,
			size=(920, 720),
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)
		self.service = getArgosService()
		self.installer: ArgosInstaller = self.service.installer
		self.settings = ArgosManagerSettings.load(self.installer.polyglotRoot)
		self.catalog: ArgosCatalog | None = None
		self.packages: list[ArgosPackage] = []
		self.installedKeys: set[str] = set()
		self.outdatedKeys: set[str] = set()
		self.pendingOperationCount = 0
		self.isBusy = False
		self.isUpdatingPackageChecks = False
		self.isAdvancedVisible = False
		self.isDestroyed = False
		self.lastLogMessage = ""
		self.logLineCount = 0
		self._sizeFetchThread: threading.Thread | None = None
		self._buildUi()
		self.SetMinSize((760, 560))
		self.SetEscapeId(wx.ID_CLOSE)
		self.Bind(wx.EVT_CLOSE, self.onClose)
		self.Bind(wx.EVT_WINDOW_DESTROY, self.onDestroy)
		wx.CallAfter(self.loadCatalog)

	def _buildUi(self) -> None:
		"""Build dialog controls."""
		root = wx.BoxSizer(wx.VERTICAL)
		self.SetSizer(root)

		self.advancedPanel = wx.Panel(self)
		self._buildAdvancedPanel()
		self.advancedPanel.Hide()
		root.Add(self.advancedPanel, 0, wx.EXPAND | wx.ALL, 10)

		root.Add(
			wx.StaticText(
				self,
				label=_(
					"Languages: check a language pair to install it; uncheck an installed pair to remove it.",
				),
			),
			0,
			wx.LEFT | wx.RIGHT | wx.TOP | wx.BOTTOM,
			10,
		)
		self.packageList = nvdaControls.AutoWidthColumnCheckListCtrl(
			self,
			style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_HRULES | wx.LC_VRULES,
		)
		for columnIndex, (label, width) in enumerate(
			(
				(_("Languages"), 320),
				(_("Status"), 150),
				(_("Download size"), 130),
				(_("Version"), 100),
			),
		):
			self.packageList.InsertColumn(columnIndex, label, width=width)
		self.packageList.Bind(wx.EVT_CHECKLISTBOX, self.onPackageChecked)
		self.packageList.SetMinSize((-1, 220))
		root.Add(self.packageList, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

		self.selectionLabel = wx.StaticText(self, label="")
		root.Add(self.selectionLabel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

		buttonRow = wx.BoxSizer(wx.HORIZONTAL)
		self.applyButton = wx.Button(self, label=_("Apply changes ({count})").format(count=0))
		self.updateButton = wx.Button(self, label=_("Update all ({count})").format(count=0))
		self.unloadButton = wx.Button(self, label=_("Unload models"))
		self.advancedButton = wx.Button(self, label=_("Advanced"))
		self.closeButton = wx.Button(self, id=wx.ID_CLOSE)
		self.applyButton.Bind(wx.EVT_BUTTON, self.onApply)
		self.updateButton.Bind(wx.EVT_BUTTON, self.onUpdateAll)
		self.unloadButton.Bind(wx.EVT_BUTTON, self.onUnloadModels)
		self.advancedButton.Bind(wx.EVT_BUTTON, self.onToggleAdvanced)
		self.closeButton.Bind(wx.EVT_BUTTON, lambda evt: self.Close())
		for button in (self.applyButton, self.updateButton, self.unloadButton, self.advancedButton):
			buttonRow.Add(button)
			buttonRow.AddSpacer(8)
		buttonRow.AddStretchSpacer()
		buttonRow.Add(self.closeButton)
		root.Add(buttonRow, 0, wx.EXPAND | wx.ALL, 10)

		logLabel = wx.StaticText(self, label=_("Log"))
		root.Add(logLabel, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
		self.logBox = wx.TextCtrl(
			self,
			style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
			size=(-1, 90),
		)
		root.Add(self.logBox, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

		self.progressGauge = wx.Gauge(self, range=100)
		root.Add(self.progressGauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
		self.progressGauge.Hide()
		self.refreshButtons()

	def _buildAdvancedPanel(self) -> None:
		"""Build the collapsible advanced settings panel."""
		panelSizer = wx.BoxSizer(wx.VERTICAL)
		self.advancedPanel.SetSizer(panelSizer)

		urlRow = wx.BoxSizer(wx.HORIZONTAL)
		urlLabel = wx.StaticText(self.advancedPanel, label=_("Package index URL:"))
		self.indexUrlBox = wx.TextCtrl(
			self.advancedPanel,
			value=resolveInitialIndexUrl(self.settings.indexUrl),
		)
		self.defaultIndexButton = wx.Button(self.advancedPanel, label=_("Restore default"))
		self.defaultIndexButton.Bind(wx.EVT_BUTTON, self.onDefaultIndex)
		urlRow.Add(urlLabel, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
		urlRow.Add(self.indexUrlBox, 1, wx.ALIGN_CENTER_VERTICAL)
		urlRow.AddSpacer(8)
		urlRow.Add(self.defaultIndexButton)
		panelSizer.Add(urlRow, 0, wx.EXPAND)

		self.indexLabel = wx.StaticText(self.advancedPanel, label=_("Package index: not loaded"))
		self.runtimeLabel = wx.StaticText(self.advancedPanel, label="")
		self.targetLabel = wx.StaticText(
			self.advancedPanel,
			label=_("Install target: {path}").format(path=self.installer.argosRoot),
		)
		self.statusLabel = wx.StaticText(self.advancedPanel, label=_("Status: idle"))
		panelSizer.Add(self.indexLabel, 0, wx.EXPAND | wx.TOP, 8)
		panelSizer.Add(self.runtimeLabel, 0, wx.EXPAND | wx.TOP, 4)
		panelSizer.Add(self.targetLabel, 0, wx.EXPAND | wx.TOP, 4)

		advancedButtons = wx.BoxSizer(wx.HORIZONTAL)
		self.reloadButton = wx.Button(self.advancedPanel, label=_("Load package index"))
		self.openTargetButton = wx.Button(self.advancedPanel, label=_("Open target"))
		self.clearCacheButton = wx.Button(self.advancedPanel, label=_("Clear unfinished downloads"))
		self.reloadButton.Bind(wx.EVT_BUTTON, self.onReloadCatalog)
		self.openTargetButton.Bind(wx.EVT_BUTTON, lambda evt: self.openDirectory(self.installer.argosRoot))
		self.clearCacheButton.Bind(wx.EVT_BUTTON, self.onClearCache)
		for button in (self.reloadButton, self.openTargetButton, self.clearCacheButton):
			advancedButtons.Add(button)
			advancedButtons.AddSpacer(8)
		panelSizer.Add(advancedButtons, 0, wx.TOP, 8)
		panelSizer.Add(self.statusLabel, 0, wx.EXPAND | wx.TOP, 8)

	# --- Events ---

	def onPackageChecked(self, evt: wx.CommandEvent) -> None:
		"""Update the operation summary when a checklist item changes."""
		if not self.isUpdatingPackageChecks:
			self.updateSelectionSummary()
		evt.Skip()

	def onToggleAdvanced(self, evt: wx.CommandEvent) -> None:
		"""Show or hide advanced settings."""
		self.setAdvancedVisible(not self.isAdvancedVisible)

	def onDefaultIndex(self, evt: wx.CommandEvent) -> None:
		"""Reset the package index URL to the Argos default and reload it."""
		self.indexUrlBox.SetValue(DEFAULT_INDEX_URL)
		self.loadCatalog()

	def onReloadCatalog(self, evt: wx.CommandEvent) -> None:
		"""Reload the package index from the current advanced URL."""
		self.loadCatalog()

	def onApply(self, evt: wx.CommandEvent) -> None:
		"""Install checked packages and remove unchecked ones, in a background thread."""
		if self.catalog is None or self.isBusy:
			return
		selected = self.getSelectedPackageKeys()
		if not self.confirmPendingRemoval(selected):
			return
		self.startOperation(selected, set())

	def onUpdateAll(self, evt: wx.CommandEvent) -> None:
		"""Reinstall every installed package the index offers a newer version of."""
		if self.catalog is None or self.isBusy or not self.outdatedKeys:
			return
		self.startOperation(self.getSelectedPackageKeys() | self.installedKeys, set(self.outdatedKeys))

	def onUnloadModels(self, evt: wx.CommandEvent) -> None:
		"""Release loaded models, so their files can be removed or updated."""
		count = self.service.translator.unloadModels()
		message = (
			_("Unloaded {count} model(s) from memory.").format(count=count)
			if count
			else _("No models are loaded.")
		)
		self.setStatus(message)
		self.log(message)
		self.refreshButtons()

	def onClearCache(self, evt: wx.CommandEvent) -> None:
		"""Clear unfinished downloads in a background thread."""
		if self.isBusy:
			return
		self.setBusy(True)
		self._startWorker(self._clearCacheWorker, self._onClearCacheWorkerDone)

	def onClose(self, evt: wx.CloseEvent) -> None:
		"""Close only when no model operation is running."""
		if self.isBusy:
			evt.Veto()
			gui.messageBox(
				_("An Argos model operation is still running."),
				DIALOG_TITLE,
				wx.OK | wx.ICON_INFORMATION,
				self,
			)
			return
		self.Destroy()

	def onDestroy(self, evt: wx.WindowDestroyEvent) -> None:
		"""Clear the global dialog reference when this dialog is destroyed."""
		if evt.GetEventObject() is not self:
			evt.Skip()
			return
		self.isDestroyed = True
		from . import menu

		menu.clearDialogReference(self)
		evt.Skip()

	# --- Package index ---

	def loadCatalog(self) -> None:
		"""Load the package index without blocking the user interface."""
		if self.isBusy:
			return
		try:
			indexUrl = normalizeIndexUrl(self.indexUrlBox.GetValue())
			self.indexUrlBox.SetValue(indexUrl)
		except RuntimeError as exc:
			self.setStatus(_("Failed."))
			gui.messageBox(str(exc), DIALOG_TITLE, wx.OK | wx.ICON_ERROR, self)
			return
		self.setBusy(True)
		self.log(_("Loading the package index: {url}").format(url=indexUrl))
		self._startWorker(lambda: self._loadCatalogWorker(indexUrl), self._onLoadCatalogWorkerDone)

	def _loadCatalogWorker(self, indexUrl: str) -> tuple[ArgosCatalog, str, bool]:
		"""Worker body for loading the package index."""
		try:
			catalog = ArgosCatalog.loadRemote(indexUrl)
			return catalog, _("Package index: downloaded from {url}").format(url=indexUrl), True
		except Exception as exc:
			wx.CallAfter(self.log, _("The package index could not be downloaded: {error}").format(error=exc))
			cached = self.installer.loadCachedIndex()
			if cached is not None:
				return cached, _("Package index: last downloaded copy"), False
			return ArgosCatalog.loadBundled(), _("Package index: the copy Polyglot ships with"), False

	def _onLoadCatalogWorkerDone(self, result: tuple[ArgosCatalog, str, bool] | BaseException) -> None:
		"""Handle package index load completion."""
		if self.isDestroyed:
			return
		self.setBusy(False)
		if isinstance(result, BaseException):
			self.catalog = None
			self.packages = []
			self.packageList.DeleteAllItems()
			self.indexLabel.SetLabel(_("Package index: could not be read"))
			self.showFailure(result)
			return
		catalog, label, isFromNetwork = result
		self.catalog = catalog
		self.service.setCatalog(catalog)
		self.indexLabel.SetLabel(label)
		if isFromNetwork:
			self.installer.saveIndexCache(catalog)
			self.saveIndexUrl(self.indexUrlBox.GetValue())
		self.populatePackageList()
		self.log(_("The package index offers {count} language pair(s).").format(count=len(catalog.packages)))
		self.startSizeFetch()

	# --- Model operations ---

	def startOperation(self, selectedKeys: set[str], keysToUpdate: set[str]) -> None:
		"""Run one install, update, and removal pass in a background thread."""
		self.setBusy(True)
		self._startWorker(
			lambda: self._applySelectionWorker(selectedKeys, keysToUpdate),
			self._onApplyWorkerDone,
		)

	def _applySelectionWorker(self, selected: set[str], keysToUpdate: set[str]) -> BaseException | None:
		"""Worker body for applying the selected packages."""
		if self.catalog is None:
			return RuntimeError(_("The package index is not loaded."))
		if not ARGOS_OPERATION_LOCK.acquire(blocking=False):
			return RuntimeError(_("Another Argos model operation is already running."))
		progress = ThrottledWxProgress(self.updateProgress)
		try:
			try:
				self.installer.applySelection(self.catalog, selected, progress.report, keysToUpdate)
			except Exception as exc:
				if isFileInUseFailure(exc):
					return RuntimeError(formatFileInUseFailure(exc))
				return exc
			return None
		finally:
			ARGOS_OPERATION_LOCK.release()

	def _onApplyWorkerDone(self, result: BaseException | None) -> None:
		"""Handle install and removal completion."""
		if self.isDestroyed:
			return
		self.setBusy(False)
		if isinstance(result, BaseException):
			self.showFailure(result)
			self.populatePackageList()
			return
		self.setStatus(_("Changes applied."))
		self.log(_("Changes applied."))
		self.populatePackageList()

	def _clearCacheWorker(self) -> _ClearCacheResult | BaseException:
		"""Worker body for clearing unfinished downloads."""
		try:
			cacheBytes = self.installer.getDownloadCacheSize()
			if cacheBytes == 0:
				return "empty", 0.0
			answer = wxCallOnMain(
				gui.messageBox,
				_(
					"This will delete {size:.1f} MiB of unfinished downloads. "
					"Installed models will not be removed.\n\nContinue?",
				).format(size=cacheBytes / 1024 / 1024),
				DIALOG_TITLE,
				wx.YES_NO | wx.ICON_QUESTION,
				self,
			)
			if answer != wx.YES:
				return "cancelled", 0.0
			if not ARGOS_OPERATION_LOCK.acquire(blocking=False):
				return RuntimeError(_("Another Argos model operation is already running."))
			try:
				progress = ThrottledWxProgress(self.updateProgress)
				clearedBytes = self.installer.clearDownloadCache(progress.report)
				return "cleared", clearedBytes / 1024 / 1024
			finally:
				ARGOS_OPERATION_LOCK.release()
		except Exception as exc:
			return exc

	def _onClearCacheWorkerDone(self, result: _ClearCacheResult | BaseException) -> None:
		"""Handle download cache clearing completion."""
		if self.isDestroyed:
			return
		self.setBusy(False)
		if isinstance(result, BaseException):
			self.showFailure(result)
			return
		state, size = result
		if state == "empty":
			message = _("There are no unfinished downloads.")
		elif state == "cleared":
			message = _("Cleared unfinished downloads ({size:.1f} MiB).").format(size=size)
		else:
			self.updateSelectionSummary()
			return
		self.setStatus(message)
		self.log(message)
		self.updateSelectionSummary()

	# --- Package list ---

	def populatePackageList(self) -> None:
		"""Populate the checklist from the package index and what is installed."""
		if self.catalog is None:
			return
		installedByKey = self.installer.getInstalledByKey()
		self.installedKeys = set(installedByKey)
		self.outdatedKeys = self.installer.getOutdatedKeys(self.catalog)
		self.packages = list(self.catalog.packages)
		self.isUpdatingPackageChecks = True
		self.packageList.Freeze()
		try:
			self.packageList.DeleteAllItems()
			for index, package in enumerate(self.packages):
				installed = installedByKey.get(package.key)
				_unused = self.packageList.InsertItem(index, pairDisplayName(package))
				self.packageList.SetItem(index, 1, self.formatStatus(package, installed is not None))
				self.packageList.SetItem(index, 2, self.formatPackageSize(package))
				self.packageList.SetItem(index, 3, self.formatVersion(package, installed))
				self.packageList.CheckItem(index, package.key in self.installedKeys)
		finally:
			self.packageList.Thaw()
			self.isUpdatingPackageChecks = False
		self.selectFirstPackageListItem()
		self.refreshRuntimeLabel()
		self.setStatus(
			_("{count} language pair(s) installed, using {size}.").format(
				count=len(self.installedKeys),
				size=formatSize(self.installer.getInstalledSize()),
			),
		)
		self.updateSelectionSummary()

	def formatStatus(self, package: ArgosPackage, isInstalled: bool) -> str:
		"""Return the status column text for one package."""
		if not isInstalled:
			return _("not installed")
		if package.key in self.outdatedKeys:
			return _("update available")
		return _("installed")

	def formatVersion(self, package: ArgosPackage, installed: InstalledPackage | None) -> str:
		"""Return the version column text, showing both versions when an update is waiting."""
		if package.key in self.outdatedKeys and installed is not None:
			return _("{installed} to {available}").format(
				installed=installed.packageVersion,
				available=package.packageVersion,
			)
		return package.packageVersion

	def formatPackageSize(self, package: ArgosPackage) -> str:
		"""Return the download size column text, which is filled in as sizes are learned."""
		size = self.installer.getCachedSize(package)
		return formatSize(size) if size > 0 else ""

	def selectFirstPackageListItem(self) -> None:
		"""Select the first row without changing its checked state."""
		if self.packageList.ItemCount == 0:
			return
		self.packageList.SetItemState(
			0,
			wx.LIST_STATE_FOCUSED | wx.LIST_STATE_SELECTED,
			wx.LIST_STATE_FOCUSED | wx.LIST_STATE_SELECTED,
		)
		self.packageList.EnsureVisible(0)

	def startSizeFetch(self) -> None:
		"""Learn the download size of each package in the background.

		The Argos index does not carry package sizes, so they are asked for once and remembered.
		"""
		if self._sizeFetchThread is not None and self._sizeFetchThread.is_alive():
			return
		packages = list(self.packages)
		if not packages:
			return

		def onSize(package: ArgosPackage, size: int) -> None:
			wx.CallAfter(self.updatePackageSize, package.key, size)

		def run() -> None:
			try:
				self.installer.fetchSizes(packages, onSize, lambda: self.isDestroyed)
			except Exception:
				log.debug("Argos: package sizes could not be collected.", exc_info=True)

		self._sizeFetchThread = threading.Thread(
			name=f"{self.__class__.__module__}.fetchSizes",
			target=run,
			daemon=True,
		)
		self._sizeFetchThread.start()

	def updatePackageSize(self, key: str, size: int) -> None:
		"""Fill in one package's download size once it is known."""
		if self.isDestroyed:
			return
		for index, package in enumerate(self.packages):
			if package.key == key:
				self.packageList.SetItem(index, 2, formatSize(size))
				return

	# --- Selection state ---

	def getSelectedPackageKeys(self) -> set[str]:
		"""Return the keys of checked packages."""
		return {
			self.packages[index].key
			for index in self.packageList.GetCheckedItems()
			if 0 <= index < len(self.packages)
		}

	def confirmPendingRemoval(self, selected: set[str]) -> bool:
		"""Confirm removal of installed packages that were unchecked."""
		if self.catalog is None:
			return False
		toRemove = [
			package
			for package in self.catalog.packages
			if package.key in self.installedKeys and package.key not in selected
		]
		if not toRemove:
			return True
		names = "\n".join(f"  - {pairDisplayName(package)}" for package in toRemove)
		answer = gui.messageBox(
			_("The following installed language pair(s) will be removed:\n\n{names}\n\nContinue?").format(
				names=names,
			),
			DIALOG_TITLE,
			wx.YES_NO | wx.ICON_WARNING,
			self,
		)
		return answer == wx.YES

	def updateSelectionSummary(self) -> None:
		"""Update the selection summary and the state of the action buttons."""
		if self.catalog is None or not self.packages:
			self.selectionLabel.SetLabel("")
			self.pendingOperationCount = 0
			self.refreshButtons()
			return
		selected = self.getSelectedPackageKeys()
		pending = self.calculatePendingOperations(selected)
		self.pendingOperationCount = pending.installCount + pending.removeCount + pending.cleanupCount
		self.selectionLabel.SetLabel(
			_(
				"Selected: {selected} | Install: {install} | Remove: {remove} | "
				"Updates available: {update} | Download: {download}",
			).format(
				selected=len(selected),
				install=pending.installCount,
				remove=pending.removeCount,
				update=pending.updateCount,
				download=formatSize(self.calculateDownloadSize(selected)),
			),
		)
		self.refreshButtons()

	def calculatePendingOperations(self, selected: set[str]) -> PendingOperations:
		"""Count what applying the current checklist would do."""
		installCount = sum(1 for key in selected if key not in self.installedKeys)
		removeCount = sum(1 for key in self.installedKeys if key not in selected)
		cleanupCount = 1 if self.installer.hasDownloadCacheFiles() else 0
		return PendingOperations(installCount, removeCount, len(self.outdatedKeys), cleanupCount)

	def calculateDownloadSize(self, selected: set[str]) -> int:
		"""Return how much applying the current checklist would download."""
		total = 0
		if not self.installer.runtime.isInstalled() and any(
			key not in self.installedKeys for key in selected
		):
			total += self.installer.runtime.downloadSize
		for package in self.packages:
			if package.key in selected and package.key not in self.installedKeys:
				total += self.installer.getCachedSize(package)
		return total

	# --- Dialog state ---

	def setBusy(self, isBusy: bool) -> None:
		"""Enable or disable controls based on operation state."""
		if self.isDestroyed:
			return
		self.isBusy = isBusy
		for control in (
			self.advancedButton,
			self.unloadButton,
			self.indexUrlBox,
			self.defaultIndexButton,
			self.reloadButton,
			self.openTargetButton,
			self.clearCacheButton,
			self.packageList,
		):
			control.Enable(not isBusy)
		self.progressGauge.Show(isBusy)
		if isBusy:
			self.progressGauge.SetValue(0)
		self.refreshButtons()
		self.Layout()

	def refreshButtons(self) -> None:
		"""Refresh the action buttons' labels and enabled state."""
		isHostSupported = self.installer.runtime.isHostSupported
		self.applyButton.SetLabel(_("Apply changes ({count})").format(count=self.pendingOperationCount))
		self.applyButton.Enable(
			not self.isBusy
			and isHostSupported
			and self.catalog is not None
			and self.pendingOperationCount > 0,
		)
		self.updateButton.SetLabel(_("Update all ({count})").format(count=len(self.outdatedKeys)))
		self.updateButton.Enable(not self.isBusy and isHostSupported and bool(self.outdatedKeys))
		self.unloadButton.Enable(not self.isBusy and self.service.translator.hasLoadedModels)

	def refreshRuntimeLabel(self) -> None:
		"""Describe the state of the Argos runtime in the advanced panel."""
		runtime = self.installer.runtime
		if not runtime.isHostSupported:
			label = runtime.unsupportedHostMessage
			self.log(label)
		elif runtime.isInstalled():
			versions = ", ".join(
				f"{name} {version}" for name, version in sorted(runtime.getInstalledVersions().items())
			)
			label = _("Runtime: installed ({versions})").format(versions=versions)
		else:
			label = _("Runtime: not installed; {size} is downloaded with the first model.").format(
				size=formatSize(runtime.downloadSize),
			)
		self.runtimeLabel.SetLabel(label)

	def setAdvancedVisible(self, isVisible: bool) -> None:
		"""Set advanced settings visibility."""
		self.isAdvancedVisible = isVisible
		self.advancedPanel.Show(isVisible)
		self.advancedButton.SetLabel(_("Hide advanced") if isVisible else _("Advanced"))
		self.Layout()

	def setStatus(self, message: str) -> None:
		"""Update the advanced status label."""
		self.statusLabel.SetLabel(_("Status: {message}").format(message=message))

	def updateProgress(self, progress: InstallProgress) -> None:
		"""Update the status, log, and progress gauge."""
		if self.isDestroyed:
			return
		self.setStatus(progress.message)
		if progress.percent is not None:
			self.progressGauge.SetValue(max(0, min(100, progress.percent)))
		self.log(progress.message)

	def log(self, message: str) -> None:
		"""Append a short timestamped log line."""
		if self.isDestroyed:
			return
		if message == self.lastLogMessage:
			return
		self.lastLogMessage = message
		if self.logLineCount >= 500:
			self.logBox.Clear()
			self.logLineCount = 0
		self.logBox.AppendText(f"[{time.strftime('%H:%M')}] {message}\n")
		self.logLineCount += 1

	def showFailure(self, error: BaseException) -> None:
		"""Log and show an operation failure."""
		self.setStatus(_("Failed."))
		self.log(str(error))
		log.error("Argos model manager operation failed (%s).", type(error).__name__)
		gui.messageBox(str(error), DIALOG_TITLE, wx.OK | wx.ICON_ERROR, self)

	def saveIndexUrl(self, indexUrl: str) -> None:
		"""Remember the last package index URL that worked."""
		try:
			self.settings.indexUrl = indexUrl
			self.settings.save(self.installer.polyglotRoot)
		except Exception as exc:
			self.log(_("Settings could not be saved: {error}").format(error=exc))

	def openDirectory(self, path: os.PathLike[str]) -> None:
		"""Open a directory in File Explorer."""
		try:
			directory = os.fspath(path)
			os.makedirs(directory, exist_ok=True)
			os.startfile(directory)  # type: ignore[attr-defined]
		except OSError as exc:
			self.showFailure(exc)

	def _startWorker(
		self,
		target: Callable[[], _WorkerResult],
		done: Callable[[_WorkerResult | BaseException], None],
	) -> None:
		"""Run a blocking operation in a daemon thread and post completion to wx."""

		def run() -> None:
			try:
				result = target()
			except Exception as exc:
				result = exc
			wx.CallAfter(self._finishWorker, done, result)

		thread = threading.Thread(
			name=f"{self.__class__.__module__}.{getattr(target, '__name__', 'worker')}",
			target=run,
			daemon=True,
		)
		thread.start()

	def _finishWorker(
		self,
		done: Callable[[_WorkerResult | BaseException], None],
		result: _WorkerResult | BaseException,
	) -> None:
		"""Dispatch worker completion only while the dialog is still alive."""
		if self.isDestroyed:
			return
		done(result)
