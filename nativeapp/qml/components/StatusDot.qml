import QtQuick 2.15

// Status indicator dot for e-ink display
Rectangle {
    id: dot

    property string status: "pending"

    width: 24
    height: 24
    radius: 12
    color: status === "done" ? "black" : "white"
    border.color: "black"
    border.width: status === "pending" ? 2 : 3

    Rectangle {
        visible: dot.status === "running"
        width: 12
        height: 12
        radius: 6
        color: "black"
        anchors.centerIn: parent
    }

    Text {
        visible: dot.status === "error"
        text: "✕"
        font.pixelSize: 14
        font.bold: true
        color: "black"
        anchors.centerIn: parent
    }
}
