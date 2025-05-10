import subprocess
import sys
import os
import time
import json
from pathlib import Path
from colorama import init, Fore, Style
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QPushButton,
    QComboBox, QTextEdit, QHBoxLayout, QMainWindow, QStyleFactory, QTabWidget, QLineEdit
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

def get_device_ip(device_id):
    # Try to get the device's IP address via adb shell
    cmd = f"adb -s {device_id} shell ip -f inet addr show wlan0"
    stdout, _ = run_command(cmd)
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("inet "):
            ip = line.split()[1].split('/')[0]
            if ip.startswith("192."):
                return ip
    return None

def ensure_wireless_connected(device_id):
    ip = get_device_ip(device_id)
    if not ip:
        return None  # No IP found, can't connect wirelessly
    # Enable tcpip mode
    run_command(f"adb -s {device_id} tcpip 5555")
    # Try to connect
    stdout, _ = run_command(f"adb connect {ip}:5555")
    if "connected" in stdout or "already connected" in stdout:
        return f"{ip}:5555"
    return None

# Path for storing last known wireless IPs
if getattr(sys, 'frozen', False):
    # Running as a bundled exe
    DATA_FILE = Path(sys.executable).parent / "fadadb_state.json"
else:
    # Running as script
    DATA_FILE = Path(__file__).parent / "fadadb_state.json"

def save_last_wireless_ips(ips):
    try:
        with open(DATA_FILE, "w") as f:
            json.dump({"wireless_ips": ips}, f)
    except Exception as e:
        pass  # Ignore errors

def load_last_wireless_ips():
    try:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
            return data.get("wireless_ips", [])
    except Exception:
        return []

def get_all_devices_with_wireless():
    devices = get_connected_devices()
    all_devices = set(devices)
    wireless_ips = []
    for dev in devices:
        if not is_wireless(dev):
            wireless_id = ensure_wireless_connected(dev)
            if wireless_id:
                all_devices.add(wireless_id)
                wireless_ips.append(wireless_id)
        elif is_wireless(dev):
            wireless_ips.append(dev)
    # Save all seen wireless IPs
    save_last_wireless_ips(wireless_ips)
    return list(all_devices)

def auto_reconnect_wireless():
    ips = load_last_wireless_ips()
    reconnected = []
    for ip in ips:
        stdout, stderr = run_command(f"adb connect {ip}")
        if "connected" in stdout or "already connected" in stdout:
            reconnected.append(ip)
    return reconnected

