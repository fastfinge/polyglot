# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Small runnable checks for credential storage outside NVDA's configuration file."""

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

from polyglot.common import secretStore  # noqa: E402


#: An engine ID no real engine uses, so the checks cannot disturb stored credentials.
TEST_ENGINE_ID = "polyglotSelfTest"


class NamingTest(unittest.TestCase):
	"""Check how credentials are addressed in Windows and in the environment."""

	def test_targetNamesAreScopedToPolyglot(self) -> None:
		"""Every stored credential is listed under Polyglot's own prefix."""
		targetName = secretStore.getTargetName("deepl", "apiKey")
		self.assertTrue(targetName.startswith(secretStore.TARGET_PREFIX))
		self.assertEqual(targetName, "NVDA/Polyglot/deepl/apiKey")

	def test_theNormalConfigurationKeepsTheOriginalTargetName(self) -> None:
		"""Credentials stored before profiles were supported stay where they are."""
		self.assertEqual(
			secretStore.getTargetName("deepl", "apiKey", None),
			secretStore.getTargetName("deepl", "apiKey"),
		)

	def test_namedProfilesGetTheirOwnTargetNames(self) -> None:
		"""Two profiles can hold different keys for the same engine setting."""
		self.assertNotEqual(
			secretStore.getTargetName("deepl", "apiKey", "work"),
			secretStore.getTargetName("deepl", "apiKey", "email"),
		)
		self.assertEqual(
			secretStore.getTargetName("deepl", "apiKey", "work"),
			"NVDA/Polyglot/profiles:work/deepl/apiKey",
		)

	def test_targetNamesRoundTrip(self) -> None:
		"""A stored credential can be traced back to the profile, engine, and setting it belongs to."""
		for profileName in (None, "work", "Reading email (laptop)"):
			with self.subTest(profileName=profileName):
				targetName = secretStore.getTargetName("deepl", "apiKey", profileName)
				self.assertEqual(
					secretStore.parseTargetName(targetName),
					(profileName, "deepl", "apiKey"),
				)

	def test_foreignTargetNamesAreIgnored(self) -> None:
		"""Credentials another program stored are never claimed as Polyglot's."""
		self.assertIsNone(secretStore.parseTargetName("git:https://example.invalid"))
		self.assertIsNone(secretStore.parseTargetName("NVDA/Polyglot/deepl"))

	def test_environmentVariableNamesAreUpperCaseAndSafe(self) -> None:
		"""Engine and setting names become a single upper-case variable name."""
		self.assertEqual(
			secretStore.getEnvironmentVariableName("openrouter", "apiKey"),
			"POLYGLOT_OPENROUTER_APIKEY",
		)
		self.assertEqual(
			secretStore.getEnvironmentVariableName("chrome_ai", "secretKey"),
			"POLYGLOT_CHROME_AI_SECRETKEY",
		)


class EnvironmentOverrideTest(unittest.TestCase):
	"""Check that the environment can supply a credential without any stored copy."""

	def setUp(self) -> None:
		self.variableName = secretStore.getEnvironmentVariableName(TEST_ENGINE_ID, "apiKey")
		setattr(nvdaConfig, "conf", FakeConfigManager())

	def test_environmentValueIsUsed(self) -> None:
		"""A credential set in the environment is returned as-is."""
		with patch.dict("os.environ", {self.variableName: "  from-environment  "}):
			self.assertTrue(secretStore.isProvidedByEnvironment(TEST_ENGINE_ID, "apiKey"))
			self.assertEqual(secretStore.getSecret(TEST_ENGINE_ID, "apiKey"), "from-environment")

	def test_blankEnvironmentValueIsIgnored(self) -> None:
		"""An empty variable does not count as an override."""
		with patch.dict("os.environ", {self.variableName: "   "}):
			self.assertFalse(secretStore.isProvidedByEnvironment(TEST_ENGINE_ID, "apiKey"))

	def test_environmentWinsOverStoredValue(self) -> None:
		"""The environment takes precedence over the Windows Credential Locker."""
		with patch.object(secretStore, "_credentialApi", None):
			with patch.dict("os.environ", {self.variableName: "from-environment"}):
				self.assertEqual(secretStore.getSecret(TEST_ENGINE_ID, "apiKey"), "from-environment")

	def test_environmentAppliesToEveryProfile(self) -> None:
		"""One variable covers the whole machine, so no profile can override it."""
		conf = FakeConfigManager()
		_unused = conf.activateProfile("work")
		setattr(nvdaConfig, "conf", conf)
		with patch.dict("os.environ", {self.variableName: "from-environment"}):
			resolved = secretStore.resolveSecret(TEST_ENGINE_ID, "apiKey")
		self.assertEqual(resolved.value, "from-environment")
		self.assertIs(resolved.source, secretStore.CredentialSource.ENVIRONMENT)


