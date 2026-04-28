# MoveWriter Native

Native on-device app for configuring Bluetooth keyboards on the reMarkable Move, running inside xochitl via the XOVI/AppLoad framework. **Working on firmware 3.22 and 3.26** as of v2.0.

## Target Device

- **Model**: reMarkable Chiappa (reMarkable Move)
- **Tested firmware**: 3.22.0.68, 3.26.0.68 (both working with current Vellum packages)
- **OS**: BusyBox-based Linux (NOT full GNU coreutils)
- **Runtime**: xochitl Qt 6 + AppLoad extension
- **Main app**: xochitl (systemd service) — this app runs INSIDE it

## DO NOT (hard-won lessons — read first)

These changes broke pair / froze the device / caused factory reset. Don't repeat them.

1. **DO NOT restart `bt-keyboard.service` after `_action_scan_devices`.** The service's setup phase runs `systemctl restart bluetooth`, which clears BlueZ's device cache. The just-scanned device becomes "not available" by pair time. The service is restarted ONLY in the pair/unpair flows (after the operation completes). If the user cancels scan, the service stays stopped until next pair/unpair/app-reopen. Acceptable trade-off.
2. **DO NOT add bluetoothctl commands before `pair_interactive` in `pair_and_connect`.** Each `bluetoothctl X` invocation eats time from the ~60s window xochitl can stay alive during BT operations before the watchdog fires. Keep `pair_and_connect` minimal: `remove(old)` → `pair_interactive` → `trust` → `connect`. Identical to desktop.
3. **DO NOT use heredoc for bluetoothctl pair.** `bluetoothctl <<EOF agent on … EOF` fails: agent registration emits "Failed to register agent object" because there's no TTY. Use `pty.openpty()` + `subprocess.Popen(stdin=slave_fd, …)`.
4. **DO NOT add `LEAutoSecurity=false` / `ReconnectUUIDs=HID` to `/etc/bluetooth/*.conf`.** These were suggested by a community fix for niche BLE keyboard issues. They cause inconsistent behavior for normal Apple/BOOX keyboards and persist in volatile `/etc` until reboot.
5. **DO NOT replace `try_connect` (trust+scan+pair+connect) with the user-suggested `clean_connect`** that does `systemctl restart bluetooth` on every reconnect attempt. Frequent bluetoothd restarts cause xochitl to hang from D-Bus signal floods.
6. **DO NOT release `wake_unlock` during BT off toggle.** Causes immediate device sleep. We removed the BT on/off toggle from the native app entirely; the service's `ExecStopPost` handles it correctly.
7. **DO NOT write `[Unit]` sections with cross-unit dependencies (After=, Requires=, Wants=) to persistent rootfs systemd overrides.** A bad dependency caused a factory reset on 2026-03-24. `[Unit]` blocks are safe ONLY for resetting/disabling existing settings (e.g., `OnFailure=`, `JobTimeoutSec=0`).
8. **DO NOT scp through `/tmp` with a separate `mv`.** If scp fails partially or hits a host-key prompt, you can land a 0-byte file at the destination. Always scp directly to the final path.

## Architecture

```
┌─────────────────────────────────┐
│         xochitl (Qt 6)          │
│  ┌───────────────────────────┐  │
│  │   QML Frontend (AppLoad)  │  │
│  │   - ServiceSection        │  │
│  │   - KeyboardSection       │  │
│  │   - PasskeyOverlay        │  │
│  └───────────┬───────────────┘  │
│              │ AF_UNIX socket   │
│              │ (SOCK_SEQPACKET) │
│  ┌───────────┴───────────────┐  │
│  │   Python Backend          │  │
│  │   - bluetooth.py          │  │
│  │   - service.py            │  │
│  │   - layout_patcher.py     │  │
│  │   - config.py             │  │
│  └───────────────────────────┘  │
└─────────────────────────────────┘
```

- QML frontend runs inside xochitl's Qt runtime via AppLoad
- Python backend launched as subprocess, communicates via AppLoad's Unix socket protocol
- Backend runs as root — direct access to bluetoothctl, systemctl, filesystem
- No SSH needed — everything is local subprocess/file operations

## Project Structure

