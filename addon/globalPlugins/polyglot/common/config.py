# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

import config as nvdaConfig
import extensionPoints
from typing import Any

_CONFIG_SECTION = "modernTranslate"
post_localDictionarySettingsChanged = extensionPoints.Action()


def getConfigSectionName() -> str:
	"""Return the NVDA configuration section used by Polyglot."""
	return _CONFIG_SECTION


def getConfig() -> dict[str, Any]:
	"""Return the add-on configuration section."""
	return nvdaConfig.conf[_CONFIG_SECTION]
