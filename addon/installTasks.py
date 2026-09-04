# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Clean-up NVDA runs when Polyglot is uninstalled.

Polyglot keeps its settings in NVDA's configuration file, its API keys, tokens, and passwords in the
Windows Credential Locker, and its translation cache in NVDA's configuration directory. None of them
lives inside the add-on's own folder, so deleting the add-on would leave all three behind: settings
in every configuration profile that holds them, credentials still listed in Windows' Credential
Manager under a program that is no longer installed, and a file recording every string the add-on
ever translated. This module removes them.

NVDA replaces an add-on by removing the installed version and putting the new one in its place, so it
runs the uninstall task for an update as well. An update has to keep the user's settings and keys, so
it is told apart from a real uninstall by the folder the waiting version sits in.
"""

import importlib
import os
import sys
from collections.abc import Iterator
from types import ModuleType
from typing import Any

import config as nvdaConfig
import globalVars
from logHandler import log

#: The add-on's name, which is also the folder NVDA installs it into. See ``buildVars.addon_info``.
ADDON_NAME = "polyglot"

#: Suffix NVDA gives the folder holding a version that is waiting to replace the installed one.
_PENDING_INSTALL_SUFFIX = ".pendingInstall"

#: Name this module imports the add-on's own package under, kept distinct from the name NVDA uses for
#: the running add-on so borrowing code here cannot disturb a copy NVDA has already loaded.
_PACKAGE_NAME = "polyglotUninstall"


def _isBeingUpdated() -> bool:
	"""Return whether NVDA is replacing this add-on rather than removing it for good."""
	try:
		from NVDAState import WritePaths

		addonsDir: str = WritePaths.addonsDir
	except ImportError:  # NVDA older than 2023.2
		addonsDir = os.path.join(globalVars.appArgs.configPath, "addons")
	return os.path.isdir(os.path.join(addonsDir, ADDON_NAME + _PENDING_INSTALL_SUFFIX))


def _importAddonModule(moduleName: str) -> ModuleType | None:
	"""Import one module from the add-on's own code, so removal follows the add-on's own rules.

	The add-on's package cannot simply be imported: ``globalPlugins/polyglot/__init__.py`` builds the
	whole add-on and needs NVDA's user interface, which is not up yet when an uninstall runs. A
	package object pointing at the same folder is made instead, which makes the individual modules
	importable on their own.

	:return: The module, or None when it could not be read.
	"""
	package: ModuleType | None = sys.modules.get(_PACKAGE_NAME)
	if package is None:
		package = ModuleType(_PACKAGE_NAME)
		packageDir = os.path.join(
			os.path.dirname(os.path.abspath(__file__)),
			"globalPlugins",
			ADDON_NAME,
		)
		setattr(package, "__path__", [packageDir])
		sys.modules[_PACKAGE_NAME] = package
	try:
		return importlib.import_module(f"{_PACKAGE_NAME}.{moduleName}")
	except ImportError:
		log.exception(f"Could not read Polyglot's '{moduleName}' module while uninstalling it.")
		return None


def _forgetAddonModules() -> None:
	"""Drop the modules borrowed above, so nothing of the removed add-on stays loaded."""
	borrowed = [name for name in sys.modules if name == _PACKAGE_NAME or name.startswith(f"{_PACKAGE_NAME}.")]
	for name in borrowed:
		del sys.modules[name]


def _deleteConfiguration() -> None:
	"""Remove Polyglot's settings from NVDA's configuration file.

	Every saved configuration profile is cleared, not only the profiles that happen to be active, so
	that no profile keeps settings for an add-on that is no longer installed.
	"""
	addonConfig = _importAddonModule("common.config")
	configProfiles = _importAddonModule("common.configProfiles")
	if addonConfig is None or configProfiles is None:
		return
	sectionName: str = addonConfig.getConfigSectionName()
	profiles: Iterator[tuple[str | None, Any]] = configProfiles.iterAllProfiles()
	clearedCount = 0
	for profileName, profile in profiles:
		if profile.pop(sectionName, None) is None:
			continue
		configProfiles.markProfileDirty(profileName)
		clearedCount += 1
	if not clearedCount:
		return
	try:
		nvdaConfig.conf.save()
	except Exception:
		log.exception("Could not save the NVDA configuration after removing Polyglot's settings.")
		return
	log.info(f"Removed Polyglot's settings from {clearedCount} configuration profile(s).")


def _deleteCredentials() -> None:
	"""Remove every credential Polyglot stored in the Windows Credential Locker.

	Credentials belong to a configuration profile, and profiles that are not active are just as much
	the user's as the active ones, so every profile's credentials go rather than only the ones the
	add-on can see right now.
	"""
	secretStore = _importAddonModule("common.secretStore")
	if secretStore is None:
		return
	removedCount: int = secretStore.deleteAllSecrets()
	if removedCount:
		log.info(f"Removed {removedCount} Polyglot credential(s) from the Windows Credential Locker.")


def _deleteTranslationCache() -> None:
	"""Remove the translation cache from NVDA's configuration directory.

	The cache records every string Polyglot has translated, which under auto-translation is much of
	what NVDA has spoken. That is the user's own content rather than the add-on's working data, and
	nothing else would ever clean it up, so it goes when the add-on does.
	"""
	cache = _importAddonModule("common.cache")
	if cache is None:
		return
	if cache.deleteCacheFile():
		log.info("Removed Polyglot's translation cache.")


def onUninstall() -> None:
	"""Remove everything Polyglot stores outside its own folder, unless it is only being updated.

	Each step is kept independent, so settings are still removed when the credentials or the cache
	cannot be, and the other way round.
	"""
	if _isBeingUpdated():
		log.debug(
			"Polyglot is being updated, so its settings, stored credentials, and translation cache are being kept.",
		)
		return
	try:
		try:
			_deleteConfiguration()
		except Exception:
			log.exception("Could not remove Polyglot's settings from the NVDA configuration.")
		try:
			_deleteCredentials()
		except Exception:
			log.exception("Could not remove Polyglot's credentials from the Windows Credential Locker.")
		try:
			_deleteTranslationCache()
		except Exception:
			log.exception("Could not remove Polyglot's translation cache.")
	finally:
		_forgetAddonModules()
