# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""The Argos Translate package index, and the language-pair rules built on it.

Argos publishes one package per language direction, and nearly all of them translate to or from
English. A pair with no package of its own is therefore served by translating through English, which
is what :meth:`ArgosCatalog.findPackagesForPair` returns.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import addonHandler
import requests

from ..common import languages

addonHandler.initTranslation()

#: The package index Argos Translate itself ships with.
DEFAULT_INDEX_URL = "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json"

#: Environment variable that overrides the index URL, for testing a different package channel.
_INDEX_URL_ENV = "POLYGLOT_ARGOS_INDEX_URL"

#: The language every Argos package pivots through when no direct package exists.
PIVOT_LANGUAGE = "en"

#: How long to wait for the index, which is a small file from a code-hosting site.
_INDEX_TIMEOUT = 30


def getString(data: dict[str, Any], key: str) -> str:
	"""Read a JSON string value with a conservative fallback."""
	value = data.get(key, "")
	return value if isinstance(value, str) else ""


@dataclass(frozen=True)
class ArgosPackage:
	"""One translation direction offered by the Argos package index."""

	code: str = ""
	fromCode: str = ""
	fromName: str = ""
	toCode: str = ""
	toName: str = ""
	packageVersion: str = ""
	argosVersion: str = ""
	links: tuple[str, ...] = ()

	@classmethod
	def fromJson(cls, data: Any) -> "ArgosPackage | None":
		"""Create a package from one index entry, or None when the entry is unusable."""
		if not isinstance(data, dict):
			return None
		rawLinks = data.get("links")
		links = tuple(
			link
			for link in (rawLinks if isinstance(rawLinks, list) else [])
			if isinstance(link, str) and urlparse(link).scheme in ("http", "https")
		)
		package = cls(
			code=getString(data, "code"),
			fromCode=getString(data, "from_code"),
			fromName=getString(data, "from_name"),
			toCode=getString(data, "to_code"),
			toName=getString(data, "to_name"),
			packageVersion=getString(data, "package_version"),
			argosVersion=getString(data, "argos_version"),
			links=links,
		)
		if not package.fromCode or not package.toCode or not package.links:
			return None
		return package

	@property
	def key(self) -> str:
		"""Return the stable identifier for this direction, independent of its version."""
		return self.code or f"translate-{self.fromCode}_{self.toCode}"

	@property
	def downloadUrl(self) -> str:
		"""Return the URL the package archive is downloaded from."""
		return self.links[0]

	@property
	def directoryName(self) -> str:
		"""Return the directory this package is installed into.

		Argos names package directories after the direction and version, as ``translate-en_fr-1_9``,
		and this follows that convention so an installed directory says which version it holds.
		"""
		version = self.packageVersion.replace(".", "_")
		return f"{self.key}-{version}" if version else self.key


