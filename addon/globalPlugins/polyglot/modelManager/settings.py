# -*- coding: utf-8 -*-
# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Persistent settings for the native ChromeAI model manager."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ModelManagerSettings:
	"""Stores model manager settings outside NVDA configuration."""

	catalogUrl: str = ""

	@classmethod
	def load(cls, polyglotRoot: Path) -> "ModelManagerSettings":
		"""Load settings from the Polyglot local app data directory."""
		try:
			path = cls.settingsPath(polyglotRoot)
			if not path.is_file():
				return cls()
			rawData = json.loads(path.read_text(encoding="utf-8-sig"))
			if not isinstance(rawData, dict):
				return cls()
			return cls(catalogUrl=str(rawData.get("CatalogUrl") or rawData.get("catalogUrl") or ""))
		except Exception:
			return cls()

	def save(self, polyglotRoot: Path) -> None:
		"""Save settings atomically."""
		path = self.settingsPath(polyglotRoot)
		path.parent.mkdir(parents=True, exist_ok=True)
		tempPath = path.with_name(path.name + ".tmp")
		tempPath.write_text(
			json.dumps({"CatalogUrl": self.catalogUrl}, ensure_ascii=False, indent=2),
			encoding="utf-8",
		)
		tempPath.replace(path)

	@staticmethod
	def settingsPath(polyglotRoot: Path) -> Path:
		"""Return the settings file path used by both native and standalone managers."""
		return polyglotRoot / "ChromeAIModelManager" / "settings.json"


def getString(data: dict[str, Any], key: str) -> str:
	"""Read a JSON string value with a conservative fallback."""
	value = data.get(key, "")
	return value if isinstance(value, str) else ""
