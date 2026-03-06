#!/usr/bin/env python3
"""Generate Qt .qmap binary keymap files for use with QT_QPA_EVDEV_KEYBOARD_PARAMETERS.

Qt's evdev keyboard handler (QEvdevKeyboardHandler) uses .qmap files to map
Linux keycodes to Unicode characters. The binary format is:
  - Header: magic(u32) + version(u32) + keymap_size(u32) + compose_size(u32)
  - Mapping entries: keycode(u16) + unicode(u16) + qtcode(u32) + modifiers(u8) + flags(u8) + special(u16)
  - Composing entries: first(u16) + second(u16) + result(u16)
All values are big-endian (QDataStream default).

Layout definitions also serve as the canonical mapping data for the binary
patcher (tools/patch_libepaper.py) which patches the US keymap in libepaper.so.
"""
import struct
import os

MAGIC = 0x514D4150  # 'QMAP'
VERSION = 1

# Modifier constants (which modifier state this entry matches)
MOD_PLAIN = 0x00
MOD_SHIFT = 0x01
MOD_ALTGR = 0x02
MOD_CONTROL = 0x04
MOD_ALT = 0x08

# Flag constants
FLAG_NONE = 0x00
FLAG_LETTER = 0x01
FLAG_DEAD = 0x02
FLAG_MODIFIER = 0x04
FLAG_SYSTEM = 0x08

# Qt Key codes
Key_Escape = 0x01000000
Key_Tab = 0x01000001
Key_Backspace = 0x01000003
Key_Return = 0x01000004
Key_Enter = 0x01000005
Key_Insert = 0x01000006
Key_Delete = 0x01000007
Key_Home = 0x01000010
Key_End = 0x01000011
Key_Left = 0x01000012
Key_Up = 0x01000013
Key_Right = 0x01000014
Key_Down = 0x01000015
Key_PageUp = 0x01000016
Key_PageDown = 0x01000017
Key_Shift = 0x01000020
Key_Control = 0x01000021
Key_Alt = 0x01000023
Key_CapsLock = 0x01000024
Key_NumLock = 0x01000025
Key_ScrollLock = 0x01000026
Key_F1 = 0x01000030
Key_Space = 0x20


def _base_entries():
    """Non-letter entries shared by all layouts."""
    entries = []

    # Escape
    entries.append((1, 0xFFFF, Key_Escape, 0, 0, 0))

    # Number row: keycodes 2-11 → 1-9, 0
    num_plain = [0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x30]
    num_shift = [0x21, 0x40, 0x23, 0x24, 0x25, 0x5E, 0x26, 0x2A, 0x28, 0x29]
    for i in range(10):
        kc = i + 2
        entries.append((kc, num_plain[i], num_plain[i], MOD_PLAIN, 0, 0))
        entries.append((kc, num_shift[i], num_shift[i], MOD_SHIFT, 0, 0))

    # Minus/underscore (keycode 12)
    entries.append((12, 0x2D, 0x2D, MOD_PLAIN, 0, 0))
    entries.append((12, 0x5F, 0x5F, MOD_SHIFT, 0, 0))

    # Equal/plus (keycode 13)
    entries.append((13, 0x3D, 0x3D, MOD_PLAIN, 0, 0))
    entries.append((13, 0x2B, 0x2B, MOD_SHIFT, 0, 0))

    # Backspace, Tab, Enter
    entries.append((14, 0x0008, Key_Backspace, 0, 0, 0))
    entries.append((15, 0x0009, Key_Tab, 0, 0, 0))
    entries.append((28, 0x000D, Key_Return, 0, 0, 0))

    # Brackets (keycodes 26, 27)
    entries.append((26, 0x5B, 0x5B, MOD_PLAIN, 0, 0))   # [
    entries.append((26, 0x7B, 0x7B, MOD_SHIFT, 0, 0))   # {
    entries.append((27, 0x5D, 0x5D, MOD_PLAIN, 0, 0))   # ]
    entries.append((27, 0x7D, 0x7D, MOD_SHIFT, 0, 0))   # }

    # Backslash (keycode 43)
    entries.append((43, 0x5C, 0x5C, MOD_PLAIN, 0, 0))   # backslash
    entries.append((43, 0x7C, 0x7C, MOD_SHIFT, 0, 0))   # |

    # Semicolon/colon (keycode 39)
    entries.append((39, 0x3B, 0x3B, MOD_PLAIN, 0, 0))   # ;
    entries.append((39, 0x3A, 0x3A, MOD_SHIFT, 0, 0))   # :

    # Apostrophe/quote (keycode 40)
    entries.append((40, 0x27, 0x27, MOD_PLAIN, 0, 0))   # '
    entries.append((40, 0x22, 0x22, MOD_SHIFT, 0, 0))   # "

    # Grave/tilde (keycode 41)
    entries.append((41, 0x60, 0x60, MOD_PLAIN, 0, 0))   # `
    entries.append((41, 0x7E, 0x7E, MOD_SHIFT, 0, 0))   # ~

    # Comma, dot, slash (keycodes 51-53)
    entries.append((51, 0x2C, 0x2C, MOD_PLAIN, 0, 0))   # ,
    entries.append((51, 0x3C, 0x3C, MOD_SHIFT, 0, 0))   # <
    entries.append((52, 0x2E, 0x2E, MOD_PLAIN, 0, 0))   # .
    entries.append((52, 0x3E, 0x3E, MOD_SHIFT, 0, 0))   # >
    entries.append((53, 0x2F, 0x2F, MOD_PLAIN, 0, 0))   # /
    entries.append((53, 0x3F, 0x3F, MOD_SHIFT, 0, 0))   # ?

    # Space
    entries.append((57, 0x20, Key_Space, 0, 0, 0))

    # Modifier keys (flags=IsModifier, special=which modifier bit)
    entries.append((42, 0xFFFF, Key_Shift, 0, FLAG_MODIFIER, MOD_SHIFT))      # Left Shift
    entries.append((54, 0xFFFF, Key_Shift, 0, FLAG_MODIFIER, MOD_SHIFT))      # Right Shift
    entries.append((29, 0xFFFF, Key_Control, 0, FLAG_MODIFIER, MOD_CONTROL))  # Left Ctrl
    entries.append((97, 0xFFFF, Key_Control, 0, FLAG_MODIFIER, MOD_CONTROL))  # Right Ctrl
    entries.append((56, 0xFFFF, Key_Alt, 0, FLAG_MODIFIER, MOD_ALT))          # Left Alt
    entries.append((100, 0xFFFF, Key_Alt, 0, FLAG_MODIFIER, MOD_ALTGR))       # Right Alt (AltGr)
    entries.append((58, 0xFFFF, Key_CapsLock, 0, FLAG_MODIFIER, 0))           # CapsLock

    # Arrow keys
    entries.append((103, 0xFFFF, Key_Up, 0, 0, 0))
    entries.append((105, 0xFFFF, Key_Left, 0, 0, 0))
    entries.append((106, 0xFFFF, Key_Right, 0, 0, 0))
    entries.append((108, 0xFFFF, Key_Down, 0, 0, 0))

    # Navigation
    entries.append((102, 0xFFFF, Key_Home, 0, 0, 0))
    entries.append((107, 0xFFFF, Key_End, 0, 0, 0))
    entries.append((104, 0xFFFF, Key_PageUp, 0, 0, 0))
    entries.append((109, 0xFFFF, Key_PageDown, 0, 0, 0))
    entries.append((110, 0xFFFF, Key_Insert, 0, 0, 0))
    entries.append((111, 0xFFFF, Key_Delete, 0, 0, 0))

    # Function keys F1-F12
    for i in range(10):
        entries.append((59 + i, 0xFFFF, Key_F1 + i, 0, 0, 0))
    entries.append((87, 0xFFFF, Key_F1 + 10, 0, 0, 0))  # F11
    entries.append((88, 0xFFFF, Key_F1 + 11, 0, 0, 0))  # F12

    # Keypad enter
    entries.append((96, 0x000D, Key_Enter, 0, 0, 0))

    return entries


