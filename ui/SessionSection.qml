import QtQuick
import QtQuick.Controls
import qs.Commons
import qs.Ui
import "../core/Progression.js" as Progression

// The session screen: round 1 to 3, a 45 second rest between them, and the two
// questions in front of ending one early — throwing the session away, or
// softening its target. All of these states live in one screen because the round
// counter, the buttons and the questions share the same place, and swapping
// whole screens would make the countdown jump.
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
    required property bool softening

    // The question in front of either way out of a round: throwing the session
    // away, or taking two reps off it. Both take the headline over and offer Yes
    // and No, so the round controls step aside while one of them is up.
    readonly property bool asking: session.confirming || session.softening

    // The four things this screen can be showing. The button set follows from
    // these, so a state and its buttons cannot disagree.
    readonly property bool resting: session.counting && !session.asking
    readonly property bool working: !session.counting && !session.asking
    readonly property bool stopping: session.confirming
    readonly property bool softeningTarget: session.softening

    // The last round has no rest after it, so it ends the session instead, and
    // there is nothing left to soften: only one button is offered.
    readonly property bool lastRound: session.round >= Progression.ROUNDS
    // A round with a rest (or another round) still ahead of it, which is the
    // only place "Too Hard" makes sense.
    readonly property bool midRound: session.round > 0 && !session.lastRound

    signal startRequested()
    signal nextRequested()
    signal tooHardRequested()
    signal tooHardConfirmed()
    signal tooHardCancelled()
    signal pauseToggled()
    signal skipRequested()
    signal stopConfirmed()
    signal stopCancelled()

    width: parent.width
    spacing: Style.space(12)

    Item {
        width: parent.width
        implicitHeight: 56

        Text {
            anchors.centerIn: parent
            visible: !session.asking && !session.counting
            text: session.round > 0 ? session.reps + "× Push-ups" : "Ready: " + session.reps + "×"
            textFormat: Text.PlainText
            color: Color.foreground
            font.family: Style.font.family
            font.pixelSize: 26
            font.bold: true
        }

        Text {
            anchors.centerIn: parent
            visible: !session.asking && session.counting
            text: session.remaining + "s"
            textFormat: Text.PlainText
            color: Color.accent
            font.family: Style.font.family
            font.pixelSize: 32
            font.bold: true
        }

        Text {
            anchors.fill: parent
            visible: session.softening
            text: "Reduce reps by 2?"
            textFormat: Text.PlainText
            color: Color.foreground
            font.family: Style.font.family
            font.pixelSize: 18
            font.bold: true
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
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

    // What the softened question is about: the number the rest of the session
    // would run at, beside the one it runs at now.
    Text {
        visible: session.softening
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        text: session.reps + "× → " + Progression.softenReps(session.reps) + "× for the rest of the session"
        textFormat: Text.PlainText
        color: Util.alpha(Color.foreground, 0.65)
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.WordWrap
    }

    Text {
        visible: !session.asking
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        text: session.counting ? "Rest — pause or skip" : "Round " + (session.round || 1) + " / " + Progression.ROUNDS
        textFormat: Text.PlainText
        color: Util.alpha(Color.foreground, 0.65)
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
    }

    Row {
        visible: !session.asking
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

    // Proceeding sits on the right, softening the target on the left, pausing
    // and skipping over a rest on the left as well. Stopping is not in this row
    // any more: it is the close button in the panel header.
    //
    // The widths come from the row and how many buttons are up, not from the
    // labels: a layout that shares the leftover space hands each button its
    // implicit width first, so a longer word would make that button wider.
    readonly property int buttonCount: (session.resting ? 2 : 0)
                                       + (session.working ? (session.midRound ? 2 : 1) : 0)
                                       + (session.stopping ? 2 : 0)
                                       + (session.softeningTarget ? 2 : 0)
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

        // Two reps off the same target for the rest of the session, then the
        // same end-of-round as Done: the round is still over.
        Button {
            width: session.buttonWidth
            visible: session.working && session.midRound
            text: "Too Hard"
            onClicked: session.tooHardRequested()
        }

        Button {
            width: session.buttonWidth
            visible: session.stopping
            text: "Yes"
            onClicked: session.stopConfirmed()
        }

        // The other question: the two reps off, or the round as it is.
        Button {
            width: session.buttonWidth
            visible: session.softeningTarget
            text: "Yes"
            onClicked: session.tooHardConfirmed()
        }

        Button {
            width: session.buttonWidth
            visible: session.working
            // The last round has no rest after it, so its button ends the
            // session instead of promising one.
            text: session.round === 0 ? "Start"
                  : session.lastRound ? "Finish" : "Done"
            onClicked: session.round === 0 ? session.startRequested() : session.nextRequested()
        }

        Button {
            width: session.buttonWidth
            visible: session.stopping
            text: "No"
            onClicked: session.stopCancelled()
        }

        Button {
            width: session.buttonWidth
            visible: session.softeningTarget
            text: "No"
            onClicked: session.tooHardCancelled()
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
