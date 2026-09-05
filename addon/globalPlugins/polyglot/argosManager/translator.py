# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Translation with installed Argos Translate models.

The pipeline follows ``argostranslate.translate.apply_packaged_translation``: paragraphs are kept
apart, each is split into sentences, every sentence is tokenized with the tokenizer its package
carries, and the sentences of a paragraph are translated as one CTranslate2 batch.

A package carries one of two tokenizers, and Polyglot picks the same one Argos Translate would.
Most carry a SentencePiece model. The rest, built from OPUS-MT, carry BPE merges instead, and are
tokenized the way those models were trained: Moses punctuation normalization, Moses tokenization,
then the package's own merges, undone by Moses detokenization on the way back.

Argos Translate itself is not used. It imports Stanza, and through it PyTorch, for sentence boundary
detection alone, which would turn a 20 MB download into a multi-gigabyte one; the sentence splitting
here is done with the punctuation rules below instead.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

import addonHandler
from logHandler import log

from .catalog import PIVOT_LANGUAGE, normalizeLanguageCode
from .installer import ArgosInstaller, InstalledPackage

addonHandler.initTranslation()

#: The longest sentence handed to a model before it is broken at a space.
MAX_SENTENCE_LENGTH = 250

#: How many models are kept in memory at once. Each one costs roughly 100 MB.
DEFAULT_MAX_LOADED_MODELS = 2

#: Where a sentence ends: full-width punctuation, which needs no following space, or Latin
#: punctuation followed by one. Closing quotes and brackets stay with the sentence they close.
_SENTENCE_END = re.compile(
	r"[。！？｡][\"'”’)\]）]*"  # Scripts that do not put a space between sentences.
	r"|[.!?…][\"'”’)\]）]*(?=\s|$)",  # Everything else, where a space or the end follows.
)

#: The marker SentencePiece writes in place of a space.
_SPACE_MARKER = "▁"

#: What BPE appends to every subword that is not the end of a word.
_BPE_SEPARATOR = "@@"


def splitSentences(paragraph: str) -> list[str]:
	"""Split one paragraph into sentences short enough for a model to translate well."""
	sentences: list[str] = []
	for sentence in _splitOnPunctuation(paragraph):
		sentences.extend(_splitLongSentence(sentence))
	return sentences


def _splitOnPunctuation(paragraph: str) -> list[str]:
	"""Split a paragraph after each sentence-ending punctuation mark."""
	sentences: list[str] = []
	start = 0
	for match in _SENTENCE_END.finditer(paragraph):
		sentence = paragraph[start : match.end()].strip()
		if sentence:
			sentences.append(sentence)
		start = match.end()
	remainder = paragraph[start:].strip()
	if remainder:
		sentences.append(remainder)
	return sentences


def _splitLongSentence(sentence: str) -> list[str]:
	"""Break a sentence the punctuation rules could not shorten, preferring spaces."""
	if len(sentence) <= MAX_SENTENCE_LENGTH:
		return [sentence]
	parts: list[str] = []
	remaining = sentence
	while len(remaining) > MAX_SENTENCE_LENGTH:
		splitIndex = remaining.rfind(" ", 0, MAX_SENTENCE_LENGTH)
		if splitIndex <= 0:
			splitIndex = MAX_SENTENCE_LENGTH
		parts.append(remaining[:splitIndex])
		remaining = remaining[splitIndex:].lstrip()
	if remaining:
		parts.append(remaining)
	return parts


class SentencePieceTokenizer:
	"""Splits sentences into the subwords a package's SentencePiece model was trained on."""

	def __init__(self, package: InstalledPackage, sentencepiece: Any) -> None:
		"""Load one package's SentencePiece model."""
		self._processor = sentencepiece.SentencePieceProcessor(model_file=str(package.tokenizerPath))

	def encode(self, sentence: str) -> list[str]:
		"""Return the subwords one sentence is made of."""
		return self._processor.encode(sentence, out_type=str)

	def decode(self, tokens: list[str]) -> str:
		"""Return the text a model's output subwords spell out."""
		return self._processor.decode_pieces(tokens).replace(_SPACE_MARKER, " ")


