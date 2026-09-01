# -*- coding: utf-8 -*-

# Copyright (C) 2025-2026 cary-rowen <manchen_0528@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Shared base implementation for NVDACN-hosted JSON translation services."""

import json
import urllib.parse
from typing import Any

import addonHandler

from ...common.exceptions import ApiResponseError, AuthenticationError, EngineError
from ..engine import BaseHttpEngine

addonHandler.initTranslation()


NVDACN_API_URL = "https://nvdacn.com/api/"


class NvdacnJsonEngine(BaseHttpEngine):
	"""Provide common configuration, request, and response handling for NVDACN JSON APIs."""

	API_URL = NVDACN_API_URL
	SERVICE_NAME = ""

	def getConfigSpec(self) -> list[dict[str, Any]]:
		"""Return the common NVDACN credential controls."""
		spec = super().getConfigSpec()
		spec.extend(
			[
				{"id": "nvdacnUser", "label": _("NVDACN Username"), "type": "text", "default": ""},
				{"id": "nvdacnPass", "label": _("NVDACN Password"), "type": "password", "default": ""},
			],
		)
		return spec

	def _buildRequestParams(self, text: str, langFrom: str, langTo: str, config: dict) -> dict:
		"""Build an authenticated JSON request for the configured NVDACN service."""
		nvdacnUser = config.get("nvdacnUser")
		nvdacnPass = config.get("nvdacnPass")
		if not nvdacnUser or not nvdacnPass:
			raise AuthenticationError(_("NVDACN username and password must be provided in settings."))
		queryParams = {
			"user": nvdacnUser,
			"pass": nvdacnPass,
			"name": self.SERVICE_NAME,
			"action": "translate",
		}
		bodyParams = {"text": text, "source": langFrom if langFrom else "auto", "target": langTo}
		return {
			"method": "POST",
			"url": f"{self.API_URL}?{urllib.parse.urlencode(queryParams)}",
			"headers": {"Content-Type": "application/json"},
			"data": json.dumps(bodyParams).encode("utf-8"),
		}

	def _parseResponse(self, responseBody: str) -> dict:
		"""Parse the common response and error format returned by NVDACN services."""
		result = json.loads(responseBody)
		if result.get("code") == 200 and "data" in result:
			data = result["data"]
			translatedText = data.get("translation")
			if translatedText is not None:
				return {"translation": translatedText, "langDetected": data.get("langDetected")}
			raise ApiResponseError(_("API response successful but did not contain a translation result."))

		errorCode = result.get("code")
		errorMessage = result.get("data", _("Unknown API error"))
		if errorCode in (401, 403):
			# Translators: Error message when authentication with the translation service fails. {error} is the detailed error description.
			raise EngineError(_("Authentication failed: {error}").format(error=errorMessage))
		raise ApiResponseError(f"{errorMessage} (Code: {errorCode or 'N/A'})")