def _letter_entries(letter_map):
    """Generate entries for letter keys from a layout map.

    letter_map: list of (keycode, lower_unicode, upper_unicode, qt_key)
    Also generates Ctrl+key variants using US key positions for shortcuts.
    """
    entries = []

    # Map from Linux keycode to US Qt::Key (for Ctrl shortcuts)
    us_qt_keys = {
        16: 0x51, 17: 0x57, 18: 0x45, 19: 0x52, 20: 0x54,
        21: 0x59, 22: 0x55, 23: 0x49, 24: 0x4F, 25: 0x50,
        30: 0x41, 31: 0x53, 32: 0x44, 33: 0x46, 34: 0x47,
        35: 0x48, 36: 0x4A, 37: 0x4B, 38: 0x4C,
        44: 0x5A, 45: 0x58, 46: 0x43, 47: 0x56, 48: 0x42,
        49: 0x4E, 50: 0x4D,
    }

    for kc, lower, upper, qt_key in letter_map:
        is_letter = FLAG_LETTER if lower > 0x7F or lower in range(0x61, 0x7B) else FLAG_NONE
        entries.append((kc, lower, qt_key, MOD_PLAIN, is_letter, 0))
        entries.append((kc, upper, qt_key, MOD_SHIFT, is_letter, 0))

        # Ctrl+key: use US Qt key code so shortcuts work regardless of layout
        us_key = us_qt_keys.get(kc)
        if us_key:
            ctrl_char = us_key - 0x40  # Ctrl+A = 0x01, etc.
            entries.append((kc, ctrl_char, us_key, MOD_CONTROL, 0, 0))

    return entries


def _punctuation_entries(punct_map):
    """Generate entries for punctuation keys that differ between layouts.

    punct_map: list of (keycode, plain_unicode, plain_qtcode, shift_unicode, shift_qtcode)
    """
    entries = []
    for kc, plain_u, plain_qt, shift_u, shift_qt in punct_map:
        entries.append((kc, plain_u, plain_qt, MOD_PLAIN, 0, 0))
        entries.append((kc, shift_u, shift_qt, MOD_SHIFT, 0, 0))
    return entries


# ── Helper: standard QWERTY letter keys ───────────────────────────────

def _us_letters():
    """Standard US QWERTY letter positions — shared by many layouts."""
    return [
        # Q row (keycodes 16-25)
        (16, 0x71, 0x51, 0x51),  # q/Q
        (17, 0x77, 0x57, 0x57),  # w/W
        (18, 0x65, 0x45, 0x45),  # e/E
        (19, 0x72, 0x52, 0x52),  # r/R
        (20, 0x74, 0x54, 0x54),  # t/T
        (21, 0x79, 0x59, 0x59),  # y/Y
        (22, 0x75, 0x55, 0x55),  # u/U
        (23, 0x69, 0x49, 0x49),  # i/I
        (24, 0x6F, 0x4F, 0x4F),  # o/O
        (25, 0x70, 0x50, 0x50),  # p/P
        # A row (keycodes 30-38)
        (30, 0x61, 0x41, 0x41),  # a/A
        (31, 0x73, 0x53, 0x53),  # s/S
        (32, 0x64, 0x44, 0x44),  # d/D
        (33, 0x66, 0x46, 0x46),  # f/F
        (34, 0x67, 0x47, 0x47),  # g/G
        (35, 0x68, 0x48, 0x48),  # h/H
        (36, 0x6A, 0x4A, 0x4A),  # j/J
        (37, 0x6B, 0x4B, 0x4B),  # k/K
        (38, 0x6C, 0x4C, 0x4C),  # l/L
        # Z row (keycodes 44-50)
        (44, 0x7A, 0x5A, 0x5A),  # z/Z
        (45, 0x78, 0x58, 0x58),  # x/X
        (46, 0x63, 0x43, 0x43),  # c/C
        (47, 0x76, 0x56, 0x56),  # v/V
        (48, 0x62, 0x42, 0x42),  # b/B
        (49, 0x6E, 0x4E, 0x4E),  # n/N
        (50, 0x6D, 0x4D, 0x4D),  # m/M
    ]


def _qwertz_letters():
    """QWERTZ letter positions (German family) — Y and Z swapped."""
    letters = _us_letters()
    # Swap Y (keycode 21) and Z (keycode 44)
    result = []
    for kc, lower, upper, qt in letters:
        if kc == 21:    # Y position → z/Z
            result.append((21, 0x7A, 0x5A, 0x5A))
        elif kc == 44:  # Z position → y/Y
            result.append((44, 0x79, 0x59, 0x59))
        else:
            result.append((kc, lower, upper, qt))
    return result


def _azerty_letters():
    """AZERTY letter positions (French family) — A↔Q, W↔Z swapped."""
    letters = _us_letters()
    result = []
    for kc, lower, upper, qt in letters:
        if kc == 16:    # Q position → a/A
            result.append((16, 0x61, 0x41, 0x41))
        elif kc == 17:  # W position → z/Z
            result.append((17, 0x7A, 0x5A, 0x5A))
        elif kc == 30:  # A position → q/Q
            result.append((30, 0x71, 0x51, 0x51))
        elif kc == 44:  # Z position → w/W
            result.append((44, 0x77, 0x57, 0x57))
        else:
            result.append((kc, lower, upper, qt))
    return result


# ══════════════════════════════════════════════════════════════════════
# Layout definitions — each returns (letters, punct)
#
# letters: list of (keycode, lower_unicode, upper_unicode, qt_key)
# punct: list of (keycode, plain_unicode, plain_qtcode, shift_unicode, shift_qtcode)
#
# punct entries OVERRIDE the base entries for those keycodes.
# Only include punct for keys that differ from standard US layout.
# ══════════════════════════════════════════════════════════════════════


def us_layout():
    """US English — standard QWERTY."""
    return _us_letters(), []


def uk_layout():
    """UK English — QWERTY, same letters as US.
    Differences: Shift+2=", Shift+3=£, backslash→#/~, grave→`/¬."""
    punct = [
        (3,  0x32, 0x32, 0x22, 0x22),      # 2 / "  (US: 2/@)
        (4,  0x33, 0x33, 0x00A3, 0x00A3),  # 3 / £  (US: 3/#)
        (41, 0x60, 0x60, 0x00AC, 0x00AC),  # ` / ¬  (US: `/~)
        (43, 0x23, 0x23, 0x7E, 0x7E),      # # / ~  (US: \/|)
    ]
    return _us_letters(), punct