class BpeTokenizer:
	"""Splits sentences the way the OPUS-MT models behind the BPE packages were trained.

	Moses escapes ``&``, ``<`` and the quote characters as XML entities, which is how they appear
	in these models' vocabularies, and the detokenizer turns them back on the way out.
	"""

	def __init__(
		self,
		package: InstalledPackage,
		punctNormalizerClass: Any,
		tokenizerClass: Any,
		detokenizerClass: Any,
		bpeClass: Any,
	) -> None:
		"""Load one package's BPE merges, and the Moses rules for its two languages."""
		self._normalizer = punctNormalizerClass(package.fromCode)
		self._tokenizer = tokenizerClass(package.fromCode)
		self._detokenizer = detokenizerClass(package.toCode)
		with package.tokenizerPath.open("r", encoding="utf-8") as merges:
			self._bpe = bpeClass(merges)

	def encode(self, sentence: str) -> list[str]:
		"""Return the subwords one sentence is made of."""
		words = self._tokenizer.tokenize(self._normalizer.normalize(sentence))
		return self._bpe.segment_tokens(" ".join(words).strip().split(" "))

	def decode(self, tokens: list[str]) -> str:
		"""Return the text a model's output subwords spell out."""
		words = " ".join(tokens).replace(_BPE_SEPARATOR + " ", "").split(" ")
		return self._detokenizer.detokenize(words)


class LoadedModel:
	"""One Argos package with its model and tokenizer held in memory."""

	def __init__(
		self,
		package: InstalledPackage,
		ctranslate2: Any,
		tokenizer: SentencePieceTokenizer | BpeTokenizer,
		threads: int,
	) -> None:
		"""Load a package's model, over the tokenizer its own files call for."""
		self.package = package
		self.targetPrefix = _readTargetPrefix(package.path)
		self._tokenizer = tokenizer
		self._translator = ctranslate2.Translator(
			str(package.path / "model"),
			device="cpu",
			inter_threads=1,
			intra_threads=threads,
			compute_type="default",
		)

	def translate(self, text: str) -> str:
		"""Translate text with this model, keeping its paragraphs apart."""
		return "\n".join(self._translateParagraph(paragraph) for paragraph in text.split("\n"))

	def _translateParagraph(self, paragraph: str) -> str:
		"""Translate one paragraph as a single batch of sentences."""
		if not paragraph.strip():
			return paragraph
		sentences = splitSentences(paragraph)
		if not sentences:
			return paragraph
		tokenized = [self._tokenizer.encode(sentence) for sentence in sentences]
		targetPrefix = [[self.targetPrefix]] * len(tokenized) if self.targetPrefix else None
		batches = self._translator.translate_batch(
			tokenized,
			target_prefix=targetPrefix,
			replace_unknowns=True,
			max_batch_size=2048,
			batch_type="tokens",
			beam_size=4,
			num_hypotheses=1,
			length_penalty=0.2,
			return_scores=False,
		)
		tokens: list[str] = []
		for batch in batches:
			tokens.extend(batch.hypotheses[0])
		value = self._tokenizer.decode(tokens)
		if self.targetPrefix and value.startswith(self.targetPrefix):
			value = value[len(self.targetPrefix) :]
		return value.lstrip(" ")


