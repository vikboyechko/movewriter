"""Install/uninstall MoveWriter Native (on-device app) via SSH.

Deploys XOVI + AppLoad + MoveWriter native app to the Move, plus a
persistent systemd drop-in that disables xochitl's watchdog (prevents
reboots during BT operations).

Source files for the native app live in the `nativeapp/` subfolder of
this repo (single source of truth). `native_app_root()` returns either
the in-repo path (running from source) or the PyInstaller bundle path
(running from a built binary).
"""
import os
import sys

# Paths on-device
DEST_DIR = "/home/root/xovi/exthome/appload/movewriter"
XOVI_DIR = "/home/root/xovi"
APPLOAD_DIR = "/home/root/xovi/extensions.d/appload"
WATCHDOG_DROPIN_DIR = "/usr/lib/systemd/system/xochitl.service.d"
WATCHDOG_DROPIN_PATH = f"{WATCHDOG_DROPIN_DIR}/zz-movewriter-overrides.conf"
AUTOSTART_SERVICE_PATH = "/usr/lib/systemd/system/movewriter-xovi.service"
AUTOSTART_SYMLINK_PATH = "/usr/lib/systemd/system/multi-user.target.wants/movewriter-xovi.service"
AUTOSTART_SCRIPT_PATH = "/usr/lib/movewriter-xovi-autostart.sh"
EMERGENCY_DROPIN_DIR = "/usr/lib/systemd/system/rm-emergency.service.d"
EMERGENCY_DROPIN_PATH = f"{EMERGENCY_DROPIN_DIR}/zz-movewriter.conf"

# vellum lives in /home/root/.vellum/bin and entware tools in /opt; the SSH exec
# is a non-login shell, so set PATH explicitly for every vellum invocation.
VELLUM_ENV = "export PATH=/opt/bin:/opt/sbin:/home/root/.vellum/bin:$PATH; "

# App layout (mirrors nativeapp/ subfolder structure)
APP_FILES = {
    "": ["manifest.json", "resources.rcc"],
    "backend": [
        "entry", "__init__.py", "main.py", "protocol.py", "bluetooth.py",
        "service.py", "layout_patcher.py", "config.py",
    ],
    "qml": [
        "main.qml", "KeyboardSection.qml", "ServiceSection.qml",
        "PasskeyOverlay.qml", "application.qrc",
    ],
    "qml/components": [
        "ActionButton.qml", "Card.qml", "DeviceList.qml", "StatusDot.qml",
    ],
    "tools": ["__init__.py", "generate_qmap.py"],
    "resources": ["bt-keyboard.sh", "remarkable-bt-keyboard.service"],
}


def native_app_root():
    """Locate the native app source tree."""
    # Source checkout: nativeapp/ subfolder of this repo
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    in_repo = os.path.join(here, "nativeapp")
    if os.path.isdir(in_repo):
        return in_repo

    # PyInstaller bundle: stages the same nativeapp/ directory
    if getattr(sys, "_MEIPASS", None):
        bundled = os.path.join(sys._MEIPASS, "nativeapp")
        if os.path.isdir(bundled):
            return bundled

    raise RuntimeError(
        "Cannot locate MoveWriter native app source. "
        "Expected at nativeapp/ alongside core/."
    )


def _resources_dir():
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")


def is_installed(ssh):
    """Check whether the native app is installed on the device."""
    try:
        _, _, code = ssh.exec(f"test -d {DEST_DIR}", timeout=5)
        return code == 0
    except Exception:
        return False


