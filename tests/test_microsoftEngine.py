# Copyright (C) 2025-2026 cary-rowen <manchen_0528@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Runnable checks for Microsoft's key-free Edge translation endpoint."""

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
from polyglot.services.engines.microsoft import MicrosoftTranslateEngine  # noqa: E402


class MicrosoftTranslateEngineTest(unittest.TestCase):
	"""Check request construction and response parsing for the Edge endpoint."""

	def setUp(self) -> None:
		"""Create the engine and a minimal HTTP configuration."""
		self.engine = MicrosoftTranslateEngine()
		self.config = {"proxyMode": "none", "timeout": 15}

	def test_buildsUnauthenticatedStringArrayRequest(self) -> None:
		"""The endpoint receives a bare string array without an auth header."""
		params = self.engine._buildRequestParams("a &lt; b", "zh-CN", "zh-TW", self.config)

		self.assertEqual(params["method"], "POST")
		self.assertIn(
			"https://edge.microsoft.com/translate/translatetext?from=zh-Hans&to=zh-Hant&isEnterpriseClient=false",
			params["url"],
		)
		self.assertEqual(json.loads(params["data"].decode("utf-8")), ["a &lt; b"])
		self.assertEqual(params["headers"], {"Content-Type": "application/json"})

	def test_usesSharedBaseHttpRequestFlow(self) -> None:
		"""Translation goes through the base class request and retry wrapper."""
		responseBody = '[{"translations":[{"text":"translated"}]}]'
		with patch("polyglot.services.engine.sendRequest", return_value=responseBody) as sendRequest:
			result = self.engine._translateChunk("hello", "", "zh-Hans", self.config)

		sendRequest.assert_called_once()
		self.assertEqual(result, {"translation": "translated", "langDetected": None})
		self.assertEqual(sendRequest.call_args.kwargs["method"], "POST")
		self.assertIn(
			"/translate/translatetext?from=&to=zh-Hans&isEnterpriseClient=false",
			sendRequest.call_args.kwargs["url"],
		)
		self.assertEqual(json.loads(sendRequest.call_args.kwargs["data"].decode("utf-8")), ["hello"])
		self.assertEqual(sendRequest.call_args.kwargs["proxies"], {"http": None, "https": None})

	def test_parsesDetectedLanguageAndPreservesLiteralEntities(self) -> None:
		"""Detected language is retained without interpreting response text as HTML."""
		responseBody = (
			'[{"detectedLanguage":{"language":"en"},'
			'"translations":[{"text":"Compare &lt; B"}]}]'
		)

		self.assertEqual(
			self.engine._parseResponse(responseBody),
			{"translation": "Compare &lt; B", "langDetected": "en"},
		)

	def test_rejectsMalformedResponse(self) -> None:
		"""Unexpected successful responses become a user-facing API error."""
		with self.assertRaises(ApiResponseError):
			self.engine._parseResponse("{}")


if __name__ == "__main__":
	unittest.main()
