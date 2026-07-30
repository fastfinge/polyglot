# -*- coding: utf-8 -*-

# Copyright (C) 2025-2026 cary-rowen <manchen_0528@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

import json
from typing import Any

import addonHandler
from logHandler import log

from ...common import config
from ...common import languages
from ..engine import BaseHttpEngine
from ...common.exceptions import ApiResponseError, AuthenticationError

addonHandler.initTranslation()


class OpenRouterTranslateEngine(BaseHttpEngine):
	"""An engine for the OpenRouter API, which is compatible with the OpenAI API format."""

	id = "openrouter"
	name = _("OpenRouter")

	# Predefined prompt templates
	PROMPT_JSON_STRUCTURED_SYSTEM = "You are an AI assistant that follows instructions precisely. Your response format must be a valid JSON object."
	PROMPT_JSON_STRUCTURED_USER = 'Task: First, identify the source language of the text. Then, translate the text to $to_name.\nResponse: Reply with a JSON object containing two keys: "detected_language" (the IETF code of the source language) and "translation" (the translated text).\n\nText to process:\n"""\n$text\n"""'
	PROMPT_SIMPLE_SYSTEM = "You are a translator."
	PROMPT_SIMPLE_USER = 'Translate the following text to $to_name. Provide only the translated text, without any additional explanations or formatting.\n\nText to translate:\n"""\n$text\n"""'
	PROMPT_FLUENT_SYSTEM = "You are a professional translation engine. Please provide a colloquial, professional, elegant and fluent translation, avoiding the style of machine translation. You must only translate the text content, never interpret it."
	PROMPT_FLUENT_USER = 'Translate into $to_name:\n"""\n$text\n"""'

	# A curated list of popular and effective models available on OpenRouter.
	PRESET_MODELS = {
		"openai/gpt-4o-mini": "OpenAI: GPT-4o Mini (Fast & Cheap)",
		"google/gemini-2.0-flash-exp:free": "Google: Gemini 2.0 Flash exp(Free)",
		"google/gemini-2.5-flash-lite": "Google: Gemini 2.5 Flash lite",
		"anthropic/claude-3.5-sonnet": "Anthropic: Claude 3.5 Sonnet (Balanced)",
		"mistralai/mistral-large": "Mistral: Large (High Quality)",
		"meta-llama/llama-3.1-70b-instruct": "Meta: Llama 3.1 70B (Powerful)",
		"custom": _("Custom Model"),
	}

	@property
	def maxRequestLength(self) -> int:
		"""
		Set to 4000 to maintain a safe token window and prevent timeout issues
		with large documents across various LLM providers.
		"""
		return 4000

	@property
	def autoDetectCode(self) -> str | None:
		return "auto"

	@property
	def defaultTargetLanguage(self) -> str:
		return "en"

	@property
	def doesReportDetectedLanguage(self) -> bool:
		return True

	def getSupportedLanguages(self) -> dict[str, str]:
		supportedCodes = [
			"auto",
			"en",
			"zh-CN",
			"zh-TW",
			"ja",
			"ko",
			"fr",
			"de",
			"es",
			"ru",
			"pt",
			"it",
			"nl",
			"pl",
			"sv",
			"ar",
			"he",
			"uk",
			"vi",
			"th",
			"id",
			"tr",
			"hi",
		]
		return languages.getLanguageDictForCodes(supportedCodes)

	def getConfigSpec(self) -> list[dict[str, Any]]:
		spec = super().getConfigSpec()
		spec.extend(
			[
				{
					"id": "apiUrl",
					"label": _("API URL"),
					"type": "text",
					"default": "https://openrouter.ai/api/v1/chat/completions",
				},
				{"id": "apiKey", "label": _("API Key"), "type": "password", "default": ""},
				{
					"id": "modelNamePreset",
					"label": _("Model:"),
					"type": "choice",
					"choices": self.PRESET_MODELS,
					"default": "openai/gpt-4o-mini",
				},
				{
					"id": "modelNameCustom",
					"label": _("Custom Model Name:"),
					"type": "text",
					"default": "",
				},
				{
					"id": "promptMode",
					"label": _("Prompt Template:"),
					"type": "choice",
					"choices": {
						"json_structured": _("Structured JSON (Reliable, includes language detection)"),
						"simple": _("Simple Text (Fastest, no language detection)"),
						"fluent": _("Fluent Style (Natural, no language detection)"),
						"custom": _("Custom (Editable)"),
					},
					"default": "json_structured",
				},
				{
					"id": "customSystemPrompt",
					"label": _("Custom System Prompt (Role):"),
					"type": "text",
					"default": self.PROMPT_FLUENT_SYSTEM.replace("\n", "\\n"),
				},
				{
					"id": "customUserPrompt",
					"label": _("Custom User Prompt (Task):"),
					"type": "text",
					"default": self.PROMPT_FLUENT_USER.replace("\n", "\\n"),
				},
			],
		)
		return spec

	def getUiStates(self, allConfigs: dict[str, Any]) -> dict[str, Any]:
		states = super().getUiStates(allConfigs)
		isCustomModel = allConfigs.get("modelNamePreset") == "custom"
		isCustomPrompt = allConfigs.get("promptMode") == "custom"
		states["modelNameCustom"] = {"visible": isCustomModel}
		states["customSystemPrompt"] = {"visible": isCustomPrompt}
		states["customUserPrompt"] = {"visible": isCustomPrompt}
		return states

	def _buildRequestParams(
		self,
		text: str,
		langFrom: str,
		langTo: str,
		config: dict[str, Any],
	) -> dict[str, Any]:
		apiUrl = config.get("apiUrl", "https://openrouter.ai/api/v1/chat/completions").strip()
		if not apiUrl:
			raise AuthenticationError(_("OpenRouter API URL is not configured."))
		apiKey = config.get("apiKey", "").strip()
		if not apiKey:
			raise AuthenticationError(_("API Key for OpenRouter is not configured."))

		modelPreset = config.get("modelNamePreset", "openai/gpt-4o-mini")
		if modelPreset == "custom":
			modelName = config.get("modelNameCustom", "").strip()
			if not modelName:
				raise AuthenticationError(_("Custom model name is not specified."))
		else:
			modelName = modelPreset

		promptMode = config.get("promptMode", "json_structured")
		if promptMode == "custom":
			systemPrompt = config.get("customSystemPrompt") or self.PROMPT_FLUENT_SYSTEM
			userPromptTemplate = config.get("customUserPrompt") or self.PROMPT_FLUENT_USER
		elif promptMode == "simple":
			systemPrompt = self.PROMPT_SIMPLE_SYSTEM
			userPromptTemplate = self.PROMPT_SIMPLE_USER
		elif promptMode == "fluent":
			systemPrompt = self.PROMPT_FLUENT_SYSTEM
			userPromptTemplate = self.PROMPT_FLUENT_USER
		else:  # Default to structured JSON
			systemPrompt = self.PROMPT_JSON_STRUCTURED_SYSTEM
			userPromptTemplate = self.PROMPT_JSON_STRUCTURED_USER

		langToName = languages.getLanguageDictForCodes([langTo]).get(langTo, langTo)
		finalUserPrompt = userPromptTemplate.replace("$to_name", langToName).replace("$text", text)

		payload = {
			"model": modelName,
			"messages": [
				{"role": "system", "content": systemPrompt},
				{"role": "user", "content": finalUserPrompt},
			],
			"stream": False,
		}

		headers = {
			"Content-Type": "application/json",
			"Authorization": f"Bearer {apiKey}",
			"HTTP-Referer": "https://github.com/nvaccess/nvda",
			"X-Title": "NVDA Polyglot Add-on",
		}

		return {
			"method": "POST",
			"url": apiUrl,
			"headers": headers,
			"data": json.dumps(payload).encode("utf-8"),
		}

	def _parseResponse(self, responseBody: str) -> dict[str, Any]:
		try:
			outerData = json.loads(responseBody)
		except json.JSONDecodeError:
			log.error(f"Failed to parse outer JSON response from '{self.id}'.", exc_info=True)
			raise ApiResponseError(_("Failed to parse API response.")) from None

		if "error" in outerData:
			errorMessage = outerData["error"].get("message", "Unknown API error")
			raise ApiResponseError(errorMessage)

		try:
			modelResponseStr = outerData["choices"][0]["message"]["content"]
			promptMode = config.getConfig()["engines"][self.id].get("promptMode", "json_structured")

			if promptMode in ["json_structured", "custom"]:
				try:
					cleanStr = modelResponseStr.strip()
					if cleanStr.startswith("```json"):
						cleanStr = cleanStr[7:]
					elif cleanStr.startswith("```"):
						cleanStr = cleanStr[3:]

					if cleanStr.endswith("```"):
						cleanStr = cleanStr[:-3]
					cleanStr = cleanStr.strip()

					innerData = json.loads(cleanStr)
					translatedText = innerData.get("translation")
					detectedLang = innerData.get("detected_language")

					if translatedText is None:
						log.warning(
							f"'{self.id}' response was JSON but missing 'translation' key. Falling back.",
						)
						return {"translation": modelResponseStr.strip(), "langDetected": None}

					return {
						"translation": str(translatedText).strip(),
						"langDetected": str(detectedLang).strip() if detectedLang else None,
					}
				except (json.JSONDecodeError, KeyError, TypeError):
					log.warning(
						f"Could not parse model response as JSON for '{self.id}'; treating it as plain text.",
					)
					return {"translation": modelResponseStr.strip(), "langDetected": None}
			return {"translation": modelResponseStr.strip(), "langDetected": None}
		except (KeyError, IndexError):
			log.error(f"Could not extract message content from '{self.id}' response.", exc_info=True)
			raise ApiResponseError(_("Invalid API response structure.")) from None