class ArgosTranslator:
	"""Translates with installed packages, keeping a bounded number of models in memory."""

	def __init__(
		self,
		installer: ArgosInstaller | None = None,
		maxLoadedModels: int = DEFAULT_MAX_LOADED_MODELS,
	) -> None:
		"""Initialize the translator over the installed packages."""
		self.installer = installer or ArgosInstaller()
		self.maxLoadedModels = max(1, maxLoadedModels)
		self._lock = threading.RLock()
		self._models: dict[str, LoadedModel] = {}
		self._loadOrder: list[str] = []
		self._ctranslate2: Any = None
		self._sentencepiece: Any = None

	@property
	def hasLoadedModels(self) -> bool:
		"""Return whether any model is currently held in memory."""
		with self._lock:
			return bool(self._models)

	def unloadModels(self) -> int:
		"""Release every loaded model, returning how many were unloaded.

		A model keeps its package's files open, so the model manager cannot remove or update a
		package until it is unloaded. The runtime's own libraries stay loaded until NVDA restarts.
		"""
		with self._lock:
			count = len(self._models)
			self._models.clear()
			self._loadOrder.clear()
		if count:
			log.debug("Argos: unloaded %d model(s).", count)
		return count

	def findRoute(self, langFrom: str, langTo: str) -> list[InstalledPackage]:
		"""Return the installed packages translating a direction, pivoting through English.

		:return: One package for a direct direction, two for a pivoted one, and an empty list when
			the installed packages cannot serve the direction.
		"""
		fromCode = normalizeLanguageCode(langFrom)
		toCode = normalizeLanguageCode(langTo)
		if not fromCode or not toCode or fromCode == toCode:
			return []
		installed = {
			(package.fromCode, package.toCode): package for package in self.installer.getInstalledPackages()
		}
		if direct := installed.get((fromCode, toCode)):
			return [direct]
		if fromCode == PIVOT_LANGUAGE or toCode == PIVOT_LANGUAGE:
			return []
		toPivot = installed.get((fromCode, PIVOT_LANGUAGE))
		fromPivot = installed.get((PIVOT_LANGUAGE, toCode))
		if toPivot is None or fromPivot is None:
			return []
		return [toPivot, fromPivot]

	def translate(self, text: str, langFrom: str, langTo: str, threads: int = 0) -> str:
		"""Translate text between two languages with the installed packages.

		:param threads: Processor threads each model may use, or 0 to decide automatically.
		:raises RuntimeError: If the runtime is missing, or no installed package serves the pair.
		"""
		if normalizeLanguageCode(langFrom) == normalizeLanguageCode(langTo):
			return text
		route = self.findRoute(langFrom, langTo)
		if not route:
			raise RuntimeError(
				_("No installed Argos model translates from {source} to {target}.").format(
					source=langFrom,
					target=langTo,
				),
			)
		value = text
		for package in route:
			model = self._getModel(package, threads)
			# One model at a time: CTranslate2 uses its own threads, and two translations at once
			# would compete for them and for the memory the models take up.
			with self._lock:
				value = model.translate(value)
		return value

	def _getModel(self, package: InstalledPackage, threads: int) -> LoadedModel:
		"""Return a package's loaded model, loading it and evicting an old one when needed."""
		with self._lock:
			model = self._models.get(package.key)
			if model is not None and model.package.path == package.path:
				self._touch(package.key)
				return model
			ctranslate2, sentencepiece = self._loadRuntime()
			log.debug("Argos: loading the %s model.", package.key)
			tokenizer = self._createTokenizer(package, sentencepiece)
			model = LoadedModel(package, ctranslate2, tokenizer, self._resolveThreads(threads))
			self._models[package.key] = model
			self._touch(package.key)
			self._evictExtraModels()
			return model

	def _createTokenizer(
		self,
		package: InstalledPackage,
		sentencepiece: Any,
	) -> SentencePieceTokenizer | BpeTokenizer:
		"""Return the tokenizer a package's own files call for.

		:raises RuntimeError: If a BPE package's extras are missing, which a reinstall puts back.
		"""
		if not package.usesBpe:
			return SentencePieceTokenizer(package, sentencepiece)
		return BpeTokenizer(package, *self.installer.runtime.loadBpe())

	def _touch(self, key: str) -> None:
		"""Mark a model as the most recently used one."""
		if key in self._loadOrder:
			self._loadOrder.remove(key)
		self._loadOrder.append(key)

	def _evictExtraModels(self) -> None:
		"""Unload the least recently used models once the cache is over its limit."""
		while len(self._loadOrder) > self.maxLoadedModels:
			evictedKey = self._loadOrder.pop(0)
			if self._models.pop(evictedKey, None) is not None:
				log.debug("Argos: unloaded the %s model to make room.", evictedKey)

	def _resolveThreads(self, threads: int) -> int:
		"""Return the processor threads a model may use.

		Translation runs on a background thread while NVDA keeps speaking, so the default leaves
		room for the rest of NVDA rather than taking every core.
		"""
		if threads > 0:
			return threads
		return max(1, min(4, (os.cpu_count() or 2) - 1))

	def _loadRuntime(self) -> tuple[Any, Any]:
		"""Import the runtime libraries once, and keep them for later translations."""
		if self._ctranslate2 is None or self._sentencepiece is None:
			self._ctranslate2, self._sentencepiece = self.installer.runtime.load()
		return self._ctranslate2, self._sentencepiece


def _readTargetPrefix(packagePath: Path) -> str:
	"""Return a package's target prefix, which a few multi-target models need."""
	metadataPath = packagePath / "metadata.json"
	try:
		metadata = json.loads(metadataPath.read_text(encoding="utf-8-sig"))
	except (OSError, ValueError, UnicodeError):
		return ""
	if not isinstance(metadata, dict):
		return ""
	prefix = metadata.get("target_prefix")
	return prefix if isinstance(prefix, str) else ""


_translator: ArgosTranslator | None = None


def getArgosTranslator() -> ArgosTranslator:
	"""Return the process-wide Argos translator."""
	global _translator
	if _translator is None:
		_translator = ArgosTranslator()
	return _translator
