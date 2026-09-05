# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Runnable checks for the Argos Translate package index.

Nothing here touches the network: every check builds its own index, apart from the one that reads
the snapshot the add-on ships with.
"""

import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
	sys.path.insert(0, str(TESTS_ROOT))

from nvdaStubs import installNvdaStubs  # noqa: E402

_unused = installNvdaStubs(PROJECT_ROOT)

from polyglot.argosManager.catalog import (  # noqa: E402
	ArgosCatalog,
	ArgosPackage,
	DEFAULT_INDEX_URL,
	compareVersions,
	normalizeIndexUrl,
	normalizeLanguageCode,
	pairDisplayName,
)


def makeEntry(fromCode: str, toCode: str, version: str = "1.9") -> dict[str, object]:
	"""Build one index entry, in the form the Argos index publishes."""
	return {
		"code": f"translate-{fromCode}_{toCode}",
		"from_code": fromCode,
		"from_name": fromCode.upper(),
		"to_code": toCode,
		"to_name": toCode.upper(),
		"package_version": version,
		"argos_version": "1.9.0",
		"links": [
			f"https://argos-net.com/v1/translate-{fromCode}_{toCode}-{version.replace('.', '_')}.argosmodel"
		],
	}


def makeCatalog(*pairs: tuple[str, str]) -> ArgosCatalog:
	"""Build a catalog holding one package per supplied language pair."""
	return ArgosCatalog.deserialize(json.dumps([makeEntry(source, target) for source, target in pairs]))


class IndexReadingTestCase(unittest.TestCase):
	"""The index is published as a bare array, and saved by Polyglot as an object."""

	def test_readsThePlainArgosArray(self) -> None:
		catalog = makeCatalog(("en", "fr"))
		self.assertEqual(len(catalog.packages), 1)
		self.assertEqual(catalog.packages[0].fromCode, "en")
		self.assertEqual(catalog.packages[0].toCode, "fr")

	def test_readsAPolyglotSnapshot(self) -> None:
		catalog = ArgosCatalog.deserialize(
			json.dumps(
				{
					"schemaVersion": 1,
					"generatedAt": "2026-01-01T00:00:00Z",
					"sourceUrl": DEFAULT_INDEX_URL,
					"packages": [makeEntry("en", "de")],
				},
			),
		)
		self.assertEqual(catalog.generatedAt, "2026-01-01T00:00:00Z")
		self.assertEqual(catalog.sourceUrl, DEFAULT_INDEX_URL)
		self.assertEqual(len(catalog.packages), 1)

	def test_aSnapshotSurvivesBeingSavedAndReadBack(self) -> None:
		catalog = makeCatalog(("en", "fr"), ("fr", "en"))
		restored = ArgosCatalog.deserialize(catalog.serialize())
		self.assertEqual(
			[(package.fromCode, package.toCode) for package in restored.packages],
			[(package.fromCode, package.toCode) for package in catalog.packages],
		)

	def test_keepsOnlyTheNewestVersionOfADirection(self) -> None:
		catalog = ArgosCatalog.deserialize(
			json.dumps([makeEntry("en", "fr", "1.0"), makeEntry("en", "fr", "1.9")]),
		)
		self.assertEqual(len(catalog.packages), 1)
		self.assertEqual(catalog.packages[0].packageVersion, "1.9")

	def test_ignoresEntriesWithoutADownload(self) -> None:
		entry = makeEntry("en", "fr")
		entry["links"] = ["ipfs://QmNotSomethingPolyglotCanDownload"]
		with self.assertRaises(RuntimeError):
			_unused = ArgosCatalog.deserialize(json.dumps([entry]))

	def test_rejectsEmptyAndUnexpectedContent(self) -> None:
		with self.assertRaises(RuntimeError):
			_unused = ArgosCatalog.deserialize("   ")
		with self.assertRaises(RuntimeError):
			_unused = ArgosCatalog.deserialize(json.dumps({"packages": "not a list"}))

	def test_readsTheBundledSnapshot(self) -> None:
		catalog = ArgosCatalog.loadBundled()
		self.assertGreater(len(catalog.packages), 50)
		self.assertIn("en", catalog.getLanguageCodes())
		for package in catalog.packages:
			self.assertTrue(package.downloadUrl.startswith("https://"))


class LanguagePairTestCase(unittest.TestCase):
	"""A direction is served either by its own package or by two packages through English."""

	def setUp(self) -> None:
		self.catalog = makeCatalog(("en", "fr"), ("fr", "en"), ("en", "de"), ("de", "en"))

	def test_findsADirectPackage(self) -> None:
		packages = self.catalog.findPackagesForPair("en", "fr")
		self.assertEqual([package.key for package in packages], ["translate-en_fr"])

	def test_pivotsThroughEnglish(self) -> None:
		packages = self.catalog.findPackagesForPair("fr", "de")
		self.assertEqual(
			[package.key for package in packages],
			["translate-fr_en", "translate-en_de"],
		)

	def test_reportsNothingForADirectionItCannotServe(self) -> None:
		self.assertEqual(self.catalog.findPackagesForPair("fr", "ja"), [])
		self.assertFalse(self.catalog.isPairSupported("fr", "ja"))

	def test_neverPivotsWhenEnglishIsOneEnd(self) -> None:
		catalog = makeCatalog(("fr", "en"))
		self.assertEqual(catalog.findPackagesForPair("en", "fr"), [])

	def test_treatsTheSameLanguageAsNothingToDo(self) -> None:
		self.assertEqual(self.catalog.findPackagesForPair("en", "en"), [])

	def test_acceptsTheRegionalCodesOtherEnginesUse(self) -> None:
		catalog = makeCatalog(("en", "zt"), ("en", "pb"))
		self.assertEqual(
			[package.key for package in catalog.findPackagesForPair("en", "zh-Hant")],
			["translate-en_zt"],
		)
		self.assertEqual(
			[package.key for package in catalog.findPackagesForPair("en", "pt-BR")],
			["translate-en_pb"],
		)

	def test_namesAPairInBothLanguages(self) -> None:
		package = self.catalog.byKey["translate-en_fr"]
		self.assertEqual(pairDisplayName(package), "English to French")


class LanguageCodeTestCase(unittest.TestCase):
	"""Polyglot's codes have to be mapped onto the ones the Argos index uses."""

	def test_mapsRegionalAndLegacyCodes(self) -> None:
		self.assertEqual(normalizeLanguageCode("zh-Hant"), "zt")
		self.assertEqual(normalizeLanguageCode("zh-TW"), "zt")
		self.assertEqual(normalizeLanguageCode("cht"), "zt")
		self.assertEqual(normalizeLanguageCode("zh-CN"), "zh")
		self.assertEqual(normalizeLanguageCode("pt-BR"), "pb")
		self.assertEqual(normalizeLanguageCode("iw"), "he")
		self.assertEqual(normalizeLanguageCode("no"), "nb")
		self.assertEqual(normalizeLanguageCode("en-US"), "en")
		self.assertEqual(normalizeLanguageCode("fil"), "tl")

	def test_treatsAutoDetectAsNoLanguage(self) -> None:
		self.assertEqual(normalizeLanguageCode("auto"), "")
		self.assertEqual(normalizeLanguageCode(""), "")