def german_layout():
    """German — QWERTZ. Y↔Z swap, umlauts on punctuation keys."""
    punct = [
        # Number row shifts differ
        (3,  0x32, 0x32, 0x22, 0x22),      # 2 / "
        (4,  0x33, 0x33, 0x00A7, 0x00A7),  # 3 / §
        (7,  0x36, 0x36, 0x26, 0x26),      # 6 / &
        (8,  0x37, 0x37, 0x2F, 0x2F),      # 7 / /
        (9,  0x38, 0x38, 0x28, 0x28),      # 8 / (
        (10, 0x39, 0x39, 0x29, 0x29),      # 9 / )
        (11, 0x30, 0x30, 0x3D, 0x3D),      # 0 / =
        (12, 0x00DF, 0x00DF, 0x3F, 0x3F),  # ß / ?
        (13, 0x00B4, 0x00B4, 0x60, 0x60),  # ´ / `
        # Brackets → ü/Ü and +/*
        (26, 0x00FC, 0x00DC, 0x00DC, 0x00DC),  # ü / Ü
        (27, 0x2B, 0x2B, 0x2A, 0x2A),          # + / *
        # Semicolon → ö/Ö
        (39, 0x00F6, 0x00D6, 0x00D6, 0x00D6),  # ö / Ö
        # Apostrophe → ä/Ä
        (40, 0x00E4, 0x00C4, 0x00C4, 0x00C4),  # ä / Ä
        # Grave → ^/°
        (41, 0x5E, 0x5E, 0x00B0, 0x00B0),      # ^ / °
        # Backslash → #/'
        (43, 0x23, 0x23, 0x27, 0x27),           # # / '
        # Comma, dot, slash
        (51, 0x2C, 0x2C, 0x3B, 0x3B),  # , / ;
        (52, 0x2E, 0x2E, 0x3A, 0x3A),  # . / :
        (53, 0x2D, 0x2D, 0x5F, 0x5F),  # - / _
    ]
    return _qwertz_letters(), punct


def french_layout():
    """French — AZERTY. Letters rearranged, numbers need shift."""
    # French number row: unshifted produces symbols, shifted produces numbers
    punct = [
        (2,  0x26, 0x26, 0x31, 0x31),      # & / 1
        (3,  0x00E9, 0x00E9, 0x32, 0x32),  # é / 2
        (4,  0x22, 0x22, 0x33, 0x33),      # " / 3
        (5,  0x27, 0x27, 0x34, 0x34),      # ' / 4
        (6,  0x28, 0x28, 0x35, 0x35),      # ( / 5
        (7,  0x2D, 0x2D, 0x36, 0x36),      # - / 6
        (8,  0x00E8, 0x00E8, 0x37, 0x37),  # è / 7
        (9,  0x5F, 0x5F, 0x38, 0x38),      # _ / 8
        (10, 0x00E7, 0x00E7, 0x39, 0x39),  # ç / 9
        (11, 0x00E0, 0x00E0, 0x30, 0x30),  # à / 0
        (12, 0x29, 0x29, 0x00B0, 0x00B0),  # ) / °
        (13, 0x3D, 0x3D, 0x2B, 0x2B),      # = / +
        # Right bracket → $ / £
        (27, 0x24, 0x24, 0x00A3, 0x00A3),  # $ / £
        # Semicolon → m/M (letter on punct key in AZERTY)
        (39, 0x6D, 0x4D, 0x4D, 0x4D),
        # Apostrophe → ù/%
        (40, 0x00F9, 0x25, 0x25, 0x25),
        # Grave → ²/³
        (41, 0x00B2, 0x00B2, 0x00B3, 0x00B3),
        # Backslash → */µ
        (43, 0x2A, 0x2A, 0x00B5, 0x00B5),
        # Comma position → ;/.
        (51, 0x3B, 0x3B, 0x2E, 0x2E),
        # Period position → ://
        (52, 0x3A, 0x3A, 0x2F, 0x2F),
        # Slash position → !/§
        (53, 0x21, 0x21, 0x00A7, 0x00A7),
    ]
    # AZERTY: M moves to semicolon key, so remove M from letter list
    letters = []
    for kc, lower, upper, qt in _azerty_letters():
        if kc == 50:  # M position in AZERTY → ,/<
            # In French AZERTY, the M key position produces , and <
            continue
        letters.append((kc, lower, upper, qt))
    # The letter ^ is on bracket key 26 in French layout
    punct.append((26, 0x5E, 0x5E, 0x00A8, 0x00A8))  # ^ / ¨ (circumflex / diaeresis)
    # M key position (50) produces , / ?
    punct.append((50, 0x2C, 0x2C, 0x3F, 0x3F))

    return letters, punct


def spanish_layout():
    """Spanish — QWERTY with ñ on semicolon key."""
    punct = [
        (12, 0x27, 0x27, 0x3F, 0x3F),      # ' / ?
        (13, 0x00A1, 0x00A1, 0x00BF, 0x00BF),  # ¡ / ¿
        (26, 0x60, 0x60, 0x5E, 0x5E),       # ` / ^  (dead accents)
        (27, 0x2B, 0x2B, 0x2A, 0x2A),       # + / *
        (39, 0x00F1, 0x00D1, 0x00D1, 0x00D1),  # ñ / Ñ
        (40, 0x00B4, 0x00B4, 0x00A8, 0x00A8),  # ´ / ¨  (dead accents)
        (41, 0x00BA, 0x00BA, 0x00AA, 0x00AA),  # º / ª
        (43, 0x00E7, 0x00C7, 0x00C7, 0x00C7),  # ç / Ç
        (51, 0x2C, 0x2C, 0x3B, 0x3B),       # , / ;
        (52, 0x2E, 0x2E, 0x3A, 0x3A),       # . / :
        (53, 0x2D, 0x2D, 0x5F, 0x5F),       # - / _
    ]
    return _us_letters(), punct


def italian_layout():
    """Italian — QWERTY with accented vowels on punctuation keys."""
    punct = [
        (12, 0x27, 0x27, 0x3F, 0x3F),       # ' / ?
        (13, 0x00EC, 0x00EC, 0x5E, 0x5E),   # ì / ^
        (26, 0x00E8, 0x00E8, 0x00E9, 0x00E9),  # è / é
        (27, 0x2B, 0x2B, 0x2A, 0x2A),       # + / *
        (39, 0x00F2, 0x00F2, 0x00E7, 0x00E7),  # ò / ç
        (40, 0x00E0, 0x00E0, 0x00B0, 0x00B0),  # à / °
        (41, 0x5C, 0x5C, 0x7C, 0x7C),       # \ / |
        (43, 0x00F9, 0x00F9, 0x00A7, 0x00A7),  # ù / §
        (51, 0x2C, 0x2C, 0x3B, 0x3B),       # , / ;
        (52, 0x2E, 0x2E, 0x3A, 0x3A),       # . / :
        (53, 0x2D, 0x2D, 0x5F, 0x5F),       # - / _
    ]
    return _us_letters(), punct


def portuguese_layout():
    """Portuguese — QWERTY with ç on semicolon key."""
    punct = [
        (12, 0x27, 0x27, 0x3F, 0x3F),       # ' / ?
        (13, 0x00AB, 0x00AB, 0x00BB, 0x00BB),  # « / »
        (26, 0x2B, 0x2B, 0x2A, 0x2A),       # + / *
        (27, 0x00B4, 0x00B4, 0x60, 0x60),   # ´ / `  (dead accents)
        (39, 0x00E7, 0x00C7, 0x00C7, 0x00C7),  # ç / Ç
        (40, 0x00BA, 0x00BA, 0x00AA, 0x00AA),  # º / ª
        (41, 0x5C, 0x5C, 0x7C, 0x7C),       # \ / |
        (43, 0x7E, 0x7E, 0x5E, 0x5E),       # ~ / ^
        (51, 0x2C, 0x2C, 0x3B, 0x3B),       # , / ;
        (52, 0x2E, 0x2E, 0x3A, 0x3A),       # . / :
        (53, 0x2D, 0x2D, 0x5F, 0x5F),       # - / _
    ]
    return _us_letters(), punct


