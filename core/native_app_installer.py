"""Install/uninstall MoveWriter Native (on-device app) via SSH.

Deploys XOVI + AppLoad + MoveWriter native app to the Move, plus a
persistent systemd drop-in that disables xochitl's watchdog (prevents
reboots during BT operations).

Source files for the native app are located via `native_app_root()`:
- Production: bundled under resources/native_app/ by PyInstaller
- Development: sibling ../movewriternative/ directory
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

# App layout (mirrors movewriternative repo structure)
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
    # PyInstaller bundle
    if getattr(sys, "_MEIPASS", None):
        bundled = os.path.join(sys._MEIPASS, "resources", "native_app")
        if os.path.isdir(bundled):
            return bundled

    # Development: sibling repo
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dev = os.path.normpath(os.path.join(here, "..", "movewriternative"))
    if os.path.isdir(dev):
        return dev

    raise RuntimeError(
        "Cannot locate MoveWriter native app source. "
        "Expected at ../movewriternative/ or bundled in resources/native_app/."
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

    say("Uploading app files...")
    _upload_app(ssh, root)

    say("Installing crash protection...")
    _install_watchdog_dropin(ssh)
    _install_emergency_override(ssh)

    say("Setting up boot autostart...")
    _install_autostart(ssh)

    say("Restarting Move interface...")
    # systemctl restart xochitl — fire and forget with & so it doesn't kill
    # the SSH command mid-execution. The UI briefly flickers.
    ssh.exec("(sleep 1 && systemctl restart xochitl) &", timeout=5)

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
                        f"Missing {local} — run `./build.sh` in movewriternative first"
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
