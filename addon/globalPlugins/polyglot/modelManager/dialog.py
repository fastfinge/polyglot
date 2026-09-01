# -*- coding: utf-8 -*-
# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""wx dialog for native ChromeAI model management."""

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

from .catalog import (
	DEFAULT_CATALOG_URL,
	ModelCatalog,
	ModelPackage,
	normalizeCatalogUrl,
	pairDisplayName,
	resolveInitialCatalogUrl,
)
from .installer import (
	MODEL_OPERATION_LOCK,
	InstallProgress,
	ModelInstaller,
	formatFileInUseFailure,
	isFileInUseFailure,
)
from .settings import ModelManagerSettings

addonHandler.initTranslation()

_WorkerResult = TypeVar("_WorkerResult")
_ClearCacheResult = tuple[Literal["empty", "cancelled", "cleared"], float]


@dataclass(frozen=True)
class PendingOperations:
	"""Pending operation counts for the current checklist state."""

	installCount: int
	removeCount: int
	cleanupCount: int

	@property
	def total(self) -> int:
		"""Return the total pending operation count."""
		return self.installCount + self.removeCount + self.cleanupCount


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


class ModelManagerDialog(nvdaControls.DPIScaledDialog):
	"""Modeless dialog for selecting, installing, and removing ChromeAI models."""

	def __init__(self, parent: wx.Window) -> None:
		"""Initialize the model manager dialog and its persisted settings."""
		super().__init__(
			parent,
			title=_("Polyglot ChromeAI Model Manager"),
			size=(920, 720),
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)
		self.installer = ModelInstaller()
		self.settings = ModelManagerSettings.load(self.installer.polyglotRoot)
		self.catalog: ModelCatalog | None = None
		self.packages: list[ModelPackage] = []
		self.installedKeys: set[str] = set()
		self.pendingOperationCount = 0
		self.isBusy = False
		self.isUpdatingPackageChecks = False
		self.isAdvancedVisible = False
		self.isDestroyed = False
		self.lastLogMessage = ""
		self.logLineCount = 0
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
				label=_("Models: check a model to install it; uncheck an installed model to remove it."),
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
				(_("Language"), 300),
				(_("Status"), 105),
				(_("Size"), 125),
				(_("Version"), 130),
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
		self.advancedButton = wx.Button(self, label=_("Advanced"))
		self.closeButton = wx.Button(self, id=wx.ID_CLOSE)
		self.applyButton.Bind(wx.EVT_BUTTON, self.onApply)
		self.advancedButton.Bind(wx.EVT_BUTTON, self.onToggleAdvanced)
		self.closeButton.Bind(wx.EVT_BUTTON, lambda evt: self.Close())
		buttonRow.Add(self.applyButton)
		buttonRow.AddSpacer(8)
		buttonRow.Add(self.advancedButton)
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
		self.refreshApplyButton()

	def _buildAdvancedPanel(self) -> None:
		"""Build the collapsible advanced settings panel."""
		panelSizer = wx.BoxSizer(wx.VERTICAL)
		self.advancedPanel.SetSizer(panelSizer)

		urlRow = wx.BoxSizer(wx.HORIZONTAL)
		urlLabel = wx.StaticText(self.advancedPanel, label=_("Catalog URL:"))
		self.catalogUrlBox = wx.TextCtrl(
			self.advancedPanel,
			value=resolveInitialCatalogUrl(self.settings.catalogUrl),
		)
		self.defaultCatalogButton = wx.Button(self.advancedPanel, label=_("Restore default"))
		self.defaultCatalogButton.Bind(wx.EVT_BUTTON, self.onDefaultCatalog)
		urlRow.Add(urlLabel, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
		urlRow.Add(self.catalogUrlBox, 1, wx.ALIGN_CENTER_VERTICAL)
		urlRow.AddSpacer(8)
		urlRow.Add(self.defaultCatalogButton)
		panelSizer.Add(urlRow, 0, wx.EXPAND)

		self.catalogLabel = wx.StaticText(self.advancedPanel, label=_("Catalog: not loaded"))
		self.targetLabel = wx.StaticText(
			self.advancedPanel,
			label=_("Install target: {path}").format(path=self.installer.profileDir),
		)
		self.statusLabel = wx.StaticText(self.advancedPanel, label=_("Status: idle"))
		panelSizer.Add(self.catalogLabel, 0, wx.EXPAND | wx.TOP, 8)
		panelSizer.Add(self.targetLabel, 0, wx.EXPAND | wx.TOP, 4)

		advancedButtons = wx.BoxSizer(wx.HORIZONTAL)
		self.reloadButton = wx.Button(self.advancedPanel, label=_("Load catalog"))
		self.openTargetButton = wx.Button(self.advancedPanel, label=_("Open target"))
		self.clearCacheButton = wx.Button(self.advancedPanel, label=_("Clear cache"))
		self.openTempButton = wx.Button(self.advancedPanel, label=_("Open temp downloads"))
		self.reloadButton.Bind(wx.EVT_BUTTON, self.onReloadCatalog)
		self.openTargetButton.Bind(wx.EVT_BUTTON, lambda evt: self.openDirectory(self.installer.profileDir))
		self.clearCacheButton.Bind(wx.EVT_BUTTON, self.onClearCache)
		self.openTempButton.Bind(
			wx.EVT_BUTTON,
			lambda evt: self.openDirectory(self.installer.tempDownloadDir),
		)
		for button in (self.reloadButton, self.openTargetButton, self.clearCacheButton, self.openTempButton):
			advancedButtons.Add(button)
			advancedButtons.AddSpacer(8)
		panelSizer.Add(advancedButtons, 0, wx.TOP, 8)
		panelSizer.Add(self.statusLabel, 0, wx.EXPAND | wx.TOP, 8)

	def onPackageChecked(self, evt: wx.CommandEvent) -> None:
		"""Update operation summary when a checklist item changes."""
		if not self.isUpdatingPackageChecks:
			self.updateSelectionSummary()
		evt.Skip()

	def onToggleAdvanced(self, evt: wx.CommandEvent) -> None:
		"""Show or hide advanced settings."""
		self.setAdvancedVisible(not self.isAdvancedVisible)

	def onDefaultCatalog(self, evt: wx.CommandEvent) -> None:
		"""Reset the catalog URL to the default channel and reload."""
		self.catalogUrlBox.SetValue(DEFAULT_CATALOG_URL)
		self.loadCatalog()

	def onReloadCatalog(self, evt: wx.CommandEvent) -> None:
		"""Reload the catalog from the current advanced URL."""
		self.loadCatalog()

	def onApply(self, evt: wx.CommandEvent) -> None:
		"""Apply selected model package state in a background thread."""
		if self.catalog is None or self.isBusy:
			return
		selected = self.getSelectedPackageKeys()
		if not self.confirmPendingRemoval(selected):
			return
		self.setBusy(True)
		self._startWorker(lambda: self._applySelectionWorker(selected), self._onApplyWorkerDone)

	def onClearCache(self, evt: wx.CommandEvent) -> None:
		"""Clear temporary download caches in a background thread."""
		if self.isBusy:
			return
		self.setBusy(True)
		self._startWorker(self._clearCacheWorker, self._onClearCacheWorkerDone)

	def onClose(self, evt: wx.CloseEvent) -> None:
		"""Close only when no model operation is active."""
		if self.isBusy:
			evt.Veto()
			gui.messageBox(
				_("A model operation is still running."),
				_("Polyglot ChromeAI Model Manager"),
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

	def loadCatalog(self) -> None:
		"""Load the model catalog without blocking the UI."""
		if self.isBusy:
			return
		try:
			catalogUrl = normalizeCatalogUrl(self.catalogUrlBox.GetValue())
			self.catalogUrlBox.SetValue(catalogUrl)
		except RuntimeError as exc:
			self.setStatus(_("Failed."))
			gui.messageBox(str(exc), _("Polyglot ChromeAI Model Manager"), wx.OK | wx.ICON_ERROR, self)
			return
		self.setBusy(True)
		self.log(_("Loading catalog: {url}").format(url=catalogUrl))
		self._startWorker(lambda: self._loadCatalogWorker(catalogUrl), self._onLoadCatalogWorkerDone)

	def _loadCatalogWorker(self, catalogUrl: str) -> tuple[ModelCatalog, str, bool]:
		"""Worker body for catalog loading."""
		try:
			catalog = ModelCatalog.loadRemote(catalogUrl)
			return (
				catalog,
				_("Catalog: remote; generated {generatedAt}").format(
					generatedAt=catalog.generatedAt,
				),
				True,
			)
		except Exception as exc:
			wx.CallAfter(self.log, _("Remote catalog failed: {error}").format(error=exc))
			catalog = ModelCatalog.loadBundled()
			return (
				catalog,
				_("Catalog: bundled fallback; generated {generatedAt}").format(
					generatedAt=catalog.generatedAt,
				),
				False,
			)

	def _onLoadCatalogWorkerDone(self, result: tuple[ModelCatalog, str, bool] | BaseException) -> None:
		"""Handle catalog load completion."""
		if self.isDestroyed:
			return
		self.setBusy(False)
		if isinstance(result, BaseException):
			self.catalog = None
			self.packages = []
			self.packageList.DeleteAllItems()
			self.catalogLabel.SetLabel(_("Catalog: failed to load"))
			self.showFailure(result)
			return
		catalog, label, shouldSaveUrl = result
		self.catalog = catalog
		self.catalogLabel.SetLabel(label)
		if shouldSaveUrl:
			self.saveCatalogUrl(self.catalogUrlBox.GetValue())
		self.populatePackageList()
		self.log(_("Loaded {count} model package(s).").format(count=len(catalog.packages)))

	def _applySelectionWorker(self, selected: set[str]) -> BaseException | None:
		"""Worker body for applying selected packages."""
		if self.catalog is None:
			return RuntimeError(_("Catalog: not loaded"))
		if not MODEL_OPERATION_LOCK.acquire(blocking=False):
			return RuntimeError(_("Another model operation is already running."))
		progress = ThrottledWxProgress(self.updateProgress)
		try:
			try:
				self.installer.applySelection(self.catalog, selected, progress.report)
			except Exception as exc:
				if isFileInUseFailure(exc):
					return RuntimeError(formatFileInUseFailure(exc))
				return exc
			return None
		finally:
			MODEL_OPERATION_LOCK.release()

	def _onApplyWorkerDone(self, result: BaseException | None) -> None:
		"""Handle apply completion."""
		if self.isDestroyed:
			return
		self.setBusy(False)
		if isinstance(result, BaseException):
			self.showFailure(result)
			return
		self.setStatus(_("Changes applied."))
		self.log(_("Changes applied."))
		self.populatePackageList()

	def _clearCacheWorker(self) -> _ClearCacheResult | BaseException:
		"""Worker body for clearing temporary caches."""
		try:
			cacheBytes = self.installer.getDownloadCacheSize()
			if cacheBytes == 0:
				return "empty", 0.0
			answer = wxCallOnMain(
				gui.messageBox,
				_(
					"This will delete {size:.1f} MiB of temporary and legacy cached downloads. "
					"Installed models will not be removed.\n\nContinue?",
				).format(size=cacheBytes / 1024 / 1024),
				_("Polyglot ChromeAI Model Manager"),
				wx.YES_NO | wx.ICON_QUESTION,
				self,
			)
			if answer != wx.YES:
				return "cancelled", 0.0
			if not MODEL_OPERATION_LOCK.acquire(blocking=False):
				return RuntimeError(_("Another model operation is already running."))
			try:
				progress = ThrottledWxProgress(self.updateProgress)
				clearedBytes = self.installer.clearDownloadCache(progress.report)
				return "cleared", clearedBytes / 1024 / 1024
			finally:
				MODEL_OPERATION_LOCK.release()
		except Exception as exc:
			return exc

	def _onClearCacheWorkerDone(self, result: _ClearCacheResult | BaseException) -> None:
		"""Handle cache clear completion."""
		if self.isDestroyed:
			return
		self.setBusy(False)
		if isinstance(result, BaseException):
			self.showFailure(result)
			return
		state, size = result
		if state == "empty":
			message = _("Temporary downloads are empty.")
		elif state == "cleared":
			message = _("Cleared temporary downloads ({size:.1f} MiB).").format(size=size)
		else:
			self.updateSelectionSummary()
			return
		self.setStatus(message)
		self.log(message)
		self.updateSelectionSummary()

	def populatePackageList(self) -> None:
		"""Populate the checklist from the current catalog and installed state."""
		if self.catalog is None:
			return
		installed = self.installer.getInstalledPackageKeys(self.catalog)
		self.installedKeys = set(installed)
		checkedKeys = installed
		self.packages = list(self.catalog.packages)
		self.isUpdatingPackageChecks = True
		self.packageList.Freeze()
		try:
			self.packageList.DeleteAllItems()
			for index, package in enumerate(self.packages):
				self.packageList.InsertItem(index, pairDisplayName(package))
				self.packageList.SetItem(
					index,
					1,
					_("installed") if package.key in installed else _("not installed"),
				)
				self.packageList.SetItem(index, 2, self.formatPackageSize(package))
				self.packageList.SetItem(index, 3, package.version)
				self.packageList.CheckItem(index, package.key in checkedKeys)
		finally:
			self.packageList.Thaw()
			self.isUpdatingPackageChecks = False
		self.selectFirstPackageListItem()
		self.setStatus(_("{count} installed package(s) detected.").format(count=len(installed)))
		self.updateSelectionSummary()

	def selectFirstPackageListItem(self) -> None:
		"""Select the first package row without changing its checked state."""
		if self.packageList.ItemCount == 0:
			return
		self.packageList.SetItemState(
			0,
			wx.LIST_STATE_FOCUSED | wx.LIST_STATE_SELECTED,
			wx.LIST_STATE_FOCUSED | wx.LIST_STATE_SELECTED,
		)
		self.packageList.EnsureVisible(0)

	def formatPackageSize(self, package: ModelPackage) -> str:
		"""Return archive size display text."""
		if package.archive is None or package.archive.size <= 0:
			return ""
		return _("{size:.1f} MiB").format(size=package.archive.size / 1024 / 1024)

	def getSelectedPackageKeys(self) -> set[str]:
		"""Return checked package keys."""
		return {
			self.packages[index].key
			for index in self.packageList.GetCheckedItems()
			if 0 <= index < len(self.packages)
		}

	def confirmPendingRemoval(self, selected: set[str]) -> bool:
		"""Confirm removal of installed models that were unchecked."""
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
			_(
				"The following installed model package(s) will be removed:\n\n{names}\n\nContinue?",
			).format(names=names),
			_("Polyglot ChromeAI Model Manager"),
			wx.YES_NO | wx.ICON_WARNING,
			self,
		)
		return answer == wx.YES

	def updateSelectionSummary(self) -> None:
		"""Update selection summary and apply button state."""
		if self.catalog is None or not self.packages:
			self.selectionLabel.SetLabel("")
			self.pendingOperationCount = 0
			self.refreshApplyButton()
			return
		selected = self.getSelectedPackageKeys()
		pending = self.calculatePendingOperations(selected)
		self.pendingOperationCount = pending.total
		self.selectionLabel.SetLabel(
			_("Selected: {selected} | Install: {install} | Remove: {remove} | Cleanup: {cleanup}").format(
				selected=len(selected),
				install=pending.installCount,
				remove=pending.removeCount,
				cleanup=pending.cleanupCount,
			),
		)
		self.refreshApplyButton()

	def calculatePendingOperations(self, selected: set[str]) -> PendingOperations:
		"""Calculate pending install, removal, and cleanup operations."""
		if self.catalog is None:
			return PendingOperations(0, 0, 0)
		installCount = sum(1 for key in selected if key not in self.installedKeys)
		removeCount = sum(1 for key in self.installedKeys if key not in selected)
		cleanupCount = 0
		if (
			not selected
			and self.installer.hasRuntimeFiles(self.catalog)
			and not self.installer.hasRegisteredPackagesOutsideCatalog(self.catalog)
		):
			cleanupCount += 1
		if self.installer.hasDownloadCacheFilesFast():
			cleanupCount += 1
		return PendingOperations(installCount, removeCount, cleanupCount)

	def setBusy(self, isBusy: bool) -> None:
		"""Enable or disable controls based on operation state."""
		if self.isDestroyed:
			return
		self.isBusy = isBusy
		for control in (
			self.advancedButton,
			self.catalogUrlBox,
			self.defaultCatalogButton,
			self.reloadButton,
			self.openTargetButton,
			self.clearCacheButton,
			self.openTempButton,
			self.packageList,
		):
			control.Enable(not isBusy)
		self.progressGauge.Show(isBusy)
		if isBusy:
			self.progressGauge.SetValue(0)
		self.refreshApplyButton()
		self.Layout()

	def refreshApplyButton(self) -> None:
		"""Refresh apply button label and enabled state."""
		self.applyButton.SetLabel(_("Apply changes ({count})").format(count=self.pendingOperationCount))
		self.applyButton.Enable(
			not self.isBusy and self.catalog is not None and self.pendingOperationCount > 0,
		)

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
		"""Update status, log, and progress gauge."""
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
		log.error("ChromeAI model manager operation failed (%s).", type(error).__name__)
		gui.messageBox(str(error), _("Polyglot ChromeAI Model Manager"), wx.OK | wx.ICON_ERROR, self)

	def saveCatalogUrl(self, catalogUrl: str) -> None:
		"""Persist the last successful catalog URL."""
		try:
			self.settings.catalogUrl = catalogUrl
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
			name=f"{self.__class__.__module__}.{target.__name__}",
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