@dataclass
class ArgosCatalog:
	"""The package index, with the lookups Polyglot needs on top of it."""

	generatedAt: str = ""
	sourceUrl: str = ""
	packages: list[ArgosPackage] = field(default_factory=list)
	byKey: dict[str, ArgosPackage] = field(default_factory=dict)

	@classmethod
	def loadRemote(cls, indexUrl: str) -> "ArgosCatalog":
		"""Load the index from an HTTP or HTTPS URL."""
		response = requests.get(indexUrl, timeout=_INDEX_TIMEOUT)
		_unused = response.raise_for_status()
		catalog = cls.deserialize(response.text)
		catalog.sourceUrl = indexUrl
		return catalog

	@classmethod
	def loadBundled(cls) -> "ArgosCatalog":
		"""Load the index snapshot that ships with the add-on."""
		path = Path(__file__).with_name("resources") / "index.json"
		if not path.is_file():
			raise RuntimeError(_("The bundled Argos package index is missing."))
		return cls.deserialize(path.read_text(encoding="utf-8-sig"))

	@classmethod
	def loadCached(cls, cachePath: Path) -> "ArgosCatalog | None":
		"""Load the last index that was downloaded successfully, or None when there is none."""
		if not cachePath.is_file():
			return None
		try:
			return cls.deserialize(cachePath.read_text(encoding="utf-8-sig"))
		except (OSError, RuntimeError, ValueError, UnicodeError):
			return None

	@classmethod
	def deserialize(cls, text: str) -> "ArgosCatalog":
		"""Read an index, in either the plain Argos form or Polyglot's snapshot wrapper.

		The Argos index is a bare JSON array. Polyglot wraps that array in an object when it saves a
		snapshot, so it can record where and when the snapshot came from, and both forms are read here.
		"""
		if not text.strip():
			raise RuntimeError(_("The Argos package index is empty."))
		rawData = json.loads(text)
		generatedAt = ""
		sourceUrl = ""
		if isinstance(rawData, dict):
			generatedAt = getString(rawData, "generatedAt")
			sourceUrl = getString(rawData, "sourceUrl")
			rawPackages = rawData.get("packages")
		else:
			rawPackages = rawData
		if not isinstance(rawPackages, list):
			raise RuntimeError(_("The Argos package index is not in a form Polyglot understands."))
		packages: list[ArgosPackage] = []
		byKey: dict[str, ArgosPackage] = {}
		for item in rawPackages:
			package = ArgosPackage.fromJson(item)
			if package is None:
				continue
			existing = byKey.get(package.key)
			if existing is not None:
				# The index may list several versions of a direction; the newest one wins.
				if compareVersions(package.packageVersion, existing.packageVersion) <= 0:
					continue
				packages[packages.index(existing)] = package
				byKey[package.key] = package
				continue
			packages.append(package)
			byKey[package.key] = package
		if not packages:
			raise RuntimeError(_("The Argos package index lists no usable packages."))
		packages.sort(key=lambda item: (pairSortName(item), item.key))
		return cls(generatedAt=generatedAt, sourceUrl=sourceUrl, packages=packages, byKey=byKey)

	def serialize(self) -> str:
		"""Return this catalog as a Polyglot snapshot, for saving next to the installed packages."""
		return json.dumps(
			{
				"schemaVersion": 1,
				"generatedAt": self.generatedAt,
				"sourceUrl": self.sourceUrl,
				"packages": [
					{
						"code": package.code,
						"from_code": package.fromCode,
						"from_name": package.fromName,
						"to_code": package.toCode,
						"to_name": package.toName,
						"package_version": package.packageVersion,
						"argos_version": package.argosVersion,
						"links": list(package.links),
					}
					for package in self.packages
				],
			},
			ensure_ascii=False,
		)

	def getLanguageCodes(self) -> list[str]:
		"""Return every language the index can translate from or to, in a stable order."""
		codes: set[str] = set()
		for package in self.packages:
			codes.add(package.fromCode)
			codes.add(package.toCode)
		return sorted(codes)

	def findPackageForPair(self, sourceLanguage: str, targetLanguage: str) -> ArgosPackage | None:
		"""Return the package that translates one direction, or None when there is none."""
		sourceLanguage = normalizeLanguageCode(sourceLanguage)
		targetLanguage = normalizeLanguageCode(targetLanguage)
		if not sourceLanguage or not targetLanguage or sourceLanguage == targetLanguage:
			return None
		for package in self.packages:
			if package.fromCode == sourceLanguage and package.toCode == targetLanguage:
				return package
		return None

	def findPackagesForPair(self, sourceLanguage: str, targetLanguage: str) -> list[ArgosPackage]:
		"""Return every package needed for a direction, pivoting through English when needed.

		:return: One package for a direct direction, two for a pivoted one, and an empty list when
			the index cannot serve the direction at all.
		"""
		sourceLanguage = normalizeLanguageCode(sourceLanguage)
		targetLanguage = normalizeLanguageCode(targetLanguage)
		if not sourceLanguage or not targetLanguage or sourceLanguage == targetLanguage:
			return []
		if direct := self.findPackageForPair(sourceLanguage, targetLanguage):
			return [direct]
		if sourceLanguage == PIVOT_LANGUAGE or targetLanguage == PIVOT_LANGUAGE:
			return []
		toPivot = self.findPackageForPair(sourceLanguage, PIVOT_LANGUAGE)
		fromPivot = self.findPackageForPair(PIVOT_LANGUAGE, targetLanguage)
		if toPivot is None or fromPivot is None:
			return []
		return [toPivot, fromPivot]

	def isPairSupported(self, sourceLanguage: str, targetLanguage: str) -> bool:
		"""Return whether the index can translate a direction, directly or through English."""
		return bool(self.findPackagesForPair(sourceLanguage, targetLanguage))


