# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Persistent cache for translation results.

Translations are kept in memory and written to NVDA's configuration directory by a background writer
that gathers changes for :data:`SAVE_INTERVAL` seconds and writes them once. Auto-translation can
finish a translation for every utterance NVDA speaks, and every result used to rewrite the whole file
on the spot, so a full-sized cache was written to disk several times a second.
:meth:`TranslationCache.terminate` writes whatever is still pending when the add-on is unloaded, so
the last few seconds of translations survive NVDA shutting down.

Entries are evicted least recently used first, so an entry that keeps being read is kept even once it
is one of the oldest. A read reorders the cache in memory but does not by itself schedule a write, so
recency reaches disk with the next real change; losing some of that ordering to a crash costs nothing
but a few cache misses.

The cache is content the user never chose to keep: it records every string translated, which under
auto-translation is much of what NVDA has spoken. Nothing else would clean it up, so it is removed
when the add-on is uninstalled. See :mod:`installTasks`.
"""

import contextlib
import hashlib
import json
import os
import threading
from collections import OrderedDict
from typing import Any, Self  # Self is available in Python 3.11+

import globalVars
from logHandler import log

#: Name of the file the cache is written to, inside NVDA's configuration directory.
CACHE_FILENAME = "translation_cache.json"

#: How long changes are gathered before being written, in seconds. A burst of translations then costs
#: one write rather than one each, and a crash loses at most this much of a cache that is disposable.
SAVE_INTERVAL = 10.0

#: How long :meth:`TranslationCache.terminate` waits for the background writer to stop, in seconds.
_TERMINATE_TIMEOUT = 5.0

#: Suffix of the file a new cache is written to before it replaces the old one.
_TEMPORARY_SUFFIX = ".tmp"


def getCachePath(filename: str = CACHE_FILENAME) -> str:
	"""Return the full path of the translation cache file."""
	return os.path.join(globalVars.appArgs.configPath, filename)


def deleteCacheFile(filename: str = CACHE_FILENAME) -> bool:
	"""Remove the translation cache from disk, with any half-written copy left by a failed write.

	Failures are logged rather than raised, so a file that cannot be removed does not stop the rest of
	the add-on's clean-up.

	:return: Whether a cache file was found and removed.
	"""
	basePath = getCachePath(filename)
	removedAny = False
	for path in (basePath, basePath + _TEMPORARY_SUFFIX):
		try:
			os.remove(path)
		except FileNotFoundError:
			continue
		except OSError:
			log.exception(f"Could not remove the translation cache file '{path}'.")
			continue
		removedAny = True
	return removedAny


class TranslationCache:
	"""Provides a simple, persistent cache for translation results. Implemented as a singleton."""

	_instance: Self | None = None

	cachePath: str
	maxSize: int
	saveInterval: float
	_cache: "OrderedDict[str, str]"
	_lock: threading.RLock
	_writeLock: threading.Lock
	_pendingSave: threading.Event
	_stopping: threading.Event
	_writer: threading.Thread | None
	_isDirty: bool
	_isInitialized: bool

	def __new__(cls, *args: Any, **kwargs: Any) -> Self:
		"""Return the process-wide translation cache instance."""
		if not cls._instance:
			cls._instance = super().__new__(cls)
		return cls._instance

	def __init__(
		self,
		filename: str = CACHE_FILENAME,
		maxSize: int = 10000,
		saveInterval: float = SAVE_INTERVAL,
	) -> None:
		"""Initialize the singleton cache from NVDA's configuration directory."""
		super().__init__()
		if hasattr(self, "_isInitialized"):
			return
		self.cachePath = getCachePath(filename)
		self.maxSize = maxSize
		self.saveInterval = saveInterval
		self._lock = threading.RLock()
		self._writeLock = threading.Lock()
		self._pendingSave = threading.Event()
		self._stopping = threading.Event()
		self._writer = None
		self._isDirty = False
		self._cache = self._load()
		self._isInitialized = True
		log.debug("Translation cache initialized with %d items.", len(self._cache))

	def _load(self) -> "OrderedDict[str, str]":
		"""Read the cache from disk, returning an empty cache when it cannot be read.

		The cache is disposable, so a file that is missing, unreadable, or not the shape this writes
		costs a fresh start rather than an error the user has to do something about.
		"""
		try:
			with open(self.cachePath, "r", encoding="utf-8") as f:
				loadedData = json.load(f, object_pairs_hook=OrderedDict)
		except FileNotFoundError:
			return OrderedDict()
		except (OSError, ValueError):
			log.error("Failed to load the translation cache.", exc_info=True)
			return OrderedDict()
		if not isinstance(loadedData, dict):
			log.error("The translation cache is not in the expected format and has been discarded.")
			return OrderedDict()
		# A hand-edited or half-written file can hold values that cannot be served as translations.
		return OrderedDict((key, value) for key, value in loadedData.items() if isinstance(value, str))

	def _ensureWriterStarted(self) -> None:
		"""Start the background writer, which is not needed until something is cached.

		The caller must hold the lock.
		"""
		if self._writer is not None:
			return
		self._writer = threading.Thread(
			target=self._writeLoop,
			name="PolyglotTranslationCacheWriter",
			daemon=True,
		)
		self._writer.start()

	def _writeLoop(self) -> None:
		"""Write pending changes on a background thread until the cache is terminated."""
		while True:
			self._pendingSave.wait()
			if self._stopping.is_set():
				break
			# Let further translations accumulate, so a burst costs one write rather than one each.
			if self._stopping.wait(self.saveInterval):
				break
			# Cleared before the write, so a change made while it runs schedules another one.
			self._pendingSave.clear()
			self._flush()

	def _markDirty(self) -> bool:
		"""Record that there are changes to write.

		The caller must hold the lock. Writing cannot be done from here: :meth:`_flush` takes the write
		lock, and taking it while holding this one is the opposite of the order the background writer
		uses, which would eventually deadlock the two against each other.

		:return: Whether the caller has to flush the change itself, the writer having stopped.
		"""
		self._isDirty = True
		if self._stopping.is_set():
			# The writer is stopping or gone, so a late change is written by the caller or not at all.
			return True
		self._ensureWriterStarted()
		self._pendingSave.set()
		return False

	def _flush(self) -> None:
		"""Write the cache to disk, doing nothing when it has not changed since the last write.

		The caller must not hold the lock. Both the background writer and a translation finishing
		during shutdown can end up here at the same time, so the whole of taking a copy and writing it
		is done under the write lock: two writers sharing one temporary file could otherwise move a
		half-written copy into place, and the slower of the two could put back what the other replaced.
		"""
		with self._writeLock:
			with self._lock:
				if not self._isDirty:
					return
				# Serialized under the lock, so the cache cannot change while it is being written out.
				contents = json.dumps(self._cache, ensure_ascii=False, indent=2)
				# Cleared before the write so a change made during it is not mistaken for written.
				self._isDirty = False
			try:
				self._writeFile(contents)
			except OSError:
				log.error("Failed to save the translation cache.", exc_info=True)
			else:
				return
		# Marked outside the write lock, which is always taken before the lock, never after.
		with self._lock:
			self._isDirty = True

	def _writeFile(self, contents: str) -> None:
		"""Replace the cache file with the given contents, leaving the old one intact on failure.

		The new cache is written beside the old one and put in its place in a single step, so an
		interrupted write cannot leave a half-written file that the next start would have to discard.
		"""
		temporaryPath = self.cachePath + _TEMPORARY_SUFFIX
		try:
			with open(temporaryPath, "w", encoding="utf-8") as f:
				f.write(contents)
			os.replace(temporaryPath, self.cachePath)
		except OSError:
			with contextlib.suppress(OSError):
				os.remove(temporaryPath)
			raise

	def buildKey(self, langFrom: str, langTo: str, text: str) -> str:
		"""Generate a cache key from the language pair and normalized text."""
		# Normalize text by stripping whitespace to improve the cache hit rate.
		normalizedText = text.strip()
		keyString = f"{langFrom}:{langTo}:{normalizedText}"
		return hashlib.md5(keyString.encode("utf-8")).hexdigest()

	def get(self, key: str) -> str | None:
		"""Return a cached translation, or None when the key is absent.

		A hit counts as recent use, so an entry that goes on being read is not evicted for being old.
		"""
		with self._lock:
			value = self._cache.get(key)
			if value is None:
				return None
			self._cache.move_to_end(key)
			return value

	def set(self, key: str, value: str) -> None:
		"""Store a translation result and schedule it to be written."""
		with self._lock:
			self._cache[key] = value
			self._cache.move_to_end(key)
			self._prune()
			writeHere = self._markDirty()
		if writeHere:
			self._flush()

	def _prune(self) -> None:
		"""Evict least recently used entries until the cache is within its size limit.

		The caller must hold the lock.
		"""
		removedCount = 0
		while len(self._cache) > self.maxSize:
			_unused = self._cache.popitem(last=False)
			removedCount += 1
		if removedCount:
			log.debug("Translation cache pruned %d items.", removedCount)

	def getItemCount(self) -> int:
		"""Return the number of cached entries."""
		with self._lock:
			return len(self._cache)

	def clear(self) -> None:
		"""Remove all entries and write the empty cache out at once.

		Clearing is what a user reaches for to get rid of what has been kept, so it is not left to the
		background writer to do some seconds later.
		"""
		with self._lock:
			self._cache = OrderedDict()
			self._isDirty = True
		self._flush()
		log.debug("Translation cache cleared.")

	def terminate(self) -> None:
		"""Stop the background writer and write whatever is still pending.

		Called when the add-on is unloaded, which includes NVDA shutting down, so the translations of
		the last few seconds are kept. Changes made after this are written as they are made, rather
		than starting a writer that a shutdown would not wait for.
		"""
		self._stopping.set()
		self._pendingSave.set()
		writer = self._writer
		if writer is not None and writer.is_alive():
			writer.join(timeout=_TERMINATE_TIMEOUT)
			if writer.is_alive():
				log.error("The translation cache writer did not stop in time.")
		self._flush()
