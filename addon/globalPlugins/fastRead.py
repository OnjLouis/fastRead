# FastRead: interrupting live readout monitor for NVDA.

import types
import time

import addonHandler
import api
import diffHandler
import globalPluginHandler
import speech
from scriptHandler import script
import textInfos
import treeInterceptorHandler
import ui
import wx

try:
	from ._onjGithubUpdater import GitHubReleaseUpdater
except Exception:
	GitHubReleaseUpdater = None

addonHandler.initTranslation()


POLL_INTERVAL_MS = 120
MIN_SPEAK_INTERVAL_SEC = 0.08
MAX_STORED_TEXT_LENGTH = 20000
MAX_SPOKEN_TEXT_LENGTH = 500


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
	if maxLength and len(text) > maxLength:
		text = text[-maxLength:].lstrip()
	return text


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
		return " ".join(lines)
	if not oldText:
		return newText
	if newText.startswith(oldText):
		return newText[len(oldText):].strip()
	if oldText in newText:
		return newText.rsplit(oldText, 1)[-1].strip()
	return newText


def _objectLocation(obj):
	try:
		left, top, width, height = obj.location
	except Exception:
		return None
	if left < 0 or top < 0 or width <= 0 or height <= 0:
		return None
	return left, top, width, height


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
		self._updater = None
		if GitHubReleaseUpdater:
			self._updater = GitHubReleaseUpdater("fastRead", "FastRead", "OnjLouis", "fastRead")
			self._updater.start()
		self._timer = wx.Timer(_guiMainFrame())
		self._timer.Bind(wx.EVT_TIMER, self._onTimer)

	def terminate(self):
		try:
			self._timer.Stop()
		except Exception:
			pass
		self._uninstallLiveTextHook()
		if self._updater:
			self._updater.stop()
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
		browseObj = _browseTextObject()
		if browseObj is not None:
			return "browse", browseObj
		focusObj = _focusObject()
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
		return self._monitorObj

	def _currentSnapshot(self):
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

	def _speakChange(self, text):
		text = _cleanText(text, preserveLines=True)
		if not text or text == self._lastText:
			return
		now = time.monotonic()
		if now - self._lastSpokenAt < MIN_SPEAK_INTERVAL_SEC:
			return
		if self._monitorSource == "browse":
			speakText = _cleanText(text, MAX_SPOKEN_TEXT_LENGTH)
		else:
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

	def _onTimer(self, evt):
		self._checkObject()

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
		if self._enabled:
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
			ui.message(_("FastRead off"))
			return
		self._enabled = True
		self._resetMonitor()
		self._timer.Start(POLL_INTERVAL_MS)
		text = self._lastText
		if text:
			ui.message(_("FastRead on {source}: {text}").format(
				source=self._monitorSource,
				text=_cleanText(text, MAX_SPOKEN_TEXT_LENGTH),
			))
		else:
			ui.message(_("FastRead on"))

	@script(description=_("Check for FastRead updates"))
	def script_checkForFastReadUpdate(self, gesture):
		if self._updater:
			wx.CallAfter(self._updater.checkNow, True)
		else:
			ui.message(_("Updater is not available"))


def _guiMainFrame():
	try:
		import gui
		return gui.mainFrame
	except Exception:
		return None
