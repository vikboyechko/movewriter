#!/bin/sh
# MoveWriter Native — Uninstall from reMarkable Move
# Usage: ./uninstall.sh [device_ip]
#
# Removes the MoveWriter app. Does NOT uninstall XOVI/AppLoad/Python
# (those are shared infrastructure other apps may use).
set -e

DEVICE="${1:-10.11.99.1}"
DEST="/home/root/xovi/exthome/appload/movewriter"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { printf "${GREEN}[✓]${NC} %s\n" "$1"; }
warn()  { printf "${YELLOW}[!]${NC} %s\n" "$1"; }
step()  { printf "\n${GREEN}──── %s ────${NC}\n" "$1"; }

run_on_device() {
    ssh root@"$DEVICE" "$@"
}

step "Uninstalling MoveWriter Native from $DEVICE"

# Stop the BT keyboard service if running
if run_on_device "systemctl is-active remarkable-bt-keyboard.service" >/dev/null 2>&1; then
    warn "Stopping BT keyboard service..."
    run_on_device "systemctl stop remarkable-bt-keyboard.service" 2>/dev/null || true
    run_on_device "systemctl disable remarkable-bt-keyboard.service" 2>/dev/null || true
fi

# Restore original libepaper.so if patched
if run_on_device "test -f /home/root/.movewriter/libepaper.so.orig"; then
    warn "Restoring original keyboard layout..."
    run_on_device "mount -o remount,rw / && cp /home/root/.movewriter/libepaper.so.orig /usr/lib/plugins/platforms/libepaper.so && mount -o remount,ro /" 2>/dev/null || true
fi

# Remove service files from persistent storage
if run_on_device "test -f /usr/lib/systemd/system/remarkable-bt-keyboard.service"; then
    warn "Removing service files..."
    run_on_device "mount -o remount,rw / && rm -f /usr/lib/systemd/system/remarkable-bt-keyboard.service /usr/lib/systemd/system/multi-user.target.wants/remarkable-bt-keyboard.service && mount -o remount,ro /" 2>/dev/null || true
    run_on_device "systemctl daemon-reload" 2>/dev/null || true
fi

# Remove movewriter data
run_on_device "rm -rf /home/root/.movewriter /home/root/.movewriter-keyboard /home/root/.movewriter-layout" 2>/dev/null || true
info "Cleaned up service and config files"

# Remove the app itself
if run_on_device "test -d $DEST"; then
    run_on_device "rm -rf $DEST"
    info "Removed app from $DEST"
else
    info "App directory already removed"
fi

step "Uninstall complete"
echo ""
echo "  MoveWriter has been removed from your Move."
echo "  XOVI, AppLoad, and Python were left in place."
echo ""
echo "  You may want to restart xochitl:"
echo "    ssh root@$DEVICE 'systemctl restart xochitl'"
echo ""
