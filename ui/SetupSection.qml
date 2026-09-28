import QtQuick
import QtQuick.Controls
import qs.Commons
import qs.Ui

// First run: the recorded max, asked once.
//
// The field is validated and only applied on Save, so a half-typed number never
// reaches the progression.
Column {
    id: setup

    required property string draft
    required property bool canSave

    signal maxCommitted(int maxPushups)
    signal maxDraftChanged(string text)

    width: parent.width
    spacing: Style.space(10)

    Text {
        width: parent.width
        text: "How many pushups can you do at max?"
        textFormat: Text.PlainText
        color: Color.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.body
        wrapMode: Text.WordWrap
    }

    Row {
        width: parent.width
        spacing: Style.space(8)

        TextField {
            id: field
            width: 100
            placeholderText: "e.g. 25"
            text: setup.draft
            font.family: Style.font.family
            validator: IntValidator { bottom: 1; top: 500 }
            // onTextEdited reports the user's own edits only, so writing the
            // draft back into the field cannot re-trigger this.
            onTextEdited: setup.maxDraftChanged(text)
            onAccepted: setup.commit()
        }

        Button {
            text: "Save"
            enabled: setup.canSave
            onClicked: setup.commit()
        }
    }

    Text {
        width: parent.width
        text: "We start with 75% of your max for 3 rounds."
        textFormat: Text.PlainText
        color: Util.alpha(Color.foreground, 0.7)
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
    }

    function commit() {
        if (!setup.canSave) return
        setup.maxCommitted(Math.floor(Number(setup.draft)))
    }
}