```
manifest.json                    → AppLoad app manifest (entry MUST have leading slash)
resources.rcc                    → Compiled QML resources (built by build.sh)
qml/
  main.qml                      → Root: AppLoad integration, message routing
  ServiceSection.qml             → Install/uninstall BT service
  KeyboardSection.qml            → Scan, pair, layout, reconnect, unpair
  PasskeyOverlay.qml             → Passkey display during pairing
  components/
    Card.qml                     → Bordered card container
    StatusDot.qml                → Status indicator
    ActionButton.qml             → High-contrast e-ink button
    DeviceList.qml               → BT device ListView
  application.qrc                → Qt resource collection (prefix "/" with qml/ aliases)
backend/
  entry                          → Shell shim: mounts /opt, cd to app root, runs python3 -m backend.main
  main.py                        → Socket server + message router
  protocol.py                    → AppLoad socket protocol handler
  bluetooth.py                   → BT operations (subprocess-based)
  service.py                     → Service installer (local file ops)
  layout_patcher.py              → Binary patching (local I/O)
  config.py                      → Config persistence
tools/
  generate_qmap.py               → Layout mapping data (from movewriterapp)
resources/
  bt-keyboard.sh                 → Setup + monitor script (from movewriterapp)
  remarkable-bt-keyboard.service → systemd service (from movewriterapp)
build.sh                         → Compiles QML → resources.rcc
install.sh                       → Deploys to device via SCP
```

## CRITICAL: Device Safety Rules

**NEVER write `[Unit]` sections (After=, Requires=) to persistent rootfs systemd overrides.** A bad dependency prevents xochitl from starting, which crashes USB networking and makes SSH unreachable. This caused a factory reset on 2026-03-24.

- Only `[Service] Environment=` lines are safe in persistent overrides (bad env vars are ignored; xochitl still starts)
- Always test systemd changes in volatile `/etc` first
- Before any persistent rootfs write, ask: "if this is wrong, can I still SSH in to fix it?"
- The `/home` encrypted disk mounts AFTER xochitl starts on 3.26 — do NOT try to fix this with `Requires=home.mount`

## XOVI/AppLoad Setup (Firmware 3.22)

### Prerequisites Installation Order

```sh
# 1. rmpp-entware (opkg package manager)
wget --no-check-certificate -O- https://raw.githubusercontent.com/hmenzagh/rmpp-entware/main/rmpp_entware.sh | bash -s -- --force

# 2. Python 3
export PATH=/opt/bin:/opt/sbin:$PATH
opkg update && opkg install python3

# 3. Vellum (reMarkable package manager)
wget --no-check-certificate -O /tmp/bootstrap.sh https://github.com/vellum-dev/vellum-cli/releases/latest/download/bootstrap.sh && bash /tmp/bootstrap.sh

# 4. XOVI + AppLoad + extensions (via Vellum — works on 3.22-3.25)
vellum add xovi
vellum add appload        # also installs xovi-extensions + qt-resource-rebuilder
vellum add xovi-extensions
```

### Entware/XOVI glibc Conflict

**Critical:** Entware installs glibc 2.27 in `/opt/lib/`. The system has glibc 2.39. When `/opt` is mounted, the dynamic linker finds entware's old glibc first, causing `LD_PRELOAD` of `xovi.so` to fail with "cannot be preloaded".

**Fix:** Unmount `/opt` before starting XOVI, then remount after:
```sh
umount /opt 2>/dev/null
bash /home/root/xovi/start
sleep 3
mount -a 2>/dev/null
```

The `backend/entry` script handles this for the Python process by remounting `/opt` before launching.

### Hashtable Rebuild

The Vellum-installed rebuild script (`xovi/rebuild_hashtable`) is interactive (has `read -p`). Run non-interactively:

