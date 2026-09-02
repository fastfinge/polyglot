# -*- coding: utf-8 -*-

# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

from collections import OrderedDict
from collections.abc import Callable
from typing import Any

import addonHandler
import wx
from configobj.validate import is_boolean
from logHandler import log

from ..common import secretStore

addonHandler.initTranslation()

# Create a Type Alias for complex, reused types.
ConfigSpec = dict[str, Any]
ConfigSection = dict[str, Any]


class ControlHandlerBase:
	"""Define the configuration and wx-control conversion contract."""

	@property
	def isSecret(self) -> bool:
		"""Return whether values of this type are credentials kept out of NVDA's configuration file."""
		return False

	@property
	def configType(self) -> str:
		"""Return the ConfigObj validator type handled by this adapter."""
		raise NotImplementedError

	def formatConfigDefault(self, value: Any) -> str:
		"""Format a Python value for use in a ConfigObj specification."""
		raise NotImplementedError

	def createControlPair(
		self,
		panel: wx.Window,
		spec: ConfigSpec,
	) -> tuple[wx.StaticText | None, wx.Control]:
		"""Create the optional label and control described by spec."""
		raise NotImplementedError

	def getValueFromControl(self, control: wx.Control) -> Any:
		"""Return the configuration value represented by control."""
		raise NotImplementedError

	def setValueToControl(self, control: wx.Control, value: Any, spec: ConfigSpec):
		"""Apply a configuration value to control."""
		raise NotImplementedError

	def bindEvent(self, control: wx.Control, callback: Callable[[wx.Event], None]):
		"""Bind control's value-change event to callback."""
		raise NotImplementedError

	def updateControlState(
		self,
		control: wx.Control,
		labelControl: wx.StaticText | None,
		prop: str,
		value: Any,
	):
		"""Apply a dynamic enabled or visible state to a control pair."""
		if prop == "enabled":
			if control.IsEnabled() != value:
				control.Enable(bool(value))
				if labelControl:
					labelControl.Enable(bool(value))
		elif prop == "visible":
			isShown = control.IsShown()
			if isShown != value:
				control.Show(bool(value))
				if labelControl:
					labelControl.Show(bool(value))

	def loadFromConfig(self, control: wx.Control, configSection: ConfigSection, spec: ConfigSpec):
		"""Load a configuration value into the control."""
		raise NotImplementedError

	def saveToConfig(self, control: wx.Control, configSection: ConfigSection, spec: ConfigSpec):
		"""Save the control's value to the configuration dictionary."""
		raise NotImplementedError


def getControlHandler(typeName: str) -> ControlHandlerBase:
	"""Return the control handler registered for a configuration type."""
	if typeName not in _controlHandlers:
		raise ValueError(f"Unknown control type: '{typeName}'")
	return _controlHandlers[typeName]


class CheckboxHandler(ControlHandlerBase):
	"""Adapt boolean configuration items to wx checkboxes."""

	@property
	def configType(self) -> str:
		return "boolean"

	def formatConfigDefault(self, value: Any) -> str:
		return str(bool(value)).capitalize()

	def createControlPair(
		self,
		panel: wx.Window,
		spec: ConfigSpec,
	) -> tuple[wx.StaticText | None, wx.Control]:
		control = wx.CheckBox(panel, label=spec["label"])
		return (None, control)

	def getValueFromControl(self, control: wx.Control) -> bool:
		assert isinstance(control, wx.CheckBox)
		return control.IsChecked()

	def setValueToControl(self, control: wx.Control, value: Any, spec: ConfigSpec) -> None:
		assert isinstance(control, wx.CheckBox)
		control.SetValue(is_boolean(value) if value is not None else False)

	def bindEvent(self, control: wx.Control, callback: Callable[[wx.Event], None]) -> None:
		assert isinstance(control, wx.CheckBox)
		control.Bind(wx.EVT_CHECKBOX, callback)

	def loadFromConfig(self, control: wx.Control, configSection: ConfigSection, spec: ConfigSpec) -> None:
		assert isinstance(control, wx.CheckBox)
		value = configSection.get(spec["id"], spec.get("default"))
		self.setValueToControl(control, value, spec)

	def saveToConfig(self, control: wx.Control, configSection: ConfigSection, spec: ConfigSpec) -> None:
		assert isinstance(control, wx.CheckBox)
		configSection[spec["id"]] = self.getValueFromControl(control)


class LabeledControlHandler(ControlHandlerBase):
	"""Create controls whose labels are separate wx static-text controls."""

	def createControlPair(
		self,
		panel: wx.Window,
		spec: ConfigSpec,
	) -> tuple[wx.StaticText | None, wx.Control]:
		wxClass, kwargs = self.getWxClassAndKwargs(spec)
		label = wx.StaticText(panel, label=spec["label"])
		control = wxClass(panel, **kwargs)
		return (label, control)

	def getWxClassAndKwargs(self, spec: ConfigSpec) -> tuple[type[wx.Control], dict[str, Any]]:
		"""Return the wx control class and constructor arguments for spec."""
		raise NotImplementedError


