import os
import re
import sys
from zipimport import zipimporter
import tokenize
from io import StringIO

from PyQt4 import QtCore, QtGui
from PyQt4.Qsci import QsciScintilla

from Extensions.BaseScintilla import BaseScintilla
from Extensions.ZoomWidget import ZoomWidget
from Extensions.Notification import Notification
from Extensions import StyleSheet


class TokenizeThread(QtCore.QThread):

    def run(self):
        self.tokenList = []
        try:
            for type, rep, begin, end, expr in \
                    tokenize.generate_tokens(StringIO(self.source).readline):
                if type == tokenize.OP:
                    line = begin[0]
                    if line not in self.tokenList:
                        self.tokenList.append(line)
        except:
            print("Token Error")

    def tokenize(self, source):
        self.source = source

        self.start()


class FindOccurenceThread(QtCore.QThread):

    marckOccurrence = QtCore.pyqtSignal(list)

    def run(self):
        word = re.escape(self.word)
        if self.wholeWord:
            word = "\\b{0}\\b".format(word)
        flags = re.UNICODE | re.LOCALE
        search = re.compile(word, flags)

        lineno = 0
        foundList = []
        for lineText in self.source.splitlines():
            for i in search.finditer(lineText):
                start = i.start()
                end = i.end()
                foundList.append([lineno, start, end])
            lineno += 1
        self.marckOccurrence.emit(foundList)

    def find(self, word, wholeWord, source):
        self.source = source
        self.word = word
        self.wholeWord = wholeWord

        self.start()


class DocThread(QtCore.QThread):

    docAvailable = QtCore.pyqtSignal(str, int)

    def run(self):
        doc = self.refactor.getDoc(self.hoverOffset)
        self.docAvailable.emit(doc, self.hoverOffset)

    def getDoc(self, refactor, hoverOffset):
        self.refactor = refactor
        self.hoverOffset = hoverOffset

        self.start()


