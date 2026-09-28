import QtQuick
import Quickshell.Io

// The end-of-rest cue: one system sound, played by whichever of pw-play, paplay
// or aplay exists. The sound file and the players are probed with `test -r` and
// `test -x` and answered by exit codes. Without either, the cue is silent and
// the countdown is unaffected.
Item {
    id: alert
    width: 0
    height: 0

    readonly property string soundPath: "/usr/share/sounds/freedesktop/stereo/complete.oga"
    readonly property var players: ["/usr/bin/pw-play", "/usr/bin/paplay", "/usr/bin/aplay"]

    property int playerIndex: 0
    property bool soundPresent: false
    property string player: ""            // the first player that exists, if any

    readonly property bool ready: alert.soundPresent && alert.player !== ""

    Process {
        id: soundProbe
        command: ["/usr/bin/test", "-r", alert.soundPath]
        running: true
        onExited: function (code) {
            if (code !== 0) return       // no cue on this machine
            alert.soundPresent = true
            playerProbe.running = true
        }
    }

    Process {
        id: playerProbe
        command: ["/usr/bin/test", "-x", alert.players[alert.playerIndex]]
        running: false
        onExited: function (code) {
            if (code === 0) {
                alert.player = alert.players[alert.playerIndex]
                return
            }
            if (alert.playerIndex < alert.players.length - 1) {
                alert.playerIndex = alert.playerIndex + 1
                running = true
            }
        }
    }

    Process { id: voice }

    function play() {
        if (!alert.ready || voice.running) return
        voice.command = [alert.player, alert.soundPath]
        voice.running = true
    }
}
