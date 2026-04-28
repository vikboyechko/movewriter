"""MoveWriter Native backend — message router and action dispatcher.

Connects to the AppLoad socket, receives JSON requests from the QML frontend,
dispatches actions to handler functions in background threads, and sends
responses/events back.

Note: the watchdog-disable drop-in installed by the desktop app prevents
xochitl from being killed during BT operations. No in-process keepalive
is needed here.
"""
import json
import logging
import subprocess
import sys
import threading
import time
import traceback

from backend.protocol import Protocol, MSG_REQUEST, SYS_TERMINATE, SYS_NEW_FRONTEND
from backend import bluetooth, config, layout_patcher, service

logging.basicConfig(level=logging.INFO, format='%(name)s: %(message)s')
log = logging.getLogger(__name__)

KEYBOARD_LAYOUTS = [
    ("US English", "us"),
    ("UK English", "uk"),
    ("German", "de"),
    ("French", "fr"),
    ("Spanish", "es"),
    ("Italian", "it"),
    ("Portuguese", "pt"),
    ("Brazilian", "br"),
    ("Dutch", "nl"),
    ("Swedish", "sv"),
    ("Norwegian", "no"),
    ("Danish", "dk"),
    ("Finnish", "fi"),
    ("Icelandic", "is"),
    ("Swiss German", "de_ch"),
    ("Swiss French", "fr_ch"),
    ("Belgian", "be"),
    ("Russian", "ru"),
    ("Ukrainian", "ua"),
    ("Czech", "cz"),
    ("Hungarian", "hu"),
    ("Turkish", "tr"),
    ("Greek", "gr"),
    ("Hebrew", "he"),
]

LAYOUT_MAP = dict(KEYBOARD_LAYOUTS)


