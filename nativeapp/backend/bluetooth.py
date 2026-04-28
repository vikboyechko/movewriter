"""Bluetooth operations for MoveWriter Native.

Adapted from movewriterapp/core/bluetooth.py — replaces SSH exec with
local subprocess calls and Paramiko channels with pty-based interaction.
"""
import os
import pty
import re
import select
import subprocess
import time

from backend import service


def _run(cmd, timeout=10):
    """Run a shell command locally, return (stdout, stderr, returncode)."""
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=timeout
    )
    return result.stdout, result.stderr, result.returncode


def read_device_keyboard():
    """Return (mac, name) for the keyboard currently set up on this Move.

    Reads from the on-device MAC file (source of truth), validates that
    BlueZ actually still has it paired, and returns the BlueZ name. If
    the MAC file exists but BlueZ doesn't know the device (e.g., a pair
    was interrupted mid-flight or the user unpaired externally), the
    stale MAC file is removed and ("", "") is returned.
    """
    try:
        with open(service.KEYBOARD_MAC_PATH) as f:
            mac = f.read().strip()
    except (FileNotFoundError, OSError):
        return "", ""

    if not mac:
        return "", ""

    name = ""
    actually_paired = False
    try:
        out, _, _ = _run("bluetoothctl devices Paired", timeout=5)
        for line in out.strip().splitlines():
            m = re.match(r"Device\s+([0-9A-Fa-f:]{17})\s+(.+)", line.strip())
            if m and m.group(1).lower() == mac.lower():
                name = m.group(2).strip()
                actually_paired = True
                break
    except Exception:
        pass

    if not actually_paired:
        # Stale MAC file — clear it so the reconnect loop stops trying
        # a phantom device and the UI doesn't show a ghost keyboard.
        try:
            os.remove(service.KEYBOARD_MAC_PATH)
        except OSError:
            pass
        return "", ""

    return mac, name


def verify_device_state(cfg):
    """Check actual device state vs saved config. Returns dict of booleans."""
    TIMEOUT = 5

    state = {
        "service_installed": False,
        "keyboard_paired": False,
        "keyboard_connected": False,
        "bt_powered": False,
    }

    try:
        _, _, code = _run(
            f"systemctl is-active {service.SERVICE_NAME}", timeout=TIMEOUT
        )
        if code == 0:
            state["service_installed"] = True
        else:
            _, _, code = _run(
                f"test -f {service.SERVICE_PERSISTENT_PATH}", timeout=TIMEOUT
            )
            state["service_installed"] = code == 0
    except Exception:
        pass

    try:
        out, _, _ = _run("bluetoothctl show", timeout=TIMEOUT)
        for line in out.splitlines():
            if "Powered:" in line:
                state["bt_powered"] = "yes" in line.lower()
                break
    except Exception:
        pass

    saved_mac = cfg.get("keyboard_mac")
    if saved_mac:
        try:
            out, _, _ = _run("bluetoothctl devices Paired", timeout=TIMEOUT)
            for line in out.strip().splitlines():
                m = re.match(r"Device\s+([0-9A-Fa-f:]{17})\s+(.+)", line.strip())
                if m and m.group(1).lower() == saved_mac.lower():
                    state["keyboard_paired"] = True
                    break
        except Exception:
            pass

        if state["keyboard_paired"]:
            try:
                out, _, _ = _run(
                    f"bluetoothctl info {saved_mac}", timeout=TIMEOUT
                )
                for line in out.splitlines():
                    if "Connected:" in line:
                        state["keyboard_connected"] = "yes" in line.lower()
                        break
            except Exception:
                pass

    return state


def scan_devices(timeout=15):
    try:
        _run(f"bluetoothctl --timeout {timeout} scan on", timeout=timeout + 5)
    except (subprocess.TimeoutExpired, TimeoutError):
        pass  # scan populated the device cache
    out, _, _ = _run("bluetoothctl devices")
    devices = []
    for line in out.strip().splitlines():
        m = re.match(r"Device\s+([0-9A-Fa-f:]{17})\s+(.+)", line.strip())
        if m:
            devices.append({"mac": m.group(1), "name": m.group(2)})
    return devices


def pair(mac):
    out, err, code = _run(f"bluetoothctl pair {mac}", timeout=30)
    combined = (out + err).lower()
    if code != 0 and "alreadyexists" not in combined:
        raise RuntimeError(f"Pair failed: {err or out}")
    return out


def trust(mac):
    out, err, code = _run(f"bluetoothctl trust {mac}", timeout=10)
    if code != 0:
        raise RuntimeError(f"Trust failed: {err or out}")
    return out


def remove(mac):
    """Fully unpair and forget a device so it won't auto-reconnect."""
    _run(f"bluetoothctl remove {mac}", timeout=10)


def connect(mac):
    out, err, code = _run(f"bluetoothctl connect {mac}", timeout=15)
    if code != 0:
        raise RuntimeError(f"Connect failed: {err or out}")
    return out


def get_connection_status(mac):
    out, _, _ = _run(f"bluetoothctl info {mac}")
    for line in out.splitlines():
        if "Connected:" in line:
            return "yes" in line.lower()
    return False


