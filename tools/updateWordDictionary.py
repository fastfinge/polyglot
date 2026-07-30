# -*- coding: utf-8 -*-

# Copyright (C) 2025-2026 cary-rowen <manchen_0528@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Prepare and apply reviewed additions to the local word dictionary."""

import argparse
import csv
import importlib.util
import json
import re
import subprocess
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from generateWordDictionaryInflections import buildInflections


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_RESOURCE_DIR = _PROJECT_ROOT / "tools/resource"
_ECDICT_DIR = _RESOURCE_DIR / "ECDICT"
_ECDICT_PATH = _ECDICT_DIR / "ecdict.csv"
_LEMMA_PATH = _ECDICT_DIR / "lemma.en.txt"
_DICTIONARY_PATH = _RESOURCE_DIR / "dictionary.json"
_INFLECTIONS_PATH = _RESOURCE_DIR / "inflections.json"
_CANDIDATES_PATH = _RESOURCE_DIR / "candidates.json"
_DATA_MODULE_PATH = _PROJECT_ROOT / "addon/globalPlugins/polyglot/common/wordDictionaryData.py"
_REVIEW_FORMAT = "polyglot.wordDictionaryReview"
_REVIEW_SCHEMA_VERSION = 1
_ECDICT_REPOSITORY = "https://github.com/skywind3000/ECDICT"
_CHINESE_PATTERN = re.compile(r"[\u3400-\u9fff]")
_PROPER_NAME_PATTERN = re.compile(
	r"人名|男子名|女子名|女名|姓氏|地名|城市|城镇|小镇|州名|郡|国名|首都|地区|岛|河|山名|港|公司|集团|品牌|快餐|球队|足球|球会|合唱团|乐队|歌星|歌手|诗人|作家|剧作家|政治家|总统|画家|建筑学家|物理学家|科学家|商学院|大学|学院|电影|动画|游戏中的角色|角色名|航空公司|轮胎|生产厂|王朝",
)


def _loadDataModule() -> ModuleType:
	"""Load dictionary schema helpers without importing the NVDA add-on package."""
	moduleSpec = importlib.util.spec_from_file_location("_polyglotWordDictionaryData", _DATA_MODULE_PATH)
	if moduleSpec is None or moduleSpec.loader is None:
		raise RuntimeError("Unable to load the word dictionary schema module.")
	module = importlib.util.module_from_spec(moduleSpec)
	moduleSpec.loader.exec_module(module)
	return module


def _objectWithoutDuplicateKeys(pairs: list[tuple[str, object]]) -> dict[str, object]:
	"""Return a JSON object while rejecting duplicate keys."""
	result: dict[str, object] = {}
	for key, value in pairs:
		if key in result:
			raise ValueError(f"JSON contains a duplicate key: {key}")
		result[key] = value
	return result


def _readJson(path: Path) -> object:
	"""Read one JSON document while rejecting duplicate object keys."""
	with path.open("r", encoding="utf-8") as sourceFile:
		return json.load(sourceFile, object_pairs_hook=_objectWithoutDuplicateKeys)


def _writeJsonAtomically(path: Path, value: object, *, shouldPrettyPrint: bool) -> None:
	"""Write deterministic JSON through a temporary file in the target directory."""
	temporaryPath: Path | None = None
	try:
		with tempfile.NamedTemporaryFile(
			"w",
			encoding="utf-8",
			dir=path.parent,
			prefix=f".{path.name}.",
			suffix=".tmp",
			delete=False,
		) as targetFile:
			temporaryPath = Path(targetFile.name)
			json.dump(
				value,
				targetFile,
				ensure_ascii=False,
				indent=2 if shouldPrettyPrint else None,
				separators=None if shouldPrettyPrint else (",", ":"),
				sort_keys=not shouldPrettyPrint,
			)
			_ = targetFile.write("\n" if shouldPrettyPrint else "")
		_ = temporaryPath.replace(path)
		temporaryPath = None
	finally:
		if temporaryPath is not None:
			temporaryPath.unlink(missing_ok=True)


