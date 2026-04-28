#!/bin/sh
# Deploy MoveWriter Native to reMarkable Move via SCP
set -e

DEVICE="${1:-10.11.99.1}"
DEST="/home/root/xovi/exthome/appload/movewriter"

echo "Deploying to $DEVICE:$DEST ..."

# Create destination directory
ssh root@"$DEVICE" "mkdir -p $DEST/backend $DEST/qml/components $DEST/resources $DEST/tools"

# Copy manifest and icon
scp manifest.json root@"$DEVICE":"$DEST/"
[ -f icon.png ] && scp icon.png root@"$DEVICE":"$DEST/"

# Copy QML files
scp qml/main.qml qml/ServiceSection.qml qml/KeyboardSection.qml qml/PasskeyOverlay.qml root@"$DEVICE":"$DEST/qml/"
scp qml/components/*.qml root@"$DEVICE":"$DEST/qml/components/"
scp qml/application.qrc root@"$DEVICE":"$DEST/qml/"

# Copy backend files
scp backend/entry backend/main.py backend/protocol.py backend/bluetooth.py \
    backend/service.py backend/layout_patcher.py backend/config.py \
    root@"$DEVICE":"$DEST/backend/"

# Copy tools (layout data used by layout_patcher)
scp tools/generate_qmap.py root@"$DEVICE":"$DEST/tools/"

# Copy resources
scp resources/bt-keyboard.sh resources/remarkable-bt-keyboard.service root@"$DEVICE":"$DEST/resources/"

# Make entry script executable
ssh root@"$DEVICE" "chmod +x $DEST/backend/entry"

# Copy pre-built resources.rcc if it exists
[ -f resources.rcc ] && scp resources.rcc root@"$DEVICE":"$DEST/"

echo "Deployed successfully. Open AppLoad on device to launch MoveWriter."
