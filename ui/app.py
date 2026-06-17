import tkinter as tk
import threading

from ui import styles
from ui.main_screen import MainScreen
from core.ssh_client import SSHClient
from core import config


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("MoveWriter")
        # Cap the window to the available screen height so the whole window
        # (and its scrollbar) stays on-screen on low-res displays; the content
        # scrolls inside MainScreen when it doesn't all fit.
        screen_h = self.root.winfo_screenheight()
        win_h = min(990, max(560, screen_h - 120))
        self.root.geometry(f"480x{win_h}")
        self.root.minsize(420, 480)

        styles.configure_root(self.root)

        self.ssh = SSHClient()
        self.cfg = config.load()

        self.screen = MainScreen(self.root, self)
        self.screen.pack(fill="both", expand=True)