```sh
# Must unmount /opt first to avoid glibc conflict
umount /opt 2>/dev/null
systemctl stop xochitl
sleep 2
kill $(pidof xochitl) 2>/dev/null
mkdir -p /home/root/xovi/exthome/qt-resource-rebuilder
rm -f /home/root/xovi/exthome/qt-resource-rebuilder/hashtab

QMLDIFF_HASHTAB_CREATE=/home/root/xovi/exthome/qt-resource-rebuilder/hashtab \
  QML_DISABLE_DISK_CACHE=1 \
  LD_PRELOAD=/home/root/xovi/xovi.so \
  /usr/bin/xochitl 2>&1 | while IFS= read line; do
    echo "$line"
    case "$line" in *"Hashtab saved"*) kill $(pidof xochitl) 2>/dev/null; break;; esac
done

systemctl start xochitl
```

### XOVI Activation

Run with `/opt` unmounted:
```sh
umount /opt 2>/dev/null
bash /home/root/xovi/start
sleep 3
mount -a 2>/dev/null
```

This creates tmpfs-mounted overrides in `/etc/systemd/system/xochitl.service.d/` and restarts xochitl with XOVI loaded.

**This is volatile** — lost when xochitl restarts (sleep/wake, reboot). Must re-run after each restart. A proper autostart service is needed for persistence (TODO).

### App Directory

With Vellum's XOVI start script, the AppLoad app directory is:
```
/home/root/xovi/services/xochitl.service/exthome/appload/
```
(NOT `/home/root/xovi/exthome/appload/` — XOVI_ROOT is set per-service by the start script)

## AppLoad Integration Details

### Manifest

The manifest `entry` field MUST have a **leading slash**:
```json
{
  "name": "MoveWriter",
  "id": "movewriter",
  "loadsBackend": true,
  "entry": "/qml/main.qml",
  "supportsScaling": true
}
```
Without the leading slash, AppLoad concatenates its random prefix directly with the path, breaking the resource lookup.

### QML Resources (resources.rcc)

QML files must be compiled into `resources.rcc` using Qt's `rcc` tool:
```sh
rcc --binary -o resources.rcc qml/application.qrc
```

The `application.qrc` uses prefix `/` with `qml/` aliases:
```xml
<qresource prefix="/">
    <file alias="qml/main.qml">main.qml</file>
    ...
</qresource>
```

On Mac, `rcc` is at: `/opt/homebrew/Cellar/qtbase/*/share/qt/libexec/rcc` (install via `brew install qt@6`).

**AppLoad caches resources.rcc** — after updating it, must restart xochitl (not just reopen the app) for changes to take effect.

### QML Root Component

Must use AppLoad's QML API, NOT raw signals:
```qml
import QtQuick 2.15
import net.asivery.AppLoad 1.0

Item {
    id: root
    anchors.fill: parent
    signal close()
    function unloading() { backend.terminate() }

    AppLoad {
        id: backend
        applicationID: "movewriter"
        onMessageReceived: function(type, contents) {
            var msg = JSON.parse(contents)
            // handle msg...
        }
    }

    function sendRequest(action, params, callback) {
        var payload = JSON.stringify({action: action, params: params, id: nextId++})
        backend.sendMessage(1, payload)  // note: sendMessage, NOT sendMesssage (triple s)
    }
}
```

### How AppLoad Finds the App

AppLoad appears in the **hamburger menu (☰)**, not the sidebar. Tap ☰ → AppLoad → MoveWriter.

## AppLoad Socket Protocol

Communication uses AF_UNIX SOCK_SEQPACKET. **Header and payload are sent as SEPARATE datagrams:**

```
recv() #1: 8-byte header → struct.pack('<II', msg_type, length)
recv() #2: payload bytes (length from header)
```

This is critical — the Rust reference client confirms this. Each `recv()` gets exactly one datagram.

- Message types: REQUEST(1), RESPONSE(2), EVENT(3)
- System messages: TERMINATE(0xFFFFFFFF), NEW_FRONTEND(0xFFFFFFFE) — these also have a 1-byte payload datagram to consume
- Backend sends responses the same way: header datagram then payload datagram

### Initial Status Push

The QML `Component.onCompleted` fires BEFORE the backend socket connects, so the initial `get_status` request is lost. Fix: the backend pushes an `initial_status` event when it receives `SYS_NEW_FRONTEND`.

## Pair Flow — What Works (read before touching pair code)

### The minimal `pair_and_connect` (DO NOT EXPAND)

