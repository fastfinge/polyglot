# Copyright (C) 2025-2026 cary-rowen <cary-rowen@outlook.com>
# This file is covered by the GNU General Public License version 3 or later.
# See the file COPYING.txt for more details.

"""
cdpBridge - Synchronous bridge to Chrome Headless via Chrome DevTools Protocol (CDP).

Thread-safe: all WebSocket operations are serialized via a lock, and each
evaluateSync call uses a unique, atomically-incremented message ID.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import winreg
from typing import Any
from collections.abc import Callable

import globalVars
from logHandler import log

import websocket


def _getUserDataDir() -> str:
	"""Return the local Chrome profile directory used by Chrome AI."""
	localAppData = os.environ.get("LOCALAPPDATA")
	if localAppData:
		return os.path.join(localAppData, "Polyglot", "ChromeAI")
	return os.path.join(globalVars.appArgs.configPath, "polyglot_chrome_ai")


_USER_DATA_DIR = _getUserDataDir()
_DEVTOOLS_ACTIVE_PORT_FILE = os.path.join(_USER_DATA_DIR, "DevToolsActivePort")
_PAGE_FILE = os.path.join(_USER_DATA_DIR, "chrome_ai.html")


class CdpError(Exception):
	"""Raised when Chrome DevTools Protocol communication fails."""

	pass


class CdpBridge:
	"""Manage synchronous, serialized CDP access to Polyglot's headless Chrome process."""

	_instance = None
	_chromeProcess: subprocess.Popen | None = None
	_ws: websocket.WebSocket | None = None
	_wsLock = threading.Lock()
	_nextMsgId = 0
	_msgIdLock = threading.Lock()
	_debugPort: int | None = None
	_staleDevToolsActivePort: tuple[int, str] | None = None
	_targetId: str | None = None
	_doesOwnBrowser = False

	@classmethod
	def getInstance(cls) -> "CdpBridge":
		"""Return the singleton CDP bridge instance."""
		if cls._instance is None:
			cls._instance = CdpBridge()
		return cls._instance

	def _allocateMsgId(self) -> int:
		"""Return a unique CDP command message ID."""
		with self._msgIdLock:
			self._nextMsgId += 1
			return self._nextMsgId

	def _getChromePath(self) -> str:
		"""Find Chrome's executable via the registry, common paths, or PATH."""
		regPaths = [
			(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"),
			(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"),
		]
		for hkey, subKey in regPaths:
			try:
				with winreg.OpenKey(hkey, subKey) as key:
					path, _ = winreg.QueryValueEx(key, "")
					if os.path.exists(path):
						return path
			except FileNotFoundError:
				continue
		candidates = [
			Path(os.environ.get("PROGRAMFILES", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
			Path(os.environ.get("PROGRAMFILES(X86)", ""))
			/ "Google"
			/ "Chrome"
			/ "Application"
			/ "chrome.exe",
			Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
		]
		for candidate in candidates:
			if candidate.exists():
				return str(candidate)
		fromPath = shutil.which("chrome.exe") or shutil.which("chrome")
		if fromPath:
			return fromPath
		return ""

	def startBrowser(self) -> None:
		"""Start the managed headless Chrome instance when needed."""
		if self._chromeProcess:
			if self._chromeProcess.poll() is None:
				return
			self._chromeProcess = None
			self._doesOwnBrowser = False
		self._debugPort = None
		self._targetId = None
		chromePath = self._getChromePath()
		if not chromePath:
			raise CdpError("Chrome not found. Please install Google Chrome.")
		os.makedirs(_USER_DATA_DIR, exist_ok=True)
		pageUrl = self._preparePageUrl()
		self._staleDevToolsActivePort = self._readDevToolsActivePort()
		try:
			os.remove(_DEVTOOLS_ACTIVE_PORT_FILE)
		except FileNotFoundError:
			pass
		except OSError:
			log.warning("Could not remove stale Chrome DevToolsActivePort file.", exc_info=True)
		log.debug("Launching managed Chrome Headless.")
		try:
			self._chromeProcess = subprocess.Popen(
				[
					chromePath,
					"--headless=new",
					"--remote-debugging-port=0",
					f"--user-data-dir={_USER_DATA_DIR}",
					"--remote-allow-origins=*",
					"--enable-features=TranslationAPI",
					"--disable-gpu",
					"--mute-audio",
					"--no-first-run",
					"--no-default-browser-check",
					pageUrl,
				],
				stdout=subprocess.DEVNULL,
				stderr=subprocess.DEVNULL,
			)
			self._doesOwnBrowser = True
		except Exception as e:
			self._doesOwnBrowser = False
			raise CdpError(f"Failed to start Chrome ({type(e).__name__}).") from None

	def _readDevToolsActivePort(self) -> tuple[int, str] | None:
		"""Read Chrome's DevToolsActivePort port and browser path if available."""
		try:
			with open(_DEVTOOLS_ACTIVE_PORT_FILE, "r", encoding="utf-8") as portFile:
				firstLine = portFile.readline().strip()
				secondLine = portFile.readline().strip()
				if firstLine and secondLine:
					return int(firstLine), secondLine
		except (FileNotFoundError, ValueError, OSError):
			return None
		return None

	def _writeDevToolsActivePort(self, devToolsActivePort: tuple[int, str]) -> None:
		"""Restore the DevToolsActivePort file for a reused Chrome endpoint."""
		port, browserPath = devToolsActivePort
		try:
			with open(_DEVTOOLS_ACTIVE_PORT_FILE, "w", encoding="utf-8") as portFile:
				portFile.write(f"{port}\n{browserPath}\n")
		except OSError:
			log.warning("Could not restore Chrome DevToolsActivePort file.", exc_info=True)

	def _readJsonFromPort(self, port: int, path: str, method: str = "GET", timeout: float = 1) -> Any:
		"""Read JSON from a Chrome debugging HTTP endpoint on a specific port."""
		url = f"http://127.0.0.1:{port}{path}"
		req = urllib.request.Request(url, method=method)
		with urllib.request.urlopen(req, timeout=timeout) as response:
			return json.loads(response.read().decode("utf-8"))

	def _reuseBrowserAtPort(
		self,
		devToolsActivePort: tuple[int, str],
		attempts: int = 10,
		timeout: float = 0.5,
		retryDelay: float = 0.2,
	) -> bool:
		"""Reuse an already-running managed Chrome debugging endpoint at a known port."""
		port, browserPath = devToolsActivePort
		for attempt in range(attempts):
			try:
				versionInfo = self._readJsonFromPort(port, "/json/version", timeout=timeout)
				if not isinstance(versionInfo, dict) or not self._matchesBrowserPath(
					versionInfo,
					browserPath,
				):
					if attempt + 1 < attempts and retryDelay:
						time.sleep(retryDelay)
					continue
				self._debugPort = port
				self._doesOwnBrowser = False
				log.debug("Reusing existing managed Chrome CDP endpoint.")
				return True
			except Exception:
				if attempt + 1 < attempts and retryDelay:
					time.sleep(retryDelay)
		log.warning("Could not reuse stale Chrome CDP endpoint.")
		return False

	def _matchesBrowserPath(self, versionInfo: dict[str, Any], browserPath: str) -> bool:
		"""Return whether /json/version matches the saved browser WebSocket path."""
		browserWsUrl = versionInfo.get("webSocketDebuggerUrl")
		if not isinstance(browserWsUrl, str):
			return False
		return urllib.parse.urlparse(browserWsUrl).path == browserPath

	def _preparePageUrl(self) -> str:
		"""Create the local secure-context page and return its file URL."""
		html = '<!doctype html><meta charset="utf-8"><title>Polyglot Chrome AI</title>'
		with open(_PAGE_FILE, "w", encoding="utf-8") as pageFile:
			pageFile.write(html)
		return Path(_PAGE_FILE).resolve().as_uri()

	def _getDebugPort(self) -> int:
		"""Read the ephemeral CDP port assigned to the managed Chrome process."""
		if self._debugPort is not None:
			return self._debugPort
		for _ in range(40):
			if self._chromeProcess and self._chromeProcess.poll() is not None:
				exitCode = self._chromeProcess.returncode
				self._chromeProcess = None
				self._doesOwnBrowser = False
				if exitCode == 21:
					staleDevToolsActivePort = self._staleDevToolsActivePort
					self._staleDevToolsActivePort = None
					if (
						staleDevToolsActivePort is not None
						and self._reuseBrowserAtPort(staleDevToolsActivePort)
						and self._debugPort is not None
					):
						self._writeDevToolsActivePort(staleDevToolsActivePort)
						return self._debugPort
					raise CdpError("Chrome AI profile is already in use by another Chrome process.")
				raise CdpError(f"Chrome exited before CDP became available: {exitCode}")
			devToolsActivePort = self._readDevToolsActivePort()
			if devToolsActivePort is not None:
				self._debugPort = devToolsActivePort[0]
				self._staleDevToolsActivePort = None
				return self._debugPort
			time.sleep(0.25)
		raise CdpError("Timeout waiting for Chrome DevToolsActivePort.")

	def _readJsonEndpoint(self, path: str, method: str = "GET") -> Any:
		"""Read JSON from the managed Chrome debugging HTTP endpoint."""
		port = self._getDebugPort()
		return self._readJsonFromPort(port, path, method=method)

	def _findPageTargetInList(self, targets: Any, pageUrl: str) -> str | None:
		"""Find the Chrome AI page WebSocket URL in a CDP target list."""
		if not isinstance(targets, list):
			return None
		for target in targets:
			if not isinstance(target, dict):
				continue
			if target.get("type") != "page":
				continue
			wsUrl = target.get("webSocketDebuggerUrl")
			if not isinstance(wsUrl, str):
				continue
			targetId = target.get("id")
			if self._targetId and targetId and str(targetId) == self._targetId:
				return wsUrl
			if target.get("url") == pageUrl:
				self._targetId = str(targetId) if targetId else None
				return wsUrl
		return None

	def _findPageTarget(self, pageUrl: str) -> str | None:
		"""Find an existing target for the Chrome AI page."""
		try:
			targets = self._readJsonEndpoint("/json/list")
		except Exception:
			return None
		return self._findPageTargetInList(targets, pageUrl)

	def _createPageTarget(self, pageUrl: str) -> str | None:
		"""Create a page target and return its WebSocket URL when available."""
		quotedUrl = urllib.parse.quote(pageUrl, safe="")
		try:
			target = self._readJsonEndpoint(f"/json/new?{quotedUrl}", method="PUT")
		except Exception:
			log.warning("Failed to create Chrome CDP page target.", exc_info=True)
			return None
		if isinstance(target, dict):
			targetId = target.get("id")
			self._targetId = str(targetId) if targetId else None
			wsUrl = target.get("webSocketDebuggerUrl")
			if isinstance(wsUrl, str):
				return wsUrl
		return None

	def _getWebSocketUrl(self) -> str:
		"""Return a page-target WebSocket URL from the managed Chrome process."""
		pageUrl = self._preparePageUrl()
		for _ in range(20):
			try:
				wsUrl = self._findPageTarget(pageUrl)
				if wsUrl:
					return wsUrl
				wsUrl = self._createPageTarget(pageUrl)
				if wsUrl:
					return wsUrl
			except Exception:
				log.debug("Chrome CDP page target is not ready yet.", exc_info=True)
			time.sleep(0.5)
		raise CdpError("Timeout waiting for Chrome CDP endpoint.")

	def _enableProtocolDomain(self, method: str) -> None:
		"""Enable a CDP protocol domain on the current WebSocket."""
		assert self._ws is not None
		msgId = self._allocateMsgId()
		self._ws.send(json.dumps({"id": msgId, "method": method}))
		while True:
			response = json.loads(self._ws.recv())
			if response.get("id") != msgId:
				continue
			if "error" in response:
				raise CdpError(f"CDP error: {response['error']}")
			return

	def _logPageDiagnostics(self) -> None:
		"""Log readiness, security context, and API availability for the page target."""
		assert self._ws is not None
		expression = """
		JSON.stringify({
			readyState: document.readyState,
			isSecureContext: globalThis.isSecureContext,
			hasTranslator: typeof Translator !== 'undefined',
			userActivation: navigator.userActivation ? {
				isActive: navigator.userActivation.isActive,
				hasBeenActive: navigator.userActivation.hasBeenActive,
			} : null,
		})
		"""
		msgId = self._allocateMsgId()
		self._ws.send(
			json.dumps(
				{
					"id": msgId,
					"method": "Runtime.evaluate",
					"params": {
						"expression": expression,
						"awaitPromise": False,
						"returnByValue": True,
					},
				},
			),
		)
		while True:
			response = json.loads(self._ws.recv())
			if response.get("id") != msgId:
				continue
			resultValue = response.get("result", {}).get("result", {}).get("value", "{}")
			try:
				diagnostics = json.loads(resultValue) if isinstance(resultValue, str) else resultValue
			except (json.JSONDecodeError, TypeError):
				diagnostics = {"raw": resultValue}
			log.debug("Chrome AI page diagnostics: %s", diagnostics)
			return

	def ensureConnection(self) -> None:
		"""Ensure a Runtime-enabled WebSocket connection is ready."""
		with self._wsLock:
			if self._ws and self._ws.connected:
				return
			self.startBrowser()
			wsUrl = self._getWebSocketUrl()
			log.debug("Connecting to managed Chrome CDP endpoint.")
			try:
				self._ws = websocket.create_connection(wsUrl, timeout=300)
				self._enableProtocolDomain("Runtime.enable")
				self._enableProtocolDomain("Page.enable")
				self._logPageDiagnostics()
				log.debug("CDP Runtime domain enabled.")
			except Exception as e:
				self._ws = None
				raise CdpError(f"WebSocket connection failed ({type(e).__name__}).") from None

	def _formatExceptionDetails(self, exceptionDetails: dict[str, Any]) -> str:
		"""Format bounded CDP Runtime exception details for diagnostics."""
		text = exceptionDetails.get("text", "Runtime exception")
		exception = exceptionDetails.get("exception", {})
		className = exception.get("className") if isinstance(exception, dict) else None
		if className:
			return f"{className}: {text}"
		return str(text)

	def _getProcessCommandLine(self, processId: int) -> str | None:
		"""Return a process command line using NVDA's WMI lookup helper."""
		try:
			import appModuleHandler

			processInfo = appModuleHandler.getWmiProcessInfo(processId)
			commandLine = getattr(processInfo, "CommandLine", None)
		except Exception:
			log.debug(f"Could not read command line for Chrome process {processId}.", exc_info=True)
			return None
		return str(commandLine) if commandLine else None

	def _isManagedChromeProcess(self, processId: int) -> bool | None:
		"""Return whether a process matches Polyglot's managed Chrome, or None if unknown."""
		commandLine = self._getProcessCommandLine(processId)
		if commandLine is None:
			return None
		normalizedCommandLine = commandLine.replace("/", "\\").replace('"', "").casefold()
		normalizedUserDataDir = os.path.normpath(_USER_DATA_DIR).replace("/", "\\").casefold()
		return (
			f"--user-data-dir={normalizedUserDataDir}" in normalizedCommandLine
			and "--headless" in normalizedCommandLine
			and "--remote-debugging-port=" in normalizedCommandLine
		)

	def evaluateSync(
		self,
		jsPayload: str,
		onConsoleLog: Callable[[str], None] | None = None,
	) -> dict[str, Any]:
		"""
		Thread-safe JS evaluation. Acquires the WebSocket lock for the
		entire send/recv cycle, ensuring only one evaluation runs at a time.
		Automatically retries once on stale connection errors (e.g. WinError 10053).
		"""
		for attempt in range(2):
			self.ensureConnection()
			msgId = self._allocateMsgId()
			cmd = {
				"id": msgId,
				"method": "Runtime.evaluate",
				"params": {
					"expression": jsPayload,
					"awaitPromise": True,
					"returnByValue": True,
					"userGesture": True,
				},
			}
			with self._wsLock:
				try:
					log.debug(f"CDP: evaluate id={msgId}, payload={len(jsPayload)} chars")
					self._ws.send(json.dumps(cmd))
					while True:
						responseStr = self._ws.recv()
						if not responseStr:
							raise CdpError("WebSocket closed unexpectedly.")
						response = json.loads(responseStr)
						if response.get("method") == "Runtime.consoleAPICalled":
							args = response.get("params", {}).get("args", [])
							for arg in args:
								logText = str(arg.get("value", ""))
								if onConsoleLog and logText:
									onConsoleLog(logText)
							continue
						if response.get("id") == msgId:
							if "error" in response:
								raise CdpError(f"CDP error: {response['error']}")
							exceptionDetails = response.get("result", {}).get("exceptionDetails")
							if isinstance(exceptionDetails, dict):
								raise CdpError(self._formatExceptionDetails(exceptionDetails))
							resultValue = response.get("result", {}).get("result", {}).get("value", "{}")
							if isinstance(resultValue, dict):
								return resultValue
							if isinstance(resultValue, str):
								try:
									return json.loads(resultValue)
								except (json.JSONDecodeError, TypeError):
									return {"code": "PARSE_ERR", "raw": resultValue}
							return {"code": "PARSE_ERR", "raw": str(resultValue)}
				except websocket.WebSocketTimeoutException:
					try:
						self._ws.close()
					except Exception:
						pass
					self._ws = None
					raise CdpError("Timed out waiting for Chrome AI response.")
				except CdpError:
					raise
				except Exception as e:
					self._ws = None
					if attempt == 0:
						log.warning(
							"WebSocket connection lost; reconnecting (%s).",
							type(e).__name__,
						)
						continue
					raise CdpError(f"WebSocket error ({type(e).__name__}).") from None

	def terminate(self) -> None:
		"""Close the CDP connection and terminate the managed Chrome process."""
		if self._ws:
			try:
				self._ws.close()
			except Exception:
				pass
			self._ws = None
		if self._chromeProcess:
			processId = self._chromeProcess.pid
			if not self._doesOwnBrowser:
				log.debug(
					f"Chrome CDP process {processId} was not started by this bridge; leaving it running.",
				)
			elif self._chromeProcess.poll() is not None:
				log.debug(f"Chrome CDP process {processId} has already exited.")
			else:
				isManagedProcess = self._isManagedChromeProcess(processId)
				if isManagedProcess is False:
					log.warning(
						f"Chrome process {processId} did not match Polyglot ownership checks; "
						"leaving it running.",
					)
				else:
					if isManagedProcess is None:
						log.warning(
							f"Could not verify Chrome process {processId}; "
							"terminating because it was started by this bridge.",
						)
					log.info(f"Terminating Chrome CDP process {processId}.")
					try:
						self._chromeProcess.terminate()
						self._chromeProcess.wait(timeout=5)
					except subprocess.TimeoutExpired:
						log.warning("Chrome did not exit gracefully, force killing.")
						self._chromeProcess.kill()
						self._chromeProcess.wait(timeout=3)
					except Exception:
						pass
			self._chromeProcess = None
			self._debugPort = None
			self._staleDevToolsActivePort = None
			self._targetId = None
			self._doesOwnBrowser = False
