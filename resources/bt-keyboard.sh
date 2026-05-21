#!/bin/sh
# MoveWriter Bluetooth Keyboard Setup & Monitor
# Stored at /home/root/.movewriter/bt-keyboard.sh (persistent across reboots)
# Handles: module loading, input.conf restoration, BT setup, keyboard reconnection

MAC_FILE="/home/root/.movewriter-keyboard"
RECONNECT_INTERVAL=10

# ── Setup ──────────────────────────────────────────────────

# Load required kernel modules (force reload to ensure clean state)
modprobe -r btnxpuart 2>/dev/null
modprobe btnxpuart
modprobe uhid

# Fix bluetooth directory permissions
chmod 555 /etc/bluetooth

# Restore input.conf settings (lost on reboot due to /etc overlay)
sed -i '/^[# ]*UserspaceHID/d' /etc/bluetooth/input.conf
echo 'UserspaceHID=true' >> /etc/bluetooth/input.conf
sed -i '/^[# ]*ClassicBondedOnly/d' /etc/bluetooth/input.conf
echo 'ClassicBondedOnly=false' >> /etc/bluetooth/input.conf

# Remove Privacy setting if present — causes BLE connections to fail
# with le-connection-abort-by-local on the NXP controller
sed -i '/^[# ]*Privacy/d' /etc/bluetooth/main.conf 2>/dev/null

# Restart bluetooth so input.conf changes take effect
systemctl restart bluetooth
sleep 2

# Power on BT adapter with retry loop (controller may not be ready immediately)
for i in 1 2 3 4 5 6; do
    bluetoothctl power on 2>/dev/null && break
    sleep 2
done

# Make the adapter pairable — default on Move 3.26 is "Pairable: no"
# which makes outgoing pair requests time out silently.
bluetoothctl pairable on 2>/dev/null

# Set wake lock to prevent sleep during keyboard use
echo user.lock >> /sys/power/wake_lock

# ── Keyboard connect ──────────────────────────────────────

is_connected() {
    bluetoothctl info "$1" 2>/dev/null | grep -q "Connected: yes"
}

is_paired() {
    bluetoothctl info "$1" 2>/dev/null | grep -q "Paired: yes"
}

# Establish the bond for a keyboard that is not paired yet. This is the original
# scan + agent + pair flow. For a SAVED keyboard it almost never runs — pairing
# is normally done by the desktop/native-app pair flow — but it stays as a
# fallback in case the bond was somehow lost.
pair_unbonded() {
    MAC="$1"
    # BLE keyboards need a scan before the first pair so bluez sees them nearby.
    (echo "scan on"; sleep 5; echo "scan off") | bluetoothctl >/dev/null 2>&1
    sleep 1
    bluetoothctl <<EOF
agent NoInputNoOutput
default-agent
pair $MAC
EOF
    sleep 2
}

# Reconnect the saved keyboard WITHOUT disrupting an existing link.
#
# By the time this service runs the keyboard is already bonded — the bond in
# /var/lib/bluetooth is persistent on 3.26 — and BlueZ auto-connects bonded +
# trusted keyboards on its own, both at boot and when a BLE keyboard wakes from
# sleep and re-advertises. So for a bonded device we must NOT re-pair or run an
# active scan:
#   * re-pairing a live device tears the HID link down
#     (bluetoothd logs "No matching connection for device")
#   * an active "scan on" suspends BlueZ's passive background auto-connect
# We just keep it trusted (so BlueZ auto-accepts) and issue a plain connect as a
# nudge/safety-net when it is down. A plain connect is a quick no-op when the
# keyboard is asleep, and is what BR/EDR keyboards (e.g. BOOX) need to reconnect.
ensure_connected() {
    MAC="$1"
    is_connected "$MAC" && return 0

    bluetoothctl trust "$MAC" >/dev/null 2>&1

    if ! is_paired "$MAC"; then
        pair_unbonded "$MAC"
    fi

    # Plain connect with a timeout — connect can hang if the keyboard is asleep;
    # bail after a few seconds and let the next cycle (or BlueZ) retry.
    bluetoothctl connect "$MAC" >/dev/null 2>&1 &
    CPID=$!
    sleep 5
    kill $CPID 2>/dev/null
    wait $CPID 2>/dev/null
}

# Initial keyboard connection. BlueZ usually auto-connects a bonded keyboard
# within a few seconds of boot, so check first and only nudge if it is down.
if [ -f "$MAC_FILE" ]; then
    MAC=$(cat "$MAC_FILE")
    for i in 1 2 3 4 5 6 7 8; do
        is_connected "$MAC" && break
        ensure_connected "$MAC"
        sleep 3
    done
fi

# ── Monitor loop ──────────────────────────────────────────
# Reconnect if the link drops. ensure_connected is a no-op while connected, so
# this never disturbs a working keyboard.

while true; do
    sleep "$RECONNECT_INTERVAL"
    if [ -f "$MAC_FILE" ]; then
        MAC=$(cat "$MAC_FILE")
        ensure_connected "$MAC"
    fi
done
