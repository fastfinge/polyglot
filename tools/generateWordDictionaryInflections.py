# -*- coding: utf-8 -*-

# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Compile high-confidence Polyglot inflection aliases for the update tool."""

import csv
import importlib.util
import json
import re
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, cast


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DATA_MODULE_PATH = _PROJECT_ROOT / "addon/globalPlugins/polyglot/common/wordDictionaryData.py"
_EXCHANGE_TYPES = frozenset(("p", "d", "i", "3", "s", "r", "t"))
_MAX_AMBIGUOUS_TARGETS = 3
_PART_OF_SPEECH_PATTERN = re.compile(
	r"(?<![A-Za-z])(a|adj|adv|art|aux|conj|int|interj|n|num|pl|pref|prep|pron|suf|suff|v|vbl|vi|vt)\.",
	re.IGNORECASE,
)
_ABBREVIATION_PATTERN = re.compile(r"(?<![A-Za-z])abbr\.", re.IGNORECASE)
_PROPER_NAME_PATTERN = re.compile(
	r"人名|男子名|女子名|女名|姓氏|地名|城市名|州名|国名|首都|岛名|河名|山名",
)
_EXPECTED_TAGS = {
	"p": frozenset(("aux", "v", "vbl", "vi", "vt")),
	"d": frozenset(("aux", "v", "vbl", "vi", "vt")),
	"i": frozenset(("aux", "v", "vbl", "vi", "vt")),
	"3": frozenset(("aux", "v", "vbl", "vi", "vt")),
	"s": frozenset(("n", "pl")),
	"r": frozenset(("a", "adj", "adv")),
	"t": frozenset(("a", "adj", "adv")),
}
_VERB_TAGS = _EXPECTED_TAGS["p"]
_NOUN_TAGS = _EXPECTED_TAGS["s"]
_DEGREE_TAGS = _EXPECTED_TAGS["r"]
_DEGREE_TYPES = frozenset(("r", "t"))
_NOUN_OR_THIRD_PERSON_TYPES = frozenset(("s", "3"))
_GREEK_IS_ENDINGS = ("osis", "esis", "asis", "ysis", "psis", "xis")
_F_TO_VES_ENDINGS = (
	"calf",
	"elf",
	"half",
	"knife",
	"leaf",
	"life",
	"loaf",
	"self",
	"sheaf",
	"shelf",
	"thief",
	"wife",
	"wolf",
)
_CH_TAKES_S_ENDINGS = (
	"anarch",
	"epoch",
	"eunuch",
	"hierarch",
	"loch",
	"matriarch",
	"monarch",
	"oligarch",
	"patriarch",
	"psych",
	"stomach",
	"tech",
	"tetrarch",
)
_O_TAKES_ES_WORDS = frozenset(
	(
		"buffalo",
		"cargo",
		"domino",
		"echo",
		"embargo",
		"halo",
		"hero",
		"mango",
		"mosquito",
		"potato",
		"tomato",
		"torpedo",
		"veto",
		"volcano",
		"zero",
	),
)
_MAN_TAKES_S_WORDS = frozenset(("german", "human", "ottoman", "roman", "shaman"))
_DOUBLED_FINAL_CONSONANT_WORDS = frozenset(
	(
		"admit",
		"begin",
		"commit",
		"compel",
		"control",
		"defer",
		"diagram",
		"emit",
		"equip",
		"expel",
		"forget",
		"format",
		"handicap",
		"incur",
		"infer",
		"input",
		"kidnap",
		"occur",
		"omit",
		"output",
		"permit",
		"prefer",
		"program",
		"propel",
		"rebel",
		"refer",
		"regret",
		"submit",
		"transfer",
		"transmit",
		"up",
	),
)
_OPTIONALLY_DOUBLED_WORDS = frozenset(
	("benefit", "bias", "combat", "dial", "equal", "focus", "fuel", "target", "worship"),
)
_E_RETAINED_BEFORE_ING_ENDINGS = ("ee", "oe", "singe", "ye")
_OPTIONAL_E_BEFORE_ING_WORDS = frozenset(("age", "queue", "sue"))
# Reviewed corrections for valid forms obscured by conflicting or malformed
# ECDICT candidates. Keeping these as data avoids broader, error-prone rules.
_MANUAL_TARGETS = {
	"acclimatises": "acclimatise",
	"aliases": "alias",
	"annexes": "annex",
	"axed": "axe",
	"axes": ("ax", "axe", "axis"),
	"backlogging": "backlog",
	"backslapped": "backslap",
	"baddies": "baddy",
	"besotting": "besot",
	"blitzes": "blitz",
	"blitzing": "blitz",
	"bogies": "bogie",
	"brailled": "braille",
	"burred": "burr",
	"burring": "burr",
	"caddied": "caddy",
	"caddies": "caddy",
	"caddying": "caddy",
	"chairmanned": "chairman",
	"chairmanning": "chairman",
	"chaperoned": "chaperone",
	"chaperoning": "chaperone",
	"chivvied": "chivvy",
	"chivvies": "chivvy",
	"clear-cutting": "clear-cut",
	"clued": "clue",
	"day-dreamed": "daydream",
	"dearies": "dearie",
	"dickies": "dickie",
	"distilling": "distil",
	"enrolling": "enrol",
	"enthralled": "enthral",
	"faeries": "faerie",
	"fizzed": "fizz",
	"flip-flopped": "flip-flop",
	"flip-flopping": "flip-flop",
	"floozies": "floozy",
	"footslogged": "footslog",
	"fosses": "fosse",
	"frolicked": "frolic",
	"frolicking": "frolic",
	"gillies": "gillie",
	"gift-wrapped": "gift-wrap",
	"gift-wrapping": "gift-wrap",
	"gnars": "gnar",
	"hankies": "hanky",
	"huger": "huge",
	"hugest": "huge",
	"hyphened": "hyphen",
	"hyphening": "hyphen",
	"instals": "instal",
	"instilled": "instil",
	"instilling": "instil",
	"jitterbugged": "jitterbug",
	"lambasted": "lambast",
	"lambasting": "lambast",
	"largesses": "largesse",
	"lollygagged": "lollygag",
	"lollygagging": "lollygag",
	"mimicked": "mimic",
	"mimicking": "mimic",
	"monies": "money",
	"motlier": "motley",
	"motliest": "motley",
	"one-stepped": "one-step",
	"one-stepping": "one-step",
	"outdrawn": "outdraw",
	"outdrew": "outdraw",
	"pelves": "pelvis",
	"pinged": "ping",
	"psyches": "psyche",
	"recreated": "recreate",
	"reechoes": "reecho",
	"refocused": "refocus",
	"refocuses": "refocus",
	"regrew": "regrow",
	"reveries": "reverie",
	"ricochetting": "ricochet",
	"scotties": "scottie",
	"spatting": "spat",
	"stomaches": "stomach",
	"stymies": "stymie",
	"tangoes": "tango",
	"taxies": "taxi",
	"toughies": "toughie",
	"underspent": "underspend",
	"unlooses": "unloose",
	"whirred": "whir",
	"whizzed": "whizz",
	"whizzes": "whizz",
	"whizzing": "whizz",
	"zinced": "zinc",
	"zincing": "zinc",
	"zombies": "zombie",
}
# Reviewed forms for selected entries whose fixed source has no usable relation
# in the basic ECDICT CSV consumed by this generator.
_REVIEWED_ADDITIONAL_TARGETS = {
	"bitcoins": "bitcoin",
	"cablecars": "cablecar",
	"captchas": "captcha",
	"cryptocurrencies": "cryptocurrency",
	"dancehalls": "dancehall",
	"datafiles": "datafile",
	"datapoints": "datapoint",
	"datastreams": "datastream",
	"emojis": "emoji",
	"fruitbats": "fruitbat",
	"glassfibres": "glassfibre",
	"half-marathons": "half-marathon",
	"hillwalkers": "hillwalker",
	"jetstreams": "jetstream",
	"lieutenant-colonels": "lieutenant-colonel",
	"mp3s": "mp3",
	"nightlights": "nightlight",
	"pipedreams": "pipedream",
	"randomisations": "randomisation",
	"service-providers": "service-provider",
	"shopfloors": "shopfloor",
	"signalboxes": "signalbox",
	"smartphones": "smartphone",
	"swimbladders": "swimbladder",
	"tee-shirts": "tee-shirt",
	"twelve-year-olds": "twelve-year-old",
	"waterboys": "waterboy",
	"watersports": "watersport",
	"webinars": "webinar",
	"whizzkids": "whizzkid",
	"windfarms": "windfarm",
	"wordlists": "wordlist",
	"wordprocessors": "wordprocessor",
	"z-scores": "z-score",
}
# Known malformed source forms which would otherwise produce a wrong definition.
_REJECTED_FORMS = frozenset(
	(
		"affraid",
		"busbys",
		"chevys",
		"cloathing",
		"dillys",
		"downtowner",
		"latelier",
		"lavvys",
		"lys",
		"matterhorns",
		"mummerys",
		"prys",
		"pulitzers",
		"skinnys",
		"spaid",
		"spinnys",
		"spoilter",
		"stonehenges",
		"thier",
		"uptowner",
		"veing",
		"widdleing",
		"xixs",
	),
)


