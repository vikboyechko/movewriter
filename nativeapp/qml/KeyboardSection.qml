import QtQuick 2.15
import "components"

// Keyboard management section
Card {
    id: kbCard
    height: kbCol.height + padding * 2

    property string kbMac: ""
    property string kbName: ""
    property string kbLayout: "US English"
    property bool kbConnected: false
    property bool scanning: false
    property bool pairing: false
    property bool busy: false
    property string statusText: ""
    property var layouts: []

    property bool showScan: kbMac === ""

    property string selectedMac: ""
    property string selectedName: ""

    function updateState(data) {
        kbMac = data.keyboard_mac || ""
        kbName = data.keyboard_name || ""
        kbLayout = data.keyboard_layout || "US English"
        kbConnected = !!data.keyboard_connected
        if (data.layouts) layouts = data.layouts
        showScan = kbMac === ""
        statusText = ""
    }

    function onScanStarted() {
        scanning = true
        statusText = "Scanning..."
    }

    function onPairComplete(data) {
        pairing = false
        kbMac = data.mac
        kbName = data.name
        kbConnected = true
        showScan = false
        statusText = "Paired and connected"
    }

    function onLayoutStatus(msg) {
        statusText = msg
    }

    Column {
        id: kbCol
        width: parent.width
        spacing: 16

        Row {
            spacing: 12
            StatusDot {
                status: kbCard.kbConnected ? "done"
                    : kbCard.kbMac !== "" ? "pending" : "pending"
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                text: "Keyboard"
                font.pixelSize: 36
                font.bold: true
                color: "black"
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        // ── Saved keyboard view ──────────────────────────
        Column {
            id: savedView
            visible: !kbCard.showScan
            width: parent.width
            spacing: 16

            Text {
                text: kbCard.kbName || kbCard.kbMac
                font.pixelSize: 28
                font.bold: true
                color: "black"
            }

            Row {
                spacing: 12
                StatusDot {
                    status: kbCard.kbConnected ? "done" : "error"
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    text: kbCard.kbConnected ? "Connected" : "Disconnected"
                    font.pixelSize: 24
                    color: "#222"
                    anchors.verticalCenter: parent.verticalCenter
                }
            }

            // Layout selector
            Row {
                spacing: 12
                Text {
                    text: "Layout:"
                    font.pixelSize: 24
                    color: "#222"
                    anchors.verticalCenter: parent.verticalCenter
                }
                ActionButton {
                    text: kbCard.kbLayout
                    onClicked: layoutPopup.visible = !layoutPopup.visible
                }
            }

            Text {
                width: parent.width
                text: "Changing layout will reboot your Move to take effect."
                font.pixelSize: 20
                color: "#222"
                wrapMode: Text.WordWrap
            }

            // Layout list popup
            Rectangle {
                id: layoutPopup
                visible: false
                width: parent.width
                height: 640
                border.color: "black"
                border.width: 2
                color: "white"
                z: 10

                ListView {
                    id: layoutListView
                    anchors.fill: parent
                    anchors.rightMargin: 12  // space for scrollbar
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    model: kbCard.layouts

                    delegate: Rectangle {
                        width: layoutListView.width
                        height: 64
                        color: modelData === kbCard.kbLayout ? "#e0e0e0" : "white"
                        border.color: "#ddd"
                        border.width: 1

                        Text {
                            text: modelData
                            font.pixelSize: 24
                            color: "black"
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left
                            anchors.leftMargin: 16
                        }

                        MouseArea {
                            anchors.fill: parent
                            onClicked: {
                                layoutPopup.visible = false
                                if (modelData !== kbCard.kbLayout) {
                                    kbCard.busy = true
                                    kbCard.statusText = "Applying layout..."
                                    sendRequest("set_layout", {"layout": modelData}, function(resp) {
                                        kbCard.busy = false
                                        if (resp.ok) {
                                            kbCard.kbLayout = modelData
                                            kbCard.statusText = resp.data.message || "Layout applied"
                                        } else {
                                            kbCard.statusText = "Error: " + (resp.error || "Unknown")
                                        }
                                    })
                                }
                            }
                        }
                    }
                }

                // Scrollbar indicator — visible whenever list exceeds popup height
                Rectangle {
                    id: scrollbarTrack
                    visible: layoutListView.contentHeight > layoutListView.height
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    anchors.margins: 2
                    width: 8
                    color: "#e0e0e0"

                    Rectangle {
                        width: parent.width
                        height: scrollbarTrack.height *
                            Math.min(1, layoutListView.height / Math.max(1, layoutListView.contentHeight))
                        y: scrollbarTrack.height *
                            (layoutListView.contentY /
                             Math.max(1, layoutListView.contentHeight))
                        color: "#222"
                    }
                }
            }

            Row {
                spacing: 12

                ActionButton {
                    text: "Change"
                    enabled: !kbCard.busy
                    onClicked: {
                        kbCard.showScan = true
                        kbCard.statusText = ""
                    }
                }

                ActionButton {
                    text: "Unpair"
                    enabled: !kbCard.busy
                    onClicked: {
                        kbCard.busy = true
                        kbCard.statusText = "Unpairing..."
                        sendRequest("unpair_keyboard", {}, function(resp) {
                            kbCard.busy = false
                            if (resp.ok) {
                                kbCard.kbMac = ""
                                kbCard.kbName = ""
                                kbCard.kbConnected = false
                                kbCard.showScan = true
                                kbCard.statusText = ""
                            } else {
                                kbCard.statusText = "Error: " + (resp.error || "Unknown")
                            }
                        })
                    }
                }
            }
        }

        // ── Scan view ────────────────────────────────────
        Column {
            id: scanView
            visible: kbCard.showScan
            width: parent.width
            spacing: 16

            Row {
                spacing: 12

                ActionButton {
                    text: kbCard.scanning ? "Scanning..." : "Scan for Keyboards"
                    enabled: !kbCard.scanning && !kbCard.pairing
                    onClicked: {
                        kbCard.scanning = true
                        kbCard.statusText = "Scanning for 15 seconds..."
                        deviceList.clear()
                        sendRequest("scan_devices", {"timeout": 15}, function(resp) {
                            kbCard.scanning = false
                            if (resp.ok) {
                                deviceList.setDevices(resp.data.devices)
                                kbCard.statusText = resp.data.devices.length
                                    + " device(s) found"
                            } else {
                                kbCard.statusText = "Scan error: " + (resp.error || "Unknown")
                            }
                        })
                    }
                }

                ActionButton {
                    text: "Cancel"
                    visible: kbCard.kbMac !== ""
                    enabled: !kbCard.scanning && !kbCard.pairing
                    onClicked: {
                        kbCard.showScan = false
                        kbCard.statusText = ""
                    }
                }
            }

            DeviceList {
                id: deviceList
                width: parent.width
                height: Math.min(count * 80, 800)
                visible: count > 0
                onDeviceSelected: function(mac, name) {
                    kbCard.selectedMac = mac
                    kbCard.selectedName = name
                }
            }

            ActionButton {
                text: kbCard.pairing ? "Pairing..." : "Pair Selected"
                visible: deviceList.selectedIndex >= 0
                enabled: !kbCard.pairing && !kbCard.scanning
                        && kbCard.selectedMac !== ""
                onClicked: {
                    kbCard.pairing = true
                    kbCard.statusText = "Pairing — this may take up to 30 seconds..."
                    sendRequest("pair_keyboard", {
                        "mac": kbCard.selectedMac,
                        "name": kbCard.selectedName
                    }, function(resp) {
                        kbCard.pairing = false
                        if (!resp.ok) {
                            kbCard.statusText = "Pair failed: " + (resp.error || "Unknown")
                        }
                    })
                }
            }
        }

        // Status text
        Text {
            visible: kbCard.statusText !== ""
            text: kbCard.statusText
            font.pixelSize: 22
            color: kbCard.statusText.indexOf("Error") >= 0
                || kbCard.statusText.indexOf("failed") >= 0 ? "#c00" : "#222"
            wrapMode: Text.WordWrap
            width: parent.width
        }
    }
}
