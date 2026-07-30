# -*- coding: utf-8 -*-

# Copyright (C) 2025-2026 cary-rowen <manchen_0528@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

import json
import urllib.parse

import addonHandler

from ...common import languages
from ..engine import BaseHttpEngine
from ...common.exceptions import ApiResponseError, AuthenticationError, EngineError

addonHandler.initTranslation()


class TencentWebTranslateEngine(BaseHttpEngine):
	"""Translate text through the NVDACN-hosted Tencent web service."""

	id = "tencentPolyglot"
	name = _("Tencent Translate (Polyglot)")

	API_URL = "https://nvdacn.com/api/"

	@property
	def autoDetectCode(self) -> str | None:
		return "auto"

	@property
	def defaultTargetLanguage(self) -> str:
		return "zh"

	@property
	def doesReportDetectedLanguage(self) -> bool:
		"""This engine does not support source language detection."""
		return False

	def getSupportedLanguages(self) -> dict:
		supportedCodes = ["auto", "zh", "en", "ja", "ko", "fr", "es", "ru", "de", "it", "ms", "th", "vi"]
		return languages.getLanguageDictForCodes(supportedCodes)

	def getConfigSpec(self) -> list[dict]:
		spec = super().getConfigSpec()
		spec.extend(
			[
				{"id": "nvdacnUser", "label": _("NVDACN Username"), "type": "text", "default": ""},
				{"id": "nvdacnPass", "label": _("NVDACN Password"), "type": "password", "default": ""},
			],
		)
		return spec

	def _buildRequestParams(self, text: str, langFrom: str, langTo: str, config: dict) -> dict:
		nvdacnUser = config.get("nvdacnUser")
		nvdacnPass = config.get("nvdacnPass")
		if not nvdacnUser or not nvdacnPass:
			raise AuthenticationError(_("NVDACN username and password must be provided in settings."))

		queryParams = {
			"user": nvdacnUser,
			"pass": nvdacnPass,
			"name": "tencentWeb",
			"action": "translate",
		}
		url = f"{self.API_URL}?{urllib.parse.urlencode(queryParams)}"

		sourceLanguage = langFrom if langFrom else "auto"
		bodyParams = {
			"text": text,
			"source": sourceLanguage,
			"target": langTo,
		}
		headers = {"Content-Type": "application/json"}
		return {
			"method": "POST",
			"url": url,
			"headers": headers,
			"data": json.dumps(bodyParams).encode("utf-8"),
		}

	def _parseResponse(self, responseBody: str) -> dict:
		result = json.loads(responseBody)
		if result.get("code") == 200 and "data" in result:
			data = result["data"]
			translatedText = data.get("translation")
			if translatedText is not None:
				detectedLang = data.get("langDetected")
				return {"translation": translatedText, "langDetected": detectedLang}
			else:
				raise ApiResponseError(
					_("API response successful but did not contain a translation result."),
				)
		else:
			errorCode = result.get("code")
			errorMessage = result.get("data", _("Unknown API error"))
			if errorCode in (401, 403):
				# Translators: Error message when authentication with the translation service fails. {error} is the detailed error description.
				raise EngineError(_("Authentication failed: {error}").format(error=errorMessage))
			raise ApiResponseError(f"{errorMessage} (Code: {errorCode or 'N/A'})")
