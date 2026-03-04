"""Binary patcher for libepaper.so keyboard layouts on reMarkable Move.

The Move's xochitl uses a custom EpaperEvdevKeyboardHandler in libepaper.so
with a built-in US keymap. This module patches the unicode values in that
keymap to support different keyboard layouts.

The US keymap is at a fixed offset in the binary. Each entry is 16 bytes:
  keycode(u16) + unicode(u16) + qtcode(u32) + modifiers(u8) + flags(u8)
  + special(u16) + padding(4 bytes)

We only patch the unicode field (bytes 2-3), preserving qtcode so that
Ctrl shortcuts (Ctrl+C, Ctrl+V, etc.) continue to work.
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

# Modifier constants matching the binary format
MOD_PLAIN = 0x00
MOD_SHIFT = 0x01


def _patch_binary(data, layout_key):
    """Patch the US keymap in libepaper.so binary data with a new layout.

    Returns the patched binary as a bytearray.
    """
    letters, punct = get_layout_mappings(layout_key)

    # Build a mapping of (keycode, modifier) → new_unicode
    patches = {}

    for kc, lower, upper, qt_key in letters:
        patches[(kc, MOD_PLAIN)] = lower
        patches[(kc, MOD_SHIFT)] = upper

    for kc, plain_u, plain_qt, shift_u, shift_qt in punct:
        patches[(kc, MOD_PLAIN)] = plain_u
        patches[(kc, MOD_SHIFT)] = shift_u

    if not patches:
        return data  # US layout, nothing to patch

    patched = bytearray(data)
    patch_count = 0

    for i in range(ENTRY_COUNT):
        offset = US_KEYMAP_OFFSET + i * ENTRY_SIZE
        # Read entry fields (little-endian on ARM64)
        keycode = struct.unpack_from('<H', patched, offset)[0]
        modifier = patched[offset + 8]  # modifiers byte

        new_unicode = patches.get((keycode, modifier))
        if new_unicode is not None:
            # Patch unicode field at bytes 2-3 (little-endian u16)
            struct.pack_into('<H', patched, offset + 2, new_unicode)
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

    if layout_key == "us":
        # Restore original — no patching needed
        status("Restoring US layout...")
        original = ssh.download_bytes(BACKUP_PATH)
        _deploy_binary(ssh, original, status)
    else:
        # Download the original backup and patch it
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
