import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "ui"
import "state"
import "ipc"
import "audio"
import "core/Progression.js" as Progression
import "core/Document.js" as Document
import "ui/Plain.js" as Plain

// Opushy: a pushup progression tracker for the Omarchy bar.
//
//   core/Progression.js  the rules, as pure functions
//   core/Document.js     the state document schema
//   state/               the only file I/O, and the QML side of it
//   ui/                  one component per screen, plus Plain.js and Status.js
//   audio/               the end-of-rest cue
//   ipc/                 the opushy.debug surface
//
// This file holds the state, the session flow and the layout.
Panel {
    id: root
    moduleName: "opushy"
    ipcTarget: "opushy"
    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight

    // ---- the document ----
    // A binding does not see `history.push(...)`, so the array is replaced
    // rather than mutated.
    property int maxPushups: 0
    property int storedReps: 0
    property string lastTrainingDate: ""
    property int trainingDays: 0
    property var history: []

    // ---- the session ----
    property int sessionReps: 0
    property int currentRound: 0
    property int remaining: 0
    property bool counting: false
    property bool paused: false
    property bool confirming: false
    // The panel is one of two screens once a max is recorded.
    property bool showingSession: false

    // ---- after the last round ----
    // The session is written before either of these is set, so a reload in the
    // middle of the screen loses nothing.
    property bool celebrating: false
    property bool newRecord: false
    property int previousRecord: 0

    // Closing the panel while the congratulations are up ends them.
    //
    // The confetti is a fullscreen surface of its own (ui/Celebration.qml), not
    // part of the panel, so it does not disappear with the dropdown: it would
    // keep falling over a desktop whose panel was gone. And the next open would
    // land back on a stale congratulations screen instead of the usual one. Both
    // are the same fix, because the surface and the shower are bound to
    // `celebrating`.
    //
    // Watched rather than put in close(), because `opened` is also cleared by the
    // bar when another widget takes over the popup, and that path never runs
    // anything in this file.
    onOpenedChanged: {
        if (!root.opened && root.celebrating) root.finishCelebration()
    }

    // ---- first-run draft ----
    property string maxDraft: ""
    readonly property int maxDraftValue: Math.floor(Number(root.maxDraft))

    // ---- backup and restore ----
    // The restore question, and the path it is about, once the user has picked
    // a file and said yes. Nothing is written until they confirm.
    property bool askingRestore: false
    property string chosenRestorePath: ""
    // What the last backup or restore reported, and when it was, so the panel
    // can say so instead of leaving the button as the only sign it happened.
    property string fileNotice: ""

    // ---- helpers ----
    // `-I -S` keeps the run out of the user environment and site-packages, `-B`
    // stops python writing __pycache__ into the folder the shell watches.
    readonly property string python: "/usr/bin/python3"
    readonly property string helperPath: decodeURIComponent(
        Qt.resolvedUrl("state/opushy-state.py").toString().replace(/^file:\/\//, ""))
    // Watcher only, and the helper resolves the real path, so this is a change
    // signal and never a read. Renamed from tracker.json in 1.1: the helper
    // moves an existing file onto this name once, on the first load, so an
    // upgraded install keeps its history.
    readonly property string statePath: Quickshell.env("HOME")
        + "/.local/state/opushy/opushy_activity.json"
    // The folder that file lives in, cut off the same string so the menu's
    // Location row and the state file cannot drift apart.
    readonly property string stateDir: statePath.substring(0, statePath.lastIndexOf("/"))
    // Pre-1.0 location, imported once on the first load and then ignored. The
    // name here is deliberately the old one: that is the file being looked for.
    readonly property string legacyStatePath: decodeURIComponent(
        Qt.resolvedUrl("tracker.json").toString().replace(/^file:\/\//, ""))

    // ---- time ----
    // The preview decays with the calendar, so the day is re-read hourly.
    // A double, not an int: Date.now() is epoch milliseconds and a QML int is
    // 32-bit, so an int property would wrap it to a date in 1970.
    property double nowMs: Date.now()
    readonly property int daysSinceLast: Progression.daysSince(root.lastTrainingDate, root.nowMs)
    readonly property bool everTrained: root.lastTrainingDate !== ""

    readonly property int statusValue: root.everTrained
        ? Progression.statusForDays(root.daysSinceLast) : Progression.ON_TRACK
    readonly property int previewReps: Progression.nextReps(root.maxPushups, root.storedReps,
                                                            root.lastTrainingDate, root.nowMs)
    // The session's frozen number while a session runs, the live preview otherwise.
    readonly property int reps: root.currentRound > 0 ? root.sessionReps : root.previewReps

    // ---- history paging ----
    readonly property int pageCount: Math.max(1, Math.ceil(root.history.length / Progression.PAGE_SIZE))
    property int historyPage: 0
    // Clamped where it is read, so a shrinking history cannot point the strip
    // past the end.
    readonly property int page: Math.max(0, Math.min(root.historyPage, root.pageCount - 1))

    // ---- the document ----
    function applyDocument(document) {
        root.maxPushups = document.maxPushups
        root.storedReps = document.reps
        root.lastTrainingDate = document.lastTrainingDate
        root.trainingDays = document.trainingDays
        root.history = document.history
        root.historyPage = root.pageCount - 1     // land on the newest sessions
    }

    function persist() {
        store.save(Document.serialize({
            maxPushups: root.maxPushups,
            reps: root.storedReps,
            lastTrainingDate: root.lastTrainingDate,
            trainingDays: root.trainingDays,
            history: root.history
        }, Progression))
    }

    // The stored max follows the reps up, so a chain that outgrows its own
    // record raises the record. Only a completed session is written.
    function applyTarget(target, completed) {
        if (Progression.isRecord(target, root.maxPushups)) root.maxPushups = target
        if (!completed) return target
        var stamp = new Date(root.nowMs).toISOString()
        root.history = root.history.concat([{ time: stamp, reps: target }])
            .slice(-Document.HISTORY_MAX)
        root.lastTrainingDate = stamp
        root.trainingDays = root.trainingDays + 1
        root.storedReps = target
        root.persist()
        return target
    }

    function saveMax(value) {
        var max = Math.floor(Number(value))
        if (!isFinite(max) || max < 1) return
        root.maxPushups = max
        // No session yet, so the date stays empty and the next preview is +1.
        root.storedReps = Progression.baseReps(max)
        root.maxDraft = ""
        root.persist()
    }

    // ---- the session flow ----
    function startSession() {
        if (root.maxPushups <= 0) return
        // The verdict is read here, against the record as it stands before
        // applyTarget raises it. Read again at the end it would always say no,
        // because the record already moved.
        var target = root.previewReps
        root.newRecord = Progression.isRecord(target, root.maxPushups)
        root.previousRecord = root.maxPushups
        root.sessionReps = root.applyTarget(target, false)
        root.currentRound = 1
        root.counting = false
        root.paused = false
        root.remaining = 0
        root.showingSession = true
        root.confirming = false
        root.celebrating = false
    }

    function nextRound() {
        if (root.currentRound === 0) { startSession(); return }
        if (root.counting) return
        // There is no rest after the last round: finishing it ends the session.
        if (root.currentRound >= Progression.ROUNDS) { completeSession(); return }
        beginRest()
    }

    function beginRest() {
        root.remaining = Progression.REST_SECONDS
        root.counting = true
        root.paused = false
        countdown.restart()
    }

    function togglePause() {
        if (!root.counting) return
        if (root.paused) {
            countdown.start()
            root.paused = false
        } else {
            countdown.stop()
            root.paused = true
        }
    }

    function skipRest() {
        countdown.stop()
        root.counting = false
        root.paused = false
        root.remaining = 0
        root.advanceRound()
    }

    // A rest only ever runs between rounds, so it can only ever move forward one.
    // Shared by the countdown running out and by Skip.
    function advanceRound() {
        root.currentRound = root.currentRound + 1
    }

    function completeSession() {
        root.applyTarget(root.sessionReps, true)
        root.currentRound = 0
        root.showingSession = false
        root.celebrating = true
    }

    // The one way the congratulations end. Nothing is written here, because the
    // session was saved before the screen ever appeared.
    function finishCelebration() {
        root.celebrating = false
    }

    function requestStop() {
        if (root.currentRound === 0) return
        root.showingSession = true
        root.confirming = true
    }

    function stopSession() {
        countdown.stop()
        root.confirming = false
        root.counting = false
        root.paused = false
        root.remaining = 0
        root.currentRound = 0
        root.showingSession = false
    }

    function pagePrevious() { root.historyPage = root.page - 1 }
    function pageNext() { root.historyPage = root.page + 1 }

    // ---- backup and restore ----
    // Both are refused while a session runs: the document a backup would copy is
    // mid-session, and a restore would replace it under the running rounds.
    readonly property bool canUseFiles: root.currentRound === 0 && !store.working

    function requestRestore(path) {
        if (!root.canUseFiles) return
        activityMenu.opened = false
        root.chosenRestorePath = path
        root.askingRestore = true
        // The question lives on the panel, so the panel has to be the surface
        // the user is looking at once they have picked a file.
        if (!root.opened) root.open()
    }

    function confirmRestore() {
        root.askingRestore = false
        if (root.chosenRestorePath === "") return
        // The old result goes now rather than sitting there until the timer
        // would have cleared it, so the panel cannot claim the previous restore
        // while this one is running.
        root.clearFileNotice()
        store.restoreFrom(root.chosenRestorePath)
        root.chosenRestorePath = ""
    }

    function cancelRestore() {
        root.askingRestore = false
        root.chosenRestorePath = ""
    }

    function reportFileOp(message) {
        // Flattened here because this is shown as text: the message carries a
        // file name that came out of a file chooser.
        root.fileNotice = Plain.plain(message)
        // Long enough to read, short enough that reopening the panel later is
        // not still reporting the last backup.
        fileNoticeClear.restart()
    }

    function clearFileNotice() {
        // Stopping the timer matters as much as emptying the text: a timer left
        // running would clear the *next* message early.
        fileNoticeClear.stop()
        root.fileNotice = ""
    }

    // The chosen file's name on its own, for the restore question. The whole
    // path is not shown: it is long, and it is not what identifies the file.
    readonly property string restoreFileName: chosenRestorePath === "" ? ""
        : Plain.plain(chosenRestorePath.substring(chosenRestorePath.lastIndexOf("/") + 1))

    // The snapshot the debug IPC returns.
    function state() {
        return JSON.stringify({
            maxPushups: root.maxPushups,
            storedReps: root.storedReps,
            reps: root.reps,
            previewReps: root.previewReps,
            trainingDays: root.trainingDays,
            historyLength: root.history.length,
            page: root.page,
            pageCount: root.pageCount,
            daysSinceLast: root.daysSinceLast,
            statusValue: root.statusValue,
            round: root.currentRound,
            counting: root.counting,
            paused: root.paused,
            showingSession: root.showingSession,
            celebrating: root.celebrating,
            newRecord: root.newRecord
        })
    }

    Component.onCompleted: store.load()

    Component.onDestruction: countdown.stop()

    Store {
        id: store
        python: root.python
        helperPath: root.helperPath
        statePath: root.statePath
        legacyPath: root.legacyStatePath
        onDocumentRead: function (document) { root.applyDocument(document) }
        onFileOpDone: function (verb, message) {
            root.reportFileOp(message)
            // An export was asked for from the menu, and the panel is not the
            // surface that is open, so the result goes back there. A restore
            // already opened the panel on its question, and that is where the
            // replaced history is, so the result stays on the panel.
            if (verb === "export" && root.currentRound === 0)
                activityMenu.opened = true
        }
    }

    Alert { id: alert }

    // A backup or restore result is news, not a status line: five seconds, then
    // it is gone. Restarted by reportFileOp() and stopped by clearFileNotice(),
    // so a timer can never outlive the message it was started for.
    Timer {
        id: fileNoticeClear
        interval: 5000
        repeat: false
        onTriggered: root.fileNotice = ""
    }

    Celebration {
        id: celebration
        panel: root
        namespace: "opushy-celebration"
    }

    Timer {
        id: countdown
        interval: 1000
        repeat: true
        running: false
        onTriggered: {
            root.remaining = root.remaining - 1
            if (root.remaining > 0) return
            stop()
            root.counting = false
            root.paused = false
            alert.play()
            root.advanceRound()
        }
    }

    Timer {
        interval: 3600000
        running: true
        repeat: true
        onTriggered: root.nowMs = Date.now()
    }

    // The day bubble counts days, so it has to be re-evaluated when the count
    // actually changes rather than whenever the shell happened to start. This
    // re-arms from the clock each tick, so a suspend or a clock change lands on
    // the next boundary instead of drifting a whole day. The hourly tick above
    // stays: nowMs also stamps recorded sessions, which want to be as close to
    // the wall clock as possible.
    Timer {
        id: dayRollover
        interval: Progression.msUntilNextDay(root.nowMs)
        running: true
        repeat: true
        onTriggered: {
            root.nowMs = Date.now()
            dayRollover.interval = Progression.msUntilNextDay(root.nowMs)
        }
    }

    // The bar's idle mark: the day bubble. Drawn rather than a glyph so it can
    // carry the day count, so it goes in through `iconComponent` and the button
    // swaps to `text` for the running states.
    Component {
        id: dayBubbleMark
        DayBubble {
            statusValue: root.statusValue
            daysSinceLast: root.daysSinceLast
            everTrained: root.everTrained
            // A 20px disc derives a label at the 8px floor, which is too small
            // to read at a glance in the bar, so the size is asked for here.
            labelSize: 9
            quietOnTrack: true
        }
    }

    BarIconButton {
        id: button
        anchors.fill: parent
        bar: root.bar
        // Idle: the day bubble. Running: the reps. Resting: the seconds left.
        // The label keeps its width in the two running states, or the panel
        // anchored to this button shifts sideways mid-session.
        // One size for every bar widget comes from Style.bar.iconFont, and the
        // theme cannot change it: Style.applyShellValues forwards only
        // size-horizontal, size-vertical and scale-with-font from [bar]. The slot
        // is 27px and OpticalGlyph centres its glyph without clipping, so this
        // button asks for more on its own.
        fontSize: Math.round(Style.bar.iconFont * 1.35)
        // The icon slot is a fixed box (BarIconButton's optical canvas) and its
        // 16px default is too small for "12d" inside a disc.
        opticalSize: 20
        text: Plain.plain(root.counting ? root.remaining + "s"
                                        : root.currentRound > 0 ? root.reps + "×" : "")
        iconComponent: root.counting || root.currentRound > 0 ? null : dayBubbleMark
        // Right, while a session is running: open the panel on the stop
        // question, so a stray right click cannot discard three finished rounds.
        // Right, while idle and a record exists: the backup menu. Before the
        // first record there is nothing to keep, so it opens the panel.
        onPressed: function (btn) {
            if (btn !== Qt.RightButton) {
                activityMenu.opened = false
                root.toggle()
                return
            }
            if (root.currentRound > 0) {
                activityMenu.opened = false
                if (!root.opened) root.open()
                root.requestStop()
                return
            }
            if (root.maxPushups <= 0) {
                activityMenu.opened = false
                root.toggle()
                return
            }
            activityMenu.opened = !activityMenu.opened
        }
    }

    ActivityMenu {
        id: activityMenu
        anchorItem: button
        bar: root.bar
        canUseFiles: root.canUseFiles
        stateDir: root.stateDir
        resultNotice: root.fileNotice
        onExportRequested: function (path) {
            root.clearFileNotice()
            store.exportTo(path)
        }
        onRestoreRequested: function (path) { root.requestRestore(path) }
    }

    KeyboardPanel {
        id: dropdown
        anchorItem: button
        owner: root
        bar: root.bar
        open: root.opened
        focusTarget: keyCatcher
        contentWidth: dropdown.fittedContentWidth(Style.space(380))
        contentHeight: dropdown.fittedContentHeight(col.implicitHeight, Style.space(520))

        PanelKeyCatcher {
            id: keyCatcher
            anchors.fill: parent
            onCloseRequested: {
                // The restore question is modal over this content: Escape
                // answers it rather than closing the panel underneath.
                if (root.askingRestore) root.cancelRestore()
                else root.close()
            }
            onTabRequested: function (dir) {
                if (!root.askingRestore) root.switchPanel(dir)
            }
            // Left and right page the history; up and down are the shell's.
            onMoveRequested: function (dx) {
                // While the question is open the arrows move its choice rather
                // than paging the history behind it.
                if (root.askingRestore) {
                    restoreQuestion.selectedIndex = dx < 0 ? 0 : 1
                    return
                }
                if (dx < 0) root.pagePrevious()
                else if (dx > 0) root.pageNext()
            }
            onActivateRequested: {
                if (root.askingRestore) restoreQuestion.selectedIndex
                        ? root.confirmRestore() : root.cancelRestore()
            }
            onReturnRequested: {
                if (root.askingRestore) restoreQuestion.selectedIndex
                        ? root.confirmRestore() : root.cancelRestore()
            }

            Flickable {
                anchors.fill: parent
                contentWidth: width
                contentHeight: col.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds

                Column {
                    id: col
                    width: parent.width
                    spacing: Style.space(14)
                    topPadding: Style.space(12)
                    bottomPadding: Style.space(12)

                    PanelHero {
                        width: parent.width
                        title: "Opushy"
                        meta: Plain.plain(root.maxPushups > 0
                            ? "Record: " + root.maxPushups + "×  •  Round: " + root.reps + "×"
                            : "First setup")
                        foreground: Color.foreground
                        fontFamily: Style.font.family
                        iconComponent: Component {
                            DayBubble {
                                statusValue: root.statusValue
                                daysSinceLast: root.daysSinceLast
                                everTrained: root.everTrained
                                // The disc already carries the
                                // on-track/keep/drop colour; the tooltip spells
                                // out which is which.
                                tooltip: true
                                // The hero's icon slot sizes the item from its
                                // implicit size, so the size is asked for here.
                                implicitWidth: Math.round(Style.font.display * 1.25)
                                implicitHeight: Math.round(Style.font.display * 1.25)
                            }
                        }
                    }

                    PanelSeparator { foreground: Color.foreground }

                    Text {
                        width: parent.width
                        visible: store.error !== ""
                        text: store.error
                        textFormat: Text.PlainText
                        color: Color.foreground
                        font.family: Style.font.family
                        font.pixelSize: Style.font.caption
                        wrapMode: Text.WordWrap
                    }

                    SetupSection {
                        width: parent.width
                        visible: root.maxPushups === 0
                        draft: root.maxDraft
                        canSave: isFinite(root.maxDraftValue) && root.maxDraftValue > 0
                        onMaxDraftChanged: function (text) { root.maxDraft = text }
                        onMaxCommitted: function (max) { root.saveMax(max) }
                    }

                    ProgressSection {
                        width: parent.width
                        visible: root.maxPushups > 0 && !root.showingSession && !root.celebrating
                        history: root.history
                        page: root.page
                        pageCount: root.pageCount
                        onStartRequested: root.startSession()
                        onPreviousPageRequested: root.pagePrevious()
                        onNextPageRequested: root.pageNext()
                    }

                    CelebrationSection {
                        width: parent.width
                        visible: root.maxPushups > 0 && root.celebrating
                        reps: root.sessionReps
                        previousRecord: root.previousRecord
                        newRecord: root.newRecord
                        onFinished: root.finishCelebration()
                    }

                    Text {
                        width: parent.width
                        visible: root.fileNotice !== ""
                        text: root.fileNotice
                        textFormat: Text.PlainText
                        color: Util.alpha(Color.foreground, 0.7)
                        font.family: Style.font.family
                        font.pixelSize: Style.font.caption
                        wrapMode: Text.WordWrap
                    }

                    SessionSection {
                        width: parent.width
                        visible: root.maxPushups > 0 && root.showingSession
                        reps: root.reps
                        round: root.currentRound
                        remaining: root.remaining
                        counting: root.counting
                        paused: root.paused
                        confirming: root.confirming
                        onStartRequested: root.startSession()
                        onNextRequested: root.nextRound()
                        onPauseToggled: root.togglePause()
                        onSkipRequested: root.skipRest()
                        onStopRequested: root.requestStop()
                        onStopConfirmed: root.stopSession()
                        onStopCancelled: root.confirming = false
                    }
                }
            }
        }

        // The restore question, over the panel's content and on the same
        // surface, so it takes the keys while it is open.
        //
        // A sibling of keyCatcher on purpose, not a child of the Panel above.
        // QML will only anchor to a parent or a sibling, and anchoring to
        // keyCatcher from anywhere else fails silently: the dialog gets no
        // geometry and draws itself cropped at the top of the bar, which is
        // exactly what it did here.
        ConfirmDialog {
            id: restoreQuestion
            anchors.fill: keyCatcher
            z: 10
            opened: root.askingRestore
            // The chosen file's name is the one variable in here, and it came
            // out of a file chooser, so it is stripped before the shell renders
            // it: that widget owns its Text item and cannot pin the format.
            message: "Replace your activity with " + Plain.plain(root.restoreFileName)
                    + "? Your current state is kept in backups/ first."
            confirmText: "Restore"
            onCanceled: root.cancelRestore()
            onConfirmed: root.confirmRestore()
        }
    }

    DebugIpc { id: debug; panel: root }
}
