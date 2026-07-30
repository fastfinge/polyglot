# -*- coding: utf-8 -*-

# Copyright (C) 2025-2026 cary-rowen <manchen_0528@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

import hashlib
import json
import os
from typing import Any, Self  # Self is available in Python 3.11+

import globalVars
from logHandler import log


class TranslationCache:
	"""Provides a simple, persistent cache for translation results. Implemented as a singleton."""

	_instance: Self | None = None

	cachePath: str
	maxSize: int
	_cache: dict[str, str]
	_isInitialized: bool

	def __new__(cls, *args: Any, **kwargs: Any) -> Self:
		"""Return the process-wide translation cache instance."""
		if not cls._instance:
			cls._instance = super().__new__(cls)
		return cls._instance

	def __init__(self, filename: str = "translation_cache.json", maxSize: int = 10000) -> None:
		"""Initialize the singleton cache from NVDA's configuration directory."""
		super().__init__()
		if hasattr(self, "_isInitialized"):
			return
		configPath = globalVars.appArgs.configPath
		self.cachePath = os.path.join(configPath, filename)
		self.maxSize = maxSize
		self._cache = self._load()
		self._isInitialized = True
		log.debug("Translation cache initialized with %d items.", len(self._cache))

	def _load(self) -> dict[str, str]:
		try:
			if os.path.exists(self.cachePath):
				with open(self.cachePath, "r", encoding="utf-8") as f:
					loadedData = json.load(f)
					if isinstance(loadedData, dict):
						return loadedData
		except (IOError, json.JSONDecodeError):
			log.error("Failed to load the translation cache.", exc_info=True)
		return {}

	def _save(self) -> None:
		try:
			if len(self._cache) > self.maxSize:
				keysToDelete = list(self._cache.keys())[: len(self._cache) - self.maxSize]
				for key in keysToDelete:
					del self._cache[key]
				log.debug("Translation cache pruned %d items.", len(keysToDelete))
			with open(self.cachePath, "w", encoding="utf-8") as f:
				json.dump(self._cache, f, ensure_ascii=False, indent=2)
		except IOError:
			log.error("Failed to save the translation cache.", exc_info=True)

	def buildKey(self, langFrom: str, langTo: str, text: str) -> str:
		"""Generate a cache key from the language pair and normalized text."""
		# Normalize text by stripping whitespace to improve the cache hit rate.
		normalizedText = text.strip()
		keyString = f"{langFrom}:{langTo}:{normalizedText}"
		return hashlib.md5(keyString.encode("utf-8")).hexdigest()

	def get(self, key: str) -> str | None:
		"""Return a cached translation, or None when the key is absent."""
		return self._cache.get(key)

	def set(self, key: str, value: str) -> None:
		"""Store a translation result and persist the cache."""
		self._cache[key] = value
		self._save()

	def getItemCount(self) -> int:
		"""Return the number of cached entries."""
		return len(self._cache)

	def clear(self) -> None:
		"""Remove all entries and persist the empty cache."""
		log.debug("Translation cache cleared.")
		self._cache = {}
		self._save()
