import QtQuick
import Quickshell
import Quickshell.Io

// Debug IPC: `omarchy-shell shell opushy.debug <fn> x` (see README). Each
// handler reads the current state or drives the panel the way its own buttons
// do; the argument the shell hands back is ignored.
Item {
    id: debugIpc

    required property var panel           // Panel.qml

    IpcHandler {
        target: "opushy.debug"

        function start(x: string): string {
            debugIpc.panel.startSession();
            return debugIpc.panel.state();
        }

        function next(x: string): string {
            debugIpc.panel.nextRound();
            return debugIpc.panel.state();
        }

        function skip(x: string): string {
            debugIpc.panel.skipRest();
            return debugIpc.panel.state();
        }

        function showProgress(x: string): string {
            debugIpc.panel.showingSession = false;
            return debugIpc.panel.state();
        }

        function showSession(x: string): string {
            debugIpc.panel.showingSession = true;
            debugIpc.panel.currentRound = 1;
            return debugIpc.panel.state();
        }

        function state(x: string): string {
            return debugIpc.panel.state();
        }
    }
}
