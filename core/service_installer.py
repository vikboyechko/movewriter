import os

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


def _resources_dir():
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")


def install(ssh):
    # Create script directory on persistent storage
    ssh.exec(f"mkdir -p {SCRIPT_DIR}")

    # Upload the setup+monitor script (normalize line endings for Linux)
    local_script = os.path.join(_resources_dir(), SCRIPT_NAME)
    with open(local_script, "r") as f:
        script_content = f.read().replace("\r\n", "\n")
    ssh.upload_string(script_content, SCRIPT_REMOTE_PATH)
    ssh.exec(f"chmod +x {SCRIPT_REMOTE_PATH}")

    # Install service file to persistent root filesystem (normalize line endings)
    local_service = os.path.join(_resources_dir(), SERVICE_NAME)
    with open(local_service, "r") as f:
        service_content = f.read().replace("\r\n", "\n")
    ssh.exec("mount -o remount,rw /")
    try:
        ssh.upload_string(service_content, SERVICE_PERSISTENT_PATH)
        # Create enable symlink on persistent root fs too
        ssh.exec(f"mkdir -p {ENABLE_SYMLINK_DIR}")
        ssh.exec(f"ln -sf {SERVICE_PERSISTENT_PATH} {ENABLE_SYMLINK_PATH}")
    finally:
        ssh.exec("mount -o remount,ro /")

    # Clean up any old volatile install
    ssh.exec(f"rm -f {SERVICE_VOLATILE_PATH}", timeout=5)

    # Reload and start
    ssh.exec("systemctl daemon-reload")
    out, err, code = ssh.exec(f"systemctl enable --now {SERVICE_NAME}", timeout=30)
    if code != 0:
        raise RuntimeError(f"Failed to enable service: {err or out}")


def uninstall(ssh):
    # Stop and disable
    ssh.exec(f"systemctl stop {SERVICE_NAME}", timeout=10)
    ssh.exec(f"systemctl disable {SERVICE_NAME}", timeout=5)

    # Remove from persistent root filesystem
    ssh.exec("mount -o remount,rw /")
    try:
        ssh.exec(f"rm -f {SERVICE_PERSISTENT_PATH}", timeout=5)
        ssh.exec(f"rm -f {ENABLE_SYMLINK_PATH}", timeout=5)
    finally:
        ssh.exec("mount -o remount,ro /")

    # Remove volatile copy too (if any)
    ssh.exec(f"rm -f {SERVICE_VOLATILE_PATH}", timeout=5)

    # Clean up script and MAC file
    ssh.exec(f"rm -rf {SCRIPT_DIR}", timeout=5)
    ssh.exec(f"rm -f {KEYBOARD_MAC_PATH}", timeout=5)

    ssh.exec("systemctl daemon-reload", timeout=5)


def save_keyboard_mac(ssh, mac):
    """Write keyboard MAC to device so the service can auto-reconnect on boot."""
    ssh.upload_string(mac, KEYBOARD_MAC_PATH)
