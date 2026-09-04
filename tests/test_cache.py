# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Runnable checks for the persistent translation cache.

The cache writes on a background thread, so the checks that care about writing either give it a
save interval long enough that it cannot fire on its own, or wait a generous multiple of a short one.
"""

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
	sys.path.insert(0, str(TESTS_ROOT))

from nvdaStubs import installNvdaStubs  # noqa: E402

_unused = installNvdaStubs(PROJECT_ROOT)

from polyglot.common import cache as cacheModule  # noqa: E402
from polyglot.common.cache import TranslationCache  # noqa: E402

#: Long enough that the background writer cannot fire during a check that does not want it to.
NEVER = 3600.0


class CacheTestCase(unittest.TestCase):
	"""Give each check its own cache directory and a cache that is not shared with the last one."""

	def setUp(self) -> None:
		directory = tempfile.TemporaryDirectory()
		self.addCleanup(directory.cleanup)
		self.configPath = Path(directory.name)
		appArgs = getattr(sys.modules["globalVars"], "appArgs")
		patcher = patch.object(appArgs, "configPath", str(self.configPath))
		_unused = patcher.start()
		self.addCleanup(patcher.stop)
		self.addCleanup(self._forgetInstance)
		self._forgetInstance()

	def _forgetInstance(self) -> None:
		"""Drop the singleton, so the next cache built is a fresh one in the current directory."""
		instance = TranslationCache._instance
		if instance is not None and getattr(instance, "_isInitialized", False):
			instance.terminate()
		TranslationCache._instance = None

	def makeCache(self, maxSize: int = 10000, saveInterval: float = NEVER) -> TranslationCache:
		"""Return a new cache reading and writing in this check's own directory."""
		self._forgetInstance()
		return TranslationCache(maxSize=maxSize, saveInterval=saveInterval)

	@property
	def cachePath(self) -> Path:
		return self.configPath / cacheModule.CACHE_FILENAME

	def readCacheFile(self) -> dict[str, str]:
		"""Return what is on disk, which is not necessarily what is in memory yet."""
		return json.loads(self.cachePath.read_text(encoding="utf-8"))


class EvictionTest(CacheTestCase):
	"""Check that the cache drops what has gone unused rather than what was stored first."""

	def test_theLeastRecentlyUsedEntryIsEvicted(self) -> None:
		"""An entry still being read is kept even once it is the oldest one stored."""
		cache = self.makeCache(maxSize=3)
		for key in ("a", "b", "c"):
			cache.set(key, key.upper())
		# 'a' is the oldest, but reading it makes it the most recently used.
		self.assertEqual(cache.get("a"), "A")
		cache.set("d", "D")
		self.assertEqual(cache.get("a"), "A")
		self.assertIsNone(cache.get("b"), "the genuinely unused entry should have been evicted")
		self.assertEqual(cache.getItemCount(), 3)

	def test_rewritingAnEntryMakesItRecent(self) -> None:
		"""Storing over an existing entry counts as use, so it does not keep its old position."""
		cache = self.makeCache(maxSize=2)
		cache.set("a", "A")
		cache.set("b", "B")
		cache.set("a", "A2")
		cache.set("c", "C")
		self.assertEqual(cache.get("a"), "A2")
		self.assertIsNone(cache.get("b"))

	def test_theCacheNeverGrowsPastItsLimit(self) -> None:
		"""Eviction happens as entries are stored, so the count is right at once."""
		cache = self.makeCache(maxSize=5)
		for index in range(50):
			cache.set(f"key{index}", f"value{index}")
			self.assertLessEqual(cache.getItemCount(), 5)
		self.assertEqual(cache.getItemCount(), 5)

	def test_aMissingKeyIsNotAHit(self) -> None:
		"""Asking for something never stored returns nothing and stores nothing."""
		cache = self.makeCache()
		self.assertIsNone(cache.get("absent"))
		self.assertEqual(cache.getItemCount(), 0)


