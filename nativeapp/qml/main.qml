import QtQuick 2.15
import net.asivery.AppLoad 1.0

// MoveWriter Native — AppLoad root component

Item {
    id: root
    anchors.fill: parent

    signal close()

    function unloading() {
        backend.terminate()
    }

    // AppLoad backend bridge
    AppLoad {
        id: backend
        applicationID: "movewriter"
        onMessageReceived: function(type, contents) {
            var msg
            try {
                msg = JSON.parse(contents)
            } catch(e) {
                return
            }

            // Response to a request
            if (msg.id !== undefined && _callbacks[msg.id]) {
                var cb = _callbacks[msg.id]
                delete _callbacks[msg.id]
                cb(msg)
                return
            }

            // Event from backend
            if (msg.event) {
                switch (msg.event) {
                case "initial_status":
                    serviceSection.updateState(msg.data)
                    keyboardSection.updateState(msg.data)
                    break
                case "scan_started":
                    keyboardSection.onScanStarted()
                    break
                case "passkey":
                    passkeyOverlay.show(msg.data.passkey)
                    break
                case "pair_complete":
                    passkeyOverlay.hide()
                    keyboardSection.onPairComplete(msg.data)
                    break
                case "pair_error":
                    passkeyOverlay.hide()
                    break
                case "layout_status":
                    keyboardSection.onLayoutStatus(msg.data.message)
                    break
                }
            }
        }
    }

    // Request tracking
    property int _nextId: 1
    property var _callbacks: ({})

    function sendRequest(action, params, callback) {
        var reqId = _nextId++
        if (callback) {
            _callbacks[reqId] = callback
        }
        var payload = JSON.stringify({
            "action": action,
            "params": params || {},
            "id": reqId
        })
        backend.sendMessage(1, payload)
    }

    // Background
    Rectangle {
        anchors.fill: parent
        color: "white"
    }

    // Close button
    Rectangle {
        id: closeBtn
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: 16
        width: 64
        height: 64
        radius: 32
        color: closeMa.pressed ? "black" : "white"
        border.color: "black"
        border.width: 3
        z: 100

        Text {
            text: "✕"
            font.pixelSize: 28
            font.bold: true
            color: closeMa.pressed ? "white" : "black"
            anchors.centerIn: parent
        }

        MouseArea {
            id: closeMa
            anchors.fill: parent
            onClicked: root.close()
        }
    }

    // Title
    Text {
        id: title
        text: "MoveWriter"
        font.pixelSize: 48
        font.bold: true
        color: "black"
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.margins: 32
    }

    // Scrollable content
    Flickable {
        id: flickable
        anchors.top: title.bottom
        anchors.topMargin: 16
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 32
        contentHeight: contentCol.height
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        Column {
            id: contentCol
            width: parent.width
            spacing: 24

            ServiceSection {
                id: serviceSection
                width: parent.width
            }

            KeyboardSection {
                id: keyboardSection
                width: parent.width
            }
        }
    }

    // Passkey overlay (full-screen)
    PasskeyOverlay {
        id: passkeyOverlay
        anchors.fill: parent
        z: 50
    }

    // Initial state arrives via the "initial_status" event the backend
    // pushes when it receives SYS_NEW_FRONTEND. No explicit get_status
    // request needed — that races with the socket handshake and would
    // fire before the backend is connected.
}
