import QtQuick
import qs.Commons
import qs.Ui
import "Status.js" as Status
import "Plain.js" as Plain

// The status dot in the hero's trailing slot: a coloured disc with the days
// since the last session, and a tooltip spelling out what the colour means.
Item {
    id: dot
    width: 36
    height: 36

    required property int statusValue      // core/Progression.js: ON_TRACK / KEEP / DROP
    required property int daysSinceLast
    required property bool everTrained

    readonly property color fillColor: Status.colorForValue(dot.statusValue)
    // "∞" until there is a session to count from.
    readonly property string dayLabel: !dot.everTrained ? "∞" : (dot.daysSinceLast + "d")

    Rectangle {
        id: disc
        anchors.fill: parent
        radius: width / 2
        color: dot.fillColor
        border.width: 1
        border.color: Util.alpha(Color.foreground, 0.2)
    }

    Text {
        anchors.centerIn: disc
        text: dot.dayLabel
        textFormat: Text.PlainText
        color: "white"
        font.family: Style.font.family
        font.pixelSize: 11
        font.bold: true
    }

    MouseArea {
        id: hover
        anchors.fill: parent
        hoverEnabled: true
    }

    PanelToolTip {
        visible: hover.containsMouse
        text: Plain.plain(Status.labelForValue(dot.statusValue))
        fontFamily: Style.font.family
    }
}