def brazilian_layout():
    """Brazilian ABNT2 — QWERTY with ç on semicolon key."""
    punct = [
        (12, 0x2D, 0x2D, 0x5F, 0x5F),      # - / _
        (13, 0x3D, 0x3D, 0x2B, 0x2B),       # = / +
        (26, 0x00B4, 0x00B4, 0x60, 0x60),   # ´ / `  (dead accents)
        (27, 0x5B, 0x5B, 0x7B, 0x7B),       # [ / {
        (39, 0x00E7, 0x00C7, 0x00C7, 0x00C7),  # ç / Ç
        (40, 0x7E, 0x7E, 0x5E, 0x5E),       # ~ / ^
        (41, 0x27, 0x27, 0x22, 0x22),        # ' / "
        (43, 0x5D, 0x5D, 0x7D, 0x7D),       # ] / }
        (51, 0x2C, 0x2C, 0x3C, 0x3C),       # , / <
        (52, 0x2E, 0x2E, 0x3E, 0x3E),       # . / >
        (53, 0x3B, 0x3B, 0x3A, 0x3A),       # ; / :
    ]
    return _us_letters(), punct


def dutch_layout():
    """Dutch — QWERTY, same letters as US. Different punctuation."""
    punct = [
        (2,  0x31, 0x31, 0x21, 0x21),       # 1 / !
        (3,  0x32, 0x32, 0x22, 0x22),       # 2 / "
        (4,  0x33, 0x33, 0x23, 0x23),       # 3 / #
        (5,  0x34, 0x34, 0x24, 0x24),       # 4 / $
        (6,  0x35, 0x35, 0x25, 0x25),       # 5 / %
        (7,  0x36, 0x36, 0x26, 0x26),       # 6 / &
        (8,  0x37, 0x37, 0x5F, 0x5F),       # 7 / _
        (9,  0x38, 0x38, 0x28, 0x28),       # 8 / (
        (10, 0x39, 0x39, 0x29, 0x29),       # 9 / )
        (11, 0x30, 0x30, 0x27, 0x27),       # 0 / '
        (12, 0x2F, 0x2F, 0x3F, 0x3F),       # / / ?
        (13, 0x00B0, 0x00B0, 0x7E, 0x7E),   # ° / ~
        (26, 0x00A8, 0x00A8, 0x5E, 0x5E),   # ¨ / ^  (dead)
        (27, 0x2A, 0x2A, 0x7C, 0x7C),       # * / |
        (39, 0x2B, 0x2B, 0x00B1, 0x00B1),   # + / ±
        (40, 0x00B4, 0x00B4, 0x60, 0x60),   # ´ / `  (dead)
        (41, 0x40, 0x40, 0x00A7, 0x00A7),   # @ / §
        (43, 0x3C, 0x3C, 0x3E, 0x3E),       # < / >
        (51, 0x2C, 0x2C, 0x3B, 0x3B),       # , / ;
        (52, 0x2E, 0x2E, 0x3A, 0x3A),       # . / :
        (53, 0x2D, 0x2D, 0x3D, 0x3D),       # - / =
    ]
    return _us_letters(), punct


def swedish_layout():
    """Swedish — QWERTY with å, ä, ö on punctuation keys."""
    punct = [
        (3,  0x32, 0x32, 0x22, 0x22),       # 2 / "
        (4,  0x33, 0x33, 0x23, 0x23),       # 3 / #  (UK pound on AltGr)
        (7,  0x36, 0x36, 0x26, 0x26),       # 6 / &
        (8,  0x37, 0x37, 0x2F, 0x2F),       # 7 / /
        (9,  0x38, 0x38, 0x28, 0x28),       # 8 / (
        (10, 0x39, 0x39, 0x29, 0x29),       # 9 / )
        (11, 0x30, 0x30, 0x3D, 0x3D),       # 0 / =
        (12, 0x2B, 0x2B, 0x3F, 0x3F),       # + / ?
        (13, 0x00B4, 0x00B4, 0x60, 0x60),   # ´ / `  (dead accent)
        (26, 0x00E5, 0x00C5, 0x00C5, 0x00C5),  # å / Å
        (27, 0x00A8, 0x00A8, 0x5E, 0x5E),   # ¨ / ^  (dead)
        (39, 0x00F6, 0x00D6, 0x00D6, 0x00D6),  # ö / Ö
        (40, 0x00E4, 0x00C4, 0x00C4, 0x00C4),  # ä / Ä
        (41, 0x00A7, 0x00A7, 0x00BD, 0x00BD),  # § / ½
        (43, 0x27, 0x27, 0x2A, 0x2A),       # ' / *
        (51, 0x2C, 0x2C, 0x3B, 0x3B),       # , / ;
        (52, 0x2E, 0x2E, 0x3A, 0x3A),       # . / :
        (53, 0x2D, 0x2D, 0x5F, 0x5F),       # - / _
    ]
    return _us_letters(), punct


def norwegian_layout():
    """Norwegian — QWERTY with å, ø, æ on punctuation keys."""
    punct = [
        (3,  0x32, 0x32, 0x22, 0x22),       # 2 / "
        (4,  0x33, 0x33, 0x23, 0x23),       # 3 / #
        (7,  0x36, 0x36, 0x26, 0x26),       # 6 / &
        (8,  0x37, 0x37, 0x2F, 0x2F),       # 7 / /
        (9,  0x38, 0x38, 0x28, 0x28),       # 8 / (
        (10, 0x39, 0x39, 0x29, 0x29),       # 9 / )
        (11, 0x30, 0x30, 0x3D, 0x3D),       # 0 / =
        (12, 0x2B, 0x2B, 0x3F, 0x3F),       # + / ?
        (13, 0x5C, 0x5C, 0x60, 0x60),       # \ / `
        (26, 0x00E5, 0x00C5, 0x00C5, 0x00C5),  # å / Å
        (27, 0x00A8, 0x00A8, 0x5E, 0x5E),   # ¨ / ^  (dead)
        (39, 0x00F8, 0x00D8, 0x00D8, 0x00D8),  # ø / Ø
        (40, 0x00E6, 0x00C6, 0x00C6, 0x00C6),  # æ / Æ
        (41, 0x7C, 0x7C, 0x00A7, 0x00A7),   # | / §
        (43, 0x27, 0x27, 0x2A, 0x2A),       # ' / *
        (51, 0x2C, 0x2C, 0x3B, 0x3B),       # , / ;
        (52, 0x2E, 0x2E, 0x3A, 0x3A),       # . / :
        (53, 0x2D, 0x2D, 0x5F, 0x5F),       # - / _
    ]
    return _us_letters(), punct


