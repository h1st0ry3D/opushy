import QtQuick
import Quickshell.Io

// The plugin's window onto its state file.
//
// Reads and writes are argv arrays of one helper (state/opushy-state.py), which
// does the descriptor-bound read and the atomic 0600 write. The QML side only
// reads what came back, through a byte budget, and hands the raw text on. It
// does not parse: see documentRead. FileView watches the file and never serves
// its contents.
//
// The root is a zero-sized Item because QtObject has no default property to hold
// the Process and FileView children.
Item {
    id: store
    width: 0
    height: 0

    required property string python        // absolute interpreter
    required property string helperPath    // absolute path to opushy-state.py
    required property string statePath     // watcher only: the file the helper owns
    required property string legacyPath    // pre-1.0 file, imported once

    // Consumer-side ceiling; the helper enforces the real one.
    readonly property int maxBytes: 65536

    // Set when a read, a write or the import fails; cleared by the next good one.
    property string error: ""
    property bool imported: false          // the one-off import has been attempted

    // The raw document text, not the parsed object. A `var` signal marshals a
    // JavaScript value through QVariant, and an array inside the parsed document
    // comes back out as a V4Sequence rather than a real Array. It still indexes
    // and pages like one, but Array.isArray() says no, which is how the history
    // strip silently read every gap as "on track" and how a save could write the
    // history away. Parsing on the receiving side keeps native arrays native.
    signal documentRead(string raw)
    // A backup or a restore finished, including one the helper refused. The
    // message says what happened. `verb` is "export" or "restore", so the
    // panel can put an export's result back on the menu that asked for it.
    signal fileOpDone(string verb, string message)

    property string readBuffer: ""
    property bool readOverflow: false
    property string pendingWrite: ""

    // Every helper run is one python process with no children, so a signal
    // reaches the helper itself and no process group is needed. Each process
    // gets a deadline, because a helper that never answers would otherwise
    // leave the panel waiting on it for the rest of the session, and a shared
    // escalation turns a helper that ignores TERM into one that is reaped.
    function timedOut(proc, message) {
        if (!proc.running) return
        store.error = message
        proc.signal(15)
        escalation.restart()
    }

    function stopAll(alsoKill) {
        readDeadline.stop()
        writeDeadline.stop()
        importDeadline.stop()
        fileDeadline.stop()
        escalation.stop()
        // Every helper writes through a temporary and a rename, so neither
        // signal can leave a half-written file behind. `alsoKill` is for the
        // destruction path, where there is no grace period left to offer.
        if (readProc.running) readProc.signal(15)
        if (writeProc.running) writeProc.signal(15)
        if (importProc.running) importProc.signal(15)
        if (fileProc.running) fileProc.signal(15)
        if (alsoKill) {
            if (readProc.running) readProc.signal(9)
            if (writeProc.running) writeProc.signal(9)
            if (importProc.running) importProc.signal(9)
            if (fileProc.running) fileProc.signal(9)
        }
    }

    // Kept armed after the leader exits, so a helper that outlives its TERM is
    // still killed. Two seconds is the grace, not the deadline.
    Timer {
        id: escalation
        interval: 2000
        onTriggered: stopAll(true)
    }

    // Set while a backup or a restore is running, and the one-line result the
    // helper printed, so the panel can say what happened.
    property bool working: false
    property string notice: ""
    // At most one queued request, so two clicks cannot stack up.
    property string queuedVerb: ""
    property string queuedPath: ""
    property bool readQueued: false

    Process {
        id: readProc
        command: [store.python, "-I", "-S", "-B", store.helperPath, "state", "read"]
        stdout: SplitParser {
            splitMarker: ""                 // raw chunks: the budget is counted here
            onRead: function (chunk) {
                // .length counts UTF-16 units; the byte cap is the helper's.
                if (store.readBuffer.length + chunk.length > store.maxBytes) {
                    store.readOverflow = true
                    return
                }
                if (!store.readOverflow) store.readBuffer += chunk
            }
        }
        onStarted: readDeadline.restart()
        onExited: function (code) {
            readDeadline.stop()
            if (code === 0 && !store.readOverflow) {
                store.error = ""
                store.documentRead(store.readBuffer)
            } else if (code !== 0) {
                store.error = "Could not read the tracker file."
            } else {
                store.error = "The tracker file is larger than " + store.maxBytes + " bytes."
            }
            store.readBuffer = ""
            store.readOverflow = false
            // A read that was asked for while this one ran: the file has been
            // written since, so this document is the one before it.
            if (store.readQueued) {
                store.readQueued = false
                readProc.running = true
                return
            }
            store.runQueued()
        }
    }

    // Ten seconds for a bounded read of one small file. Generous for what the
    // helper does, short enough that a stuck run becomes a message rather than
    // a panel that never updates again.
    Timer {
        id: readDeadline
        interval: 10000
        onTriggered: store.timedOut(readProc, "Reading the tracker file took too long.")
    }

    Process {
        id: writeProc
        command: [store.python, "-I", "-S", "-B", store.helperPath, "state", "write"]
        stdinEnabled: true
        onStarted: {
            writeDeadline.restart()
            // The helper reads one bounded line, so this never needs EOF.
            write(store.pendingWrite + "\n")
            store.pendingWrite = ""
            stdinEnabled = false
        }
        onExited: function (code) {
            writeDeadline.stop()
            if (code === 0) store.error = ""
            else store.error = "Could not save the tracker file."
            store.startWrite()      // a save that arrived mid-write goes out now
            store.runQueued()       // and then a backup or restore that was waiting
        }
    }

    Timer {
        id: writeDeadline
        interval: 10000
        onTriggered: store.timedOut(writeProc, "Saving the tracker file took too long.")
    }

    Process {
        id: importProc
        command: [store.python, "-I", "-S", "-B", store.helperPath, "migrate", store.legacyPath]
        onStarted: importDeadline.restart()
        onExited: function (code) {
            importDeadline.stop()
            if (code !== 0) store.error = "Could not bring the old tracker file over."
            store.startRead()
            store.runQueued()
        }
    }

    // The import reads two files and writes one, so it gets longer than a
    // plain read or save.
    Timer {
        id: importDeadline
        interval: 20000
        onTriggered: store.timedOut(importProc, "Importing the old tracker file took too long.")
    }

    // The one process that backs up or restores, so the two cannot interleave
    // and a restore cannot land in the middle of a save.
    Process {
        id: fileProc
        property string verb: ""

        command: [store.python, "-I", "-S", "-B", store.helperPath, "backup", fileProc.verb]
        stdinEnabled: true
        onStarted: {
            fileDeadline.restart()
            // The helper reads one bounded line, so this never needs EOF.
            write(store.pendingFile + "\n")
            store.pendingFile = ""
            stdinEnabled = false
        }
        stdout: SplitParser {
            splitMarker: ""
            onRead: function (chunk) {
                // The helper prints one short result line; anything longer than
                // that is not the reply this is waiting for.
                if (store.notice.length + chunk.length > store.maxBytes) {
                    store.error = "The helper said something unexpected."
                    return
                }
                store.notice += chunk
            }
        }
        onExited: function (code) {
            var verb = fileProc.verb
            var message = ""
            store.working = false
            fileProc.verb = ""
            fileDeadline.stop()
            if (code === 0) {
                store.error = ""
                // Read the helper's line before notice is cleared below.
                message = store.reportFor(verb)
            } else if (code === 1) {
                // The helper refused, and said why on stderr. Quickshell does
                // not hand stderr over, so the exit code is all that arrives
                // and this words it. The file it was about is untouched either
                // way, which is the part worth saying.
                message = verb === "restore"
                    ? "That file was not restored. It is not a backup this plugin wrote."
                    : "The backup was not written there."
            } else {
                message = "The helper could not be run."
            }
            store.notice = ""
            store.fileOpDone(verb, message)
            // A restore replaced the file, so the panel re-reads it and the
            // watcher fires as well; one of the two is enough and startRead()
            // ignores the other.
            startRead()
            // A request that arrived while this one ran goes out now.
            runQueued()
        }
    }

    // A backup or a restore copies one bounded file. The deadline is longer than
    // a read because the file may be on another volume, but it is still a
    // deadline: without one a chooser pointing at an unplugged drive leaves the
    // rows dead for the rest of the session.
    Timer {
        id: fileDeadline
        interval: 30000
        onTriggered: {
            // The verb is read before the state is cleared, so the message
            // names the operation that ran out of time.
            var verb = fileProc.verb
            store.working = false
            fileProc.verb = ""
            store.timedOut(fileProc,
                verb === "restore" ? "That file took too long to read."
                                   : "Writing that backup took too long.")
        }
    }

    // preload off and blockAllReads on, so nothing here can hand out a read.
    FileView {
        id: watcher
        path: store.statePath
        preload: false
        blockAllReads: true
        watchChanges: true
        printErrors: false
        onFileChanged: store.startRead()
    }

    function load() {
        if (store.imported) { startRead(); return }
        store.imported = true
        importProc.running = true
    }

    function startRead() {
        // A read asked for while one is in flight is remembered rather than
        // dropped: that is how a restore gets the file it just wrote read back
        // instead of the one that was on disk when the read started.
        if (readProc.running) { store.readQueued = true; return }
        readProc.running = true
    }

    // One write is in flight, and at most one is held back.
    function save(document) {
        store.pendingWrite = document
        store.startWrite()
    }

    function startWrite() {
        if (writeProc.running || store.pendingWrite === "") return
        writeProc.running = true
    }

    // ---- backup and restore ----
    //
    // `path` is the file the panel's own dialog returned. It is handed over as
    // the one bounded line the helper reads, never as an argument, so it is not
    // in any process's /proc/<pid>/cmdline while the helper runs.
    property string pendingFile: ""

    function exportTo(path) {
        store.beginFileOp("export", path)
    }

    function restoreFrom(path) {
        store.beginFileOp("restore", path)
    }

    function beginFileOp(verb, path) {
        if (typeof path !== "string" || path === "") {
            store.error = "No file was chosen."
            return
        }
        if (store.working) return
        store.queuedVerb = verb
        store.queuedPath = path
        store.runQueued()
    }

    // A read or a save in flight owns the state file, and a restore replacing
    // it under one would leave the panel and the file disagreeing. So the
    // request waits its turn rather than racing, and a save that is still only
    // queued goes out first: the backup is then of what was just written.
    function runQueued() {
        if (store.working || store.queuedVerb === "") return
        if (readProc.running || importProc.running) return
        if (writeProc.running) return
        if (store.pendingWrite !== "") { startWrite(); return }
        store.error = ""
        store.working = true
        fileProc.verb = store.queuedVerb
        store.pendingFile = JSON.stringify({ path: store.queuedPath })
        store.queuedVerb = ""
        store.queuedPath = ""
        fileProc.running = true
    }

    // The shell is going away, and a helper started by this panel must not
    // outlive it. Every write the helper does is a temporary plus a rename, so
    // a signal can never leave a half-written tracker behind. There is no grace
    // period here to offer, so a helper still running after TERM is killed.
    Component.onDestruction: stopAll(true)

    // What the helper printed, turned into one sentence. The reply is its own
    // JSON, so a name is a string and is flattened here rather than in the
    // panel: it came out of a dialog and the shell renders this text.
    function reportFor(verb) {
        var reply = null
        try {
            reply = JSON.parse(store.notice)
        } catch (e) {
            reply = null
        }
        if (!reply || reply.ok !== true) return verb === "restore" ? "Restored." : "Backed up."
        if (verb === "restore") {
            var sessions = Number(reply.sessions)
            return isFinite(sessions) && sessions === 1
                ? "Restored 1 session. The state before it is in backups/."
                : "Restored " + sessions + " sessions. The state before it is in backups/."
        }
        return "Wrote " + reply.name + "."
    }
}