```python
def pair_and_connect(mac, old_mac=None, passkey_callback=None):
    if old_mac and old_mac.lower() != mac.lower():
        remove(old_mac)
    pair_interactive(mac, passkey_callback=passkey_callback)
    trust(mac)
    connect(mac)
    if not get_connection_status(mac):
        raise RuntimeError(...)
```

Identical to the desktop app's pair_and_connect. Minimal. Reliable.

I tried adding `bluetoothctl pairable on / power on / scan / trust mac` before `pair_interactive` to "make pair more robust". Each invocation took 1-7 seconds. The cumulative pre-pair delay (and BT cache disturbance from scan) broke pair. **Don't add these.**

### Action flow

```python
_action_pair_keyboard:
    _stop_bt_service()              # service stops; pair owns the BT stack
    try:
        pair_and_connect(...)        # the minimal flow above
    except Exception:
        _send_event("pair_error")    # tells UI to hide passkey overlay
        _start_bt_service()          # resume reconnect loop
        raise
    save_keyboard_mac(mac)
    _start_bt_service()              # always restart on success
    _send_event("pair_complete", ...)
```

`_action_scan_devices` only does `_stop_bt_service()`. It does NOT restart the service after — that would clear the BlueZ cache before pair runs.

### `pair_interactive` uses pty (not heredoc)

```python
master, slave = pty.openpty()
proc = subprocess.Popen(["bluetoothctl"], stdin=slave, stdout=slave, stderr=slave, close_fds=True)
os.close(slave)
# read/write via master_fd, parse output for passkey/PIN/result
```

Heredoc-based stdin (`bluetoothctl <<EOF … EOF`) fails: agent registration silently fails ("Failed to register agent object") because there's no TTY, so PIN-based pairs can't complete.

### Why pair_interactive sometimes flickers xochitl

When pair runs while the native app's QML+backend is loaded, BlueZ emits D-Bus signals that xochitl's `epaperkeyboardhandler` chokes on. xochitl's event loop blocks. Watchdog fires after ~60s, xochitl is killed, restart by systemd, screen goes black ~10s, comes back.

Pre-regression behavior: pair completed in 5-10s for already-bonded devices and 20-40s for fresh pairs. xochitl might still hang on the BT signal cascade afterward, but the pair was already done in BlueZ. Bonding persists. User sees flicker, then keyboard works.

This is firmware behavior we can't fix. Our job is to make the flicker survivable.

## xochitl Crash Protection Stack

All three pieces must be in place. Without them, an xochitl hang during pair → reboot loop → device freeze → hard reboot required.

### 1. Stock watchdog (don't override)

xochitl ships with `WatchdogSec=60s`. Leave it. Detects xochitl hangs.

### 2. Drop-in: `/usr/lib/systemd/system/xochitl.service.d/zz-movewriter-overrides.conf`

```ini
[Unit]
OnFailure=
OnFailureJobMode=fail
JobTimeoutSec=0
StartLimitIntervalSec=0
```

- **`OnFailureJobMode=fail` is THE critical fix.** When xochitl fails, systemd tries to queue `emergency.target`. With `replace` mode (default), emergency.target replaces multi-user.target → all services stop → device frozen. With `fail` mode, queueing emergency.target FAILS because of conflicts with the running multi-user.target → emergency doesn't activate → `Restart=on-failure` brings xochitl back cleanly.
- **`OnFailure=` (empty) does NOT actually clear the inherited list.** `systemctl show xochitl | grep OnFailure` still shows `emergency.target remarkable-fail.service`. We tried; it's a systemd quirk. The `JobMode=fail` line is what actually saves us.
- **`JobTimeoutSec=0`** removes a 60s job timeout that another reMarkable drop-in adds.
- **`StartLimitIntervalSec=0`** removes the rate limit (default: 4 restarts per 10 min). Without this, frequent flickers hit the limit and systemd refuses to restart xochitl → device stuck in emergency mode → hard reboot needed.

The filename starts with `zz-` so it sorts AFTER other drop-ins and is applied last (drop-ins are loaded alphabetically across all dirs combined).

### 3. Drop-in: `/usr/lib/systemd/system/rm-emergency.service.d/zz-movewriter.conf`