class Backend:
    def __init__(self, socket_path):
        self.proto = Protocol(socket_path)
        self.cfg = config.load()

    def run(self):
        """Main receive loop."""
        log.info("Backend started")
        while True:
            try:
                msg_type, payload = self.proto.recv()
            except Exception as e:
                log.error("Socket recv failed: %s", e)
                break

            log.info("Received msg_type=%s payload=%s", msg_type, repr(payload)[:200])

            if msg_type == SYS_TERMINATE:
                log.info("Received terminate signal")
                break

            if msg_type == SYS_NEW_FRONTEND:
                log.info("New frontend connected — sending initial status")
                thread = threading.Thread(
                    target=self._push_initial_status, daemon=True
                )
                thread.start()
                continue

            if msg_type == MSG_REQUEST and payload:
                action = payload.get("action")
                params = payload.get("params", {})
                req_id = payload.get("id")
                if action:
                    thread = threading.Thread(
                        target=self._handle_action,
                        args=(action, params, req_id),
                        daemon=True,
                    )
                    thread.start()

    def _handle_action(self, action, params, req_id):
        """Dispatch an action to the appropriate handler."""
        try:
            handler = getattr(self, f"_action_{action}", None)
            if not handler:
                self._send_error(req_id, f"Unknown action: {action}")
                return
            result = handler(params)
            self._send_result(req_id, result)
        except Exception as e:
            log.error("Action %s failed: %s", action, traceback.format_exc())
            self._send_error(req_id, str(e))

    def _push_initial_status(self):
        """Send initial status as an event when frontend connects."""
        time.sleep(0.5)  # brief delay to let frontend initialize
        try:
            status = self._action_get_status({})
            self._send_event("initial_status", status)
        except Exception as e:
            log.error("Failed to push initial status: %s", e)

    def _send_result(self, req_id, data=None):
        msg = {"id": req_id, "ok": True}
        if data is not None:
            msg["data"] = data
        log.info("Sending result for req %s: %s", req_id, repr(msg)[:200])
        self.proto.send_response(msg)

    def _send_error(self, req_id, error):
        log.info("Sending error for req %s: %s", req_id, error)
        self.proto.send_response({"id": req_id, "ok": False, "error": error})

    def _send_event(self, event, data=None):
        msg = {"event": event}
        if data is not None:
            msg["data"] = data
        log.info("Sending event: %s", event)
        self.proto.send_event(msg)

    # ── Action handlers ──────────────────────────────────────

    def _action_get_status(self, params):
        # Pull keyboard identity and layout from the device (source of truth)
        # before verifying state, so cfg reflects what's actually there.
        changed = False
        mac, name = bluetooth.read_device_keyboard()
        if mac:
            if mac != self.cfg.get("keyboard_mac"):
                self.cfg["keyboard_mac"] = mac
                changed = True
            if name and name != self.cfg.get("keyboard_name"):
                self.cfg["keyboard_name"] = name
                changed = True
        elif self.cfg.get("keyboard_mac"):
            # Device has no keyboard (MAC file was stale or cleared) but
            # cfg still remembers one — wipe cfg so the UI shows reality.
            self.cfg["keyboard_mac"] = ""
            self.cfg["keyboard_name"] = ""
            changed = True
        device_layout_name = layout_patcher.read_current_layout_display_name(
            KEYBOARD_LAYOUTS
        )
        if device_layout_name and device_layout_name != self.cfg.get("keyboard_layout"):
            self.cfg["keyboard_layout"] = device_layout_name
            changed = True
        if changed:
            config.save(self.cfg)

        state = bluetooth.verify_device_state(self.cfg)
        return {
            **state,
            "keyboard_mac": self.cfg.get("keyboard_mac", ""),
            "keyboard_name": self.cfg.get("keyboard_name", ""),
            "keyboard_layout": self.cfg.get("keyboard_layout", "US English"),
            "layouts": [display for display, _ in KEYBOARD_LAYOUTS],
        }

    def _action_get_config(self, params):
        return {
            "keyboard_mac": self.cfg.get("keyboard_mac", ""),
            "keyboard_name": self.cfg.get("keyboard_name", ""),
            "keyboard_layout": self.cfg.get("keyboard_layout", "US English"),
        }

    def _stop_bt_service(self):
        """Stop the BT keyboard service to prevent conflicts with scan/pair."""
        mac = self.cfg.get("keyboard_mac")
        if mac and bluetooth.get_connection_status(mac):
            try:
                subprocess.run(
                    f"bluetoothctl disconnect {mac}",
                    shell=True, capture_output=True, timeout=5,
                )
                time.sleep(2)
            except Exception:
                pass
        subprocess.run(
            f"systemctl stop {service.SERVICE_NAME}",
            shell=True, capture_output=True, timeout=10,
        )

    def _start_bt_service(self):
        """Start the BT keyboard service if installed.

        Called after scan/pair/unpair to resume the monitor/reconnect loop.
        Non-fatal on failure — the service may not be installed yet.
        """
        if not self.cfg.get("service_installed"):
            return
        subprocess.run(
            f"systemctl start {service.SERVICE_NAME}",
            shell=True, capture_output=True, timeout=10,
        )

    def _action_scan_devices(self, params):
        timeout = params.get("timeout", 15)
        self._send_event("scan_started")
        self._stop_bt_service()
        # Do NOT restart the bt-keyboard service after scan — its startup
        # runs `systemctl restart bluetooth` which clears BlueZ's device
        # cache, making the just-scanned device "not available" for the
        # subsequent pair attempt. The pair flow restarts the service
        # itself after success or failure.
        devices = bluetooth.scan_devices(timeout=timeout)
        return {"devices": devices}

    def _action_pair_keyboard(self, params):
        mac = params["mac"]
        name = params.get("name") or mac
        old_mac = self.cfg.get("keyboard_mac") or None

        def passkey_cb(passkey):
            self._send_event("passkey", {"passkey": passkey})

        self._stop_bt_service()
        try:
            bluetooth.pair_and_connect(
                mac, old_mac=old_mac, passkey_callback=passkey_cb
            )
        except Exception:
            # Tell the UI so the passkey overlay hides; re-raise so the
            # response carries the error message.
            self._send_event("pair_error")
            self._start_bt_service()
            raise

        # Prefer the name BlueZ knows over whatever the UI passed, since
        # the UI's name may have come from an older scan cache.
        bluez_name = bluetooth.get_device_name(mac)
        if bluez_name:
            name = bluez_name

        # Save keyboard MAC for service auto-reconnect on reboot
        service.save_keyboard_mac(mac)

        self.cfg["keyboard_mac"] = mac
        self.cfg["keyboard_name"] = name
        config.save(self.cfg)

        # Resume the service's reconnect loop now that we have a new keyboard
        self._start_bt_service()

        self._send_event("pair_complete", {"mac": mac, "name": name})
        return {"mac": mac, "name": name, "connected": True}

    def _action_unpair_keyboard(self, params):
        self._stop_bt_service()
        try:
            mac = self.cfg.get("keyboard_mac")
            if mac:
                bluetooth.remove(mac)
            service.clear_keyboard_mac()
            self.cfg["keyboard_mac"] = ""
            self.cfg["keyboard_name"] = ""
            config.save(self.cfg)
        finally:
            # Restart so the reconnect loop stops trying the old MAC
            self._start_bt_service()
        return {"unpaired": True}

    def _action_set_layout(self, params):
        display_name = params["layout"]
        layout_key = LAYOUT_MAP.get(display_name)
        if not layout_key:
            raise RuntimeError(f"Unknown layout: {display_name}")

        def status_cb(msg):
            self._send_event("layout_status", {"message": msg})

        layout_patcher.apply_layout(layout_key, status_cb=status_cb)

        self.cfg["keyboard_layout"] = display_name
        config.save(self.cfg)

        # Schedule xochitl restart 3s out — decoupled from our process via
        # systemd-run so our response gets back to the UI first, and the
        # restart survives our backend exiting.
        try:
            subprocess.Popen(
                [
                    "systemd-run", "--on-active=3s", "--collect",
                    "/bin/systemctl", "restart", "xochitl",
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:
            log.error("Failed to schedule xochitl restart: %s", e)

        return {
            "layout": display_name,
            "needs_restart": True,
            "message": "Layout changed — restarting Move interface...",
        }

    def _action_install_service(self, params):
        """Enable Bluetooth keyboard support on the Move.

        We don't manually restart xochitl. If the BT operations cause
        xochitl to hang, its stock WatchdogSec=60 fires, Restart=on-failure
        brings it back, and our OnFailureJobMode=fail drop-in blocks the
        emergency-target cascade. Worst case is a brief flicker.
        """
        service.install()
        self.cfg["service_installed"] = True
        config.save(self.cfg)
        return {"service_installed": True}

    def _action_uninstall_service(self, params):
        """Disable Bluetooth keyboard support on the Move."""
        service.uninstall()
        self.cfg["service_installed"] = False
        self.cfg["keyboard_mac"] = ""
        self.cfg["keyboard_name"] = ""
        self.cfg["keyboard_layout"] = "US English"
        config.save(self.cfg)
        return {"service_installed": False}


def main():
    if len(sys.argv) < 2:
        print("Usage: main.py <socket_path>", file=sys.stderr)
        sys.exit(1)

    socket_path = sys.argv[1]
    backend = Backend(socket_path)
    backend.run()


if __name__ == "__main__":
    main()
