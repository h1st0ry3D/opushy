import QtQuick
import QtQuick.Controls
import qs.Commons
import qs.Ui
import "../core/Progression.js" as Progression

// The session screen: round 1 to 3, a 45 second rest between them, and the
// confirmation in front of throwing a session away. All three states live in one
// screen because the round counter, the buttons and the confirm share the same
// place, and swapping whole screens would make the countdown jump.
//
// The reps are the ones the session started with, frozen at Start (Panel.qml).
Column {
    id: session

    required property int reps
    required property int round
    required property int remaining
    required property bool counting
    required property bool paused
    required property bool confirming

    // The three things this screen can be showing. The button set follows from
    // these, so a state and its buttons cannot disagree.
    readonly property bool resting: session.counting && !session.confirming
    readonly property bool working: !session.counting && !session.confirming
    readonly property bool stopping: session.confirming

    signal startRequested()
    signal nextRequested()
    signal pauseToggled()
    signal skipRequested()
    signal stopRequested()
    signal stopConfirmed()
    signal stopCancelled()

    width: parent.width
    spacing: Style.space(12)

    Item {
        width: parent.width
        implicitHeight: 56

        Text {
            anchors.centerIn: parent
            visible: !session.confirming && !session.counting
            text: session.round > 0 ? session.reps + "× Push-ups" : "Ready: " + session.reps + "×"
            textFormat: Text.PlainText
            color: Color.foreground
            font.family: Style.font.family
            font.pixelSize: 26
            font.bold: true
        }

        Text {
            anchors.centerIn: parent
            visible: !session.confirming && session.counting
            text: session.remaining + "s"
            textFormat: Text.PlainText
            color: Color.accent
            font.family: Style.font.family
            font.pixelSize: 32
            font.bold: true
        }

        Text {
            anchors.fill: parent
            visible: session.confirming
            text: "Stop current session?"
            textFormat: Text.PlainText
            color: Color.foreground
            font.family: Style.font.family
            font.pixelSize: 18
            font.bold: true
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
        }
    }

    Text {
        visible: !session.confirming
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        text: session.counting ? "Rest — pause or skip" : "Round " + (session.round || 1) + " / " + Progression.ROUNDS
        textFormat: Text.PlainText
        color: Util.alpha(Color.foreground, 0.65)
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
    }

    Row {
        visible: !session.confirming
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: Style.space(8)

        Repeater {
            model: Progression.ROUNDS

            Rectangle {
                required property int index
                width: 10
                height: 10
                radius: 5
                color: (index + 1) === session.round ? Color.accent
                       : (index + 1) < session.round ? Color.foreground
                       : Util.alpha(Color.foreground, 0.2)
            }
        }
    }

    // Proceeding sits on the right, pausing and interrupting on the left.
    //
    // The widths come from the row and how many buttons are up, not from the
    // labels: a layout that shares the leftover space hands each button its
    // implicit width first, so a longer word would make that button wider.
    readonly property int buttonCount: (session.resting ? 2 : 0)
                                       + (session.working ? (session.round > 0 ? 2 : 1) : 0)
                                       + (session.stopping ? 2 : 0)
    readonly property real buttonWidth: session.buttonCount > 0
        ? (session.width - Math.max(0, session.buttonCount - 1) * Style.space(10))
          / session.buttonCount
        : 0

    Row {
        width: parent.width
        spacing: Style.space(10)

        Button {
            width: session.buttonWidth
            visible: session.resting
            text: session.paused ? "Continue" : "Pause"
            onClicked: session.pauseToggled()
        }

        Button {
            width: session.buttonWidth
            visible: session.resting
            text: "Skip"
            onClicked: session.skipRequested()
        }

        Button {
            width: session.buttonWidth
            visible: session.working && session.round > 0
            text: "Stop"
            onClicked: session.stopRequested()
        }

        Button {
            width: session.buttonWidth
            visible: session.stopping
            text: "Yes"
            onClicked: session.stopConfirmed()
        }

        Button {
            width: session.buttonWidth
            visible: session.working
            // The last round has no rest after it, so the button stops promising
            // one.
            text: session.round === 0 ? "Start"
                  : session.round >= Progression.ROUNDS ? "Done" : "Next"
            onClicked: session.round === 0 ? session.startRequested() : session.nextRequested()
        }

        Button {
            width: session.buttonWidth
            visible: session.stopping
            text: "No"
            onClicked: session.stopCancelled()
        }
    }

    PanelSeparator { foreground: Color.foreground }

    Text {
        width: parent.width
        text: "Next: within 2 days +1 • day 3 keep • day 4+ -1"
        textFormat: Text.PlainText
        color: Util.alpha(Color.foreground, 0.6)
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
        horizontalAlignment: Text.AlignHCenter
    }
}
