# -*- coding: utf-8 -*-

# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

import addonHandler

from .ollamaBase import OllamaBaseEngine

addonHandler.initTranslation()


class OllamaTranslateEngine(OllamaBaseEngine):
	"""
	This is the first, primary instance of the Ollama engine.
	It inherits all logic from the base engine and sets a unique ID and name.
	"""

	id = "ollama1"
	name = _("Ollama 1")
