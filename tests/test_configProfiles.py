# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Small runnable checks for how Polyglot reads NVDA's configuration profile stack."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
	sys.path.insert(0, str(TESTS_ROOT))

from nvdaStubs import FakeConfigManager, installNvdaStubs  # noqa: E402

nvdaConfig = installNvdaStubs(PROJECT_ROOT)

from polyglot.common import configProfiles  # noqa: E402


class ProfileStackTest(unittest.TestCase):
	"""Check that Polyglot reads and writes the same profiles NVDA would."""

	def setUp(self) -> None:
		self.conf = FakeConfigManager()
		setattr(nvdaConfig, "conf", self.conf)

	def test_normalConfigurationIsUsedWhenNoProfileIsActive(self) -> None:
		"""With no profile active, everything belongs to the normal configuration."""
		self.assertIsNone(configProfiles.getWritableProfileName())
		self.assertEqual(configProfiles.getActiveProfileNames(), [None])

	def test_settingsAreWrittenToTheMostRecentlyActivatedProfile(self) -> None:
		"""NVDA writes a changed setting to the topmost profile, and so does Polyglot."""
		_unused = self.conf.activateProfile("work")
		_unused = self.conf.activateProfile("email")
		self.assertEqual(configProfiles.getWritableProfileName(), "email")

	def test_activeProfilesAreSearchedFromTheTopDown(self) -> None:
		"""Lookup order runs from the most recently activated profile to the normal configuration."""
		_unused = self.conf.activateProfile("work")
		_unused = self.conf.activateProfile("email")
		self.assertEqual(configProfiles.getActiveProfileNames(), ["email", "work", None])

	def test_normalConfigurationIsAlwaysTheLastResort(self) -> None:
		"""Even if NVDA reports only named profiles, the normal configuration ends the search."""
		self.conf.profiles = [self.conf.addProfile("work")]
		self.assertEqual(configProfiles.getActiveProfileNames(), ["work", None])

	def test_allProfilesStartWithTheNormalConfiguration(self) -> None:
		"""Saved profiles are listed after the normal configuration, whether or not they are active."""
		_unused = self.conf.addProfile("work")
		_unused = self.conf.addProfile("email")
		self.assertEqual(configProfiles.getAllProfileNames(), [None, "email", "work"])

	def test_everySavedProfileCanBeRead(self) -> None:
		"""Migration reaches inactive profiles, not only the ones that happen to be active."""
		_unused = self.conf.addProfile("work", {"modernTranslate": {}})
		names = [name for name, _unusedProfile in configProfiles.iterAllProfiles()]
		self.assertEqual(names, [None, "work"])

	def test_unreadableProfilesAreSkipped(self) -> None:
		"""A profile that cannot be read is skipped rather than aborting the scan."""
		with patch.object(self.conf, "listProfiles", return_value=["missing"]):
			names = [name for name, _unusedProfile in configProfiles.iterAllProfiles()]
		self.assertEqual(names, [None])

	def test_changedProfilesAreMarkedForSaving(self) -> None:
		"""A named profile has to be flagged before NVDA will write it back to disk."""
		configProfiles.markProfileDirty("work")
		self.assertIn("work", self.conf._dirtyProfiles)

	def test_theNormalConfigurationNeedsNoFlag(self) -> None:
		"""NVDA always writes the normal configuration, so it is never flagged."""
		configProfiles.markProfileDirty(None)
		self.assertEqual(self.conf._dirtyProfiles, set())


class ProfileHookTest(unittest.TestCase):
	"""Check that renaming and deleting a profile is reported, so credentials can follow."""

	def setUp(self) -> None:
		self.conf = FakeConfigManager()
		setattr(nvdaConfig, "conf", self.conf)
		self.renamed: list[tuple[str, str]] = []
		self.deleted: list[str] = []
		configProfiles.post_profileRenamed.register(self._onRenamed)
		configProfiles.post_profileDeleted.register(self._onDeleted)
		self.addCleanup(configProfiles.post_profileRenamed.unregister, self._onRenamed)
		self.addCleanup(configProfiles.post_profileDeleted.unregister, self._onDeleted)
		configProfiles.installProfileHooks()
		self.addCleanup(configProfiles.removeProfileHooks)

	def _onRenamed(self, oldName: str, newName: str) -> None:
		self.renamed.append((oldName, newName))

	def _onDeleted(self, profileName: str) -> None:
		self.deleted.append(profileName)

	def test_renamingAProfileIsReported(self) -> None:
		"""A rename reaches the handler with both names, and NVDA still does the rename."""
		_unused = self.conf.addProfile("work")
		self.conf.renameProfile("work", "office")
		self.assertEqual(self.renamed, [("work", "office")])
		self.assertEqual(self.conf.renamed, [("work", "office")])
		self.assertIn("office", self.conf.savedProfiles)

	def test_deletingAProfileIsReported(self) -> None:
		"""A deletion reaches the handler, and NVDA still deletes the profile."""
		_unused = self.conf.addProfile("work")
		self.conf.deleteProfile("work")
		self.assertEqual(self.deleted, ["work"])
		self.assertNotIn("work", self.conf.savedProfiles)

	def test_aFailedRenameIsNotReported(self) -> None:
		"""Nothing is moved when NVDA itself could not rename the profile."""
		with self.assertRaises(KeyError):
			self.conf.renameProfile("absent", "office")
		self.assertEqual(self.renamed, [])

	def test_hooksAreInstalledOnlyOnce(self) -> None:
		"""Installing again leaves one wrapper, so a rename is never reported twice."""
		configProfiles.installProfileHooks()
		_unused = self.conf.addProfile("work")
		self.conf.renameProfile("work", "office")
		self.assertEqual(self.renamed, [("work", "office")])

	def test_removingHooksRestoresNvdaMethods(self) -> None:
		"""NVDA's own methods are back once Polyglot stops watching."""
		configProfiles.removeProfileHooks()
		_unused = self.conf.addProfile("work")
		self.conf.deleteProfile("work")
		self.assertEqual(self.deleted, [])
		self.assertEqual(self.conf.deleted, ["work"])


if __name__ == "__main__":
	unittest.main()
