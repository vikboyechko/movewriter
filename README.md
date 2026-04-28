<p align="center">
  <img src="images/movewriter-logo.png" alt="MoveWriter" width="280">
</p>

<p align="center">
  Use a Bluetooth keyboard with your reMarkable Move.
</p>

---

> **Just want the app?** Download the ready-to-use version for Mac and Windows at [movewriter.com](https://movewriter.com). This repo is for developers who prefer to run from source.

---

<p align="center">
  <img src="images/movewriter-screenshot.jpg" alt="MoveWriter screenshot" width="480">
</p>

MoveWriter is a desktop app that connects to your reMarkable Move over USB and sets up Bluetooth keyboard support. Pair once, and your keyboard stays connected across reboots — no need to keep the app running.

## What it does

1. **Installs a lightweight service** on your Move that enables Bluetooth and loads the required kernel modules on every boot
2. **Pairs a Bluetooth keyboard** of your choice to the Move
3. **Auto-reconnects** the keyboard after the Move or keyboard is powered off and back on

## Requirements

- reMarkable Move connected via USB
- A Bluetooth keyboard (BT Classic or BLE)
- Python 3.10+
- macOS or Windows (for running the app)

## Setup

```bash
git clone https://github.com/yourusername/movewriter.git
cd movewriter
pip install -r requirements.txt
python main.py
```

## Usage

1. Connect your Move to your computer via USB
2. Open MoveWriter and click **Connect to Device**
   - The SSH password is found on your Move under Settings > Help > About > Copyrights and licenses
3. Click **Enable** in the Bluetooth Service section to set up the on-device service
4. Put your keyboard in pairing mode, click **Scan for Keyboards**, and pair it

That's it. You can close the app — your keyboard will reconnect automatically, even after rebooting the Move.

To switch keyboards or unpair, reopen the app and use **Change Keyboard** or **Unpair**. To remove Bluetooth keyboard support entirely, click **Disable** in the Bluetooth Service section.

## How it works

MoveWriter communicates with your Move over SSH (via the USB network interface at `10.11.99.1`). It uploads a small systemd service and shell script that:

- Loads the `btnxpuart` and `uhid` kernel modules
- Configures BlueZ for keyboard input (`UserspaceHID=true`, `ClassicBondedOnly=false`)
- Powers on the Bluetooth adapter
- Reconnects your saved keyboard on boot and monitors the connection

The service and script are installed to persistent storage on the Move, so they survive reboots and firmware updates to the `/etc` overlay.

## Keyboard Language

MoveWriter supports 24 keyboard languages. Select your language from the dropdown in the app, and it will be applied to the Move. The Move's UI will briefly restart for the new layout to take effect, then your keyboard works in the new language. The setting persists across reboots.

Supported languages: US English, UK English, German, French, Spanish, Italian, Portuguese, Brazilian, Dutch, Swedish, Norwegian, Danish, Finnish, Icelandic, Swiss German, Swiss French, Belgian, Russian, Ukrainian, Czech, Hungarian, Turkish, Greek, Hebrew.

## Native App (Experimental)

The optional **Install on Move** button (in the *Native App (Experimental)* section) installs MoveWriter as a native AppLoad app on the Move itself. With it installed, you can manage your keyboard directly on the device — no computer needed:

- Pair, unpair, and switch keyboards
- Change keyboard layout
- Enable/disable the Bluetooth keyboard service

Open it from the Move's hamburger menu (☰) → AppLoad → MoveWriter.

**Tested on Move OS 3.26.** The native app relies on community-maintained tools (XOVI and AppLoad) that are firmware-specific. To avoid breaking the install, **disable automatic updates** in your Move's settings. If a Move OS update happens, just uninstall the Native App from the desktop, update, and reinstall.

What gets installed under the hood:
- XOVI extension framework + AppLoad (via [Vellum](https://github.com/vellum-dev/vellum-cli))
- Python 3 (via entware) for the on-device backend
- The MoveWriter QML app and Python backend
- A small systemd service that reactivates XOVI on every boot
- xochitl crash-protection drop-ins (see below)

Pairing keyboards from the Native App can cause a brief screen flicker (~10s) on Move 3.26 due to a firmware quirk. The crash-protection drop-ins make this a recoverable flicker rather than a frozen device. For first-time keyboard pairing, the desktop app is smoother — pair from there once, then use the Native App for day-to-day management.

To remove everything cleanly, click **Uninstall** in the Native App section.

## Limitations

- After rebooting the Move, you may need to power-cycle the keyboard to wake it up for reconnection
- Pairing from the Native App can cause a brief screen flicker on Move OS 3.26 (firmware-side BlueZ/xochitl interaction). Recoverable, but pair from the desktop for the smoothest experience.

## PIN-Based keyboards

Some Bluetooth keyboards require a PIN code to pair. MoveWriter supports this for both BT Classic and BLE keyboards. When you select a keyboard that requires a PIN, MoveWriter will prompt you to enter the code. The app will then handle the pairing process using the provided PIN.

## License

[The Unlicense](LICENSE.md) — public domain. Do whatever you want.
