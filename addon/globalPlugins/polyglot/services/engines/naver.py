# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Translate through the translator behind Naver's search bar.

Naver's search results page carries a translator widget, and this engine talks to the endpoint that
widget calls. It is Naver's Papago translation, which is the strongest of the key-free engines for
Korean in either direction, and it needs no account and no API key.

The endpoint will not answer without a "passport key", a short-lived token the search page hands out.
The key is scraped once, kept for as long as it lasts, and fetched again when Naver refuses it, so a
translation costs one request in the ordinary case.
"""

import json
import re
import threading
import time
import urllib.parse
from typing import Any

import addonHandler
from logHandler import log

from ...common import languages
from ...common.exceptions import ApiResponseError
from ...common.network import sendRequest
from ..engine import BaseHttpEngine

addonHandler.initTranslation()


class _PassportKeyRejectedError(ApiResponseError):
	"""Naver refused the passport key a request carried, so a new one has to be fetched.

	This is internal to :class:`NaverTranslateEngine`, which catches it and translates again. It
	derives from :class:`ApiResponseError` so that the base class's request wrapper passes it through
	untouched rather than folding it into a generic engine failure.
	"""


class NaverTranslateEngine(BaseHttpEngine):
	"""Translate text with the Papago endpoint behind Naver's search-bar translator."""

	id = "naver"
	# Translators: Name of the key-free Naver Papago translation engine.
	name = _("Naver Papago (key-free)")

	#: The endpoint the search page's translator widget calls. It is not a documented API and carries
	#: no service guarantee; Naver's own Papago API is what to buy when guarantees are needed.
	API_URL = "https://m.search.naver.com/p/csearch/ocontent/util/nmtProxy.naver"

	#: Naver's results for the search "번역기" (translator), the page whose translator widget is handed
	#: a passport key. Other search pages carry one too, but this is the one the widget belongs to.
	PASSPORT_PAGE_URL = "https://search.naver.com/search.naver?where=nexearch&sm=top_hty&fbm=1&ie=utf8&query=%EB%B2%88%EC%97%AD%EA%B8%B0"

	#: Matches the passport key where the search page writes it into the widget's own request.
	_PASSPORT_PATTERN = re.compile(r"passportKey=([A-Za-z0-9%]+)")

	#: How long a scraped key is reused before being fetched again, in seconds. Naver does not say how
	#: long a key lasts, so this only keeps an obviously stale one from being tried; a key refused
	#: before it runs out is replaced on the spot.
	_PASSPORT_LIFETIME = 1800.0

	#: The part of Naver's "not a valid key" answer this matches on. Only the "valid key" wording is
	#: matched, so a change to the words around it does not stop the key from being renewed.
	_REJECTED_KEY_MARKER = "유효한 키"

	_passportLock: threading.Lock
	_passportKey: str | None
	_passportKeyFetchedAt: float

	def __init__(self) -> None:
		"""Start with no passport key; one is fetched with the first translation."""
		super().__init__()
		self._passportLock = threading.Lock()
		self._passportKey = None
		self._passportKeyFetchedAt = 0.0

	@property
	def maxRequestLength(self) -> int:
		"""Return the amount of text sent at once.

		Measured against the endpoint: 5,000 characters are translated in full and 8,000 are refused.
		The limit counts characters rather than bytes, so Korean and Japanese text reaches it at the
		same length as English.
		"""
		return 5000

	@property
	def autoDetectCode(self) -> str | None:
		return "auto"

	@property
	def defaultTargetLanguage(self) -> str:
		"""Return Korean, the language this engine is worth choosing for."""
		return "ko"

	def getSupportedLanguages(self) -> dict[str, str]:
		"""Return the languages the endpoint accepts, which are fewer than Papago's own list."""
		return languages.getLanguageDictForCodes(
			[
				"auto",
				"ko",
				"en",
				"ja",
				"zh-CN",
				"zh-TW",
				"vi",
				"id",
				"th",
				"de",
				"ru",
				"es",
				"it",
				"fr",
				"pt",
				"hi",
				"ar",
			],
		)

	def _forgetPassportKey(self) -> None:
		"""Discard the stored passport key so the next request scrapes a new one.

		The key is dropped whichever request was refused, rather than only the one that used it: the
		worst that costs is one extra page fetch, and working out whose key was refused would mean
		threading it back out of a response this class does not otherwise care about.
		"""
		with self._passportLock:
			self._passportKey = None
			self._passportKeyFetchedAt = 0.0

	def _getPassportKey(self, config: dict[str, Any]) -> str:
		"""Return a passport key, scraping the search page when there is no usable one.

		The lock is held across the fetch, so the several requests a long text is split into do not
		each scrape the search page when none of them finds a key waiting.
		"""
		with self._passportLock:
			key = self._passportKey
			isFresh = time.monotonic() - self._passportKeyFetchedAt < self._PASSPORT_LIFETIME
			if key is not None and isFresh:
				return key
			key = self._fetchPassportKey(config)
			self._passportKey = key
			self._passportKeyFetchedAt = time.monotonic()
			return key

	def _fetchPassportKey(self, config: dict[str, Any]) -> str:
		"""Scrape a passport key from Naver's search page.

		:raises ApiResponseError: If the page holds no key, which is what a change to Naver's search
			page would look like from here.
		"""
		log.debug("Fetching a Naver passport key.")
		page = sendRequest(
			method="GET",
			url=self.PASSPORT_PAGE_URL,
			timeout=int(config.get("timeout", 15)),
			proxies=self._getProxies(config),
		)
		match = self._PASSPORT_PATTERN.search(page)
		if match is None:
			raise ApiResponseError(
				# Translators: Reported when Naver's search page no longer hands out the key its
				# translator needs.
				_("Naver's search page did not hand out the key its translator needs."),
			)
		return urllib.parse.unquote(match.group(1))

	def _buildRequestParams(
		self,
		text: str,
		langFrom: str,
		langTo: str,
		config: dict[str, Any],
	) -> dict[str, Any]:
		formData = {
			"passportKey": self._getPassportKey(config),
			"query": text,
			"srcLang": langFrom or self.autoDetectCode,
			"tarLang": langTo,
		}
		return {
			# Sent as a form body rather than in the query string: the same text in a URL is refused
			# with "413 Request Entity Too Large" well below the endpoint's own length limit.
			"method": "POST",
			"url": self.API_URL,
			"headers": {
				"Content-Type": "application/x-www-form-urlencoded",
				# The endpoint serves the search page's translator, so the request is made to look
				# like it came from there.
				"Referer": "https://search.naver.com/",
			},
			"data": urllib.parse.urlencode(formData).encode("utf-8"),
		}

	def _parseResponse(self, responseBody: str) -> dict[str, Any]:
		data = json.loads(responseBody)
		message = data.get("message") if isinstance(data, dict) else None
		if not isinstance(message, dict):
			raise ApiResponseError(_("Naver's translator returned an unexpected response."))
		error = message.get("error")
		if error:
			errorText = str(error)
			if self._REJECTED_KEY_MARKER in errorText:
				raise _PassportKeyRejectedError(errorText)
			# Naver answers in Korean, and says no more than that something went wrong. It is still
			# what the service said, so it is passed on rather than replaced with a guess.
			raise ApiResponseError(
				# Translators: Reported when Naver's translator refuses a request. {details} is the
				# message Naver returned, which is in Korean.
				_("Naver's translator returned an error: {details}").format(details=errorText),
			)
		result = message.get("result")
		translation = result.get("translatedText") if isinstance(result, dict) else None
		if translation is None:
			raise ApiResponseError(_("Naver's translator returned no translation."))
		detectedLanguage = result.get("srcLangType")
		return {
			"translation": str(translation),
			"langDetected": str(detectedLanguage) if detectedLanguage else None,
		}

	def _translateChunk(
		self,
		text: str,
		langFrom: str,
		langTo: str,
		config: dict[str, Any],
	) -> dict[str, Any]:
		"""Translate one chunk, renewing the passport key once when Naver refuses the one used.

		A key that has run out is the one failure this engine can put right by itself, and running
		out is the expected end of every key, so it costs a second attempt rather than a translation.
		"""
		try:
			return super()._translateChunk(text, langFrom, langTo, config)
		except _PassportKeyRejectedError:
			log.debug("Naver refused its passport key; fetching a new one and translating again.")
			self._forgetPassportKey()
		try:
			return super()._translateChunk(text, langFrom, langTo, config)
		except _PassportKeyRejectedError as e:
			raise ApiResponseError(
				# Translators: Reported when Naver keeps refusing the key Polyglot fetched for it.
				_("Naver's translator refused the key Polyglot obtained from its search page."),
			) from e