```ini
[Service]
ExecStart=
ExecStart=/bin/sh -c 'if [ "$(cat /sys/devices/platform/lpgpr/swu_applied 2>/dev/null)" = "1" ]; then /usr/sbin/rm-emergency.sh; else echo "MoveWriter: suppressed emergency reboot (no OTA pending)" > /dev/kmsg; fi'
```

reMarkable's `/usr/sbin/rm-emergency.sh` always calls `reboot` at the end. Even when our `OnFailureJobMode=fail` blocks the emergency.target activation, if anything else triggers rm-emergency.service we'd reboot. This drop-in replaces the script with a noop unless an OTA partition swap is pending.

### Result: hang → flicker, not freeze

```
xochitl hangs (BT signals during pair)
  → 60s later: watchdog fires, SIGABRT
  → stop-sigterm timeout, SIGKILL
  → service marked Failed
  → OnFailure tries to queue emergency.target → JobMode=fail rejects
  → Restart=on-failure brings xochitl back
  → ~10s screen flicker, device alive
```

## Filesystem Persistence on 3.26

```
/etc                       overlay, upperdir=/var/volatile/lib  ← VOLATILE
/var/lib                   overlay, upperdir=/var/volatile/lib  ← VOLATILE
/var/lib/bluetooth         /dev/mapper/home-encrypted-disk      ← PERSISTENT
/var/lib/remarkable        /dev/mapper/persist (read-only)
/usr/lib                   read-only image, remountable rw
/home/root                 persistent
```

**`/var/lib/bluetooth` is PERSISTENT** on 3.26 (mounted from the encrypted home disk). Bonding data survives reboots. Earlier docs incorrectly said it was volatile. Don't re-pair on every boot — `bluetoothctl connect MAC` works for already-bonded devices.

`/etc` is volatile — `bt-keyboard.sh` restores `/etc/bluetooth/input.conf` settings on every service start. Same for any other `/etc` config.

## bt-keyboard.sh

The simple version (current). Setup phase + monitor loop. Don't replace with `clean_connect`-style aggressive bluetoothd restarts.

Key setup steps:
1. `modprobe -r btnxpuart && modprobe btnxpuart && modprobe uhid` — clean reload
2. Restore `/etc/bluetooth/input.conf`: `UserspaceHID=true`, `ClassicBondedOnly=false`
3. `systemctl restart bluetooth` (so input.conf takes effect)
4. `bluetoothctl power on` (with retry loop)
5. **`bluetoothctl pairable on`** — 3.26 default is `Pairable: no`, which silently fails outgoing pair requests
6. `echo user.lock >> /sys/power/wake_lock`
7. Initial connection retries via `try_connect` (trust → scan → pair-with-AlreadyExists-OK → connect)
8. Monitor loop every 10s

`try_connect` does a 5-second internal scan before pair. This is essential — without it, BlueZ may not have the device cached at pair time.

## Layout Change Auto-Restart

Layout patches `libepaper.so` which xochitl has loaded in memory. To take effect, xochitl must restart. We do this from the backend via:

```python
subprocess.Popen(
    ["systemd-run", "--on-active=3s", "--collect", "/bin/systemctl", "restart", "xochitl"],
    start_new_session=True,
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
```

`systemd-run --on-active=Ns --collect` creates a transient timer unit that fires after N seconds. The timer is decoupled from our process tree, so when xochitl (and our backend) restart, the scheduled restart still fires correctly.

**Don't use shell-backgrounded `(sleep 1 && systemctl restart xochitl) &`.** When our process dies, the backgrounded subshell may be killed too (depending on signal handling), causing the restart to never happen.

## Adapted from movewriterapp

| File | Source | Key changes |
|------|--------|-------------|
| `backend/bluetooth.py` | `core/bluetooth.py` | ssh.exec → subprocess.run, Paramiko channel → pty.openpty |
| `backend/service.py` | `core/service_installer.py` | ssh.upload → shutil.copy/Path.write, ssh.exec → subprocess |
| `backend/layout_patcher.py` | `core/layout_patcher.py` | ssh.download/upload_bytes → Path.read/write_bytes, no xochitl restart |
| `backend/config.py` | `core/config.py` | Removed SSH fields (ip, password_b64) |

