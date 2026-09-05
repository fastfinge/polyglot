# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Runnable checks for the Naver engine's passport key handling and API contract."""

import builtins
import sys
import unittest
import urllib.parse
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
from polyglot.services.engines.naver import NaverTranslateEngine  # noqa: E402


#: A passport key written into the search page the way Naver writes it.
SEARCH_PAGE = '<div data-url="/p/csearch/x.naver?passportKey=abc123def456&amp;q=1"></div>'
#: What the endpoint answers when a translation succeeds.
TRANSLATED = (
	'{"message":{"@type":"response","result":{"srcLangType":"en","tarLangType":"ko",'
	'"translatedText":"\\uc548\\ub155"}}}'
)
#: What the endpoint answers when the passport key is missing, stale, or otherwise refused.
KEY_REJECTED = '{"message":{"error":"\\uc720\\ud6a8\\ud55c \\ud0a4\\uac00 \\uc544\\ub2d9\\ub2c8\\ub2e4."}}'


class NaverEngineTest(unittest.TestCase):
	"""Check the passport key the engine scrapes, reuses and renews, and how it reads an answer."""

	def setUp(self) -> None:
		"""Create the engine and a configuration that keeps requests off any proxy."""
		self.engine = NaverTranslateEngine()
		self.config = {"proxyMode": "none", "timeout": 15}

	def test_scrapesThePassportKeyBeforeTranslating(self) -> None:
		"""The search page is fetched first, and its key travels with the translation request."""
		with (
			patch(
				"polyglot.services.engine.sendRequest",
				return_value=TRANSLATED,
			) as translateRequest,
			patch(
				"polyglot.services.engines.naver.sendRequest",
				return_value=SEARCH_PAGE,
			) as pageRequest,
		):
			result = self.engine._translateChunk("hello", "auto", "ko", self.config)

		pageRequest.assert_called_once()
		self.assertEqual(pageRequest.call_args.kwargs["url"], self.engine.PASSPORT_PAGE_URL)
		self.assertEqual(pageRequest.call_args.kwargs["proxies"], {"http": None, "https": None})
		self.assertEqual(result, {"translation": "안녕", "langDetected": "en"})
		body = urllib.parse.parse_qs(translateRequest.call_args.kwargs["data"].decode("utf-8"))
		self.assertEqual(body["passportKey"], ["abc123def456"])
		self.assertEqual(body["query"], ["hello"])
		self.assertEqual(body["srcLang"], ["auto"])
		self.assertEqual(body["tarLang"], ["ko"])

	def test_reusesAScrapedKeyForLaterTranslations(self) -> None:
		"""A translation costs one request once a key is held, rather than two."""
		with (
			patch("polyglot.services.engine.sendRequest", return_value=TRANSLATED),
			patch(
				"polyglot.services.engines.naver.sendRequest",
				return_value=SEARCH_PAGE,
			) as pageRequest,
		):
			_unused = self.engine._translateChunk("hello", "auto", "ko", self.config)
			_unused = self.engine._translateChunk("hello again", "auto", "ko", self.config)

		pageRequest.assert_called_once()

	def test_renewsTheKeyWhenNaverRefusesIt(self) -> None:
		"""A key that has run out costs a second attempt, not a failed translation."""
		with (
			patch(
				"polyglot.services.engine.sendRequest",
				side_effect=[KEY_REJECTED, TRANSLATED],
			),
			patch(
				"polyglot.services.engines.naver.sendRequest",
				return_value=SEARCH_PAGE,
			) as pageRequest,
		):
			result = self.engine._translateChunk("hello", "auto", "ko", self.config)

		self.assertEqual(result["translation"], "안녕")
		self.assertEqual(pageRequest.call_count, 2)

	def test_reportsAKeyThatKeepsBeingRefused(self) -> None:
		"""Renewing the key is tried once; a key refused again is a user-facing failure."""
		with (
			patch("polyglot.services.engine.sendRequest", return_value=KEY_REJECTED),
			patch(
				"polyglot.services.engines.naver.sendRequest",
				return_value=SEARCH_PAGE,
			),
		):
			with self.assertRaises(ApiResponseError):
				_unused = self.engine._translateChunk("hello", "auto", "ko", self.config)

	def test_reportsASearchPageThatHandsOutNoKey(self) -> None:
		"""A change to Naver's search page is reported rather than sent as an empty key."""
		with patch("polyglot.services.engines.naver.sendRequest", return_value="<html></html>"):
			with self.assertRaises(ApiResponseError):
				_unused = self.engine._buildRequestParams("hello", "auto", "ko", self.config)

	def test_sendsTheTextAsAFormBody(self) -> None:
		"""The text travels in the body, which a URL of the same length is too long to carry."""
		with patch("polyglot.services.engines.naver.sendRequest", return_value=SEARCH_PAGE):
			params = self.engine._buildRequestParams("hello", "auto", "ko", self.config)

		self.assertEqual(params["method"], "POST")
		self.assertEqual(params["url"], self.engine.API_URL)
		self.assertEqual(params["headers"]["Content-Type"], "application/x-www-form-urlencoded")
		self.assertNotIn("?", params["url"])

	def test_surfacesTheServicesOwnErrorText(self) -> None:
		"""What Naver says is wrong reaches the user, Korean and all."""
		with self.assertRaises(ApiResponseError) as caught:
			_unused = self.engine._parseResponse('{"message":{"error":"일시적인 오류입니다."}}')

		self.assertIn("일시적인 오류입니다.", str(caught.exception))

	def test_rejectsAResponseWithoutATranslation(self) -> None:
		"""An answer holding no translation becomes a user-facing API error."""
		for responseBody in ('{"message":{"result":{}}}', '{"message":{}}', "{}", "[]"):
			with self.assertRaises(ApiResponseError):
				_unused = self.engine._parseResponse(responseBody)

	def test_offersOnlyTheLanguagesTheEndpointAccepts(self) -> None:
		"""Automatic detection and Naver's own language set are offered, with real names."""
		supported = self.engine.getSupportedLanguages()

		self.assertIn("auto", supported)
		for code in ("ko", "en", "ja", "zh-CN", "zh-TW", "ar"):
			self.assertIn(code, supported)
		# Papago's site lists these, but the search-bar endpoint refuses them.
		for code in ("tr", "nl", "pl", "zh"):
			self.assertNotIn(code, supported)
		self.assertTrue(all(name and name != code for code, name in supported.items()))

	def test_translatesIntoKoreanByDefault(self) -> None:
		"""The engine is worth choosing for Korean, so that is where it starts."""
		self.assertEqual(self.engine.defaultTargetLanguage, "ko")
		self.assertEqual(self.engine.defaultSourceLanguage, "auto")
		self.assertTrue(self.engine.doesReportDetectedLanguage)


if __name__ == "__main__":
	unittest.main()