@dataclass
class _Relation:
	"""Collect evidence for one inflected form and one possible lemma."""

	forwardTypes: set[str] = field(default_factory=set[str])
	reverseTypes: set[str] = field(default_factory=set[str])
	lemmaSpellings: set[str] = field(default_factory=set[str])


def _loadDataModule() -> ModuleType:
	"""Load dictionary schema helpers without importing the NVDA add-on package."""
	moduleSpec = importlib.util.spec_from_file_location("_polyglotWordDictionaryData", _DATA_MODULE_PATH)
	if moduleSpec is None or moduleSpec.loader is None:
		raise RuntimeError("Unable to load the word dictionary schema module.")
	module = importlib.util.module_from_spec(moduleSpec)
	moduleSpec.loader.exec_module(module)
	return module


def _getPartOfSpeechTags(definition: str) -> frozenset[str]:
	"""Return recognized part-of-speech tags from a bundled definition."""
	return frozenset(match.casefold() for match in _PART_OF_SPEECH_PATTERN.findall(definition))


def _isShortUppercaseWord(word: str) -> bool:
	"""Return whether a spelling is an ambiguous two- or three-character initialism."""
	return word.isupper() and sum(character.isalnum() for character in word) < 4


def _hasOneVowelGroup(word: str) -> bool:
	"""Return whether a word has one contiguous group of vowel letters."""
	return len(re.findall(r"[aeiouy]+", word)) == 1


