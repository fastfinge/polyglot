# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Runnable checks for the Argos translation pipeline.

The models themselves cannot be loaded outside 64-bit NVDA, so the checks here cover the parts that
decide what a model is given and which models a language direction uses: sentence splitting, and
route resolution over the installed packages.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
	sys.path.insert(0, str(TESTS_ROOT))

from nvdaStubs import installNvdaStubs  # noqa: E402

_unused = installNvdaStubs(PROJECT_ROOT)

from polyglot.argosManager.installer import ArgosInstaller  # noqa: E402
from polyglot.argosManager.translator import (  # noqa: E402
	MAX_SENTENCE_LENGTH,
	ArgosTranslator,
	splitSentences,
)


class SentenceSplittingTestCase(unittest.TestCase):
	"""Models translate one sentence at a time, so a paragraph has to be split up first."""

	def test_splitsOnSentencePunctuation(self) -> None:
		self.assertEqual(
			splitSentences("First one. Second one! Third one?"),
			["First one.", "Second one!", "Third one?"],
		)

	def test_keepsClosingQuotesWithTheirSentence(self) -> None:
		self.assertEqual(
			splitSentences('He said "no thanks." She left.'),
			['He said "no thanks."', "She left."],
		)

	def test_splitsScriptsThatDoNotUseSpaces(self) -> None:
		self.assertEqual(splitSentences("这是第一句。这是第二句。"), ["这是第一句。", "这是第二句。"])

	def test_breaksASentenceTooLongForTheModel(self) -> None:
		sentence = "word " * 200
		parts = splitSentences(sentence)
		self.assertGreater(len(parts), 1)
		for part in parts:
			self.assertLessEqual(len(part), MAX_SENTENCE_LENGTH)

	def test_breaksTextWithNoSpacesToSplitOn(self) -> None:
		parts = splitSentences("x" * (MAX_SENTENCE_LENGTH * 2 + 10))
		self.assertEqual(len(parts), 3)
		for part in parts:
			self.assertLessEqual(len(part), MAX_SENTENCE_LENGTH)

	def test_hasNothingToSplitInEmptyText(self) -> None:
		self.assertEqual(splitSentences(""), [])
		self.assertEqual(splitSentences("   "), [])


class RouteTestCase(unittest.TestCase):
	"""A direction is served by one installed package, or by two through English."""

	def setUp(self) -> None:
		self._tempDir = tempfile.TemporaryDirectory()
		self.installer = ArgosInstaller(polyglotRoot=Path(self._tempDir.name))
		self.translator = ArgosTranslator(self.installer)

	def tearDown(self) -> None:
		self._tempDir.cleanup()

	def installFakePackage(self, fromCode: str, toCode: str, version: str = "1.9") -> None:
		"""Write a package directory shaped like an installed one, without a real model."""
		path = self.installer.packagesDir / f"translate-{fromCode}_{toCode}-{version.replace('.', '_')}"
		(path / "model").mkdir(parents=True)
		_unused = (path / "sentencepiece.model").write_text("not a real tokenizer")
		_unused = (path / "metadata.json").write_text(
			json.dumps(
				{
					"package_version": version,
					"from_code": fromCode,
					"to_code": toCode,
				},
			),
		)

	def test_usesADirectPackage(self) -> None:
		self.installFakePackage("en", "fr")
		route = self.translator.findRoute("en", "fr")
		self.assertEqual([package.key for package in route], ["translate-en_fr"])

	def test_pivotsThroughEnglish(self) -> None:
		self.installFakePackage("fr", "en")
		self.installFakePackage("en", "de")
		route = self.translator.findRoute("fr", "de")
		self.assertEqual(
			[package.key for package in route],
			["translate-fr_en", "translate-en_de"],
		)

	def test_prefersADirectPackageOverAPivot(self) -> None:
		self.installFakePackage("fr", "en")
		self.installFakePackage("en", "de")
		self.installFakePackage("fr", "de")
		route = self.translator.findRoute("fr", "de")
		self.assertEqual([package.key for package in route], ["translate-fr_de"])

	def test_hasNoRouteWhenHalfAPivotIsInstalled(self) -> None:
		self.installFakePackage("fr", "en")
		self.assertEqual(self.translator.findRoute("fr", "de"), [])

	def test_acceptsTheRegionalCodesOtherEnginesUse(self) -> None:
		self.installFakePackage("en", "zt")
		route = self.translator.findRoute("en", "zh-Hant")
		self.assertEqual([package.key for package in route], ["translate-en_zt"])

	def test_reportsAMissingModelRatherThanFailingLater(self) -> None:
		with self.assertRaises(RuntimeError):
			_unused = self.translator.translate("hello", "en", "fr")

	def test_returnsTextUnchangedForTheSameLanguage(self) -> None:
		self.assertEqual(self.translator.translate("hello", "en", "en-US"), "hello")

	def test_hasNoLoadedModelsBeforeTranslating(self) -> None:
		self.assertFalse(self.translator.hasLoadedModels)
		self.assertEqual(self.translator.unloadModels(), 0)


if __name__ == "__main__":
	unittest.main()
