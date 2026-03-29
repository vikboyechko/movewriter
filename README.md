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

## Setup (Ubuntu)

```bash
git clone https://github.com/yourusername/movewriter.git
cd movewriter
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

You may also need to install the Tkinter system package if it's not already present:

```bash
sudo apt install python3-tk
```

## Usage

1. Connect your Move to your computer via USB
2. Open MoveWriter and click **Connect to Device**
   - The SSH password is found on your Move under Settings > Help > About > Copyrights and licenses
3. Click **Install** to set up the Bluetooth service
4. Put your keyboard in pairing mode, click **Scan for Keyboards**, and pair it

That's it. You can close the app — your keyboard will reconnect automatically, even after rebooting the Move.

To switch keyboards or unpair, reopen the app and use **Change Keyboard** or **Unpair**.

## How it works

MoveWriter communicates with your Move over SSH (via the USB network interface at `10.11.99.1`). It uploads a small systemd service and shell script that:

- Loads the `btnxpuart` and `uhid` kernel modules
- Configures BlueZ for keyboard input (`UserspaceHID=true`, `ClassicBondedOnly=false`)
- Powers on the Bluetooth adapter
- Reconnects your saved keyboard on boot and monitors the connection

The service and script are installed to persistent storage on the Move, so they survive reboots and firmware updates to the `/etc` overlay.

## Keyboard Language

MoveWriter supports 23 keyboard languages. Select your language from the dropdown in the app, and it will be applied to the Move immediately. The setting persists across reboots.

Supported languages: US English, UK English, German, French, Spanish, Italian, Portuguese, Brazilian, Dutch, Swedish, Norwegian, Danish, Finnish, Swiss German, Swiss French, Belgian, Russian, Ukrainian, Czech, Hungarian, Turkish, Greek, Hebrew.

## Building an AppImage (Ubuntu)

```bash
pip install python-appimage
python-appimage build app -p 3.10 --name MoveWriter \
  -x main.py core ui tools resources images \
  appimage
```

This produces a `MoveWriter-x86_64.AppImage` in the current directory. The `appimage/` directory contains the metadata, icon, and entrypoint.

## Limitations

- After rebooting the Move, you may need to power-cycle the keyboard to wake it up for reconnection

## PIN-Based keyboards

Some Bluetooth keyboards require a PIN code to pair. MoveWriter supports this for both BT Classic and BLE keyboards. When you select a keyboard that requires a PIN, MoveWriter will prompt you to enter the code. The app will then handle the pairing process using the provided PIN.

## License

[PolyForm Noncommercial 1.0.0](LICENSE.md) — free for personal and noncommercial use.