class ProfileInheritanceTest(unittest.TestCase):
	"""Check that a credential is inherited exactly as NVDA inherits a setting."""

	def setUp(self) -> None:
		self.conf = FakeConfigManager()
		setattr(nvdaConfig, "conf", self.conf)
		#: Stands in for the Credential Locker, keyed by target name.
		self.stored: dict[str, str] = {}
		reader = patch.object(secretStore, "_readCredential", side_effect=self._readCredential)
		_unused = reader.start()
		self.addCleanup(reader.stop)
		self.variableName = secretStore.getEnvironmentVariableName(TEST_ENGINE_ID, "apiKey")
		environment = patch.dict("os.environ", {self.variableName: ""})
		_unused = environment.start()
		self.addCleanup(environment.stop)

	def _readCredential(self, targetName: str) -> str:
		return self.stored.get(targetName, "")

	def _store(self, profileName: str | None, value: str) -> None:
		self.stored[secretStore.getTargetName(TEST_ENGINE_ID, "apiKey", profileName)] = value

	def test_aProfileWithoutItsOwnKeyInheritsTheOneBelow(self) -> None:
		"""An unset key in a profile falls back to the normal configuration."""
		self._store(None, "shared-key")
		_unused = self.conf.activateProfile("work")
		resolved = secretStore.resolveSecret(TEST_ENGINE_ID, "apiKey")
		self.assertEqual(resolved.value, "shared-key")
		self.assertIsNone(resolved.profileName)

	def test_aProfileKeyOverridesTheNormalConfiguration(self) -> None:
		"""A key set in the active profile is used instead of the inherited one."""
		self._store(None, "shared-key")
		self._store("work", "work-key")
		_unused = self.conf.activateProfile("work")
		resolved = secretStore.resolveSecret(TEST_ENGINE_ID, "apiKey")
		self.assertEqual(resolved.value, "work-key")
		self.assertEqual(resolved.profileName, "work")

	def test_theTopmostProfileWins(self) -> None:
		"""With several profiles active, the most recently activated one supplies the key."""
		self._store(None, "shared-key")
		self._store("work", "work-key")
		self._store("email", "email-key")
		_unused = self.conf.activateProfile("work")
		_unused = self.conf.activateProfile("email")
		self.assertEqual(secretStore.getSecret(TEST_ENGINE_ID, "apiKey"), "email-key")

	def test_lookupFallsThroughProfilesThatSetNothing(self) -> None:
		"""A profile that stores no key of its own is passed over, not treated as empty."""
		self._store("work", "work-key")
		_unused = self.conf.activateProfile("work")
		_unused = self.conf.activateProfile("email")
		self.assertEqual(secretStore.getSecret(TEST_ENGINE_ID, "apiKey"), "work-key")

	def test_profileKeysDoNotLeakIntoOtherProfiles(self) -> None:
		"""A key set only in one profile is invisible to a sibling profile."""
		self._store("work", "work-key")
		_unused = self.conf.activateProfile("email")
		resolved = secretStore.resolveSecret(TEST_ENGINE_ID, "apiKey")
		self.assertEqual(resolved.value, "")
		self.assertIs(resolved.source, secretStore.CredentialSource.NONE)

	def test_aProfileSeesOnlyItsOwnStoredKey(self) -> None:
		"""Reading a single profile ignores what it would inherit, so the settings field can too."""
		self._store(None, "shared-key")
		self.assertEqual(secretStore.getStoredSecret(TEST_ENGINE_ID, "apiKey", "work"), "")
		self.assertEqual(secretStore.getStoredSecret(TEST_ENGINE_ID, "apiKey", None), "shared-key")


