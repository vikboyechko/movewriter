import os
import tkinter as tk
from tkinter import ttk
import threading

from ui import styles
from core import config, bluetooth, service_installer, layout_patcher
from core.service_installer import save_keyboard_mac

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_ERROR = "error"

STATUS_DOTS = {
    STATUS_PENDING: "\u25cb",  # ○
    STATUS_RUNNING: "\u25d4",  # ◔
    STATUS_DONE: "\u25cf",     # ●
    STATUS_ERROR: "\u2717",    # ✗
}

STATUS_COLORS = {
    STATUS_PENDING: styles.FG_DIM,
    STATUS_RUNNING: styles.WARNING,
    STATUS_DONE: styles.SUCCESS,
    STATUS_ERROR: styles.ERROR,
}

PADDING_X = 24

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

LAYOUT_NAMES = [name for name, _ in KEYBOARD_LAYOUTS]
LAYOUT_MAP = dict(KEYBOARD_LAYOUTS)


class PasskeyDialog(tk.Toplevel):
    """Modal dialog that displays a Bluetooth passkey for the user to type."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Bluetooth Passkey")
        self.configure(bg=styles.BG)
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        # Center on parent
        self.geometry("360x200")
        self.update_idletasks()
        px = parent.winfo_toplevel().winfo_rootx()
        py = parent.winfo_toplevel().winfo_rooty()
        pw = parent.winfo_toplevel().winfo_width()
        ph = parent.winfo_toplevel().winfo_height()
        x = px + (pw - 360) // 2
        y = py + (ph - 200) // 2
        self.geometry(f"+{x}+{y}")

        self.label = tk.Label(
            self, text="Passkey required",
            font=styles.FONT_HEADING, bg=styles.BG, fg=styles.FG,
        )
        self.label.pack(pady=(24, 8))

        self.passkey_label = tk.Label(
            self, text="------",
            font=("Menlo", 36, "bold"), bg=styles.BG, fg=styles.ACCENT,
        )
        self.passkey_label.pack(pady=(4, 8))

        self.instruction = tk.Label(
            self, text="Type this code on your keyboard, then press Enter.",
            font=styles.FONT_BODY, bg=styles.BG, fg=styles.FG_DIM,
            wraplength=300,
        )
        self.instruction.pack(pady=(0, 16))

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def show_passkey(self, passkey):
        self.passkey_label.configure(text=passkey)

    def close_with_success(self):
        try:
            self.grab_release()
            self.destroy()
        except Exception:
            pass

    def close_with_error(self, msg):
        try:
            self.grab_release()
            self.destroy()
        except Exception:
            pass

    def _on_close(self):
        try:
            self.grab_release()
            self.destroy()
        except Exception:
            pass


class MainScreen(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.configure(style="TFrame")

        self.sections = {}
        self.device_list = []
        self._monitor_active = False
        self._passkey_dialog = None

        self._build_ui()
        self._restore_state()

    # ── Build UI ──────────────────────────────────────────────

    def _build_ui(self):
        # Logo header
        logo_frame = ttk.Frame(self, style="TFrame")
        logo_frame.pack(fill="x", padx=PADDING_X, pady=(20, 4))

        logo_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "images", "movewriter-logo.png"
        )
        if os.path.exists(logo_path):
            from PIL import Image, ImageTk
            img = Image.open(logo_path)
            # Scale to 40px height, preserving aspect ratio
            target_h = 40
            scale = target_h / img.height
            img = img.resize((int(img.width * scale), target_h), Image.LANCZOS)
            self._logo_image = ImageTk.PhotoImage(img)
            ttk.Label(logo_frame, image=self._logo_image, background=styles.BG).pack(
                side="left"
            )

        # Separator
        sep = ttk.Frame(self, height=1)
        sep.pack(fill="x", padx=PADDING_X, pady=(8, 4))
        tk.Frame(sep, bg=styles.BORDER, height=1).pack(fill="x")

        # Build sections
        self._build_connection_section()
        self._build_service_section()
        self._build_keyboard_section()

        # Footer message
        ttk.Label(
            self,
            text="After pairing, your keyboard will stay connected even after closing this app.",
            style="Dim.TLabel",
            wraplength=400,
        ).pack(pady=(20, 5))

    # ── Card helper ────────────────────────────────────────────

    def _make_section(self, name, title):
        outer = ttk.Frame(self, style="Card.TFrame")
        outer.pack(fill="x", padx=PADDING_X, pady=(8, 0))

        border = tk.Frame(outer, bg=styles.BORDER, padx=1, pady=1)
        border.pack(fill="x")

        inner = ttk.Frame(border, style="Card.TFrame")
        inner.pack(fill="x")

        # Header row
        header = ttk.Frame(inner, style="Card.TFrame")
        header.pack(fill="x", padx=16, pady=(12, 8))

        ttk.Label(header, text=title, style="CardHeading.TLabel").pack(side="left")

        dot = ttk.Label(
            header,
            text=STATUS_DOTS[STATUS_PENDING],
            foreground=STATUS_COLORS[STATUS_PENDING],
            background=styles.BG_CARD,
            font=("Helvetica", 16),
        )
        dot.pack(side="right", padx=(8, 0))

        # Body
        body = ttk.Frame(inner, style="Card.TFrame")
        body.pack(fill="x", padx=16, pady=(0, 14))

        self.sections[name] = {"dot": dot, "status": STATUS_PENDING}

        return body

    def _set_section_status(self, name, status):
        sec = self.sections[name]
        sec["status"] = status
        if sec["dot"]:
            sec["dot"].configure(
                text=STATUS_DOTS[status],
                foreground=STATUS_COLORS[status],
            )

    # ── Section 1: Connection ─────────────────────────────────

    def _build_connection_section(self):
        body = self._make_section("connection", "Device")

        form = ttk.Frame(body, style="Card.TFrame")
        form.pack(fill="x")

        # IP row
        ip_row = ttk.Frame(form, style="Card.TFrame")
        ip_row.pack(fill="x", pady=(0, 6))
        ttk.Label(ip_row, text="IP Address", style="Card.TLabel").pack(anchor="w")
        self.ip_var = tk.StringVar(value=self.app.cfg.get("ip", "10.11.99.1"))
        self.ip_entry = styles.make_entry(ip_row, textvariable=self.ip_var, width=30)
        self.ip_entry.pack(fill="x", pady=(2, 0))

        # Password row
        pw_row = ttk.Frame(form, style="Card.TFrame")
        pw_row.pack(fill="x", pady=(0, 4))
        ttk.Label(pw_row, text="SSH Password", style="Card.TLabel").pack(anchor="w")
        self.pw_var = tk.StringVar(value=config.get_password(self.app.cfg))
        self.pw_entry = styles.make_entry(pw_row, textvariable=self.pw_var, show="*", width=30)
        self.pw_entry.pack(fill="x", pady=(2, 0))

        ttk.Label(
            form,
            text="Settings \u2192 Help \u2192 About \u2192 Copyrights and licenses",
            style="CardDim.TLabel",
        ).pack(anchor="w", pady=(0, 10))

        # Connect button + status
        btn_row = ttk.Frame(form, style="Card.TFrame")
        btn_row.pack(fill="x")
        self.connect_btn = ttk.Button(
            btn_row, text="Connect to Device", style="Accent.TButton", command=self._on_connect
        )
        self.connect_btn.pack(side="left")

        self.conn_status_var = tk.StringVar()
        self.conn_status_label = ttk.Label(
            btn_row, textvariable=self.conn_status_var, style="CardStatus.TLabel"
        )
        self.conn_status_label.pack(side="left", padx=(12, 0))

        # Bind Enter
        self.ip_entry.bind("<Return>", lambda e: self.pw_entry.focus())
        self.pw_entry.bind("<Return>", lambda e: self._on_connect())

    def _on_connect(self):
        ip = self.ip_var.get().strip()
        pw = self.pw_var.get().strip()
        if not ip:
            self._set_conn_status("Enter IP address", "Error.TLabel")
            return

        self.connect_btn.configure(state="disabled")
        self._set_conn_status("Connecting...", "Warning.TLabel")

        def worker():
            try:
                self.app.ssh.connect(ip, pw)
                self.after(0, self._on_connected, ip, pw)
            except Exception as e:
                self.after(0, self._on_connect_error, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_connected(self, ip, pw):
        self.app.cfg["ip"] = ip
        config.set_password(self.app.cfg, pw)
        config.save(self.app.cfg)
        self._set_conn_status("Connected", "Success.TLabel")
        self.connect_btn.configure(state="disabled")
        self._set_section_status("connection", STATUS_DONE)
        # Enable service and keyboard buttons now that we're connected
        self.install_btn.configure(state="normal")
        self.scan_btn.configure(state="normal")
        self.reconnect_btn.configure(state="normal")
        self.layout_combo.configure(state="readonly")
        self._verify_device_state()
        self._start_connection_monitor()

    def _on_connect_error(self, msg):
        self.connect_btn.configure(state="normal")
        short = msg.split("\n")[0][:80]
        self._set_conn_status(f"Failed: {short}", "Error.TLabel")
        self._set_section_status("connection", STATUS_ERROR)

    def _set_conn_status(self, text, label_style="CardStatus.TLabel"):
        self.conn_status_var.set(text)
        self.conn_status_label.configure(style=label_style)

    def _start_connection_monitor(self):
        self._monitor_active = True
        self._check_connection()

    def _check_connection(self):
        if not self._monitor_active:
            return

        def ping():
            try:
                self.app.ssh.exec("true", timeout=3)
                if self._monitor_active:
                    self.after(3000, self._check_connection)
            except Exception:
                if self._monitor_active:
                    self.after(0, self._on_disconnected)

        threading.Thread(target=ping, daemon=True).start()

    def _on_disconnected(self):
        self._monitor_active = False
        self.connect_btn.configure(state="normal")
        self._set_conn_status("Disconnected", "Error.TLabel")
        self._set_section_status("connection", STATUS_ERROR)
        self._set_section_status("service", STATUS_PENDING)
        self.svc_status_var.set("")
        self._set_section_status("keyboard", STATUS_PENDING)
        self.kb_status_var.set("")
        # Disable service and keyboard buttons until reconnected
        self.install_btn.configure(state="disabled")
        self.scan_btn.configure(state="disabled")
        self.reconnect_btn.configure(state="disabled")
        self.layout_combo.configure(state="disabled")

    # ── Section 2: Bluetooth Service ──────────────────────────

    def _build_service_section(self):
        body = self._make_section("service", "Bluetooth Service")

        ttk.Label(
            body,
            text="Uploads the keyboard service and configures Bluetooth on your Move.",
            style="CardStatus.TLabel",
            wraplength=400,
        ).pack(anchor="w", pady=(0, 8))

        btn_row = ttk.Frame(body, style="Card.TFrame")
        btn_row.pack(fill="x")

        self.install_btn = ttk.Button(
            btn_row, text="Install", style="Accent.TButton", command=self._run_service_toggle,
            state="disabled",
        )
        self.install_btn.pack(side="left")

        self.svc_status_var = tk.StringVar()
        ttk.Label(btn_row, textvariable=self.svc_status_var, style="CardStatus.TLabel").pack(
            side="left", padx=(12, 0)
        )

    def _run_service_toggle(self):
        if not self.app.ssh.is_connected:
            self.svc_status_var.set("Connect to device first.")
            return

        is_installed = self.app.cfg.get("service_installed", False)
        self._set_section_status("service", STATUS_RUNNING)
        self.install_btn.configure(state="disabled")
        self._monitor_active = False

        if is_installed:
            self.svc_status_var.set("Uninstalling...")

            def worker():
                try:
                    service_installer.uninstall(self.app.ssh)
                    self.after(0, self._service_uninstalled)
                except Exception as e:
                    self.after(0, self._service_error, str(e))
        else:
            self.svc_status_var.set("Installing...")

            def worker():
                try:
                    service_installer.install(self.app.ssh)
                    self.after(0, self._service_installed)
                except Exception as e:
                    self.after(0, self._service_error, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _service_installed(self):
        self._set_section_status("service", STATUS_DONE)
        self.svc_status_var.set("Installed")
        self.install_btn.configure(state="normal", text="Uninstall")
        self.app.cfg["service_installed"] = True
        config.save(self.app.cfg)
        mac = self.app.cfg.get("keyboard_mac")
        if mac:
            def save_mac():
                try:
                    save_keyboard_mac(self.app.ssh, mac)
                except Exception:
                    pass
            threading.Thread(target=save_mac, daemon=True).start()
        self._start_connection_monitor()

    def _service_uninstalled(self):
        self._set_section_status("service", STATUS_PENDING)
        self.svc_status_var.set("")
        self.install_btn.configure(state="normal", text="Install")
        self.app.cfg["service_installed"] = False
        self.app.cfg["setup_complete"] = False
        config.save(self.app.cfg)
        self._start_connection_monitor()

    def _service_error(self, msg):
        self._set_section_status("service", STATUS_ERROR)
        self.svc_status_var.set(f"Error: {msg[:100]}")
        self.install_btn.configure(state="normal")
        self._start_connection_monitor()

    # ── Section 3: Keyboard ───────────────────────────────────

    def _build_keyboard_section(self):
        body = self._make_section("keyboard", "Keyboard")
        self.kb_body = body

        # ── Saved keyboard view ──
        self.kb_saved_frame = ttk.Frame(body, style="Card.TFrame")

        self.kb_name_var = tk.StringVar()
        ttk.Label(
            self.kb_saved_frame, textvariable=self.kb_name_var,
            style="Card.TLabel", font=styles.FONT_HEADING,
        ).pack(anchor="w")

        self.kb_status_var = tk.StringVar()
        ttk.Label(
            self.kb_saved_frame, textvariable=self.kb_status_var,
            style="CardStatus.TLabel",
        ).pack(anchor="w", pady=(2, 8))

        # Layout dropdown
        layout_row = ttk.Frame(self.kb_saved_frame, style="Card.TFrame")
        layout_row.pack(fill="x", pady=(0, 8))
        ttk.Label(layout_row, text="Language", style="Card.TLabel").pack(side="left")
        self.layout_var = tk.StringVar()
        self.layout_combo = ttk.Combobox(
            layout_row, textvariable=self.layout_var,
            values=LAYOUT_NAMES, state="readonly", width=20,
        )
        self.layout_combo.pack(side="left", padx=(8, 0))
        self.layout_combo.set(self.app.cfg.get("keyboard_layout", "US English"))
        self.layout_combo.bind("<<ComboboxSelected>>", self._on_layout_changed)

        self.layout_status_var = tk.StringVar()
        ttk.Label(
            layout_row, textvariable=self.layout_status_var,
            style="CardStatus.TLabel",
        ).pack(side="left", padx=(8, 0))

        saved_btn_row = ttk.Frame(self.kb_saved_frame, style="Card.TFrame")
        saved_btn_row.pack(fill="x")

        self.reconnect_btn = ttk.Button(
            saved_btn_row, text="Reconnect", style="Blue.TButton",
            command=self._run_reconnect, state="disabled",
        )
        self.reconnect_btn.pack(side="left")

        self.forget_btn = ttk.Button(
            saved_btn_row, text="Change Keyboard",
            command=self._show_scan_view,
        )
        self.forget_btn.pack(side="left", padx=(8, 0))

        self.unpair_btn = ttk.Button(
            saved_btn_row, text="Unpair",
            command=self._run_unpair,
        )
        self.unpair_btn.pack(side="left", padx=(8, 0))

        # ── Scan/pair view ──
        self.kb_scan_frame = ttk.Frame(body, style="Card.TFrame")

        # Back link (shown only when there's a saved keyboard to go back to)
        self.cancel_scan_link = ttk.Label(
            self.kb_scan_frame, text="\u2190 Back to saved keyboard",
            style="CardStatus.TLabel", foreground=styles.ACCENT,
            cursor="hand2",
        )
        self.cancel_scan_link.bind("<Button-1>", lambda e: self._show_saved_view())
        # Not packed yet — _show_scan_view controls visibility

        self.kb_scan_instructions = ttk.Label(
            self.kb_scan_frame,
            text=(
                "Put your keyboard in pairing mode. "
                "If it's connected to another device, remove it there first."
            ),
            style="CardStatus.TLabel",
            wraplength=400,
        ).pack(anchor="w", pady=(0, 8))

        scan_row = ttk.Frame(self.kb_scan_frame, style="Card.TFrame")
        scan_row.pack(fill="x")

        self.scan_btn = ttk.Button(
            scan_row, text="Scan for Keyboards", style="Blue.TButton",
            command=self._run_scan, state="disabled",
        )
        self.scan_btn.pack(side="left")

        self.scan_status_var = tk.StringVar()
        ttk.Label(
            scan_row, textvariable=self.scan_status_var,
            style="CardStatus.TLabel",
        ).pack(side="left", padx=(12, 0))

        self.device_listbox = tk.Listbox(
            self.kb_scan_frame, height=5,
            bg=styles.BG_CARD, fg=styles.FG, font=styles.FONT_BODY,
            selectbackground=styles.ACCENT, selectforeground="white",
            borderwidth=1, highlightthickness=0, relief="solid",
            selectmode="browse",
        )

        pair_row = ttk.Frame(self.kb_scan_frame, style="Card.TFrame")
        self.pair_row = pair_row

        self.pair_btn = ttk.Button(
            pair_row, text="Pair Selected", style="Blue.TButton",
            command=self._run_pair,
        )
        self.pair_btn.pack(side="left")

        self.pair_status_var = tk.StringVar()
        ttk.Label(
            pair_row, textvariable=self.pair_status_var,
            style="CardStatus.TLabel",
        ).pack(side="left", padx=(12, 0))

        # Show the right view
        if self.app.cfg.get("keyboard_mac"):
            self._show_saved_view()
        else:
            self._show_scan_view()

    def _show_saved_view(self):
        self.kb_scan_frame.pack_forget()
        name = self.app.cfg.get("keyboard_name", "Unknown")
        self.kb_name_var.set(name)
        self.kb_status_var.set("")
        self.kb_saved_frame.pack(fill="x")

    def _show_scan_view(self):
        self._old_keyboard_mac = self.app.cfg.get("keyboard_mac")
        self.kb_saved_frame.pack_forget()
        self.scan_status_var.set("")
        self.pair_status_var.set("")
        self.device_listbox.delete(0, tk.END)
        self.device_listbox.pack_forget()
        self.pair_row.pack_forget()
        self.pair_btn.configure(state="normal")
        if self.app.cfg.get("keyboard_mac"):
            self.cancel_scan_link.pack(anchor="w", pady=(16, 4), before=self.kb_scan_instructions)
        else:
            self.cancel_scan_link.pack_forget()
        self.kb_scan_frame.pack(fill="x")

    def _run_scan(self):
        if not self.app.ssh.is_connected:
            self.scan_status_var.set("Connect to device first.")
            return
        self.scan_btn.configure(state="disabled")
        self.scan_status_var.set("Scanning for 15 seconds...")
        self.device_listbox.delete(0, tk.END)
        self.device_listbox.pack_forget()
        self.pair_row.pack_forget()

        def worker():
            try:
                devices = bluetooth.scan_devices(self.app.ssh, timeout=15)
                self.after(0, self._scan_done, devices)
            except Exception as e:
                self.after(0, self._scan_error, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _scan_done(self, devices):
        self.scan_btn.configure(state="normal")
        self.device_list = devices
        self.device_listbox.delete(0, tk.END)
        if not devices:
            self.scan_status_var.set("No devices found. Try again.")
            return
        self.scan_status_var.set(f"Found {len(devices)} device(s). Select yours:")
        for d in devices:
            self.device_listbox.insert(tk.END, f"{d['name']}  ({d['mac']})")
        self.device_listbox.pack(fill="x", pady=(8, 8))
        self.pair_btn.configure(state="normal")
        self.pair_status_var.set("")
        self.pair_row.pack(fill="x")

    def _scan_error(self, msg):
        self.scan_btn.configure(state="normal")
        self.scan_status_var.set(f"Scan error: {msg[:100]}")

    def _run_pair(self):
        sel = self.device_listbox.curselection()
        if not sel:
            self.pair_status_var.set("Select a device first.")
            return
        if not self.app.ssh.is_connected:
            self.pair_status_var.set("Connect to device first.")
            return
        device = self.device_list[sel[0]]
        self.pair_btn.configure(state="disabled")
        self._set_section_status("keyboard", STATUS_RUNNING)
        self.pair_status_var.set(f"Pairing with {device['name']}...")

        def on_passkey(passkey):
            self.after(0, self._show_passkey_dialog, passkey)

        def worker():
            try:
                old_mac = getattr(self, '_old_keyboard_mac', None)
                bluetooth.pair_and_connect(
                    self.app.ssh, device["mac"],
                    old_mac=old_mac, passkey_callback=on_passkey,
                )
                save_keyboard_mac(self.app.ssh, device["mac"])
                self.after(0, self._pair_done, device)
            except Exception as e:
                self.after(0, self._pair_error, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _show_passkey_dialog(self, passkey):
        if self._passkey_dialog is not None:
            try:
                self._passkey_dialog.show_passkey(passkey)
                return
            except Exception:
                self._passkey_dialog = None
        self._passkey_dialog = PasskeyDialog(self)
        self._passkey_dialog.show_passkey(passkey)

    def _pair_done(self, device):
        if self._passkey_dialog is not None:
            self._passkey_dialog.close_with_success()
            self._passkey_dialog = None
        self._set_section_status("keyboard", STATUS_DONE)
        self.app.cfg["keyboard_mac"] = device["mac"]
        self.app.cfg["keyboard_name"] = device["name"]
        config.save(self.app.cfg)
        self._show_saved_view()
        self.kb_status_var.set("Connected")

    def _pair_error(self, msg):
        if self._passkey_dialog is not None:
            self._passkey_dialog.close_with_error(msg)
            self._passkey_dialog = None
        self._set_section_status("keyboard", STATUS_ERROR)
        self.pair_btn.configure(state="normal")
        self.pair_status_var.set(f"Pair error: {msg[:100]}")

    def _run_reconnect(self):
        mac = self.app.cfg.get("keyboard_mac")
        name = self.app.cfg.get("keyboard_name", "keyboard")
        if not mac:
            return
        if not self.app.ssh.is_connected:
            self.kb_status_var.set("Connect to device first.")
            return
        self.reconnect_btn.configure(state="disabled")
        self._set_section_status("keyboard", STATUS_RUNNING)
        self.kb_status_var.set("Reconnecting...")

        def worker():
            try:
                bluetooth.connect(self.app.ssh, mac)
                self.after(0, self._reconnect_done, name)
            except Exception as e:
                self.after(0, self._reconnect_error, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _reconnect_done(self, name):
        self._set_section_status("keyboard", STATUS_DONE)
        self.reconnect_btn.configure(state="normal")
        self.kb_status_var.set("Connected")

    def _reconnect_error(self, msg):
        self._set_section_status("keyboard", STATUS_ERROR)
        self.reconnect_btn.configure(state="normal")
        self.kb_status_var.set(f"Reconnect failed: {msg[:80]}")

    def _run_unpair(self):
        mac = self.app.cfg.get("keyboard_mac")
        if not mac:
            return
        if not self.app.ssh.is_connected:
            self.kb_status_var.set("Connect to device first.")
            return
        self.unpair_btn.configure(state="disabled")
        self.kb_status_var.set("Unpairing...")

        def worker():
            try:
                bluetooth.remove(self.app.ssh, mac)
                self.app.ssh.exec(
                    f"rm -f {service_installer.KEYBOARD_MAC_PATH}", timeout=5
                )
                self.after(0, self._unpair_done)
            except Exception as e:
                self.after(0, self._unpair_error, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _unpair_done(self):
        self.app.cfg.pop("keyboard_mac", None)
        self.app.cfg.pop("keyboard_name", None)
        config.save(self.app.cfg)
        self._set_section_status("keyboard", STATUS_PENDING)
        self._show_scan_view()

    def _unpair_error(self, msg):
        self.unpair_btn.configure(state="normal")
        self.kb_status_var.set(f"Unpair failed: {msg[:80]}")

    # ── Keyboard layout ──────────────────────────────────────

    def _on_layout_changed(self, event=None):
        display_name = self.layout_var.get()
        layout_key = LAYOUT_MAP.get(display_name, "us")

        # Save to local config immediately
        self.app.cfg["keyboard_layout"] = display_name
        config.save(self.app.cfg)

        if not self.app.ssh.is_connected:
            self.layout_status_var.set("Saved (apply on next connect)")
            return

        self.layout_combo.configure(state="disabled")
        self.layout_status_var.set("Applying...")

        def on_status(msg):
            self.after(0, self.layout_status_var.set, msg)

        def worker():
            try:
                layout_patcher.apply_layout(
                    self.app.ssh, layout_key, status_cb=on_status,
                )
                self.after(0, self._layout_applied)
            except Exception as e:
                self.after(0, self._layout_error, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _layout_applied(self):
        self.layout_combo.configure(state="readonly")
        self.layout_status_var.set("Applied")

    def _layout_error(self, msg):
        self.layout_combo.configure(state="readonly")
        self.layout_status_var.set(f"Error: {msg[:60]}")

    # ── State restoration ─────────────────────────────────────

    def _restore_state(self):
        if self.app.cfg.get("service_installed"):
            self.svc_status_var.set("Connect to verify")

    def _verify_device_state(self):
        self._apply_config_state()

        def worker():
            try:
                state = bluetooth.verify_device_state(self.app.ssh, self.app.cfg)
                self.after(0, self._apply_verified_state, state)
            except Exception:
                pass
            # Sync keyboard layout if needed
            self._sync_layout_if_needed()

        threading.Thread(target=worker, daemon=True).start()

    def _sync_layout_if_needed(self):
        """Apply saved layout to device if it doesn't match."""
        display_name = self.app.cfg.get("keyboard_layout", "US English")
        layout_key = LAYOUT_MAP.get(display_name, "us")

        # Check what layout the device currently has
        try:
            out, _, code = self.app.ssh.exec(
                f"cat {layout_patcher.LAYOUT_FILE} 2>/dev/null", timeout=5,
            )
            device_layout = out.strip() if code == 0 else "us"
        except Exception:
            device_layout = "us"

        if device_layout == layout_key:
            return  # Already in sync

        # Apply the saved layout
        self.after(0, self.layout_combo.configure, {"state": "disabled"})
        self.after(0, self.layout_status_var.set, "Syncing layout...")
        try:
            layout_patcher.apply_layout(self.app.ssh, layout_key)
            self.after(0, self._layout_applied)
        except Exception as e:
            self.after(0, self._layout_error, str(e))

    def _apply_verified_state(self, state):
        cfg = self.app.cfg
        changed = False

        if state["service_installed"]:
            self._set_section_status("service", STATUS_DONE)
            self.svc_status_var.set("Installed")
            self.install_btn.configure(text="Uninstall")
        elif cfg.get("service_installed"):
            self._set_section_status("service", STATUS_ERROR)
            self.svc_status_var.set("Bluetooth Service was removed")
            self.install_btn.configure(text="Install")
            cfg["service_installed"] = False
            changed = True
        else:
            self._set_section_status("service", STATUS_PENDING)
            self.svc_status_var.set("")

        saved_mac = cfg.get("keyboard_mac")
        if saved_mac:
            if state["keyboard_connected"]:
                self._set_section_status("keyboard", STATUS_DONE)
                self._show_saved_view()
                self.kb_status_var.set("Connected")
            elif state["keyboard_paired"]:
                self._set_section_status("keyboard", STATUS_RUNNING)
                self._show_saved_view()
                self.kb_status_var.set("Paired but not connected")
            else:
                # Pairing not detected — don't clear config, the service
                # re-pairs on boot and pairing data is volatile
                self._set_section_status("keyboard", STATUS_RUNNING)
                self._show_saved_view()
                self.kb_status_var.set("Not connected")

        if changed:
            config.save(cfg)

    def _apply_config_state(self):
        if self.app.cfg.get("service_installed"):
            self._set_section_status("service", STATUS_DONE)
            self.svc_status_var.set("Installed")
            self.install_btn.configure(text="Uninstall")
        else:
            self._set_section_status("service", STATUS_PENDING)
            self.svc_status_var.set("")
            self.install_btn.configure(text="Install")

        if self.app.cfg.get("keyboard_mac"):
            self._set_section_status("keyboard", STATUS_DONE)
            self._show_saved_view()
        else:
            self._set_section_status("keyboard", STATUS_PENDING)
            self._show_scan_view()
