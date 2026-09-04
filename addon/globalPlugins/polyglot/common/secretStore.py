# -*- coding: utf-8 -*-

# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Storage for engine credentials outside NVDA's configuration file.

API keys, tokens, and passwords are never written to ``nvda.ini``. A credential is taken from an
environment variable when one is set, and is otherwise kept in the Windows Credential Locker, where
Windows encrypts it for the signed-in account. Keeping credentials out of ``nvda.ini`` keeps them out
of NVDA's log and out of portable copies, denies them to other add-ons, and lets users review or
remove them from Windows' own Credential Manager.

Every credential belongs to one NVDA configuration profile, so a user can hold a different key in
each profile. Because credentials do not live in ``nvda.ini``, NVDA cannot apply its own profile
rules to them, so this module applies those rules instead: a credential is looked for in the most
recently activated profile first and then in each profile below it, ending at the normal
configuration, and a credential is saved to the profile NVDA is currently writing to. See
:mod:`.configProfiles`.
"""

import ctypes
import enum
import os
import re
from ctypes import wintypes
from typing import NamedTuple

from logHandler import log

from . import configProfiles

#: Control type used by engines for configuration items that hold a credential.
SECRET_CONTROL_TYPE = "password"

#: Prefix shared by every credential Polyglot writes to the Windows Credential Locker.
TARGET_PREFIX = "NVDA/Polyglot/"

#: Marks the configuration profile a credential belongs to. The colon cannot appear in an NVDA
#: profile name, which is a file name, nor in an engine ID, so this can never be mistaken for either.
_PROFILE_MARKER = "profiles:"

#: Prefix shared by every environment variable that can supply a credential.
ENVIRONMENT_PREFIX = "POLYGLOT_"

#: Description stored with each credential so it is recognisable in Windows' Credential Manager.
_CREDENTIAL_COMMENT = "Credential for the Polyglot NVDA add-on."

_CRED_TYPE_GENERIC = 1
# Credentials stay on this machine and are never roamed to another one.
_CRED_PERSIST_LOCAL_MACHINE = 2
#: Maximum credential blob size in bytes, as documented for ``CREDENTIALW``.
_CRED_MAX_CREDENTIAL_BLOB_SIZE = 5 * 512
_ERROR_NOT_FOUND = 1168


class CredentialSource(enum.Enum):
	"""Where the credential in force for the active configuration profile came from."""

	#: Nothing supplies the credential.
	NONE = enum.auto()
	#: An environment variable supplies it, overriding every stored copy.
	ENVIRONMENT = enum.auto()
	#: A configuration profile has a stored copy.
	PROFILE = enum.auto()


class ResolvedCredential(NamedTuple):
	"""One credential as the active configuration profile sees it."""

	#: The credential itself, or an empty string when nothing supplies it.
	value: str
	#: What supplied the credential.
	source: CredentialSource
	#: The profile holding it, or None for the normal configuration. Only meaningful for ``PROFILE``.
	profileName: str | None = None


class _Credential(ctypes.Structure):
	"""Mirror the Windows ``CREDENTIALW`` structure."""

	_fields_ = (
		("Flags", wintypes.DWORD),
		("Type", wintypes.DWORD),
		("TargetName", wintypes.LPWSTR),
		("Comment", wintypes.LPWSTR),
		("LastWritten", wintypes.FILETIME),
		("CredentialBlobSize", wintypes.DWORD),
		("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
		("Persist", wintypes.DWORD),
		("AttributeCount", wintypes.DWORD),
		("Attributes", ctypes.c_void_p),
		("TargetAlias", wintypes.LPWSTR),
		("UserName", wintypes.LPWSTR),
	)


def _loadCredentialApi() -> "ctypes.WinDLL | None":
	"""Return the Windows credential management library, or None when it cannot be used."""
	try:
		library = ctypes.WinDLL("advapi32", use_last_error=True)
	except (AttributeError, OSError):
		log.error("The Windows Credential Locker is unavailable; Polyglot cannot store credentials.")
		return None
	credentialPointer = ctypes.POINTER(_Credential)
	library.CredReadW.argtypes = (
		wintypes.LPCWSTR,
		wintypes.DWORD,
		wintypes.DWORD,
		ctypes.POINTER(credentialPointer),
	)
	library.CredReadW.restype = wintypes.BOOL
	library.CredWriteW.argtypes = (credentialPointer, wintypes.DWORD)
	library.CredWriteW.restype = wintypes.BOOL
	library.CredDeleteW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD)
	library.CredDeleteW.restype = wintypes.BOOL
	library.CredEnumerateW.argtypes = (
		wintypes.LPCWSTR,
		wintypes.DWORD,
		ctypes.POINTER(wintypes.DWORD),
		ctypes.POINTER(ctypes.POINTER(credentialPointer)),
	)
	library.CredEnumerateW.restype = wintypes.BOOL
	library.CredFree.argtypes = (ctypes.c_void_p,)
	library.CredFree.restype = None
	return library


_credentialApi: "ctypes.WinDLL | None" = _loadCredentialApi()


def getTargetName(engineId: str, key: str, profileName: str | None = None) -> str:
	"""Return the Credential Locker target name holding one engine credential in one profile.

	:param profileName: The profile the credential belongs to, or None for the normal configuration.
	"""
	if profileName:
		return f"{TARGET_PREFIX}{_PROFILE_MARKER}{profileName}/{engineId}/{key}"
	# The normal configuration keeps the unqualified name Polyglot has always used, so credentials
	# stored before profiles were supported stay where they are and go on working.
	return f"{TARGET_PREFIX}{engineId}/{key}"


def parseTargetName(targetName: str) -> tuple[str | None, str, str] | None:
	"""Split one of Polyglot's target names back into its profile, engine, and setting.

	:return: The profile name (None for the normal configuration), the engine ID, and the setting ID,
		or None when the target name is not one Polyglot writes.
	"""
	if not targetName.startswith(TARGET_PREFIX):
		return None
	parts = targetName[len(TARGET_PREFIX) :].split("/")
	profileName: str | None = None
	if parts and parts[0].startswith(_PROFILE_MARKER):
		profileName = parts[0][len(_PROFILE_MARKER) :]
		parts = parts[1:]
		if not profileName:
			return None
	if len(parts) != 2 or not all(parts):
		return None
	return (profileName, parts[0], parts[1])


def getEnvironmentVariableName(engineId: str, key: str) -> str:
	"""Return the environment variable that can supply one engine credential."""
	return ENVIRONMENT_PREFIX + re.sub(r"[^A-Z0-9]", "_", f"{engineId}_{key}".upper())


def getFromEnvironment(engineId: str, key: str) -> str | None:
	"""Return an engine credential supplied by the environment, or None when there is none.

	The environment describes the whole machine rather than one profile, so a variable set here
	applies to every configuration profile.
	"""
	value = os.environ.get(getEnvironmentVariableName(engineId, key), "").strip()
	return value or None


def isProvidedByEnvironment(engineId: str, key: str) -> bool:
	"""Return whether the environment supplies an engine credential, overriding any stored one."""
	return getFromEnvironment(engineId, key) is not None


def _readCredential(targetName: str) -> str:
	"""Return the credential stored under one target name, or an empty string when there is none."""
	if _credentialApi is None:
		return ""
	credential = ctypes.POINTER(_Credential)()
	if not _credentialApi.CredReadW(
		targetName,
		_CRED_TYPE_GENERIC,
		0,
		ctypes.byref(credential),
	):
		errorCode = ctypes.get_last_error()
		if errorCode != _ERROR_NOT_FOUND:
			log.error(f"Could not read the credential '{targetName}' (Windows error {errorCode}).")
		return ""
	try:
		blobSize = credential.contents.CredentialBlobSize
		blob = ctypes.string_at(credential.contents.CredentialBlob, blobSize) if blobSize else b""
	finally:
		_credentialApi.CredFree(credential)
	return blob.decode("utf-16-le", errors="replace")


def getStoredSecret(engineId: str, key: str, profileName: str | None) -> str:
	"""Return the credential one configuration profile stores itself, ignoring inheritance.

	:param profileName: The profile to look in, or None for the normal configuration.
	:return: The stored credential, or an empty string when that profile stores none of its own.
	"""
	return _readCredential(getTargetName(engineId, key, profileName))


def resolveSecret(engineId: str, key: str) -> ResolvedCredential:
	"""Return the credential in force for the active configuration profile, and where it came from.

	The environment wins over everything. Otherwise the active profiles are searched in NVDA's own
	order, from the most recently activated profile down to the normal configuration, so a profile
	that stores no credential of its own inherits the one below it.
	"""
	fromEnvironment = getFromEnvironment(engineId, key)
	if fromEnvironment is not None:
		return ResolvedCredential(fromEnvironment, CredentialSource.ENVIRONMENT)
	for profileName in configProfiles.getActiveProfileNames():
		value = getStoredSecret(engineId, key, profileName)
		if value:
			return ResolvedCredential(value, CredentialSource.PROFILE, profileName)
	return ResolvedCredential("", CredentialSource.NONE)


def getSecret(engineId: str, key: str) -> str:
	"""Return the credential in force for the active configuration profile.

	:return: The credential, or an empty string when nothing supplies one.
	"""
	return resolveSecret(engineId, key).value


def setSecret(engineId: str, key: str, value: str, profileName: str | None) -> bool:
	"""Store one engine credential in one configuration profile, removing it when value is empty.

	Removing a credential from a named profile makes that profile inherit again, exactly as removing
	a setting from a profile in ``nvda.ini`` would.

	:param profileName: The profile to store it in, or None for the normal configuration.
	:return: Whether the credential was stored or removed successfully.
	"""
	value = value.strip()
	if not value:
		return deleteSecret(engineId, key, profileName)
	if _credentialApi is None:
		log.error(f"Could not store the '{engineId}' credential '{key}'; no secure storage is available.")
		return False
	blob = value.encode("utf-16-le")
	if len(blob) > _CRED_MAX_CREDENTIAL_BLOB_SIZE:
		log.error(f"The '{engineId}' credential '{key}' is too long for the Windows Credential Locker.")
		return False
	# The buffer must outlive the CredWriteW call, so it is held in its own local variable.
	blobBuffer = ctypes.create_string_buffer(blob, len(blob))
	credential = _Credential(
		Flags=0,
		Type=_CRED_TYPE_GENERIC,
		TargetName=getTargetName(engineId, key, profileName),
		Comment=_CREDENTIAL_COMMENT,
		CredentialBlobSize=len(blob),
		CredentialBlob=ctypes.cast(blobBuffer, ctypes.POINTER(ctypes.c_byte)),
		Persist=_CRED_PERSIST_LOCAL_MACHINE,
		AttributeCount=0,
		Attributes=None,
		TargetAlias=None,
		UserName=engineId,
	)
	if _credentialApi.CredWriteW(ctypes.byref(credential), 0):
		return True
	log.error(
		f"Could not store the '{engineId}' credential '{key}' (Windows error {ctypes.get_last_error()}).",
	)
	return False


def _deleteCredential(targetName: str) -> bool:
	"""Remove the credential stored under one target name.

	:return: Whether no stored copy of the credential remains.
	"""
	if _credentialApi is None:
		# Nothing can have been stored, so there is nothing left to remove.
		return True
	if _credentialApi.CredDeleteW(targetName, _CRED_TYPE_GENERIC, 0):
		return True
	errorCode = ctypes.get_last_error()
	if errorCode == _ERROR_NOT_FOUND:
		return True
	log.error(f"Could not remove the credential '{targetName}' (Windows error {errorCode}).")
	return False


def deleteSecret(engineId: str, key: str, profileName: str | None) -> bool:
	"""Remove one engine credential from one configuration profile.

	:param profileName: The profile to remove it from, or None for the normal configuration.
	:return: Whether no stored copy of the credential remains in that profile.
	"""
	return _deleteCredential(getTargetName(engineId, key, profileName))


def getStoredTargetNames() -> list[str]:
	"""Return the target names of every credential Polyglot has stored on this machine."""
	if _credentialApi is None:
		return []
	count = wintypes.DWORD(0)
	credentials = ctypes.POINTER(ctypes.POINTER(_Credential))()
	if not _credentialApi.CredEnumerateW(
		f"{TARGET_PREFIX}*",
		0,
		ctypes.byref(count),
		ctypes.byref(credentials),
	):
		errorCode = ctypes.get_last_error()
		if errorCode != _ERROR_NOT_FOUND:
			log.error(f"Could not list the stored Polyglot credentials (Windows error {errorCode}).")
		return []
	try:
		targetNames = (credentials[index].contents.TargetName for index in range(count.value))
		return [targetName for targetName in targetNames if targetName]
	finally:
		_credentialApi.CredFree(credentials)


def getStoredTargetNamesForProfile(profileName: str | None) -> list[str]:
	"""Return the target names of every credential stored for one configuration profile.

	:param profileName: The profile to list, or None for the normal configuration.
	"""
	stored: list[str] = []
	for targetName in getStoredTargetNames():
		parsed = parseTargetName(targetName)
		if parsed is not None and parsed[0] == profileName:
			stored.append(targetName)
	return stored


def deleteAllSecrets() -> int:
	"""Remove every credential Polyglot has stored in every profile.

	:return: How many credentials were removed.
	"""
	return sum(1 for targetName in getStoredTargetNames() if _deleteCredential(targetName))


def deleteSecretsForProfile(profileName: str) -> int:
	"""Remove every credential stored for one named configuration profile.

	This keeps a deleted profile's API keys from outliving it in Windows' Credential Manager.

	:return: How many credentials were removed.
	"""
	if not profileName:
		# The normal configuration is never deleted, and an empty name would match no credential.
		return 0
	removedCount = 0
	for targetName in getStoredTargetNamesForProfile(profileName):
		if _deleteCredential(targetName):
			removedCount += 1
	if removedCount:
		log.debug(f"Removed {removedCount} credential(s) stored for the deleted profile '{profileName}'.")
	return removedCount


def renameProfileSecrets(oldName: str, newName: str) -> int:
	"""Move every credential stored for one named configuration profile to its new name.

	Credentials are addressed by profile name, so without this a renamed profile would silently lose
	the API keys it was set up with.

	:return: How many credentials were moved.
	"""
	if not oldName or not newName or oldName.casefold() == newName.casefold():
		# Windows matches target names without regard to case, so a rename that only changes the
		# casing already reaches the same credentials. Moving them would delete what it just wrote.
		return 0
	movedCount = 0
	for targetName in getStoredTargetNamesForProfile(oldName):
		parsed = parseTargetName(targetName)
		if parsed is None:
			continue
		engineId, key = parsed[1], parsed[2]
		value = _readCredential(targetName)
		if not value:
			_unused = _deleteCredential(targetName)
			continue
		if not setSecret(engineId, key, value, newName):
			log.error(
				f"The '{engineId}' credential '{key}' could not be moved to the renamed profile '{newName}', so it has been left under '{oldName}'.",
			)
			continue
		_unused = _deleteCredential(targetName)
		movedCount += 1
	if movedCount:
		log.debug(f"Moved {movedCount} credential(s) from the profile '{oldName}' to '{newName}'.")
	return movedCount
