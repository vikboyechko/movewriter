"""Keyboard layout support for the reMarkable Move.

Adapted from movewriterapp/core/layout_patcher.py — replaces SSH file
transfers with local file access. Keep the two in sync.

Two firmware generations need two different mechanisms:

**Legacy firmware (3.26 / 3.27)**: xochitl's libepaper.so has a single
built-in US keymap at a fixed offset (0x0250b0). Layouts are applied by
binary-patching the unicode values in that keymap.

**Multi-locale firmware (2026-09 builds and later; verified on
3.29.0.152)**: the firmware ships built-in keymaps for en_UK, de_DE,
fr_FR, it_IT, es_ES, no_DK, no_NO, no_SV (Swedish) and fi_FI, selected
at runtime from the `InputLocale` key in the [General] section of
/home/root/.config/remarkable/xochitl.conf. Without that key the
firmware falls back to US (Bluetooth keyboards provide no language —
the root cause of "Swedish selected, å/ä/ö produce US punctuation").
For firmware locales we select the built-in keymap via InputLocale and
binary-patch exactly two keycodes inside that firmware table (kc41/kc43,
whose positions differ between the firmware's ISO tables and standard
Bluetooth keyboards; kc86 is already correct).

en_US is deliberately NOT in FIRMWARE_LOCALES: the firmware's en_US
table has dead-key accents on kc26/27 and a broken grave key (kc41),
which the binary patch fixes together with InputLocale=en_US.

IMPORTANT: this app runs inside xochitl (AppLoad), so it must not restart
xochitl itself. The conf write is scheduled as a detached systemd-run job
that waits for xochitl to exit, applies the setting, and starts xochitl
again — writing while xochitl runs would be clobbered by its QSettings
cache on exit. The binary change and layout file are written immediately;
the UI tells the user that the Move interface restarts.

Backup safety across OS updates: the libepaper backup is stamped with
/etc/version when taken. If the version changes, the backup is stale
(from a different firmware) and is re-taken from the live binary, which
is stock after an OTA.
"""
import hashlib
import logging
import os
import re
import shutil
import struct
import subprocess
from pathlib import Path

# Import layout mappings — the tools directory is bundled with the backend
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tools.generate_qmap import get_layout_mappings

log = logging.getLogger(__name__)

LIBEPAPER_PATH = "/usr/lib/plugins/platforms/libepaper.so"
BACKUP_PATH = "/home/root/.movewriter/libepaper.so.orig"
BACKUP_VERSION_PATH = "/home/root/.movewriter/libepaper.so.version"
LAYOUT_FILE = "/home/root/.movewriter-layout"
SCRIPT_DIR = "/home/root/.movewriter"
XOCHITL_CONF = "/home/root/.config/remarkable/xochitl.conf"
LOCALE_APPLY_SCRIPT = "/home/root/.movewriter/apply-locale.sh"

# US keymap location in legacy libepaper.so (ARM64, little-endian)
US_KEYMAP_OFFSET = 0x0250b0
ENTRY_SIZE = 16
ENTRY_COUNT = 211

# Marker for multi-locale firmware: the dynamic symbol table references
# built-in per-locale keymaps (EpaperEvdevKeyboardMap::Locale::*::keymap).
MULTI_LOCALE_MARKER = b"EpaperEvdevKeyboardMap6Locale"

# Layout key -> InputLocale value understood by multi-locale firmware.
# "us" is deliberately absent — see module docstring.
FIRMWARE_LOCALES = {
    "uk": "en_UK",
    "de": "de_DE",
    "fr": "fr_FR",
    "it": "it_IT",
    "es": "es_ES",
    "no": "no_NO",
    "dk": "no_DK",
    "sv": "no_SV",
    "fi": "fi_FI",
}

