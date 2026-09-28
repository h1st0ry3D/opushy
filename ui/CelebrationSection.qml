import QtQuick
import QtQuick.Controls
import qs.Commons
import qs.Ui
import "../core/Progression.js" as Progression

// What replaces the countdown when the third rest runs out.
//
// The session is already written at this point, so this screen only reports: the
// headline (a new record or just progress), the number that was asked for, and
// the one button that closes it.
Column {
    id: celebration

    required property int reps
    required property int previousRecord      // 0 when there was no record to beat
    required property bool newRecord

    signal finished()

    width: parent.width
    spacing: Style.space(12)

    Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        text: celebration.newRecord ? "NEW RECORD" : "GREAT PROGRESS"
        textFormat: Text.PlainText
        color: celebration.newRecord ? Color.accent : Color.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.heading
        font.bold: true
        wrapMode: Text.WordWrap
    }

    Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        text: celebration.reps + "×"
        textFormat: Text.PlainText
        color: Color.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.displayLarge
        font.bold: true
    }

    Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        text: celebration.newRecord
              ? "Past your record of " + celebration.previousRecord + "×"
              : Progression.ROUNDS + " rounds, " + celebration.reps * Progression.ROUNDS + " push-ups"
        textFormat: Text.PlainText
        color: Util.alpha(Color.foreground, 0.7)
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.WordWrap
    }

    Item { width: 1; height: Style.space(4) }

    Button {
        width: parent.width
        text: "Finish"
        onClicked: celebration.finished()
    }
}
