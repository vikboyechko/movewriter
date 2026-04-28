#!/bin/sh
# Build MoveWriter Native — compile QML resources into resources.rcc
set -e
cd "$(dirname "$0")"

echo "Compiling QML resources..."
rcc --binary -o resources.rcc qml/application.qrc

echo "Built resources.rcc ($(wc -c < resources.rcc) bytes)"