def _requireUpstreamFiles() -> None:
	"""Require the two ECDICT files used by the maintenance workflow."""
	missingPaths = [path for path in (_ECDICT_PATH, _LEMMA_PATH) if not path.is_file()]
	if missingPaths:
		missingText = ", ".join(str(path.relative_to(_PROJECT_ROOT)) for path in missingPaths)
		raise FileNotFoundError(
			f"Missing {missingText}. Clone {_ECDICT_REPOSITORY} into "
			f"{_ECDICT_DIR.relative_to(_PROJECT_ROOT)}.",
		)


def _getSourceRevision() -> str | None:
	"""Return the checked-out ECDICT revision when Git is available."""
	try:
		result = subprocess.run(
			("git", "-C", str(_ECDICT_DIR), "rev-parse", "HEAD"),
			capture_output=True,
			check=False,
			encoding="utf-8",
			text=True,
		)
	except OSError:
		return None
	revision = result.stdout.strip()
	return revision if result.returncode == 0 and revision else None


def _parsePositiveInteger(value: str | None) -> int | None:
	"""Return a positive integer from one ECDICT ranking field."""
	try:
		parsedValue = int(value or "")
	except ValueError:
		return None
	return parsedValue if parsedValue > 0 else None


def _getDefinition(translation: str) -> str | None:
	"""Return a compact useful Chinese definition from ECDICT translation text."""
	senses: list[str] = []
	for rawLine in translation.replace("\\n", "\n").splitlines():
		line = " ".join(rawLine.split())
		if not line or line.startswith("[网络]"):
			continue
		for rawSense in re.split(r"[;；]", line):
			sense = rawSense.strip()
			if not sense or _PROPER_NAME_PATTERN.search(sense) is not None or sense in senses:
				continue
			senses.append(sense)
	definition = "; ".join(senses)
	if not definition or _CHINESE_PATTERN.search(definition) is None:
		return None
	return definition


def _getEvidence(row: dict[str, str]) -> dict[str, object] | None:
	"""Return useful ranking evidence, or ``None`` for an unranked row."""
	collins = _parsePositiveInteger(row.get("collins"))
	oxford = row.get("oxford", "").strip() not in ("", "0")
	tags = sorted(set(row.get("tag", "").split()))
	bnc = _parsePositiveInteger(row.get("bnc"))
	frq = _parsePositiveInteger(row.get("frq"))
	if collins is None and not oxford and not tags and bnc is None and frq is None:
		return None
	return {
		"collins": collins,
		"oxford": oxford,
		"tags": tags,
		"bnc": bnc,
		"frq": frq,
	}


def _getCandidatePriority(word: str, evidence: dict[str, object]) -> tuple[object, ...]:
	"""Return a stable order placing stronger dictionary signals first."""
	collins = cast(int | None, evidence["collins"])
	oxford = cast(bool, evidence["oxford"])
	tags = cast(list[str], evidence["tags"])
	bnc = cast(int | None, evidence["bnc"])
	frq = cast(int | None, evidence["frq"])
	corpusRanks = [rank for rank in (bnc, frq) if rank is not None]
	return (
		-(collins or 0),
		0 if oxford else 1,
		-len(tags),
		min(corpusRanks, default=1_000_000_000),
		word,
	)


def _readReviewEntries() -> tuple[dict[str, dict[str, object]], str | None]:
	"""Return validated review entries and their recorded ECDICT revision."""
	if not _CANDIDATES_PATH.is_file():
		return {}, None
	rawReview = _readJson(_CANDIDATES_PATH)
	if type(rawReview) is not dict:
		raise ValueError("The candidate file must contain one JSON object.")
	review = cast(dict[str, object], rawReview)
	if review.get("format") != _REVIEW_FORMAT or review.get("schemaVersion") != _REVIEW_SCHEMA_VERSION:
		raise ValueError("The candidate file format is unsupported.")
	rawSource = review.get("source")
	if type(rawSource) is not dict:
		raise ValueError("The candidate source metadata is invalid.")
	source = cast(dict[str, object], rawSource)
	revisionValue = source.get("revision")
	if revisionValue is not None and type(revisionValue) is not str:
		raise ValueError("The candidate source revision is invalid.")
	rawEntries = review.get("entries")
	if type(rawEntries) is not dict:
		raise ValueError("The candidate entries must contain one JSON object.")
	entries: dict[str, dict[str, object]] = {}
	for word, rawEntry in cast(dict[object, object], rawEntries).items():
		if type(word) is not str or type(rawEntry) is not dict:
			raise ValueError("A candidate entry is invalid.")
		entry = cast(dict[str, object], rawEntry)
		if type(entry.get("approved")) is not bool:
			raise ValueError(f"Candidate approval must be true or false: {word}")
		if type(entry.get("definition")) is not str or not cast(str, entry["definition"]).strip():
			raise ValueError(f"Candidate definition is invalid: {word}")
		sourceDefinition = entry.get("sourceDefinition")
		if type(sourceDefinition) is not str or not sourceDefinition.strip():
			raise ValueError(f"Candidate source definition is invalid: {word}")
		if type(entry.get("evidence")) is not dict:
			raise ValueError(f"Candidate review metadata is invalid: {word}")
		note = entry.get("note", "")
		if type(note) is not str:
			raise ValueError(f"Candidate review note is invalid: {word}")
		entry["note"] = note
		entries[word] = entry
	return entries, cast(str | None, revisionValue)


