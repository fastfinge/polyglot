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
"""

import ctypes
import os
import re
from ctypes import wintypes

from logHandler import log

#: Control type used by engines for configuration items that hold a credential.
SECRET_CONTROL_TYPE = "password"

#: Prefix shared by every credential Polyglot writes to the Windows Credential Locker.
TARGET_PREFIX = "NVDA/Polyglot/"

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


def getTargetName(engineId: str, key: str) -> str:
	"""Return the Credential Locker target name holding one engine credential."""
	return f"{TARGET_PREFIX}{engineId}/{key}"


def getEnvironmentVariableName(engineId: str, key: str) -> str:
	"""Return the environment variable that can supply one engine credential."""
	return ENVIRONMENT_PREFIX + re.sub(r"[^A-Z0-9]", "_", f"{engineId}_{key}".upper())


def getFromEnvironment(engineId: str, key: str) -> str | None:
	"""Return an engine credential supplied by the environment, or None when there is none."""
	value = os.environ.get(getEnvironmentVariableName(engineId, key), "").strip()
	return value or None


def isProvidedByEnvironment(engineId: str, key: str) -> bool:
	"""Return whether the environment supplies an engine credential, overriding any stored one."""
	return getFromEnvironment(engineId, key) is not None


def getSecret(engineId: str, key: str) -> str:
	"""Return a stored engine credential, or an empty string when none is available."""
	fromEnvironment = getFromEnvironment(engineId, key)
	if fromEnvironment is not None:
		return fromEnvironment
	if _credentialApi is None:
		return ""
	credential = ctypes.POINTER(_Credential)()
	if not _credentialApi.CredReadW(
		getTargetName(engineId, key),
		_CRED_TYPE_GENERIC,
		0,
		ctypes.byref(credential),
	):
		errorCode = ctypes.get_last_error()
		if errorCode != _ERROR_NOT_FOUND:
			log.error(f"Could not read the '{engineId}' credential '{key}' (Windows error {errorCode}).")
		return ""
	try:
		blobSize = credential.contents.CredentialBlobSize
		blob = ctypes.string_at(credential.contents.CredentialBlob, blobSize) if blobSize else b""
	finally:
		_credentialApi.CredFree(credential)
	return blob.decode("utf-16-le", errors="replace")


def setSecret(engineId: str, key: str, value: str) -> bool:
	"""Store one engine credential, removing it instead when value is empty.

	:return: Whether the credential was stored or removed successfully.
	"""
	value = value.strip()
	if not value:
		return deleteSecret(engineId, key)
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
		TargetName=getTargetName(engineId, key),
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


def deleteSecret(engineId: str, key: str) -> bool:
	"""Remove one stored engine credential.

	:return: Whether no stored copy of the credential remains.
	"""
	if _credentialApi is None:
		# Nothing can have been stored, so there is nothing left to remove.
		return True
	if _credentialApi.CredDeleteW(getTargetName(engineId, key), _CRED_TYPE_GENERIC, 0):
		return True
	errorCode = ctypes.get_last_error()
	if errorCode == _ERROR_NOT_FOUND:
		return True
	log.error(f"Could not remove the '{engineId}' credential '{key}' (Windows error {errorCode}).")
	return False


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


def deleteAllSecrets() -> int:
	"""Remove every credential Polyglot has stored, and return how many were removed."""
	if _credentialApi is None:
		return 0
	removedCount = 0
	for targetName in getStoredTargetNames():
		if _credentialApi.CredDeleteW(targetName, _CRED_TYPE_GENERIC, 0):
			removedCount += 1
		else:
			errorCode = ctypes.get_last_error()
			log.error(f"Could not remove the credential '{targetName}' (Windows error {errorCode}).")
	return removedCount