class AutoCompletionThread(QtCore.QThread):
    # Most portions of this code taken from spyder ide

    #*****************************************************************************
    #
    #  The functions in this class were taken from the file ipy_completers,
    #  which belongs to the IPython project. They were added here because a)
    #  IPython is not a runtime dependency of Spyder, and b) we want to perfom
    #  module completion not only on an ipython shell, but also on a regular
    #  python interpreter and a source code editor.
    #  Besides, we needed to modify moduleCompletion to make it work as a regular
    #  python function, and not as a mix of python and readline completion, which
    #  is how we think it works on IPython.
    #
    #  Distributed under the terms of the BSD License.
    #
    #*************************************************************************

    """
    Returns a list containing the completion possibilities for an import line.
    The line looks like this :
    'import xml.d'
    'from xml.dom import'
    """

    completions = QtCore.pyqtSignal(tuple, list)

    def run(self):
        result = self.moduleCompletion()
        if result is None:
            return
        self.completions.emit(self.completionCallPos, result)

    def moduleCompletion(self):
        self.completionType = 3
        wordList = self.lineText.split(' ')

        if len(wordList) == 3 and wordList[0] == 'from':
            if wordList[2].startswith('i') or wordList[2] == '':
                return ['import ']
            else:
                return []

        if len(wordList) == 1 and wordList[0] == 'from':
            return []

        if wordList[0] == 'import':
            if len(wordList) == 2 and wordList[1] == '':
                return self.getRootModules()

            if ',' == wordList[-1][-1]:
                return [' ']

            module = wordList[-1].split('.')

            return self.dotCompletion(module)

        if len(wordList) < 3 and (wordList[0] == 'from'):
            if len(wordList) == 1:
                return self.getRootModules()

            module = wordList[1].split('.')
            return self.dotCompletion(module)

        if len(wordList) >= 3 and wordList[0] == 'from':
            module = wordList[1]
            completionList = self.tryImport(module)
            if wordList[2] == 'import' and wordList[3] != '':
                if '(' in wordList[-1]:
                    wordList = wordList[:-2] + wordList[-1].split('(')
                if ',' in wordList[-1]:
                    wordList = wordList[:-2] + wordList[-1].split(',')
                return list(set(filter(lambda x: x.startswith(wordList[-1]), completionList)))
            else:
                return completionList

        if self.column != 0:
            if len(self.lineText.strip()) >= 2:
                completions = self.refactor.getCompletions()
                self.completionType = 2
                return completions

    def moduleList(self, path):
        """
        Return the list containing the names of the modules available in the given
        folder.
        """

        if os.path.isdir(path):
            folderList = os.listdir(path)
        elif path.endswith('.egg'):
            try:
                folderList = [f for f in zipimporter(path)._files]
            except:
                folderList = []
        else:
            folderList = []
        folderList_ = []
        for p in folderList:
            if os.path.exists(os.path.join(path, p, '__init__.py')) \
                or p[-3:] in ('.py', '.so') \
                    or p[-4:] in ('.pyc', '.pyo', '.pyd'):
                if os.path.isdir(os.path.join(path, p)):
                    folderList_.append(p + os.path.sep)
                else:
                    folderList_.append(os.path.splitext(p)[0])

        return folderList_

    def getRootModules(self):
        """
        Returns a list containing the names of all the modules available in the
        folders of the pythonpath.
        """
        modules = []
        modules += self.moduleList(self.refactor.root)

        modules += sys.builtin_module_names

        modules = list(set(modules))
        if '__init__' in modules:
            modules.remove('__init__')
        modules = list(set(modules))

        return sorted(modules)

    def tryImport(self, module, only_modules=False):
        try:
            modulesDir = os.path.join(
                self.refactor.root, module.replace('.', '//'))
            m = os.listdir(modulesDir)
            completionList = []
            for item in m:
                path = os.path.join(modulesDir, item)
                if os.path.isfile(path):
                    completionList.append(os.path.splitext(item)[0])
                else:
                    if '__init__.py' in os.listdir(path):
                        completionList.append(item + os.path.sep)
            if '__init__' in completionList:
                completionList.remove('__init__')
        except:
            return []

        return completionList

    def dotCompletion(self, mod):
        if len(mod) < 2:
            return sorted(list(set(filter(lambda x: x.startswith(mod[0]), self.getRootModules()))))

        completionList = self.tryImport('.'.join(mod[:-1]), True)
        completionList = list(set(filter(lambda x: x.startswith(mod[-1]),
                                         completionList)))

        return sorted(completionList)

    def complete(self, completionCallPos, refactor, lineText, col):
        self.completionCallPos = completionCallPos
        self.refactor = refactor
        self.lineText = lineText
        self.column = col

        self.start()


