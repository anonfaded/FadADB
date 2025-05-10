import subprocess
import sys
import os
import time
from colorama import init, Fore, Style
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QPushButton,
    QComboBox, QTextEdit, QHBoxLayout, QMainWindow, QStyleFactory
)
from PyQt6.QtCore import Qt

init(autoreset=True)

# Utility Functions
def clear_terminal():
    os.system('cls' if os.name == 'nt' else 'clear')

def run_command(command):
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        return result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return '', str(e)

def get_connected_devices():
    output, _ = run_command("adb devices")
    lines = output.splitlines()[1:]
    return [line.split('\t')[0] for line in lines if '\tdevice' in line]

def is_wireless(device_id):
    # Checking if device_id starts with "192." indicating it's a wireless device
    return device_id.startswith("192.")

def format_device_label(device_id):
    # Check if device ID starts with "192." to indicate it's wireless
    if device_id.startswith("192."):
        return f"📡 Wireless: {device_id}"
    else:
        return f"🔌 USB: {device_id}"

def connect_device():
    devices = get_connected_devices()
    if not devices:
        print(Fore.RED + "\n[❌] No available devices to connect.")
        input(Fore.WHITE + Style.DIM + "\n🔙 Press Enter to return to menu...")
        return

    print(Fore.GREEN + "\n📱 Available Devices:")
    for idx, dev in enumerate(devices, 1):
        print(f" {idx}. {format_device_label(dev)}")

    print(Style.DIM + "\n✏️  Enter the number of the device to connect or 'q' to return.")
    selection = input(Fore.CYAN + "\n🔢 Select device: ").strip()

    if selection.lower() == 'q':
        return
    if not selection.isdigit() or int(selection) < 1 or int(selection) > len(devices):
        print(Fore.RED + "[!] Invalid selection.")
        time.sleep(1)
        return

    selected_device = devices[int(selection) - 1]

    if is_wireless(selected_device):
        stdout, stderr = run_command(f"adb connect {selected_device}")
    else:
        print(Fore.YELLOW + f"[ℹ️] Physical device detected, no connection needed: {selected_device}")
        stdout, stderr = "already connected", ""

    if "connected" in stdout:
        print(Fore.GREEN + f"[✅] Connected to {selected_device}.")
    elif "already connected" in stdout:
        print(Fore.YELLOW + f"[ℹ️] Already connected: {selected_device}.")
    else:
        print(Fore.RED + f"[❌] Connection failed: {stdout or stderr}")
    input(Fore.WHITE + Style.DIM + "\n🔙 Press Enter to return to menu...")

def show_connected_devices():
    clear_terminal()
    print(Fore.GREEN + "\n🔌 Connected Devices:\n")

    stdout, _ = run_command("adb devices")
    lines = stdout.strip().split('\n')[1:]  # skip the header

    if not lines or all("device" not in line for line in lines):
        print(Fore.RED + "[❌] No connected devices found.")
    else:
        for idx, line in enumerate(lines, 1):
            device = line.strip().split()[0]
            print(f" {Fore.CYAN}{idx}.{Fore.GREEN} {format_device_label(device)}")

    input(Fore.WHITE + Style.DIM + "\n🔙 Press Enter to return to menu...")

# GUI Class
class FadADBGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FadADB - GUI")
        self.setStyleSheet("background-color: #121212; color: white;")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)

        widget = QWidget()
        self.setCentralWidget(widget)

        self.layout = QVBoxLayout()
        self.label = QLabel("Available Devices:")
        self.combo = QComboBox()
        self.refresh_button = QPushButton("Refresh")
        self.connect_button = QPushButton("Connect")
        self.log = QTextEdit()
        self.log.setReadOnly(True)

        self.refresh_button.clicked.connect(self.load_devices)
        self.connect_button.clicked.connect(self.gui_connect_device)

        self.combo.setStyleSheet("background-color: #1e1e1e; color: white;")
        self.refresh_button.setStyleSheet("background-color: #333; color: white;")
        self.connect_button.setStyleSheet("background-color: #008000; color: black;")

        self.layout.addWidget(self.label)
        self.layout.addWidget(self.combo)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.refresh_button)
        button_layout.addWidget(self.connect_button)
        self.layout.addLayout(button_layout)

        self.layout.addWidget(QLabel("\nLogs:"))
        self.layout.addWidget(self.log)

        widget.setLayout(self.layout)
        self.load_devices()

    def load_devices(self):
        self.combo.clear()
        devices = get_connected_devices()
        if devices:
            self.combo.addItems([format_device_label(d) for d in devices])
            self.log.append("[+] Devices loaded.")
        else:
            self.log.append("[!] No connected devices found.")

    def gui_connect_device(self):
        label = self.combo.currentText()
        if not label:
            self.log.append("[!] No device selected.")
            return

        device = label.split(" ", 1)[-1]  # Remove the (Label) prefix

        if is_wireless(device):
            stdout, stderr = run_command(f"adb connect {device}")
        else:
            stdout, stderr = "already connected", ""

        if "connected" in stdout:
            self.log.append(f"[+] Connected to {device}.")
        elif "already connected" in stdout:
            self.log.append(f"[i] Already connected: {device}.")
        else:
            self.log.append(f"[!] Connection failed: {stdout or stderr}")

# CLI Menu
def main_menu():
    while True:
        clear_terminal()
        print(Fore.RED + Style.BRIGHT + "FadADB - Wireless ADB Connect Tool\n")
        print(Fore.GREEN + "📋 Main Menu")
        print(Fore.WHITE + f" {Fore.CYAN}1.{Fore.WHITE} Connect device")
        print(Fore.WHITE + f" {Fore.CYAN}2.{Fore.WHITE} Show connected devices")
        print(Fore.WHITE + f" {Fore.CYAN}3.{Fore.WHITE} Launch GUI")
        print(Fore.WHITE + f" {Fore.CYAN}4.{Fore.WHITE} Exit")
        print(Style.DIM + "\nSelect a number to perform an action.")

        choice = input(Fore.CYAN + "\n🔢 Select an option (1-4): ").strip()

        if choice == '1':
            connect_device()
        elif choice == '2':
            show_connected_devices()
        elif choice == '3':
            launch_gui()
        elif choice == '4':
            print(Fore.YELLOW + "\n👋 Exiting FadADB. Goodbye!\n")
            break
        else:
            print(Fore.RED + "[!] Invalid option. Please select 1–4.")
            time.sleep(1)

def launch_gui():
    app = QApplication(sys.argv)
    app.setStyle(QStyleFactory.create("Fusion"))
    window = FadADBGUI()
    window.resize(500, 400)
    window.show()

    # Keep the CLI alive while GUI is open
    app.exec()

    # When GUI is closed, return control to CLI
    input(Fore.WHITE + Style.DIM + "\n🔙 Press Enter to return to menu...")


# Entry Point
if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == "--gui":
        launch_gui()
    else:
        main_menu()
