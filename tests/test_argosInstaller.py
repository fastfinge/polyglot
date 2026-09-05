# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Runnable checks for installing, updating, and removing Argos models.

Nothing here downloads anything: the archives are built in a temporary directory in the shape the
real ones have, and the download step is replaced with a copy from disk.
"""

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
	sys.path.insert(0, str(TESTS_ROOT))

from nvdaStubs import installNvdaStubs  # noqa: E402

_unused = installNvdaStubs(PROJECT_ROOT)

from polyglot.argosManager import installer as installerModule  # noqa: E402
from polyglot.argosManager.catalog import ArgosCatalog  # noqa: E402
from polyglot.argosManager.installer import ArgosInstaller  # noqa: E402
from polyglot.argosManager.runtime import RuntimeCatalog, getPythonTag  # noqa: E402


def makeEntry(fromCode: str, toCode: str, version: str = "1.9") -> dict[str, object]:
	"""Build one index entry, in the form the Argos index publishes."""
	name = f"translate-{fromCode}_{toCode}-{version.replace('.', '_')}"
	return {
		"code": f"translate-{fromCode}_{toCode}",
		"from_code": fromCode,
		"from_name": fromCode.upper(),
		"to_code": toCode,
		"to_name": toCode.upper(),
		"package_version": version,
		"argos_version": "1.9.0",
		"links": [f"https://argos-net.com/v1/{name}.argosmodel"],
	}


def writePackageArchive(
	path: Path,
	fromCode: str,
	toCode: str,
	version: str = "1.9",
	tokenizerFileName: str = "sentencepiece.model",
) -> None:
	"""Write an archive shaped like a real Argos package."""
	directoryName = f"translate-{fromCode}_{toCode}-{version.replace('.', '_')}"
	metadata = {
		"package_version": version,
		"argos_version": "1.9.0",
		"from_code": fromCode,
		"from_name": fromCode.upper(),
		"to_code": toCode,
		"to_name": toCode.upper(),
	}
	path.parent.mkdir(parents=True, exist_ok=True)
	with zipfile.ZipFile(path, "w") as archive:
		archive.writestr(f"{directoryName}/metadata.json", json.dumps(metadata))
		archive.writestr(f"{directoryName}/{tokenizerFileName}", "not a real tokenizer")
		archive.writestr(f"{directoryName}/model/model.bin", "not a real model")
		archive.writestr(f"{directoryName}/model/config.json", "{}")


class ArgosInstallerTestCase(unittest.TestCase):
	"""Give each check its own Polyglot directory and its own archives to install from."""

	def setUp(self) -> None:
		self._tempDir = tempfile.TemporaryDirectory()
		self.root = Path(self._tempDir.name)
		self.archiveDir = self.root / "archives"
		self.installer = ArgosInstaller(polyglotRoot=self.root / "Polyglot")
		self.catalog = ArgosCatalog.deserialize(
			json.dumps([makeEntry("en", "fr"), makeEntry("fr", "en"), makeEntry("en", "de")]),
		)
		self.progressMessages: list[str] = []
		self.runtimeInstallCalls: list[bool] = []

	def tearDown(self) -> None:
		self._tempDir.cleanup()

	def progress(self, update: object) -> None:
		"""Record progress, the way the model manager records it in its log."""
		self.progressMessages.append(getattr(update, "message", ""))

	def installFromArchives(self, *keys: str, keysToUpdate: set[str] | None = None) -> None:
		"""Apply a selection with downloads served from the local archive directory."""

		def fakeDownload(url: str, destination: Path, expectedSize: int, progress: object) -> None:
			source = self.archiveDir / url.rsplit("/", 1)[-1]
			destination.parent.mkdir(parents=True, exist_ok=True)
			_unused = destination.write_bytes(source.read_bytes())

		def fakeRuntimeInstall(progress: object, withBpeSupport: bool = False) -> None:
			self.runtimeInstallCalls.append(withBpeSupport)

		with patch.object(installerModule, "downloadFile", fakeDownload):
			with patch.object(self.installer.runtime, "install", fakeRuntimeInstall):
				self.installer.applySelection(
					self.catalog,
					set(keys),
					self.progress,
					keysToUpdate or set(),
				)

	def writeArchive(
		self,
		fromCode: str,
		toCode: str,
		version: str = "1.9",
		tokenizerFileName: str = "sentencepiece.model",
	) -> None:
		"""Write one package archive where a fake download will find it."""
		name = f"translate-{fromCode}_{toCode}-{version.replace('.', '_')}.argosmodel"
		writePackageArchive(self.archiveDir / name, fromCode, toCode, version, tokenizerFileName)

	def test_installsAndReportsAPackage(self) -> None:
		self.writeArchive("en", "fr")
		self.installFromArchives("translate-en_fr")
		installed = self.installer.getInstalledPackages()
		self.assertEqual([package.key for package in installed], ["translate-en_fr"])
		self.assertEqual(installed[0].packageVersion, "1.9")
		self.assertTrue((installed[0].path / "model" / "model.bin").is_file())

	def test_installsABpePackageAndAsksForItsExtras(self) -> None:
		self.writeArchive("es", "en", tokenizerFileName="bpe.model")
		self.catalog = ArgosCatalog.deserialize(json.dumps([makeEntry("es", "en")]))
		self.installFromArchives("translate-es_en")
		installed = self.installer.getInstalledByKey()["translate-es_en"]
		self.assertTrue(installed.usesBpe)
		self.assertEqual(installed.tokenizerPath.name, "bpe.model")
		self.assertTrue(self.installer.needsBpeSupport())
		self.assertIn(True, self.runtimeInstallCalls)

	def test_leavesTheExtrasAloneForASentencePiecePackage(self) -> None:
		self.writeArchive("en", "fr")
		self.installFromArchives("translate-en_fr")
		installed = self.installer.getInstalledByKey()["translate-en_fr"]
		self.assertFalse(installed.usesBpe)
		self.assertFalse(self.installer.needsBpeSupport())
		self.assertNotIn(True, self.runtimeInstallCalls)

	def test_removesAPackageThatIsNoLongerSelected(self) -> None:
		self.writeArchive("en", "fr")
		self.writeArchive("en", "de")
		self.installFromArchives("translate-en_fr", "translate-en_de")
		self.installFromArchives("translate-en_fr")
		self.assertEqual(
			[package.key for package in self.installer.getInstalledPackages()],
			["translate-en_fr"],
		)

	def test_removingEverythingLeavesNoPackagesBehind(self) -> None:
		self.writeArchive("en", "fr")
		self.installFromArchives("translate-en_fr")
		self.installFromArchives()
		self.assertEqual(self.installer.getInstalledPackages(), [])

	def test_reportsAnAvailableUpdateAndInstallsIt(self) -> None:
		self.writeArchive("en", "fr", "1.0")
		catalogWithOldVersion = ArgosCatalog.deserialize(json.dumps([makeEntry("en", "fr", "1.0")]))
		originalCatalog = self.catalog
		self.catalog = catalogWithOldVersion
		self.installFromArchives("translate-en_fr")
		self.catalog = originalCatalog
		self.assertEqual(self.installer.getOutdatedKeys(self.catalog), {"translate-en_fr"})
		self.writeArchive("en", "fr", "1.9")
		self.installFromArchives("translate-en_fr", keysToUpdate={"translate-en_fr"})
		installed = self.installer.getInstalledByKey()["translate-en_fr"]
		self.assertEqual(installed.packageVersion, "1.9")
		self.assertEqual(self.installer.getOutdatedKeys(self.catalog), set())

	def test_anUpToDatePackageIsNotOffered_anUpdate(self) -> None:
		self.writeArchive("en", "fr")
		self.installFromArchives("translate-en_fr")
		self.assertEqual(self.installer.getOutdatedKeys(self.catalog), set())

	def test_ignoresAnIncompleteInstallDirectory(self) -> None:
		brokenPath = self.installer.packagesDir / "translate-en_fr-1_9"
		brokenPath.mkdir(parents=True)
		_unused = (brokenPath / "metadata.json").write_text('{"from_code": "en", "to_code": "fr"}')
		self.assertEqual(self.installer.getInstalledPackages(), [])

	def test_refusesAnArchiveThatWritesOutsideThePackagesDirectory(self) -> None:
		archivePath = self.archiveDir / "escape.argosmodel"
		archivePath.parent.mkdir(parents=True, exist_ok=True)
		with zipfile.ZipFile(archivePath, "w") as archive:
			archive.writestr("../escaped.txt", "should never be written")
		package = self.catalog.byKey["translate-en_fr"]
		with self.assertRaises(RuntimeError):
			self.installer.extractPackage(archivePath, package, self.progress)
		self.assertFalse((self.installer.packagesDir.parent / "escaped.txt").exists())

	def test_refusesAnArchiveWithoutAModel(self) -> None:
		archivePath = self.archiveDir / "empty.argosmodel"
		archivePath.parent.mkdir(parents=True, exist_ok=True)
		with zipfile.ZipFile(archivePath, "w") as archive:
			archive.writestr("translate-en_fr-1_9/README.md", "no model here")
		package = self.catalog.byKey["translate-en_fr"]
		with self.assertRaises(RuntimeError):
			self.installer.extractPackage(archivePath, package, self.progress)

	def test_remembersPackageSizes(self) -> None:
		package = self.catalog.byKey["translate-en_fr"]
		self.assertEqual(self.installer.getCachedSize(package), 0)
		self.installer.rememberSize(package, 12345)
		self.assertEqual(self.installer.getCachedSize(package), 12345)
		self.assertEqual(
			ArgosInstaller(polyglotRoot=self.installer.polyglotRoot).getCachedSize(package),
			12345,
		)

	def test_savesAndReadsBackTheDownloadedIndex(self) -> None:
		self.installer.saveIndexCache(self.catalog)
		cached = self.installer.loadCachedIndex()
		assert cached is not None
		self.assertEqual(
			[package.key for package in cached.packages],
			[package.key for package in self.catalog.packages],
		)

	def test_hasNoCachedIndexBeforeOneIsDownloaded(self) -> None:
		self.assertIsNone(self.installer.loadCachedIndex())


class RuntimeCatalogTestCase(unittest.TestCase):
	"""The runtime downloads are pinned in the add-on, hash and all."""

	def test_pinsAHashAndSizeForEveryComponent(self) -> None:
		catalog = RuntimeCatalog.loadBundled()
		self.assertTrue(catalog.byPythonTag)
		for pythonTag, components in catalog.byPythonTag.items():
			self.assertTrue(pythonTag.startswith("cp"))
			names = {component.name for component in components}
			self.assertEqual(names, {"ctranslate2", "sentencepiece"})
			for component in components:
				self.assertEqual(len(component.sha256), 64)
				self.assertGreater(component.size, 0)
				self.assertTrue(component.url.startswith("https://"))
				self.assertIn("win_amd64", component.fileName)

	def test_pinsTheExtrasBpePackagesNeed(self) -> None:
		catalog = RuntimeCatalog.loadBundled()
		for pythonTag in catalog.byPythonTag:
			components = catalog.getBpeComponents(pythonTag)
			names = {component.name for component in components}
			self.assertEqual(names, {"regex", "cloudpickle", "joblib", "tqdm", "sacremoses", "subword-nmt"})
			for component in components:
				self.assertEqual(len(component.sha256), 64)
				self.assertGreater(component.size, 0)
				self.assertTrue(component.url.startswith("https://files.pythonhosted.org/"))
			# The compiled one has to match the Python build; the rest are pure Python.
			regex = next(component for component in components if component.name == "regex")
			self.assertIn(pythonTag, regex.fileName)
			self.assertIn("win_amd64", regex.fileName)

	def test_coversThePythonNvdaRunsWhereItCan(self) -> None:
		catalog = RuntimeCatalog.loadBundled()
		# The Python builds NVDA 2026.1 and its likely successor use.
		self.assertIn("cp313", catalog.byPythonTag)
		self.assertEqual(catalog.getComponents("cp0"), ())

	def test_refusesToRunOnAnUnsupportedHost(self) -> None:
		with tempfile.TemporaryDirectory() as tempDir:
			root = Path(tempDir)
			installer = ArgosInstaller(polyglotRoot=root)
			runtime = installer.runtime
			with patch.object(installerModule, "downloadFile", lambda *args: None):
				with patch("polyglot.argosManager.runtime.isSixtyFourBit", lambda: False):
					self.assertFalse(runtime.isHostSupported)
					with self.assertRaises(RuntimeError):
						runtime.install(lambda update: None)

	def test_addsTheBpeExtrasWithoutReplacingTheRuntime(self) -> None:
		with tempfile.TemporaryDirectory() as tempDir:
			runtime = ArgosInstaller(polyglotRoot=Path(tempDir)).runtime
			installedNames: list[str] = []

			def fakeInstallComponent(component: object, progress: object) -> None:
				installedNames.append(getattr(component, "name", ""))

			with (
				patch("polyglot.argosManager.runtime.getPythonTag", lambda: "cp313"),
				patch("polyglot.argosManager.runtime.isSixtyFourBit", lambda: True),
				patch.object(runtime, "_installComponent", fakeInstallComponent),
			):
				runtime.install(lambda update: None)
				self.assertEqual(installedNames, ["ctranslate2", "sentencepiece"])
				self.assertTrue(runtime.isInstalled())
				self.assertFalse(runtime.isBpeInstalled())

				# A BPE package arriving later adds the extras next to the runtime it already has.
				installedNames.clear()
				runtime.install(lambda update: None, withBpeSupport=True)
				self.assertNotIn("ctranslate2", installedNames)
				self.assertIn("sacremoses", installedNames)
				self.assertIn("subword-nmt", installedNames)
				self.assertTrue(runtime.isInstalled())
				self.assertTrue(runtime.isBpeInstalled())

				installedNames.clear()
				runtime.install(lambda update: None, withBpeSupport=True)
				self.assertEqual(installedNames, [])

	def test_replacesTheWholeRuntimeWhenAComponentIsOutdated(self) -> None:
		with tempfile.TemporaryDirectory() as tempDir:
			runtime = ArgosInstaller(polyglotRoot=Path(tempDir)).runtime
			installedNames: list[str] = []

			def fakeInstallComponent(component: object, progress: object) -> None:
				installedNames.append(getattr(component, "name", ""))

			with (
				patch("polyglot.argosManager.runtime.getPythonTag", lambda: "cp313"),
				patch("polyglot.argosManager.runtime.isSixtyFourBit", lambda: True),
				patch.object(runtime, "_installComponent", fakeInstallComponent),
			):
				runtime.install(lambda update: None, withBpeSupport=True)
				runtime.markerPath.write_text(
					json.dumps({"pythonTag": "cp313", "components": {"sacremoses": "0.0.1"}}),
					encoding="utf-8",
				)
				installedNames.clear()
				runtime.install(lambda update: None, withBpeSupport=True)
				# Components share one directory, so the stale one takes the rest down with it.
				self.assertIn("ctranslate2", installedNames)
				self.assertIn("sacremoses", installedNames)
				self.assertTrue(runtime.isBpeInstalled())

	def test_reportsAnEmptyRuntimeAsNotInstalled(self) -> None:
		with tempfile.TemporaryDirectory() as tempDir:
			installer = ArgosInstaller(polyglotRoot=Path(tempDir))
			self.assertFalse(installer.runtime.isInstalled())
			self.assertFalse(installer.runtime.isAnythingInstalled())
			self.assertEqual(installer.runtime.libDir.name, getPythonTag())


if __name__ == "__main__":
	unittest.main()