def install(ssh, status_cb=None):
    """Install XOVI + AppLoad + MoveWriter native app + watchdog drop-in.

    status_cb(msg) is called with progress messages.
    """
    def say(msg):
        if status_cb:
            status_cb(msg)

    root = native_app_root()

    say("Checking prerequisites...")
    _ensure_entware(ssh, say)
    _ensure_python3(ssh, say)
    _ensure_vellum(ssh, say)
    _ensure_xovi(ssh, say)
    _ensure_appload(ssh, say)

    # Heal across firmware updates. A forced OTA bumps the OS, wipes the
    # system-partition mods, and leaves a stale hashtab — and the _ensure_*
    # steps above no-op when the dirs already exist, so a plain reinstall would
    # NOT recover. Run the vellum recovery every time (idempotent when healthy):
    # upgrade (pull OS-compatible versions + sync OS) -> check-os gate ->
    # reenable (restore the system-partition mods).
    _vellum_upgrade(ssh, say)
    _check_os_supported(ssh, say)
    _vellum_reenable(ssh, say)

    say("Uploading app files...")
    _upload_app(ssh, root)

    say("Installing crash protection...")
    _install_watchdog_dropin(ssh)
    _install_emergency_override(ssh)

    say("Setting up boot autostart...")
    _install_autostart(ssh)

    # Rebuild the hashtab for THIS xochitl (required after any firmware change;
    # also the hard XOVI-compat gate — aborts if XOVI can't load this xochitl),
    # then activate XOVI via the autostart script so the install brings the app
    # up now rather than only on the next reboot.
    _rebuild_hashtable(ssh, say)
    _activate_xovi(ssh, say)

    say("Install complete")


def uninstall(ssh, status_cb=None):
    """Remove MoveWriter native app and its watchdog drop-in.

    Leaves XOVI/AppLoad/Python in place (shared infrastructure).
    """
    def say(msg):
        if status_cb:
            status_cb(msg)

    say("Removing app files...")
    ssh.exec(f"rm -rf {DEST_DIR}", timeout=10)

    say("Removing crash protection...")
    _remove_watchdog_dropin(ssh)
    _remove_emergency_override(ssh)

    say("Removing boot autostart...")
    _remove_autostart(ssh)

    say("Restarting Move interface...")
    ssh.exec("(sleep 1 && systemctl restart xochitl) &", timeout=5)

    say("Uninstall complete")


# ── Prerequisite installers ───────────────────────────────────

def _ensure_entware(ssh, say):
    _, _, code = ssh.exec("command -v opkg || test -x /opt/bin/opkg", timeout=5)
    if code == 0:
        return
    say("Installing entware (package manager)...")
    ssh.exec(
        "wget --no-check-certificate -O- "
        "https://raw.githubusercontent.com/hmenzagh/rmpp-entware/main/rmpp_entware.sh "
        "| bash -s -- --force",
        timeout=180,
    )
    _, _, code = ssh.exec("test -x /opt/bin/opkg", timeout=5)
    if code != 0:
        raise RuntimeError("entware install failed")


def _ensure_python3(ssh, say):
    _, _, code = ssh.exec("test -x /opt/bin/python3", timeout=5)
    if code == 0:
        return
    say("Installing Python 3...")
    ssh.exec(
        "export PATH=/opt/bin:/opt/sbin:$PATH && opkg update && opkg install python3",
        timeout=180,
    )
    _, _, code = ssh.exec("test -x /opt/bin/python3", timeout=5)
    if code != 0:
        raise RuntimeError("Python 3 install failed")


def _ensure_vellum(ssh, say):
    _, _, code = ssh.exec("command -v vellum", timeout=5)
    if code == 0:
        return
    say("Installing Vellum...")
    ssh.exec(
        "wget --no-check-certificate -O /tmp/bootstrap.sh "
        "https://github.com/vellum-dev/vellum-cli/releases/latest/download/bootstrap.sh "
        "&& bash /tmp/bootstrap.sh && rm -f /tmp/bootstrap.sh",
        timeout=120,
    )
    _, _, code = ssh.exec("command -v vellum", timeout=5)
    if code != 0:
        raise RuntimeError("Vellum install failed")


def _ensure_xovi(ssh, say):
    _, _, code = ssh.exec(f"test -d {XOVI_DIR}", timeout=5)
    if code == 0:
        return
    say("Installing XOVI...")
    ssh.exec("vellum add xovi", timeout=180)
    _, _, code = ssh.exec(f"test -d {XOVI_DIR}", timeout=5)
    if code != 0:
        raise RuntimeError("XOVI install failed")


def _ensure_appload(ssh, say):
    _, _, code = ssh.exec(f"test -d {APPLOAD_DIR}", timeout=5)
    if code == 0:
        return
    say("Installing AppLoad...")
    ssh.exec("vellum add appload", timeout=180)
    _, _, code = ssh.exec(f"test -d {APPLOAD_DIR}", timeout=5)
    if code != 0:
        # Try alternate path check
        _, _, code = ssh.exec(
            f"ls {XOVI_DIR}/extensions.d/ | grep -qi appload", timeout=5
        )
        if code != 0:
            raise RuntimeError("AppLoad install failed")


