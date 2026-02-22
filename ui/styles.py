import tkinter as tk
from tkinter import ttk

# Colors
BG = "#FAFAF8"
BG_CARD = "#FFFFFF"
BORDER = "#E0E0DC"
FG = "#1A1A1A"
FG_DIM = "#888888"
ACCENT = "#D6393A"
ACCENT_HOVER = "#B02E2F"
SUCCESS = "#2E7D32"
WARNING = "#E65100"
ERROR = "#C62828"

# Fonts
FONT_TITLE = ("Helvetica", 22, "bold")
FONT_HEADING = ("Helvetica", 14, "bold")
FONT_BODY = ("Helvetica", 13)
FONT_STATUS = ("Helvetica", 13)
FONT_SMALL = ("Helvetica", 11)
FONT_MONO = ("Menlo", 12)


def configure_root(root):
    root.configure(bg=BG)
    style = ttk.Style()
    style.theme_use("clam")

    # Frames
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=BG_CARD)

    # Labels
    style.configure("TLabel", background=BG, foreground=FG, font=FONT_BODY)
    style.configure("Title.TLabel", font=FONT_TITLE, foreground=FG, background=BG)
    style.configure("Heading.TLabel", font=FONT_HEADING, foreground=FG, background=BG)
    style.configure("Dim.TLabel", foreground=FG_DIM, background=BG, font=FONT_SMALL)
    style.configure("Success.TLabel", foreground=SUCCESS, background=BG)
    style.configure("Error.TLabel", foreground=ERROR, background=BG)
    style.configure("Warning.TLabel", foreground=WARNING, background=BG)

    # Card-background label variants
    style.configure("Card.TLabel", background=BG_CARD, foreground=FG, font=FONT_BODY)
    style.configure("CardDim.TLabel", background=BG_CARD, foreground=FG_DIM, font=FONT_SMALL)
    style.configure("CardStatus.TLabel", background=BG_CARD, foreground=FG_DIM, font=FONT_STATUS)
    style.configure("CardHeading.TLabel", background=BG_CARD, foreground=FG, font=FONT_HEADING)

    # Accent button (red, primary action)
    style.configure(
        "Accent.TButton",
        background=ACCENT,
        foreground="white",
        font=("Helvetica", 13, "bold"),
        padding=(24, 12),
        borderwidth=0,
    )
    style.map(
        "Accent.TButton",
        background=[("active", ACCENT_HOVER), ("disabled", "#CCCCCC")],
        foreground=[("disabled", "#999999")],
    )

    # Blue button (Bluetooth actions)
    style.configure(
        "Blue.TButton",
        background="#3A6EA5",
        foreground="white",
        font=("Helvetica", 13, "bold"),
        padding=(24, 12),
        borderwidth=0,
    )
    style.map(
        "Blue.TButton",
        background=[("active", "#2D5986"), ("disabled", "#CCCCCC")],
        foreground=[("disabled", "#999999")],
    )

    # Default button (secondary action)
    style.configure(
        "TButton",
        background="#ECECEA",
        foreground=FG,
        font=("Helvetica", 13),
        padding=(20, 12),
        borderwidth=0,
    )
    style.map(
        "TButton",
        background=[("active", "#DDDDD8"), ("disabled", "#F0F0EE")],
        foreground=[("disabled", "#AAAAAA")],
    )

    # Entry
    style.configure(
        "TEntry",
        fieldbackground=BG_CARD,
        foreground=FG,
        insertcolor=FG,
        font=FONT_BODY,
        padding=8,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
    )

    # Scrollbar
    style.configure(
        "TScrollbar",
        background=BG,
        troughcolor=BG,
        bordercolor=BG,
        arrowcolor=FG_DIM,
    )


def make_entry(parent, show=None, **kwargs):
    entry = ttk.Entry(parent, style="TEntry", font=FONT_BODY, **kwargs)
    entry.configure(foreground=FG)
    if show:
        entry.configure(show=show)
    return entry
