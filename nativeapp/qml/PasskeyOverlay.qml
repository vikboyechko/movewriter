import QtQuick 2.15

// Full-screen passkey display overlay
// Uses opaque white background (not transparent — e-ink ghosting)
Item {
    id: overlay
    visible: false

    function show(passkey) {
        passkeyText.text = passkey
        visible = true
    }

    function hide() {
        visible = false
    }

    // Opaque white background to cover everything
    Rectangle {
        anchors.fill: parent
        color: "white"
    }

    // Centered card
    Rectangle {
        width: 360
        height: 220
        anchors.centerIn: parent
        color: "white"
        border.color: "black"
        border.width: 2
        radius: 8

        Column {
            anchors.centerIn: parent
            spacing: 16

            Text {
                text: "Enter this code on your keyboard:"
                font.pixelSize: 16
                color: "black"
                anchors.horizontalCenter: parent.horizontalCenter
            }

            Text {
                id: passkeyText
                text: ""
                font.pixelSize: 48
                font.bold: true
                font.letterSpacing: 8
                color: "black"
                anchors.horizontalCenter: parent.horizontalCenter
            }

            Text {
                text: "Then press Enter"
                font.pixelSize: 14
                color: "#222"
                anchors.horizontalCenter: parent.horizontalCenter
            }
        }
    }

    // Block input to items behind overlay
    MouseArea {
        anchors.fill: parent
    }
}