class TextHandler(LabeledControlHandler):
	"""Adapt string and password configuration items to wx text controls."""

	@property
	def configType(self) -> str:
		return "string"

	def formatConfigDefault(self, value: Any) -> str:
		return f'"{str(value)}"'

	def getWxClassAndKwargs(self, spec: ConfigSpec) -> tuple[type[wx.Control], dict[str, Any]]:
		kwargs = {"style": wx.TE_PASSWORD} if spec.get("type") == "password" else {}
		return wx.TextCtrl, kwargs

	def getValueFromControl(self, control: wx.Control) -> str:
		assert isinstance(control, wx.TextCtrl)
		return control.GetValue()

	def setValueToControl(self, control: wx.Control, value: Any, spec: ConfigSpec) -> None:
		assert isinstance(control, wx.TextCtrl)
		control.SetValue(str(value) if value is not None else "")

	def bindEvent(self, control: wx.Control, callback: Callable[[wx.Event], None]) -> None:
		assert isinstance(control, wx.TextCtrl)
		control.Bind(wx.EVT_TEXT, callback)

	def loadFromConfig(self, control: wx.Control, configSection: ConfigSection, spec: ConfigSpec) -> None:
		assert isinstance(control, wx.TextCtrl)
		value = configSection.get(spec["id"], spec.get("default"))
		self.setValueToControl(control, value, spec)

	def saveToConfig(self, control: wx.Control, configSection: ConfigSection, spec: ConfigSpec) -> None:
		assert isinstance(control, wx.TextCtrl)
		configSection[spec["id"]] = self.getValueFromControl(control)


class PasswordHandler(TextHandler):
	"""Adapt credential configuration items to wx text controls backed by the secret store.

	Credentials never reach NVDA's configuration file, so specifications handled here must carry the
	owning engine's ID in an ``engineId`` entry; see :func:`engineManager.getEngineConfigSpec`.
	"""

	@property
	def isSecret(self) -> bool:
		return True

	def _getEngineId(self, spec: ConfigSpec) -> str:
		"""Return the engine owning a credential, or an empty string when it is unknown."""
		engineId = str(spec.get("engineId", ""))
		if not engineId:
			log.error(
				f"""Credential setting '{spec.get("id")}' is not bound to an engine, so it cannot be stored securely.""",
			)
		return engineId

	def createControlPair(
		self,
		panel: wx.Window,
		spec: ConfigSpec,
	) -> tuple[wx.StaticText | None, wx.Control]:
		label, control = super().createControlPair(panel, spec)
		engineId = self._getEngineId(spec)
		if label is not None and engineId and secretStore.isProvidedByEnvironment(engineId, spec["id"]):
			label.SetLabel(
				# Translators: Label for a credential field whose value comes from an environment
				# variable. {label} is the usual field label, {variable} is the variable name.
				_("{label} (set by the {variable} environment variable)").format(
					label=spec["label"],
					variable=secretStore.getEnvironmentVariableName(engineId, spec["id"]),
				),
			)
		return (label, control)

	def loadFromConfig(self, control: wx.Control, configSection: ConfigSection, spec: ConfigSpec) -> None:
		assert isinstance(control, wx.TextCtrl)
		engineId = self._getEngineId(spec)
		if engineId and secretStore.isProvidedByEnvironment(engineId, spec["id"]):
			# The environment wins over anything the user could type here.
			control.SetValue("")
			control.Disable()
			return
		stored = secretStore.getSecret(engineId, spec["id"]) if engineId else ""
		self.setValueToControl(control, stored or spec.get("default", ""), spec)

	def saveToConfig(self, control: wx.Control, configSection: ConfigSection, spec: ConfigSpec) -> None:
		assert isinstance(control, wx.TextCtrl)
		# configSection is deliberately untouched: credentials never reach NVDA's configuration file.
		engineId = self._getEngineId(spec)
		if not engineId or secretStore.isProvidedByEnvironment(engineId, spec["id"]):
			return
		value = self.getValueFromControl(control)
		if value.strip() == str(spec.get("default", "")).strip():
			# The built-in default needs no stored copy.
			_unused = secretStore.deleteSecret(engineId, spec["id"])
			return
		if not secretStore.setSecret(engineId, spec["id"], value):
			log.error(f"Could not save the '{engineId}' credential '{spec['id']}' to secure storage.")