def danish_layout():
    """Danish — QWERTY with å, æ, ø on punctuation keys.
    Note: Danish swaps æ/ø positions compared to Norwegian."""
    punct = [
        (3,  0x32, 0x32, 0x22, 0x22),       # 2 / "
        (4,  0x33, 0x33, 0x23, 0x23),       # 3 / #
        (7,  0x36, 0x36, 0x26, 0x26),       # 6 / &
        (8,  0x37, 0x37, 0x2F, 0x2F),       # 7 / /
        (9,  0x38, 0x38, 0x28, 0x28),       # 8 / (
        (10, 0x39, 0x39, 0x29, 0x29),       # 9 / )
        (11, 0x30, 0x30, 0x3D, 0x3D),       # 0 / =
        (12, 0x2B, 0x2B, 0x3F, 0x3F),       # + / ?
        (13, 0x00B4, 0x00B4, 0x60, 0x60),   # ´ / `  (dead accent)
        (26, 0x00E5, 0x00C5, 0x00C5, 0x00C5),  # å / Å
        (27, 0x00A8, 0x00A8, 0x5E, 0x5E),   # ¨ / ^  (dead)
        (39, 0x00E6, 0x00C6, 0x00C6, 0x00C6),  # æ / Æ
        (40, 0x00F8, 0x00D8, 0x00D8, 0x00D8),  # ø / Ø
        (41, 0x00BD, 0x00BD, 0x00A7, 0x00A7),  # ½ / §
        (43, 0x27, 0x27, 0x2A, 0x2A),       # ' / *
        (51, 0x2C, 0x2C, 0x3B, 0x3B),       # , / ;
        (52, 0x2E, 0x2E, 0x3A, 0x3A),       # . / :
        (53, 0x2D, 0x2D, 0x5F, 0x5F),       # - / _
    ]
    return _us_letters(), punct


def finnish_layout():
    """Finnish — identical to Swedish layout."""
    return swedish_layout()


def swiss_german_layout():
    """Swiss German — QWERTZ with ü, ö, ä on punctuation keys."""
    punct = [
        (3,  0x32, 0x32, 0x22, 0x22),       # 2 / "
        (4,  0x33, 0x33, 0x2A, 0x2A),       # 3 / *
        (7,  0x36, 0x36, 0x26, 0x26),       # 6 / &
        (8,  0x37, 0x37, 0x2F, 0x2F),       # 7 / /
        (9,  0x38, 0x38, 0x28, 0x28),       # 8 / (
        (10, 0x39, 0x39, 0x29, 0x29),       # 9 / )
        (11, 0x30, 0x30, 0x3D, 0x3D),       # 0 / =
        (12, 0x27, 0x27, 0x3F, 0x3F),       # ' / ?
        (13, 0x5E, 0x5E, 0x60, 0x60),       # ^ / `  (dead)
        (26, 0x00FC, 0x00DC, 0x00DC, 0x00DC),  # ü / Ü
        (27, 0x00A8, 0x00A8, 0x21, 0x21),   # ¨ / !
        (39, 0x00F6, 0x00D6, 0x00D6, 0x00D6),  # ö / Ö
        (40, 0x00E4, 0x00C4, 0x00C4, 0x00C4),  # ä / Ä
        (41, 0x00A7, 0x00A7, 0x00B0, 0x00B0),  # § / °
        (43, 0x24, 0x24, 0x00A3, 0x00A3),   # $ / £
        (51, 0x2C, 0x2C, 0x3B, 0x3B),       # , / ;
        (52, 0x2E, 0x2E, 0x3A, 0x3A),       # . / :
        (53, 0x2D, 0x2D, 0x5F, 0x5F),       # - / _
    ]
    return _qwertz_letters(), punct


def swiss_french_layout():
    """Swiss French — QWERTZ with è, é, à on punctuation keys."""
    punct = [
        (3,  0x32, 0x32, 0x22, 0x22),       # 2 / "
        (4,  0x33, 0x33, 0x2A, 0x2A),       # 3 / *
        (7,  0x36, 0x36, 0x26, 0x26),       # 6 / &
        (8,  0x37, 0x37, 0x2F, 0x2F),       # 7 / /
        (9,  0x38, 0x38, 0x28, 0x28),       # 8 / (
        (10, 0x39, 0x39, 0x29, 0x29),       # 9 / )
        (11, 0x30, 0x30, 0x3D, 0x3D),       # 0 / =
        (12, 0x27, 0x27, 0x3F, 0x3F),       # ' / ?
        (13, 0x5E, 0x5E, 0x60, 0x60),       # ^ / `  (dead)
        (26, 0x00E8, 0x00C8, 0x00C8, 0x00C8),  # è / È
        (27, 0x00A8, 0x00A8, 0x21, 0x21),   # ¨ / !
        (39, 0x00E9, 0x00C9, 0x00C9, 0x00C9),  # é / É
        (40, 0x00E0, 0x00C0, 0x00C0, 0x00C0),  # à / À
        (41, 0x00A7, 0x00A7, 0x00B0, 0x00B0),  # § / °
        (43, 0x24, 0x24, 0x00A3, 0x00A3),   # $ / £
        (51, 0x2C, 0x2C, 0x3B, 0x3B),       # , / ;
        (52, 0x2E, 0x2E, 0x3A, 0x3A),       # . / :
        (53, 0x2D, 0x2D, 0x5F, 0x5F),       # - / _
    ]
    return _qwertz_letters(), punct


def belgian_layout():
    """Belgian — AZERTY, similar to French but with some differences."""
    # Belgian has same letter arrangement as French (AZERTY)
    # Number row: same as French (symbols unshifted, numbers shifted)
    punct = [
        (2,  0x26, 0x26, 0x31, 0x31),       # & / 1
        (3,  0x00E9, 0x00E9, 0x32, 0x32),   # é / 2
        (4,  0x22, 0x22, 0x33, 0x33),        # " / 3
        (5,  0x27, 0x27, 0x34, 0x34),        # ' / 4
        (6,  0x28, 0x28, 0x35, 0x35),        # ( / 5
        (7,  0x00A7, 0x00A7, 0x36, 0x36),    # § / 6
        (8,  0x00E8, 0x00E8, 0x37, 0x37),    # è / 7
        (9,  0x21, 0x21, 0x38, 0x38),        # ! / 8
        (10, 0x00E7, 0x00E7, 0x39, 0x39),    # ç / 9
        (11, 0x00E0, 0x00E0, 0x30, 0x30),    # à / 0
        (12, 0x29, 0x29, 0x00B0, 0x00B0),    # ) / °
        (13, 0x2D, 0x2D, 0x5F, 0x5F),        # - / _
        (26, 0x5E, 0x5E, 0x00A8, 0x00A8),    # ^ / ¨  (dead)
        (27, 0x24, 0x24, 0x2A, 0x2A),        # $ / *
        (39, 0x6D, 0x4D, 0x4D, 0x4D),        # m / M  (letter on punct key)
        (40, 0x00F9, 0x25, 0x25, 0x25),    # ù / %
        (41, 0x00B2, 0x00B2, 0x00B3, 0x00B3),  # ² / ³
        (43, 0x00B5, 0x00B5, 0x00A3, 0x00A3),  # µ / £
        (50, 0x2C, 0x2C, 0x3F, 0x3F),        # , / ?  (M position)
        (51, 0x3B, 0x3B, 0x2E, 0x2E),        # ; / .
        (52, 0x3A, 0x3A, 0x2F, 0x2F),        # : / /
        (53, 0x3D, 0x3D, 0x2B, 0x2B),        # = / +
    ]
    # Remove M from letter list (it's on semicolon key in Belgian AZERTY)
    letters = [e for e in _azerty_letters() if e[0] != 50]
    return letters, punct


