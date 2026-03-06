"""Binary patcher for libepaper.so keyboard layouts on reMarkable Move.

The Move's xochitl uses a custom EpaperEvdevKeyboardHandler in libepaper.so
with a built-in US keymap. This module patches the unicode values in that
keymap to support different keyboard layouts.

The US keymap is at a fixed offset in the binary. Each entry is 16 bytes:
  keycode(u16) + unicode(u16) + qtcode(u32) + modifiers(u8) + flags(u8)
  + special(u16) + padding(4 bytes)

We only patch the unicode field (bytes 2-3), preserving qtcode so that
Ctrl shortcuts (Ctrl+C, Ctrl+V, etc.) continue to work.

NOTE: The Move's built-in keymap may not match a standard US layout.
For example, keycodes 26/27 ([/]) have dead key accents instead of
brackets. We match entries by keycode and modifier order (not by
expected unicode values) to handle these firmware-specific differences.
"""
import struct
import logging

from tools.generate_qmap import get_layout_mappings

log = logging.getLogger(__name__)

LIBEPAPER_PATH = "/usr/lib/plugins/platforms/libepaper.so"
BACKUP_PATH = "/home/root/.movewriter/libepaper.so.orig"
LAYOUT_FILE = "/home/root/.movewriter-layout"
SCRIPT_DIR = "/home/root/.movewriter"

# US keymap location in libepaper.so (ARM64, little-endian)
US_KEYMAP_OFFSET = 0x0250b0
ENTRY_SIZE = 16
ENTRY_COUNT = 211


def _patch_binary(data, layout_key):
    """Patch the US keymap in libepaper.so binary data with a new layout.

    Groups entries by keycode, sorts by modifier byte, and patches:
      - lowest modifier  → plain unicode
      - second modifier  → shift unicode
    This avoids relying on the existing unicode values (which may differ
    from standard US in the Move's firmware) or specific modifier byte
    values (which may differ from standard Qt).

    Returns the patched binary as bytes.
    """
    letters, punct = get_layout_mappings(layout_key)

    # Build target mappings: keycode → (plain_unicode, shift_unicode, plain_qt, shift_qt)
    targets = {}
    for kc, new_lower, new_upper, qt_key in letters:
        targets[kc] = (new_lower, new_upper, qt_key, qt_key)
    for kc, plain_u, plain_qt, shift_u, shift_qt in punct:
        targets[kc] = (plain_u, shift_u, plain_qt, shift_qt)

    # The Move firmware has dead key accents on some keys (e.g. keycodes 26/27
    # have ´/`/¨/~ instead of [/{/]/}). For layouts that don't remap these keys,
    # force them to standard US values so dead key behavior is removed.
    DEAD_KEY_DEFAULTS = {
        26: (0x5B, 0x7B, 0x5B, 0x7B),  # [ / {
        27: (0x5D, 0x7D, 0x5D, 0x7D),  # ] / }
    }
    for kc, vals in DEAD_KEY_DEFAULTS.items():
        if kc not in targets:
            targets[kc] = vals

    if not targets:
        return data

    # First pass: group binary entries by keycode (only keycodes we care about)
    entries_by_kc = {}
    for i in range(ENTRY_COUNT):
        offset = US_KEYMAP_OFFSET + i * ENTRY_SIZE
        keycode = struct.unpack_from('<H', data, offset)[0]
        if keycode in targets:
            mod = data[offset + 8]
            entries_by_kc.setdefault(keycode, []).append((offset, mod))

    # Second pass: patch plain and shift entries for each target keycode
    patched = bytearray(data)
    patch_count = 0

    # Qt dead key qtcode range — entries with these need qtcode/special patched too
    DEAD_KEY_QT_MIN = 0x01001250
    DEAD_KEY_QT_MAX = 0x01001263

    for kc, (new_plain, new_shift, plain_qt, shift_qt) in targets.items():
        entries = entries_by_kc.get(kc, [])
        if not entries:
            log.warning("No entries found for keycode %d", kc)
            continue

        # Sort by modifier byte: lowest = plain, next = shift
        entries.sort(key=lambda e: e[1])

        # Patch plain entry
        offset, mod = entries[0]
        struct.pack_into('<H', patched, offset + 2, new_plain)
        # If the existing qtcode is a dead key, replace it and clear special
        old_qt = struct.unpack_from('<I', patched, offset + 4)[0]
        if DEAD_KEY_QT_MIN <= old_qt <= DEAD_KEY_QT_MAX:
            struct.pack_into('<I', patched, offset + 4, plain_qt)
            struct.pack_into('<H', patched, offset + 10, 0)
        patch_count += 1

        # Patch shift entry
        if len(entries) >= 2:
            offset, mod = entries[1]
            struct.pack_into('<H', patched, offset + 2, new_shift)
            old_qt = struct.unpack_from('<I', patched, offset + 4)[0]
            if DEAD_KEY_QT_MIN <= old_qt <= DEAD_KEY_QT_MAX:
                struct.pack_into('<I', patched, offset + 4, shift_qt)
                struct.pack_into('<H', patched, offset + 10, 0)
            patch_count += 1

    log.info("Patched %d entries for layout '%s'", patch_count, layout_key)
    return bytes(patched)