# ── Firmware-update recovery ──────────────────────────────────
# A forced OTA wipes the system-partition mods (XOVI activation) and leaves the
# qt-resource-rebuilder hashtab keyed to the OLD xochitl. These run on every
# install so that a reinstall HEALS a force-updated device (idempotent when the
# device is already healthy). This is the sequence validated by hand on 3.27.

def _current_os_version(ssh):
    """Device firmware version, e.g. '3.27.1.0' (empty string if unreadable)."""
    out, _, _ = ssh.exec('. /etc/os-release && echo "$IMG_VERSION"', timeout=5)
    return (out or "").strip()


def _vellum_upgrade(ssh, say):
    """Pull OS-compatible package versions and sync vellum's recorded OS.

    `vellum upgrade` is documented to handle OS-version changes; it's a no-op on
    an already-current install. The `yes |` answers its confirmation prompt
    (the SSH exec is non-interactive).
    """
    say("Updating components for current firmware...")
    ssh.exec(f"{VELLUM_ENV} yes | vellum upgrade", timeout=300)


def _check_os_supported(ssh, say):
    """Stop the install early if XOVI's packages don't support this firmware.

    Avoids activating into a boot-flicker loop when reMarkable ships a new
    firmware before XOVI/AppLoad upstream catch up. Only the on-device app is
    gated — the Bluetooth keyboard service is unaffected. Advisory: the hashtab
    rebuild is the hard gate, so we hard-stop only on explicit incompatibility.
    """
    os_ver = _current_os_version(ssh)
    if not os_ver:
        return
    out, _, _ = ssh.exec(f"{VELLUM_ENV} vellum check-os {os_ver}", timeout=60)
    text = (out or "").lower()
    if "all packages are compatible" in text:
        return
    if "incompatible" in text or "not compatible" in text:
        raise RuntimeError(
            f"XOVI/AppLoad don't support firmware {os_ver} yet, so the on-device "
            f"app can't be installed safely right now. Your Bluetooth keyboard "
            f"still works — try the native app again once XOVI adds {os_ver} support."
        )
    say(f"Note: couldn't confirm {os_ver} compatibility; the rebuild step verifies it.")


def _vellum_reenable(ssh, say):
    """Restore XOVI's system-partition modifications after an OS upgrade."""
    say("Restoring system modifications...")
    ssh.exec(f"{VELLUM_ENV} yes | vellum reenable", timeout=120)


def _rebuild_hashtable(ssh, say):
    """Rebuild the qt-resource-rebuilder hashtab for the CURRENT xochitl.

    Required after any firmware change (the hashtab is keyed to xochitl's QML).
    The rebuild runs a headless xochitl that occasionally HANGS on startup, so a
    naive blocking call would freeze the install, leave orphaned processes, and
    could falsely proceed. Instead we run it BOUNDED in the background, poll for
    the hashtab + "Hashtab saved", then hard-KILL the rebuild chain (no orphans)
    if it doesn't finish in time. The hang is intermittent, so we retry once.
    On total failure we restart stock xochitl (never leave the screen dark) and
    abort. Stops xochitl while it runs (~1-2 min; the device screen blanks).
    """
    bounded_rebuild = (
        'HT=/home/root/xovi/exthome/qt-resource-rebuilder/hashtab; '
        'rm -f "$HT"; '
        '( echo "" | bash /home/root/xovi/rebuild_hashtable >/tmp/mw_rb.log 2>&1 ) & '
        'i=0; while [ $i -lt 25 ]; do sleep 4; '
        'if [ -f "$HT" ] && grep -q "Hashtab saved" /tmp/mw_rb.log 2>/dev/null; then break; fi; '
        'i=$((i+1)); done; '
        'pkill -9 -f rebuild_hashtable 2>/dev/null; kill -9 $(pidof xochitl) 2>/dev/null; sleep 1; '
        'if [ -f "$HT" ] && grep -q "Hashtab saved" /tmp/mw_rb.log 2>/dev/null; '
        'then echo MW_OK; else echo MW_FAIL; fi'
    )
    for n in (1, 2):
        say("Rebuilding interface resources (~1-2 min; screen will flicker — please wait)"
            + ("..." if n == 1 else " — retrying..."))
        out, _, _ = ssh.exec(bounded_rebuild, timeout=150)
        if "MW_OK" in (out or ""):
            return
    # Both attempts failed: don't leave the device dark or half-activated.
    ssh.exec("systemctl start xochitl.service", timeout=20)
    raise RuntimeError(
        "Couldn't rebuild the interface resources — xochitl kept hanging "
        "during the rebuild. Stopped before activation so the device isn't left "
        "in a bad state; your Bluetooth keyboard service is unaffected. Please "
        "try the install again."
    )


