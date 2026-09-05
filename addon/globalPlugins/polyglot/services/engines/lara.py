# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Translate through Lara, Translated's context-aware translation service.

Lara is a paid service from Translated, the company behind MyMemory and ModernMT. It is a
translation-specialized model rather than a general-purpose one, so it answers about as quickly as
the other online engines.

Lara publishes SDKs rather than an API, and says a REST API is available on request. What its SDKs
speak is the protocol implemented here, read from Translated's own MIT-licensed Python SDK: an access
key is exchanged for a short-lived token, which is then carried by each translation. Nothing about
that exchange is guaranteed to stay as it is, so this engine is written to fail with a clear message
rather than to assume it holds.
"""

import base64
import hashlib
import hmac
import json
import re
import threading
import time
from email.utils import formatdate
from typing import Any

import addonHandler
from logHandler import log

from ...common import languages
from ...common.exceptions import ApiResponseError, AuthenticationError
from ...common.network import sendRequest
from ..engine import BaseHttpEngine

addonHandler.initTranslation()

#: Polyglot's language codes mapped to the ones Lara uses. Lara names a locale rather than a language,
#: and documents a default locale for only a handful of the bare codes, so every code offered here is
#: written out in full. Where a language has several locales, the one chosen is the widest spoken.
_LANGUAGE_CODES = {
	"en": "en-US",
	"en-US": "en-US",
	"en-GB": "en-GB",
	"es": "es-ES",
	"es-419": "es-419",
	"fr": "fr-FR",
	"de": "de-DE",
	"it": "it-IT",
	"pt": "pt-PT",
	"pt-PT": "pt-PT",
	"pt-BR": "pt-BR",
	"nl": "nl-NL",
	"ru": "ru-RU",
	"pl": "pl-PL",
	"uk": "uk-UA",
	"cs": "cs-CZ",
	"sk": "sk-SK",
	"hu": "hu-HU",
	"ro": "ro-RO",
	"bg": "bg-BG",
	"el": "el-GR",
	"da": "da-DK",
	"fi": "fi-FI",
	"sv": "sv-SE",
	"nb": "nb-NO",
	"is": "is-IS",
	"ga": "ga-IE",
	"cy": "cy-GB",
	"gd": "gd-GB",
	"mt": "mt-MT",
	"lb": "lb-LU",
	"et": "et-EE",
	"lv": "lv-LV",
	"lt": "lt-LT",
	"sl": "sl-SI",
	"hr": "hr-HR",
	"bs": "bs-BA",
	# Lara offers Serbian in both scripts; Cyrillic is the official one.
	"sr": "sr-Cyrl-RS",
	"mk": "mk-MK",
	"sq": "sq-AL",
	"be": "be-BY",
	"eu": "eu-ES",
	"ca": "ca-ES",
	"gl": "gl-ES",
	"eo": "eo-EU",
	"la": "la-VA",
	"zh": "zh-CN",
	"zh-CN": "zh-CN",
	"zh-TW": "zh-TW",
	"zh-HK": "zh-HK",
	"ja": "ja-JP",
	"ko": "ko-KR",
	"th": "th-TH",
	"vi": "vi-VN",
	"id": "id-ID",
	"ms": "ms-MY",
	"tl": "tl-PH",
	"ceb": "ceb-PH",
	"my": "my-MM",
	"km": "km-KH",
	"lo": "lo-LA",
	"jw": "jv-ID",
	"su": "su-ID",
	"hi": "hi-IN",
	"bn": "bn-BD",
	"pa": "pa-IN",
	"gu": "gu-IN",
	"mr": "mr-IN",
	"ta": "ta-IN",
	"te": "te-IN",
	"kn": "kn-IN",
	"ml": "ml-IN",
	"si": "si-LK",
	"ne": "ne-NP",
	"sd": "sd-PK",
	"fa": "fa-IR",
	"he": "he-IL",
	"ar": "ar-SA",
	"tr": "tr-TR",
	"az": "az-AZ",
	"hy": "hy-AM",
	"ka": "ka-GE",
	"uz": "uzn-UZ",
	"kk": "kk-KZ",
	"ky": "ky-KG",
	"tg": "tg-TJ",
	"ur": "ur-PK",
	"ps": "ps-PK",
	# Lara offers Northern (Kurmanji) and Central (Sorani) Kurdish separately; Kurmanji is the wider.
	"ku": "kmr-TR",
	"mn": "mn-MN",
	"af": "af-ZA",
	"am": "am-ET",
	"sw": "sw-KE",
	"so": "so-SO",
	"ha": "ha-NE",
	"yo": "yo-NG",
	"ig": "ig-NG",
	"zu": "zu-ZA",
	"xh": "xh-ZA",
	"st": "st-LS",
	"sn": "sn-ZW",
	"mg": "mg-MG",
	"ny": "ny-MW",
	"mi": "mi-NZ",
	"sm": "sm-WS",
	"ht": "ht-HT",
	"yi": "ydd-US",
}

#: Lara's codes mapped back to Polyglot's, for reporting the language Lara says it detected. The table
#: above is read backwards, so that where several of Polyglot's codes name one of Lara's, the first of
#: them wins: that is the plain code rather than a regional one.
_DETECTED_LANGUAGE_CODES = {
	laraCode: polyglotCode for polyglotCode, laraCode in reversed(list(_LANGUAGE_CODES.items()))
}


class LaraEngine(BaseHttpEngine):
	"""Translate text with Lara, exchanging an access key for a short-lived token."""

	id = "lara"
	name = _("Lara Translate")

	#: Where Lara answers. Translated runs no other host for this, so it is not configurable.
	API_BASE_URL = "https://api.laratranslate.com"

	#: Path that exchanges a signed access key for a token.
	_AUTH_PATH = "/v2/auth"

	#: Path that translates.
	_TRANSLATE_PATH = "/v2/translate"

	#: Content type of both requests, and part of what the access key signs.
	_CONTENT_TYPE = "application/json"

	#: How long before a token's stated expiry it is replaced, in seconds. A token that expires while
	#: a request is in flight is refused, and the margin is what keeps that from happening.
	_EXPIRY_MARGIN = 30.0

	#: How long a token whose expiry cannot be read is used for, in seconds. Lara states an expiry in
	#: every token it issues, so this only covers a token in a shape this engine does not recognise.
	_ASSUMED_TOKEN_LIFETIME = 300.0

	#: Matches the status code the shared request wrapper writes into the message of a refused
	#: request. Lara answers 401 to a token it will not accept, which is the one failure this engine
	#: can put right by itself.
	_UNAUTHORIZED_PATTERN = re.compile(r"\b401\b")

	_tokenLock: threading.Lock
	_token: str | None
	_tokenExpiry: float
	_tokenKeyId: str | None

	def __init__(self) -> None:
		"""Start with no token; one is obtained with the first translation."""
		super().__init__()
		self._tokenLock = threading.Lock()
		self._token = None
		self._tokenExpiry = 0.0
		self._tokenKeyId = None

	@property
	def autoDetectCode(self) -> str | None:
		return "auto"

	@property
	def defaultTargetLanguage(self) -> str:
		return "en"

	@property
	def maxRequestLength(self) -> int:
		"""Return the amount of text sent at once.

		Lara documents no limit and this has not been measured against the service, so the figure is
		a cautious one. Lara translates with the surrounding sentences in mind, so raising it once
		the real limit is known would improve the translation as well as save requests.
		"""
		return 2000

	def getSupportedLanguages(self) -> dict[str, str]:
		"""Return the languages Lara translates, under the codes Polyglot names them by."""
		return languages.getLanguageDictForCodes(["auto", *_LANGUAGE_CODES])

	def areLanguagesEquivalent(self, detectedLanguage: str, targetLanguage: str) -> bool:
		"""Treat an unqualified detected code as equivalent to its regional target.

		Lara answers with a locale, such as ``en-US``, which is reported back under whichever of
		Polyglot's codes names it. That is usually the plain code, which is a match for a regional
		target of the same language. Two regional codes are only a match for each other when they
		are the same one, so Brazilian and European Portuguese stay distinct.
		"""
		if detectedLanguage.casefold() == targetLanguage.casefold():
			return True
		return "-" not in detectedLanguage and languages.getLanguageFamily(
			detectedLanguage,
		) == languages.getLanguageFamily(targetLanguage)

	def getConfigSpec(self) -> list[dict[str, Any]]:
		spec = super().getConfigSpec()
		spec.extend(
			[
				{
					"id": "accessKeyId",
					"label": _("Access key ID:"),
					"type": "text",
					"default": "",
				},
				{
					"id": "accessKeySecret",
					"label": _("Access key secret:"),
					"type": "password",
					"default": "",
				},
			],
		)
		return spec

	@staticmethod
	def _getCredentials(config: dict[str, Any]) -> tuple[str, str]:
		"""Return the configured access key ID and secret.

		:raises AuthenticationError: If either half of the access key is missing.
		"""
		keyId = str(config.get("accessKeyId", "")).strip()
		secret = str(config.get("accessKeySecret", "")).strip()
		if not keyId or not secret:
			raise AuthenticationError(
				# Translators: Reported when the Lara engine has no access key to authenticate with.
				_("A Lara access key ID and access key secret must both be provided."),
			)
		return keyId, secret

	@classmethod
	def _isUnauthorized(cls, error: Exception) -> bool:
		"""Return whether a failed request was refused as unauthorised.

		The shared request wrapper reports an HTTP status rather than raising a distinct exception
		for each one, so the status is read back out of the message it built.
		"""
		return cls._UNAUTHORIZED_PATTERN.search(str(error)) is not None

	@classmethod
	def _getTokenExpiry(cls, token: str) -> float:
		"""Return the time at which a token should be replaced.

		Lara issues a JSON Web Token, whose middle segment states when it expires. That segment is
		read rather than verified: it only decides when to ask for another token, and Lara itself is
		what refuses one that has run out.
		"""
		assumed = time.time() + cls._ASSUMED_TOKEN_LIFETIME
		segments = token.split(".")
		if len(segments) != 3:
			return assumed
		try:
			payloadSegment = segments[1] + "=" * (-len(segments[1]) % 4)
			payload = json.loads(base64.urlsafe_b64decode(payloadSegment))
			expiry = payload.get("exp") if isinstance(payload, dict) else None
		except Exception:
			log.debug("Could not read the expiry of Lara's token.", exc_info=True)
			return assumed
		if isinstance(expiry, bool) or not isinstance(expiry, (int, float)):
			return assumed
		return float(expiry) - cls._EXPIRY_MARGIN

	def _forgetToken(self) -> None:
		"""Discard the stored token so the next request authenticates again."""
		with self._tokenLock:
			self._token = None
			self._tokenExpiry = 0.0
			self._tokenKeyId = None

	def _getToken(self, config: dict[str, Any]) -> str:
		"""Return a token, authenticating when there is no usable one.

		The lock is held across the exchange, so the several requests a long text is split into do
		not each authenticate when none of them finds a token waiting. A token belongs to the access
		key that obtained it, so changing the key in settings obtains a new one.
		"""
		keyId, secret = self._getCredentials(config)
		with self._tokenLock:
			token = self._token
			if token is not None and self._tokenKeyId == keyId and time.time() < self._tokenExpiry:
				return token
			token = self._authenticate(keyId, secret, config)
			self._token = token
			self._tokenExpiry = self._getTokenExpiry(token)
			self._tokenKeyId = keyId
			return token

	def _authenticate(self, keyId: str, secret: str, config: dict[str, Any]) -> str:
		"""Exchange an access key for a token.

		The access key secret never leaves this computer: it signs a statement of what is being asked
		for, and Lara checks that signature against the key it holds.

		:raises AuthenticationError: If Lara refuses the access key.
		:raises ApiResponseError: If Lara answers with anything other than a token.
		"""
		log.debug("Authenticating with Lara.")
		# Signed exactly as sent, so the body is built once and the same bytes are hashed and posted.
		body = json.dumps({"id": keyId}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
		contentMd5 = base64.b64encode(hashlib.md5(body).digest()).decode("ascii")
		# Lara wants an RFC 1123 date in GMT. `formatdate` writes the day and month in English
		# whatever locale NVDA is running in, which `strftime` would not.
		date = formatdate(usegmt=True)
		challenge = f"POST\n{self._AUTH_PATH}\n{contentMd5}\n{self._CONTENT_TYPE}\n{date}"
		signature = base64.b64encode(
			hmac.new(secret.encode("utf-8"), challenge.encode("utf-8"), hashlib.sha256).digest(),
		).decode("ascii")
		try:
			responseBody = sendRequest(
				method="POST",
				url=f"{self.API_BASE_URL}{self._AUTH_PATH}",
				headers={
					"Authorization": f"Lara:{signature}",
					"X-Lara-Date": date,
					"Content-MD5": contentMd5,
					"Content-Type": self._CONTENT_TYPE,
				},
				data=body,
				timeout=int(config.get("timeout", 15)),
				proxies=self._getProxies(config),
			)
		except ApiResponseError as e:
			# Only a refusal is reported as a key problem. Anything else, a Lara that cannot be
			# reached among it, is passed on as it came so it is not mistaken for a wrong key.
			if isinstance(e, AuthenticationError) or self._isUnauthorized(e):
				raise AuthenticationError(
					# Translators: Reported when Lara will not accept the access key it was given.
					_("Lara did not accept the access key. Check the access key ID and secret."),
				) from e
			raise
		try:
			data = json.loads(responseBody)
		except ValueError as e:
			raise ApiResponseError(_("Lara returned an unexpected response.")) from e
		token = data.get("token") if isinstance(data, dict) else None
		if not token:
			raise ApiResponseError(
				# Translators: Reported when Lara accepts the access key but hands out no token.
				_("Lara did not return a token to translate with."),
			)
		return str(token)

	def _buildRequestParams(
		self,
		text: str,
		langFrom: str,
		langTo: str,
		config: dict[str, Any],
	) -> dict[str, Any]:
		target = _LANGUAGE_CODES.get(langTo)
		if target is None:
			raise ApiResponseError(
				# Translators: Reported when Lara is asked for a target language it does not
				# translate into. {language} is the name of that language.
				_("Lara does not translate into {language}.").format(
					language=languages.getLanguageName(langTo),
				),
			)
		payload: dict[str, Any] = {"q": text, "target": target}
		# Lara detects the source language when none is named, so 'auto' is sent as no source at all.
		if langFrom and langFrom != self.autoDetectCode:
			source = _LANGUAGE_CODES.get(langFrom)
			if source is not None:
				payload["source"] = source
		return {
			"method": "POST",
			"url": f"{self.API_BASE_URL}{self._TRANSLATE_PATH}",
			# No 'Accept' is asked for, and Translated's own SDKs ask for none either: Lara answers a
			# translation as a stream of JSON objects rather than as one, so naming 'application/json'
			# is a way to be refused it.
			"headers": {
				"Authorization": f"Bearer {self._getToken(config)}",
				"Content-Type": self._CONTENT_TYPE,
				# Asks Lara to translate without keeping what it was sent.
				"X-No-Trace": "true",
			},
			"data": json.dumps(payload).encode("utf-8"),
		}

	def _parseResponse(self, responseBody: str) -> dict[str, Any]:
		# Lara answers a translation as a stream of JSON objects, one to a line, each holding more of
		# the result than the last. Only the final line is of interest here.
		lines = [line for line in responseBody.splitlines() if line.strip()]
		if not lines:
			raise ApiResponseError(_("Lara returned an empty response."))
		try:
			data = json.loads(lines[-1])
		except ValueError as e:
			raise ApiResponseError(_("Lara returned an unexpected response.")) from e
		if not isinstance(data, dict):
			raise ApiResponseError(_("Lara returned an unexpected response."))
		# A request Lara answers but will not carry out describes why in the body it returns.
		message = data.get("message")
		if message and "translation" not in data:
			raise ApiResponseError(str(message))
		translation = data.get("translation")
		# A translation comes back as text, or as a list when several pieces were sent at once. Only
		# one piece is ever sent from here, but a list holding it is read rather than refused.
		if isinstance(translation, list):
			translation = "".join(part for part in translation if isinstance(part, str))
		if not isinstance(translation, str):
			raise ApiResponseError(_("Lara returned no translation."))
		sourceLanguage = data.get("source_language")
		detected = None
		if isinstance(sourceLanguage, str) and sourceLanguage:
			detected = _DETECTED_LANGUAGE_CODES.get(sourceLanguage, sourceLanguage)
		return {"translation": translation, "langDetected": detected}

	def _translateChunk(
		self,
		text: str,
		langFrom: str,
		langTo: str,
		config: dict[str, Any],
	) -> dict[str, Any]:
		"""Translate one chunk, authenticating again once when Lara refuses the token used.

		A token is replaced before it expires, so this covers one Lara stops accepting sooner than it
		said it would, which is the one failure this engine can put right by itself.
		"""
		try:
			return super()._translateChunk(text, langFrom, langTo, config)
		except AuthenticationError:
			# Raised for an access key Lara will not accept, which authenticating again cannot mend.
			raise
		except ApiResponseError as e:
			if not self._isUnauthorized(e):
				raise
			log.debug("Lara refused its token; authenticating again and translating again.")
			self._forgetToken()
		return super()._translateChunk(text, langFrom, langTo, config)
