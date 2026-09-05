"""Verify the packaged .nvda-addon before it is uploaded or released.

Two kinds of check live here. The first is the usual packaging check: every module the plugin imports
has to be in the bundle, because a module that stops being packaged is a crash on the first NVDA start
after release rather than a test failure. The second is what makes this a Polyglot-secure build: the
bundle must not carry a shared credential or a route through NVDACN infrastructure. Those were removed
deliberately, and a merge from upstream is exactly the kind of change that would quietly bring them back.
"""

from pathlib import Path, PurePosixPath
import re
import zipfile


PLUGIN_PREFIX = "globalPlugins/polyglot/"
ENGINE_PREFIX = f"{PLUGIN_PREFIX}services/engines/"

REQUIRED_FILES = {
	"manifest.ini",
	"installTasks.py",
	"COPYING.txt",
	"doc/en/readme.html",
	# The websocket client is a submodule. A checkout without `submodules: recursive` still builds a
	# bundle, and that bundle fails on import at NVDA start.
	"websocketClientRepo/websocket/__init__.py",
	# The offline dictionary is compiled at build time from tools/resource.
	f"{PLUGIN_PREFIX}common/resources/dictionary.pickle",
	# Every first-party package the plugin imports at start.
	f"{PLUGIN_PREFIX}__init__.py",
	f"{PLUGIN_PREFIX}configspec.py",
	f"{PLUGIN_PREFIX}app/manager.py",
	f"{PLUGIN_PREFIX}app/speechFilter.py",
	f"{PLUGIN_PREFIX}app/task.py",
	f"{PLUGIN_PREFIX}argosManager/__init__.py",
	f"{PLUGIN_PREFIX}argosManager/menu.py",
	f"{PLUGIN_PREFIX}common/config.py",
	f"{PLUGIN_PREFIX}common/configProfiles.py",
	f"{PLUGIN_PREFIX}common/cues.py",
	f"{PLUGIN_PREFIX}common/network.py",
	f"{PLUGIN_PREFIX}common/secretStore.py",
	f"{PLUGIN_PREFIX}modelManager/__init__.py",
	f"{PLUGIN_PREFIX}modelManager/menu.py",
	f"{PLUGIN_PREFIX}services/cdpBridge.py",
	f"{PLUGIN_PREFIX}services/engine.py",
	f"{PLUGIN_PREFIX}services/engineManager.py",
	f"{PLUGIN_PREFIX}views/factory.py",
	f"{PLUGIN_PREFIX}views/interactiveDialog.py",
	f"{PLUGIN_PREFIX}views/settings.py",
}

#: Engines are discovered by scanning the package, so an engine module that comes back in a merge is
#: live again the moment it is packaged, with no import anywhere to notice it.
FORBIDDEN_FILES = {
	f"{ENGINE_PREFIX}_nvdacn.py",
	f"{ENGINE_PREFIX}_vivoAuth.py",
	f"{ENGINE_PREFIX}googlePolyglot.py",
	f"{ENGINE_PREFIX}tencentPolyglot.py",
	f"{ENGINE_PREFIX}vivo.py",
	f"{ENGINE_PREFIX}volcenginePolyglot.py",
}

#: Text that must not appear anywhere in the bundle, and why. Checked against every packaged file.
FORBIDDEN_CONTENT = {
	"3a64ad20-724b-41dc-ba23-cf64185dbfa3": "upstream's shared Google mirror token",
	"nvdacn.com": "an NVDACN service endpoint",
	"family.zxrjy.net": "a shared third-party Ollama server",
}

#: `translate.googleapis.mirror.nvdadr.com` is the key-free Google engine's optional mirror toggle. It
#: needs no credentials and is off unless the user turns it on, so it stays; this pattern is what keeps
#: the `nvdadr.com` allowance narrow enough that a credentialed route through it would still be caught.
ALLOWED_NVDADR_HOST = "translate.googleapis.mirror.nvdadr.com"
NVDADR_PATTERN = re.compile(r"[\w.-]*nvdadr\.com")

#: Files worth scanning for the strings above. The dictionary pickle and the sounds are not text.
SCANNED_SUFFIXES = (".py", ".json", ".ini", ".md", ".html", ".txt", ".po")


def _readEntry(bundle: zipfile.ZipFile, entry: str) -> str:
	"""Return a packaged file decoded loosely enough that a stray byte cannot mask a match."""
	return bundle.read(entry).decode("utf-8", errors="replace")


def checkContent(bundle: zipfile.ZipFile, entries: set[str]) -> list[str]:
	"""Return one problem description per packaged file carrying a credential or removed endpoint."""
	problems: list[str] = []
	for entry in sorted(entries):
		if not entry.lower().endswith(SCANNED_SUFFIXES):
			continue
		text = _readEntry(bundle, entry).lower()
		for needle, description in FORBIDDEN_CONTENT.items():
			if needle in text:
				problems.append(f"{entry}: contains {description} ({needle!r})")
		for host in set(NVDADR_PATTERN.findall(text)):
			if host != ALLOWED_NVDADR_HOST:
				problems.append(f"{entry}: contains an unexpected nvdadr.com host ({host!r})")
	return problems


def main() -> None:
	"""Verify the single .nvda-addon in the working directory, raising on the first failed check."""
	artifacts = sorted(Path.cwd().glob("*.nvda-addon"))
	if len(artifacts) != 1:
		raise AssertionError(
			f"Expected exactly one *.nvda-addon artifact, found {len(artifacts)}: {artifacts}",
		)

	artifact = artifacts[0]
	with zipfile.ZipFile(artifact) as bundle:
		entries = set(bundle.namelist())

		missingFiles = REQUIRED_FILES - entries
		if missingFiles:
			raise AssertionError(f"Missing required files: {sorted(missingFiles)}")

		shippedForbidden = FORBIDDEN_FILES & entries
		if shippedForbidden:
			raise AssertionError(f"Removed engine modules are packaged again: {sorted(shippedForbidden)}")

		pycEntries = {entry for entry in entries if entry.lower().endswith(".pyc")}
		if pycEntries:
			raise AssertionError(f"Bundle contains .pyc files: {sorted(pycEntries)}")

		pycacheEntries = {entry for entry in entries if "__pycache__" in PurePosixPath(entry).parts}
		if pycacheEntries:
			raise AssertionError(f"Bundle contains __pycache__ content: {sorted(pycacheEntries)}")

		contentProblems = checkContent(bundle, entries)
		if contentProblems:
			raise AssertionError(
				"Bundle carries removed credentials or endpoints:\n  " + "\n  ".join(contentProblems),
			)

		engineModules = sorted(
			entry
			for entry in entries
			if entry.startswith(ENGINE_PREFIX) and entry.endswith(".py") and not entry.endswith("__init__.py")
		)

	print(f"Artifact: {artifact}")
	print(f"Required files present: {len(REQUIRED_FILES)}")
	print(f"Removed engine modules absent: {sorted(FORBIDDEN_FILES)}")
	print(f"Packaged engine modules ({len(engineModules)}):")
	for entry in engineModules:
		print(f"  {entry}")
	print(f".pyc entries: {len(pycEntries)}")
	print(f"__pycache__ entries: {len(pycacheEntries)}")
	print("No shared credentials or removed endpoints found.")
	print("Artifact verification passed.")


if __name__ == "__main__":
	main()