class CodeEditor(BaseScintilla):

    def __init__(self, useData, refactor, colorScheme,
                 DATA, editorTabWidget, parent=None):
        BaseScintilla.__init__(self, parent)

        self.useData = useData
        self.refactor = refactor
        self.DATA = DATA
        self.colorScheme = colorScheme
        self.editorTabWidget = editorTabWidget

        self.setMouseTracking(True)

        self.autoCompletionThread = AutoCompletionThread()
        self.autoCompletionThread.completions.connect(self.showCompletion)

        self.findOccurenceThread = FindOccurenceThread()
        self.findOccurenceThread.marckOccurrence.connect(self.markOccurence)

        self.docThread = DocThread()
        self.docThread.docAvailable.connect(
            self.showDoc)

        self.docThreadTimer = QtCore.QTimer()
        self.docThreadTimer.setSingleShot(True)
        self.docThreadTimer.setInterval(500)
        self.docThreadTimer.timeout.connect(self.getDoc)

        self.tokenizeThread = TokenizeThread()
        self.tokenizeThread.finished.connect(
            self.displayTokenLines)

        self.tokenizeTimer = QtCore.QTimer()
        self.tokenizeTimer.setSingleShot(True)
        self.tokenizeTimer.setInterval(1000)
        self.tokenizeTimer.timeout.connect(self.getOperationTokens)

        self.occurrencesTimer = QtCore.QTimer()
        self.occurrencesTimer.setSingleShot(True)
        self.occurrencesTimer.setInterval(1000)
        self.occurrencesTimer.timeout.connect(self.findOccurrences)

        self.completionThreadTimer = QtCore.QTimer()
        self.completionThreadTimer.setSingleShot(True)
        self.completionThreadTimer.setInterval(1000)
        self.completionThreadTimer.timeout.connect(self.startCompletion)

        self.cursorPositionChanged.connect(self.occurrencesTimer.start)

        mainLayout = QtGui.QVBoxLayout()
        mainLayout.setMargin(0)
        self.setLayout(mainLayout)

        mainLayout.addStretch(1)

        #

        hbox = QtGui.QHBoxLayout()
        hbox.addStretch(1)
        hbox.setContentsMargins(0, 0, 20, 0)
        mainLayout.addLayout(hbox)

        self.zoomWidget = ZoomWidget(self.useData, self)
        hbox.addWidget(self.zoomWidget)

        #

        hbox = QtGui.QHBoxLayout()
        hbox.addStretch(1)
        hbox.setContentsMargins(5, 0, 10, 20)
        mainLayout.addLayout(hbox)

        self.notify = Notification()
        hbox.addWidget(self.notify)
        self.notify.hide()

        #

        self.createActions()
        self.setStyleSheet(StyleSheet.editorStyle)

        self.setAutoCompletion()

        " Initialises indicators "
        self.syntaxErrorIndicator = self.indicatorDefine(
            QsciScintilla.INDIC_SQUIGGLE, 8)
        self.setIndicatorForegroundColor(QtGui.QColor(
            "#FF0000"), self.syntaxErrorIndicator)
        self.setIndicatorDrawUnder(True, self.syntaxErrorIndicator)

        self.matchIndicator = self.indicatorDefine(QsciScintilla.INDIC_BOX, 9)
        self.setIndicatorForegroundColor(
            QtGui.QColor("#FFCC00"), self.matchIndicator)
        self.setIndicatorDrawUnder(True, self.matchIndicator)

        self.searchIndicator = self.indicatorDefine(
            QsciScintilla.INDIC_ROUNDBOX, 10)
        self.setIndicatorForegroundColor(
            QtGui.QColor("#FFDB4A"), self.searchIndicator)
        self.setIndicatorDrawUnder(True, self.searchIndicator)

        self.userListActivated.connect(self.insertCompletion)

        self.copyAvailableTimer = QtCore.QTimer()
        self.copyAvailableTimer.setSingleShot(True)
        self.copyAvailableTimer.setInterval(0)
        self.copyAvailableTimer.timeout.connect(self.copyActModifier)

        self.copyAvailable.connect(self.copyAvailableTimer.start)

        self.textChangedTimer = QtCore.QTimer()
        self.textChangedTimer.setSingleShot(True)
        self.textChangedTimer.setInterval(0)
        self.textChangedTimer.timeout.connect(self.undoActModifier)
        self.textChangedTimer.timeout.connect(self.redoActModifier)

        self.textChanged.connect(self.textChangedTimer.start)
        self.textChanged.connect(self.tokenizeTimer.start)
        self.textChanged.connect(self.completionThreadTimer.start)

        self.linesChanged.connect(self.updateLineCount)
        self.marginClicked.connect(self.toggleBookmark)

        # define the font to use
        font = QtGui.QFont("Courier New")
        font.setFixedPitch(True)
        font.setPointSize(10)
        # the font metrics here will help
        # building the margin width later
        self.fontMetrics = QtGui.QFontMetrics(font)

        if self.DATA["codingFormat"] is None:
            self.setUtf8(True)
        self.setAutoIndent(True)
        self.setIndentationsUseTabs(False)
        self.setBackspaceUnindents(True)
        self.setIndentationWidth(4)
        self.setTabWidth(4)