class ChoiceHandler(LabeledControlHandler):
	"""Adapt enumerated string configuration items to wx choices."""

	@property
	def configType(self) -> str:
		return "string"

	def formatConfigDefault(self, value: Any) -> str:
		return f'"{str(value)}"'

	def getWxClassAndKwargs(self, spec: ConfigSpec) -> tuple[type[wx.Control], dict[str, Any]]:
		return wx.Choice, {}

	def getValueFromControl(self, control: wx.Control) -> Any:
		assert isinstance(control, wx.Choice)
		selection = control.GetSelection()
		return control.GetClientData(selection) if selection != wx.NOT_FOUND else None

	def setValueToControl(self, control: wx.Control, value: Any, spec: ConfigSpec) -> None:
		assert isinstance(control, wx.Choice)
		self.populateChoices(control, spec.get("choices", {}), value)

	def updateControlState(
		self,
		control: wx.Control,
		labelControl: wx.StaticText | None,
		prop: str,
		value: Any,
	) -> None:
		assert isinstance(control, wx.Choice)
		if prop == "choices":
			currentSelection = self.getValueFromControl(control)
			self.populateChoices(control, value, currentSelection)
		else:
			super().updateControlState(control, labelControl, prop, value)

	def populateChoices(
		self,
		choiceCtrl: wx.Choice,
		choicesDict: dict[str, str],
		currentValueCode: Any = None,
	) -> None:
		"""Update choice items while retaining a valid current selection."""
		currentChoices = OrderedDict()
		for i in range(choiceCtrl.GetCount()):
			currentChoices[choiceCtrl.GetClientData(i)] = choiceCtrl.GetString(i)

		if choicesDict == currentChoices:
			return

		choiceCtrl.Freeze()
		try:
			if not choicesDict:
				choiceCtrl.Clear()
				choiceCtrl.Disable()
				return
			choiceCtrl.Enable()
			codes, names = list(choicesDict.keys()), list(choicesDict.values())
			choiceCtrl.Clear()
			for i, name in enumerate(names):
				choiceCtrl.Append(name, codes[i])
			finalCode = currentValueCode if currentValueCode in codes else (codes[0] if codes else None)
			if finalCode:
				try:
					index = codes.index(finalCode)
					if choiceCtrl.GetSelection() != index:
						choiceCtrl.SetSelection(index)
				except (ValueError, KeyError):
					if choiceCtrl.GetCount() > 0:
						choiceCtrl.SetSelection(0)
			elif choiceCtrl.GetCount() > 0:
				choiceCtrl.SetSelection(0)
		finally:
			choiceCtrl.Thaw()

	def bindEvent(self, control: wx.Control, callback: Callable[[wx.Event], None]) -> None:
		assert isinstance(control, wx.Choice)
		control.Bind(wx.EVT_CHOICE, callback)

	def loadFromConfig(self, control: wx.Control, configSection: ConfigSection, spec: ConfigSpec) -> None:
		assert isinstance(control, wx.Choice)
		value = configSection.get(spec["id"], spec.get("default"))
		self.setValueToControl(control, value, spec)

	def saveToConfig(self, control: wx.Control, configSection: ConfigSection, spec: ConfigSpec) -> None:
		assert isinstance(control, wx.Choice)
		configSection[spec["id"]] = self.getValueFromControl(control)


class SpinCtrlHandler(LabeledControlHandler):
	"""Adapt bounded integer configuration items to wx spin controls."""

	@property
	def configType(self) -> str:
		return "integer"

	def formatConfigDefault(self, value: Any) -> str:
		return str(int(value))

	def getWxClassAndKwargs(self, spec: ConfigSpec) -> tuple[type[wx.Control], dict[str, Any]]:
		kwargs = {
			"value": str(spec.get("default", 15)),
			"min": spec.get("min", 1),
			"max": spec.get("max", 60),
		}
		# wx.SpinCtrl accepts min, max, and initial as constructor arguments.
		return wx.SpinCtrl, {"min": kwargs["min"], "max": kwargs["max"], "initial": int(kwargs["value"])}

	def getValueFromControl(self, control: wx.Control) -> int:
		assert isinstance(control, wx.SpinCtrl)
		return control.GetValue()

	def setValueToControl(self, control: wx.Control, value: Any, spec: ConfigSpec) -> None:
		assert isinstance(control, wx.SpinCtrl)
		try:
			control.SetValue(int(value))
		except (ValueError, TypeError):
			control.SetValue(spec.get("default", control.GetMin()))

	def bindEvent(self, control: wx.Control, callback: Callable[[wx.Event], None]) -> None:
		assert isinstance(control, wx.SpinCtrl)
		# The EVT_SPINCTRL event triggers when the value changes.
		control.Bind(wx.EVT_SPINCTRL, callback)
		# Also bind the text event to respond to direct input.
		control.Bind(wx.EVT_TEXT, callback)

	def loadFromConfig(self, control: wx.Control, configSection: ConfigSection, spec: ConfigSpec) -> None:
		assert isinstance(control, wx.SpinCtrl)
		value = configSection.get(spec["id"], spec.get("default"))
		self.setValueToControl(control, value, spec)

	def saveToConfig(self, control: wx.Control, configSection: ConfigSection, spec: ConfigSpec) -> None:
		assert isinstance(control, wx.SpinCtrl)
		configSection[spec["id"]] = self.getValueFromControl(control)


_controlHandlers: dict[str, ControlHandlerBase] = {
	"checkbox": CheckboxHandler(),
	"text": TextHandler(),
	"password": PasswordHandler(),
	"choice": ChoiceHandler(),
	"spinctrl": SpinCtrlHandler(),
}
