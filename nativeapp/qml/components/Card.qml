import QtQuick 2.15

// Bordered card container for e-ink display
Rectangle {
    id: card
    color: "white"
    border.color: "black"
    border.width: 2
    radius: 8

    default property alias content: inner.data

    property int padding: 24

    Item {
        id: inner
        anchors.fill: parent
        anchors.margins: card.padding
    }
}