# Fingerprints that identify the firmware's built-in table for each
# locale: (keycode, modifier byte, unicode) triples verified in the
# 3.29.0.152 binary. All are distinct across the nine tables.
LOCALE_FINGERPRINTS = {
    "uk": ((4, 1, 0xA3), (41, 0, 0x23)),
    "de": ((26, 0, 0xFC),),
    "fr": ((40, 0, 0xF9),),
    "it": ((41, 0, 0xF9),),
    "es": ((39, 0, 0xF1),),
    "sv": ((26, 0, 0xE5), (39, 0, 0xF6), (40, 0, 0xE4)),
    "fi": ((26, 0, 0xE5), (39, 0, 0xF6), (40, 0, 0xE4)),
    "no": ((26, 0, 0xE5), (39, 0, 0xF8)),
    "dk": ((26, 0, 0xE5), (39, 0, 0xE6)),
}

# Keycodes whose position differs between the firmware's ISO tables and
# standard Bluetooth keyboards. These are patched inside the firmware's
# own table; everything else (dead keys, AltGr characters) is kept.
LOCALE_TABLE_FIX_KEYCODES = (41, 43)


class LayoutError(Exception):
    """Raised when a layout cannot be applied safely."""


def _run(cmd, timeout=10):
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=timeout
    )
    return result.stdout, result.stderr, result.returncode


# ══════════════════════════════════════════════════════════════════════
# Keymap table location (keep in sync with core/layout_patcher.py)
# ══════════════════════════════════════════════════════════════════════

# Every built-in keymap table starts with the Escape entry:
# keycode=1, unicode=0xFFFF, qtcode=0x01000000, rest zero.
_ESCAPE_ENTRY = struct.pack("<HHIBBH", 1, 0xFFFF, 0x01000000, 0, 0, 0)


def _find_table_starts(data):
    """Offsets of every built-in keymap table. Each table begins with the
    Escape entry (keycode=1, unicode=0xFFFF, qtcode=0x01000000)."""
    starts = []
    for m in re.finditer(re.escape(_ESCAPE_ENTRY), data):
        if m.start() % 4 == 0:
            starts.append(m.start())
    return starts


def _valid_entry(data, pos):
    """True if the 16 bytes at pos look like a keymap entry."""
    keycode, uni = struct.unpack_from("<HH", data, pos)
    qt = struct.unpack_from("<I", data, pos + 4)[0]
    mod, flags = data[pos + 8], data[pos + 9]
    special = struct.unpack_from("<H", data, pos + 10)[0]
    if keycode == 0 or keycode > 0x1FF:
        return False
    if mod > 0x0F or flags > 0x0F or special > 0x1F:
        return False
    key_code = qt & 0xFFFFFF
    return (
        qt == 0 or qt == uni or 0x20 <= qt <= 0x17F or qt == 0xFFFF
        or qt == 0x01FFFFFF  # Key_Unknown
        or (1 <= (qt >> 24) <= 0x3F and key_code <= 0x100126F)
    )


def _table_bounds(data, offset, next_start=None):
    """Validate a keymap table at offset. Return entry count, or 0 if the
    bytes do not look like a keymap table. The table ends at next_start
    (the next table's Escape entry) or at the first invalid entry."""
    if offset + ENTRY_SIZE > len(data):
        return 0
    if data[offset:offset + len(_ESCAPE_ENTRY)] != _ESCAPE_ENTRY:
        return 0
    end = len(data) - ENTRY_SIZE
    if next_start is not None:
        end = min(end, next_start)
    count = 1
    while offset + (count + 1) * ENTRY_SIZE <= end:
        if not _valid_entry(data, offset + count * ENTRY_SIZE):
            break
        count += 1
    return count if count >= 200 else 0


def _is_us_table(data, offset, count):
    """True if the table maps Shift+2 to '@' (the US layout trait)."""
    for i in range(count):
        pos = offset + i * ENTRY_SIZE
        if struct.unpack_from("<H", data, pos)[0] != 3:
            continue
        if data[pos + 8] == 1:  # modifier byte 1 = shift
            return struct.unpack_from("<H", data, pos + 2)[0] == 0x40
    return False


