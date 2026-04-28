#!/bin/bash
# MoveWriter XOVI autostart — runs on boot from /usr/lib/systemd/system/movewriter-xovi.service.
#
# Safe by design: no [Unit] deps. If /home never mounts, script exits silently and
# stock xochitl keeps running. Do NOT add Requires=home.mount to the unit file —
# that caused a factory reset on 3.22.

LOGFILE=/home/root/.movewriter/xovi-autostart.log

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

log "autostart: done"
exit 0
