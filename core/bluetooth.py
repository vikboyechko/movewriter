import re

from core import service_installer


def verify_device_state(ssh, cfg):
    """Check actual device state vs saved config. Returns dict of booleans."""
    TIMEOUT = 5

    state = {
        "service_installed": False,
        "keyboard_paired": False,
        "keyboard_connected": False,
        "bt_powered": False,
    }

    try:
        _, _, code = ssh.exec(
            f"systemctl is-enabled {service_installer.SERVICE_NAME}", timeout=TIMEOUT
        )
        state["service_installed"] = code == 0
    except Exception:
        pass

    try:
        out, _, _ = ssh.exec("bluetoothctl show", timeout=TIMEOUT)
        for line in out.splitlines():
            if "Powered:" in line:
                state["bt_powered"] = "yes" in line.lower()
                break
    except Exception:
        pass

    saved_mac = cfg.get("keyboard_mac")
    if saved_mac:
        try:
            out, _, _ = ssh.exec("bluetoothctl devices Paired", timeout=TIMEOUT)
            for line in out.strip().splitlines():
                m = re.match(r"Device\s+([0-9A-Fa-f:]{17})\s+(.+)", line.strip())
                if m and m.group(1).lower() == saved_mac.lower():
                    state["keyboard_paired"] = True
                    break
        except Exception:
            pass

        if state["keyboard_paired"]:
            try:
                out, _, _ = ssh.exec(
                    f"bluetoothctl info {saved_mac}", timeout=TIMEOUT
                )
                for line in out.splitlines():
                    if "Connected:" in line:
                        state["keyboard_connected"] = "yes" in line.lower()
                        break
            except Exception:
                pass

    return state


def scan_devices(ssh, timeout=15):
    ssh.exec(f"bluetoothctl --timeout {timeout} scan on", timeout=timeout + 5)
    out, _, _ = ssh.exec("bluetoothctl devices")
    devices = []
    for line in out.strip().splitlines():
        m = re.match(r"Device\s+([0-9A-Fa-f:]{17})\s+(.+)", line.strip())
        if m:
            devices.append({"mac": m.group(1), "name": m.group(2)})
    return devices


def pair(ssh, mac):
    out, err, code = ssh.exec(f"bluetoothctl pair {mac}", timeout=30)
    combined = (out + err).lower()
    if code != 0 and "alreadyexists" not in combined:
        raise RuntimeError(f"Pair failed: {err or out}")
    return out


def trust(ssh, mac):
    out, err, code = ssh.exec(f"bluetoothctl trust {mac}", timeout=10)
    if code != 0:
        raise RuntimeError(f"Trust failed: {err or out}")
    return out


def remove(ssh, mac):
    """Fully unpair and forget a device so it won't auto-reconnect."""
    ssh.exec(f"bluetoothctl remove {mac}", timeout=10)


def connect(ssh, mac):
    out, err, code = ssh.exec(f"bluetoothctl connect {mac}", timeout=15)
    if code != 0:
        raise RuntimeError(f"Connect failed: {err or out}")
    return out


def get_connection_status(ssh, mac):
    out, _, _ = ssh.exec(f"bluetoothctl info {mac}")
    for line in out.splitlines():
        if "Connected:" in line:
            return "yes" in line.lower()
    return False


def pair_and_connect(ssh, mac, old_mac=None):
    if old_mac and old_mac.lower() != mac.lower():
        remove(ssh, old_mac)
    pair(ssh, mac)
    trust(ssh, mac)
    connect(ssh, mac)
    if not get_connection_status(ssh, mac):
        raise RuntimeError("Pairing succeeded but device is not connected")
