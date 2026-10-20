import sys
import os
import tkinter as tk
from ui.app import App


def main():
    if sys.platform == "win32":
        # Set AppUserModelID so the taskbar uses our icon instead of the
        # default Python/Tk feather icon.
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "movewriter.movewriter.app"
        )

    root = tk.Tk()

    if sys.platform == "win32":
        # Set the window/taskbar icon (Windows only — macOS uses the .app bundle icon)
        if getattr(sys, "frozen", False):
            base = sys._MEIPASS
        else:
            base = os.path.dirname(__file__)
        icon_path = os.path.join(base, "icon", "icon.ico")
        if os.path.exists(icon_path):
            root.iconbitmap(icon_path)

    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
