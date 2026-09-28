import QtQuick
import QtQuick.Controls
import qs.Commons
import qs.Ui
import "Status.js" as Status

// The progress screen: the recorded chain, and the way back into a session.
//
// HistoryStrip is used through the composite namespace that Panel.qml's
// `import "ui"` sets up. A file that imported its sibling by relative path would
// not resolve inside a plugin folder.
Column {
    id: progress

    required property var history
    required property int page
    required property int pageCount

    signal startRequested()
    signal previousPageRequested()
    signal nextPageRequested()

    width: parent.width
    spacing: Style.space(12)

    Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        text: "My Activity"
        textFormat: Text.PlainText
        color: Color.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.title
        font.bold: true
    }

    HistoryStrip {
        width: parent.width
        history: progress.history
        page: progress.page
        pageCount: progress.pageCount
        onPreviousRequested: progress.previousPageRequested()
        onNextRequested: progress.nextPageRequested()
    }

    // The same three statuses as the strip above, in words.
    Row {
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: Style.space(12)

        Repeater {
            model: [
                { value: 1, text: "1-2 days" },
                { value: 0, text: "3 days" },
                { value: -1, text: "4 or more days" }
            ]

            Row {
                id: legendItem
                required property var modelData
                spacing: 4

                Rectangle {
                    width: 10
                    height: 10
                    radius: 5
                    color: Status.colorForValue(legendItem.modelData.value)
                    anchors.verticalCenter: parent.verticalCenter
                }

                Text {
                    text: legendItem.modelData.text
                    textFormat: Text.PlainText
                    color: Util.alpha(Color.foreground, 0.6)
                    font.family: Style.font.family
                    font.pixelSize: 9
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
        }
    }

    Button {
        width: parent.width
        text: "Start"
        onClicked: progress.startRequested()
    }
}