def _readDictionarySources(dataModule: ModuleType) -> dict[str, Any]:
	"""Read and compile the tracked dictionary source documents."""
	rawEntries = _readJson(_DICTIONARY_PATH)
	rawInflections = _readJson(_INFLECTIONS_PATH)
	return cast(dict[str, Any], dataModule.createDictionaryData(rawEntries, rawInflections))


def _prepareCandidates() -> dict[str, int | str | None]:
	"""Generate a review file containing relevant missing ECDICT headwords."""
	_requireUpstreamFiles()
	dataModule = _loadDataModule()
	compiledData = _readDictionarySources(dataModule)
	entries = cast(dict[str, str], compiledData["entries"])
	casefoldAliases = cast(dict[str, object], compiledData["casefoldAliases"])
	normalizedAliases = cast(dict[str, object], compiledData["normalizedAliases"])
	inflectionAliases = cast(dict[str, object], compiledData["inflectionAliases"])
	existingFoldedKeys = {key.casefold() for key in entries}.union(casefoldAliases)
	existingNormalizedKeys = {dataModule.normalizeKey(key) for key in entries}.union(normalizedAliases)
	previousEntries, _previousRevision = _readReviewEntries()

	requiredFields = {
		"word",
		"translation",
		"collins",
		"oxford",
		"tag",
		"bnc",
		"frq",
		"exchange",
	}
	candidates: dict[str, tuple[tuple[object, ...], dict[str, object]]] = {}
	duplicateWords: set[str] = set()
	rowCount = 0
	with _ECDICT_PATH.open("r", encoding="utf-8-sig", newline="") as sourceFile:
		reader = csv.DictReader(sourceFile)
		if reader.fieldnames is None or not requiredFields.issubset(reader.fieldnames):
			raise ValueError("ECDICT fields are invalid.")
		for rawRow in reader:
			rowCount += 1
			row = {key: value or "" for key, value in rawRow.items() if key is not None}
			word = row["word"].strip()
			if (
				word != dataModule.canonicalizeWord(word)
				or word != word.casefold()
				or word.endswith(".")
				or not dataModule.isLookupWord(word)
				or any(item.startswith("0:") for item in row["exchange"].split("/"))
			):
				continue
			normalizedKey = dataModule.normalizeKey(word)
			if (
				word in existingFoldedKeys
				or word in inflectionAliases
				or normalizedKey in existingNormalizedKeys
			):
				continue
			definition = _getDefinition(row["translation"])
			if definition is None:
				continue
			evidence = _getEvidence(row)
			if evidence is None:
				continue
			if word in candidates:
				duplicateWords.add(word)
				continue
			previousEntry = previousEntries.get(word)
			candidate: dict[str, object] = {
				"approved": bool(previousEntry and previousEntry["approved"]),
				"definition": previousEntry["definition"] if previousEntry else definition,
				"sourceDefinition": definition,
				"evidence": evidence,
				"note": previousEntry["note"] if previousEntry else "",
			}
			candidates[word] = (_getCandidatePriority(word, evidence), candidate)
	for word in duplicateWords:
		_ = candidates.pop(word, None)

	orderedEntries = {
		word: candidate
		for word, (_priority, candidate) in sorted(
			candidates.items(),
			key=lambda item: item[1][0],
		)
	}
	revision = _getSourceRevision()
	review: dict[str, object] = {
		"format": _REVIEW_FORMAT,
		"schemaVersion": _REVIEW_SCHEMA_VERSION,
		"source": {
			"repository": _ECDICT_REPOSITORY,
			"revision": revision,
		},
		"entries": orderedEntries,
	}
	_writeJsonAtomically(_CANDIDATES_PATH, review, shouldPrettyPrint=True)
	return {
		"candidates": len(orderedEntries),
		"duplicateSourceWords": len(duplicateWords),
		"sourceEntries": rowCount,
		"sourceRevision": revision,
	}


