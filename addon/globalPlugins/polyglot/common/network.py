# -*- coding: utf-8 -*-

# Copyright (C) 2025-2026 cary-rowen <manchen_0528@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

import functools
import time
from collections.abc import Callable

# Best practice: Import advanced typing tools for creating robust decorators and `cast`.
from typing import Any, ParamSpec, TypeVar, cast

import addonHandler
import requests
from logHandler import log

from .exceptions import ApiResponseError, AuthenticationError, NetworkConnectionError

addonHandler.initTranslation()

# Best practice: Use ParamSpec and TypeVar to create a generic decorator.
P = ParamSpec("P")
R = TypeVar("R")


def retryOnNetworkError(
	attempts: int = 3,
	delay: float = 0.5,
	backoff: float = 1.5,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
	"""
	Retry decorated `requests` calls after transient network and HTTP failures.
	It handles not only pure network errors (e.g., timeouts) but also recoverable API errors
	(e.g., 408, 429, and 5xx HTTP status codes).
	"""

	def decorator(func: Callable[P, R]) -> Callable[P, R]:
		@functools.wraps(func)
		def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
			currentDelay = delay
			lastException: Exception | None = None
			for attempt in range(attempts):
				try:
					return func(*args, **kwargs)
				# Catch pure network-level errors.
				except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
					lastException = e
					logMessagePrefix = (
						f"Network error on attempt {attempt + 1}/{attempts} for {func.__name__}"
					)
				# Catch all HTTP errors and determine internally if they are retryable.
				except requests.exceptions.HTTPError as e:
					statusCode = e.response.status_code
					# Define which HTTP status codes are retryable.
					retryableStatusCodes = {408, 429}  # 408: Request Time-out, 429: Too Many Requests
					if statusCode >= 500 or statusCode in retryableStatusCodes:
						# If it's a retryable error, log it and prepare for the next loop.
						lastException = e
						logMessagePrefix = f"Retryable HTTP {statusCode} on attempt {attempt + 1}/{attempts} for {func.__name__}"
					else:
						# If it's a non-retryable HTTP error (e.g., 400, 403), stop trying and re-raise immediately.
						# sendRequest will then catch this exception and wrap it in our custom type.
						raise e
				# If this is the last attempt, break the loop to prepare for the final wrapped exception.
				if attempt + 1 >= attempts:
					log.error(
						"%s failed after %d attempts (%s).",
						func.__name__,
						attempts,
						type(lastException).__name__,
					)
					break
				# Log a warning and wait for the next retry.
				log.warning("%s. Retrying in %.1fs...", logMessagePrefix, currentDelay)
				time.sleep(currentDelay)
				currentDelay *= backoff
			# After all retries fail, wrap the last caught exception into our own user-friendly exception type.
			assert lastException is not None
			if isinstance(lastException, requests.exceptions.HTTPError):
				raise ApiResponseError(
					_(
						"Service temporarily unavailable or timed out. Please try again later. (HTTP {code})",
					).format(code=lastException.response.status_code),
				) from None
			elif isinstance(lastException, requests.exceptions.Timeout):
				raise NetworkConnectionError(
					_("Request to translation service timed out"),
				) from None
			else:
				# Translators: Error message for generic network connection failures. {error} is the detailed error description.
				raise NetworkConnectionError(
					_("Network connection error. Check your connection and try again."),
				) from None

		return wrapper

	return decorator


@retryOnNetworkError()
def sendRequest(
	method: str,
	url: str,
	headers: dict[str, str] | None = None,
	data: bytes | None = None,
	timeout: int = 15,
	proxies: dict[str, str | None] | None = None,
) -> str:
	"""
	Send one HTTP(S) request using `requests`.
	This function is protected by the `@retryOnNetworkError` decorator
	and is only responsible for a single request attempt and handling non-retryable business errors.
	"""
	finalHeaders = headers.copy() if headers else {}
	if "User-Agent" not in finalHeaders:
		finalHeaders["User-Agent"] = "Mozilla/5.0"
	try:
		response = requests.request(
			method=method,
			url=url,
			headers=finalHeaders,
			data=data,
			timeout=timeout,
			proxies=cast(Any, proxies),
		)
		# Let requests raise an HTTPError for any 4xx or 5xx response.
		# Our decorator will then catch this exception and decide whether to retry.
		response.raise_for_status()
		return response.text
	except requests.exceptions.HTTPError as e:
		# This try-except block now only handles HTTP errors that the decorator has decided not to retry.
		log.error("Translation service returned non-retryable HTTP status %d.", e.response.status_code)
		statusCode = e.response.status_code
		if statusCode == 403:
			raise AuthenticationError(_("Authentication failed. Please check your API key.")) from None
		if statusCode == 456:
			raise ApiResponseError(_("Monthly translation quota has been reached.")) from None
		# For all other non-retryable 4xx errors.
		errorDetails = e.response.text[:200]
		# Translators: Error message for HTTP failures. {code} is the HTTP status code, {reason} is the status message, and {details} is the error body.
		raise ApiResponseError(
			_("Service returned an error: {code} {reason}. Details: {details}").format(
				code=statusCode,
				reason=e.response.reason,
				details=errorDetails,
			),
		) from None