def normalizeIndexUrl(inputUrl: str | None) -> str:
	"""Normalize an index URL, appending index.json to a directory URL.

	:raises RuntimeError: If the URL is not an HTTP or HTTPS URL.
	"""
	indexUrl = (inputUrl or DEFAULT_INDEX_URL).strip() or DEFAULT_INDEX_URL
	parsed = urlparse(indexUrl)
	if parsed.scheme not in ("http", "https") or not parsed.netloc:
		raise RuntimeError(_("The Argos package index URL must be an HTTP or HTTPS URL."))
	if not parsed.query and not parsed.path.lower().endswith(".json"):
		indexUrl = indexUrl.rstrip("/") + "/index.json"
	return indexUrl


def resolveInitialIndexUrl(savedIndexUrl: str = "") -> str:
	"""Resolve the index URL from the environment, saved settings, or the default."""
	for value in (os.environ.get(_INDEX_URL_ENV), savedIndexUrl, DEFAULT_INDEX_URL):
		try:
			return normalizeIndexUrl(value)
		except RuntimeError:
			continue
	return DEFAULT_INDEX_URL


#: Codes other engines use for traditional Chinese, which Argos calls ``zt``.
_TRADITIONAL_CHINESE_CODES = ("zt", "cht", "zh-tw", "zh-hk", "zh-mo")


def normalizeLanguageCode(code: str) -> str:
	"""Normalize a language code to the form the Argos index uses.

	Argos codes are plain two-letter subtags, with two of its own: ``pb`` for Brazilian Portuguese
	and ``zt`` for traditional Chinese. Regional forms Polyglot's other engines use are mapped onto
	them, so a target such as ``zh-Hant`` finds the traditional Chinese package.
	"""
	normalized = (code or "").replace("_", "-")
	lowerCode = normalized.lower()
	if lowerCode in ("auto", "und", ""):
		return ""
	if lowerCode in ("he", "iw"):
		return "he"
	if lowerCode in ("nb", "no", "nn"):
		return "nb"
	if lowerCode in ("pb", "pt-br"):
		return "pb"
	if lowerCode in _TRADITIONAL_CHINESE_CODES or lowerCode.startswith("zh-hant"):
		return "zt"
	if lowerCode.startswith("zh"):
		return "zh"
	if lowerCode in ("tl", "fil"):
		return "tl"
	return lowerCode.split("-", 1)[0]


def compareVersions(left: str, right: str) -> int:
	"""Compare two Argos package versions, which are dotted numbers such as ``1.9``.

	:return: A negative number when left is older, zero when they match, positive when it is newer.
	"""
	leftParts = _versionParts(left)
	rightParts = _versionParts(right)
	length = max(len(leftParts), len(rightParts))
	for index in range(length):
		leftPart = leftParts[index] if index < len(leftParts) else 0
		rightPart = rightParts[index] if index < len(rightParts) else 0
		if leftPart != rightPart:
			return -1 if leftPart < rightPart else 1
	return 0


def _versionParts(version: str) -> list[int]:
	"""Return a version's numeric parts, ignoring anything that is not a number."""
	parts: list[int] = []
	for part in (version or "").split("."):
		digits = "".join(character for character in part if character.isdigit())
		parts.append(int(digits) if digits else 0)
	return parts


def languageName(code: str) -> str:
	"""Return a localized display name for a language code."""
	return languages.getLanguageName(code)


def pairDisplayName(package: ArgosPackage) -> str:
	"""Return a package's name as a language pair, in Polyglot's own language names."""
	return _("{source} to {target}").format(
		source=languageName(package.fromCode),
		target=languageName(package.toCode),
	)


def pairSortName(package: ArgosPackage) -> str:
	"""Return the name a package is sorted by in the model manager."""
	return pairDisplayName(package).casefold()