@unittest.skipIf(
	secretStore._credentialApi is None,
	"The Windows Credential Locker is not available on this system.",
)
class CredentialLockerTest(unittest.TestCase):
	"""Check storing, reading, listing, and removing real credentials."""

	def setUp(self) -> None:
		self.conf = FakeConfigManager()
		setattr(nvdaConfig, "conf", self.conf)
		for profileName in (None, "polyglotSelfTestProfile", "polyglotSelfTestRenamed"):
			self.addCleanup(secretStore.deleteSecret, TEST_ENGINE_ID, "apiKey", profileName)
			_unused = secretStore.deleteSecret(TEST_ENGINE_ID, "apiKey", profileName)

	def test_storedValueIsReadBack(self) -> None:
		"""A stored credential round-trips, including non-ASCII characters."""
		self.assertTrue(secretStore.setSecret(TEST_ENGINE_ID, "apiKey", "sk-tëst-密钥", None))
		self.assertEqual(secretStore.getSecret(TEST_ENGINE_ID, "apiKey"), "sk-tëst-密钥")

	def test_missingCredentialReadsAsEmpty(self) -> None:
		"""Reading a credential that was never stored is not an error."""
		self.assertEqual(secretStore.getSecret(TEST_ENGINE_ID, "apiKey"), "")

	def test_storingAnEmptyValueRemovesTheCredential(self) -> None:
		"""Clearing a field deletes the stored credential rather than storing a blank one."""
		self.assertTrue(secretStore.setSecret(TEST_ENGINE_ID, "apiKey", "sk-test", None))
		self.assertTrue(secretStore.setSecret(TEST_ENGINE_ID, "apiKey", "   ", None))
		self.assertEqual(secretStore.getSecret(TEST_ENGINE_ID, "apiKey"), "")

	def test_deletingAnAbsentCredentialSucceeds(self) -> None:
		"""Removal reports success when nothing is stored."""
		self.assertTrue(secretStore.deleteSecret(TEST_ENGINE_ID, "apiKey", None))

	def test_storedCredentialsAreListed(self) -> None:
		"""Stored credentials can be found again so they can be reported and cleared."""
		self.assertTrue(secretStore.setSecret(TEST_ENGINE_ID, "apiKey", "sk-test", None))
		self.assertIn(
			secretStore.getTargetName(TEST_ENGINE_ID, "apiKey"),
			secretStore.getStoredTargetNames(),
		)

	def test_oversizedValueIsRejected(self) -> None:
		"""A value too large for the Credential Locker is refused instead of truncated."""
		self.assertFalse(secretStore.setSecret(TEST_ENGINE_ID, "apiKey", "x" * 4096, None))
		self.assertEqual(secretStore.getSecret(TEST_ENGINE_ID, "apiKey"), "")

	def test_eachProfileKeepsItsOwnCredential(self) -> None:
		"""Storing a key for a profile leaves the normal configuration's key alone."""
		self.assertTrue(secretStore.setSecret(TEST_ENGINE_ID, "apiKey", "shared-key", None))
		profileName = "polyglotSelfTestProfile"
		self.assertTrue(secretStore.setSecret(TEST_ENGINE_ID, "apiKey", "profile-key", profileName))
		self.assertEqual(secretStore.getStoredSecret(TEST_ENGINE_ID, "apiKey", None), "shared-key")
		self.assertEqual(
			secretStore.getStoredSecret(TEST_ENGINE_ID, "apiKey", profileName),
			"profile-key",
		)

	def test_clearingAProfileKeyRestoresTheInheritedOne(self) -> None:
		"""Emptying a profile's field makes it inherit again instead of leaving it blank."""
		profileName = "polyglotSelfTestProfile"
		_unused = self.conf.activateProfile(profileName)
		self.assertTrue(secretStore.setSecret(TEST_ENGINE_ID, "apiKey", "shared-key", None))
		self.assertTrue(secretStore.setSecret(TEST_ENGINE_ID, "apiKey", "profile-key", profileName))
		self.assertEqual(secretStore.getSecret(TEST_ENGINE_ID, "apiKey"), "profile-key")
		self.assertTrue(secretStore.setSecret(TEST_ENGINE_ID, "apiKey", "", profileName))
		self.assertEqual(secretStore.getSecret(TEST_ENGINE_ID, "apiKey"), "shared-key")

	def test_credentialsFollowARenamedProfile(self) -> None:
		"""A renamed profile keeps the keys it was set up with."""
		self.assertTrue(
			secretStore.setSecret(TEST_ENGINE_ID, "apiKey", "profile-key", "polyglotSelfTestProfile"),
		)
		self.assertEqual(
			secretStore.renameProfileSecrets("polyglotSelfTestProfile", "polyglotSelfTestRenamed"),
			1,
		)
		self.assertEqual(
			secretStore.getStoredSecret(TEST_ENGINE_ID, "apiKey", "polyglotSelfTestProfile"),
			"",
		)
		self.assertEqual(
			secretStore.getStoredSecret(TEST_ENGINE_ID, "apiKey", "polyglotSelfTestRenamed"),
			"profile-key",
		)

	def test_recasingAProfileNameKeepsItsCredentials(self) -> None:
		"""Windows ignores case in target names, so a rename that only recases must move nothing."""
		profileName = "polyglotSelfTestProfile"
		self.assertTrue(secretStore.setSecret(TEST_ENGINE_ID, "apiKey", "profile-key", profileName))
		self.assertEqual(secretStore.renameProfileSecrets(profileName, profileName.upper()), 0)
		self.assertEqual(
			secretStore.getStoredSecret(TEST_ENGINE_ID, "apiKey", profileName.upper()),
			"profile-key",
		)

	def test_credentialsDoNotOutliveADeletedProfile(self) -> None:
		"""Deleting a profile takes its keys out of Windows' Credential Manager too."""
		profileName = "polyglotSelfTestProfile"
		self.assertTrue(secretStore.setSecret(TEST_ENGINE_ID, "apiKey", "shared-key", None))
		self.assertTrue(secretStore.setSecret(TEST_ENGINE_ID, "apiKey", "profile-key", profileName))
		self.assertEqual(secretStore.deleteSecretsForProfile(profileName), 1)
		self.assertEqual(secretStore.getStoredSecret(TEST_ENGINE_ID, "apiKey", profileName), "")
		# The normal configuration is untouched, so every other profile keeps working.
		self.assertEqual(secretStore.getStoredSecret(TEST_ENGINE_ID, "apiKey", None), "shared-key")


class UnavailableStoreTest(unittest.TestCase):
	"""Check that a system without the Credential Locker degrades safely."""

	def setUp(self) -> None:
		setattr(nvdaConfig, "conf", FakeConfigManager())

	def test_readingReturnsNothing(self) -> None:
		"""No credential is invented when there is nowhere to store one."""
		with patch.object(secretStore, "_credentialApi", None):
			self.assertEqual(secretStore.getSecret(TEST_ENGINE_ID, "apiKey"), "")

	def test_storingReportsFailure(self) -> None:
		"""A credential that cannot be stored securely is reported, not silently dropped."""
		with patch.object(secretStore, "_credentialApi", None):
			self.assertFalse(secretStore.setSecret(TEST_ENGINE_ID, "apiKey", "sk-test", None))


if __name__ == "__main__":
	unittest.main()