def _locate_keymap(data):
    """Return (offset, entry_count) of the built-in US keymap in the
    libepaper.so binary. Raise LayoutError if it cannot be found safely."""
    count = _table_bounds(data, US_KEYMAP_OFFSET)
    if count and _is_us_table(data, US_KEYMAP_OFFSET, count):
        return US_KEYMAP_OFFSET, min(count, ENTRY_COUNT)

    starts = _find_table_starts(data)
    for i, offset in enumerate(starts):
        next_start = starts[i + 1] if i + 1 < len(starts) else None
        count = _table_bounds(data, offset, next_start)
        if count and _is_us_table(data, offset, count):
            return offset, count

    raise LayoutError(
        "Could not find the keyboard keymap in libepaper.so — this "
        "firmware is not supported for binary layout patching"
    )


def _find_locale_table(data, layout_key):
    """Return (offset, entry_count) of the firmware's built-in table for
    layout_key, or None if it cannot be identified."""
    checks = LOCALE_FINGERPRINTS.get(layout_key)
    if not checks:
        return None
    starts = _find_table_starts(data)
    for i, offset in enumerate(starts):
        next_start = starts[i + 1] if i + 1 < len(starts) else None
        count = _table_bounds(data, offset, next_start)
        if not count:
            continue
        entries = {}
        for j in range(count):
            pos = offset + j * ENTRY_SIZE
            kc = struct.unpack_from("<H", data, pos)[0]
            entries[(kc, data[pos + 8])] = struct.unpack_from("<H", data, pos + 2)[0]
        if all(entries.get((kc, mod)) == uni for kc, mod, uni in checks):
            return offset, count
    return None


# ══════════════════════════════════════════════════════════════════════
# Binary patching
# ══════════════════════════════════════════════════════════════════════

# Qt dead key qtcode range. In this firmware a dead key is marked by a
# Key_Dead_* qtcode AND special (offset+10) == 1; composition with the
# next keystroke is keyed off the dead-key TYPE the handler recognises.
DEAD_KEY_QT_MIN = 0x01001250
DEAD_KEY_QT_MAX = 0x01001263


def _patch_level(patched, offset, new_uni, new_qt):
    """Patch one keymap entry. Sets a dead key when the target qtcode is a
    Key_Dead_* code, clears the dead marker when turning a stock dead key
    into a normal one, replaces a broken Key_Unknown qtcode, and otherwise
    leaves the qtcode untouched so Ctrl shortcuts keep working."""
    struct.pack_into('<H', patched, offset + 2, new_uni)
    old_qt = struct.unpack_from('<I', patched, offset + 4)[0]
    target_dead = DEAD_KEY_QT_MIN <= new_qt <= DEAD_KEY_QT_MAX
    old_dead = DEAD_KEY_QT_MIN <= old_qt <= DEAD_KEY_QT_MAX
    if target_dead or old_dead or old_qt == 0x01FFFFFF:
        struct.pack_into('<I', patched, offset + 4, new_qt)
        struct.pack_into('<H', patched, offset + 10, 1 if target_dead else 0)


def _patch_entries(patched, offset, count, targets):
    """Patch plain and shift entries for each target keycode inside the
    table at offset. Entries are grouped by keycode and sorted by
    modifier byte (lowest = plain, next = shift). targets values are
    (plain_unicode, shift_unicode, plain_qt, shift_qt).
    Returns (patched, missing) counts.
    """
    groups = {}
    for i in range(count):
        pos = offset + i * ENTRY_SIZE
        keycode = struct.unpack_from('<H', patched, pos)[0]
        if keycode in targets:
            groups.setdefault(keycode, []).append((pos, patched[pos + 8]))

    patched_n = 0
    missing = 0
    for kc, (new_plain, new_shift, plain_qt, shift_qt) in targets.items():
        entries = groups.get(kc, [])
        if not entries:
            log.warning("No entries found for keycode %d", kc)
            missing += 1
            continue
        entries.sort(key=lambda e: e[1])
        _patch_level(patched, entries[0][0], new_plain, plain_qt)
        patched_n += 1
        if len(entries) >= 2:
            _patch_level(patched, entries[1][0], new_shift, shift_qt)
            patched_n += 1
    return patched_n, missing


