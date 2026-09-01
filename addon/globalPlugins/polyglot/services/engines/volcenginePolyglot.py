# -*- coding: utf-8 -*-

# Copyright (C) 2025-2026 cary-rowen <manchen_0528@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

import addonHandler

from ...common import languages
from ._nvdacn import NvdacnJsonEngine

addonHandler.initTranslation()


class VolcengineTranslateEngine(NvdacnJsonEngine):
	"""Translate text through the NVDACN-hosted Volcengine service."""

	id = "volcenginePolyglot"
	name = _("Volcengine (Polyglot)")

	SERVICE_NAME = "volcengine"

	@property
	def autoDetectCode(self) -> str | None:
		return "auto"

	@property
	def defaultTargetLanguage(self) -> str:
		return "zh"

	def getSupportedLanguages(self) -> dict:
		supportedCodes = [
			"auto",
			"zh",
			"en",
			"ja",
			"ko",
			"fr",
			"es",
			"ru",
			"de",
			"it",
			"pt",
			"vi",
			"id",
			"th",
		]
		return languages.getLanguageDictForCodes(supportedCodes)