def russian_layout():
    """Russian — ЙЦУКЕН layout. All letter keys produce Cyrillic characters."""
    letters = [
        # Q row: й ц у к е н г ш щ з
        (16, 0x0439, 0x0419, 0x0419),  # Q → й/Й
        (17, 0x0446, 0x0426, 0x0426),  # W → ц/Ц
        (18, 0x0443, 0x0423, 0x0423),  # E → у/У
        (19, 0x043A, 0x041A, 0x041A),  # R → к/К
        (20, 0x0435, 0x0415, 0x0415),  # T → е/Е
        (21, 0x043D, 0x041D, 0x041D),  # Y → н/Н
        (22, 0x0433, 0x0413, 0x0413),  # U → г/Г
        (23, 0x0448, 0x0428, 0x0428),  # I → ш/Ш
        (24, 0x0449, 0x0429, 0x0429),  # O → щ/Щ
        (25, 0x0437, 0x0417, 0x0417),  # P → з/З
        # A row: ф ы в а п р о л д ж э
        (30, 0x0444, 0x0424, 0x0424),  # A → ф/Ф
        (31, 0x044B, 0x042B, 0x042B),  # S → ы/Ы
        (32, 0x0432, 0x0412, 0x0412),  # D → в/В
        (33, 0x0430, 0x0410, 0x0410),  # F → а/А
        (34, 0x043F, 0x041F, 0x041F),  # G → п/П
        (35, 0x0440, 0x0420, 0x0420),  # H → р/Р
        (36, 0x043E, 0x041E, 0x041E),  # J → о/О
        (37, 0x043B, 0x041B, 0x041B),  # K → л/Л
        (38, 0x0434, 0x0414, 0x0414),  # L → д/Д
        # Z row: я ч с м и т ь б ю
        (44, 0x044F, 0x042F, 0x042F),  # Z → я/Я
        (45, 0x0447, 0x0427, 0x0427),  # X → ч/Ч
        (46, 0x0441, 0x0421, 0x0421),  # C → с/С
        (47, 0x043C, 0x041C, 0x041C),  # V → м/М
        (48, 0x0438, 0x0418, 0x0418),  # B → и/И
        (49, 0x0442, 0x0422, 0x0422),  # N → т/Т
        (50, 0x044C, 0x042C, 0x042C),  # M → ь/Ь
    ]
    # Remaining Cyrillic letters on punctuation keys: х ъ ж э
    punct = [
        (26, 0x0445, 0x0425, 0x0425, 0x0425),  # [ → х/Х
        (27, 0x044A, 0x042A, 0x042A, 0x042A),  # ] → ъ/Ъ
        (39, 0x0436, 0x0416, 0x0416, 0x0416),  # ; → ж/Ж
        (40, 0x044D, 0x042D, 0x042D, 0x042D),  # ' → э/Э
        (41, 0x0451, 0x0401, 0x0401, 0x0401),  # ` → ё/Ё
        (43, 0x5C, 0x5C, 0x2F, 0x2F),          # \ / /
        (51, 0x0431, 0x0411, 0x0411, 0x0411),  # , → б/Б
        (52, 0x044E, 0x042E, 0x042E, 0x042E),  # . → ю/Ю
        (53, 0x2E, 0x2E, 0x2C, 0x2C),          # / → . / ,
    ]
    return letters, punct


def ukrainian_layout():
    """Ukrainian — ЙЦУКЕН variant with Ukrainian-specific letters (і, є, ї, ґ).
    No ё or ъ (Russian-only); и is on B position, і is on S position."""
    letters = [
        # Q row: й ц у к е н г ш щ з
        (16, 0x0439, 0x0419, 0x0419),  # Q → й/Й
        (17, 0x0446, 0x0426, 0x0426),  # W → ц/Ц
        (18, 0x0443, 0x0423, 0x0423),  # E → у/У
        (19, 0x043A, 0x041A, 0x041A),  # R → к/К
        (20, 0x0435, 0x0415, 0x0415),  # T → е/Е
        (21, 0x043D, 0x041D, 0x041D),  # Y → н/Н
        (22, 0x0433, 0x0413, 0x0413),  # U → г/Г
        (23, 0x0448, 0x0428, 0x0428),  # I → ш/Ш
        (24, 0x0449, 0x0429, 0x0429),  # O → щ/Щ
        (25, 0x0437, 0x0417, 0x0417),  # P → з/З
        # A row: ф і в а п р о л д
        (30, 0x0444, 0x0424, 0x0424),  # A → ф/Ф
        (31, 0x0456, 0x0406, 0x0406),  # S → і/І  (Ukrainian dotted I)
        (32, 0x0432, 0x0412, 0x0412),  # D → в/В
        (33, 0x0430, 0x0410, 0x0410),  # F → а/А
        (34, 0x043F, 0x041F, 0x041F),  # G → п/П
        (35, 0x0440, 0x0420, 0x0420),  # H → р/Р
        (36, 0x043E, 0x041E, 0x041E),  # J → о/О
        (37, 0x043B, 0x041B, 0x041B),  # K → л/Л
        (38, 0x0434, 0x0414, 0x0414),  # L → д/Д
        # Z row: я ч с м и т ь б ю
        (44, 0x044F, 0x042F, 0x042F),  # Z → я/Я
        (45, 0x0447, 0x0427, 0x0427),  # X → ч/Ч
        (46, 0x0441, 0x0421, 0x0421),  # C → с/С
        (47, 0x043C, 0x041C, 0x041C),  # V → м/М
        (48, 0x0438, 0x0418, 0x0418),  # B → и/И
        (49, 0x0442, 0x0422, 0x0422),  # N → т/Т
        (50, 0x044C, 0x042C, 0x042C),  # M → ь/Ь
    ]
    punct = [
        (26, 0x0445, 0x0425, 0x0425, 0x0425),  # [ → х/Х
        (27, 0x0457, 0x0407, 0x0407, 0x0407),  # ] → ї/Ї  (Ukrainian Yi)
        (39, 0x0436, 0x0416, 0x0416, 0x0416),  # ; → ж/Ж
        (40, 0x0454, 0x0404, 0x0404, 0x0404),  # ' → є/Є  (Ukrainian Ie)
        (41, 0x0027, 0x0027, 0x007E, 0x007E),  # ` → ' / ~  (apostrophe)
        (43, 0x0491, 0x0490, 0x0490, 0x0490),  # \ → ґ/Ґ  (Ukrainian Ghe with upturn)
        (51, 0x0431, 0x0411, 0x0411, 0x0411),  # , → б/Б
        (52, 0x044E, 0x042E, 0x042E, 0x042E),  # . → ю/Ю
        (53, 0x002E, 0x002E, 0x002C, 0x002C),  # / → . / ,
    ]
    return letters, punct