def _build_targets(layout_key):
    """Target map keycode → (plain_unicode, shift_unicode, plain_qt,
    shift_qt) for a layout, including dead-key defaults."""
    letters, punct = get_layout_mappings(layout_key)
    targets = {}
    for kc, new_lower, new_upper, qt_key in letters:
        targets[kc] = (new_lower, new_upper, qt_key, qt_key)
    for kc, plain_u, plain_qt, shift_u, shift_qt in punct:
        targets[kc] = (plain_u, shift_u, plain_qt, shift_qt)

    # The firmware's US keymap has dead key accents on some keys (e.g.
    # keycodes 26/27 have ´/`/¨/~ instead of [/{/]/}, and kc41 is a
    # broken Key_Unknown grave). For layouts that don't remap these keys,
    # force them to standard US values so dead key behavior is removed.
    DEAD_KEY_DEFAULTS = {
        26: (0x5B, 0x7B, 0x5B, 0x7B),  # [ / {
        27: (0x5D, 0x7D, 0x5D, 0x7D),  # ] / }
        41: (0x60, 0x7E, 0x60, 0x7E),  # ` / ~
    }
    for kc, vals in DEAD_KEY_DEFAULTS.items():
        if kc not in targets:
            targets[kc] = vals
    return targets


def _patch_binary(data, layout_key):
    """Patch the built-in US keymap with the given layout.

    Returns the patched binary as bytes. Raises LayoutError when the
    keymap cannot be found or the patch would be incomplete.
    """
    targets = _build_targets(layout_key)
    if not targets:
        return data

    keymap_offset, entry_count = _locate_keymap(data)
    log.info("Keymap table at %#x, %d entries", keymap_offset, entry_count)

    patched = bytearray(data)
    patched_n, missing = _patch_entries(patched, keymap_offset, entry_count,
                                        targets)

    if missing > len(targets) // 2:
        raise LayoutError(
            "Keymap patch would be incomplete "
            f"({len(targets) - missing}/{len(targets)} keys found) — aborting"
        )

    log.info("Patched %d entries for layout '%s'", patched_n, layout_key)
    return bytes(patched)


def _patch_locale_table(data, layout_key):
    """Fix the two ISO keycodes (41, 43) inside the firmware's built-in
    table for layout_key, using the layout's own definitions.

    Returns (bytes, changed). Returns (data, False) when the table cannot
    be identified — the InputLocale selection still works, only the two
    ISO keys keep the firmware's positions.
    """
    loc = _find_locale_table(data, layout_key)
    if not loc:
        log.warning("Firmware table for '%s' not identified — skipping "
                    "ISO key fix", layout_key)
        return data, False
    offset, count = loc
    _, punct = get_layout_mappings(layout_key)
    # _patch_entries expects (plain_u, shift_u, plain_qt, shift_qt)
    targets = {kc: (pu, su, pq, sq)
               for kc, pu, pq, su, sq in punct
               if kc in LOCALE_TABLE_FIX_KEYCODES}
    if not targets:
        return data, False
    patched = bytearray(data)
    _patch_entries(patched, offset, count, targets)
    changed = bytes(patched) != data
    if changed:
        log.info("Patched ISO keys %s in firmware table for '%s' at %#x",
                 sorted(targets), layout_key, offset)
    return bytes(patched), changed


# ══════════════════════════════════════════════════════════════════════
# xochitl.conf InputLocale handling (multi-locale firmware)
# ══════════════════════════════════════════════════════════════════════

