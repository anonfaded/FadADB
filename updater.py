import re
import ssl
import certifi
import logging
import urllib.request
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QMessageBox
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import Qt, QUrl

# Configure logging
logger = logging.getLogger('FadADBUpdater')

def get_latest_version():
    """
    Fetch the latest version from GitHub releases page headers.
    Returns tuple (version_string, release_url)
    """
    repo_url = "https://github.com/anonfaded/FadADB"
    releases_url = f"{repo_url}/releases/latest"
    
    try:
        # Create a request with headers that make it appear like a browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        req = urllib.request.Request(releases_url, headers=headers)
        
        # Use a proper SSL context
        context = ssl.create_default_context(cafile=certifi.where())
        
        # Open the URL and get the final URL after redirects
        response = urllib.request.urlopen(req, context=context, timeout=5)
        final_url = response.geturl()
        
        # The URL usually ends with /tag/vX.Y.Z or similar
        version_match = re.search(r'/tag/v?(\d+\.\d+(?:\.\d+)?)', final_url)
        if version_match:
            version = version_match.group(1)
            return version, final_url
        
        # If we can't extract from URL, try to read the page and find version
        content = response.read().decode('utf-8')
        version_match = re.search(r'Release\s+v?(\d+\.\d+(?:\.\d+)?)', content)
        if version_match:
            return version_match.group(1), final_url
            
        logger.warning("Could not extract version number from GitHub release page")
        return None, releases_url
        
    except Exception as e:
        logger.error(f"Error checking for updates: {e}")
        return None, releases_url

def version_to_tuple(version_str):
    """Convert a version string to a tuple for comparison"""
    return tuple(map(int, version_str.split('.')))

def is_update_available(current_version):
    """
    Check if an update is available
    Returns tuple (is_available, latest_version, release_url)
    """
    latest_version, release_url = get_latest_version()
    
    if not latest_version:
        return False, None, release_url
        
    try:
        current_tuple = version_to_tuple(current_version)
        latest_tuple = version_to_tuple(latest_version)
        
        return latest_tuple > current_tuple, latest_version, release_url
    except Exception as e:
        logger.error(f"Error comparing versions: {e}")
        return False, latest_version, release_url

class UpdateDialog(QDialog):
    """Dialog to display update information"""
    
    def __init__(self, current_version, latest_version, release_url, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Update Available")
        self.setMinimumWidth(400)
        self.setStyleSheet("""
            QDialog {
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
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #3A3A3A;
            }
        """)
        
        layout = QVBoxLayout(self)
        
        # Title
        title_label = QLabel(f"🚀 Update Available!")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #66A0FF;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Update message
        message_label = QLabel(
            f"A new version of FadADB is available!\n\n"
            f"Current version: {current_version}\n"
            f"Latest version: {latest_version}\n\n"
            f"Would you like to download the update?"
        )
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_label.setWordWrap(True)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        download_button = QPushButton("Download Update")
        download_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(release_url)))
        download_button.setStyleSheet("background-color: #4CAF50;")
        
        skip_button = QPushButton("Skip This Version")
        skip_button.clicked.connect(self.accept)
        
        button_layout.addWidget(download_button)
        button_layout.addWidget(skip_button)
        
        # Add everything to main layout
        layout.addWidget(title_label)
        layout.addWidget(message_label)
        layout.addLayout(button_layout)

def check_for_updates(current_version, parent=None, silent=False):
    """
    Check for updates and show a dialog if an update is available
    Returns True if an update is available, False otherwise
    """
    try:
        update_available, latest_version, release_url = is_update_available(current_version)
        
        if update_available:
            dialog = UpdateDialog(current_version, latest_version, release_url, parent)
            dialog.exec()
            return True
        elif not silent:
            # Use non-modal message to avoid hanging
            msg = QMessageBox(parent)
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setWindowTitle("No Updates Available")
            msg.setText(f"You are running the latest version ({current_version}).")
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
            # Use show instead of exec to be non-blocking
            msg.show()
            return False
        return False
    except Exception as e:
        if not silent:
            # Use non-modal message to avoid hanging
            msg = QMessageBox(parent)
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setWindowTitle("Update Check Failed")
            msg.setText(f"Could not check for updates:\n{str(e)}")
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
            # Use show instead of exec to be non-blocking
            msg.show()
        logger.error(f"Update check failed: {e}")
        return False 