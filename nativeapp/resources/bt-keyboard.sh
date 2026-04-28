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

try_connect() {
    MAC="$1"
    # Trust first so BlueZ auto-accepts
    bluetoothctl trust "$MAC" 2>/dev/null

    # BLE keyboards require a scan before connect — without it, bluez doesn't
    # know the device is nearby and connect fails silently
    (echo "scan on"; sleep 5; echo "scan off") | bluetoothctl >/dev/null 2>&1
    sleep 1

    # Re-pair with NoInputNoOutput agent (pairing data is volatile on the Move)
    bluetoothctl <<EOF
agent NoInputNoOutput
default-agent
pair $MAC
EOF
    sleep 2

    # Connect with timeout — BLE connect can hang indefinitely
    bluetoothctl connect "$MAC" >/dev/null 2>&1 &
    CPID=$!
    sleep 5
    kill $CPID 2>/dev/null
    wait $CPID 2>/dev/null
}

is_connected() {
    MAC="$1"
    bluetoothctl info "$MAC" 2>/dev/null | grep -q "Connected: yes"
}

# Initial keyboard connection (with retries, keyboard may take a moment)
if [ -f "$MAC_FILE" ]; then
    MAC=$(cat "$MAC_FILE")
    for i in 1 2 3 4 5 6 7 8; do
        try_connect "$MAC"
        sleep 2
        if is_connected "$MAC"; then
            break
        fi
        sleep 3
    done
fi

# ── Monitor loop ──────────────────────────────────────────
# Check keyboard connection periodically and reconnect if dropped

while true; do
    sleep "$RECONNECT_INTERVAL"
    if [ -f "$MAC_FILE" ]; then
        MAC=$(cat "$MAC_FILE")
        if ! is_connected "$MAC"; then
            try_connect "$MAC"
        fi
    fi
done