def _schedule_locale_apply(locale_code):
    """Schedule a detached job that applies (or, with locale_code=None,
    removes) InputLocale after xochitl exits, then restarts xochitl.

    This app runs inside xochitl, so it must not stop or restart xochitl
    itself, and it must not write xochitl.conf while xochitl runs: the
    running xochitl rewrites the file from its QSettings cache on exit
    and would drop the change. The systemd-run job survives our process.
    QSettings only reads keys that sit in the right section, so the key
    must be inserted directly after [General] — appending at the end
    silently does nothing (verified on-device).
    """
    os.makedirs(SCRIPT_DIR, exist_ok=True)
    if locale_code:
        conf_edit = (
            f"sed -i '/^InputLocale=/d' {XOCHITL_CONF}\n"
            f"if grep -q '^\\[General\\]$' {XOCHITL_CONF}; then\n"
            f"    sed -i '/^\\[General\\]$/a InputLocale={locale_code}' {XOCHITL_CONF}\n"
            f"else\n"
            f"    printf '[General]\\nInputLocale={locale_code}\\n' | cat - {XOCHITL_CONF} > {XOCHITL_CONF}.tmp && mv {XOCHITL_CONF}.tmp {XOCHITL_CONF}\n"
            f"fi\n"
        )
    else:
        conf_edit = f"sed -i '/^InputLocale=/d' {XOCHITL_CONF}\n"
    script = f"""#!/bin/sh
# Written by the MoveWriter native app. Applies the InputLocale setting
# after xochitl exits (its settings flush would clobber an earlier
# write), then starts xochitl again. One-shot.
systemctl stop xochitl
i=0
while pidof xochitl >/dev/null 2>&1; do
    sleep 1
    i=$((i + 1))
    if [ "$i" -gt 30 ]; then break; fi
done
{conf_edit}systemctl start xochitl
echo "$(date) applied {locale_code or 'clear'}" >> {SCRIPT_DIR}/locale-apply.log
"""
    Path(LOCALE_APPLY_SCRIPT).write_text(script)
    os.chmod(LOCALE_APPLY_SCRIPT, 0o755)
    _run(f"systemd-run --on-active=3s --collect /bin/sh {LOCALE_APPLY_SCRIPT}",
         timeout=10)


def _clear_input_locale():
    """Schedule removal of InputLocale — must run after xochitl exits
    (see _schedule_locale_apply), so this delegates to the detached job
    without restarting xochitl afterwards... the job restarts xochitl;
    during uninstall that is expected anyway."""
    _schedule_locale_apply(None)


# ══════════════════════════════════════════════════════════════════════
# Apply / restore
# ══════════════════════════════════════════════════════════════════════

def _firmware_version():
    try:
        return Path("/etc/version").read_text().strip()
    except OSError:
        return ""


def _ensure_backup():
    """Return the stock libepaper.so bytes, with a version-stamped backup.

    If the stamped version no longer matches /etc/version, the Move was
    force-updated since the backup was taken: the live binary is then the
    stock binary of the new firmware and the old backup MUST NOT be used
    (deploying it can break xochitl)."""
    os.makedirs(SCRIPT_DIR, exist_ok=True)
    backup = Path(BACKUP_PATH)
    live_ver = _firmware_version()
    refresh = not backup.exists()
    original = None
    if backup.exists():
        original = backup.read_bytes()
        try:
            saved_ver = Path(BACKUP_VERSION_PATH).read_text().strip()
        except OSError:
            saved_ver = ""
        if saved_ver and saved_ver != live_ver:
            refresh = True
        elif not saved_ver:
            # Backup from an older MoveWriter without a version stamp.
            # Refresh only when the backup is from a different firmware
            # generation than the live binary (the dangerous case).
            live_multi = MULTI_LOCALE_MARKER in Path(LIBEPAPER_PATH).read_bytes()
            refresh = (MULTI_LOCALE_MARKER in original) != live_multi
    if refresh:
        shutil.copy2(LIBEPAPER_PATH, BACKUP_PATH)
        Path(BACKUP_VERSION_PATH).write_text(live_ver)
        original = backup.read_bytes()
    return original