def _activate_xovi(ssh, say):
    """Bring xochitl up WITH xovi.so via the autostart script, then VERIFY it
    actually loaded — so the install never reports success when XOVI didn't
    activate. (A bare `systemctl restart xochitl` would start xochitl WITHOUT
    XOVI.)"""
    say("Activating MoveWriter...")
    # Clear the autostart failsafe counter — the hashtab rebuild just proved
    # XOVI loads, so give the device a clean slate.
    ssh.exec(
        "rm -f /home/root/.movewriter/xovi-activation-attempts 2>/dev/null || true",
        timeout=5,
    )
    ssh.exec(f"bash {AUTOSTART_SCRIPT_PATH}", timeout=90)
    out, _, _ = ssh.exec(
        'sleep 4; XPID=$(pidof xochitl); '
        'if tr "\\0" "\\n" </proc/$XPID/environ 2>/dev/null | grep -q xovi.so; '
        'then echo MW_XOVI_OK; else echo MW_XOVI_NO; fi',
        timeout=20,
    )
    if "MW_XOVI_OK" not in (out or ""):
        raise RuntimeError(
            "XOVI didn't activate after install, so MoveWriter may not appear in "
            "the menu. Try rebooting the Move and reinstalling."
        )


def _upload_app(ssh, root):
    """Upload all native app files to DEST_DIR."""
    # Create subdirectories
    subdirs = set(APP_FILES.keys()) - {""}
    for sub in sorted(subdirs):
        ssh.exec(f"mkdir -p {DEST_DIR}/{sub}", timeout=5)
    ssh.exec(f"mkdir -p {DEST_DIR}", timeout=5)

    for subdir, files in APP_FILES.items():
        for name in files:
            local = os.path.join(root, subdir, name) if subdir else os.path.join(root, name)
            remote = f"{DEST_DIR}/{subdir}/{name}" if subdir else f"{DEST_DIR}/{name}"
            if not os.path.isfile(local):
                # Optional files (e.g., resources.rcc before build, icon.png)
                if name in ("resources.rcc",):
                    raise RuntimeError(
                        f"Missing {local} -- run `./build.sh` in nativeapp/ first"
                    )
                continue
            with open(local, "rb") as f:
                data = f.read()
            # Normalize line endings for text files
            if name.endswith((".py", ".sh", ".qml", ".qrc", ".json", ".service"))\
               or name == "entry":
                data = data.replace(b"\r\n", b"\n")
            ssh.upload_bytes(data, remote)

    ssh.exec(f"chmod +x {DEST_DIR}/backend/entry", timeout=5)


def _install_watchdog_dropin(ssh):
    """Install the [Service]\\nWatchdogSec=0 drop-in on persistent rootfs.

    Safe: no [Unit] section. A [Unit] section with deps caused a factory
    reset before — only [Service] is allowed in this drop-in.
    """
    local = os.path.join(_resources_dir(), "xochitl-nowatchdog.conf")
    with open(local, "r") as f:
        content = f.read().replace("\r\n", "\n")

    # Sanity: a [Unit] section is allowed here ONLY to RESET inherited
    # values (e.g., OnFailure=, JobTimeoutSec=0). Never add cross-unit
    # dependencies — that's what caused the factory reset in the past.
    for forbidden in ("Requires=", "Wants=", "After=", "Before=", "BindsTo="):
        if forbidden in content:
            raise RuntimeError(
                f"Refusing to write xochitl drop-in containing '{forbidden}' "
                "(only blank-value resets allowed in [Unit])"
            )

    ssh.exec("mount -o remount,rw /", timeout=5)
    try:
        ssh.exec(f"mkdir -p {WATCHDOG_DROPIN_DIR}", timeout=5)
        ssh.upload_string(content, WATCHDOG_DROPIN_PATH)
    finally:
        ssh.exec("mount -o remount,ro /", timeout=5)

    ssh.exec("systemctl daemon-reload", timeout=10)


