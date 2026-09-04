# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Small runnable checks for the clean-up NVDA runs when Polyglot is uninstalled."""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
	sys.path.insert(0, str(TESTS_ROOT))

from nvdaStubs import FakeConfigManager, installNvdaStubs  # noqa: E402

nvdaConfig = installNvdaStubs(PROJECT_ROOT)

from polyglot.common.config import getConfigSectionName  # noqa: E402


def _loadInstallTasks() -> ModuleType:
	"""Load the add-on's install tasks the way NVDA does, from the add-on folder rather than a package."""
	path = PROJECT_ROOT / "addon" / "installTasks.py"
	spec = importlib.util.spec_from_file_location("polyglotInstallTasks", path)
	assert spec is not None and spec.loader is not None
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


installTasks = _loadInstallTasks()

#: The section Polyglot keeps its settings in, taken from the add-on rather than repeated here.
SECTION_NAME = getConfigSectionName()


class UpdateDetectionTest(unittest.TestCase):
	"""Check that an update is told apart from a removal."""

	def setUp(self) -> None:
		self.addonsDir = tempfile.TemporaryDirectory()
		self.addCleanup(self.addonsDir.cleanup)
		writePaths = getattr(sys.modules["NVDAState"], "WritePaths")
		patcher = patch.object(writePaths, "addonsDir", self.addonsDir.name)
		_unused = patcher.start()
		self.addCleanup(patcher.stop)

	def test_removingTheAddonIsNotAnUpdate(self) -> None:
		"""With no incoming version waiting, the add-on is being removed for good."""
		self.assertFalse(installTasks._isBeingUpdated())

	def test_anIncomingVersionMeansAnUpdate(self) -> None:
		"""NVDA leaves the new version beside the installed one, which marks the removal as an update."""
		pendingInstall = Path(self.addonsDir.name) / f"{installTasks.ADDON_NAME}.pendingInstall"
		pendingInstall.mkdir()
		self.assertTrue(installTasks._isBeingUpdated())

	def test_anotherAddonsUpdateIsNotOurs(self) -> None:
		"""Another add-on being updated at the same time says nothing about this one."""
		(Path(self.addonsDir.name) / "someOtherAddon.pendingInstall").mkdir()
		self.assertFalse(installTasks._isBeingUpdated())


class ConfigurationRemovalTest(unittest.TestCase):
	"""Check that the settings Polyglot keeps in NVDA's configuration file are removed."""

	def setUp(self) -> None:
		self.conf = FakeConfigManager()
		setattr(nvdaConfig, "conf", self.conf)

	def test_settingsGoFromEveryProfileThatHasThem(self) -> None:
		"""Profiles that are not active are the user's too, so their settings go as well."""
		self.conf.profiles[0].values[SECTION_NAME] = {"engine": "deepl"}
		_unused = self.conf.addProfile("work", {SECTION_NAME: {"engine": "google"}})
		_unused = self.conf.addProfile("email", {"speech": {}})
		installTasks._deleteConfiguration()
		self.assertNotIn(SECTION_NAME, self.conf.profiles[0].values)
		self.assertNotIn(SECTION_NAME, self.conf.savedProfiles["work"].values)
		self.assertIn("speech", self.conf.savedProfiles["email"].values)

	def test_clearedProfilesAreWrittenBackToDisk(self) -> None:
		"""A profile only loses its settings for good once NVDA has saved it."""
		_unused = self.conf.addProfile("work", {SECTION_NAME: {"engine": "google"}})
		installTasks._deleteConfiguration()
		self.assertEqual(self.conf._dirtyProfiles, {"work"})
		self.assertEqual(self.conf.saveCount, 1)

	def test_nothingIsSavedWhenThereWereNoSettings(self) -> None:
		"""An add-on that was never configured leaves NVDA's configuration file untouched."""
		_unused = self.conf.addProfile("work", {"speech": {}})
		installTasks._deleteConfiguration()
		self.assertEqual(self.conf.saveCount, 0)

	def test_aFailedSaveIsReportedRatherThanRaised(self) -> None:
		"""A configuration that cannot be written must not stop the rest of the clean-up."""
		self.conf.profiles[0].values[SECTION_NAME] = {"engine": "deepl"}
		with patch.object(self.conf, "save", side_effect=OSError("disk full")):
			installTasks._deleteConfiguration()

	def test_unreadableAddonCodeIsSurvived(self) -> None:
		"""If the add-on's own modules cannot be read, nothing is guessed at."""
		with patch.object(installTasks, "_importAddonModule", return_value=None):
			installTasks._deleteConfiguration()
		self.assertEqual(self.conf.saveCount, 0)


class CredentialRemovalTest(unittest.TestCase):
	"""Check that stored credentials are removed, without touching this machine's real ones."""

	def test_everyStoredCredentialIsRemoved(self) -> None:
		"""Credentials belong to profiles, and every profile's credentials go."""
		secretStore = Mock()
		secretStore.deleteAllSecrets.return_value = 3
		with patch.object(installTasks, "_importAddonModule", return_value=secretStore):
			installTasks._deleteCredentials()
		secretStore.deleteAllSecrets.assert_called_once_with()

	def test_unreadableAddonCodeIsSurvived(self) -> None:
		"""If the secret store cannot be read, the clean-up simply reports it."""
		with patch.object(installTasks, "_importAddonModule", return_value=None):
			installTasks._deleteCredentials()


class UninstallTest(unittest.TestCase):
	"""Check what the whole clean-up does and does not do."""

	def setUp(self) -> None:
		self.deleteConfiguration = Mock()
		self.deleteCredentials = Mock()
		for name, replacement in (
			("_deleteConfiguration", self.deleteConfiguration),
			("_deleteCredentials", self.deleteCredentials),
		):
			patcher = patch.object(installTasks, name, replacement)
			_unused = patcher.start()
			self.addCleanup(patcher.stop)

	def _setUpdating(self, isBeingUpdated: bool) -> None:
		patcher = patch.object(installTasks, "_isBeingUpdated", return_value=isBeingUpdated)
		_unused = patcher.start()
		self.addCleanup(patcher.stop)

	def test_removingTheAddonRemovesWhatItStored(self) -> None:
		"""Nothing the add-on stored outside its own folder is left behind."""
		self._setUpdating(False)
		installTasks.onUninstall()
		self.deleteConfiguration.assert_called_once_with()
		self.deleteCredentials.assert_called_once_with()

	def test_anUpdateKeepsSettingsAndCredentials(self) -> None:
		"""An update must not make the user set the add-on up and enter their API keys again."""
		self._setUpdating(True)
		installTasks.onUninstall()
		self.deleteConfiguration.assert_not_called()
		self.deleteCredentials.assert_not_called()

	def test_credentialsGoEvenWhenSettingsCannot(self) -> None:
		"""The two stores are independent, so a failure in one must not leave the other behind."""
		self._setUpdating(False)
		self.deleteConfiguration.side_effect = RuntimeError("no configuration")
		installTasks.onUninstall()
		self.deleteCredentials.assert_called_once_with()

	def test_nothingOfTheAddonStaysLoaded(self) -> None:
		"""The modules borrowed to do the clean-up are dropped again once it is done."""
		sys.modules[f"{installTasks._PACKAGE_NAME}.common.config"] = ModuleType("stale")
		self._setUpdating(False)
		installTasks.onUninstall()
		borrowed = [name for name in sys.modules if name.startswith(installTasks._PACKAGE_NAME)]
		self.assertEqual(borrowed, [])


if __name__ == "__main__":
	unittest.main()