def apply_layout(layout_key, status_cb=None):
    """Apply the given layout on device.

    Does NOT restart xochitl directly — the app runs inside xochitl. A
    detached job applies the conf setting and restarts xochitl a few
    seconds after this call returns.
    """
    def status(msg):
        log.info(msg)
        if status_cb:
            status_cb(msg)

    original = _ensure_backup()
    multi_locale = MULTI_LOCALE_MARKER in original
    locale = FIRMWARE_LOCALES.get(layout_key)

    if multi_locale and locale is not None:
        # Firmware has a built-in keymap for this layout — select it via
        # xochitl.conf, and fix the two ISO keycodes inside the firmware's
        # own table. Also removes any stale binary patch from an older
        # MoveWriter version (the backup is the stock binary).
        status(f"Selecting the Move's built-in '{locale}' keymap...")
        patched, table_changed = _patch_locale_table(original, layout_key)
        _run("mount -o remount,rw /", timeout=10)
        try:
            if table_changed:
                status("Adjusting two keys in the built-in keymap...")
                Path(LIBEPAPER_PATH).write_bytes(patched)
            elif Path(LIBEPAPER_PATH).read_bytes() != original:
                status("Removing old layout patch...")
                Path(LIBEPAPER_PATH).write_bytes(original)
        finally:
            _run("mount -o remount,ro /", timeout=10)
        _schedule_locale_apply(locale)
        Path(LAYOUT_FILE).write_text(layout_key)
        status("Layout applied — Move interface restarts in a few seconds")
        return

    # Binary patch route: legacy firmware always, new firmware for en_US
    # and for layouts the firmware has no built-in keymap for.
    status(f"Patching for {layout_key}...")
    patched = _patch_binary(original, layout_key)

    _run("mount -o remount,rw /", timeout=10)
    try:
        Path(LIBEPAPER_PATH).write_bytes(patched)
    finally:
        _run("mount -o remount,ro /", timeout=10)

    if multi_locale:
        # Force the firmware to load the (patched) US table.
        _schedule_locale_apply("en_US")

    # Save layout key to device
    Path(LAYOUT_FILE).write_text(layout_key)
    status("Layout applied — Move interface restarts in a few seconds")


def read_current_layout_key():
    """Return the layout key currently written on-device, or '' if unset."""
    try:
        return Path(LAYOUT_FILE).read_text().strip()
    except (FileNotFoundError, OSError):
        return ""


def read_current_layout_display_name(layouts_list):
    """Return the display name for the layout on device.

    layouts_list is a list of (display_name, layout_key) tuples.
    Returns '' if no layout is applied on device.
    """
    key = read_current_layout_key()
    if not key:
        return ""
    for display, k in layouts_list:
        if k == key:
            return display
    return ""


def restore_original():
    """Restore the original unpatched libepaper.so. Used during uninstall."""
    backup = Path(BACKUP_PATH)
    if not backup.exists():
        return  # No backup means no patching was ever done

    live_ver = _firmware_version()
    try:
        saved_ver = Path(BACKUP_VERSION_PATH).read_text().strip()
    except OSError:
        saved_ver = ""

    if saved_ver and saved_ver != live_ver:
        # The backup is from a different firmware generation — the live
        # binary is already the stock build of the current firmware.
        # Deploying the stale backup would break xochitl. Just clean up.
        log.warning("Skipping libepaper restore: firmware changed since "
                    "backup (%s -> %s)", saved_ver, live_ver)
        _clear_input_locale()
        _cleanup_files()
        return

    original = backup.read_bytes()

    _run("mount -o remount,rw /", timeout=10)
    try:
        if Path(LIBEPAPER_PATH).read_bytes() != original:
            Path(LIBEPAPER_PATH).write_bytes(original)
        _clear_input_locale()
    finally:
        _run("mount -o remount,ro /", timeout=10)

    _cleanup_files()


def _cleanup_files():
    # NOTE: LOCALE_APPLY_SCRIPT is intentionally kept — a scheduled job
    # may still need it a few seconds after this call. It is overwritten
    # on each use.
    for path in (LAYOUT_FILE, BACKUP_PATH, BACKUP_VERSION_PATH):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
