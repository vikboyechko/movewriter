import re
import time
import select

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
            f"systemctl is-active {service_installer.SERVICE_NAME}", timeout=TIMEOUT
        )
        if code == 0:
            state["service_installed"] = True
        else:
            # Service may not be running yet (boot timing) but files exist
            _, _, code = ssh.exec(
                f"test -f {service_installer.SERVICE_PERSISTENT_PATH}", timeout=TIMEOUT
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
    try:
        ssh.exec(f"bluetoothctl --timeout {timeout} scan on", timeout=timeout + 5)
    except TimeoutError:
        pass  # scan populated the device cache; timeout means it ran the full duration
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


def _send_line(channel, text):
    """Send a line of text to an interactive channel."""
    channel.sendall(text + "\n")


def _read_available(channel, timeout=0.5):
    """Read all currently available data from a channel."""
    data = b""
    end_time = time.monotonic() + timeout
    while time.monotonic() < end_time:
        remaining = end_time - time.monotonic()
        if remaining <= 0:
            break
        ready, _, _ = select.select([channel], [], [], min(remaining, 0.1))
        if ready:
            chunk = channel.recv(4096)
            if not chunk:
                break
            data += chunk
        elif data:
            # Got some data and nothing more coming
            break
    return data.decode("utf-8", errors="replace")


def _strip_ansi(text):
    """Remove ANSI escape sequences from text."""
    return re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)


def pair_interactive(ssh, mac, passkey_callback=None, timeout=60):
    """Pair using interactive bluetoothctl to handle passkey/PIN prompts.

    Args:
        ssh: SSHClient instance
        mac: Bluetooth MAC address to pair
        passkey_callback: Called with passkey string when keyboard requests PIN entry.
                         Signature: callback(passkey: str) -> None
        timeout: Maximum seconds to wait for pairing to complete

    Returns:
        True if pairing succeeded

    Raises:
        RuntimeError on pairing failure
    """
    channel = ssh.open_channel()
    try:
        # Wait for shell prompt
        _read_available(channel, timeout=2)

        # Start bluetoothctl in interactive mode
        _send_line(channel, "bluetoothctl")
        _read_available(channel, timeout=1)

        # Register as agent so we can receive passkey requests
        _send_line(channel, "agent on")
        _read_available(channel, timeout=1)

        _send_line(channel, "default-agent")
        _read_available(channel, timeout=1)

        # Initiate pairing
        _send_line(channel, f"pair {mac}")

        # Monitor output for passkey or result
        deadline = time.monotonic() + timeout
        paired = False
        passkey_sent = False

        while time.monotonic() < deadline:
            output = _read_available(channel, timeout=2)
            if not output:
                continue

            clean = _strip_ansi(output)
            lower = clean.lower()

            # Check for already paired
            if "alreadyexists" in lower.replace(" ", ""):
                paired = True
                break

            # Check for passkey/PIN prompts
            # "Confirm passkey 123456 (yes/no):" — auto-confirm
            confirm_match = re.search(
                r"confirm passkey\s+(\d+)\s+\(yes/no\)", lower
            )
            if confirm_match:
                passkey = confirm_match.group(1)
                if passkey_callback and not passkey_sent:
                    passkey_callback(passkey)
                    passkey_sent = True
                _send_line(channel, "yes")
                continue

            # "[agent] PIN code: 813282" — legacy PIN pairing (e.g. old Apple keyboards)
            # The agent generates a random PIN; user must type it on the physical keyboard
            pin_match = re.search(r"pin code:\s*(\d+)", lower)
            if pin_match:
                passkey = pin_match.group(1)
                if passkey_callback and not passkey_sent:
                    passkey_callback(passkey)
                    passkey_sent = True
                # Don't send anything — just wait for the user to type it on the keyboard
                continue

            # "Passkey: 123456" — SSP display passkey, user types on keyboard
            passkey_match = re.search(r"passkey:\s*(\d+)", lower)
            if passkey_match:
                passkey = passkey_match.group(1)
                if passkey_callback and not passkey_sent:
                    passkey_callback(passkey)
                    passkey_sent = True
                continue

            # "Enter PIN code:" — keyboard wants us to enter a PIN (without displaying one)
            if "enter pin code" in lower and not pin_match:
                if passkey_callback and not passkey_sent:
                    passkey_callback("0000")
                    passkey_sent = True
                _send_line(channel, "0000")
                continue

            # Check for success
            if "pairing successful" in lower or "paired: yes" in lower:
                paired = True
                break

            # Check for failure
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
            raise RuntimeError(f"Pairing timed out after {timeout}s")

        return paired

    finally:
        try:
            _send_line(channel, "quit")
            time.sleep(0.3)
        except Exception:
            pass
        try:
            channel.close()
        except Exception:
            pass


def pair_and_connect(ssh, mac, old_mac=None, passkey_callback=None):
    if old_mac and old_mac.lower() != mac.lower():
        remove(ssh, old_mac)
    pair_interactive(ssh, mac, passkey_callback=passkey_callback)
    trust(ssh, mac)
    connect(ssh, mac)
    if not get_connection_status(ssh, mac):
        raise RuntimeError("Pairing succeeded but device is not connected")
