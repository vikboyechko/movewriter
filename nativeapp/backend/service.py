"""Service installer for MoveWriter Native.

Adapted from movewriterapp/core/service_installer.py — replaces SSH/SFTP
operations with local file I/O and subprocess calls.
"""
import os
import shutil
import subprocess
from pathlib import Path

from backend import layout_patcher

SERVICE_NAME = "remarkable-bt-keyboard.service"
SCRIPT_NAME = "bt-keyboard.sh"

# Persistent locations (survive reboot)
SERVICE_PERSISTENT_PATH = f"/usr/lib/systemd/system/{SERVICE_NAME}"
ENABLE_SYMLINK_DIR = "/usr/lib/systemd/system/multi-user.target.wants"
ENABLE_SYMLINK_PATH = f"{ENABLE_SYMLINK_DIR}/{SERVICE_NAME}"
SCRIPT_DIR = "/home/root/.movewriter"
SCRIPT_REMOTE_PATH = f"{SCRIPT_DIR}/{SCRIPT_NAME}"
KEYBOARD_MAC_PATH = "/home/root/.movewriter-keyboard"

# Volatile location (for cleanup of old installs)
SERVICE_VOLATILE_PATH = f"/etc/systemd/system/{SERVICE_NAME}"


def _run(cmd, timeout=10):
    """Run a shell command locally, return (stdout, stderr, returncode)."""
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=timeout
    )
    return result.stdout, result.stderr, result.returncode


def _resources_dir():
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")


def install():
    # Create script directory on persistent storage
    os.makedirs(SCRIPT_DIR, exist_ok=True)

    # Copy the setup+monitor script (normalize line endings for Linux)
    local_script = os.path.join(_resources_dir(), SCRIPT_NAME)
    with open(local_script, "r") as f:
        script_content = f.read().replace("\r\n", "\n")
    Path(SCRIPT_REMOTE_PATH).write_text(script_content)
    os.chmod(SCRIPT_REMOTE_PATH, 0o755)

    # Install service file to persistent root filesystem (normalize line endings)
    local_service = os.path.join(_resources_dir(), SERVICE_NAME)
    with open(local_service, "r") as f:
        service_content = f.read().replace("\r\n", "\n")
    _run("mount -o remount,rw /", timeout=10)
    try:
        Path(SERVICE_PERSISTENT_PATH).write_text(service_content)
        os.makedirs(ENABLE_SYMLINK_DIR, exist_ok=True)
        # Create enable symlink
        try:
            os.symlink(SERVICE_PERSISTENT_PATH, ENABLE_SYMLINK_PATH)
        except FileExistsError:
            os.remove(ENABLE_SYMLINK_PATH)
            os.symlink(SERVICE_PERSISTENT_PATH, ENABLE_SYMLINK_PATH)
    finally:
        _run("mount -o remount,ro /", timeout=10)

    # Clean up any old volatile install
    try:
        os.remove(SERVICE_VOLATILE_PATH)
    except FileNotFoundError:
        pass

    # Reload and start
    _run("systemctl daemon-reload")
    out, err, code = _run(f"systemctl start {SERVICE_NAME}", timeout=30)
    if code != 0:
        raise RuntimeError(f"Failed to start service: {err or out}")


def uninstall():
    # Restore original libepaper.so if it was patched
    layout_patcher.restore_original()

    # Stop and disable
    _run(f"systemctl stop {SERVICE_NAME}", timeout=10)
    _run(f"systemctl disable {SERVICE_NAME}", timeout=5)

    # Remove from persistent root filesystem
    _run("mount -o remount,rw /", timeout=10)
    try:
        try:
            os.remove(SERVICE_PERSISTENT_PATH)
        except FileNotFoundError:
            pass
        try:
            os.remove(ENABLE_SYMLINK_PATH)
        except FileNotFoundError:
            pass
    finally:
        _run("mount -o remount,ro /", timeout=10)

    # Remove volatile copy too (if any)
    try:
        os.remove(SERVICE_VOLATILE_PATH)
    except FileNotFoundError:
        pass

    # Clean up script, MAC file, and movewriter directory
    shutil.rmtree(SCRIPT_DIR, ignore_errors=True)
    try:
        os.remove(KEYBOARD_MAC_PATH)
    except FileNotFoundError:
        pass

    _run("systemctl daemon-reload", timeout=5)


def save_keyboard_mac(mac):
    """Write keyboard MAC to device so the service can auto-reconnect on boot."""
    Path(KEYBOARD_MAC_PATH).write_text(mac)


def clear_keyboard_mac():
    """Remove the MAC file so the service stops trying to reconnect."""
    try:
        os.remove(KEYBOARD_MAC_PATH)
    except FileNotFoundError:
        pass