def _requiresFinalConsonantDoubling(word: str) -> bool:
	"""Return whether a short CVC word doubles its final consonant."""
	if word in _DOUBLED_FINAL_CONSONANT_WORDS:
		return True
	if len(word) < 3 or not word.isalpha() or not _hasOneVowelGroup(word):
		return False
	if word.endswith("iz") and not word.endswith("zz") and len(word) <= 4:
		return True
	first, vowel, final = word[-3:]
	return first not in "aeiou" and vowel in "aeiou" and final not in "aeiouwxy"


def _allowsOptionalFinalConsonantDoubling(word: str) -> bool:
	"""Return whether common US and UK spellings differ by consonant doubling."""
	return word in _OPTIONALLY_DOUBLED_WORDS or (
		len(word) >= 3 and word.endswith("l") and word[-2] in "aeiouy" and word[-3] not in "aeiouy"
	)


def _iterPluralForms(lemma: str) -> Iterator[str]:
	"""Yield supported regular plural and third-person forms."""
	if lemma.endswith(_GREEK_IS_ENDINGS):
		yield f"{lemma[:-2]}es"
	elif lemma.endswith("y") and len(lemma) > 1 and lemma[-2] not in "aeiou":
		yield f"{lemma[:-1]}ies"
	elif lemma.endswith(_CH_TAKES_S_ENDINGS):
		yield f"{lemma}s"
	elif lemma.endswith(("s", "x", "z", "ch", "sh")):
		if lemma.endswith("z") and _requiresFinalConsonantDoubling(lemma):
			yield f"{lemma}{lemma[-1]}es"
		else:
			yield f"{lemma}es"
	else:
		yield f"{lemma}s"
	if lemma in _O_TAKES_ES_WORDS:
		yield f"{lemma}es"
	if lemma.endswith(_F_TO_VES_ENDINGS):
		endingLength = 2 if lemma.endswith("fe") else 1
		yield f"{lemma[:-endingLength]}ves"
	if lemma.endswith("man") and lemma not in _MAN_TAKES_S_WORDS:
		yield f"{lemma[:-3]}men"


