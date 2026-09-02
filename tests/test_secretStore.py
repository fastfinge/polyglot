# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""Small runnable checks for credential storage outside NVDA's configuration file."""

import sys
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
addonHandler = ModuleType("addonHandler")
setattr(addonHandler, "initTranslation", Mock())
sys.modules.setdefault("addonHandler", addonHandler)
logHandler = ModuleType("logHandler")
setattr(logHandler, "log", Mock())
sys.modules.setdefault("logHandler", logHandler)
polyglotPackage = ModuleType("polyglot")
setattr(polyglotPackage, "__path__", [str(PROJECT_ROOT / "addon" / "globalPlugins" / "polyglot")])
sys.modules.setdefault("polyglot", polyglotPackage)

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


@unittest.skipIf(
	secretStore._credentialApi is None,
	"The Windows Credential Locker is not available on this system.",
)
class CredentialLockerTest(unittest.TestCase):
	"""Check storing, reading, listing, and removing real credentials."""

	def setUp(self) -> None:
		self.addCleanup(secretStore.deleteSecret, TEST_ENGINE_ID, "apiKey")
		_unused = secretStore.deleteSecret(TEST_ENGINE_ID, "apiKey")

	def test_storedValueIsReadBack(self) -> None:
		"""A stored credential round-trips, including non-ASCII characters."""
		self.assertTrue(secretStore.setSecret(TEST_ENGINE_ID, "apiKey", "sk-tëst-密钥"))
		self.assertEqual(secretStore.getSecret(TEST_ENGINE_ID, "apiKey"), "sk-tëst-密钥")

	def test_missingCredentialReadsAsEmpty(self) -> None:
		"""Reading a credential that was never stored is not an error."""
		self.assertEqual(secretStore.getSecret(TEST_ENGINE_ID, "apiKey"), "")

	def test_storingAnEmptyValueRemovesTheCredential(self) -> None:
		"""Clearing a field deletes the stored credential rather than storing a blank one."""
		self.assertTrue(secretStore.setSecret(TEST_ENGINE_ID, "apiKey", "sk-test"))
		self.assertTrue(secretStore.setSecret(TEST_ENGINE_ID, "apiKey", "   "))
		self.assertEqual(secretStore.getSecret(TEST_ENGINE_ID, "apiKey"), "")

	def test_deletingAnAbsentCredentialSucceeds(self) -> None:
		"""Removal reports success when nothing is stored."""
		self.assertTrue(secretStore.deleteSecret(TEST_ENGINE_ID, "apiKey"))

	def test_storedCredentialsAreListed(self) -> None:
		"""Stored credentials can be found again so they can be reported and cleared."""
		self.assertTrue(secretStore.setSecret(TEST_ENGINE_ID, "apiKey", "sk-test"))
		self.assertIn(
			secretStore.getTargetName(TEST_ENGINE_ID, "apiKey"),
			secretStore.getStoredTargetNames(),
		)

	def test_oversizedValueIsRejected(self) -> None:
		"""A value too large for the Credential Locker is refused instead of truncated."""
		self.assertFalse(secretStore.setSecret(TEST_ENGINE_ID, "apiKey", "x" * 4096))
		self.assertEqual(secretStore.getSecret(TEST_ENGINE_ID, "apiKey"), "")


class UnavailableStoreTest(unittest.TestCase):
	"""Check that a system without the Credential Locker degrades safely."""

	def test_readingReturnsNothing(self) -> None:
		"""No credential is invented when there is nowhere to store one."""
		with patch.object(secretStore, "_credentialApi", None):
			self.assertEqual(secretStore.getSecret(TEST_ENGINE_ID, "apiKey"), "")

	def test_storingReportsFailure(self) -> None:
		"""A credential that cannot be stored securely is reported, not silently dropped."""
		with patch.object(secretStore, "_credentialApi", None):
			self.assertFalse(secretStore.setSecret(TEST_ENGINE_ID, "apiKey", "sk-test"))


if __name__ == "__main__":
	unittest.main()
