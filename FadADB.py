import os
import platform
import subprocess
import time
import sys
from PyQt6.QtWidgets import QApplication, QWidget, QPushButton, QVBoxLayout, QLabel, QMessageBox, QComboBox, QInputDialog
from colorama import init, Fore, Style

# ---------- Terminal UI Setup ----------
init(autoreset=True)

RED = Fore.RED
CYAN = Fore.CYAN
GREEN = Fore.GREEN
YELLOW = Fore.YELLOW
WHITE = Fore.WHITE
RESET = Style.RESET_ALL

# ---------- Terminal Utilities ----------
def clear():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_header():
    clear()
    print(f"{RED}🛡️ FadADB - ADB Wireless Tool")
    print(f"{RED}🔧 By FadSecLab")
    print(f"{RED}{'-'*35}\n")

def safe_input(prompt):
    try:
        return input(prompt)
    except (KeyboardInterrupt, EOFError):
        print(f"\n{RED}⚠️ Operation cancelled by user.")
        main_menu()

# ---------- ADB Commands ----------
def run_adb_command(cmd):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return "", str(e)

def get_device_ip():
    # Use QInputDialog to ask for an IP address or port
    ip, ok = QInputDialog.getText(None, "Enter IP Address", "Please enter device IP:")

    if ok:
        print(f"IP address entered: {ip}")
        return ip
    else:
        print("No IP entered.")
        return None

def enable_tcpip():
    print(f"{CYAN}🔌 Enabling TCP/IP mode on port 5555...")
    _, err = run_adb_command("adb tcpip 5555")
    if err:
        print(f"{RED}❌ Error: {err}")
        return False
    return True

def connect_to_ip(ip):
    print(f"{CYAN}📡 Connecting to {ip}:5555...")
    out, err = run_adb_command(f"adb connect {ip}:5555")
    if "connected" in out.lower():
        print(f"{GREEN}✅ Connected: {ip}:5555")
    else:
        print(f"{RED}❌ Connection failed: {err or out}")

def show_devices():
    print(f"{CYAN}📱 Connected devices:")
    out, err = run_adb_command("adb devices")
    if out:
        devices = [line.split()[0] for line in out.splitlines()[1:] if line]
        if devices:
            for idx, device in enumerate(devices, 1):
                print(f"{YELLOW}{idx}. {device}")
            return devices
        else:
            print(f"{RED}❌ No devices found.")
            return []
    else:
        print(f"{RED}❌ Error: {err or 'No devices found.'}")
        return []

def show_devices_in_gui():
    out, err = run_adb_command("adb devices")
    devices = []
    if out:
        devices = [line.split()[0] for line in out.splitlines()[1:] if line]
    return devices