def _iterPastForms(lemma: str) -> Iterator[str]:
	"""Yield supported regular past-tense forms."""
	if lemma.endswith("e"):
		yield f"{lemma}d"
	elif lemma.endswith("y") and len(lemma) > 1 and lemma[-2] not in "aeiou":
		yield f"{lemma[:-1]}ied"
	elif lemma.endswith("c"):
		yield f"{lemma}ked"
	elif _requiresFinalConsonantDoubling(lemma):
		yield f"{lemma}{lemma[-1]}ed"
	elif _allowsOptionalFinalConsonantDoubling(lemma):
		yield f"{lemma}ed"
		yield f"{lemma}{lemma[-1]}ed"
	else:
		yield f"{lemma}ed"


def _iterProgressiveForms(lemma: str) -> Iterator[str]:
	"""Yield supported regular present-participle forms."""
	if lemma.endswith("ie"):
		yield f"{lemma[:-2]}ying"
	elif lemma.endswith("e"):
		if lemma.endswith(_E_RETAINED_BEFORE_ING_ENDINGS):
			yield f"{lemma}ing"
		elif lemma in _OPTIONAL_E_BEFORE_ING_WORDS:
			yield f"{lemma[:-1]}ing"
			yield f"{lemma}ing"
		else:
			yield f"{lemma[:-1]}ing"
	elif lemma.endswith("c"):
		yield f"{lemma}king"
	elif _requiresFinalConsonantDoubling(lemma):
		yield f"{lemma}{lemma[-1]}ing"
	elif _allowsOptionalFinalConsonantDoubling(lemma):
		yield f"{lemma}ing"
		yield f"{lemma}{lemma[-1]}ing"
	else:
		yield f"{lemma}ing"


def _iterDegreeForms(lemma: str, isSuperlative: bool) -> Iterator[str]:
	"""Yield supported regular comparative or superlative forms."""
	suffix = "est" if isSuperlative else "er"
	if lemma.endswith("e"):
		yield f"{lemma}{'st' if isSuperlative else 'r'}"
	elif lemma.endswith("y") and len(lemma) > 1 and lemma[-2] not in "aeiou":
		yield f"{lemma[:-1]}i{suffix}"
	elif _requiresFinalConsonantDoubling(lemma):
		yield f"{lemma}{lemma[-1]}{suffix}"
	else:
		yield f"{lemma}{suffix}"


def _iterRegularForms(lemma: str, exchangeType: str) -> Iterator[str]:
	"""Yield forms produced by transparent spelling rules for one exchange type."""
	if exchangeType in ("s", "3"):
		yield from _iterPluralForms(lemma)
	elif exchangeType in ("p", "d"):
		yield from _iterPastForms(lemma)
	elif exchangeType == "i":
		yield from _iterProgressiveForms(lemma)
	else:
		yield from _iterDegreeForms(lemma, isSuperlative=exchangeType == "t")