def czech_layout():
    """Czech — QWERTZ. Y↔Z swap, Czech characters on number row."""
    punct = [
        # Number row: unshifted = Czech chars, shifted = numbers
        (2,  0x2B, 0x2B, 0x31, 0x31),       # + / 1
        (3,  0x011B, 0x011B, 0x32, 0x32),   # ě / 2
        (4,  0x0161, 0x0161, 0x33, 0x33),   # š / 3
        (5,  0x010D, 0x010D, 0x34, 0x34),   # č / 4
        (6,  0x0159, 0x0159, 0x35, 0x35),   # ř / 5
        (7,  0x017E, 0x017E, 0x36, 0x36),   # ž / 6
        (8,  0x00FD, 0x00FD, 0x37, 0x37),   # ý / 7
        (9,  0x00E1, 0x00E1, 0x38, 0x38),   # á / 8
        (10, 0x00ED, 0x00ED, 0x39, 0x39),   # í / 9
        (11, 0x00E9, 0x00E9, 0x30, 0x30),   # é / 0
        (12, 0x3D, 0x3D, 0x25, 0x25),       # = / %
        (13, 0x00B4, 0x00B4, 0x02C7, 0x02C7),  # ´ / ˇ  (dead accents)
        (26, 0x00FA, 0x00FA, 0x2F, 0x2F),   # ú / /
        (27, 0x29, 0x29, 0x28, 0x28),       # ) / (
        (39, 0x016F, 0x016F, 0x22, 0x22),   # ů / "
        (40, 0x00A7, 0x00A7, 0x21, 0x21),   # § / !
        (41, 0x3B, 0x3B, 0x00B0, 0x00B0),   # ; / °
        (43, 0x00A8, 0x00A8, 0x27, 0x27),   # ¨ / '
        (51, 0x2C, 0x2C, 0x3F, 0x3F),       # , / ?
        (52, 0x2E, 0x2E, 0x3A, 0x3A),       # . / :
        (53, 0x2D, 0x2D, 0x5F, 0x5F),       # - / _
    ]
    return _qwertz_letters(), punct



def hungarian_layout():
    """Hungarian — QWERTZ with Hungarian accented characters."""
    punct = [
        # Number row shifts differ
        (2,  0x31, 0x31, 0x27, 0x27),       # 1 / '
        (3,  0x32, 0x32, 0x22, 0x22),       # 2 / "
        (4,  0x33, 0x33, 0x2B, 0x2B),       # 3 / +
        (5,  0x34, 0x34, 0x21, 0x21),       # 4 / !
        (6,  0x35, 0x35, 0x25, 0x25),       # 5 / %
        (7,  0x36, 0x36, 0x2F, 0x2F),       # 6 / /
        (8,  0x37, 0x37, 0x3D, 0x3D),       # 7 / =
        (9,  0x38, 0x38, 0x28, 0x28),       # 8 / (
        (10, 0x39, 0x39, 0x29, 0x29),       # 9 / )
        (11, 0x00F6, 0x00D6, 0x00D6, 0x00D6),  # ö / Ö
        (12, 0x00FC, 0x00DC, 0x00DC, 0x00DC),  # ü / Ü
        (13, 0x00F3, 0x00D3, 0x00D3, 0x00D3),  # ó / Ó
        (26, 0x0151, 0x0150, 0x0150, 0x0150),  # ő / Ő
        (27, 0x00FA, 0x00DA, 0x00DA, 0x00DA),  # ú / Ú
        (39, 0x00E9, 0x00C9, 0x00C9, 0x00C9),  # é / É
        (40, 0x00E1, 0x00C1, 0x00C1, 0x00C1),  # á / Á
        (41, 0x30, 0x30, 0x00A7, 0x00A7),   # 0 / §
        (43, 0x0171, 0x0170, 0x0170, 0x0170),  # ű / Ű
        (51, 0x2C, 0x2C, 0x3F, 0x3F),       # , / ?
        (52, 0x2E, 0x2E, 0x3A, 0x3A),       # . / :
        (53, 0x2D, 0x2D, 0x5F, 0x5F),       # - / _
    ]
    return _qwertz_letters(), punct


def turkish_layout():
    """Turkish Q — QWERTY base with Turkish-specific i/ı distinction.
    Key 23 (I position) → ı/I (dotless), Key 40 → i/İ (dotted)."""
    # Turkish letters: mostly US QWERTY but with ı/I distinction
    letters = []
    for kc, lower, upper, qt in _us_letters():
        if kc == 23:  # I position → ı (dotless small i) / I (capital I without dot)
            letters.append((23, 0x0131, 0x49, 0x49))  # ı / I
        else:
            letters.append((kc, lower, upper, qt))

    punct = [
        (12, 0x2A, 0x2A, 0x3F, 0x3F),       # * / ?
        (13, 0x2D, 0x2D, 0x5F, 0x5F),       # - / _
        (26, 0x011F, 0x011E, 0x011E, 0x011E),  # ğ / Ğ
        (27, 0x00FC, 0x00DC, 0x00DC, 0x00DC),  # ü / Ü
        (39, 0x015F, 0x015E, 0x015E, 0x015E),  # ş / Ş
        (40, 0x69, 0x0130, 0x69, 0x0130),    # i / İ  (dotted small i / capital İ)
        (41, 0x22, 0x22, 0x00E9, 0x00E9),    # " / é
        (43, 0x2C, 0x2C, 0x3B, 0x3B),        # , / ;
        (51, 0x00F6, 0x00D6, 0x00D6, 0x00D6),  # ö / Ö
        (52, 0x00E7, 0x00C7, 0x00C7, 0x00C7),  # ç / Ç
        (53, 0x2E, 0x2E, 0x3A, 0x3A),        # . / :
    ]
    return letters, punct


def greek_layout():
    """Standard Greek keyboard layout."""
    letters = [
        # Q row (keycodes 16-25): ; ς ε ρ τ υ θ ι ο π
        (16, 0x003B, 0x003A, 0x003B),  # Q → ;/:  (semicolon, not a letter)
        (17, 0x03C2, 0x03A3, 0x03A3),  # W → ς/Σ  (final sigma)
        (18, 0x03B5, 0x0395, 0x0395),  # E → ε/Ε
        (19, 0x03C1, 0x03A1, 0x03A1),  # R → ρ/Ρ
        (20, 0x03C4, 0x03A4, 0x03A4),  # T → τ/Τ
        (21, 0x03C5, 0x03A5, 0x03A5),  # Y → υ/Υ
        (22, 0x03B8, 0x0398, 0x0398),  # U → θ/Θ
        (23, 0x03B9, 0x0399, 0x0399),  # I → ι/Ι
        (24, 0x03BF, 0x039F, 0x039F),  # O → ο/Ο
        (25, 0x03C0, 0x03A0, 0x03A0),  # P → π/Π
        # A row (keycodes 30-38): α σ δ φ γ η ξ κ λ
        (30, 0x03B1, 0x0391, 0x0391),  # A → α/Α
        (31, 0x03C3, 0x03A3, 0x03A3),  # S → σ/Σ
        (32, 0x03B4, 0x0394, 0x0394),  # D → δ/Δ
        (33, 0x03C6, 0x03A6, 0x03A6),  # F → φ/Φ
        (34, 0x03B3, 0x0393, 0x0393),  # G → γ/Γ
        (35, 0x03B7, 0x0397, 0x0397),  # H → η/Η
        (36, 0x03BE, 0x039E, 0x039E),  # J → ξ/Ξ
        (37, 0x03BA, 0x039A, 0x039A),  # K → κ/Κ
        (38, 0x03BB, 0x039B, 0x039B),  # L → λ/Λ
        # Z row (keycodes 44-50): ζ χ ψ ω β ν μ
        (44, 0x03B6, 0x0396, 0x0396),  # Z → ζ/Ζ
        (45, 0x03C7, 0x03A7, 0x03A7),  # X → χ/Χ
        (46, 0x03C8, 0x03A8, 0x03A8),  # C → ψ/Ψ
        (47, 0x03C9, 0x03A9, 0x03A9),  # V → ω/Ω
        (48, 0x03B2, 0x0392, 0x0392),  # B → β/Β
        (49, 0x03BD, 0x039D, 0x039D),  # N → ν/Ν
        (50, 0x03BC, 0x039C, 0x039C),  # M → μ/Μ
    ]
    punct = [
        (39, 0x0384, 0x0384, 0x00A8, 0x00A8),  # ΄ / ¨ (tonos / diaeresis)
        (40, 0x0027, 0x0027, 0x0022, 0x0022),   # ' / "
        (41, 0x0060, 0x0060, 0x007E, 0x007E),   # ` / ~
    ]
    return letters, punct


