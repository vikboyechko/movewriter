import os
import tkinter as tk
from ui.app import App


def main():
    root = tk.Tk()

    icon_path = os.path.join(os.path.dirname(__file__), "images", "movewriter-icon.png")
    if os.path.exists(icon_path):
        icon = tk.PhotoImage(file=icon_path)
        root.iconphoto(True, icon)

    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
