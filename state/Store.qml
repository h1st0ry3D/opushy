import QtQuick
import Quickshell.Io
import "../core/Progression.js" as Progression
import "../core/Document.js" as Document

// The plugin's window onto its state file.
//
// Reads and writes are argv arrays of one helper (state/opushy-state.py), which
// does the descriptor-bound read and the atomic 0600 write. The QML side only
// parses what came back, through a byte budget. FileView watches the file and
// never serves its contents.
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

    signal documentRead(var document)

    property string readBuffer: ""
    property bool readOverflow: false
    property string pendingWrite: ""

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
        onExited: function (code) {
            if (code === 0 && !store.readOverflow) {
                store.error = ""
                store.documentRead(Document.parse(store.readBuffer, Progression))
            } else if (code !== 0) {
                store.error = "Could not read the tracker file."
            } else {
                store.error = "The tracker file is larger than " + store.maxBytes + " bytes."
            }
            store.readBuffer = ""
            store.readOverflow = false
        }
    }

    Process {
        id: writeProc
        command: [store.python, "-I", "-S", "-B", store.helperPath, "state", "write"]
        stdinEnabled: true
        onStarted: {
            // The helper reads one bounded line, so this never needs EOF.
            write(store.pendingWrite + "\n")
            store.pendingWrite = ""
            stdinEnabled = false
        }
        onExited: function (code) {
            if (code === 0) store.error = ""
            else store.error = "Could not save the tracker file."
            store.startWrite()      // a save that arrived mid-write goes out now
        }
    }

    Process {
        id: importProc
        command: [store.python, "-I", "-S", "-B", store.helperPath, "migrate", store.legacyPath]
        onExited: function (code) {
            if (code !== 0) store.error = "Could not import the old tracker.json."
            store.startRead()
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
        if (readProc.running) return
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
}
