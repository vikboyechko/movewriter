import QtQuick 2.15

// High-contrast e-ink button — large tap target, inverts on press
Rectangle {
    id: btn

    property string text: ""
    property bool enabled: true
    property alias font: label.font

    signal clicked()

    width: Math.max(label.implicitWidth + 48, 180)
    height: 72
    radius: 8
    color: !enabled ? "#e0e0e0" : pressed ? "black" : "white"
    border.color: !enabled ? "#999" : "black"
    border.width: 3

    property bool pressed: false

    Text {
        id: label
        text: btn.text
        color: !btn.enabled ? "#999" : btn.pressed ? "white" : "black"
        font.pixelSize: 28
        font.bold: true
        anchors.centerIn: parent
    }

    MouseArea {
        anchors.fill: parent
        enabled: btn.enabled
        onPressed: btn.pressed = true
        onReleased: {
            btn.pressed = false
            btn.clicked()
        }
        onCanceled: btn.pressed = false
    }
}