def connect_device():
    devices = get_all_devices_with_wireless()
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
        self.setWindowTitle("FadADB - ADB manager for USB and wireless devices")
        self.setStyleSheet("background-color: #121212; color: white;")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # Device Tab
        self.device_tab = QWidget()
        self.device_layout = QVBoxLayout()
        self.label = QLabel("Available Devices:")
        self.combo = QComboBox()
        self.combo.setPlaceholderText("Select a device from the list below...")
        self.refresh_button = QPushButton("Refresh Devices")
        self.connect_button = QPushButton("Connect")
        self.test_button = QPushButton("Test Device")
        # Manual add row
        manual_row = QHBoxLayout()
        self.manual_ip_input = QLineEdit()
        self.manual_ip_input.setPlaceholderText("e.g. 192.168.1.2:5555")
        self.add_manual_button = QPushButton("Add Device by IP")
        self.add_manual_button.setToolTip("Add a device by IP:Port (e.g. 192.168.1.2:5555)")
        self.add_manual_button.clicked.connect(self.add_manual_device)
        manual_row.addWidget(self.manual_ip_input)
        manual_row.addWidget(self.add_manual_button)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.view_state_button = QPushButton("View Saved Wireless Devices")
        self.view_state_button.clicked.connect(self.show_state_file)

        self.refresh_button.clicked.connect(self.load_devices)
        self.connect_button.clicked.connect(self.gui_connect_device)
        self.test_button.clicked.connect(self.test_device)

        self.device_layout.addWidget(self.label)
        self.device_layout.addWidget(self.combo)
        self.device_layout.addLayout(manual_row)
        self.device_layout.addWidget(self.view_state_button)
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.refresh_button)
        button_layout.addWidget(self.connect_button)
        button_layout.addWidget(self.test_button)
        self.device_layout.addLayout(button_layout)
        self.device_layout.addWidget(QLabel("\nLogs:"))
        self.device_layout.addWidget(self.log)
        self.device_tab.setLayout(self.device_layout)
        self.tabs.addTab(self.device_tab, "Devices")

        # ADB Tab
        self.adb_tab = QWidget()
        self.adb_layout = QVBoxLayout()
        self.toggle_server_button = QPushButton("Restart ADB Server")
        self.adb_log = QTextEdit()
        self.adb_log.setReadOnly(True)
        self.toggle_server_button.clicked.connect(self.toggle_adb_server)
        adb_btn_layout = QHBoxLayout()
        adb_btn_layout.addWidget(self.toggle_server_button)
        self.adb_layout.addLayout(adb_btn_layout)
        self.adb_layout.addWidget(QLabel("\nADB Logs:"))
        self.adb_layout.addWidget(self.adb_log)
        self.adb_tab.setLayout(self.adb_layout)
        self.tabs.addTab(self.adb_tab, "ADB Tools")

        self.load_devices()

    def log_action(self, message, adb=False):
        if adb:
            self.adb_log.append(message)
        else:
            self.log.append(message)

    def load_devices(self):
        self.combo.clear()
        devices = get_all_devices_with_wireless()
        if devices:
            self.combo.addItems([format_device_label(d) for d in devices])
            self.log_action("[+] Devices loaded.")
        else:
            self.log_action("[!] No connected devices found.")

    def gui_connect_device(self):
        label = self.combo.currentText()
        if not label:
            self.log_action("[!] No device selected.")
            return
        device = label.split(" ", 1)[-1]
        # Fix: Only use the actual device ID (strip label prefix)
        if label.startswith("📡 Wireless:") or label.startswith("🔌 USB:"):
            device = label.split(": ", 1)[-1]
        if is_wireless(device):
            stdout, stderr = run_command(f"adb connect {device}")
        else:
            stdout, stderr = "already connected", ""
        if "connected" in stdout:
            self.log_action(f"[+] Connected to {device}.")
        elif "already connected" in stdout:
            self.log_action(f"[i] Already connected: {device}.")
        else:
            self.log_action(f"[!] Connection failed: {stdout or stderr}")

    def test_device(self):
        label = self.combo.currentText()
        if not label:
            self.log_action("[!] No device selected.")
            return
        device = label.split(" ", 1)[-1]
        # Fix: Only use the actual device ID (strip label prefix)
        if label.startswith("📡 Wireless:") or label.startswith("🔌 USB:"):
            device = label.split(": ", 1)[-1]
        self.log_action(f"[Test] Running: adb -s {device} shell getprop ro.product.model")
        stdout, stderr = run_command(f"adb -s {device} shell getprop ro.product.model")
        if stdout:
            self.log_action(f"[ADB STDOUT] {stdout}")
        if stderr:
            self.log_action(f"[ADB STDERR] {stderr}")
        if not stdout and not stderr:
            self.log_action("[!] No response from device.")

    def toggle_adb_server(self):
        self.toggle_server_button.setEnabled(False)
        self.toggle_server_button.setText("Restarting...")
        self.log_action("[ADB] Killing server...", adb=True)
        stdout_kill, stderr_kill = run_command("adb kill-server")
        self.log_action(f"[ADB Kill-Server] {stdout_kill or stderr_kill}", adb=True)
        self.log_action("[ADB] Starting server...", adb=True)
        stdout_start, stderr_start = run_command("adb start-server")
        self.log_action(f"[ADB Start-Server] {stdout_start or stderr_start}", adb=True)
        self.log_action("[ADB] Attempting to auto-reconnect wireless devices...", adb=True)
        reconnected = auto_reconnect_wireless()
        if reconnected:
            self.log_action(f"[ADB] Reconnected: {', '.join(reconnected)}", adb=True)
        else:
            self.log_action("[ADB] No wireless devices reconnected.", adb=True)
        self.load_devices()
        self.log_action("[ADB] Device list refreshed.", adb=True)
        self.toggle_server_button.setText("Restart ADB Server")
        self.toggle_server_button.setEnabled(True)

    def add_manual_device(self):
        ip = self.manual_ip_input.text().strip()
        if not ip:
            self.log_action("[!] Please enter a device IP.")
            return
        if not (":" in ip and all(part.isdigit() for part in ip.split(":")[0].split("."))):
            self.log_action("[!] Invalid IP format. Use e.g. 192.168.1.2:5555")
            return
        # Try to connect
        self.log_action(f"[Manual Add] Connecting to {ip}...")
        stdout, stderr = run_command(f"adb connect {ip}")
        if "connected" in stdout or "already connected" in stdout:
            # Add to state file
            ips = load_last_wireless_ips()
            if ip not in ips:
                ips.append(ip)
                save_last_wireless_ips(ips)
            self.log_action(f"[+] Connected to {ip} and added to known devices.")
            self.load_devices()
        else:
            self.log_action(f"[!] Connection failed: {stdout or stderr}")

    def show_state_file(self):
        try:
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
            pretty = json.dumps(data, indent=4)
            self.log_action(f"[fadadb_state.json] ({DATA_FILE})\n" + pretty)
        except Exception as e:
            self.log_action(f"[!] Could not read state file: {e}\nPath tried: {DATA_FILE}")

