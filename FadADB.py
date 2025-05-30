import subprocess
import sys
import os
import time
import json
import platform
import shutil
import logging
import tempfile
import threading
import importlib.util
from pathlib import Path
from colorama import init, Fore, Style
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QPushButton,
    QComboBox, QTextEdit, QHBoxLayout, QMainWindow, QStyleFactory, QTabWidget, QLineEdit,
    QProgressDialog, QDialog, QStatusBar, QProgressBar, QScrollArea, QFrame, QMessageBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QTimer, QPropertyAnimation, QEasingCurve, QPoint, QUrl
from PyQt6.QtGui import QIcon, QPixmap, QTextCursor, QDesktopServices

# Application version
APP_VERSION = "2.0"

init(autoreset=True)

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('FadADB')

# Get base directory and determine path to bundled ADB
if getattr(sys, 'frozen', False):
    # Running as a bundled exe
    BASE_DIR = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
    DATA_FILE = Path(sys.executable).parent / "fadadb_state.json"
else:
    # Running as script
    BASE_DIR = Path(__file__).parent
    DATA_FILE = Path(__file__).parent / "fadadb_state.json"

# State file management
class StateManager:
    """Handles the persistent state file with robust error handling and validation."""
    
    def __init__(self, file_path):
        self.file_path = file_path
        self.default_state = {"wireless_ips": []}
        self._ensure_state_file_exists()
    
    def _ensure_state_file_exists(self):
        """Creates the state file with default values if it doesn't exist."""
        if not self.file_path.exists():
            try:
                with open(self.file_path, 'w') as f:
                    json.dump(self.default_state, f)
                logger.info(f"Created new state file at {self.file_path}")
            except Exception as e:
                logger.error(f"Failed to create state file: {e}")
    
    def _acquire_lock_windows(self, file_handle):
        """Windows-specific file locking."""
        try:
            import msvcrt
            msvcrt.locking(file_handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except ImportError:
            logger.warning("msvcrt module not available, file locking disabled on Windows")
            return True
        except OSError:
            logger.warning("State file is locked by another process")
            return False
        except Exception as e:
            logger.error(f"Windows file locking error: {e}")
            return False
    
    def _acquire_lock_unix(self, file_handle):
        """Unix-specific file locking."""
        try:
            # Try to dynamically import fcntl and use it
            # We'll use a different approach that doesn't trigger linter errors
            lock_module = __import__('fcntl')
            # LOCK_EX = 2, LOCK_NB = 4
            lock_module.lockf(file_handle, lock_module.LOCK_EX | lock_module.LOCK_NB)
            return True
        except ImportError:
            logger.warning("fcntl module not available, file locking disabled on Unix")
            return True
        except IOError:
            logger.warning("State file is locked by another process")
            return False
        except Exception as e:
            logger.error(f"Unix file locking error: {e}")
            return False
    
    def _acquire_lock(self, file_handle):
        """Platform-independent file locking."""
        if platform.system().lower() == 'windows':
            return self._acquire_lock_windows(file_handle)
        else:
            return self._acquire_lock_unix(file_handle)
    
    def _release_lock_windows(self, file_handle):
        """Windows-specific file unlocking."""
        try:
            import msvcrt
            msvcrt.locking(file_handle.fileno(), msvcrt.LK_UNLCK, 1)
        except (ImportError, OSError, Exception):
            pass
    
    def _release_lock_unix(self, file_handle):
        """Unix-specific file unlocking."""
        try:
            # Try to dynamically import fcntl and use it
            lock_module = __import__('fcntl')
            # LOCK_UN = 8
            lock_module.lockf(file_handle, lock_module.LOCK_UN)
        except (ImportError, IOError, Exception):
            pass
    
    def _release_lock(self, file_handle):
        """Platform-independent file unlocking."""
        if platform.system().lower() == 'windows':
            self._release_lock_windows(file_handle)
        else:
            self._release_lock_unix(file_handle)
    
    def save_state(self, wireless_ips):
        """Safely saves wireless IPs to the state file with validation."""
        # Validate input
        if not isinstance(wireless_ips, list):
            logger.error("Invalid wireless IPs format, expected list")
            return False
        
        # Validate each IP in the list
        valid_ips = []
        for ip in wireless_ips:
            if isinstance(ip, str) and ":" in ip:
                # Basic validation for IP:PORT format
                ip_part = ip.split(":")[0]
                parts = ip_part.split(".")
                if len(parts) == 4 and all(part.isdigit() and 0 <= int(part) <= 255 for part in parts):
                    valid_ips.append(ip)
                else:
                    logger.warning(f"Skipping invalid IP format: {ip}")
            else:
                logger.warning(f"Skipping invalid IP: {ip}")
        
        # Use atomic write pattern with temporary file
        temp_file = self.file_path.with_suffix('.tmp')
        try:
            with open(temp_file, 'w') as f:
                if not self._acquire_lock(f):
                    return False
                
                try:
                    json.dump({"wireless_ips": valid_ips}, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())  # Ensure data is written to disk
                finally:
                    self._release_lock(f)
            
            # Atomic replace
            if platform.system().lower() == 'windows':
                # Windows requires special handling for atomic replace
                if os.path.exists(self.file_path):
                    os.replace(temp_file, self.file_path)
                else:
                    os.rename(temp_file, self.file_path)
            else:
                # POSIX systems support atomic rename
                os.rename(temp_file, self.file_path)
            
            logger.info(f"Successfully saved {len(valid_ips)} wireless IPs to state file")
            return True
        except Exception as e:
            logger.error(f"Failed to save state file: {e}")
            if os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                except:
                    pass
            return False
    
    def load_state(self):
        """Safely loads wireless IPs from the state file with error recovery."""
        if not self.file_path.exists():
            logger.warning("State file doesn't exist, creating default")
            self._ensure_state_file_exists()
            return []
        
        try:
            with open(self.file_path, 'r') as f:
                if not self._acquire_lock(f):
                    return []
                
                try:
                    data = json.load(f)
                    
                    # Validate structure
                    if not isinstance(data, dict) or "wireless_ips" not in data:
                        logger.warning("Invalid state file format, using default")
                        return []
                    
                    # Validate content
                    wireless_ips = data.get("wireless_ips", [])
                    if not isinstance(wireless_ips, list):
                        logger.warning("Invalid wireless_ips format, using default")
                        return []
                    
                    logger.info(f"Loaded {len(wireless_ips)} wireless IPs from state file")
                    return wireless_ips
                except json.JSONDecodeError:
                    logger.error("Corrupted state file detected, restoring default")
                    # Backup corrupted file for debugging
                    backup_path = str(self.file_path) + ".corrupted"
                    try:
                        shutil.copy2(self.file_path, backup_path)
                        logger.info(f"Backed up corrupted state file to {backup_path}")
                    except Exception as e:
                        logger.error(f"Failed to back up corrupted state file: {e}")
                    # Restore default state
                    self._ensure_state_file_exists()
                    return []
                finally:
                    self._release_lock(f)
        except Exception as e:
            logger.error(f"Failed to load state file: {e}")
            return []

# Initialize state manager
state_manager = StateManager(DATA_FILE)

def get_adb_path():
    """Returns the path to the bundled ADB executable based on OS."""
    system = platform.system().lower()
    if system == 'windows':
        adb_path = BASE_DIR / 'assets' / 'adb' / 'platform-tools-windows' / 'adb.exe'
    elif system == 'linux':
        adb_path = BASE_DIR / 'assets' / 'adb' / 'platform-tools-linux' / 'adb'
    else:
        raise EnvironmentError(f"Unsupported operating system: {system}")
    
    # Make sure ADB is executable on Linux
    if system == 'linux' and adb_path.exists():
        os.chmod(str(adb_path), 0o755)
    
    return str(adb_path)

# Utility Functions
def clear_terminal():
    os.system('cls' if os.name == 'nt' else 'clear')

def run_command(command):
    try:
        # Replace direct "adb" calls with the full path to our bundled adb
        adb_path = get_adb_path()
        command = command.replace("adb ", f'"{adb_path}" ')
        
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

def save_last_wireless_ips(ips):
    """Save wireless IPs using the state manager."""
    return state_manager.save_state(ips)

def load_last_wireless_ips():
    """Load wireless IPs using the state manager."""
    return state_manager.load_state()

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
        self.setWindowTitle(f"FadADB v{APP_VERSION} - ADB manager for USB and wireless devices")
        self.setStyleSheet("background-color: #121212; color: white;")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        
        # Set a larger default size for the app
        self.resize(550, 650)  # Increased height
        
        # Create status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.setStyleSheet("background-color: #282828; color: white;")
        
        # Create custom progress indicator
        class CustomProgressIndicator(QFrame):
            def __init__(self, parent=None):
                super().__init__(parent)
                # Set fixed size
                self.setFixedSize(120, 16)
                # Style the frame
                self.setStyleSheet("""
                    QFrame {
                        background-color: #333;
                        border-radius: 8px;
                    }
                """)
                
                # Create the moving element
                self.dot = QFrame(self)
                self.dot.setFixedSize(20, 10)
                self.dot.setStyleSheet("""
                    QFrame {
                        background-color: #D53343;
                        border-radius: 5px;
                    }
                """)
                
                # Center the dot vertically
                self.dot.move(5, 3)  # Start a bit inside the container
                
                # Create animation
                self.animation = QPropertyAnimation(self.dot, b"pos")
                self.animation.setDuration(800)  # Slightly faster
                self.animation.setStartValue(QPoint(5, 3))  # Start position (left side with margin)
                self.animation.setEndValue(QPoint(95, 3))   # End position (right side with margin)
                
                # Use bounce easing curve for more natural bounce effect
                self.direction = 1  # 1 = right, -1 = left
                self.animation.finished.connect(self.bounce)
            
            def bounce(self):
                """Creates a continuous bouncing effect between left and right"""
                # Switch direction
                self.direction *= -1
                
                # Set new start and end positions based on direction
                if self.direction > 0:  # Moving right
                    self.animation.setStartValue(QPoint(5, 3))
                    self.animation.setEndValue(QPoint(95, 3))
                else:  # Moving left
                    self.animation.setStartValue(QPoint(95, 3))
                    self.animation.setEndValue(QPoint(5, 3))
                
                # Start the animation again
                self.animation.start()
            
            def showEvent(self, event):
                # Reset to starting position and direction
                self.direction = 1
                self.dot.move(5, 3)
                self.animation.setStartValue(QPoint(5, 3))
                self.animation.setEndValue(QPoint(95, 3))
                self.animation.start()
                super().showEvent(event)
                
            def hideEvent(self, event):
                self.animation.stop()
                super().hideEvent(event)
        
        # Create status label
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("padding: 4px; color: #aaa;")
        
        # Create our custom progress indicator
        self.progress_indicator = CustomProgressIndicator()
        self.progress_indicator.hide()
        
        # Add widgets to status bar
        self.status_bar.addWidget(self.status_label, 1)
        self.status_bar.addWidget(self.progress_indicator)
        
        # Initialize a timer for status messages
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._reset_status)
        
        # ----- Fix Start for dark title bar -----
        # Use explicit print statements for debugging in addition to logger
        print("Setting up dark title bar for FadADB...")
        
        system = platform.system().lower()
        if system == "windows":
            # For Windows, use a proven working method with multiple checks
            print("Windows system detected, applying dark title bar...")
            try:
                # For Windows 10/11
                import ctypes
                
                # Enable Dark Mode in the application process
                try:
                    # Try to force Windows app to use dark mode
                    ctypes.windll.UxTheme.SetPreferredAppMode(2)  # 2 = Force Dark Mode
                    print("Set preferred app mode to dark")
                except Exception as e:
                    print(f"UxTheme approach failed: {e}")
                
                # Get the app window handle and apply title bar color
                try:
                    hwnd = int(self.winId())
                    print(f"Window handle: {hwnd}")
                    
                    # Try multiple known methods for dark title bar
                    
                    # Method 1: Windows 11 22H2+ (newer builds)
                    try:
                        # Prefer Win11 dark title bar color directly
                        # DWMWA_CAPTION_COLOR = 35 (Windows 11 22H2)
                        DWMWA_CAPTION_COLOR = 35
                        # RGB for dark color (note: this is in BGR format - 0x00BBGGRR)
                        dark_color = ctypes.c_int(0x00303030)  # Dark gray
                        
                        # Use explicit debug
                        print(f"Trying caption color attribute {DWMWA_CAPTION_COLOR}")
                        
                        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                            hwnd,
                            DWMWA_CAPTION_COLOR, 
                            ctypes.byref(dark_color),
                            ctypes.sizeof(dark_color)
                        )
                        print(f"Caption color result: {result}")
                        if result == 0:  # S_OK = 0
                            print("Successfully applied dark title bar using caption color")
                            logger.info("Dark caption color applied successfully")
                    except Exception as e:
                        print(f"Caption color method failed: {e}")
                    
                    # Method 2: Windows 10/11 dark mode attribute
                    try:
                        # DWMWA_USE_IMMERSIVE_DARK_MODE
                        for attr_value in [20, 19]:  # Try both known values
                            try:
                                print(f"Trying dark mode attribute {attr_value}")
                                dark_mode_enabled = ctypes.c_int(1)  # 1 = Enable dark mode
                                result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                                    hwnd,
                                    attr_value,  # Attribute ID
                                    ctypes.byref(dark_mode_enabled),
                                    ctypes.sizeof(dark_mode_enabled)
                                )
                                print(f"Dark mode attribute {attr_value} result: {result}")
                                if result == 0:  # S_OK = 0
                                    print(f"Successfully applied dark mode attribute {attr_value}")
                                    logger.info(f"Dark title bar applied with attribute {attr_value}")
                                    break  # Exit the loop if successful
                            except Exception as e:
                                print(f"Attribute {attr_value} failed: {e}")
                    except Exception as e:
                        print(f"Dark mode attribute methods failed: {e}")
            
                except Exception as e:
                    print(f"Window handle operations failed: {e}")
            
            except Exception as e:
                print(f"Windows dark title bar application failed: {e}")
                logger.error(f"Failed to apply dark title bar: {e}")
                
        elif system == "linux":
            print("Linux system detected - no title bar styling applied")
            # No specific styling for Linux as it depends heavily on window manager
        # ----- Fix Ended for dark title bar -----

        # Set window icon
        if getattr(sys, 'frozen', False):
            # If running as exe, use PyInstaller's _MEIPASS if available
            base_path = getattr(sys, '_MEIPASS', Path(sys.executable).parent)
            icon_path = Path(base_path) / 'assets' / 'img' / 'FadADB-ico.ico'
            # print(f"[DEBUG] Icon path resolved to: {icon_path}")  # Debug line commented out
        else:
            icon_path = Path(__file__).parent / 'assets' / 'img' / 'FadADB-ico.ico'
        self.setWindowIcon(QIcon(str(icon_path)))

        # Create a scrollable central widget
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.central_layout = QVBoxLayout(self.central_widget)
        self.central_layout.setContentsMargins(0, 0, 0, 0)
        
        # Create tab widget
        self.tabs = QTabWidget()
        
        self.central_layout.addWidget(self.tabs)

        # Device Tab - Make scrollable
        self.device_tab_widget = QWidget()
        self.device_scroll = self._create_scroll_area()
        self.device_scroll.setWidget(self.device_tab_widget)
        self.device_layout = QVBoxLayout(self.device_tab_widget)
        
        self.label = QLabel("Available Devices:")
        self.combo = QComboBox()
        self.combo.setPlaceholderText("Select a device from the list below...")
        self.combo.setToolTip("📱 USB devices are automatically connected\n🔌 Wireless devices might need explicit connection")
        
        self.refresh_button = QPushButton("Refresh Devices")
        self.refresh_button.setToolTip("Scan for connected USB and wireless devices")
        
        self.connect_button = QPushButton("Connect")
        self.connect_button.setToolTip("Connect to the selected device (required for wireless devices)")
        
        self.test_button = QPushButton("Test Device")
        self.test_button.setToolTip("Test connection by retrieving device model information")
        
        # Manual add row
        manual_row = QHBoxLayout()
        self.manual_ip_input = QLineEdit()
        self.manual_ip_input.setPlaceholderText("e.g. 192.168.1.2 or 192.168.1.2:5555")
        self.add_manual_button = QPushButton("Add Device by IP")
        self.add_manual_button.setToolTip("Add a device by IP (port 5555 will be added automatically if omitted)")
        self.add_manual_button.clicked.connect(self.add_manual_device)
        manual_row.addWidget(self.manual_ip_input)
        manual_row.addWidget(self.add_manual_button)
        
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        # Enhanced styling for the log with better contrast and context menu styling
        self.log.setStyleSheet("""
            QTextEdit {
                background-color: #1A1A1A; 
                color: #66A0FF;  /* Blue default color */
                border: 1px solid #444;
                border-radius: 6px;
                padding: 5px;
                font-family: "Consolas", "Monaco", monospace;
                selection-background-color: #D53343;
            }
            QMenu {
                background-color: #1A1A1A;
                color: white;
                border: 1px solid #444;
            }
            QMenu::item:selected {
                background-color: #D53343;
                color: white;
            }
        """)
        
        # Make logs scrollable vertically only
        self.log.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.log.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        
        self.view_state_button = QPushButton("View Saved Wireless Devices")
        self.view_state_button.setToolTip("Show the list of remembered wireless devices that will be auto-reconnected")
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
        self.device_layout.addStretch(1)  # Add stretch to prevent widgets from expanding too much
        
        self.tabs.addTab(self.device_scroll, "Devices")

        # ADB Tab - Make scrollable
        self.adb_tab_widget = QWidget()
        self.adb_scroll = self._create_scroll_area()
        self.adb_scroll.setWidget(self.adb_tab_widget)
        self.adb_layout = QVBoxLayout(self.adb_tab_widget)
        
        self.toggle_server_button = QPushButton("Restart ADB Server")
        self.toggle_server_button.setToolTip("Restart the ADB server and attempt to reconnect wireless devices")
        self.adb_log = QTextEdit()
        self.adb_log.setReadOnly(True)
        # Enhanced styling for the ADB log with better contrast and context menu styling
        self.adb_log.setStyleSheet("""
            QTextEdit {
                background-color: #1A1A1A; 
                color: #66A0FF;  /* Blue default color */
                border: 1px solid #444;
                border-radius: 6px;
                padding: 5px;
                font-family: "Consolas", "Monaco", monospace;
                selection-background-color: #D53343;
            }
            QMenu {
                background-color: #1A1A1A;
                color: white;
                border: 1px solid #444;
            }
            QMenu::item:selected {
                background-color: #D53343;
                color: white;
            }
        """)
        
        # Make ADB logs scrollable vertically only
        self.adb_log.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.adb_log.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        
        self.toggle_server_button.clicked.connect(self.toggle_adb_server)
        adb_btn_layout = QHBoxLayout()
        adb_btn_layout.addWidget(self.toggle_server_button)
        self.adb_layout.addLayout(adb_btn_layout)
        self.adb_layout.addWidget(QLabel("\nADB Logs:"))
        self.adb_layout.addWidget(self.adb_log)
        self.adb_layout.addStretch(1)  # Add stretch
        
        self.tabs.addTab(self.adb_scroll, "ADB Tools")

        # About Tab - Make scrollable
        self.about_tab_widget = QWidget()
        self.about_scroll = self._create_scroll_area()
        self.about_scroll.setWidget(self.about_tab_widget)
        self.about_layout = QVBoxLayout(self.about_tab_widget)
        
        # Logo section directly in the main layout
        logo_layout = QHBoxLayout()
        logo_label = QLabel()
        
        # Get path to logo based on whether running as exe or script
        if getattr(sys, 'frozen', False):
            logo_path = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent)) / 'assets' / 'img' / 'fadsec-lab-logo.png'
        else:
            logo_path = Path(__file__).parent / 'assets' / 'img' / 'fadsec-lab-logo.png'
            
        # Load and display the logo if it exists
        if logo_path.exists():
            try:
                pixmap = QPixmap(str(logo_path))
                logo_label.setPixmap(pixmap.scaledToWidth(200, Qt.TransformationMode.SmoothTransformation))
                logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            except Exception as e:
                print(f"Error loading logo: {e}")
                logo_label.setText("FadSec Lab")
                logo_label.setStyleSheet("font-size: 24px; font-weight: bold;")
                logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            logo_label.setText("FadSec Lab")
            logo_label.setStyleSheet("font-size: 24px; font-weight: bold;")
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
        logo_layout.addStretch()
        logo_layout.addWidget(logo_label)
        logo_layout.addStretch()
        
        # Version label
        version_label = QLabel(f"Version {APP_VERSION}")
        version_label.setStyleSheet("color: #D53343; font-size: 16px; font-weight: bold; margin-bottom: 15px;")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Information section box (containing project info and about info)
        info_frame = QFrame()
        info_frame.setStyleSheet("""
            QFrame {
                background-color: #212121;
                border-radius: 10px;
                border: 1px solid #444;
                margin: 10px;
                padding: 15px;
            }
        """)
        info_frame_layout = QVBoxLayout(info_frame)
        
        # Project information
        info_text = QLabel()
        info_text.setTextFormat(Qt.TextFormat.RichText)
        info_text.setOpenExternalLinks(True)
        info_text.setWordWrap(True)
        info_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_text.setText("""
        <h2 style="color: #D53343;">Project by FadSec Lab</h2>
        <p>
            <a href="https://github.com/fadsec-lab">Check out more apps by FadSec Lab</a>
        </p>
        
        <h3 style="color: #D53343;">About FadADB</h3>
        <p>
            FadADB is a management tool for ADB (Android Debug Bridge) that simplifies 
            connecting to Android devices over both USB and wireless connections.
        </p>
        <p>
            It is designed for app developers, testers, and power users who need to 
            efficiently work with multiple Android devices, especially maintaining wireless 
            debugging connections.
        </p>
        """)
        
        # Add to layout
        info_frame_layout.addWidget(info_text)
        
        # Links section in a styled box
        links_frame = QFrame()
        links_frame.setStyleSheet("""
            QFrame {
                background-color: #212121;
                border-radius: 10px;
                border: 1px solid #444;
                margin: 10px;
                padding: 15px;
            }
        """)
        links_layout = QVBoxLayout(links_frame)
        
        # HTML title and description
        links_title = QLabel()
        links_title.setTextFormat(Qt.TextFormat.RichText)
        links_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        links_title.setText("<h3 style='color: #D53343;'>Links & Resources</h3>")
        
        # Button for source code link
        source_code_btn = QPushButton("🔍 View Source Code on GitHub")
        source_code_btn.setToolTip("Visit the project repository on GitHub")
        source_code_btn.setStyleSheet("""
            QPushButton {
                background-color: #2A2A2A;
                color: white;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3A3A3A;
            }
        """)
        source_code_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/anonfaded/FadADB")))
        
        # Button for checking updates
        check_updates_btn = QPushButton("🚀 Check for Updates")
        check_updates_btn.setToolTip("Check if a newer version is available on GitHub")
        check_updates_btn.setStyleSheet("""
            QPushButton {
                background-color: #2A2A2A;
                color: white;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3A3A3A;
            }
        """)
        check_updates_btn.clicked.connect(lambda: self.check_for_updates())
        
        # Add buttons to links layout
        links_layout.addWidget(links_title)
        links_layout.addWidget(source_code_btn)
        links_layout.addWidget(check_updates_btn)
        
        # License information in a styled box
        license_frame = QFrame()
        license_frame.setStyleSheet("""
            QFrame {
                background-color: #212121;
                border-radius: 10px;
                border: 1px solid #444;
                margin: 10px;
                padding: 15px;
            }
        """)
        license_layout = QVBoxLayout(license_frame)
        
        # License text
        license_text = QLabel()
        license_text.setTextFormat(Qt.TextFormat.RichText)
        license_text.setOpenExternalLinks(True)
        license_text.setWordWrap(True)
        license_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        license_text.setText("""
        <h3 style="color: #D53343;">License Information</h3>
        <p>
            This application uses Qt 6 licensed under LGPL v3.0.
            Users have the right to obtain the Qt source code and replace Qt libraries with modified versions.
        </p>
        <p>
            <a href="https://download.qt.io/archive/qt/">Get Qt Source Code</a>
        </p>
        """)
        
        # Add widgets to layout
        license_layout.addWidget(license_text)
        
        # Add everything to the main layout with spacing for better appearance
        self.about_layout.addLayout(logo_layout)
        self.about_layout.addWidget(version_label)
        self.about_layout.addSpacing(10)  # Add a small space between logo and info
        self.about_layout.addWidget(info_frame)
        self.about_layout.addWidget(links_frame)
        self.about_layout.addWidget(license_frame)
        self.about_layout.addStretch()  # Push everything to the top
        
        self.tabs.addTab(self.about_scroll, "About")

        # Show ADB path in logs on startup
        adb_path = get_adb_path()
        self.log_action(f"[INFO] Using bundled ADB: {adb_path}", adb=True)

        self.load_devices()
        
    def check_for_updates(self):
        """Check for updates using the updater module"""
        try:
            # Try to import the updater module
            updater_path = Path(__file__).parent / "updater.py"
            if updater_path.exists():
                # Set status
                self.show_loading_dialog("Checking for updates...")
                
                try:
                    # Dynamic import with error handling
                    spec = importlib.util.spec_from_file_location("updater", updater_path)
                    if spec is None:
                        raise ImportError(f"Could not load spec for updater module from {updater_path}")
                    
                    updater = importlib.util.module_from_spec(spec)
                    if spec.loader is None:
                        raise ImportError("Updater module loader is None")
                    
                    spec.loader.exec_module(updater)
                    
                    # Check if the updater has the required functionality
                    if not hasattr(updater, "is_update_available"):
                        self.log_action("[!] Updater module doesn't have required functions. Please reinstall.", adb=True)
                        self.hide_loading_dialog()
                        return
                        
                    # Run the updater in a separate thread
                    class UpdateCheckerWorker(QObject):
                        finished = pyqtSignal()
                        update_available = pyqtSignal(bool, str, str)
                        update_error = pyqtSignal(str)
                        
                        def run(self):
                            try:
                                is_available, latest_version, release_url = updater.is_update_available(APP_VERSION)
                                self.update_available.emit(is_available, latest_version, release_url)
                            except Exception as e:
                                logger.error(f"Error checking for updates: {e}")
                                self.update_error.emit(str(e))
                            finally:
                                self.finished.emit()
                    
                    # Set up worker thread
                    self.update_worker = UpdateCheckerWorker()
                    self.update_thread = QThread()
                    self.update_worker.moveToThread(self.update_thread)
                    
                    # Connect signals
                    self.update_thread.started.connect(self.update_worker.run)
                    self.update_worker.finished.connect(self.update_thread.quit)
                    self.update_worker.finished.connect(self.update_worker.deleteLater)
                    self.update_thread.finished.connect(self.update_thread.deleteLater)
                    self.update_thread.finished.connect(self.hide_loading_dialog)
                    
                    # Connect result handling signals - these will be called in the main thread
                    self.update_worker.update_available.connect(self._handle_update_check_result)
                    self.update_worker.update_error.connect(self._handle_update_check_error)
                    
                    # Start thread
                    self.update_thread.start()
                except ImportError as e:
                    logger.error(f"Error importing updater module: {e}")
                    self.log_action(f"[!] Update check failed: Missing required modules. {str(e)}", adb=True)
                    self.hide_loading_dialog()
                except Exception as e:
                    logger.error(f"Error in updater initialization: {e}")
                    self.log_action(f"[!] Update check failed: {str(e)}", adb=True)
                    self.hide_loading_dialog()
            else:
                self.log_action("[!] Update checker module not found. Please reinstall the application.", adb=True)
                self.hide_loading_dialog()
        except Exception as e:
            logger.error(f"Error in update process: {e}")
            self.log_action(f"[!] Update check failed: {str(e)}", adb=True)
            self.hide_loading_dialog()
            
    def _handle_update_check_result(self, is_available, latest_version, release_url):
        """Handle the update check result in the main thread"""
        try:
            # Check if we have a valid result
            if latest_version is None and not is_available:
                self.log_action("[!] Update check completed, but couldn't determine version.", adb=True)
                return
                
            # Try to import the updater module (should be safe since this is called after checking)
            try:
                spec = importlib.util.spec_from_file_location("updater", Path(__file__).parent / "updater.py")
                if spec is None:
                    raise ImportError("Could not load spec for updater module")
                    
                updater = importlib.util.module_from_spec(spec)
                if spec.loader is None:
                    raise ImportError("Updater module loader is None")
                    
                spec.loader.exec_module(updater)
                
                if is_available:
                    # Show update dialog from our thread
                    dialog = updater.UpdateDialog(APP_VERSION, latest_version, release_url, self)
                    dialog.exec()
                else:
                    # Show "no updates" message from our thread
                    msg = QMessageBox(self)
                    msg.setIcon(QMessageBox.Icon.Information)
                    msg.setWindowTitle("No Updates Available")
                    msg.setText(f"You are running the latest version ({APP_VERSION}).")
                    msg.setStandardButtons(QMessageBox.StandardButton.Ok)
                    msg.setStyleSheet("""
                        QMessageBox {
                            background-color: #1A1A1A;
                            color: white;
                        }
                        QLabel {
                            color: white;
                        }
                        QPushButton {
                            background-color: #2A2A2A;
                            color: white;
                            border: 1px solid #444;
                            border-radius: 4px;
                            padding: 6px 12px;
                        }
                        QPushButton:hover {
                            background-color: #3A3A3A;
                        }
                    """)
                    msg.show()
            except ImportError as e:
                logger.error(f"Error importing updater module for results: {e}")
                self.log_action(f"[!] Could not display update information: {str(e)}", adb=True)
                # Still try to show the basic result
                if is_available:
                    self.log_action(f"[!] Update available: Version {latest_version} - Visit: {release_url}", adb=True)
        except Exception as e:
            logger.error(f"Error handling update result: {e}")
            self.log_action(f"[!] Update check result handling failed: {str(e)}", adb=True)
    
    def _handle_update_check_error(self, error_msg):
        """Handle update check errors in the main thread"""
        # Show error message from our thread
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Update Check Failed")
        msg.setText(f"Could not check for updates:\n{error_msg}")
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.setStyleSheet("""
            QMessageBox {
                background-color: #1A1A1A;
                color: white;
            }
            QLabel {
                color: white;
            }
            QPushButton {
                background-color: #2A2A2A;
                color: white;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #3A3A3A;
            }
        """)
        msg.show()
        self.log_action(f"[!] Update check failed: {error_msg}", adb=True)

    def _create_scroll_area(self):
        """Creates a scroll area with proper styling and settings for tab content"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet("""
            QScrollArea { background-color: transparent; }
            QScrollBar:vertical {
                background: #2A2A2A;
                width: 12px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #555;
                min-height: 20px;
                border-radius: 6px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)
        return scroll

    def log_action(self, message, adb=False):
        """Logs a message with color syntax highlighting based on message content."""
        # Define colors for different types of messages
        color_success = "#4CAF50"  # Green
        color_error = "#FF5252"    # Red
        color_info = "#66A0FF"     # Blue (default)
        color_warning = "#FFC107"  # Amber
        color_command = "#BB86FC"  # Purple
        color_response = "#03DAC6" # Teal
        
        # Determine the color based on message content
        color = color_info  # Default blue
        
        # Apply color based on message content
        if "[+]" in message or "Connected" in message or "[✅]" in message or "Success" in message:
            color = color_success
        elif "[!]" in message or "failed" in message or "Error" in message or "error" in message or "[❌]" in message:
            color = color_error
        elif "[ℹ️]" in message or "Info" in message:
            color = color_info
        elif "[ADB" in message:
            color = color_command
        elif "STDOUT" in message:
            color = color_response
        elif "STDERR" in message:
            color = color_error
        elif "Warning" in message or "warning" in message:
            color = color_warning
            
        # Create HTML for the message
        formatted_message = f'<span style="color: {color};">{message}</span>'
        
        # Append to the appropriate log - using append method to ensure logs go at the bottom
        if adb:
            # Use append to add message at the end
            self.adb_log.append(formatted_message)
            # Auto-scroll to bottom
            scrollbar = self.adb_log.verticalScrollBar()
            if scrollbar:
                scrollbar.setValue(scrollbar.maximum())
        else:
            # Use append to add message at the end
            self.log.append(formatted_message)
            # Auto-scroll to bottom
            scrollbar = self.log.verticalScrollBar()
            if scrollbar:
                scrollbar.setValue(scrollbar.maximum())
            
    def show_loading_dialog(self, message="Processing..."):
        """Shows a non-blocking status indicator in the status bar."""
        # Update status message
        self.status_label.setText(message)
        self.progress_indicator.setVisible(True)
        # Cancel any existing timer
        self.status_timer.stop()
        # Force UI update
        QApplication.processEvents()

    def hide_loading_dialog(self):
        """Hides the loading indicator and shows a success message."""
        self.progress_indicator.setVisible(False)
        self.status_label.setText("Operation completed")
        # Start timer to clear the status after 5 seconds
        self.status_timer.start(5000)
        # Force UI update
        QApplication.processEvents()
    
    def _reset_status(self):
        """Resets the status message after a delay."""
        self.status_timer.stop()
        self.status_label.setText("Ready")
        QApplication.processEvents()

    def load_devices(self):
        """Loads devices asynchronously to prevent GUI freezing."""
        self.show_loading_dialog("Loading devices...")
        
        # Create a worker thread to load devices
        class DeviceLoaderWorker(QObject):
            finished = pyqtSignal()
            devices_loaded = pyqtSignal(list)
            
            def run(self):
                try:
                    devices = get_all_devices_with_wireless()
                    self.devices_loaded.emit(devices)
                except Exception as e:
                    logger.error(f"Error loading devices: {e}")
                    self.devices_loaded.emit([])
                finally:
                    self.finished.emit()
        
        # Set up the worker thread
        self.worker = DeviceLoaderWorker()
        self.loader_thread = QThread()
        self.worker.moveToThread(self.loader_thread)
        
        # Connect signals
        self.loader_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.loader_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.loader_thread.finished.connect(self.loader_thread.deleteLater)
        
        # Connect the result handler
        self.worker.devices_loaded.connect(self._on_devices_loaded)
        
        # Start the thread
        self.loader_thread.start()
    
    def _on_devices_loaded(self, devices):
        """Callback when devices are loaded."""
        self.hide_loading_dialog()
        self.combo.clear()
        
        if devices:
            self.combo.addItems([format_device_label(d) for d in devices])
            self.log_action("[+] Devices loaded.")
        else:
            self.log_action("[!] No connected devices found.")

    def gui_connect_device(self):
        """Connects to the selected device asynchronously."""
        label = self.combo.currentText()
        if not label:
            self.log_action("[!] No device selected.")
            return
            
        device = label.split(" ", 1)[-1]
        # Fix: Only use the actual device ID (strip label prefix)
        if label.startswith("📡 Wireless:") or label.startswith("🔌 USB:"):
            device = label.split(": ", 1)[-1]
            
        self.show_loading_dialog(f"Connecting to {device}...")
        
        # Create a worker thread for device connection
        class DeviceConnectWorker(QObject):
            finished = pyqtSignal()
            result = pyqtSignal(str, str)
            is_wireless = pyqtSignal(bool)
            
            def __init__(self, device_id):
                super().__init__()
                self.device_id = device_id
                
            def run(self):
                try:
                    if is_wireless(self.device_id):
                        self.is_wireless.emit(True)
                        stdout, stderr = run_command(f"adb connect {self.device_id}")
                    else:
                        self.is_wireless.emit(False)
                        stdout, stderr = "already connected", ""
                    self.result.emit(stdout, stderr)
                except Exception as e:
                    logger.error(f"Error connecting to device: {e}")
                    self.result.emit("", str(e))
                finally:
                    self.finished.emit()
        
        # Set up the worker thread
        self.connect_worker = DeviceConnectWorker(device)
        self.connect_thread = QThread()
        self.connect_worker.moveToThread(self.connect_thread)
        
        # Connect signals
        self.connect_thread.started.connect(self.connect_worker.run)
        self.connect_worker.finished.connect(self.connect_thread.quit)
        self.connect_worker.finished.connect(self.connect_worker.deleteLater)
        self.connect_thread.finished.connect(self.connect_thread.deleteLater)
        
        # Connect the result handler
        self.connect_worker.result.connect(lambda stdout, stderr: self._on_device_connected(device, stdout, stderr))
        self.connect_worker.is_wireless.connect(lambda is_wireless: 
            self.log_action(f"[ℹ️] {'Wireless' if is_wireless else 'Physical'} device detected") if is_wireless else None)
        
        # Start the thread
        self.connect_thread.start()
    
    def _on_device_connected(self, device, stdout, stderr):
        """Callback when device connection is complete."""
        self.hide_loading_dialog()
        
        if "connected" in stdout:
            self.log_action(f"[+] Connected to {device}.")
        elif "already connected" in stdout:
            self.log_action(f"[i] Already connected: {device}.")
        else:
            self.log_action(f"[!] Connection failed: {stdout or stderr}")

    def test_device(self):
        """Tests the selected device asynchronously."""
        label = self.combo.currentText()
        if not label:
            self.log_action("[!] No device selected.")
            return
            
        device = label.split(" ", 1)[-1]
        # Fix: Only use the actual device ID (strip label prefix)
        if label.startswith("📡 Wireless:") or label.startswith("🔌 USB:"):
            device = label.split(": ", 1)[-1]
        
        self.log_action(f"[Test] Running: adb -s {device} shell getprop ro.product.model")
        self.show_loading_dialog(f"Testing device {device}...")
        
        # Create a worker thread for device testing
        class DeviceTestWorker(QObject):
            finished = pyqtSignal()
            result = pyqtSignal(str, str)
            
            def __init__(self, device_id):
                super().__init__()
                self.device_id = device_id
                
            def run(self):
                try:
                    stdout, stderr = run_command(f"adb -s {self.device_id} shell getprop ro.product.model")
                    self.result.emit(stdout, stderr)
                except Exception as e:
                    logger.error(f"Error testing device: {e}")
                    self.result.emit("", str(e))
                finally:
                    self.finished.emit()
        
        # Set up the worker thread
        self.test_worker = DeviceTestWorker(device)
        self.test_thread = QThread()
        self.test_worker.moveToThread(self.test_thread)
        
        # Connect signals
        self.test_thread.started.connect(self.test_worker.run)
        self.test_worker.finished.connect(self.test_thread.quit)
        self.test_worker.finished.connect(self.test_worker.deleteLater)
        self.test_thread.finished.connect(self.test_thread.deleteLater)
        
        # Connect the result handler
        self.test_worker.result.connect(lambda stdout, stderr: self._on_device_tested(stdout, stderr))
        
        # Start the thread
        self.test_thread.start()
    
    def _on_device_tested(self, stdout, stderr):
        """Callback when device testing is complete."""
        self.hide_loading_dialog()
        
        if stdout:
            self.log_action(f"[ADB STDOUT] {stdout}")
        if stderr:
            self.log_action(f"[ADB STDERR] {stderr}")
        if not stdout and not stderr:
            self.log_action("[!] No response from device.")

    def toggle_adb_server(self):
        """Restarts ADB server asynchronously."""
        self.toggle_server_button.setEnabled(False)
        self.toggle_server_button.setText("Restarting...")
        self.log_action("[ADB] Killing server...", adb=True)
        self.show_loading_dialog("Restarting ADB server...")
        
        # Create a worker thread for server restart
        class ServerRestartWorker(QObject):
            finished = pyqtSignal()
            kill_result = pyqtSignal(str, str)
            start_result = pyqtSignal(str, str)
            reconnected = pyqtSignal(list)
            
            def run(self):
                try:
                    # Kill server
                    stdout_kill, stderr_kill = run_command("adb kill-server")
                    self.kill_result.emit(stdout_kill, stderr_kill)
                    
                    # Start server
                    stdout_start, stderr_start = run_command("adb start-server")
                    self.start_result.emit(stdout_start, stderr_start)
                    
                    # Try to reconnect devices
                    reconnected_devices = auto_reconnect_wireless()
                    self.reconnected.emit(reconnected_devices)
                except Exception as e:
                    logger.error(f"Error restarting ADB server: {e}")
                finally:
                    self.finished.emit()
        
        # Set up the worker thread
        self.server_worker = ServerRestartWorker()
        self.server_thread = QThread()
        self.server_worker.moveToThread(self.server_thread)
        
        # Connect signals
        self.server_thread.started.connect(self.server_worker.run)
        self.server_worker.finished.connect(self.server_thread.quit)
        self.server_worker.finished.connect(self.server_worker.deleteLater)
        self.server_thread.finished.connect(self.server_thread.deleteLater)
        
        # Connect the result handlers
        self.server_worker.kill_result.connect(
            lambda stdout, stderr: self.log_action(f"[ADB Kill-Server] {stdout or stderr}", adb=True)
        )
        self.server_worker.start_result.connect(
            lambda stdout, stderr: self.log_action(f"[ADB Start-Server] {stdout or stderr}", adb=True)
        )
        self.server_worker.reconnected.connect(self._on_server_restarted)
        
        # Start the thread
        self.server_thread.start()
    
    def _on_server_restarted(self, reconnected):
        """Callback when server restart is complete."""
        self.hide_loading_dialog()
        
        self.log_action("[ADB] Attempting to auto-reconnect wireless devices...", adb=True)
        if reconnected:
            self.log_action(f"[ADB] Reconnected: {', '.join(reconnected)}", adb=True)
        else:
            self.log_action("[ADB] No wireless devices reconnected.", adb=True)
        
        self.load_devices()
        self.log_action("[ADB] Device list refreshed.", adb=True)
        self.toggle_server_button.setText("Restart ADB Server")
        self.toggle_server_button.setEnabled(True)

    def add_manual_device(self):
        """Adds a device by IP asynchronously."""
        ip_input = self.manual_ip_input.text().strip()
        if not ip_input:
            self.log_action("[!] Please enter a device IP.")
            return
            
        # Check if the input contains a port
        if ":" not in ip_input:
            # No port specified, so add the default ADB port 5555
            ip = f"{ip_input}:5555"
            self.log_action(f"[ℹ️] Adding default port 5555 to the IP address: {ip}")
        else:
            ip = ip_input
            
        # Validate the IP part
        ip_part = ip.split(":")[0]
        parts = ip_part.split(".")
        if len(parts) != 4 or not all(part.isdigit() and 0 <= int(part) <= 255 for part in parts):
            self.log_action("[!] Invalid IP format. Use e.g. 192.168.1.2 or 192.168.1.2:5555")
            return
            
        # Try to connect
        self.log_action(f"[Manual Add] Connecting to {ip}...")
        self.show_loading_dialog(f"Connecting to {ip}...")
        
        # Create a worker thread for manual device connection
        class ManualConnectWorker(QObject):
            finished = pyqtSignal()
            result = pyqtSignal(str, str, str)
            
            def __init__(self, ip):
                super().__init__()
                self.ip = ip
                
            def run(self):
                try:
                    stdout, stderr = run_command(f"adb connect {self.ip}")
                    self.result.emit(self.ip, stdout, stderr)
                except Exception as e:
                    logger.error(f"Error connecting to manual device: {e}")
                    self.result.emit(self.ip, "", str(e))
                finally:
                    self.finished.emit()
        
        # Set up the worker thread
        self.manual_worker = ManualConnectWorker(ip)
        self.manual_thread = QThread()
        self.manual_worker.moveToThread(self.manual_thread)
        
        # Connect signals
        self.manual_thread.started.connect(self.manual_worker.run)
        self.manual_worker.finished.connect(self.manual_thread.quit)
        self.manual_worker.finished.connect(self.manual_worker.deleteLater)
        self.manual_thread.finished.connect(self.manual_thread.deleteLater)
        
        # Connect the result handler
        self.manual_worker.result.connect(self._on_manual_device_connected)
        
        # Start the thread
        self.manual_thread.start()
    
    def _on_manual_device_connected(self, ip, stdout, stderr):
        """Callback when manual device connection is complete."""
        self.hide_loading_dialog()
        
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
    print(Fore.GREEN + "\n[Manual Add] Enter the device IP (e.g. 192.168.1.2 or 192.168.1.2:5555):")
    ip_input = input(Fore.CYAN + "IP: ").strip()
    if not ip_input:
        print(Fore.RED + "[!] No IP entered.")
        return
        
    # Check if the input contains a port
    if ":" not in ip_input:
        # No port specified, so add the default ADB port 5555
        ip = f"{ip_input}:5555"
        print(Fore.YELLOW + f"[ℹ️] Adding default port 5555 to the IP address: {ip}")
    else:
        ip = ip_input
        
    # Validate the IP part
    ip_part = ip.split(":")[0]
    parts = ip_part.split(".")
    if len(parts) != 4 or not all(part.isdigit() and 0 <= int(part) <= 255 for part in parts):
        print(Fore.RED + "[!] Invalid IP format. Use e.g. 192.168.1.2 or 192.168.1.2:5555")
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
    # Verify the ADB binary exists
    try:
        adb_path = get_adb_path()
        if not Path(adb_path).exists():
            print(Fore.RED + f"[ERROR] Could not find ADB binary at: {adb_path}")
            print(Fore.RED + "Please ensure the ADB binaries are properly installed in the assets/adb directory.")
            sys.exit(1)
        print(Fore.GREEN + f"[INFO] Using bundled ADB: {adb_path}")
    except Exception as e:
        print(Fore.RED + f"[ERROR] {str(e)}")
        sys.exit(1)
        
    if len(sys.argv) > 1 and sys.argv[1] == "--gui":
        launch_gui()
    else:
        main_menu()
