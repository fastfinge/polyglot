# -*- coding: utf-8 -*-

# Copyright (C) 2025-2026 cary-rowen <manchen_0528@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

import json
import urllib.parse

import addonHandler

from ...common import languages
from ..engine import BaseHttpEngine
from ...common.exceptions import ApiResponseError

addonHandler.initTranslation()


class LingvaTranslateEngine(BaseHttpEngine):
	"""
	An engine that uses the Lingva Translate public API.
	Lingva is an alternative front-end for Google Translate.
	"""

	id = "lingva"
	name = _("Lingva Translate")

	@property
	def maxRequestLength(self) -> int:
		"""
		Empirical testing (EN->ZH) revealed a limit of 4,998 characters.
		CRITICAL: Lingva uses GET requests with the text embedded in the URL path.
		URL-encoded Chinese characters will massively inflate the URI length.
		A very strict limit of 1,000 is enforced here to avoid '414 URI Too Long' crashes.
		"""
		return 1000

	@property
	def autoDetectCode(self) -> str | None:
		return "auto"

	@property
	def defaultTargetLanguage(self) -> str:
		return "zh"

	@property
	def doesReportDetectedLanguage(self) -> bool:
		# The API response does not include the detected source language.
		return False

	def getSupportedLanguages(self) -> dict:
		supportedCodes = [
			"auto",
			"zh",
			"zh_HANT",
			"en",
			"ja",
			"ko",
			"fr",
			"es",
			"ru",
			"de",
			"it",
			"tr",
			"pt",
			"vi",
			"id",
			"th",
			"ms",
			"ar",
			"hi",
			"mn",
			"km",
			"no",
			"fa",
			"sv",
			"pl",
			"nl",
			"uk",
			"he",
		]
		return languages.getLanguageDictForCodes(supportedCodes)

	def _buildRequestParams(self, text: str, langFrom: str, langTo: str, config: dict) -> dict:
		"""Build request parameters for the Lingva API."""
		# The API has a quirk where forward slashes in the text cause issues.
		# The JS code replaces them with '@@' before encoding.
		processedText = text.replace("/", "@@")
		encodedText = urllib.parse.quote(processedText)

		url = f"https://lingva.pot-app.com/api/v1/{langFrom}/{langTo}/{encodedText}"

		return {
			"method": "GET",
			"url": url,
			# No headers or data needed for this GET request
		}

	def _parseResponse(self, responseBody: str) -> dict:
		"""Parse a Lingva API response into the common translation result."""
		try:
			data = json.loads(responseBody)
		except json.JSONDecodeError:
			# Sometimes Lingva might return a non-JSON error for very long texts
			raise ApiResponseError(_("Service returned an invalid result (text may be too long)."))

		translation = data.get("translation")

		if translation:
			# Reverse the special character replacement from the request building step.
			finalTranslation = translation.replace("@@", "/")
			return {
				"translation": finalTranslation,
				"langDetected": None,  # API doesn't provide this
			}
		else:
			errorInfo = data.get("error", "Unknown API error")
			raise ApiResponseError(f"{errorInfo}")
