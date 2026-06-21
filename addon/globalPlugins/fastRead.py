# FastRead: interrupting live readout monitor for NVDA.

import types
import time

import addonHandler
import api
import controlTypes
import diffHandler
import globalPluginHandler
import speech
from scriptHandler import script, getLastScriptRepeatCount
import textInfos
import treeInterceptorHandler
import ui
import winUser
import wx

addonHandler.initTranslation()


POLL_INTERVAL_MS = 120
MIN_SPEAK_INTERVAL_SEC = 0.08
MAX_STORED_TEXT_LENGTH = 20000
MAX_SPOKEN_TEXT_LENGTH = 500
WATCHER_SLOTS = (1, 2, 3)
WATCHER_SPEAK_DELAY_MS = 250
SELECT_INSTRUCTION_PREFIXES = (
	"click to select an item for ",
	"click to select ",
)


def _cleanText(text, maxLength=MAX_STORED_TEXT_LENGTH, preserveLines=False):
	if text is None:
		return ""
	if not isinstance(text, str):
		text = str(text)
	if preserveLines:
		lines = (" ".join(line.split()) for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
		text = "\n".join(line for line in lines if line)
	else:
		text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
	text = _stripSelectionInstructionText(text, preserveLines=preserveLines)
	if maxLength and len(text) > maxLength:
		text = text[-maxLength:].lstrip()
	return text


def _stripSelectionInstructionText(text, preserveLines=False):
	if not text:
		return ""
	lines = text.split("\n") if preserveLines else [text]
	cleanedLines = []
	for line in lines:
		stripped = line.strip()
		lower = stripped.lower()
		for prefix in SELECT_INSTRUCTION_PREFIXES:
			if lower.startswith(prefix) and ". " in stripped:
				possibleValue = stripped.split(". ", 1)[1].strip()
				if possibleValue:
					stripped = possibleValue
				break
		cleanedLines.append(stripped)
	return "\n".join(line for line in cleanedLines if line)


def _objectText(obj):
	if obj is None:
		return ""
	parts = []
	for attr in ("name", "value", "description"):
		try:
			value = getattr(obj, attr)
		except Exception:
			continue
		value = _cleanText(value)
		if value and value not in parts:
			parts.append(value)

	# Some status-like controls expose useful text through simple review text
	# rather than name/value.
	try:
		textInfo = obj.makeTextInfo("all")
		text = _cleanText(textInfo.text)
	except Exception:
		text = ""
	if text and text not in parts:
		parts.append(text)

	if not parts:
		return ""
	return " ".join(parts)


def _textInfoText(obj):
	try:
		ti = obj.makeTextInfo(textInfos.POSITION_ALL)
	except Exception:
		return ""
	for getter in (
		lambda: diffHandler.prefer_difflib()._getText(ti),
		lambda: ti.text,
	):
		try:
			text = getter()
		except Exception:
			continue
		if text and not text.isspace():
			return _cleanText(text, preserveLines=True)
	return ""


def _liveTextText(obj):
	getText = getattr(obj, "_getText", None)
	if getText is None:
		return ""
	_refreshLiveText(obj)
	try:
		text = getText()
	except Exception:
		return ""
	if text and not text.isspace():
		return _cleanText(text, preserveLines=True)
	return ""


def _snapshotText(obj):
	if _isDocumentLike(obj):
		return _objectText(obj)
	if _isLiveTextLike(obj):
		text = _liveTextText(obj)
		if text:
			return text
	text = _textInfoText(obj)
	if text:
		return text
	return _objectText(obj)


def _sameObject(first, second):
	if first is None or second is None:
		return False
	try:
		return first == second
	except Exception:
		return False


def _navigatorObject():
	try:
		return api.getNavigatorObject()
	except Exception:
		return None


def _focusObject():
	try:
		return api.getFocusObject()
	except Exception:
		return None


def _className(obj):
	if obj is None:
		return ""
	return obj.__class__.__name__


def _isLiveTextLike(obj):
	if obj is None:
		return False
	if callable(getattr(obj, "_getText", None)):
		return True
	name = _className(obj).lower()
	return "livetext" in name or "terminal" in name


def _isOrdinaryEditableText(obj):
	if obj is None or _isLiveTextLike(obj):
		return False
	try:
		if obj.role == controlTypes.Role.EDITABLETEXT:
			return True
	except Exception:
		pass
	name = _className(obj).lower()
	return "editabletext" in name or "editor" in name


def _refreshLiveText(obj):
	if obj is None:
		return
	try:
		obj.redraw()
	except Exception:
		pass


def _isDocumentLike(obj):
	if obj is None:
		return False
	try:
		if isinstance(obj, treeInterceptorHandler.DocumentTreeInterceptor):
			return True
	except Exception:
		pass
	name = _className(obj).lower()
	return "vbuf" in name or "virtual" in name or "document" in name


def _objectArea(obj):
	location = _objectLocation(obj)
	if not location:
		return 0
	return location[2] * location[3]


def _betterReviewCandidate(navObj, focusObj):
	if navObj is None:
		return False
	if not _objectLocation(navObj):
		return False
	if focusObj is None:
		return True
	if _className(navObj) != _className(focusObj):
		return True
	focusLocation = _objectLocation(focusObj)
	navLocation = _objectLocation(navObj)
	if focusLocation and navLocation and navLocation != focusLocation:
		navArea = _objectArea(navObj)
		focusArea = _objectArea(focusObj)
		if navArea and focusArea and navArea <= focusArea:
			return True
	try:
		return bool(getattr(navObj, "name", "") and getattr(navObj, "name", "") != getattr(focusObj, "name", ""))
	except Exception:
		return False


def _browseTextObject():
	obj = _focusObject()
	try:
		treeInterceptor = obj.treeInterceptor
	except Exception:
		return None
	if treeInterceptor is None:
		return None
	try:
		passThrough = treeInterceptor.passThrough
	except Exception:
		passThrough = True
	if passThrough or not hasattr(treeInterceptor, "TextInfo"):
		return None
	return treeInterceptor


def _applicationLineInfo():
	obj = _focusObject()
	if obj is None:
		return None
	try:
		treeInterceptor = obj.treeInterceptor
	except Exception:
		treeInterceptor = None
	if (
		isinstance(treeInterceptor, treeInterceptorHandler.DocumentTreeInterceptor)
		and not treeInterceptor.passThrough
	):
		obj = treeInterceptor
	try:
		info = obj.makeTextInfo(textInfos.POSITION_CARET)
	except Exception:
		return None
	try:
		info.expand(textInfos.UNIT_LINE)
	except Exception:
		return None
	return info


def _applicationLineText():
	info = _applicationLineInfo()
	if info is None:
		return ""
	try:
		text = info.text
	except Exception:
		return ""
	if text and not text.isspace():
		return _cleanText(text, preserveLines=True)
	return ""


def _browseLineText():
	info = _browseLineInfo()
	if info is None:
		return ""
	try:
		text = info.text
	except Exception:
		return ""
	if text and not text.isspace():
		return _cleanText(text, preserveLines=True)
	return ""


def _browseLineInfo():
	info = _applicationLineInfo()
	if info is not None:
		return info
	try:
		info = api.getReviewPosition().copy()
		info.expand(textInfos.UNIT_LINE)
		return info
	except Exception:
		pass
	obj = _browseTextObject()
	if obj is None:
		return None
	for position in (textInfos.POSITION_CARET, textInfos.POSITION_SELECTION, textInfos.POSITION_FIRST):
		try:
			info = obj.makeTextInfo(position)
			info.expand(textInfos.UNIT_LINE)
		except Exception:
			continue
		return info
	return None


def _speechForChange(oldText, newText):
	if len(newText) < len(oldText) and oldText.endswith(newText):
		return ""
	try:
		lines = diffHandler.prefer_difflib().diff(newText, oldText)
	except Exception:
		lines = []
	if lines:
		speakText = " ".join(lines)
		if _changeFragmentTooSmall(speakText, newText):
			return newText
		return speakText
	if not oldText:
		return newText
	if newText.startswith(oldText):
		speakText = newText[len(oldText):].strip()
		if _changeFragmentTooSmall(speakText, newText):
			return newText
		return speakText
	if oldText in newText:
		speakText = newText.rsplit(oldText, 1)[-1].strip()
		if _changeFragmentTooSmall(speakText, newText):
			return newText
		return speakText
	return newText


def _changeFragmentTooSmall(fragment, fullText):
	fragment = _cleanText(fragment, maxLength=0)
	fullText = _cleanText(fullText, maxLength=0)
	if not fragment or len(fullText) < 12:
		return False
	if len(fragment) <= 2:
		return True
	if len(fragment) <= 4 and not any(ch.isalpha() for ch in fragment):
		return True
	return False


def _objectLocation(obj):
	try:
		left, top, width, height = obj.location
	except Exception:
		return None
	if left < 0 or top < 0 or width <= 0 or height <= 0:
		return None
	return left, top, width, height


def _rootWindowHandle(obj):
	if obj is None:
		return 0
	try:
		handle = int(getattr(obj, "windowHandle", 0) or 0)
	except Exception:
		handle = 0
	if not handle:
		return 0
	try:
		return int(winUser.getAncestor(handle, winUser.GA_ROOT) or handle)
	except Exception:
		return handle


def _currentRootWindowHandle():
	handle = _rootWindowHandle(_focusObject())
	if handle:
		return handle
	return _rootWindowHandle(_navigatorObject())


class WatcherSlot:
	def __init__(self, slot, rootWindow, source, textInfo=None, obj=None, lastText=""):
		self.slot = slot
		self.rootWindow = rootWindow
		self.source = source
		self.textInfo = textInfo
		self.obj = obj
		self.lastText = lastText
		self.unavailableReported = False

	def snapshot(self):
		if self.rootWindow and _currentRootWindowHandle() != self.rootWindow:
			return None, False
		text = ""
		if self.source == "line" and self.textInfo is not None:
			try:
				info = self.textInfo.copy()
				info.expand(textInfos.UNIT_LINE)
				text = _cleanText(info.text, preserveLines=True)
			except Exception:
				text = ""
		if not text and self.obj is not None:
			text = _snapshotText(self.obj)
		return text, True


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	scriptCategory = _("FastRead")

	def __init__(self):
		super().__init__()
		self._enabled = False
		self._monitorObj = None
		self._monitorSource = "focus"
		self._lastText = ""
		self._lastSpokenAt = 0
		self._liveTextHookObj = None
		self._liveTextHookOriginal = None
		self._watchers = {}
		self._pendingWatcherSpeech = {}
		self._pendingWatcherCallLater = {}
		self._watcherPollCallLater = None
		self._timer = wx.Timer(_guiMainFrame())
		self._timer.Bind(wx.EVT_TIMER, self._onTimer)

	def terminate(self):
		try:
			self._timer.Stop()
		except Exception:
			pass
		self._stopWatcherPoll()
		self._uninstallLiveTextHook()
		self._watchers.clear()
		self._pendingWatcherSpeech.clear()
		for callLater in self._pendingWatcherCallLater.values():
			try:
				callLater.Stop()
			except Exception:
				pass
		self._pendingWatcherCallLater.clear()
		self._watcherPollCallLater = None
		super().terminate()

	def _resetMonitor(self, obj=None):
		self._uninstallLiveTextHook()
		self._monitorObj = obj or self._chooseMonitorObject()
		if _isLiveTextLike(self._monitorObj):
			self._installLiveTextHook(self._monitorObj)
		self._lastText = self._currentSnapshot()
		self._lastSpokenAt = 0

	def _chooseMonitorObject(self):
		self._monitorSource, obj = self._monitorCandidate()
		return obj

	def _monitorCandidate(self):
		focusObj = _focusObject()
		if _isOrdinaryEditableText(focusObj):
			return "typing", None
		browseObj = _browseTextObject()
		if browseObj is not None:
			return "browse", browseObj
		navObj = _navigatorObject()
		if _betterReviewCandidate(navObj, focusObj):
			return "review", navObj
		return "focus", focusObj

	def _monitorSourceChanged(self):
		source, obj = self._monitorCandidate()
		if source != self._monitorSource:
			return True
		if source == "browse":
			return obj is not None and not _sameObject(obj, self._monitorObj)
		if source in ("focus", "review"):
			return obj is not None and not _sameObject(obj, self._monitorObj)
		return False

	def _currentMonitorObject(self):
		if self._monitorSource == "browse":
			return _browseTextObject() or self._monitorObj
		if self._monitorSource == "review":
			# In browse mode, NVDA can replace the underlying object as the
			# document refreshes. Reading the current navigator object keeps the
			# monitor attached to the item the user is reviewing.
			return _navigatorObject() or self._monitorObj
		if self._monitorSource == "typing":
			return None
		return self._monitorObj

	def _currentSnapshot(self):
		if self._monitorSource == "typing":
			return ""
		currentObj = self._currentMonitorObject()
		if _isLiveTextLike(currentObj):
			text = _snapshotText(currentObj)
			if text:
				return text
		text = _applicationLineText()
		if text:
			return text
		if self._monitorSource == "browse":
			text = _browseLineText()
			if text:
				return text
			return ""
		if _isDocumentLike(currentObj):
			return ""
		return _snapshotText(currentObj)

	def _installLiveTextHook(self, obj):
		if obj is None or self._liveTextHookObj is obj:
			return
		reportNewText = getattr(obj, "_reportNewText", None)
		if not callable(reportNewText):
			return

		def fastReadReportNewText(liveObj, line):
			if not self._enabled or not _sameObject(liveObj, self._monitorObj):
				return self._liveTextHookOriginal(line)
			self._speakImmediate(line)

		self._liveTextHookObj = obj
		self._liveTextHookOriginal = reportNewText
		try:
			obj._reportNewText = types.MethodType(fastReadReportNewText, obj)
			startMonitoring = getattr(obj, "startMonitoring", None)
			if callable(startMonitoring):
				startMonitoring()
		except Exception:
			self._liveTextHookObj = None
			self._liveTextHookOriginal = None

	def _uninstallLiveTextHook(self):
		obj = self._liveTextHookObj
		original = self._liveTextHookOriginal
		self._liveTextHookObj = None
		self._liveTextHookOriginal = None
		if obj is None or original is None:
			return
		try:
			obj._reportNewText = original
		except Exception:
			pass

	def _speakImmediate(self, text):
		text = _cleanText(text, MAX_SPOKEN_TEXT_LENGTH)
		if not text:
			return
		now = time.monotonic()
		if now - self._lastSpokenAt < MIN_SPEAK_INTERVAL_SEC:
			return
		self._lastText = text
		self._lastSpokenAt = now
		try:
			speech.cancelSpeech()
		except Exception:
			pass
		ui.message(text)

	def _speakWatcher(self, slot, text):
		text = _cleanText(text, MAX_SPOKEN_TEXT_LENGTH)
		if not text:
			return
		self._pendingWatcherSpeech[slot] = text
		if slot not in self._pendingWatcherCallLater:
			self._pendingWatcherCallLater[slot] = wx.CallLater(
				WATCHER_SPEAK_DELAY_MS,
				self._speakPendingWatcher,
				slot,
			)

	def _speakPendingWatcher(self, slot):
		self._pendingWatcherCallLater.pop(slot, None)
		text = self._pendingWatcherSpeech.pop(slot, "")
		if not self._watchers.get(slot) or not text:
			return
		ui.message(text)

	def _speakChange(self, text):
		text = _cleanText(text, preserveLines=True)
		if not text or text == self._lastText:
			return
		now = time.monotonic()
		if now - self._lastSpokenAt < MIN_SPEAK_INTERVAL_SEC:
			return
		speakText = _cleanText(_speechForChange(self._lastText, text), MAX_SPOKEN_TEXT_LENGTH)
		if not speakText:
			self._lastText = text
			return
		self._lastText = text
		self._lastSpokenAt = now
		try:
			speech.cancelSpeech()
		except Exception:
			pass
		ui.message(speakText)

	def _checkObject(self, obj=None):
		if not self._enabled:
			return
		if _isOrdinaryEditableText(_focusObject()):
			self._monitorSource = "typing"
			self._monitorObj = None
			self._lastText = ""
			return
		if self._monitorSourceChanged():
			self._resetMonitor()
			return
		if self._monitorSource == "browse":
			text = self._currentSnapshot()
			if text:
				self._speakChange(text)
			return
		currentObj = self._currentMonitorObject()
		if obj is not None and currentObj is not None and not _sameObject(obj, currentObj):
			return
		if currentObj is None:
			self._resetMonitor()
			currentObj = self._currentMonitorObject()
		self._speakChange(self._currentSnapshot())

	def _checkWatchers(self):
		if not self._enabled:
			return False
		changed = False
		for slot in WATCHER_SLOTS:
			watcher = self._watchers.get(slot)
			if watcher is None:
				continue
			text, inWindow = watcher.snapshot()
			if not inWindow:
				continue
			if not text:
				if not watcher.unavailableReported:
					watcher.unavailableReported = True
					self._speakWatcher(slot, _("unavailable"))
				continue
			watcher.unavailableReported = False
			if text != watcher.lastText:
				watcher.lastText = text
				changed = True
				self._speakWatcher(slot, text)
		return changed

	def _onTimer(self, evt):
		self._checkObject()

	def _onWatcherPoll(self):
		self._watcherPollCallLater = None
		self._checkWatchers()
		self._scheduleWatcherPoll()

	def _stopWatcherPoll(self):
		callLater = self._watcherPollCallLater
		self._watcherPollCallLater = None
		if callLater is None:
			return
		try:
			callLater.Stop()
		except Exception:
			pass

	def _scheduleWatcherPoll(self):
		if not (self._enabled and self._watchers):
			self._stopWatcherPoll()
			return
		if self._watcherPollCallLater is not None:
			return
		self._watcherPollCallLater = wx.CallLater(POLL_INTERVAL_MS, self._onWatcherPoll)

	def _updateWatcherPoll(self):
		if self._enabled and self._watchers:
			self._scheduleWatcherPoll()
		else:
			self._stopWatcherPoll()

	def _makeWatcher(self, slot):
		rootWindow = _currentRootWindowHandle()
		lineInfo = _browseLineInfo()
		if lineInfo is not None:
			try:
				storedInfo = lineInfo.copy()
				storedInfo.expand(textInfos.UNIT_LINE)
				text = _cleanText(storedInfo.text, preserveLines=True)
			except Exception:
				storedInfo = None
				text = ""
			if text:
				return WatcherSlot(slot, rootWindow, "line", textInfo=storedInfo, obj=_navigatorObject(), lastText=text)
		source, obj = self._monitorCandidate()
		text = _snapshotText(obj)
		if text:
			return WatcherSlot(slot, rootWindow, source, obj=obj, lastText=text)
		return None

	def _watcherCommand(self, slot):
		if getLastScriptRepeatCount() >= 1:
			if slot in self._watchers:
				del self._watchers[slot]
				self._pendingWatcherSpeech.pop(slot, None)
				callLater = self._pendingWatcherCallLater.pop(slot, None)
				if callLater is not None:
					try:
						callLater.Stop()
					except Exception:
						pass
				self._updateWatcherPoll()
				ui.message(_("Watcher {slot} cleared").format(slot=slot))
				return
			watcher = self._makeWatcher(slot)
			if watcher is None:
				ui.message(_("No readable text for watcher {slot}").format(slot=slot))
				return
			self._watchers[slot] = watcher
			self._updateWatcherPoll()
			ui.message(_("Watcher {slot} set: {text}").format(
				slot=slot,
				text=_cleanText(watcher.lastText, MAX_SPOKEN_TEXT_LENGTH),
			))
			return
		watcher = self._watchers.get(slot)
		if watcher is None:
			ui.message(_("Watcher {slot} is not set. Press twice to set it.").format(slot=slot))
			return
		text, inWindow = watcher.snapshot()
		if not inWindow:
			ui.message(_("Watcher {slot} is outside the current window").format(slot=slot))
			return
		if text:
			watcher.lastText = text
			ui.message(_("Watcher {slot}: {text}").format(
				slot=slot,
				text=_cleanText(text, MAX_SPOKEN_TEXT_LENGTH),
			))
		else:
			ui.message(_("Watcher {slot} unavailable").format(slot=slot))

	def event_gainFocus(self, obj, nextHandler):
		nextHandler()
		if self._enabled and self._monitorSource == "focus":
			self._resetMonitor(obj)

	def event_textChange(self, obj, nextHandler):
		if self._enabled and _isLiveTextLike(obj):
			if not _sameObject(obj, self._monitorObj):
				self._monitorSource = "focus"
				self._resetMonitor(obj)
				return
			self._speakChange(_snapshotText(obj))
			return
		nextHandler()
		if self._enabled and not _isOrdinaryEditableText(obj):
			self._checkObject(obj)

	def event_nameChange(self, obj, nextHandler):
		nextHandler()
		self._checkObject(obj)

	def event_valueChange(self, obj, nextHandler):
		nextHandler()
		self._checkObject(obj)

	def event_descriptionChange(self, obj, nextHandler):
		nextHandler()
		self._checkObject(obj)

	def event_liveRegionChange(self, obj, nextHandler):
		nextHandler()
		if self._enabled:
			text = _objectText(obj)
			if text:
				self._speakChange(text)

	@script(
		description=_("Toggles FastRead monitoring of the current focus or browse object."),
		gesture="kb:NVDA+y",
	)
	def script_toggleFastRead(self, gesture):
		if self._enabled:
			self._enabled = False
			self._uninstallLiveTextHook()
			self._monitorObj = None
			self._monitorSource = "focus"
			self._lastText = ""
			self._timer.Stop()
			self._updateWatcherPoll()
			ui.message(_("FastRead off"))
			return
		self._enabled = True
		self._resetMonitor()
		self._timer.Start(POLL_INTERVAL_MS)
		self._updateWatcherPoll()
		text = self._lastText
		if text:
			ui.message(_("FastRead on {source}: {text}").format(
				source=self._monitorSource,
				text=_cleanText(text, MAX_SPOKEN_TEXT_LENGTH),
			))
		else:
			ui.message(_("FastRead on"))

	@script(
		description=_("FastRead watcher 1. Single press to read; double press to set or clear."),
		gesture="kb:NVDA+8",
	)
	def script_watcher1(self, gesture):
		self._watcherCommand(1)

	@script(
		description=_("FastRead watcher 2. Single press to read; double press to set or clear."),
		gesture="kb:NVDA+9",
	)
	def script_watcher2(self, gesture):
		self._watcherCommand(2)

	@script(
		description=_("FastRead watcher 3. Single press to read; double press to set or clear."),
		gesture="kb:NVDA+0",
	)
	def script_watcher3(self, gesture):
		self._watcherCommand(3)

def _guiMainFrame():
	try:
		import gui
		return gui.mainFrame
	except Exception:
		return None
