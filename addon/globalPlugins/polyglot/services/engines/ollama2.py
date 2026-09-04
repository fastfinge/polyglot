# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

import addonHandler

from .ollamaBase import OllamaBaseEngine

addonHandler.initTranslation()


class Ollama2TranslateEngine(OllamaBaseEngine):
	"""
	This is the second instance of the Ollama engine.
	It also inherits all logic and simply overrides the ID and name.
	"""

	id = "ollama2"
	name = _("Ollama 2")
