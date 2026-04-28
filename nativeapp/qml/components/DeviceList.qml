import QtQuick 2.15

// ListView for scanned Bluetooth devices
ListView {
    id: deviceList

    property int selectedIndex: -1

    signal deviceSelected(string mac, string name)

    clip: true
    boundsBehavior: Flickable.StopAtBounds

    // Scrollbar
    Rectangle {
        id: scrollbar
        visible: deviceList.contentHeight > deviceList.height
        anchors.right: parent.right
        width: 6
        radius: 3
        color: "black"
        opacity: 0.5
        y: deviceList.height * deviceList.contentY / deviceList.contentHeight
        height: Math.max(40, deviceList.height * deviceList.height / deviceList.contentHeight)
        z: 10
    }

    model: ListModel { id: deviceModel }

    delegate: Rectangle {
        width: deviceList.width
        height: 80
        color: index === deviceList.selectedIndex ? "#e0e0e0" : "white"
        border.color: "#ccc"
        border.width: index > 0 ? 1 : 0

        Column {
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left
            anchors.leftMargin: 16
            anchors.right: parent.right
            anchors.rightMargin: 16

            Text {
                text: model.name
                font.pixelSize: 28
                font.bold: true
                color: "black"
                elide: Text.ElideRight
                width: parent.width
            }
            Text {
                text: model.mac
                font.pixelSize: 20
                color: "#222"
            }
        }

        MouseArea {
            anchors.fill: parent
            onClicked: {
                deviceList.selectedIndex = index
                deviceList.deviceSelected(model.mac, model.name)
            }
        }
    }

    function setDevices(devices) {
        deviceModel.clear()
        selectedIndex = -1
        for (var i = 0; i < devices.length; i++) {
            deviceModel.append(devices[i])
        }
    }

    function clear() {
        deviceModel.clear()
        selectedIndex = -1
    }
}