def _applyCandidates() -> dict[str, object]:
	"""Apply approved additions and regenerate all tracked inflection aliases."""
	_requireUpstreamFiles()
	reviewEntries, reviewRevision = _readReviewEntries()
	if not _CANDIDATES_PATH.is_file():
		raise ValueError("No candidate review file is available. Run prepare first.")
	currentRevision = _getSourceRevision()
	if reviewRevision is not None and currentRevision is not None and reviewRevision != currentRevision:
		raise ValueError("ECDICT changed after prepare. Review a newly prepared candidate file.")

	dataModule = _loadDataModule()
	compiledData = _readDictionarySources(dataModule)
	entries = cast(dict[str, str], compiledData["entries"])
	updatedEntries = dict(entries)
	existingFoldedKeys = {key.casefold() for key in entries}
	existingNormalizedKeys = {dataModule.normalizeKey(key) for key in entries}
	addedWords: list[str] = []
	alreadyPresent = 0
	for word, candidate in reviewEntries.items():
		if not cast(bool, candidate["approved"]):
			continue
		definition = " ".join(cast(str, candidate["definition"]).split())
		if (
			word != dataModule.canonicalizeWord(word)
			or word != word.casefold()
			or word.endswith(".")
			or not dataModule.isLookupWord(word)
			or _CHINESE_PATTERN.search(definition) is None
		):
			raise ValueError(f"Approved candidate is invalid: {word}")
		existingDefinition = updatedEntries.get(word)
		if existingDefinition is not None:
			if existingDefinition != definition:
				raise ValueError(f"Approved candidate conflicts with an existing definition: {word}")
			alreadyPresent += 1
			continue
		if word.casefold() in existingFoldedKeys or dataModule.normalizeKey(word) in existingNormalizedKeys:
			raise ValueError(f"Approved candidate conflicts with an existing spelling: {word}")
		updatedEntries[word] = definition
		existingFoldedKeys.add(word.casefold())
		existingNormalizedKeys.add(dataModule.normalizeKey(word))
		addedWords.append(word)

	temporaryDictionaryPath: Path | None = None
	try:
		with tempfile.NamedTemporaryFile(
			"w",
			encoding="utf-8",
			dir=_RESOURCE_DIR,
			prefix=".dictionary.json.",
			suffix=".tmp",
			delete=False,
		) as temporaryFile:
			temporaryDictionaryPath = Path(temporaryFile.name)
			json.dump(
				updatedEntries,
				temporaryFile,
				ensure_ascii=False,
				separators=(",", ":"),
				sort_keys=True,
			)
		inflections, inflectionStats = buildInflections(
			_ECDICT_PATH,
			_LEMMA_PATH,
			temporaryDictionaryPath,
		)
		_ = dataModule.createDictionaryData(updatedEntries, inflections)
	finally:
		if temporaryDictionaryPath is not None:
			temporaryDictionaryPath.unlink(missing_ok=True)

	if addedWords:
		_writeJsonAtomically(_DICTIONARY_PATH, updatedEntries, shouldPrettyPrint=False)
	_writeJsonAtomically(_INFLECTIONS_PATH, inflections, shouldPrettyPrint=False)
	return {
		"addedEntries": len(addedWords),
		"alreadyPresent": alreadyPresent,
		"dictionaryEntries": len(updatedEntries),
		"inflections": inflectionStats,
	}


def main() -> None:
	"""Run the selected word dictionary maintenance action."""
	parser = argparse.ArgumentParser(description=__doc__)
	subparsers = parser.add_subparsers(dest="command", required=True)
	_ = subparsers.add_parser("prepare", help="write missing ECDICT entries for review")
	_ = subparsers.add_parser("apply", help="apply approved entries and regenerate inflections")
	args = parser.parse_args()
	result = _prepareCandidates() if args.command == "prepare" else _applyCandidates()
	print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
	main()