def _readObservedForms(
	lemmaPath: Path,
	dataModule: ModuleType,
) -> dict[str, set[str]]:
	"""Read observed forms from ECDICT's combined lemma database."""
	observedForms: dict[str, set[str]] = defaultdict(set)
	with lemmaPath.open("r", encoding="utf-8") as sourceFile:
		for line in sourceFile:
			heading, separator, forms = line.strip().partition(" -> ")
			lemma, countSeparator, count = heading.rpartition("/")
			if not separator or not countSeparator or not count.isdecimal():
				continue
			foldedLemma = dataModule.canonicalizeWord(lemma).casefold()
			if not dataModule.isLookupWord(foldedLemma):
				continue
			for form in forms.split(","):
				foldedForm = dataModule.canonicalizeWord(form).casefold()
				if dataModule.isLookupWord(foldedForm):
					observedForms[foldedLemma].add(foldedForm)
	if not observedForms:
		raise ValueError("ECDICT lemma data contains no supported forms.")
	return observedForms


def _getSupportedTypes(
	form: str,
	lemma: str,
	relation: _Relation,
	allowedTypes: set[str],
	forwardForms: dict[str, dict[str, set[str]]],
	observedForms: dict[str, set[str]],
) -> set[str]:
	"""Return relation types supported by spelling or lemma-database evidence."""
	supportedTypes: set[str] = set()
	isObserved = form in observedForms.get(lemma, set())
	for exchangeType in allowedTypes:
		isTransparent = form in _iterRegularForms(lemma, exchangeType)
		isCorpusSupported = isObserved and exchangeType not in _DEGREE_TYPES
		if exchangeType in relation.forwardTypes and (isTransparent or isCorpusSupported):
			supportedTypes.add(exchangeType)
			continue
		if exchangeType not in relation.reverseTypes:
			continue
		knownForwardForms = forwardForms.get(lemma, {}).get(exchangeType)
		if knownForwardForms and form not in knownForwardForms:
			continue
		if isTransparent or isCorpusSupported:
			supportedTypes.add(exchangeType)
	return supportedTypes


def _readRelations(
	ecdictPath: Path,
	dataModule: ModuleType,
) -> tuple[dict[str, dict[str, _Relation]], dict[str, dict[str, set[str]]]]:
	"""Read authoritative lemma rows and separate reverse form pointers."""
	relations: dict[str, dict[str, _Relation]] = defaultdict(dict)
	forwardForms: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
	with ecdictPath.open("r", encoding="utf-8-sig", newline="") as sourceFile:
		for row in csv.DictReader(sourceFile):
			word = dataModule.canonicalizeWord(cast(str, row["word"]))
			parts: list[tuple[str, str]] = []
			for item in cast(str, row["exchange"]).split("/"):
				code, separator, value = item.partition(":")
				if separator and value:
					parts.append((code, dataModule.canonicalizeWord(value)))
			if not parts:
				continue
			lemma = next((value for code, value in parts if code == "0"), None)
			if lemma is not None:
				formTypes = next((value for code, value in parts if code == "1"), "")
				for exchangeType in formTypes:
					if exchangeType not in _EXCHANGE_TYPES:
						continue
					relation = relations[word.casefold()].setdefault(lemma.casefold(), _Relation())
					relation.reverseTypes.add(exchangeType)
					relation.lemmaSpellings.add(lemma)
				continue

			for exchangeType, form in parts:
				if exchangeType not in _EXCHANGE_TYPES:
					continue
				foldedForm = form.casefold()
				forwardForms[word.casefold()][exchangeType].add(foldedForm)
				relation = relations[foldedForm].setdefault(word.casefold(), _Relation())
				relation.forwardTypes.add(exchangeType)
				relation.lemmaSpellings.add(word)
	return relations, forwardForms