def _remove_watchdog_dropin(ssh):
    ssh.exec("mount -o remount,rw /", timeout=5)
    try:
        ssh.exec(f"rm -f {WATCHDOG_DROPIN_PATH}", timeout=5)
        ssh.exec(f"rmdir {WATCHDOG_DROPIN_DIR} 2>/dev/null || true", timeout=5)
    finally:
        ssh.exec("mount -o remount,ro /", timeout=5)
    ssh.exec("systemctl daemon-reload", timeout=10)


def _install_emergency_override(ssh):
    """Override rm-emergency.service so it doesn't reboot on xochitl hangs.

    The OTA swu_applied=1 path is preserved (that reboot is needed for
    partition swap). For all other emergencies, we just log and do nothing.
    """
    local = os.path.join(_resources_dir(), "rm-emergency-override.conf")
    with open(local, "r") as f:
        content = f.read().replace("\r\n", "\n")

    for forbidden in ("Requires=", "Wants=", "After=", "Before=", "BindsTo="):
        if forbidden in content:
            raise RuntimeError(
                f"Refusing rm-emergency override containing '{forbidden}'"
            )

    ssh.exec("mount -o remount,rw /", timeout=5)
    try:
        ssh.exec(f"mkdir -p {EMERGENCY_DROPIN_DIR}", timeout=5)
        ssh.upload_string(content, EMERGENCY_DROPIN_PATH)
    finally:
        ssh.exec("mount -o remount,ro /", timeout=5)
    ssh.exec("systemctl daemon-reload", timeout=10)


def _remove_emergency_override(ssh):
    ssh.exec("mount -o remount,rw /", timeout=5)
    try:
        ssh.exec(f"rm -f {EMERGENCY_DROPIN_PATH}", timeout=5)
        ssh.exec(f"rmdir {EMERGENCY_DROPIN_DIR} 2>/dev/null || true", timeout=5)
    finally:
        ssh.exec("mount -o remount,ro /", timeout=5)
    ssh.exec("systemctl daemon-reload", timeout=10)


def _install_autostart(ssh):
    """Install XOVI autostart service so MoveWriter survives reboots."""
    script_local = os.path.join(_resources_dir(), "movewriter-xovi-autostart.sh")
    service_local = os.path.join(_resources_dir(), "movewriter-xovi.service")

    with open(script_local, "r") as f:
        script = f.read().replace("\r\n", "\n")
    with open(service_local, "r") as f:
        service = f.read().replace("\r\n", "\n")

    # Sanity: no forbidden [Unit] deps in our service file. We allow [Unit]
    # with just Description, but never After/Requires/Wants (caused factory reset).
    for forbidden in ("Requires=", "Wants=", "After=", "Before=", "BindsTo="):
        if forbidden in service:
            raise RuntimeError(
                f"Refusing to write autostart service with '{forbidden}' "
                "in persistent rootfs"
            )

    ssh.exec("mount -o remount,rw /", timeout=5)
    try:
        ssh.upload_string(script, AUTOSTART_SCRIPT_PATH)
        ssh.exec(f"chmod +x {AUTOSTART_SCRIPT_PATH}", timeout=5)
        ssh.upload_string(service, AUTOSTART_SERVICE_PATH)
        ssh.exec(
            "mkdir -p /usr/lib/systemd/system/multi-user.target.wants",
            timeout=5,
        )
        ssh.exec(
            f"ln -sf {AUTOSTART_SERVICE_PATH} {AUTOSTART_SYMLINK_PATH}",
            timeout=5,
        )
    finally:
        ssh.exec("mount -o remount,ro /", timeout=5)

    ssh.exec("systemctl daemon-reload", timeout=10)


def _remove_autostart(ssh):
    ssh.exec("mount -o remount,rw /", timeout=5)
    try:
        ssh.exec(f"rm -f {AUTOSTART_SCRIPT_PATH}", timeout=5)
        ssh.exec(f"rm -f {AUTOSTART_SERVICE_PATH}", timeout=5)
        ssh.exec(f"rm -f {AUTOSTART_SYMLINK_PATH}", timeout=5)
    finally:
        ssh.exec("mount -o remount,ro /", timeout=5)
    ssh.exec("systemctl daemon-reload", timeout=10)