## Key Differences from Desktop App

### No xochitl Restart for Layout Changes
The app runs inside xochitl via AppLoad. Restarting xochitl kills the app. Layout patches are written to disk and take effect after reboot.

### No SSH
All operations are local subprocess calls and direct file I/O.

### E-ink Design
- Black-on-white only, no animations, no transparency
- Large tap targets (72px buttons, 36px headings, 24-28px body text)
- Minimize redraws

## Deployment

Build and deploy:
```sh
# Build resources.rcc on Mac
/opt/homebrew/Cellar/qtbase/*/share/qt/libexec/rcc --binary -o resources.rcc qml/application.qrc

# Deploy to device
DEST="/home/root/xovi/services/xochitl.service/exthome/appload/movewriter"
scp resources.rcc manifest.json root@10.11.99.1:"$DEST/"
scp -r backend/ tools/ resources/ root@10.11.99.1:"$DEST/"
ssh root@10.11.99.1 "chmod +x $DEST/backend/entry"

# Restart XOVI (required after resources.rcc changes)
ssh root@10.11.99.1 "umount /opt 2>/dev/null; bash /home/root/xovi/start; sleep 3; mount -a 2>/dev/null"
```

## Firmware 3.26 Status (WORKING)

As of v2.0, 3.26 is fully supported via Vellum:
- XOVI v0.3.3, AppLoad v0.5.0, xovi-extensions v18.0.0-r2
- Auto-update prevention: disable in Move's settings; despite the toggle, the Move force-updated 3.22 → 3.26 once. Users should be warned in the UI.
- `/home` mount timing on 3.26: the encrypted home disk mounts AFTER xochitl starts. The autostart script (`/usr/lib/movewriter-xovi-autostart.sh`) polls for `/home/root/xovi` for up to 20s before activating XOVI. **NEVER add `Requires=home.mount`** to persistent overrides — caused the factory reset.

## XOVI Reboot Persistence (SOLVED)

Autostart service at `/usr/lib/systemd/system/movewriter-xovi.service` runs a script at `/usr/lib/movewriter-xovi-autostart.sh` on every boot. The script:

1. Polls for `/home/root/xovi` (up to 20 seconds) — does NOT use `Requires=home.mount`
2. Unmounts `/opt` (entware glibc conflict)
3. Runs `bash /home/root/xovi/start` (creates tmpfs overlays, restarts xochitl with XOVI)
4. Remounts `/opt`
5. Logs to `/home/root/.movewriter/xovi-autostart.log`

**Why this is safe:**
- No `[Unit]` dependencies — if `/home` never mounts, script exits silently, xochitl runs stock
- Service is `Type=oneshot` with `RemainAfterExit=yes`
- Script and service file are on persistent rootfs (`/usr/lib/`) so they're available before `/home` mounts
- If the script crashes, xochitl is already running — no crash loop possible

**Tested:** Reboot on 3.26 → XOVI activates in ~3 seconds → AppLoad + MoveWriter available.

## Known Issues / TODO

- **Auto-update prevention**: The Move force-updated 3.22 → 3.26 once despite auto-update being disabled. UI now warns users to disable auto-updates.
- **Pair flickers xochitl**: Firmware bug — BT D-Bus signals during pair hang xochitl when AppLoad app is loaded. Crash protection turns this into a recoverable ~10s flicker. The pair itself completes correctly before the hang.
- **Pair requires keyboard in active pairing mode**: Apple keyboards must have LED actively blinking. Just being "on" isn't enough.

## BusyBox Compatibility

Same as movewriterapp — see that CLAUDE.md for details. The Move uses BusyBox, NOT GNU coreutils.

## Development Notes

- `tools/generate_qmap.py` is copied from movewriterapp — provides layout mapping data
- `resources/` files are identical copies from movewriterapp
- Backend can be partially tested on Mac by mocking subprocess calls
- QML can be previewed with `qmlscene` but AppLoad integration only works on device
- After QML changes, must rebuild `resources.rcc`, deploy, AND restart xochitl (AppLoad caches RCC)
- Backend Python changes take effect on next app open (no xochitl restart needed)
