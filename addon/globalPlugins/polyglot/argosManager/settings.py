# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Persistent settings for the Argos model manager."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ArgosManagerSettings:
	"""Stores model manager settings outside NVDA configuration.

	These belong to the downloaded models rather than to a configuration profile, so they live next
	to the models themselves and are shared by every profile.
	"""

	indexUrl: str = ""

	@classmethod
	def load(cls, polyglotRoot: Path) -> "ArgosManagerSettings":
		"""Load settings from the Polyglot local application data directory."""
		try:
			path = cls.settingsPath(polyglotRoot)
			if not path.is_file():
				return cls()
			rawData = json.loads(path.read_text(encoding="utf-8-sig"))
			if not isinstance(rawData, dict):
				return cls()
			return cls(indexUrl=str(rawData.get("IndexUrl") or rawData.get("indexUrl") or ""))
		except Exception:
			return cls()

	def save(self, polyglotRoot: Path) -> None:
		"""Save settings atomically."""
		path = self.settingsPath(polyglotRoot)
		path.parent.mkdir(parents=True, exist_ok=True)
		tempPath = path.with_name(path.name + ".tmp")
		_unused = tempPath.write_text(
			json.dumps({"IndexUrl": self.indexUrl}, ensure_ascii=False, indent=2),
			encoding="utf-8",
		)
		_unused = tempPath.replace(path)

	@staticmethod
	def settingsPath(polyglotRoot: Path) -> Path:
		"""Return the model manager settings file path."""
		return polyglotRoot / "Argos" / "settings.json"