def apply_layout(ssh, layout_key, status_cb=None):
    """Patch libepaper.so on device with the given layout and restart xochitl.

    Args:
        ssh: Connected SSH client
        layout_key: Layout identifier (e.g. 'de', 'gr', 'ru')
        status_cb: Optional callback(msg) for progress updates
    """
    def status(msg):
        log.info(msg)
        if status_cb:
            status_cb(msg)

    # Ensure backup directory exists
    ssh.exec(f"mkdir -p {SCRIPT_DIR}")

    # Create backup of original if it doesn't exist yet
    _, _, code = ssh.exec(f"test -f {BACKUP_PATH}")
    if code != 0:
        status("Backing up original libepaper.so...")
        ssh.exec(f"cp {LIBEPAPER_PATH} {BACKUP_PATH}")

    # Download the original backup and patch it
    # Even US gets patched to fix firmware dead keys on keycodes 26/27
    status("Downloading library...")
    original = ssh.download_bytes(BACKUP_PATH)

    status(f"Patching for {layout_key}...")
    patched = _patch_binary(original, layout_key)

    _deploy_binary(ssh, patched, status)

    # Save layout key to device
    ssh.upload_string(layout_key, LAYOUT_FILE)
    status("Layout applied")


def _deploy_binary(ssh, binary_data, status):
    """Stop xochitl, upload binary, restart xochitl."""
    status("Restarting display app...")
    ssh.exec("systemctl stop xochitl", timeout=15)

    try:
        ssh.exec("mount -o remount,rw /", timeout=10)
        try:
            ssh.upload_bytes(binary_data, LIBEPAPER_PATH)
        finally:
            ssh.exec("mount -o remount,ro /", timeout=10)
    finally:
        ssh.exec("systemctl start xochitl", timeout=15)


def restore_original(ssh):
    """Restore the original unpatched libepaper.so. Used during uninstall."""
    _, _, code = ssh.exec(f"test -f {BACKUP_PATH}")
    if code != 0:
        return  # No backup means no patching was ever done

    original = ssh.download_bytes(BACKUP_PATH)

    ssh.exec("systemctl stop xochitl", timeout=15)
    try:
        ssh.exec("mount -o remount,rw /", timeout=10)
        try:
            ssh.upload_bytes(original, LIBEPAPER_PATH)
        finally:
            ssh.exec("mount -o remount,ro /", timeout=10)
    finally:
        ssh.exec("systemctl start xochitl", timeout=15)

    # Clean up layout file
    ssh.exec(f"rm -f {LAYOUT_FILE}", timeout=5)
    ssh.exec(f"rm -f {BACKUP_PATH}", timeout=5)