# ---------- GUI Components ----------
class FadADB_GUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('FadADB - ADB Wireless Tool')
        self.setStyleSheet("background-color: #1e1e1e; color: white;")
        self.setGeometry(400, 200, 400, 300)

        self.devices = []
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        self.status_label = QLabel("Ready to connect. Select an action.")
        self.status_label.setStyleSheet("color: #f5f5f5;")
        layout.addWidget(self.status_label)

        self.device_selector = QComboBox()
        self.device_selector.setStyleSheet("background-color: #333333; color: white;")
        self.device_selector.setEditable(False)
        layout.addWidget(self.device_selector)

        self.connect_btn = QPushButton("Connect Device via Wi-Fi")
        self.connect_btn.setStyleSheet("background-color: #FF4C4C; color: white;")
        self.connect_btn.clicked.connect(self.connect_device)
        layout.addWidget(self.connect_btn)

        self.show_btn = QPushButton("Show Connected Devices")
        self.show_btn.setStyleSheet("background-color: #4CFF4C; color: white;")
        self.show_btn.clicked.connect(self.show_devices)
        layout.addWidget(self.show_btn)

        self.reconnect_btn = QPushButton("Reconnect (Manual IP)")
        self.reconnect_btn.setStyleSheet("background-color: #FFBF00; color: white;")
        self.reconnect_btn.clicked.connect(self.reconnect_manual)
        layout.addWidget(self.reconnect_btn)

        self.exit_btn = QPushButton("Exit")
        self.exit_btn.setStyleSheet("background-color: #4C4C4C; color: white;")
        self.exit_btn.clicked.connect(self.close)
        layout.addWidget(self.exit_btn)

        self.setLayout(layout)

    def show_message(self, title, message, is_error=False):
        msg = QMessageBox()
        msg.setWindowTitle(title)
        msg.setText(message)
        if is_error:
            msg.setIcon(QMessageBox.Icon.Critical)
        else:
            msg.setIcon(QMessageBox.Icon.Information)
        msg.exec()

    def connect_device(self):
        ip = self.device_selector.currentText()
        if not ip:
            self.show_message("Connection Failed", "No device selected. Please try again.", True)
            return
        self.connect_to_ip(ip)

    def show_devices(self):
        self.devices = show_devices_in_gui()
        if self.devices:
            self.device_selector.clear()
            self.device_selector.addItems(self.devices)
            self.status_label.setText(f"Found {len(self.devices)} devices. Select one to connect.")
        else:
            self.status_label.setText("No devices found.")
            self.show_message("No Devices Found", "No devices detected. Please ensure your device is connected.", True)

    def reconnect_manual(self):
        ip, ok = self.get_manual_ip_input()
        if ok:
            self.connect_to_ip(ip)

    def connect_to_ip(self, ip):
        self.status_label.setText(f"Connecting to {ip}...")
        out, err = run_adb_command(f"adb connect {ip}:5555")
        if "connected" in out.lower():
            self.status_label.setText(f"Device {ip} connected successfully.")
            self.show_message("Connected", f"Device {ip} connected successfully.", False)
        else:
            self.show_message("Connection Failed", f"Failed to connect: {err or out}", True)

    def get_manual_ip_input(self):
        ip, ok = QInputDialog.getText(self, "Enter IP", "Enter the device IP address:")
        return ip, ok

# ---------- Main Menu ----------
def main_menu():
    print_header()
    print(f"{RED}📋 Main Menu")
    print(f"{RED}{'='*35}")
    print(f"{RED}1️⃣  Connect device via WiFi")
    print(f"{RED}2️⃣  Show connected devices")
    print(f"{RED}3️⃣  Reconnect (manual IP entry)")
    print(f"{RED}4️⃣  Launch GUI")
    print(f"{RED}5️⃣  Exit")
    print(f"{RED}{'='*35}")

    choice = safe_input(f"{YELLOW}Select an option (1-5): ")

    if choice == '1':
        connect_device()  # Connect to device (with a selection process)
    elif choice == '2':
        show_devices()
    elif choice == '3':
        reconnect_manual()  # Reconnect by manually entering the IP
    elif choice == '4':
        launch_gui()
    elif choice == '5':
        print(f"{CYAN}👋 Exiting... Stay secure.")
        sys.exit(0)
    else:
        print(f"{RED}❌ Invalid option.")

    time.sleep(1.5)
    main_menu()


def connect_device():
    devices = show_devices()  # Get the list of connected devices
    if not devices:
        print(f"{RED}❌ No devices available. Please ensure your device is connected and try again.")
        return

    print(f"{CYAN}📱 Available devices:")
    for i, device in enumerate(devices, 1):
        print(f"{YELLOW}{i}. {device}")

    selected_device = safe_input(f"{YELLOW}Select a device by number: ")

    try:
        selected_device = int(selected_device)
        if selected_device < 1 or selected_device > len(devices):
            print(f"{RED}❌ Invalid selection.")
            return
        ip = devices[selected_device - 1]
        connect_to_ip(ip)  # Connect to the selected device
    except ValueError:
        print(f"{RED}❌ Invalid input. Please select a valid number.")
        return

def reconnect_manual():
    ip = safe_input(f"{YELLOW}Enter the IP address of the device to reconnect to: ")
    if ip:
        print(f"{CYAN}📡 Attempting to reconnect to {ip}...")
        connect_to_ip(ip)  # Attempt connection with the manually entered IP
    else:
        print(f"{RED}❌ Invalid IP address. Please try again.")


# ---------- GUI Launcher ----------
def launch_gui():
    print(f"{CYAN}💻 Launching GUI...")
    app = QApplication(sys.argv)
    gui = FadADB_GUI()
    gui.show()
    sys.exit(app.exec())

# ---------- Entry Point ----------
def main():
    try:
        main_menu()
    except KeyboardInterrupt:
        print(f"\n{RED}🛑 Interrupted. Exiting cleanly.")
        sys.exit(0)

if __name__ == "__main__":
    main()