class VersionTestCase(unittest.TestCase):
	"""Package versions decide whether an installed package can be updated."""

	def test_ordersDottedVersions(self) -> None:
		self.assertLess(compareVersions("1.0", "1.9"), 0)
		self.assertGreater(compareVersions("1.10", "1.9"), 0)
		self.assertEqual(compareVersions("1.9", "1.9"), 0)
		self.assertEqual(compareVersions("1.9", "1.9.0"), 0)

	def test_treatsAMissingVersionAsTheOldest(self) -> None:
		self.assertGreater(compareVersions("1.0", ""), 0)


class IndexUrlTestCase(unittest.TestCase):
	"""The index URL can be pointed at another channel, but only over HTTP."""

	def test_keepsAJsonUrlAsItIs(self) -> None:
		self.assertEqual(normalizeIndexUrl(DEFAULT_INDEX_URL), DEFAULT_INDEX_URL)

	def test_completesADirectoryUrl(self) -> None:
		self.assertEqual(
			normalizeIndexUrl("https://example.invalid/argos/"),
			"https://example.invalid/argos/index.json",
		)

	def test_fallsBackToTheDefaultWhenEmpty(self) -> None:
		self.assertEqual(normalizeIndexUrl(""), DEFAULT_INDEX_URL)
		self.assertEqual(normalizeIndexUrl(None), DEFAULT_INDEX_URL)

	def test_refusesAnythingThatIsNotHttp(self) -> None:
		with self.assertRaises(RuntimeError):
			_unused = normalizeIndexUrl("file:///c:/argos/index.json")


class PackageEntryTestCase(unittest.TestCase):
	"""Entries name the directory a package is installed into."""

	def test_namesTheInstallDirectoryTheWayArgosDoes(self) -> None:
		package = ArgosPackage.fromJson(makeEntry("en", "fr", "1.9"))
		assert package is not None
		self.assertEqual(package.directoryName, "translate-en_fr-1_9")

	def test_ignoresAnEntryWithoutLanguages(self) -> None:
		entry = makeEntry("en", "fr")
		del entry["from_code"]
		self.assertIsNone(ArgosPackage.fromJson(entry))


if __name__ == "__main__":
	unittest.main()
