import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Ui
import "Status.js" as Status

// The confetti shower, on a surface of its own.
//
// The panel is a small drop-down, so a shower inside it would be a handful of
// characters behind a dropdown. This puts one on a fullscreen layer-shell
// surface instead, with an empty input region so it never takes a click from the
// desktop underneath (the same trick the OSD uses).
//
// Confetti comes from the composite namespace that Panel.qml's `import "ui"`
// sets up: a file that imported its sibling by relative path would not resolve
// inside a plugin folder.
//
// The root is a zero-sized Item because QtObject has no default property to hold
// the PanelWindow child.
Item {
    id: celebration
    width: 0
    height: 0

    required property var panel          // the plugin root
    required property string namespace   // layer-shell namespace, unique per surface

    readonly property var palette: [
        Status.ON_TRACK, Status.KEEP, Status.DROP, Color.accent, Color.foreground
    ]

    PanelWindow {
        id: surface
        visible: celebration.panel.celebrating
        anchors { top: true; bottom: true; left: true; right: true }
        color: "transparent"
        WlrLayershell.namespace: celebration.namespace
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
        exclusionMode: ExclusionMode.Ignore
        // Visual only: an empty input region keeps every click on the desktop
        // below it.
        mask: Region {}

        Confetti {
            anchors.fill: parent
            running: celebration.panel.celebrating
            palette: celebration.palette
            scale: 1.4
        }
    }
}
