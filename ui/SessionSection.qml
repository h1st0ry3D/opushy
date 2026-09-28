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

    Row {
        width: parent.width
        spacing: Style.space(10)

        Button {
            visible: !session.confirming && !session.counting
            width: session.round === 0 ? parent.width : (parent.width - Style.space(10)) / 2
            // The last round has no rest after it, so the button stops promising
            // one.
            text: session.round === 0 ? "Start"
                  : session.round >= Progression.ROUNDS ? "Finish" : "Next"
            onClicked: session.round === 0 ? session.startRequested() : session.nextRequested()
        }

        Button {
            visible: !session.confirming && session.counting
            width: (parent.width - Style.space(10)) / 2
            text: session.paused ? "Continue" : "Pause"
            onClicked: session.pauseToggled()
        }

        Button {
            visible: !session.confirming && session.round > 0
            width: (parent.width - Style.space(10)) / 2
            text: session.counting ? "Skip" : "Stop"
            onClicked: session.counting ? session.skipRequested() : session.stopRequested()
        }

        Button {
            visible: session.confirming
            width: (parent.width - Style.space(10)) / 2
            text: "Yes"
            onClicked: session.stopConfirmed()
        }

        Button {
            visible: session.confirming
            width: (parent.width - Style.space(10)) / 2
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