#        self.setAnnotationDisplay(QsciScintilla.AnnotationStandard)

        # Line numbers
        # conventionnaly, margin 0 is for line numbers
        self.setMarginWidth(0, self.fontMetrics.width("0000") + 5)

        # Clickable margin 1 for showing markers
        self.setMarginSensitivity(1, True)

        self.setAutoCompletionReplaceWord(True)
        # minimum number of letters to be typed before list is displayed
        self.setAutoCompletionThreshold(2)

        if self.useData.SETTINGS["EnableFolding"] == "True":
            self.setFolding(QsciScintilla.BoxedTreeFoldStyle, 2)

        # Braces matching
        # TODO: Causes flicker when selecting text. I suspect it has
        # do with my graphics card since it wasnt always this way
        if self.useData.SETTINGS["MatchBraces"] == "True":
            self.setBraceMatching(QsciScintilla.SloppyBraceMatch)

        if self.useData.SETTINGS["ShowEdgeLine"] == 'True':
            if self.useData.SETTINGS["EdgeMode"] == 'Line':
                self.setEdgeMode(QsciScintilla.EdgeLine)
            elif self.useData.SETTINGS["EdgeMode"] == 'Background':
                self.setEdgeMode(QsciScintilla.EdgeBackground)

        if self.useData.SETTINGS["ShowCaretLine"] == 'True':
            self.setCaretLineVisible(True)

        self.showWhiteSpaces()
        # set annotation display
        # the annotation font can be changed by changing the default lexer font
        self.setAnnotationDisplay(QsciScintilla.AnnotationBoxed)

        # Edge Mode shows a vetical bar at specific number of chars
        if self.useData.SETTINGS["ShowEdgeLine"] == 'True':
            if self.useData.SETTINGS['EdgeMode'] == "Line":
                self.setEdgeMode(QsciScintilla.EdgeLine)
            else:
                self.setEdgeMode(QsciScintilla.EdgeBackground)
        self.setEdgeColumn(int(self.useData.SETTINGS["EdgeColumn"]))

        # define markers
        # the background markers will not show until the editor has focus
        self.breakpointMarker = self.markerDefine(QsciScintilla.Background)
        self.setMarkerForegroundColor(QtGui.QColor("#000000"),
                                      self.breakpointMarker)
        self.setMarkerBackgroundColor(QtGui.QColor("#ffe1e1"),
                                      self.breakpointMarker)

        self.markerDefine(QtGui.QPixmap(
            os.path.join("Resources", "images", "ui-button-navigation")), 8)
        self.setMarkerBackgroundColor(QtGui.QColor("#ee1111"), 8)

        self.markerDefine(
            QtGui.QPixmap(os.path.join("Resources", "images", "err_mark")), 9)
        self.setMarkerBackgroundColor(QtGui.QColor("#ee1111"), 9)

        self.markerDefine(
            QtGui.QPixmap(os.path.join("Resources", "images", "brk_point")), 10)
        self.setMarkerBackgroundColor(QtGui.QColor("#ee1111"), 10)

        self.markerDefine(QsciScintilla.VerticalLine, 11)
        self.setMarkerBackgroundColor(QtGui.QColor("#EEEE11"), 11)
        self.setMarkerForegroundColor(QtGui.QColor("#EEEE11"), 11)
        self.setMarginWidth(3, self.fontMetrics.width("0"))

        self.showLineNumbers()

        if self.useData.SETTINGS["ShowCaretLine"] == 'True':
            self.setCaretLineVisible(True)

        self.lexer = self.colorScheme.styleEditor(self)

        self.install_shortcuts()

    def getOperationTokens(self):
        self.tokenizeThread.tokenize(self.text())

    def displayTokenLines(self):
        return
        print(self.tokenizeThread.tokenList)

    def showDoc(self, doc, pos):
        if self.isListActive():
            return
        if doc is not None:
            QtGui.QToolTip.showText(self.lastHoverPos, doc, self)

    def getDoc(self):
        self.docThread.getDoc(self.refactor, self.hoverOffset)

    def findOccurrences(self):
        self.clearAllIndicators(self.matchIndicator)
        if self.useData.SETTINGS['MarkSearchOccurrence'] == 'True':
            wholeWord = True
            if self.hasSelectedText():
                lineFrom_, indexFrom_, lineTo_, indexTo_ = self.getSelection()
                if lineFrom_ != lineTo_:
                    return
                word = self.selectedText().strip()
                if word == '':
                    return
                wholeWord = False
            else:
                word = self.get_current_word()
                if not word:
                    self.clearMatchIndicators()
                    return
            self.findOccurenceThread.find(word, wholeWord, self.text())

    def markOccurence(self, foundList):
        self.clearAllIndicators(self.matchIndicator)
        if len(foundList) == 1:
            return
        for i in foundList:
            self.fillIndicatorRange(
                i[0], i[1], i[0], i[2], self.matchIndicator)

    def mouseMoveEvent(self, event):
        if self.useData.SETTINGS["DocOnHover"] == "True":
            self.lastHoverPos = event.globalPos()
            self.hoverOffset = self.positionFromPoint(event.pos())

            QtGui.QToolTip.hideText()
            self.docThreadTimer.start()
        super(BaseScintilla, self).mouseMoveEvent(event)

    def createActions(self):
        self.cutAct = QtGui.QAction(
            "Cut", self,
            statusTip="Cut selected text", triggered=self.cut)

        self.copyAct = QtGui.QAction(
            "Copy", self,
            statusTip="Copy selected text", triggered=self.copy)

        self.pasteAct = QtGui.QAction(
            "Paste", self,
            statusTip="Paste text from clipboard",
            triggered=self.paste)

        self.selectToMatchingBraceAct = \
            QtGui.QAction(
                "Select to Matching Brace", self,
                statusTip="Select to Matching Brace",
                          triggered=self.selectToMatchingBrace)

        self.snippetsAct = \
            QtGui.QAction(
                QtGui.QIcon(os.path.join("Resources", "images", "edit2")),
                "Insert Snippet...", self,
                statusTip="Insert Snippet...",
                          triggered=self.showSnippets)

        self.toggleBookmarkAct = \
            QtGui.QAction(
                "Toggle Bookmark", self,
                statusTip="Toggle Bookmark",
                triggered=self._toggleBookmark)

        self.toggleBreakpointAct = \
            QtGui.QAction(
                "Toggle Line Breakpoint", self,
                statusTip="Toggle Line Breakpoint",
                triggered=self.toggleLineBreakpoint)

        self.takeSnapshotAct = \
            QtGui.QAction("Take Snapshot", self,
                          statusTip="Take Snapshot",
                          triggered=self.takeSnapshot)

        self.zoomAct = QtGui.QAction(
            QtGui.QIcon(os.path.join("Resources", "images", "zoom")),
            "Zoom", self,
            statusTip="Zoom", triggered=self.showZoomWidget)

        self.indentationGuideAct = \
            QtGui.QAction(
                QtGui.QIcon(os.path.join("Resources", "images", "guide")),
                "Indentation Guide", self,
                statusTip="Indentation Guide",
                          triggered=self.showIndentationGuide)

        self.contextMenu = QtGui.QMenu()
        self.contextMenu.addAction(self.snippetsAct)
        self.contextMenu.addSeparator()
        self.contextMenu.addAction(self.cutAct)
        self.contextMenu.addAction(self.copyAct)
        self.contextMenu.addAction(self.pasteAct)
        self.contextMenu.addAction(self.selectToMatchingBraceAct)
        self.contextMenu.addAction(self.toggleBookmarkAct)
        self.contextMenu.addAction(self.toggleBreakpointAct)

        self.contextMenu.addSeparator()
        self.contextMenu.addAction(self.refactor.findDefAct)
        self.contextMenu.addAction(self.refactor.findOccurrencesAct)

        self.contextMenu.addMenu(self.refactor.refactorMenu)

        self.viewMenu = self.contextMenu.addMenu("View")
        self.viewMenu.addAction(self.editorTabWidget.vSplitEditorAct)
        self.viewMenu.addAction(self.editorTabWidget.hSplitEditorAct)
        self.viewMenu.addAction(self.editorTabWidget.noSplitEditorAct)
        self.viewMenu.addSeparator()
        self.viewMenu.addAction(self.indentationGuideAct)
        self.viewMenu.addSeparator()
        self.viewMenu.addAction(self.zoomAct)
        self.contextMenu.addSeparator()
        self.contextMenu.addAction(self.takeSnapshotAct)

    def contextMenuEvent(self, event):
        filePath = self.DATA['filePath']
        isProjectFile = self.editorTabWidget.isProjectFile(filePath)
        self.refactor.refactorMenu.setEnabled(isProjectFile)
        self.refactor.findOccurrencesAct.setEnabled(isProjectFile)

        hasSelection = self.hasSelectedText()
        self.copyAct.setEnabled(hasSelection)
        self.cutAct.setEnabled(hasSelection)

        self.contextMenu.exec_(event.globalPos())

    def undoActModifier(self):
        state = self.isUndoAvailable()
        self.editorTabWidget.undoAct.setEnabled(state)

    def redoActModifier(self):
        state = self.isRedoAvailable()
        self.editorTabWidget.redoAct.setEnabled(state)

    def copyActModifier(self):
        state = self.hasSelectedText()
        self.editorTabWidget.copyAct.setEnabled(state)
        self.editorTabWidget.cutAct.setEnabled(state)

    def updateLineCount(self):
        lines = self.lines()
        self.editorTabWidget.updateLinesCount.emit(lines)

    def startCompletion(self):
        if self.useData.SETTINGS["EnableAutoCompletion"] == "True":
            if self.useData.SETTINGS["AutoCompletion"] == "Api":
                lineno, col = self.getCursorPosition()
                self.completionCallPos = self.getCursorPosition()
                lineText = self.text(lineno)[:col]

                self.autoCompletionThread.complete(
                    self.completionCallPos, self.refactor, lineText, col)

    def showCompletion(self, completionCallPos, result):
        if len(result) > 0:
            if self.hasFocus():
                currentPos = self.getCursorPosition()
                if currentPos == completionCallPos:
                    self.showUserList(
                        self.autoCompletionThread.completionType, result)
                else:
                    self.startCompletion()
        else:
            self.cancelList()

    def insertCompletion(self, id, text):
        word = self.get_current_word()
        if not word:
            pass
        else:
            self.deleteWordToLeft()
        self.removeSelectedText()
        if id == 1:
            file = open(os.path.join(self.useData.appPathDict[
                        "snippetsdir"], text), 'r')
            cmpl = file.read()
            file.close()
            self.insert(cmpl)
        elif id == 2:
            # TODO: Insert must check for brackets after inserting functions.
            x = text.split()
            cmpl = x[0]
            type = x[2].strip(")")
            self.insert(cmpl)
        elif id == 3:
            cmpl = text.rstrip(os.path.sep)
            self.insert(cmpl)
        self.moveCursorWordRight()

    def takeSnapshot(self):
        reply = QtGui.QMessageBox.warning(self, "Snapshot",
                                          "Take a snapshot of the current module state?",
                                          QtGui.QMessageBox.Yes | QtGui.QMessageBox.No)
        if reply == QtGui.QMessageBox.Yes:
            subStack = self.editorTabWidget.currentWidget()
            subStack.widget(1).setText(self.text())
        else:
            return

    def toggleLineBreakpoint(self):
        line, index = self.getCursorPosition()
        if self.markersAtLine(line) != 0:
            self.markerDelete(line, self.breakpointMarker)
        else:
            self.markerAdd(line, self.breakpointMarker)
        self.ensureLineVisible(line - 1)

    def updateLexer(self, lexer):
        self.lexer = lexer
        self.setLexer(lexer)

    def _toggleBookmark(self):
        nmargin = 0
        nline = self.getCursorPosition()[0]

        self.toggleBookmark(nmargin, nline)

    def toggleBookmark(self, nmargin, nline, modifiers=None):
        if self.markersAtLine(nline) == 0:
            handle = self.markerAdd(nline, 8)
            self.DATA["bookmarkList"].append(handle)
        else:
            for handle in self.DATA["bookmarkList"]:
                if self.markerLine(handle) == nline:
                    self.DATA["bookmarkList"].remove(handle)
                    self.markerDeleteHandle(handle)

        markersExist = self.bookmarksExist()
        self.editorTabWidget.enableBookmarkButtons(markersExist)

    def bookmarksExist(self):
        markersExist = (len(self.DATA["bookmarkList"]) > 0)
        return markersExist

    def getBookmarks(self):
        bookmarkLines = []
        for handle in self.DATA["bookmarkList"]:
            line = self.markerLine(handle)
            bookmarkLines.append(line)

        return bookmarkLines

    def showSnippets(self):
        try:
            snippetList = os.listdir(
                self.useData.appPathDict["snippetsdir"])
        except:
            self.notify.showMessage("Could not fetch snippets.")
            return
        if len(snippetList) > 0:
            self.showUserList(1, snippetList)
        else:
            self.notify.showMessage("No snippets available.")

    def clearErrorMarkerAndIndicator(self):
        self.clearAllIndicators(self.syntaxErrorIndicator)
        self.clearAnnotations()
        self.markerDeleteAll(9)

    def setAutoCompletion(self):
        if self.useData.SETTINGS["EnableAutoCompletion"] == "False":
            self.setAutoCompletionSource(QsciScintilla.AcsNone)
            return
        if self.useData.SETTINGS["AutoCompletion"] == "Api":
            self.setAutoCompletionSource(QsciScintilla.AcsNone)
        elif self.useData.SETTINGS["AutoCompletion"] == "Document":
            self.setAutoCompletionSource(QsciScintilla.AcsDocument)

    def getOffset(self):
        offset = self.currentPosition()
        return offset

    def showLine(self, lineNum, highlight=True):
        if highlight:
            self.setSelection(
                lineNum, 0, lineNum, self.lineLength(lineNum) - 1)
        self.ensureLineVisible(lineNum)

    def showIndentationGuide(self):
        if self.indentationGuides():
            self.setIndentationGuides(False)
        else:
            self.setIndentationGuides(True)

    def showZoomWidget(self):
        self.zoomWidget.show()

    def showWhiteSpaces(self):
        if self.useData.SETTINGS["ShowWhiteSpaces"] == 'True':
            self.setWhitespaceVisibility(QsciScintilla.WsVisible)
        else:
            self.setWhitespaceVisibility(QsciScintilla.WsInvisible)

    def findNextBookmark(self):
        cursorLine = self.getCursorPosition()[0]
        lineNum = self.markerFindNext(cursorLine + 1, 256)
        if lineNum == -1:
            lineNum = self.markerFindNext(0, 256)
            if lineNum == -1:
                return
        self.showLine(lineNum)

    def findPreviousBookmark(self):
        cursorLine = self.getCursorPosition()[0]
        lineNum = self.markerFindPrevious(cursorLine - 1, 256)
        if lineNum == -1:
            lineNum = self.markerFindPrevious(self.lines(), 256)
            if lineNum == -1:
                return
        self.showLine(lineNum)

    def removeBookmarks(self):
        if len(self.DATA["bookmarkList"]) > 0:
            self.DATA["bookmarkList"] = []
            self.markerDeleteAll(8)

    def addCommentPrefix(self, line):
        if self.text(line).strip().startswith('#'):
            pass
        else:
            self.insertAt('#', line, 0)

    def removeCommentPrefix(self, line):
        if self.text(line).strip().startswith('#'):
            lineText = self.text(line)
            commentIndex = lineText.find('#')
            self.setSelection(line, commentIndex, line, commentIndex + 1)
            self.replaceSelectedText('')
        else:
            pass

    def comment(self):
        if self.hasSelectedText():
            lineFrom, indexFrom, lineTo, indexTo = self.getSelection()
            if lineFrom == lineTo:
                self.addCommentPrefix(lineFrom)
            else:
                self.beginUndoAction()
                for i in range(lineFrom, lineTo + 1):
                    self.addCommentPrefix(i)
                self.endUndoAction()
            self.setSelection(lineFrom, indexFrom, lineTo, indexTo)
        else:
            line, index = self.getCursorPosition()
            self.addCommentPrefix(line)

    def unComment(self):
        if self.hasSelectedText():
            lineFrom, indexFrom, lineTo, indexTo = self.getSelection()
            if lineFrom == lineTo:
                self.removeCommentPrefix(lineFrom)
            else:
                self.beginUndoAction()
                for i in range(lineFrom, lineTo + 1):
                    self.removeCommentPrefix(i)
                self.endUndoAction()
            self.setSelection(lineFrom, indexFrom, lineTo, indexTo)
        else:
            line, index = self.getCursorPosition()
            self.removeCommentPrefix(line)

    def replaceTabsWithSpaces(self):
        text = self.text()
        text = text.replace('\t', ' ' * 4)
        self.selectAll()
        self.replaceSelectedText(text)

    def removeTrailingWhitespaces(self):
        self.beginUndoAction()
        for i in range(self.lines()):
            text = self.text(i)
            white_len = len(text) - len(text.rstrip())
            if white_len > 1:
                self.setSelection(i, self.lineLength(i) - white_len, i,
                                  self.lineLength(i) - 1)
                self.removeSelectedText()
        self.endUndoAction()

    def notify(self, mess):
        self.infoBar.showMessage(mess)

    def install_shortcuts(self):
        self.updateShortcuts(self.useData)

        shortcuts = self.useData.CUSTOM_DEFAULT_SHORTCUTS

        self.cutAct.setShortcut(shortcuts["Editor"]["Cut-Selection"][0])
        self.copyAct.setShortcut(shortcuts["Editor"]["Copy-Selection"][0])
        self.pasteAct.setShortcut(shortcuts["Editor"]["Paste"][0])

        self.shortSnippets = QtGui.QShortcut(
            shortcuts["Editor"]["Snippets"][0], self)
        self.shortSnippets.activated.connect(self.showSnippets)

        self.shortIndentationGuide = QtGui.QShortcut(
            shortcuts["Editor"]["Toggle-Indentation-Guide"][0], self)
        self.shortIndentationGuide.activated.connect(self.showIndentationGuide)

        self.shortShowCompletion = QtGui.QShortcut(
            shortcuts["Editor"]["Show-Completion"][0], self)
        self.shortShowCompletion.activated.connect(self.startCompletion)

        self.shortToggleBreakpoint = QtGui.QShortcut(
            shortcuts["Editor"]["Toggle-Breakpoint"][0], self)
        self.shortToggleBreakpoint.activated.connect(self.toggleLineBreakpoint)

        self.shortNextBookmark = QtGui.QShortcut(
            shortcuts["Editor"]["Next-Bookmark"][0], self)
        self.shortNextBookmark.activated.connect(self.findNextBookmark)

        self.shortPreviousBookmark = QtGui.QShortcut(
            shortcuts["Editor"]["Previous-Bookmark"][0], self)
        self.shortPreviousBookmark.activated.connect(self.findPreviousBookmark)

        self.shortComment = QtGui.QShortcut(
            shortcuts["Editor"]["Comment"][0], self)
        self.shortComment.activated.connect(self.comment)

        self.shortUncomment = QtGui.QShortcut(
            shortcuts["Editor"]["Uncomment"][0], self)
        self.shortUncomment.activated.connect(self.unComment)

        self.shortZoomIn = QtGui.QShortcut(
            shortcuts["Editor"]["Zoom-In"][0], self)
        self.shortZoomIn.activated.connect(self.zoomWidget.zoomIn)

        self.shortZoomOut = QtGui.QShortcut(
            shortcuts["Editor"]["Zoom-Out"][0], self)
        self.shortZoomOut.activated.connect(self.zoomWidget.zoomOut)