def hebrew_layout():
    """Hebrew — SI 1452 standard layout. Hebrew has no uppercase;
    shift on letter keys produces the same character."""
    letters = [
        # Q row: / ' ק ר א ט ו ן ם פ
        (16, 0x002F, 0x002F, 0x002F),  # Q → /
        (17, 0x0027, 0x0027, 0x0027),  # W → '
        (18, 0x05E7, 0x05E7, 0x05E7),  # E → ק
        (19, 0x05E8, 0x05E8, 0x05E8),  # R → ר
        (20, 0x05D0, 0x05D0, 0x05D0),  # T → א
        (21, 0x05D8, 0x05D8, 0x05D8),  # Y → ט
        (22, 0x05D5, 0x05D5, 0x05D5),  # U → ו
        (23, 0x05DF, 0x05DF, 0x05DF),  # I → ן (final nun)
        (24, 0x05DD, 0x05DD, 0x05DD),  # O → ם (final mem)
        (25, 0x05E4, 0x05E4, 0x05E4),  # P → פ
        # A row: ש ד ג כ ע י ח ל ך
        (30, 0x05E9, 0x05E9, 0x05E9),  # A → ש
        (31, 0x05D3, 0x05D3, 0x05D3),  # S → ד
        (32, 0x05D2, 0x05D2, 0x05D2),  # D → ג
        (33, 0x05DB, 0x05DB, 0x05DB),  # F → כ
        (34, 0x05E2, 0x05E2, 0x05E2),  # G → ע
        (35, 0x05D9, 0x05D9, 0x05D9),  # H → י
        (36, 0x05D7, 0x05D7, 0x05D7),  # J → ח
        (37, 0x05DC, 0x05DC, 0x05DC),  # K → ל
        (38, 0x05DA, 0x05DA, 0x05DA),  # L → ך (final kaf)
        # Z row: ז ס ב ה נ מ צ
        (44, 0x05D6, 0x05D6, 0x05D6),  # Z → ז
        (45, 0x05E1, 0x05E1, 0x05E1),  # X → ס
        (46, 0x05D1, 0x05D1, 0x05D1),  # C → ב
        (47, 0x05D4, 0x05D4, 0x05D4),  # V → ה
        (48, 0x05E0, 0x05E0, 0x05E0),  # B → נ
        (49, 0x05DE, 0x05DE, 0x05DE),  # N → מ
        (50, 0x05E6, 0x05E6, 0x05E6),  # M → צ
    ]
    punct = [
        (39, 0x05E3, 0x05E3, 0x05E3, 0x05E3),  # ; → ף (final pe)
        (40, 0x002C, 0x002C, 0x0022, 0x0022),   # ' → , / "
        (41, 0x003B, 0x003B, 0x007E, 0x007E),   # ` → ; / ~
        (51, 0x05EA, 0x05EA, 0x05EA, 0x05EA),   # , → ת
        (52, 0x05E5, 0x05E5, 0x05E5, 0x05E5),   # . → ץ (final tsade)
        (53, 0x002E, 0x002E, 0x002F, 0x002F),   # / → . / /
    ]
    return letters, punct



# ══════════════════════════════════════════════════════════════════════
# Layout registry — maps internal layout key to layout function
# ══════════════════════════════════════════════════════════════════════

LAYOUTS = {
    "us": us_layout,
    "uk": uk_layout,
    "de": german_layout,
    "fr": french_layout,
    "es": spanish_layout,
    "it": italian_layout,
    "pt": portuguese_layout,
    "br": brazilian_layout,
    "nl": dutch_layout,
    "sv": swedish_layout,
    "no": norwegian_layout,
    "dk": danish_layout,
    "fi": finnish_layout,
    "de_ch": swiss_german_layout,
    "fr_ch": swiss_french_layout,
    "be": belgian_layout,
    "ru": russian_layout,
    "ua": ukrainian_layout,
    "cz": czech_layout,
    "hu": hungarian_layout,
    "tr": turkish_layout,
    "gr": greek_layout,
    "he": hebrew_layout,
}


def get_layout_mappings(layout_name):
    """Return the raw (letters, punct) data for a layout.

    Useful for the binary patcher which needs the unicode mappings
    without generating a full .qmap file.
    """
    if layout_name not in LAYOUTS:
        raise ValueError(f"Unknown layout: {layout_name}. Available: {list(LAYOUTS.keys())}")
    return LAYOUTS[layout_name]()


def generate_qmap(layout_name):
    """Generate a complete .qmap binary for the given layout."""
    letters, punct = get_layout_mappings(layout_name)

    entries = _base_entries()
    entries.extend(_letter_entries(letters))
    entries.extend(_punctuation_entries(punct))

    # Remove base entries that are overridden by punct
    punct_keycodes = {}
    for kc, plain_u, plain_qt, shift_u, shift_qt in punct:
        punct_keycodes.setdefault(kc, set()).update([MOD_PLAIN, MOD_SHIFT])

    filtered = []
    for entry in entries:
        kc, uni, qt, mod, flags, special = entry
        # Keep if not overridden by punct, or if it's a punct entry itself
        if kc not in punct_keycodes or mod not in punct_keycodes[kc] or (uni, qt) != (uni, qt):
            filtered.append(entry)

    # Deduplicate: later entries (from letters/punct) override earlier (from base)
    seen = {}
    for entry in entries:
        kc, uni, qt, mod, flags, special = entry
        seen[(kc, mod)] = entry
    deduped = sorted(seen.values(), key=lambda e: (e[0], e[3]))

    # Pack binary
    header = struct.pack('>IIII', MAGIC, VERSION, len(deduped), 0)  # 0 compose entries
    body = b''.join(
        struct.pack('>HHIBBH', kc, uni, qt, mod, flags, special)
        for kc, uni, qt, mod, flags, special in deduped
    )

    return header + body


def main():
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--all":
        # Generate all layouts
        layouts = list(LAYOUTS.keys())
    else:
        layouts = [sys.argv[1] if len(sys.argv) > 1 else "us"]

    out_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "keymaps")
    os.makedirs(out_dir, exist_ok=True)

    for layout in layouts:
        out_path = os.path.join(out_dir, f"{layout}.qmap")
        data = generate_qmap(layout)
        with open(out_path, "wb") as f:
            f.write(data)
        n_entries = (len(data) - 16) // 12
        print(f"Generated {layout:>10s}.qmap  ({len(data):5d} bytes, {n_entries:3d} entries)")


if __name__ == "__main__":
    main()