def get_device_name(mac):
    """Return the human-readable name BlueZ knows for a MAC, or ''."""
    try:
        out, _, _ = _run(f"bluetoothctl info {mac}", timeout=5)
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("Name:"):
                return line[len("Name:"):].strip()
    except Exception:
        pass
    return ""


def _strip_ansi(text):
    """Remove ANSI escape sequences from text."""
    return re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)


def _read_pty(master_fd, timeout=0.5):
    """Read all currently available data from a pty master fd."""
    data = b""
    end_time = time.monotonic() + timeout
    while time.monotonic() < end_time:
        remaining = end_time - time.monotonic()
        if remaining <= 0:
            break
        ready, _, _ = select.select([master_fd], [], [], min(remaining, 0.1))
        if ready:
            try:
                chunk = os.read(master_fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            data += chunk
        elif data:
            break
    return data.decode("utf-8", errors="replace")


def _write_pty(master_fd, text):
    """Write a line of text to a pty master fd."""
    os.write(master_fd, (text + "\n").encode())


def pair_interactive(mac, passkey_callback=None, timeout=60):
    """Pair using interactive bluetoothctl to handle passkey/PIN prompts.

    Uses pty.openpty() + subprocess.Popen instead of Paramiko channels.

    Args:
        mac: Bluetooth MAC address to pair
        passkey_callback: Called with passkey string when keyboard requests PIN entry.
        timeout: Maximum seconds to wait for pairing to complete

    Returns:
        True if pairing succeeded

    Raises:
        RuntimeError on pairing failure
    """
    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        ["bluetoothctl"],
        stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
        close_fds=True,
    )
    os.close(slave_fd)

    try:
        # Wait for bluetoothctl prompt
        _read_pty(master_fd, timeout=2)

        # Register as agent
        _write_pty(master_fd, "agent on")
        _read_pty(master_fd, timeout=1)

        _write_pty(master_fd, "default-agent")
        _read_pty(master_fd, timeout=1)

        # Initiate pairing
        _write_pty(master_fd, f"pair {mac}")

        deadline = time.monotonic() + timeout
        paired = False
        passkey_sent = False

        while time.monotonic() < deadline:
            output = _read_pty(master_fd, timeout=2)
            if not output:
                continue

            clean = _strip_ansi(output)
            lower = clean.lower()

            if "alreadyexists" in lower.replace(" ", ""):
                paired = True
                break

            # "Confirm passkey 123456 (yes/no):" — auto-confirm
            confirm_match = re.search(
                r"confirm passkey\s+(\d+)\s+\(yes/no\)", lower
            )
            if confirm_match:
                passkey = confirm_match.group(1)
                if passkey_callback and not passkey_sent:
                    passkey_callback(passkey)
                    passkey_sent = True
                _write_pty(master_fd, "yes")
                continue

            # "[agent] PIN code: 813282"
            pin_match = re.search(r"pin code:\s*(\d+)", lower)
            if pin_match:
                passkey = pin_match.group(1)
                if passkey_callback and not passkey_sent:
                    passkey_callback(passkey)
                    passkey_sent = True
                continue

            # "Passkey: 123456"
            passkey_match = re.search(r"passkey:\s*(\d+)", lower)
            if passkey_match:
                passkey = passkey_match.group(1)
                if passkey_callback and not passkey_sent:
                    passkey_callback(passkey)
                    passkey_sent = True
                continue

            # "Enter PIN code:"
            if "enter pin code" in lower and not pin_match:
                if passkey_callback and not passkey_sent:
                    passkey_callback("0000")
                    passkey_sent = True
                _write_pty(master_fd, "0000")
                continue

            if "pairing successful" in lower or "paired: yes" in lower:
                paired = True
                break

            if "authenticationfailed" in lower.replace(" ", ""):
                raise RuntimeError(
                    "Authentication failed — keyboard may require a PIN "
                    "that couldn't be entered automatically"
                )
            if "authenticationcanceled" in lower.replace(" ", ""):
                raise RuntimeError("Pairing was canceled")
            if "authenticationrejected" in lower.replace(" ", ""):
                raise RuntimeError("Pairing was rejected by the keyboard")
            if "connectionrefused" in lower.replace(" ", ""):
                raise RuntimeError("Connection refused by the keyboard")

        if not paired and time.monotonic() >= deadline:
            raise RuntimeError(
                "Pairing timed out. Make sure your keyboard is in "
                "pairing mode (usually hold the power/connect button "
                "for 3+ seconds until the LED blinks rapidly)."
            )

        return paired

    finally:
        try:
            _write_pty(master_fd, "quit")
            time.sleep(0.3)
        except Exception:
            pass
        try:
            os.close(master_fd)
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def pair_and_connect(mac, old_mac=None, passkey_callback=None):
    """Pair + trust + connect a keyboard.

    Mirrors the desktop app's flow exactly — that's the version that
    has worked reliably. Don't add bluetoothctl commands before the
    pair: each one consumes time during which xochitl may hang from
    BT D-Bus signals, eating into the window pair has to complete.
    """
    if old_mac and old_mac.lower() != mac.lower():
        remove(old_mac)
    pair_interactive(mac, passkey_callback=passkey_callback)
    trust(mac)
    connect(mac)
    if not get_connection_status(mac):
        raise RuntimeError("Pairing succeeded but device is not connected")
