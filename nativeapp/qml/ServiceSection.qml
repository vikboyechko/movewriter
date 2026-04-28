import QtQuick 2.15
import "components"

// Bluetooth Service management — Enable/Disable the on-device keyboard stack.
//
// No manual xochitl restart; if BT state changes cause xochitl to hang,
// the stock watchdog + OnFailureJobMode=fail drop-in handle recovery with
// a brief flicker.
Card {
    id: serviceCard
    height: serviceCol.height + padding * 2

    property bool serviceInstalled: false
    property bool busy: false
    property string statusText: ""

    function updateState(data) {
        serviceInstalled = !!data.service_installed
        statusText = ""
    }

    Column {
        id: serviceCol
        width: parent.width
        spacing: 16

        Row {
            spacing: 12
            StatusDot {
                status: serviceCard.busy ? "running"
                    : serviceCard.serviceInstalled ? "done" : "pending"
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                text: "Bluetooth Service"
                font.pixelSize: 36
                font.bold: true
                color: "black"
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        Text {
            visible: statusText.length > 0
            text: serviceCard.statusText
            font.pixelSize: 24
            color: "#222"
        }

        Text {
            width: parent.width
            text: "Enables your Move to remember and reconnect to a Bluetooth keyboard."
            font.pixelSize: 22
            color: "#222"
            wrapMode: Text.WordWrap
        }

        ActionButton {
            text: serviceCard.serviceInstalled ? "Disable" : "Enable"
            enabled: !serviceCard.busy
            onClicked: {
                serviceCard.busy = true
                var enabling = !serviceCard.serviceInstalled
                var action = enabling ? "install_service" : "uninstall_service"
                serviceCard.statusText = enabling ? "Enabling..." : "Disabling..."
                sendRequest(action, {}, function(resp) {
                    serviceCard.busy = false
                    if (resp.ok) {
                        serviceCard.serviceInstalled = !!resp.data.service_installed
                        serviceCard.statusText = serviceCard.serviceInstalled
                            ? "Enabled" : "Disabled"
                    } else {
                        serviceCard.statusText = "Error: " + (resp.error || "Unknown")
                    }
                })
            }
        }
    }
}
