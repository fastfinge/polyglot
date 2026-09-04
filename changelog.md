### Polyglot-secure 0.0.1

- API keys, tokens, and passwords now follow NVDA's configuration profile rules: each profile can hold its own key, a profile without one uses the key from the profile below it, and the profile activated last wins. Keys are saved to the profile NVDA is editing, and clearing a field returns that profile to the inherited key.
- Renaming a configuration profile now moves its stored keys with it, and deleting a profile removes them.
- Upgrading from Polyglot 1.2.0 or earlier now migrates the keys saved in every configuration profile, not only in the profiles that happen to be active.
- Uninstalling Polyglot now removes its settings from every NVDA configuration profile, every API key, token, and password it stored in the Windows Credential Locker, and its translation cache. Updating the add-on keeps all three.
- The translation cache is now written a few seconds after it changes rather than on every translation. With auto-translation on, Polyglot used to rewrite the whole cache file for every phrase NVDA spoke; it now gathers those changes and writes them once, and writes whatever is still pending when NVDA exits.
- The translation cache now discards the entries you have used least recently rather than the ones stored longest ago, so a phrase you keep meeting stays cached.
- The translation cache is now replaced in a single step and is safe to use from several translations at once, so an interrupted write or two results arriving together can no longer damage it.

### 1.2.1

- Improved the Simplified Chinese and Ukrainian localizations and aligned the English and Simplified Chinese documentation.
- Removed unused internal code and obsolete comments.

### 1.2.0

- Added the key-free `DeepL Web` engine with automatic source detection, regional language options, and support for requests up to 1,500 characters.
- Migrated key-free Microsoft Translator to the current Edge `translatetext` endpoint and removed the retired authentication-token flow.
- Refreshed OpenRouter presets with current translation-specialised Tencent and Gemini Flash Lite models, automatic fallback for retired presets, and prompt options matched to model capabilities.
- Reused HTTP connections across translation requests to reduce latency for repeated translations.
- Removed the unavailable Lingva Translate engine.
- Fixed long labels overflowing the Chrome AI and Common Settings panels.

### 1.1.1

- Fixed repeated current-character review failing after version 1.1.0 by preserving NVDA's
  `speech.spellTextInfo` keyword-argument contract.

### 1.1.0

- Relicensed Polyglot and its first-party dictionary resources under GPL-3.0-or-later, with cary-rowen
  copyright attribution and preserved third-party MIT and Apache-2.0 notices.
- Standardized copyright headers, NVDA naming, and docstrings, and removed sensitive content from diagnostic
  logs.
- Applied repository-wide Ruff formatting and excluded vendored dependencies and template build files from
  first-party linting.

### 1.0.0

- Added offline English-to-Chinese definitions to NVDA's repeated current-word review command in Chinese,
  including conservative lookup for common spelling and inflection variants, candidate announcements for
  ambiguous words, and clear feedback for possible abbreviations and words absent from the local dictionary.
- Manual selection, clipboard, and last-spoken translation now use matching local word definitions for
  supported English-Chinese requests. Translation-command and text-review lookup can be controlled separately
  from Common Settings.

### 0.9.7

- Improved smart speech filtering to better preserve user content while avoiding auto-translation of NVDA speech metadata.
- Simplified internal code by removing unused abstractions and redundant wrappers.
- Added Vietnamese localization.

### 0.9.5

- Improved ChromeAI model checks for faster translation responses.
- Improved ChromeAI cold-start performance.
- Hardened ChromeAI's managed Chrome handling for better stability and safety.