def buildInflections(
	ecdictPath: Path,
	lemmaPath: Path,
	dictionaryPath: Path,
) -> tuple[dict[str, str | list[str]], dict[str, int]]:
	"""Return deterministic aliases and statistics for a dictionary source."""
	dataModule = _loadDataModule()
	rawEntries = json.loads(dictionaryPath.read_text(encoding="utf-8"))
	compiledData = cast(dict[str, Any], dataModule.createDictionaryData(rawEntries))
	entries = cast(dict[str, str], compiledData["entries"])
	casefoldAliases = cast(dict[str, str | tuple[str, ...]], compiledData["casefoldAliases"])
	normalizedAliases = cast(dict[str, str | tuple[str, ...]], compiledData["normalizedAliases"])

	def resolveEntryKey(text: str) -> str | None:
		"""Resolve text through lookup stages which precede inflections."""
		word = dataModule.canonicalizeWord(text)
		if not dataModule.isLookupWord(word):
			return None
		if word in entries:
			return word
		foldedWord = word.casefold()
		if foldedWord in entries:
			return foldedWord
		casefoldTarget = casefoldAliases.get(foldedWord)
		if type(casefoldTarget) is str:
			return casefoldTarget
		if "'" not in word:
			normalizedTarget = normalizedAliases.get(dataModule.normalizeKey(word))
			if type(normalizedTarget) is str:
				return normalizedTarget
		return None

	def hasHigherPriorityMatch(text: str) -> bool:
		"""Return whether exact or case-insensitive lookup must win."""
		word = dataModule.canonicalizeWord(text)
		foldedWord = word.casefold()
		return word in entries or foldedWord in entries or foldedWord in casefoldAliases

	def getAllowedTypes(target: str, relation: _Relation) -> set[str]:
		"""Return exchange types compatible with the target's meaning and casing."""
		definition = entries[target]
		tags = _getPartOfSpeechTags(definition)
		allTypes = relation.forwardTypes.union(relation.reverseTypes)
		if tags:
			allowedTypes = {
				exchangeType for exchangeType in allTypes if tags.intersection(_EXPECTED_TAGS[exchangeType])
			}
		else:
			if _ABBREVIATION_PATTERN.search(definition) is not None:
				return set()
			allowedTypes = allTypes.difference(_DEGREE_TYPES)
			if any(word != word.casefold() for word in relation.lemmaSpellings):
				return set()

		if any(word != word.casefold() for word in relation.lemmaSpellings):
			allowedTypes.difference_update(_DEGREE_TYPES)
		if _PROPER_NAME_PATTERN.search(definition):
			allowedTypes.discard("s")
		if (
			any(_isShortUppercaseWord(word) for word in relation.lemmaSpellings)
			and _ABBREVIATION_PATTERN.search(definition) is None
		):
			return set()
		return allowedTypes

	regularTargets: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
	for entryKey, definition in entries.items():
		lemma = dataModule.canonicalizeWord(entryKey).casefold()
		if not dataModule.isLookupWord(lemma) or lemma.endswith("."):
			continue
		tags = _getPartOfSpeechTags(definition)
		exchangeTypes: set[str] = set()
		if tags.intersection(_NOUN_TAGS) and not _PROPER_NAME_PATTERN.search(definition):
			exchangeTypes.add("s")
		if tags.intersection(_VERB_TAGS):
			exchangeTypes.update(("p", "d", "i", "3"))
		if tags.intersection(_DEGREE_TAGS):
			exchangeTypes.update(_DEGREE_TYPES)
		for exchangeType in exchangeTypes:
			for form in _iterRegularForms(lemma, exchangeType):
				regularTargets[form][entryKey].add(exchangeType)

	observedForms = _readObservedForms(lemmaPath, dataModule)
	relations, forwardForms = _readRelations(ecdictPath, dataModule)
	aliases: dict[str, str | list[str]] = {}
	stats: defaultdict[str, int] = defaultdict(int)
	for form, targetRelations in sorted(relations.items()):
		if (
			form != dataModule.canonicalizeWord(form)
			or form.endswith(".")
			or not dataModule.isLookupWord(form)
		):
			stats["invalidForms"] += 1
			continue
		if hasHigherPriorityMatch(form):
			stats["earlierMatches"] += 1
			continue
		if form in _REJECTED_FORMS:
			stats["rejectedSourceForms"] += 1
			continue

		candidateTypes: dict[str, set[str]] = defaultdict(set)
		for lemma, relation in targetRelations.items():
			target = resolveEntryKey(lemma)
			if target is None:
				continue
			allowedTypes = getAllowedTypes(target, relation)
			supportedTypes = _getSupportedTypes(
				form,
				lemma,
				relation,
				allowedTypes,
				forwardForms,
				observedForms,
			)
			candidateTypes[target].update(supportedTypes)
		candidateTypes = {target: types for target, types in candidateTypes.items() if types}
		if not candidateTypes:
			stats["rejectedRelations"] += 1
			continue

		taggedCandidates = {target for target in candidateTypes if _getPartOfSpeechTags(entries[target])}
		if taggedCandidates:
			candidateTypes = {
				target: types for target, types in candidateTypes.items() if target in taggedCandidates
			}

		competingTypes = set[str]().union(*candidateTypes.values())
		# Noun plurals and third-person singular verbs use the same surface forms.
		if competingTypes.intersection(_NOUN_OR_THIRD_PERSON_TYPES):
			competingTypes.update(_NOUN_OR_THIRD_PERSON_TYPES)
		competingTargets = {
			target
			for target, exchangeTypes in regularTargets.get(form, {}).items()
			if exchangeTypes.intersection(competingTypes)
			and (
				target in candidateTypes
				or form in observedForms.get(dataModule.canonicalizeWord(target).casefold(), set())
			)
		}
		candidateTargetKeys = set[str](candidateTypes).union(competingTargets)

		candidateTargetsByDefinition: dict[str, str] = {}
		for target in sorted(
			candidateTargetKeys,
			key=lambda target: (len(target), target.casefold(), target),
		):
			_ = candidateTargetsByDefinition.setdefault(entries[target], target)
		if len(candidateTargetsByDefinition) != 1:
			aliases[form] = list(candidateTargetsByDefinition.values())[:_MAX_AMBIGUOUS_TARGETS]
			stats["ambiguousForms"] += 1
			continue
		aliases[form] = min(
			candidateTypes,
			key=lambda target: (len(target), target.casefold(), target),
		)
		stats["generatedAliases"] += 1

	reviewedTargets = _MANUAL_TARGETS | _REVIEWED_ADDITIONAL_TARGETS
	if len(reviewedTargets) != len(_MANUAL_TARGETS) + len(_REVIEWED_ADDITIONAL_TARGETS):
		raise ValueError("Reviewed inflection targets overlap.")
	for form, requestedTargets in reviewedTargets.items():
		if hasHigherPriorityMatch(form):
			continue
		requestedTargetSequence = (
			(requestedTargets,) if isinstance(requestedTargets, str) else requestedTargets
		)
		targets: list[str] = []
		for requestedTarget in requestedTargetSequence:
			target = resolveEntryKey(requestedTarget)
			if target is None:
				raise ValueError(f"Manual inflection target is unavailable: {requestedTarget}")
			targets.append(target)
		aliases[form] = targets[0] if len(targets) == 1 else targets
	stats["manualTargets"] = len(_MANUAL_TARGETS)
	stats["reviewedAdditionalTargets"] = len(_REVIEWED_ADDITIONAL_TARGETS)
	stats["finalAliases"] = sum(type(target) is str for target in aliases.values())
	stats["explicitAmbiguities"] = sum(type(target) is list for target in aliases.values())
	return dict(sorted(aliases.items())), dict(sorted(stats.items()))
