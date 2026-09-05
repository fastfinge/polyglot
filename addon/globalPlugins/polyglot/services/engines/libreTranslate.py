# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Translate through a LibreTranslate server.

LibreTranslate runs the same Argos models as Polyglot's offline engine, but on a server rather than
inside NVDA. That suits anyone whose computer is too slow to translate locally, anyone on a 32-bit
NVDA, where the Argos engine is unavailable, and anyone who already has a LibreTranslate server to
point at. Which server is used is entirely the user's choice: the address defaults to a copy running
on this machine, so nothing is sent anywhere until the address is changed.
"""

import json
from typing import Any

import addonHandler

from ...common import languages
from ...common.exceptions import ApiResponseError, AuthenticationError, EngineError
from ..engine import BaseHttpEngine

addonHandler.initTranslation()


class LibreTranslateEngine(BaseHttpEngine):
	"""Translate text with the LibreTranslate API of a user-supplied server."""

	id = "libretranslate"
	name = _("LibreTranslate")

	#: Address used until the user supplies one. A LibreTranslate server installed on this computer
	#: listens here, so the default sends nothing to anyone else. Point it at your own server, or at
	#: a hosted one such as ``https://libretranslate.com``, to translate somewhere else.
	DEFAULT_SERVER_URL = "http://localhost:5000"

	#: Path appended to the server address to reach the translation endpoint.
	_TRANSLATE_PATH = "/translate"

	@property
	def autoDetectCode(self) -> str | None:
		return "auto"

	@property
	def defaultTargetLanguage(self) -> str:
		return "en"

	@property
	def maxRequestLength(self) -> int:
		"""Return the text size sent at once, kept below the character limit servers commonly set."""
		return 2000

	def getSupportedLanguages(self) -> dict[str, str]:
		"""Return the languages a LibreTranslate server can be built with.

		These are the languages the Argos package index publishes, which is what LibreTranslate
		installs. A server can be built with fewer, and asking it for one it does not have is
		answered with an error naming the languages it does have.
		"""
		return languages.getLanguageDictForCodes(
			[
				"auto",
				"ar",
				"az",
				"bg",
				"bn",
				"ca",
				"cs",
				"da",
				"de",
				"el",
				"en",
				"eo",
				"es",
				"et",
				"eu",
				"fa",
				"fi",
				"fr",
				"ga",
				"gl",
				"he",
				"hi",
				"hu",
				"id",
				"it",
				"ja",
				"ko",
				"ky",
				"lt",
				"lv",
				"ms",
				"nb",
				"nl",
				"pb",
				"pl",
				"pt",
				"ro",
				"ru",
				"sk",
				"sl",
				"sq",
				"sv",
				"sw",
				"th",
				"tl",
				"tr",
				"uk",
				"ur",
				"vi",
				"zh",
				"zt",
			],
		)

	def getConfigSpec(self) -> list[dict[str, Any]]:
		spec = super().getConfigSpec()
		spec.extend(
			[
				{
					"id": "serverUrl",
					"label": _("Server address:"),
					"type": "text",
					"default": self.DEFAULT_SERVER_URL,
				},
				{
					"id": "apiKey",
					"label": _("API key (leave empty if the server does not require one):"),
					"type": "password",
					"default": "",
				},
			],
		)
		return spec

	def _getEndpointUrl(self, config: dict[str, Any]) -> str:
		"""Return the translation endpoint of the configured server.

		:raises AuthenticationError: If no server address is configured.
		:raises EngineError: If the address is not one that can be requested.
		"""
		serverUrl = str(config.get("serverUrl", "")).strip().rstrip("/")
		if not serverUrl:
			raise AuthenticationError(_("No LibreTranslate server address is configured."))
		if "://" not in serverUrl:
			raise EngineError(
				# Translators: Reported when the LibreTranslate server address has no scheme.
				# {address} is the address the user typed.
				_(
					"The LibreTranslate server address must start with http:// or https://. It is currently {address}.",
				).format(address=serverUrl),
			)
		# The endpoint is accepted either as the server's own address or written out in full, so an
		# address copied from a server's API documentation works as typed.
		if serverUrl.endswith(self._TRANSLATE_PATH):
			return serverUrl
		return serverUrl + self._TRANSLATE_PATH

	def _buildRequestParams(
		self,
		text: str,
		langFrom: str,
		langTo: str,
		config: dict[str, Any],
	) -> dict[str, Any]:
		payload: dict[str, Any] = {
			"q": text,
			"source": langFrom or self.autoDetectCode,
			"target": langTo,
			"format": "text",
		}
		apiKey = str(config.get("apiKey", "")).strip()
		if apiKey:
			payload["api_key"] = apiKey
		return {
			"method": "POST",
			"url": self._getEndpointUrl(config),
			"headers": {"Content-Type": "application/json", "Accept": "application/json"},
			"data": json.dumps(payload).encode("utf-8"),
		}

	def _parseResponse(self, responseBody: str) -> dict[str, Any]:
		data = json.loads(responseBody)
		if not isinstance(data, dict):
			raise ApiResponseError(_("The LibreTranslate server returned an unexpected response."))
		# A server that rejects the request answers with an 'error' field describing why, which is
		# far more useful than anything this add-on could say about it.
		error = data.get("error")
		if error:
			raise ApiResponseError(str(error))
		translation = data.get("translatedText")
		if translation is None:
			raise ApiResponseError(_("The LibreTranslate server returned no translation."))
		detected = data.get("detectedLanguage")
		detectedLanguage = detected.get("language") if isinstance(detected, dict) else None
		return {
			"translation": str(translation),
			"langDetected": str(detectedLanguage) if detectedLanguage else None,
		}
