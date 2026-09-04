# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""NVDA's configuration profile rules, applied to the settings Polyglot keeps outside ``nvda.ini``.

NVDA resolves a setting by walking the active configuration profiles from the most recently activated
one down to the normal configuration and taking the first profile that defines it, and it writes a
changed setting to the most recently activated profile. Credentials are kept in the Windows Credential
Locker rather than in ``nvda.ini``, so :mod:`.secretStore` has to reproduce those rules for itself.
This module is the only place that reads NVDA's profile state, so everything else can work with plain
profile names.

A profile name of ``None`` always means NVDA's normal configuration, matching what NVDA reports as
``config.conf.profiles[0].name``.
"""

from collections.abc import Callable, Iterator
from typing import Any

import config as nvdaConfig
import extensionPoints
from logHandler import log

#: Notified with ``oldName`` and ``newName`` after NVDA renames a configuration profile.
post_profileRenamed = extensionPoints.Action()

#: Notified with ``profileName`` after NVDA deletes a configuration profile.
post_profileDeleted = extensionPoints.Action()

#: The wrappers installed on NVDA's configuration manager, kept so they can be removed again.
_installedHooks: dict[str, Callable[..., Any]] = {}


def getWritableProfileName() -> str | None:
	"""Return the profile NVDA would write a changed setting to.

	This is the profile the settings dialog is editing, which NVDA also names in that dialog's title.

	:return: The profile name, or None when NVDA would write to the normal configuration.
	"""
	try:
		profiles: list[Any] = list(nvdaConfig.conf.profiles)
	except AttributeError:
		log.error("NVDA reported no configuration profiles; assuming the normal configuration.")
		return None
	if not profiles:
		return None
	name: str | None = profiles[-1].name
	return name


def getActiveProfileNames() -> list[str | None]:
	"""Return the active profile names in NVDA's own search order.

	The most recently activated profile comes first and the normal configuration comes last, so that
	walking the list finds the value a setting inherits exactly as NVDA would.
	"""
	try:
		profiles: list[Any] = list(nvdaConfig.conf.profiles)
	except AttributeError:
		log.error("NVDA reported no configuration profiles; assuming the normal configuration.")
		return [None]
	names: list[str | None] = [profile.name for profile in reversed(profiles)]
	if None not in names:
		# The normal configuration is the last resort, whatever NVDA reported.
		names.append(None)
	return names


def getAllProfileNames() -> list[str | None]:
	"""Return the normal configuration followed by the name of every saved profile."""
	names: list[str | None] = [None]
	try:
		names.extend(sorted(nvdaConfig.conf.listProfiles()))
	except Exception:
		log.exception("Could not list the saved NVDA configuration profiles.")
	return names


def _loadProfile(profileName: str) -> Any | None:
	"""Return one saved profile, loading it from disk when NVDA has not already done so.

	NVDA offers this under more than one name and only some of them load a profile that is not in use
	yet, so each is tried until one produces the profile.
	"""
	for accessorName in ("_getProfile", "getProfile"):
		accessor: Callable[[str], Any] | None = getattr(nvdaConfig.conf, accessorName, None)
		if accessor is None:
			continue
		try:
			return accessor(profileName)
		except Exception:
			log.debugWarning(
				f"Could not read the '{profileName}' configuration profile through '{accessorName}'.",
				exc_info=True,
			)
	log.error(f"Could not read the '{profileName}' configuration profile.")
	return None


def iterAllProfiles() -> Iterator[tuple[str | None, Any]]:
	"""Yield every saved profile with its name, starting with the normal configuration."""
	try:
		normalConfiguration: Any = nvdaConfig.conf.profiles[0]
	except (AttributeError, IndexError):
		log.error("NVDA reported no normal configuration.")
		return
	yield (None, normalConfiguration)
	for profileName in getAllProfileNames():
		if profileName is None:
			continue
		profile = _loadProfile(profileName)
		if profile is not None:
			yield (profileName, profile)


def markProfileDirty(profileName: str | None) -> None:
	"""Tell NVDA that a profile has changed and must be written back to disk."""
	if profileName is None:
		# NVDA always writes the normal configuration out when it saves.
		return
	# NVDA offers no public way to flag a named profile as needing to be written back to disk.
	dirtyProfiles: set[str] | None = getattr(nvdaConfig.conf, "_dirtyProfiles", None)
	if dirtyProfiles is None:
		log.error(f"Could not mark the '{profileName}' configuration profile as changed.")
		return
	dirtyProfiles.add(profileName)


def installProfileHooks() -> None:
	"""Start reporting profile renames and deletions through this module's extension points.

	NVDA announces a profile switch but not a rename or a deletion. Credentials are addressed by
	profile name, so they would be orphaned by either. The two configuration manager methods that
	change those names are wrapped here; each wrapper lets NVDA do its work first and only then
	reports it, so a failed rename or deletion never moves a credential.
	"""
	if _installedHooks:
		return
	renameProfile: Callable[..., Any] | None = getattr(nvdaConfig.conf, "renameProfile", None)
	deleteProfile: Callable[..., Any] | None = getattr(nvdaConfig.conf, "deleteProfile", None)
	if renameProfile is None or deleteProfile is None:
		log.error(
			"This NVDA version does not support renaming or deleting configuration profiles, so stored API keys cannot follow them.",
		)
		return

	def onRenameProfile(oldName: str, newName: str) -> Any:
		result = renameProfile(oldName, newName)
		try:
			post_profileRenamed.notify(oldName=oldName, newName=newName)
		except Exception:
			log.exception(f"Could not update what is stored for the renamed profile '{newName}'.")
		return result

	def onDeleteProfile(profileName: str) -> Any:
		result = deleteProfile(profileName)
		try:
			post_profileDeleted.notify(profileName=profileName)
		except Exception:
			log.exception(f"Could not clean up what is stored for the deleted profile '{profileName}'.")
		return result

	nvdaConfig.conf.renameProfile = onRenameProfile
	nvdaConfig.conf.deleteProfile = onDeleteProfile
	_installedHooks["renameProfile"] = onRenameProfile
	_installedHooks["deleteProfile"] = onDeleteProfile


def removeProfileHooks() -> None:
	"""Stop reporting profile renames and deletions, restoring NVDA's own methods."""
	for methodName, wrapper in _installedHooks.items():
		if getattr(nvdaConfig.conf, methodName, None) is not wrapper:
			# Something else replaced the wrapper; removing it now would undo that instead.
			continue
		try:
			delattr(nvdaConfig.conf, methodName)
		except AttributeError:
			log.error(f"Could not restore NVDA's own '{methodName}' method.")
	_installedHooks.clear()
