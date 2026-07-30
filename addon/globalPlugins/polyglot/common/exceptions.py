# -*- coding: utf-8 -*-

# Copyright (C) 2025-2026 cary-rowen <manchen_0528@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""This module defines all custom exception types for the add-on."""


class EngineError(Exception):
	"""
	Base class for all exceptions related to translation engine interactions.
	Catching this exception can handle all known engine-related issues.
	"""

	message: str

	def __init__(self, message: str) -> None:
		"""Initialize the error with a user-facing description."""
		self.message = message
		super().__init__(self.message)

	def __str__(self) -> str:
		"""Return the user-facing error description."""
		return str(self.message)


class NetworkConnectionError(EngineError):
	"""
	Raised for retryable network-level errors (e.g., timeouts, DNS failures, connection refused).
	This is raised by the network module after multiple retry attempts have failed.
	"""

	pass


class ApiResponseError(EngineError):
	"""
	Raised when a network request is successful, but the API returns a business logic error
	(e.g., invalid API key, insufficient quota, bad parameters).
	"""

	pass


class ResponseParsingError(EngineError):
	"""Raised when the API's response cannot be parsed correctly (e.g., invalid JSON)."""

	pass


class SilentTranslationCancel(Exception):
	"""Raised when a translation task should stop without user-facing failure output."""

	pass


class AuthenticationError(ApiResponseError):
	"""A specific error for authentication failures."""

	pass