class BatchedWritingTest(CacheTestCase):
	"""Check that a run of translations does not rewrite the whole file once per translation."""

	def test_storingDoesNotWriteStraightAway(self) -> None:
		"""Auto-translation stores constantly, so a store must not reach the disk on its own."""
		cache = self.makeCache()
		for index in range(20):
			cache.set(f"key{index}", f"value{index}")
		self.assertFalse(self.cachePath.exists(), "storing should not have written the cache yet")

	def test_terminateWritesWhatIsStillPending(self) -> None:
		"""NVDA shutting down must not throw away the last few seconds of translations."""
		cache = self.makeCache()
		cache.set("key", "value")
		cache.terminate()
		self.assertEqual(self.readCacheFile(), {"key": "value"})

	def test_aBurstCostsOneWrite(self) -> None:
		"""Changes made close together are gathered up and written once."""
		cache = self.makeCache(saveInterval=0.2)
		writes: list[str] = []
		realWriteFile = cache._writeFile

		def recordingWriteFile(contents: str) -> None:
			# Recorded once the write is finished, so a recorded write is one the file already holds.
			realWriteFile(contents)
			writes.append(contents)

		with patch.object(cache, "_writeFile", recordingWriteFile):
			for index in range(20):
				cache.set(f"key{index}", f"value{index}")
			deadline = time.monotonic() + 5.0
			while not writes and time.monotonic() < deadline:
				time.sleep(0.02)
			self.assertEqual(len(writes), 1, "the burst should have been written exactly once")
		self.assertEqual(len(self.readCacheFile()), 20)

	def test_aLateChangeIsWrittenEvenAfterTerminate(self) -> None:
		"""A task still finishing during shutdown has nowhere else to put its result."""
		cache = self.makeCache()
		cache.terminate()
		cache.set("late", "value")
		self.assertEqual(self.readCacheFile(), {"late": "value"})

	def test_terminateWithNothingPendingWritesNothing(self) -> None:
		"""A session that cached nothing should not leave a cache file behind."""
		cache = self.makeCache()
		cache.terminate()
		self.assertFalse(self.cachePath.exists())


class PersistenceTest(CacheTestCase):
	"""Check what survives a restart, and what a damaged file costs."""

	def test_entriesComeBackInRecencyOrder(self) -> None:
		"""The order written is the order eviction will use after a restart."""
		cache = self.makeCache()
		for key in ("a", "b", "c"):
			cache.set(key, key.upper())
		_unused = cache.get("a")
		cache.terminate()
		reloaded = self.makeCache(maxSize=3)
		self.assertEqual(list(reloaded._cache), ["b", "c", "a"])
		reloaded.set("d", "D")
		self.assertIsNone(reloaded.get("b"), "the oldest entry from the previous session goes first")
		self.assertEqual(reloaded.get("a"), "A")

	def test_anUnreadableCacheStartsEmpty(self) -> None:
		"""The cache is disposable, so damage to it costs misses rather than an error."""
		self.cachePath.write_text("{ this is not json", encoding="utf-8")
		cache = self.makeCache()
		self.assertEqual(cache.getItemCount(), 0)

	def test_aCacheOfTheWrongShapeStartsEmpty(self) -> None:
		"""A file holding something other than an object of translations is not usable."""
		self.cachePath.write_text('["not", "an", "object"]', encoding="utf-8")
		cache = self.makeCache()
		self.assertEqual(cache.getItemCount(), 0)

	def test_entriesThatAreNotTranslationsAreDropped(self) -> None:
		"""A hand-edited file must not put values into the cache that cannot be spoken."""
		self.cachePath.write_text('{"good": "value", "bad": 42, "worse": null}', encoding="utf-8")
		cache = self.makeCache()
		self.assertEqual(cache.getItemCount(), 1)
		self.assertEqual(cache.get("good"), "value")

	def test_aFailedWriteLeavesTheOldCacheIntact(self) -> None:
		"""A cache is replaced in one step, so an interrupted write cannot destroy the last one."""
		cache = self.makeCache()
		cache.set("first", "value")
		cache.terminate()
		later = self.makeCache()
		later.set("second", "value")
		with patch.object(cacheModule.os, "replace", side_effect=OSError("disk full")):
			later.terminate()
		self.assertEqual(self.readCacheFile(), {"first": "value"})
		self.assertFalse(
			(self.configPath / (cacheModule.CACHE_FILENAME + ".tmp")).exists(),
			"a failed write should not leave its half-written file behind",
		)