# CLI Menu
def main_menu():
    while True:
        clear_terminal()
        print(Fore.RED + Style.BRIGHT + "FadADB - ADB manager for USB and wireless devices\n")
        print(Fore.GREEN + "📋 Main Menu")
        print(Fore.WHITE + f" {Fore.CYAN}1.{Fore.WHITE} Connect device")
        print(Fore.WHITE + f" {Fore.CYAN}2.{Fore.WHITE} Show connected devices")
        print(Fore.WHITE + f" {Fore.CYAN}3.{Fore.WHITE} Launch GUI")
        print(Fore.WHITE + f" {Fore.CYAN}4.{Fore.WHITE} Restart ADB Server")
        print(Fore.WHITE + f" {Fore.CYAN}5.{Fore.WHITE} Add device by IP (manual)")
        print(Fore.RED + f" {Fore.CYAN}6.{Fore.RED} Exit")
        print(Style.DIM + "\nSelect a number to perform an action.")

        choice = input(Fore.CYAN + "\n🔢 Select an option (1-6): ").strip()

        if choice == '1':
            connect_device()
        elif choice == '2':
            show_connected_devices()
        elif choice == '3':
            launch_gui()
        elif choice == '4':
            restart_adb_server_cli()
        elif choice == '5':
            add_manual_device_cli()
        elif choice == '6':
            print(Fore.RED + Style.BRIGHT + "\n👋 Exiting FadADB. Goodbye!\n")
            break
        else:
            print(Fore.RED + "[!] Invalid option. Please select 1–6.")
            time.sleep(1)

def restart_adb_server_cli():
    print(Fore.YELLOW + "\n[ADB] Killing server...")
    stdout_kill, stderr_kill = run_command("adb kill-server")
    if stdout_kill or stderr_kill:
        print(Fore.WHITE + f"[ADB Kill-Server] {stdout_kill or stderr_kill}")
    print(Fore.YELLOW + "[ADB] Starting server...")
    stdout_start, stderr_start = run_command("adb start-server")
    if stdout_start or stderr_start:
        print(Fore.WHITE + f"[ADB Start-Server] {stdout_start or stderr_start}")
    print(Fore.YELLOW + "[ADB] Attempting to auto-reconnect wireless devices...")
    reconnected = auto_reconnect_wireless()
    if reconnected:
        print(Fore.GREEN + f"[ADB] Reconnected: {', '.join(reconnected)}")
    else:
        print(Fore.RED + "[ADB] No wireless devices reconnected.")
    print(Fore.GREEN + "[ADB] Server restarted. Device list will be refreshed.")
    input(Fore.WHITE + Style.DIM + "\n🔙 Press Enter to return to menu...")

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

# Add CLI manual add feature
def add_manual_device_cli():
    print(Fore.GREEN + "\n[Manual Add] Enter the device IP (e.g. 192.168.1.2:5555):")
    ip = input(Fore.CYAN + "IP: ").strip()
    if not ip:
        print(Fore.RED + "[!] No IP entered.")
        return
    if not (":" in ip and all(part.isdigit() for part in ip.split(":")[0].split("."))):
        print(Fore.RED + "[!] Invalid IP format. Use e.g. 192.168.1.2:5555")
        return
    print(Fore.YELLOW + f"[Manual Add] Connecting to {ip}...")
    stdout, stderr = run_command(f"adb connect {ip}")
    if "connected" in stdout or "already connected" in stdout:
        ips = load_last_wireless_ips()
        if ip not in ips:
            ips.append(ip)
            save_last_wireless_ips(ips)
        print(Fore.GREEN + f"[+] Connected to {ip} and added to known devices.")
    else:
        print(Fore.RED + f"[!] Connection failed: {stdout or stderr}")
    input(Fore.WHITE + Style.DIM + "\n🔙 Press Enter to return to menu...")

# Entry Point
if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == "--gui":
        launch_gui()
    else:
        main_menu()
