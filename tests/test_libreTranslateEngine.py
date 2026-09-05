# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Runnable checks for the LibreTranslate engine's server address handling and API contract."""

import builtins
import json
import sys
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if not hasattr(builtins, "_"):
	setattr(builtins, "_", lambda message: message)
for moduleName in ("config", "nvwave", "queueHandler", "tones", "ui"):
	sys.modules.setdefault(moduleName, ModuleType(moduleName))
globalVars = ModuleType("globalVars")
setattr(globalVars, "appArgs", Mock(configPath=str(PROJECT_ROOT)))
sys.modules.setdefault("globalVars", globalVars)
extensionPoints = ModuleType("extensionPoints")
setattr(extensionPoints, "Action", Mock)
sys.modules.setdefault("extensionPoints", extensionPoints)
addonHandler = ModuleType("addonHandler")
setattr(addonHandler, "initTranslation", Mock())
sys.modules.setdefault("addonHandler", addonHandler)
logHandler = ModuleType("logHandler")
setattr(logHandler, "log", Mock())
sys.modules.setdefault("logHandler", logHandler)
polyglotPackage = ModuleType("polyglot")
setattr(polyglotPackage, "__path__", [str(PROJECT_ROOT / "addon" / "globalPlugins" / "polyglot")])
sys.modules.setdefault("polyglot", polyglotPackage)

from polyglot.common.exceptions import (  # noqa: E402
	ApiResponseError,
	AuthenticationError,
	EngineError,
)
from polyglot.services.engines.libreTranslate import LibreTranslateEngine  # noqa: E402


class LibreTranslateEngineTest(unittest.TestCase):
	"""Check the endpoint the engine builds, and how it reads a server's answer."""

	def setUp(self) -> None:
		"""Create the engine and a configuration naming a server of one's own."""
		self.engine = LibreTranslateEngine()
		self.config = {
			"proxyMode": "none",
			"timeout": 15,
			"serverUrl": "https://translate.example.org",
			"apiKey": "",
		}

	def _getSpecItem(self, itemId: str) -> dict:
		"""Return the configuration specification entry with the given id."""
		for item in self.engine.getConfigSpec():
			if item["id"] == itemId:
				return item
		raise AssertionError(f"No configuration item '{itemId}'.")

	def test_defaultServerIsOnThisComputer(self) -> None:
		"""Nothing is sent anywhere until the user names a server of their own."""
		self.assertEqual(self._getSpecItem("serverUrl")["default"], "http://localhost:5000")

	def test_apiKeyIsStoredAsACredential(self) -> None:
		"""The API key is a credential, so it is kept out of NVDA's configuration file."""
		self.assertEqual(self._getSpecItem("apiKey")["type"], "password")
		self.assertEqual(self._getSpecItem("apiKey")["default"], "")

	def test_buildsTranslateRequestForConfiguredServer(self) -> None:
		"""The server address gains the translation path, and the key is left out when unset."""
		params = self.engine._buildRequestParams("hello", "auto", "es", self.config)

		self.assertEqual(params["method"], "POST")
		self.assertEqual(params["url"], "https://translate.example.org/translate")
		self.assertEqual(
			json.loads(params["data"].decode("utf-8")),
			{"q": "hello", "source": "auto", "target": "es", "format": "text"},
		)

	def test_sendsApiKeyWhenTheServerNeedsOne(self) -> None:
		"""A configured key travels in the request body, as the LibreTranslate API expects."""
		params = self.engine._buildRequestParams("hello", "en", "de", {**self.config, "apiKey": " k "})

		self.assertEqual(json.loads(params["data"].decode("utf-8"))["api_key"], "k")

	def test_acceptsAnAddressWrittenOutInFull(self) -> None:
		"""An address copied from a server's API documentation is not given a second path."""
		config = {**self.config, "serverUrl": "https://translate.example.org/translate/"}
		params = self.engine._buildRequestParams("hello", "auto", "es", config)

		self.assertEqual(params["url"], "https://translate.example.org/translate")

	def test_rejectsAnEmptyServerAddress(self) -> None:
		"""An unconfigured server is reported before anything is sent."""
		with self.assertRaises(AuthenticationError):
			self.engine._buildRequestParams("hello", "auto", "es", {**self.config, "serverUrl": "  "})

	def test_rejectsAnAddressWithoutAScheme(self) -> None:
		"""A bare host name is reported as the mistake it is, rather than an unknown error."""
		with self.assertRaises(EngineError):
			self.engine._buildRequestParams(
				"hello",
				"auto",
				"es",
				{**self.config, "serverUrl": "localhost:5000"},
			)

	def test_usesSharedBaseHttpRequestFlow(self) -> None:
		"""Translation goes through the base class request and retry wrapper."""
		responseBody = '{"translatedText":"hola","detectedLanguage":{"confidence":92,"language":"en"}}'
		with patch("polyglot.services.engine.sendRequest", return_value=responseBody) as sendRequest:
			result = self.engine._translateChunk("hello", "auto", "es", self.config)

		sendRequest.assert_called_once()
		self.assertEqual(result, {"translation": "hola", "langDetected": "en"})
		self.assertEqual(sendRequest.call_args.kwargs["url"], "https://translate.example.org/translate")
		self.assertEqual(sendRequest.call_args.kwargs["proxies"], {"http": None, "https": None})

	def test_reportsNoDetectedLanguageForAnExplicitSource(self) -> None:
		"""A server answering without a detected language is not reported as having guessed one."""
		self.assertEqual(
			self.engine._parseResponse('{"translatedText":"hola"}'),
			{"translation": "hola", "langDetected": None},
		)

	def test_surfacesTheServersOwnErrorText(self) -> None:
		"""What the server says is wrong reaches the user unchanged."""
		with self.assertRaises(ApiResponseError) as caught:
			self.engine._parseResponse('{"error":"es is not supported"}')

		self.assertEqual(str(caught.exception), "es is not supported")

	def test_rejectsAResponseWithoutATranslation(self) -> None:
		"""An answer holding no translation becomes a user-facing API error."""
		with self.assertRaises(ApiResponseError):
			self.engine._parseResponse("{}")
		with self.assertRaises(ApiResponseError):
			self.engine._parseResponse("[]")

	def test_offersEveryLanguageLibreTranslateCanBeBuiltWith(self) -> None:
		"""Automatic detection and the Argos language set are both offered, with real names."""
		supported = self.engine.getSupportedLanguages()

		self.assertIn("auto", supported)
		# 'zt' and 'pb' are the codes LibreTranslate uses for traditional Chinese and Brazilian
		# Portuguese, and are easily confused with the more usual ones.
		for code in ("zt", "pb", "en", "es"):
			self.assertIn(code, supported)
		self.assertTrue(all(name and name != code for code, name in supported.items()))


if __name__ == "__main__":
	unittest.main()
