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

from ..common import configProfiles
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

	def refreshLabel(self, labelControl: wx.StaticText | None, spec: ConfigSpec) -> None:
		"""Update a label whose text depends on state the control itself does not hold."""
		if labelControl is not None:
			labelControl.SetLabel(spec["label"])

	def loadFromConfig(self, control: wx.Control, configSection: ConfigSection, spec: ConfigSpec) -> None:
		"""Load a configuration value into the control."""
		value = configSection.get(spec["id"], spec.get("default"))
		self.setValueToControl(control, value, spec)

	def saveToConfig(self, control: wx.Control, configSection: ConfigSection, spec: ConfigSpec) -> None:
		"""Save the control's value to the configuration dictionary."""
		configSection[spec["id"]] = self.getValueFromControl(control)


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


class LabeledControlHandler(ControlHandlerBase):
	"""Create controls whose labels are separate wx static-text controls."""

	def createControlPair(
		self,
		panel: wx.Window,
		spec: ConfigSpec,
	) -> tuple[wx.StaticText | None, wx.Control]:
		wxClass, kwargs = self.getWxClassAndKwargs(spec)
		label = wx.StaticText(panel, label=spec["label"])
		self.refreshLabel(label, spec)
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


class PasswordHandler(TextHandler):
	"""Adapt credential configuration items to wx text controls backed by the secret store.

	Credentials never reach NVDA's configuration file, so specifications handled here must carry the
	owning engine's ID in an ``engineId`` entry; see :func:`engineManager.getEngineConfigSpec`.

	The field shows and saves only the credential belonging to the configuration profile NVDA is
	writing to, matching how NVDA treats every other setting. When a named profile holds no
	credential of its own the field is left empty and its label names the profile the credential is
	inherited from, so clearing the field is what returns a profile to the inherited credential.
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

	def _getLabel(self, spec: ConfigSpec) -> str:
		"""Return the field label, saying where the credential in use comes from when that is not obvious."""
		engineId = self._getEngineId(spec)
		if not engineId:
			return str(spec["label"])
		if secretStore.isProvidedByEnvironment(engineId, spec["id"]):
			# Translators: Label for a credential field whose value comes from an environment
			# variable. {label} is the usual field label, {variable} is the variable name.
			return _("{label} (set by the {variable} environment variable)").format(
				label=spec["label"],
				variable=secretStore.getEnvironmentVariableName(engineId, spec["id"]),
			)
		editedProfile = configProfiles.getWritableProfileName()
		if editedProfile is None:
			# The normal configuration inherits from nothing, so its label needs no explanation.
			return str(spec["label"])
		if secretStore.getStoredSecret(engineId, spec["id"], editedProfile):
			# Translators: Label for a credential field holding a key used only by the configuration
			# profile being edited. {label} is the usual field label.
			return _("{label} (set in this profile)").format(label=spec["label"])
		inherited = secretStore.resolveSecret(engineId, spec["id"])
		if inherited.source is not secretStore.CredentialSource.PROFILE:
			return str(spec["label"])
		if inherited.profileName is None:
			# Translators: Label for an empty credential field in a configuration profile that uses
			# the key from NVDA's normal configuration. {label} is the usual field label.
			return _("{label} (inherited from the normal configuration)").format(label=spec["label"])
		# Translators: Label for an empty credential field in a configuration profile that uses the
		# key from another profile. {label} is the usual field label, {profile} is that profile.
		return _("{label} (inherited from the {profile} profile)").format(
			label=spec["label"],
			profile=inherited.profileName,
		)

	def refreshLabel(self, labelControl: wx.StaticText | None, spec: ConfigSpec) -> None:
		if labelControl is not None:
			labelControl.SetLabel(self._getLabel(spec))

	def loadFromConfig(self, control: wx.Control, configSection: ConfigSection, spec: ConfigSpec) -> None:
		assert isinstance(control, wx.TextCtrl)
		engineId = self._getEngineId(spec)
		if engineId and secretStore.isProvidedByEnvironment(engineId, spec["id"]):
			# The environment wins over anything the user could type here.
			control.SetValue("")
			control.Disable()
			return
		editedProfile = configProfiles.getWritableProfileName()
		stored = secretStore.getStoredSecret(engineId, spec["id"], editedProfile) if engineId else ""
		if not stored and editedProfile is not None:
			# An empty field in a named profile means the credential is inherited, so the built-in
			# default must not be shown here: it would be saved over what the profile inherits.
			self.setValueToControl(control, "", spec)
			return
		self.setValueToControl(control, stored or spec.get("default", ""), spec)

	def saveToConfig(self, control: wx.Control, configSection: ConfigSection, spec: ConfigSpec) -> None:
		assert isinstance(control, wx.TextCtrl)
		# configSection is deliberately untouched: credentials never reach NVDA's configuration file.
		engineId = self._getEngineId(spec)
		if not engineId or secretStore.isProvidedByEnvironment(engineId, spec["id"]):
			return
		editedProfile = configProfiles.getWritableProfileName()
		value = self.getValueFromControl(control).strip()
		isBuiltInDefault = value == str(spec.get("default", "")).strip()
		if not value or (editedProfile is None and isBuiltInDefault):
			# An empty field stores nothing, so a named profile goes back to inheriting; and in the
			# normal configuration the built-in default needs no stored copy of its own.
			_unused = secretStore.deleteSecret(engineId, spec["id"], editedProfile)
			return
		if not secretStore.setSecret(engineId, spec["id"], value, editedProfile):
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


_controlHandlers: dict[str, ControlHandlerBase] = {
	"checkbox": CheckboxHandler(),
	"text": TextHandler(),
	"password": PasswordHandler(),
	"choice": ChoiceHandler(),
	"spinctrl": SpinCtrlHandler(),
}
