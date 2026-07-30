# -*- coding: utf-8 -*-

# Copyright (C) 2025-2026 cary-rowen <manchen_0528@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

import importlib
import inspect
import pkgutil
from typing import Any

from logHandler import log

from . import engines
from .engine import TranslationEngine

_engineInstances: list[TranslationEngine] | None = None


def _scanAndLoadEngines() -> None:
	global _engineInstances
	log.debug("First-time scan: Loading translation engines...")
	_engineInstances = []
	for _, name, _ in pkgutil.iter_modules(engines.__path__, engines.__name__ + "."):
		try:
			module = importlib.import_module(name)
			for _, memberObj in inspect.getmembers(module):
				if (
					inspect.isclass(memberObj)
					and issubclass(memberObj, TranslationEngine)
					and memberObj is not TranslationEngine
					and not inspect.isabstract(memberObj)
				):
					instance: TranslationEngine = memberObj()
					_engineInstances.append(instance)
					log.debug(f"Successfully loaded engine: {instance.name} (ID: {instance.id})")
		except Exception:
			log.error(f"Failed to load engine module '{name}'", exc_info=True)
	if not _engineInstances:
		log.warning(
			"""No translation engines were loaded successfully. This may be due to errors in the engine modules or an issue with the add-on installation. Translation functionality will not be available.""",
		)
	assert _engineInstances is not None
	_engineInstances.sort(key=lambda e: e.name)


def getAllEngines() -> list[TranslationEngine]:
	"""Return all discovered concrete translation engines."""
	global _engineInstances
	if _engineInstances is None:
		_scanAndLoadEngines()
	assert _engineInstances is not None
	return _engineInstances


def _getEngineConfig(engineId: str) -> dict[str, Any]:
	"""Return the saved configuration section for an engine."""
	from ..common import config

	conf = config.getConfig()
	return conf["engines"].get(engineId, {})


def getEnabledEngines() -> list[TranslationEngine]:
	"""Return loaded engines enabled by the current configuration."""
	return [engine for engine in getAllEngines() if engine.isEnabled(_getEngineConfig(engine.id))]


def getNextEnabledEngine(currentId: str, isForward: bool = True) -> TranslationEngine | None:
	"""Return the next enabled engine, or None when none are enabled."""
	allEngines = getAllEngines()
	if not allEngines:
		return None
	engineIds = [engine.id for engine in allEngines]
	try:
		currentIndex = engineIds.index(currentId)
	except ValueError:
		currentIndex = -1 if isForward else 0
	step = 1 if isForward else -1
	for offset in range(1, len(allEngines) + 1):
		newIndex = (currentIndex + (step * offset)) % len(allEngines)
		candidate = allEngines[newIndex]
		if candidate.isEnabled(_getEngineConfig(candidate.id)):
			return candidate
	return None


def getEngineById(engineId: str) -> TranslationEngine:
	"""Return the loaded engine matching engineId.

	:raises ValueError: If no loaded engine uses the requested ID.
	"""
	allEngines = getAllEngines()
	for engine in allEngines:
		if engine.id == engineId:
			return engine
	raise ValueError(f"Engine with ID '{engineId}' not found.")