class ClearTest(CacheTestCase):
	"""Check that clearing the cache actually gets rid of it."""

	def test_clearingWritesAtOnce(self) -> None:
		"""A user clearing the cache expects it gone now, not in ten seconds' time."""
		cache = self.makeCache()
		cache.set("key", "value")
		cache.terminate()
		later = self.makeCache()
		self.assertEqual(later.getItemCount(), 1)
		later.clear()
		self.assertEqual(self.readCacheFile(), {})
		self.assertEqual(later.getItemCount(), 0)

	def test_clearingSurvivesARestart(self) -> None:
		"""What was cleared must not come back when NVDA next starts."""
		cache = self.makeCache()
		cache.set("key", "value")
		cache.clear()
		cache.terminate()
		self.assertEqual(self.makeCache().getItemCount(), 0)


class ThreadSafetyTest(CacheTestCase):
	"""Check that concurrent translation tasks cannot damage the cache or each other."""

	def test_concurrentStoresAllArrive(self) -> None:
		"""Several tasks finish at once, and every result must survive the writing going on."""
		cache = self.makeCache(saveInterval=0)
		threadCount, perThread = 8, 50
		barrier = threading.Barrier(threadCount)
		failures: list[BaseException] = []

		def store(threadIndex: int) -> None:
			try:
				_unused = barrier.wait()
				for index in range(perThread):
					key = f"t{threadIndex}k{index}"
					cache.set(key, f"value{index}")
					_unused = cache.get(key)
			except BaseException as error:  # noqa: BLE001 - reported rather than lost in a thread
				failures.append(error)

		threads = [threading.Thread(target=store, args=(index,)) for index in range(threadCount)]
		for thread in threads:
			thread.start()
		for thread in threads:
			thread.join(timeout=30)
		self.assertEqual(failures, [])
		self.assertEqual(cache.getItemCount(), threadCount * perThread)
		cache.terminate()
		self.assertEqual(len(self.readCacheFile()), threadCount * perThread)

	def test_storingWhileShuttingDownIsSafe(self) -> None:
		"""A task finishing as NVDA exits writes for itself while the writer may still be writing."""
		cache = self.makeCache(saveInterval=0)
		stop = threading.Event()
		failures: list[BaseException] = []

		def storeUntilStopped() -> None:
			try:
				index = 0
				while not stop.is_set():
					cache.set(f"key{index}", f"value{index}")
					index += 1
			except BaseException as error:  # noqa: BLE001 - reported rather than lost in a thread
				failures.append(error)

		thread = threading.Thread(target=storeUntilStopped)
		thread.start()
		try:
			time.sleep(0.1)
			cache.terminate()
		finally:
			stop.set()
			thread.join(timeout=30)
		self.assertFalse(thread.is_alive(), "storing during shutdown should not have deadlocked")
		self.assertEqual(failures, [])
		self.assertIsInstance(self.readCacheFile(), dict)


class DeleteCacheFileTest(CacheTestCase):
	"""Check the removal the uninstall clean-up relies on."""

	def test_theCacheIsRemoved(self) -> None:
		cache = self.makeCache()
		cache.set("key", "value")
		cache.terminate()
		self.assertTrue(cacheModule.deleteCacheFile())
		self.assertFalse(self.cachePath.exists())

	def test_aHalfWrittenCacheIsRemovedToo(self) -> None:
		"""An interrupted write can leave a temporary file, which holds translations just the same."""
		temporaryPath = self.configPath / (cacheModule.CACHE_FILENAME + ".tmp")
		temporaryPath.write_text('{"key": "value"}', encoding="utf-8")
		self.assertTrue(cacheModule.deleteCacheFile())
		self.assertFalse(temporaryPath.exists())

	def test_removingWhatIsNotThereIsNotAFailure(self) -> None:
		"""A user who never translated anything has no cache, which is not a problem."""
		self.assertFalse(cacheModule.deleteCacheFile())


if __name__ == "__main__":
	unittest.main()
