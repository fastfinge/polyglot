# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Runnable checks for the Lara engine's access-key exchange, token reuse, and API contract."""

import base64
import builtins
import hashlib
import hmac
import json
import sys
import time
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

from polyglot.common.exceptions import ApiResponseError, AuthenticationError  # noqa: E402
from polyglot.services.engines.lara import LaraEngine  # noqa: E402


def makeToken(expiry: float) -> str:
	"""Return a token shaped like Lara's, stating the given expiry."""

	def segment(payload: dict) -> str:
		encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8"))
		return encoded.decode("ascii").rstrip("=")

	return f"{segment({'alg': 'HS256'})}.{segment({'exp': expiry})}.signature"


class LaraEngineTest(unittest.TestCase):
	"""Check what the engine sends to Lara, and how it reads what comes back."""

	def setUp(self) -> None:
		"""Create the engine and a configuration holding an access key."""
		self.engine = LaraEngine()
		self.config = {
			"proxyMode": "none",
			"timeout": 15,
			"accessKeyId": "key-id",
			"accessKeySecret": "key-secret",
		}
		self.token = makeToken(time.time() + 3600)

	def _getSpecItem(self, itemId: str) -> dict:
		"""Return the configuration specification entry with the given id."""
		for item in self.engine.getConfigSpec():
			if item["id"] == itemId:
				return item
		raise AssertionError(f"No configuration item '{itemId}'.")

	def _authResponse(self, token: str | None = None) -> str:
		"""Return the body Lara answers an accepted access key with."""
		return json.dumps({"token": token or self.token})

	# --- Configuration ---

	def test_accessKeySecretIsStoredAsACredential(self) -> None:
		"""The secret is a credential, so it is kept out of NVDA's configuration file."""
		self.assertEqual(self._getSpecItem("accessKeySecret")["type"], "password")
		self.assertEqual(self._getSpecItem("accessKeyId")["type"], "text")

	def test_shipsNoAccessKey(self) -> None:
		"""Nothing is sent to Lara until the user supplies a key of their own."""
		self.assertEqual(self._getSpecItem("accessKeyId")["default"], "")
		self.assertEqual(self._getSpecItem("accessKeySecret")["default"], "")

	def test_requiresBothHalvesOfTheAccessKey(self) -> None:
		"""A half-configured key is reported before anything is sent."""
		for config in (
			{**self.config, "accessKeyId": "  "},
			{**self.config, "accessKeySecret": ""},
		):
			with self.assertRaises(AuthenticationError):
				self.engine._buildRequestParams("hello", "auto", "it", config)

	# --- Authenticating ---

	def test_signsTheAccessKeyExchangeAsLaraExpects(self) -> None:
		"""The exchange carries the signature, digest, and date Lara checks it against."""
		with patch(
			"polyglot.services.engines.lara.sendRequest",
			return_value=self._authResponse(),
		) as sendRequest:
			token = self.engine._getToken(self.config)

		self.assertEqual(token, self.token)
		kwargs = sendRequest.call_args.kwargs
		self.assertEqual(kwargs["method"], "POST")
		self.assertEqual(kwargs["url"], "https://api.laratranslate.com/v2/auth")
		self.assertEqual(kwargs["proxies"], {"http": None, "https": None})
		# The body is signed exactly as sent, so it must carry no incidental whitespace.
		self.assertEqual(kwargs["data"], b'{"id":"key-id"}')

		headers = kwargs["headers"]
		expectedMd5 = base64.b64encode(hashlib.md5(kwargs["data"]).digest()).decode("ascii")
		self.assertEqual(headers["Content-MD5"], expectedMd5)
		self.assertEqual(headers["Content-Type"], "application/json")
		challenge = f"POST\n/v2/auth\n{expectedMd5}\napplication/json\n{headers['X-Lara-Date']}"
		expectedSignature = base64.b64encode(
			hmac.new(b"key-secret", challenge.encode("utf-8"), hashlib.sha256).digest(),
		).decode("ascii")
		self.assertEqual(headers["Authorization"], f"Lara:{expectedSignature}")

	def test_datesTheExchangeInEnglishAndGmt(self) -> None:
		"""Lara reads an RFC 1123 date, whatever locale NVDA is running in."""
		with patch(
			"polyglot.services.engines.lara.sendRequest",
			return_value=self._authResponse(),
		) as sendRequest:
			self.engine._getToken(self.config)

		date = sendRequest.call_args.kwargs["headers"]["X-Lara-Date"]
		self.assertTrue(date.endswith("GMT"), date)
		self.assertEqual(
			date[:3],
			["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][time.gmtime().tm_wday],
		)

	def test_reportsARefusedAccessKeyAsTheKeyProblemItIs(self) -> None:
		"""A key Lara will not accept is reported as a key to check, not as an unknown error."""
		refused = ApiResponseError("Service returned an error: 401 Unauthorized. Details: nope")
		with patch("polyglot.services.engines.lara.sendRequest", side_effect=refused):
			with self.assertRaises(AuthenticationError):
				self.engine._getToken(self.config)

	def test_passesOnAFailureThatIsNotAboutTheKey(self) -> None:
		"""A service that cannot be reached is not reported as a wrong access key."""
		unavailable = ApiResponseError("Service temporarily unavailable or timed out. (HTTP 503)")
		with patch("polyglot.services.engines.lara.sendRequest", side_effect=unavailable):
			with self.assertRaises(ApiResponseError) as caught:
				self.engine._getToken(self.config)

		self.assertNotIsInstance(caught.exception, AuthenticationError)

	def test_rejectsAnExchangeThatHandsOutNoToken(self) -> None:
		"""An answer holding no token becomes a user-facing API error."""
		for body in ("{}", "[]", "not json"):
			with patch("polyglot.services.engines.lara.sendRequest", return_value=body):
				with self.assertRaises(ApiResponseError):
					self.engine._getToken(self.config)

	# --- Reusing a token ---

	def test_reusesATokenUntilItIsAboutToExpire(self) -> None:
		"""One exchange covers every translation a token's lifetime spans."""
		with patch(
			"polyglot.services.engines.lara.sendRequest",
			return_value=self._authResponse(),
		) as sendRequest:
			self.engine._getToken(self.config)
			self.engine._getToken(self.config)

		sendRequest.assert_called_once()

	def test_authenticatesAgainForAnExpiredToken(self) -> None:
		"""A token Lara has said is finished with is replaced rather than sent."""
		expired = self._authResponse(makeToken(time.time() - 1))
		with patch(
			"polyglot.services.engines.lara.sendRequest",
			side_effect=[expired, self._authResponse()],
		) as sendRequest:
			self.engine._getToken(self.config)
			self.assertEqual(self.engine._getToken(self.config), self.token)

		self.assertEqual(sendRequest.call_count, 2)

	def test_replacesATokenBeforeItsStatedExpiry(self) -> None:
		"""A token is given up while it still has a moment left, not once it has run out."""
		expiry = time.time() + 3600
		self.assertLess(self.engine._getTokenExpiry(makeToken(expiry)), expiry)

	def test_reusesATokenWhoseExpiryCannotBeRead(self) -> None:
		"""A token in an unfamiliar shape is still used, briefly, rather than refused."""
		self.assertGreater(self.engine._getTokenExpiry("not-a-token"), time.time())

	def test_authenticatesAgainForADifferentAccessKey(self) -> None:
		"""A token belongs to the key that obtained it, so a new key obtains a new token."""
		otherToken = makeToken(time.time() + 3600) + "-other"
		with patch(
			"polyglot.services.engines.lara.sendRequest",
			side_effect=[self._authResponse(), self._authResponse(otherToken)],
		):
			self.engine._getToken(self.config)
			token = self.engine._getToken({**self.config, "accessKeyId": "other-key-id"})

		self.assertEqual(token, otherToken)

	# --- Translating ---

	def test_buildsTranslateRequestCarryingTheToken(self) -> None:
		"""The translation carries the token, and asks Lara not to keep the text."""
		with patch.object(self.engine, "_getToken", return_value="the-token"):
			params = self.engine._buildRequestParams("hello", "auto", "it", self.config)

		self.assertEqual(params["method"], "POST")
		self.assertEqual(params["url"], "https://api.laratranslate.com/v2/translate")
		self.assertEqual(params["headers"]["Authorization"], "Bearer the-token")
		self.assertEqual(params["headers"]["X-No-Trace"], "true")
		# 'auto' is sent as no source at all, which is how Lara is asked to detect one.
		self.assertEqual(
			json.loads(params["data"].decode("utf-8")),
			{"q": "hello", "target": "it-IT"},
		)

	def test_namesLanguagesByTheLocaleLaraUses(self) -> None:
		"""Polyglot's plain codes reach Lara as the locales it names languages by."""
		with patch.object(self.engine, "_getToken", return_value="the-token"):
			params = self.engine._buildRequestParams("hello", "en", "pt-BR", self.config)

		self.assertEqual(
			json.loads(params["data"].decode("utf-8")),
			{"q": "hello", "target": "pt-BR", "source": "en-US"},
		)

	def test_rejectsATargetLanguageLaraDoesNotTranslateInto(self) -> None:
		"""A target Lara cannot translate into is reported before anything is sent."""
		with patch.object(self.engine, "_getToken", return_value="the-token"):
			with self.assertRaises(ApiResponseError):
				self.engine._buildRequestParams("hello", "auto", "haw", self.config)

	def test_usesSharedBaseHttpRequestFlow(self) -> None:
		"""Translation goes through the base class request and retry wrapper."""
		responseBody = '{"content_type":"text/plain","source_language":"en-US","translation":"ciao"}'
		with patch.object(self.engine, "_getToken", return_value="the-token"):
			with patch("polyglot.services.engine.sendRequest", return_value=responseBody) as sendRequest:
				result = self.engine._translateChunk("hello", "auto", "it", self.config)

		sendRequest.assert_called_once()
		self.assertEqual(result, {"translation": "ciao", "langDetected": "en"})
		self.assertEqual(
			sendRequest.call_args.kwargs["url"],
			"https://api.laratranslate.com/v2/translate",
		)
		self.assertEqual(sendRequest.call_args.kwargs["proxies"], {"http": None, "https": None})

	# --- Reading Lara's answer ---

	def test_readsTheLastOfTheObjectsLaraStreams(self) -> None:
		"""Lara answers with a line per stage of the translation; the finished one is the last."""
		responseBody = '{"translation":"cia"}\n\n{"translation":"ciao","source_language":"en-US"}\n'

		self.assertEqual(
			self.engine._parseResponse(responseBody),
			{"translation": "ciao", "langDetected": "en"},
		)

	def test_reportsTheDetectedLanguageUnderPolyglotsOwnCode(self) -> None:
		"""A locale Lara detected is reported as the code Polyglot names that language by."""
		self.assertEqual(
			self.engine._parseResponse('{"translation":"ciao","source_language":"pt-BR"}'),
			{"translation": "ciao", "langDetected": "pt-BR"},
		)
		self.assertEqual(
			self.engine._parseResponse('{"translation":"ciao","source_language":"de-DE"}'),
			{"translation": "ciao", "langDetected": "de"},
		)

	def test_passesOnALocaleItDoesNotRecognise(self) -> None:
		"""A language Lara adds is reported as Lara named it rather than dropped."""
		self.assertEqual(
			self.engine._parseResponse('{"translation":"ciao","source_language":"xx-YY"}')["langDetected"],
			"xx-YY",
		)

	def test_readsATranslationReturnedAsAList(self) -> None:
		"""A translation answered as a list of one piece is read rather than refused."""
		self.assertEqual(
			self.engine._parseResponse('{"translation":["ciao"]}'),
			{"translation": "ciao", "langDetected": None},
		)

	def test_surfacesLarasOwnErrorText(self) -> None:
		"""What Lara says is wrong reaches the user unchanged."""
		with self.assertRaises(ApiResponseError) as caught:
			self.engine._parseResponse('{"type":"BadRequest","message":"target is required"}')

		self.assertEqual(str(caught.exception), "target is required")

	def test_rejectsAResponseWithoutATranslation(self) -> None:
		"""An answer holding no translation becomes a user-facing API error."""
		for body in ("", "   ", "[]", "not json", '{"translation":42}'):
			with self.assertRaises(ApiResponseError):
				self.engine._parseResponse(body)

	# --- Recovering from a refused token ---

	def test_authenticatesAgainWhenLaraRefusesItsToken(self) -> None:
		"""A token Lara stops accepting early costs a second attempt, not a translation."""
		refused = ApiResponseError("Service returned an error: 401 Unauthorized. Details: expired")
		translated = '{"translation":"ciao","source_language":"en-US"}'
		with patch(
			"polyglot.services.engines.lara.sendRequest",
			return_value=self._authResponse(),
		) as authRequest:
			with patch(
				"polyglot.services.engine.sendRequest",
				side_effect=[refused, translated],
			) as sendRequest:
				result = self.engine._translateChunk("hello", "auto", "it", self.config)

		self.assertEqual(result["translation"], "ciao")
		self.assertEqual(sendRequest.call_count, 2)
		# The refused token is given up, so the second attempt carries a freshly obtained one.
		self.assertEqual(authRequest.call_count, 2)

	def test_doesNotAuthenticateAgainForAFailureThatIsNotAboutTheToken(self) -> None:
		"""A translation Lara refuses on its merits is not retried, so it is not paid for twice."""
		refused = ApiResponseError("Service returned an error: 400 Bad Request. Details: nope")
		with patch(
			"polyglot.services.engines.lara.sendRequest",
			return_value=self._authResponse(),
		):
			with patch("polyglot.services.engine.sendRequest", side_effect=refused) as sendRequest:
				with self.assertRaises(ApiResponseError):
					self.engine._translateChunk("hello", "auto", "it", self.config)

		sendRequest.assert_called_once()

	# --- Languages ---

	def test_offersAutoDetectionAndLarasLanguages(self) -> None:
		"""Automatic detection and Lara's language set are both offered, with real names."""
		supported = self.engine.getSupportedLanguages()

		self.assertIn("auto", supported)
		for code in ("en", "it", "zh-CN", "pt-BR", "yi"):
			self.assertIn(code, supported)
		self.assertTrue(all(name and name != code for code, name in supported.items()))

	def test_treatsAPlainDetectedCodeAsItsRegionalTarget(self) -> None:
		"""Auto-swap works even though Lara reports a locale and the target may be a plain code."""
		self.assertTrue(self.engine.areLanguagesEquivalent("en", "en-US"))
		self.assertTrue(self.engine.areLanguagesEquivalent("zh", "zh-CN"))
		self.assertTrue(self.engine.areLanguagesEquivalent("pt-BR", "pt-BR"))
		self.assertFalse(self.engine.areLanguagesEquivalent("en", "it"))
		# Two named regions are only a match for each other when they are the same region.
		self.assertFalse(self.engine.areLanguagesEquivalent("pt-BR", "pt-PT"))


if __name__ == "__main__":
	unittest.main()
