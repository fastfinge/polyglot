# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Runnable checks for DeepL's anonymous oneshot translation endpoint."""

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

from polyglot.common.exceptions import ApiResponseError  # noqa: E402
from polyglot.services.engines.deeplWeb import DeepLWebTranslateEngine  # noqa: E402


class DeepLWebTranslateEngineTest(unittest.TestCase):
	"""Check request construction and response parsing for the Web endpoint."""

	def setUp(self) -> None:
		"""Create the engine used by each check."""
		self.engine = DeepLWebTranslateEngine()

	def test_buildsMappedRequest(self) -> None:
		"""Generic and regional codes become valid oneshot codes."""
		params = self.engine._buildRequestParams("a &lt; b", "en", "zh-Hant", {})

		self.assertEqual(params["method"], "POST")
		self.assertEqual(params["url"], self.engine.API_URL)
		self.assertEqual(params["headers"]["Authorization"], "None")
		payload = json.loads(params["data"].decode("utf-8"))
		self.assertEqual(
			payload,
			{
				"text": ["a &lt; b"],
				"target_lang": "zh-Hant",
				"source_lang": "en",
				"usage_type": "Translate",
			},
		)

	def test_omitsSourceForAutomaticDetection(self) -> None:
		"""Automatic detection is represented by an omitted source field."""
		params = self.engine._buildRequestParams("hello", "auto", "en", {})
		payload = json.loads(params["data"].decode("utf-8"))

		self.assertEqual(payload["target_lang"], "en-US")
		self.assertNotIn("source_lang", payload)

	def test_rejectsUnknownLanguage(self) -> None:
		"""Unsupported codes fail before a request reaches the endpoint."""
		with self.assertRaises(ApiResponseError):
			self.engine._buildRequestParams("hello", "auto", "xx", {})
		with self.assertRaises(ApiResponseError):
			self.engine._buildRequestParams("hello", "auto", "auto", {})

	def test_usesAnonymousRequestLimit(self) -> None:
		"""The chunking layer receives the endpoint's documented limit."""
		self.assertEqual(self.engine.maxRequestLength, 1500)

	def test_countsUtf16UnitsWhenChunking(self) -> None:
		"""Supplementary characters consume two units at the endpoint."""
		text = "😀" * 751
		translateChunk = Mock(side_effect=lambda chunk, *args: {"translation": chunk, "langDetected": "en"})
		with (
			patch.object(self.engine, "_translateChunk", translateChunk),
			patch("polyglot.services.engine.Beep.reportProgress"),
			patch("polyglot.services.engine.time.sleep"),
		):
			result = self.engine.translate(text, "auto", "en", {})

		self.assertEqual(result["translation"], text)
		self.assertEqual(translateChunk.call_count, 2)
		self.assertEqual(
			[len(call.args[0].encode("utf-16-le")) // 2 for call in translateChunk.call_args_list],
			[1500, 2],
		)

	def test_matchesOnlyBaseDetectionForRegionalTargets(self) -> None:
		"""Base detection matches a regional target without merging dialects."""
		self.assertTrue(self.engine.areLanguagesEquivalent("en", "en-US"))
		self.assertTrue(self.engine.areLanguagesEquivalent("zh", "zh-Hans"))
		self.assertFalse(self.engine.areLanguagesEquivalent("pt-BR", "pt-PT"))
		self.assertFalse(self.engine.areLanguagesEquivalent("zh-Hans", "zh-Hant"))

	def test_exposesWebLanguageVariants(self) -> None:
		"""The language list includes supported regional and Chinese variants."""
		languages = self.engine.getSupportedLanguages()

		for code in ("en-US", "en-GB", "es-419", "pt-BR", "pt-PT", "zh-Hans", "zh-Hant"):
			with self.subTest(code=code):
				self.assertIn(code, languages)

	def test_parsesTranslationAndDetectedLanguage(self) -> None:
		"""The common result contains text and the detected source code."""
		responseBody = json.dumps(
			{"translations": [{"detected_source_language": "en", "text": "Hallo"}]},
		)

		self.assertEqual(
			self.engine._parseResponse(responseBody),
			{"translation": "Hallo", "langDetected": "en"},
		)

	def test_rejectsMissingTranslation(self) -> None:
		"""Malformed successful responses become user-facing API errors."""
		with self.assertRaises(ApiResponseError):
			self.engine._parseResponse('{"translations": []}')

	def test_usesSharedBaseHttpRequestFlow(self) -> None:
		"""Translation uses the existing HTTP flow and response parser."""
		responseBody = '{"translations":[{"text":"Hallo"}]}'
		with patch("polyglot.services.engine.sendRequest", return_value=responseBody) as sendRequest:
			result = self.engine._translateChunk("hello", "auto", "de", {"proxyMode": "none", "timeout": 15})

		sendRequest.assert_called_once()
		self.assertEqual(result, {"translation": "Hallo", "langDetected": None})
		self.assertEqual(sendRequest.call_args.kwargs["proxies"], {"http": None, "https": None})


if __name__ == "__main__":
	unittest.main()
