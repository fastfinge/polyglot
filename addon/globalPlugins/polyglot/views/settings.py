# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# Copyright (C) 2025 WangFeng Huang <1398969445@qq.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

from collections import OrderedDict
from typing import Any

import addonHandler
import gui
import ui
import wx
from gui import guiHelper
from gui.settingsDialogs import SettingsPanel
from logHandler import log

from ..common.cache import TranslationCache
from ..common import config
from ..common import configProfiles
from ..common import secretStore
from ..services import engineManager
from . import factory as uiFactory

addonHandler.initTranslation()


class TranslationSettingsPanel(SettingsPanel):
	"""Present global and per-engine Polyglot settings in NVDA's settings dialog."""

	title = _("Polyglot")

	# Annotate instance variables with their known types
	engines: "OrderedDict[str, Any]"  # Forward reference because TranslationEngine is not imported
	cache: TranslationCache
	uiModel: dict[str, Any]
	dynamicControls: dict[str, dict[str, Any]]
	enginePanelContainer: wx.Panel
	enginePanelsCache: dict[str, wx.Panel]
	# Allow these instance variables to be None, matching their initial assignment.
	activeEnginePanel: wx.Panel | None
	_engineSwitchTimer: wx.CallLater | None

	def __init__(self, parent):
		"""Initialize engine state and lazily created settings panels."""
		self.engines = OrderedDict((e.id, e) for e in engineManager.getAllEngines())
		# TranslationCache is a singleton, so getting an instance here is safe
		# and will access the same cache used by the manager.
		self.cache = TranslationCache()
		self.uiModel = {}

		self.dynamicControls = {}
		self.enginePanelsCache = {}
		self.activeEnginePanel = None

		# --- DEBOUNCING STRATEGY: Timer for smooth engine switching ---
		self._engineSwitchTimer = None

		super().__init__(parent)
		self.Bind(wx.EVT_WINDOW_DESTROY, self._onDestroy)

	def makeSettings(self, sizer):
		"""Create common settings and the per-engine panel container."""
		sHelper = guiHelper.BoxSizerHelper(self, sizer=sizer)

		self.engineChoice = sHelper.addLabeledControl(_("Translation &engine:"), wx.Choice)
		_unused = sHelper.addItem(wx.StaticLine(self, style=wx.LI_HORIZONTAL))

		self.enginePanelContainer = wx.Panel(self)
		self.enginePanelContainerSizer = wx.BoxSizer(wx.VERTICAL)
		self.enginePanelContainer.SetSizer(self.enginePanelContainerSizer)
		_unused = sHelper.addItem(self.enginePanelContainer, proportion=1, flag=wx.EXPAND)

		_unused = sHelper.addItem(wx.StaticLine(self, style=wx.LI_HORIZONTAL))

		commonBox = wx.StaticBox(self, label=_("Common Settings"))
		commonSizer = wx.StaticBoxSizer(commonBox, wx.VERTICAL)
		commonSHelper = guiHelper.BoxSizerHelper(self, sizer=commonSizer)

		self.copyResultCheckbox = commonSHelper.addItem(
			wx.CheckBox(self, label=_("Copy manual translation results to clipboard")),
		)
		self.enableLocalDictionaryForTranslationCheckbox = commonSHelper.addItem(
			wx.CheckBox(
				self,
				# Translators: Checkbox controlling local dictionary lookup for manual translation commands.
				label=_(
					"Prefer local English-Chinese dictionary for selected text, clipboard, and last spoken text",
				),
			),
		)
		self.enableLocalDictionaryForTextReviewCheckbox = commonSHelper.addItem(
			wx.CheckBox(
				self,
				# Translators: Checkbox controlling local dictionary definitions in NVDA text review.
				label=_("Use the local English-Chinese dictionary in text review"),
			),
		)
		self.enableSmartFilterCheckbox = commonSHelper.addItem(
			wx.CheckBox(
				self,
				label=_(
					"Enable smart speech filter (skips roles, states, location, and formatting information)",
				),
			),
		)
		self.clearCacheButton = commonSHelper.addItem(wx.Button(self, label=_("Clear Cache")))
		self.clearCredentialsButton = commonSHelper.addItem(
			# Translators: Button that deletes every API key Polyglot has stored in the Windows Credential Locker.
			wx.Button(self, label=_("Clear Stored API Keys")),
		)
		_unused = sHelper.addItem(commonSizer, flag=wx.EXPAND)

		self.engineChoice.Bind(wx.EVT_CHOICE, self.onEngineChanged)
		self.copyResultCheckbox.Bind(wx.EVT_CHECKBOX, self.onAnyControlChanged)
		self.enableLocalDictionaryForTranslationCheckbox.Bind(wx.EVT_CHECKBOX, self.onAnyControlChanged)
		self.enableLocalDictionaryForTextReviewCheckbox.Bind(wx.EVT_CHECKBOX, self.onAnyControlChanged)
		self.enableSmartFilterCheckbox.Bind(wx.EVT_CHECKBOX, self.onAnyControlChanged)
		self.clearCacheButton.Bind(wx.EVT_BUTTON, self.onClearCache)
		self.clearCredentialsButton.Bind(wx.EVT_BUTTON, self.onClearCredentials)

		self._populateInitialState()

	def _onDestroy(self, event: wx.Event) -> None:
		"""Ensure the timer is stopped when the panel is destroyed."""
		if self._engineSwitchTimer and self._engineSwitchTimer.IsRunning():
			self._engineSwitchTimer.Stop()
		event.Skip()

	def onSave(self):
		"""Persist the current common and per-engine settings."""
		conf = config.getConfig()
		self._syncModelFromUi()

		conf["engine"] = self.uiModel["engine"]
		conf["copyResult"] = self.uiModel["copyResult"]
		conf["enableLocalDictionaryForTranslation"] = self.uiModel["enableLocalDictionaryForTranslation"]
		conf["enableLocalDictionaryForTextReview"] = self.uiModel["enableLocalDictionaryForTextReview"]
		conf["enableSmartFilter"] = self.uiModel["enableSmartFilter"]

		for engineId, controls in self.dynamicControls.items():
			if not controls:
				continue
			if engineId not in conf["engines"]:
				conf["engines"][engineId] = {}
			engineConf = conf["engines"][engineId]
			for _unused, info in controls.items():
				info["handler"].saveToConfig(info["control"], engineConf, info["spec"])

	def postSave(self) -> None:
		"""Apply local dictionary hook changes after every settings panel saves successfully."""
		config.post_localDictionarySettingsChanged.notify()

	def onEngineChanged(self, event: wx.Event) -> None:
		"""Debounce the engine switch event to avoid stutter on rapid changes."""
		# If a switch is already scheduled, cancel it.
		if self._engineSwitchTimer and self._engineSwitchTimer.IsRunning():
			self._engineSwitchTimer.Stop()

		# Schedule the actual switch to happen after a short delay (200ms).
		self._engineSwitchTimer = wx.CallLater(200, self._performEngineSwitch)

	def _performEngineSwitch(self):
		"""Switch the active engine panel when the debounce timer fires."""
		self.Freeze()
		try:
			self._switchEnginePanel()
		finally:
			self._sendLayoutUpdatedEvent()
			self.Thaw()

	def onAnyControlChanged(self, event: wx.Event | None = None):
		"""Synchronize the UI model and apply engine-defined dynamic states."""
		if event:
			event.Skip()

		self._syncModelFromUi()

		engine = self._getSelectedEngine()
		if not engine:
			return
		try:
			uiStates = engine.getUiStates(self.uiModel)
			self._applyUiStates(uiStates)
		except Exception:
			log.error(f"Error executing getUiStates for engine '{engine.id}'.", exc_info=True)

	def _populateInitialState(self):
		"""Populate settings controls and create the initial engine settings panel."""
		self.Freeze()
		try:
			conf = config.getConfig()
			for engineId, engine in self.engines.items():
				self.engineChoice.Append(engine.name, engineId)
			engineId = conf.get("engine", list(self.engines.keys())[0] if self.engines else None)
			if engineId and engineId in self.engines:
				self.engineChoice.SetStringSelection(self.engines[engineId].name)

			self.copyResultCheckbox.SetValue(conf.get("copyResult", True))
			self.enableLocalDictionaryForTranslationCheckbox.SetValue(
				conf.get("enableLocalDictionaryForTranslation", True),
			)
			self.enableLocalDictionaryForTextReviewCheckbox.SetValue(
				conf.get("enableLocalDictionaryForTextReview", True),
			)
			self.enableSmartFilterCheckbox.SetValue(conf.get("enableSmartFilter", True))

			self._switchEnginePanel()
		finally:
			self.Thaw()

	def _switchEnginePanel(self):
		"""Show the panel for the selected engine, creating it if necessary."""
		engineId = self._getSelectedEngineId()
		if not engineId:
			return

		if self.activeEnginePanel:
			self.activeEnginePanel.Hide()

		if engineId in self.enginePanelsCache:
			panel = self.enginePanelsCache[engineId]
			panel.Show()
			self.activeEnginePanel = panel
		else:
			panel = self._createEnginePanel(engineId)
			self.enginePanelsCache[engineId] = panel
			self.enginePanelContainerSizer.Add(panel, 1, wx.EXPAND)
			self.activeEnginePanel = panel

		self.onAnyControlChanged()
		self.enginePanelContainer.Layout()
		self.Layout()

	def _createEnginePanel(self, engineId: str) -> wx.Panel:
		"""Create and populate the settings panel for a specific engine ONCE."""
		panel = wx.Panel(self.enginePanelContainer)
		engine = self.engines.get(engineId)
		if not engine:
			return panel

		engineConf = config.getConfig()["engines"].get(engine.id, {})
		configSpecList = engineManager.getEngineConfigSpec(engine)

		self.dynamicControls[engineId] = {}

		box = wx.StaticBox(panel, label=_("Current Engine Settings"))
		containerSizer = wx.StaticBoxSizer(box, wx.VERTICAL)

		if not configSpecList:
			noSettingsText = wx.StaticText(
				panel,
				label=_("This engine requires no additional configuration."),
			)
			containerSizer.Add(noSettingsText, 0, wx.ALL, 5)
			panel.SetSizer(containerSizer)
			return panel

		editedProfile = configProfiles.getWritableProfileName()
		if editedProfile is not None and any(
			uiFactory.getControlHandler(spec["type"]).isSecret for spec in configSpecList
		):
			profileHint = wx.StaticText(
				panel,
				# Translators: Explains how API keys behave while a configuration profile other than
				# NVDA's normal configuration is being edited.
				label=_(
					"API keys here apply only to this configuration profile. Clear a key to inherit it again.",
				),
			)
			containerSizer.Add(profileHint, 0, wx.ALL, 5)

		gridSizer = wx.FlexGridSizer(cols=2, vgap=5, hgap=5)
		gridSizer.AddGrowableCol(1)

		for spec in configSpecList:
			handler = uiFactory.getControlHandler(spec["type"])
			labelControl, control = handler.createControlPair(panel, spec)

			handler.loadFromConfig(control, engineConf, spec)
			handler.bindEvent(control, self.onAnyControlChanged)

			if labelControl is None:
				gridSizer.Add(control, 1, wx.EXPAND)
				gridSizer.AddSpacer(0)
			else:
				gridSizer.Add(labelControl, 0, wx.ALIGN_CENTER_VERTICAL)
				gridSizer.Add(control, 1, wx.EXPAND)

			self.dynamicControls[engineId][spec["id"]] = {
				"control": control,
				"handler": handler,
				"spec": spec,
				"labelControl": labelControl,
			}

		containerSizer.Add(gridSizer, 1, wx.EXPAND | wx.ALL, 5)
		panel.SetSizer(containerSizer)
		return panel

	def _applyUiStates(self, uiStates: dict[str, dict[str, Any]]):
		engineId = self._getSelectedEngineId()
		if not engineId or engineId not in self.dynamicControls:
			return

		for cid, states in uiStates.items():
			info = self.dynamicControls[engineId].get(cid)
			if not info:
				continue
			handler = info["handler"]
			for prop, value in states.items():
				handler.updateControlState(info["control"], info["labelControl"], prop, value)

		self.Layout()

	def _syncModelFromUi(self):
		engineId = self._getSelectedEngineId()
		if not engineId:
			return

		self.uiModel = {
			"engine": engineId,
			"copyResult": self.copyResultCheckbox.IsChecked(),
			"enableLocalDictionaryForTranslation": self.enableLocalDictionaryForTranslationCheckbox.IsChecked(),
			"enableLocalDictionaryForTextReview": self.enableLocalDictionaryForTextReviewCheckbox.IsChecked(),
			"enableSmartFilter": self.enableSmartFilterCheckbox.IsChecked(),
		}

		if engineId in self.dynamicControls:
			for cid, info in self.dynamicControls[engineId].items():
				self.uiModel[cid] = info["handler"].getValueFromControl(info["control"])

	def onPanelActivated(self):
		"""Refresh cache and stored credential information when the panel becomes active."""
		super().onPanelActivated()
		self._updateCacheButton()
		self._updateCredentialsButton()

	def _getSelectedEngineId(self) -> str | None:
		selection = self.engineChoice.GetSelection()
		if selection == wx.NOT_FOUND:
			return None
		return self.engineChoice.GetClientData(selection)

	def _getSelectedEngine(self) -> Any | None:
		engineId = self._getSelectedEngineId()
		if not engineId:
			return None
		return self.engines.get(engineId)

	def onClearCache(self, event: wx.Event):
		"""Clear cached translations and refresh the cache button."""
		self.cache.clear()
		self._updateCacheButton()
		wx.CallAfter(self.clearCacheButton.SetFocus)

	def _updateCacheButton(self):
		self.clearCacheButton.SetLabel(_("Clear Cache (Items: {})").format(self.cache.getItemCount()))

	def onClearCredentials(self, event: wx.Event):
		"""Delete every API key Polyglot has stored, after confirming with the user."""
		storedCount = len(secretStore.getStoredTargetNames())
		if not storedCount:
			# Translators: Message reported when there is no stored API key to delete.
			ui.message(_("Polyglot has no stored API keys."))
			return
		if (
			gui.messageBox(
				# Translators: Confirmation prompt shown before deleting stored API keys. {count} is how many are stored.
				_(
					"Delete the {count} API key(s) Polyglot has stored for this Windows account, in every configuration profile? You will have to enter them again to use the engines that need them.",
				).format(count=storedCount),
				# Translators: Title of the dialog confirming deletion of stored API keys.
				_("Clear Stored API Keys"),
				wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
				self,
			)
			!= wx.YES
		):
			return
		removedCount = secretStore.deleteAllSecrets()
		self._reloadCredentialControls()
		self._updateCredentialsButton()
		# Translators: Message reported after stored API keys are deleted. {count} is how many were deleted.
		ui.message(_("Deleted {count} stored API key(s).").format(count=removedCount))
		wx.CallAfter(self.clearCredentialsButton.SetFocus)

	def _reloadCredentialControls(self):
		"""Refresh every credential field and its label from the secret store."""
		enginesConf = config.getConfig()["engines"]
		for engineId, controls in self.dynamicControls.items():
			engineConf = enginesConf.get(engineId, {})
			for info in controls.values():
				handler = info["handler"]
				if not handler.isSecret:
					continue
				handler.loadFromConfig(info["control"], engineConf, info["spec"])
				# Whether a credential is inherited can have changed, and the label says so.
				handler.refreshLabel(info["labelControl"], info["spec"])
		self.Layout()

	def _updateCredentialsButton(self):
		self.clearCredentialsButton.SetLabel(
			# Translators: Label of the button that deletes stored API keys. {} is how many are stored.
			_("Clear Stored API Keys (Items: {})").format(len(secretStore.getStoredTargetNames())),
		)
