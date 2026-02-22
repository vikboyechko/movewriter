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
        self.root.geometry("480x920")
        self.root.minsize(420, 700)

        styles.configure_root(self.root)

        self.ssh = SSHClient()
        self.cfg = config.load()

        self.screen = MainScreen(self.root, self)
        self.screen.pack(fill="both", expand=True)
