#!/bin/bash
# MoveWriter XOVI autostart — runs on boot from /usr/lib/systemd/system/movewriter-xovi.service.
#
# Safe by design: no [Unit] deps. If /home never mounts, script exits silently and
# stock xochitl keeps running. Do NOT add Requires=home.mount to the unit file —
# that caused a factory reset on 3.22.

LOGFILE=/home/root/.movewriter/xovi-autostart.log
# Failsafe counter: bumped before each activation attempt, reset to 0 by the
# delayed health check (below) once xochitl is confirmed healthy. If activation
# keeps failing (xochitl crash-loops with XOVI on a firmware it doesn't support),
# we stop activating after MAX_ATTEMPTS boots and stay on stock so the device
# stays usable. A reinstall clears it (and re-checks compat + rebuilds hashtab).
ATTEMPTS_FILE=/home/root/.movewriter/xovi-activation-attempts
MAX_ATTEMPTS=3

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOGFILE" 2>/dev/null || true
}

# Poll for /home/root/xovi — /home is an encrypted volume that mounts after xochitl starts.
i=0
while [ $i -lt 20 ]; do
    if [ -d /home/root/xovi ]; then
        break
    fi
    sleep 1
    i=$((i + 1))
done

if [ ! -d /home/root/xovi ]; then
    # /home never mounted — stock xochitl will keep running, exit silently.
    exit 0
fi

mkdir -p /home/root/.movewriter 2>/dev/null || true
log "autostart: found /home/root/xovi"

# Failsafe: if XOVI activation has failed repeatedly (xochitl crash-looping on a
# firmware XOVI doesn't support), stop trying and stay on stock — xochitl is
# already running stock at this point, so the device stays usable.
ATTEMPTS=$(cat "$ATTEMPTS_FILE" 2>/dev/null)
case "$ATTEMPTS" in ''|*[!0-9]*) ATTEMPTS=0 ;; esac
if [ "$ATTEMPTS" -ge "$MAX_ATTEMPTS" ]; then
    log "autostart: XOVI activation failed ${ATTEMPTS}x — staying on stock (reinstall MoveWriter to retry)"
    exit 0
fi
echo $((ATTEMPTS + 1)) > "$ATTEMPTS_FILE" 2>/dev/null || true

# Entware's /opt has glibc 2.27 which shadows the system glibc 2.39.
# XOVI's start script invokes tools that break if /opt is mounted.
OPT_WAS_MOUNTED=0
if mountpoint -q /opt 2>/dev/null; then
    OPT_WAS_MOUNTED=1
    umount /opt 2>/dev/null && log "autostart: unmounted /opt"
fi

# Activate XOVI — sets up tmpfs overlays and restarts xochitl with XOVI loaded.
export XOVI_ROOT=/home/root/xovi
bash /home/root/xovi/start >> "$LOGFILE" 2>&1 || log "autostart: xovi/start exited non-zero"

# Remount /opt so entware is available for the native app backend.
if [ $OPT_WAS_MOUNTED -eq 1 ]; then
    mount --bind /home/root/.entware /opt 2>/dev/null && log "autostart: remounted /opt"
fi

# Decoupled health check: 60s from now, if xochitl is up and not crash-looping,
# reset the failsafe counter (activation succeeded). If it IS crash-looping with
# XOVI, revert to stock to break the loop and leave the counter so repeated
# failures eventually trip the MAX_ATTEMPTS guard. systemd-run survives this
# oneshot exiting; if unavailable, reset the counter (fail open to prior behavior).
systemd-run --on-active=60 --collect /bin/sh -c 'NR=$(systemctl show xochitl.service -p NRestarts --value 2>/dev/null); if pidof xochitl >/dev/null 2>&1 && [ "${NR:-0}" -lt 5 ]; then echo 0 > /home/root/.movewriter/xovi-activation-attempts; else bash /home/root/xovi/stock >/dev/null 2>&1; fi' >/dev/null 2>&1 || echo 0 > "$ATTEMPTS_FILE"

log "autostart: done"
exit 0
