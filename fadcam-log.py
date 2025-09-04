import os
import subprocess
import platform
import time
import signal
import sys
try:
    from PyQt6 import QtWidgets, QtGui, QtCore
    from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QTextEdit, QComboBox, QMessageBox, QCheckBox
    QT_AVAILABLE = True
except Exception:
    QT_AVAILABLE = False
import threading
import re

# ANSI regexes used by GUI to detect and parse SGR/escape sequences
import os
import subprocess
import platform
import time
import signal
import sys
import re
try:
    from PyQt6 import QtWidgets, QtGui, QtCore
    from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QTextEdit, QComboBox, QMessageBox
    QT_AVAILABLE = True
except Exception:
    QT_AVAILABLE = False

# Constants
OS_TYPE = platform.system()
DEFAULT_PACKAGE = "com.fadcam"

# OS-specific paths (adjust as needed)
if OS_TYPE == "Windows":
    PIDCAT_PATH = r"D:\ubuntu-shared\Documents\Documents\repos\pidcat\pidcat.py"
else:
    PIDCAT_PATH = "/home/faded/Documents/Documents/repos/pidcat/pidcat.py"

# Precompiled regexes
SGR_RE = re.compile(r'\x1b\[(?P<code>[0-9;]*)m')
ESC_PRESENT = re.compile(r'\x1b\[')


def _child_run_pidcat():
    """Child mode: run pidcat with the same behavior and forward stdout."""
    pkg = None
    dev = None
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--package' and i + 1 < len(argv):
            pkg = argv[i + 1]; i += 2; continue
        if a == '--device' and i + 1 < len(argv):
            dev = argv[i + 1]; i += 2; continue
        i += 1
    env = os.environ.copy()
    if dev:
        env['ANDROID_SERIAL'] = dev
    package = pkg or DEFAULT_PACKAGE
    try:
        # pidcat expects package names as positional arguments. Passing '-c' made
        # pidcat treat the package string as an unexpected option on some versions.
        p = subprocess.Popen([sys.executable, PIDCAT_PATH, package], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
        for line in iter(p.stdout.readline, ''):
            if not line:
                break
            sys.stdout.write(line)
            sys.stdout.flush()
        try:
            p.stdout.close()
        except Exception:
            pass
        p.wait()
    except KeyboardInterrupt:
        try:
            if p and getattr(p, 'terminate', None):
                p.terminate()
        except Exception:
            pass
    sys.exit(0)


if '--child-pidcat' in sys.argv:
    _child_run_pidcat()


class LogcatAssistant:
    def __init__(self):
        self.default_package = DEFAULT_PACKAGE

    def get_adb_devices(self):
        try:
            res = subprocess.run(['adb', 'devices'], capture_output=True, text=True, check=False)
            lines = res.stdout.splitlines()[1:]
            devices = []
            for l in lines:
                l = l.strip()
                if not l:
                    continue
                parts = l.split()
                if parts:
                    devices.append(parts[0])
            return devices
        except FileNotFoundError:
            return []

    def run_logcat(self, package=None):
        devices = self.get_adb_devices()
        chosen = None
        if not devices:
            print('No adb devices found.')
            return
        if len(devices) == 1:
            chosen = devices[0]
        else:
            print('Multiple devices found:')
            for i, d in enumerate(devices, 1):
                print(f'  [{i}] {d}')
            while True:
                sel = input(f'Enter device number [1-{len(devices)}]: ').strip()
                if sel.isdigit() and 1 <= int(sel) <= len(devices):
                    chosen = devices[int(sel) - 1]
                    break

        env = os.environ.copy()
        if chosen:
            env['ANDROID_SERIAL'] = chosen

        package = package or self.default_package
        env['PYTHONUNBUFFERED'] = '1'
        # Prefer passing device explicitly to pidcat to avoid interactive prompts
        if chosen:
            cmd = [sys.executable, PIDCAT_PATH, '-s', chosen, package]
        else:
            cmd = [sys.executable, PIDCAT_PATH, package]
        try:
            subprocess.run(cmd, env=env)
        except KeyboardInterrupt:
            # If the user hits Ctrl+C while pidcat is prompting, exit cleanly.
            print('\nCtrl+C detected. Exiting.')
            return

    def run(self):
        while True:
            try:
                pkg = input('Enter package (or ENTER for default, "all" for full): ').strip()
                self.run_logcat(pkg if pkg else None)
                cont = input('Run another? (y/n): ').strip().lower()
                if cont != 'y':
                    break
            except KeyboardInterrupt:
                print('\nCtrl+C detected. Exiting.')
                break


class ProcessReader(QtCore.QThread):
    """Background thread that runs pidcat (or whatever cmd) and emits lines.
    On POSIX we attach the child to a pty so pidcat will emit ANSI escapes; on other
    systems we fall back to using pipes.
    """
    line_ready = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, cmd, env=None, input_text=None):
        super().__init__()
        self.cmd = cmd
        self.env = env or os.environ.copy()
        self.input_text = input_text
        self.process = None

    def run(self):
        env = dict(self.env)
        env.setdefault('PYTHONUNBUFFERED', '1')
        # Encourage color output
        env.setdefault('TERM', 'xterm-256color')
        env.setdefault('FORCE_COLOR', '1')
        # Ask pidcat to treat the terminal as very wide so it doesn't hard-wrap lines
        env.setdefault('COLUMNS', '2000')
        env.setdefault('LINES', '2000')

        # On POSIX, spawn the child attached to a pty so pidcat thinks it's a TTY
        if os.name == 'posix':
            try:
                import pty
                master, slave = pty.openpty()
                self.process = subprocess.Popen(self.cmd, stdin=slave, stdout=slave, stderr=slave, env=env)
                os.close(slave)
                buf = b''
                while True:
                    try:
                        chunk = os.read(master, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    buf += chunk
                    while b'\n' in buf:
                        line, buf = buf.split(b'\n', 1)
                        try:
                            decoded = line.decode('utf-8', errors='replace')
                        except Exception:
                            decoded = line.decode('latin-1', errors='replace')
                        self.line_ready.emit(decoded + '\n')
                if buf:
                    try:
                        decoded = buf.decode('utf-8', errors='replace')
                    except Exception:
                        decoded = buf.decode('latin-1', errors='replace')
                    self.line_ready.emit(decoded)
                try:
                    os.close(master)
                except Exception:
                    pass
                if self.process:
                    self.process.wait()
            finally:
                self.finished.emit()
            return

        # Fallback: use PIPE and text mode
        stdin_pipe = subprocess.PIPE if self.input_text else None
        try:
            self.process = subprocess.Popen(self.cmd, stdin=stdin_pipe, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env, bufsize=1)
            if self.input_text and self.process.stdin:
                try:
                    self.process.stdin.write(self.input_text + '\n')
                    self.process.stdin.flush()
                except Exception:
                    pass

            for line in iter(self.process.stdout.readline, ''):
                if not line:
                    break
                self.line_ready.emit(line)

            try:
                if self.process.stdout:
                    self.process.stdout.close()
            except Exception:
                pass
            self.process.wait()
        finally:
            self.finished.emit()


class LogcatGUI(QWidget):
    def __init__(self):
        super().__init__()
        if not QT_AVAILABLE:
            raise RuntimeError('PyQt6 required')
        self.setWindowTitle('Android Logcat Assistant - GUI')
        self.resize(1000, 700)
        self.setStyleSheet('background:#141414; color:#e6e6e6;')

        # widgets
        self.device_cb = QComboBox()
        self.refresh_btn = QPushButton('Refresh')
        self.package_edit = QLineEdit(DEFAULT_PACKAGE)
        self.status_label = QLabel('Ready')

        self.start_btn = QPushButton('Start Logcat')
        self.stop_btn = QPushButton('Stop Logcat')
        self.stop_btn.setEnabled(False)
        self.clear_btn = QPushButton('Clear Logs')
        self.copy_btn = QPushButton('Copy Logs')

        # search widgets
        self.search_edit = QLineEdit()
        self.search_btn = QPushButton('Search')
        self.case_checkbox = QCheckBox('Case-insensitive')
        self.case_checkbox.setChecked(False)
        self.prev_search_btn = QPushButton('Prev')
        self.next_search_btn = QPushButton('Next')
        self.search_count_label = QLabel('0/0')
        self.clear_search_btn = QPushButton('Clear Highlight')

        # allow Enter in the search box to trigger the search
        try:
            self.search_edit.returnPressed.connect(self.search_logs)
        except Exception:
            pass

        # compact button styling
        btns = (self.start_btn, self.stop_btn, self.clear_btn, self.copy_btn,
                self.search_btn, self.prev_search_btn, self.next_search_btn)
        for b in btns:
            try:
                b.setFixedHeight(28)
                b.setStyleSheet('font-size:12px; padding:4px 8px;')
                b.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            except Exception:
                pass

        # set icons from the current QApplication style where possible
        try:
            style = QApplication.style()
            if style:
                try:
                    self.start_btn.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MediaPlay))
                except Exception:
                    pass
                try:
                    self.stop_btn.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MediaStop))
                except Exception:
                    pass
                try:
                    self.clear_btn.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DialogResetButton))
                except Exception:
                    pass
                try:
                    self.copy_btn.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DialogSaveButton))
                except Exception:
                    pass
                try:
                    self.prev_search_btn.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ArrowBack))
                except Exception:
                    pass
                try:
                    self.next_search_btn.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ArrowForward))
                except Exception:
                    pass
        except Exception:
            pass

        # input and checkbox contrast adjustments
        try:
            self.search_edit.setStyleSheet('background:#181818; color:#e6e6e6; border:1px solid #333; padding:4px;')
            self.package_edit.setStyleSheet('background:#181818; color:#e6e6e6; border:1px solid #333; padding:4px;')
            self.device_cb.setStyleSheet('background:#181818; color:#e6e6e6; border:1px solid #333; padding:2px;')
            self.case_checkbox.setStyleSheet('color:#d0d4d8;')
        except Exception:
            pass

        # log display
        self.log_widget = QTextEdit()
        self.log_widget.setReadOnly(True)
        self.log_widget.setStyleSheet('background:#0f0f0f; color:#e6e6e6; font-family:monospace;')

        # layout
        header = QHBoxLayout()
        header.addWidget(QLabel('Device:'))
        header.addWidget(self.device_cb)
        header.addWidget(self.refresh_btn)
        header.addWidget(QLabel('Package:'))
        header.addWidget(self.package_edit)
        header.addWidget(self.status_label)

        controls = QHBoxLayout()
        controls.addWidget(self.start_btn)
        controls.addWidget(self.stop_btn)
        controls.addWidget(self.clear_btn)
        controls.addWidget(self.copy_btn)

        search = QHBoxLayout()
        search.addWidget(QLabel('Search:'))
        search.addWidget(self.search_edit)
        search.addWidget(self.case_checkbox)
        search.addWidget(self.search_btn)
        search.addWidget(self.prev_search_btn)
        search.addWidget(self.next_search_btn)
        search.addWidget(self.search_count_label)
        search.addWidget(self.clear_search_btn)

        # small shortcuts hint and wrap toggle
        self.shortcuts_label = QLabel('Shortcuts: Start Ctrl+R • Stop Ctrl+S • Find Ctrl+F • Next F3 • Prev Shift+F3')
        self.shortcuts_label.setStyleSheet('font-size:11px; color:#9aa0a6;')
        self.wrap_checkbox = QCheckBox('Wrap lines')
        self.wrap_checkbox.setChecked(True)
        try:
            self.wrap_checkbox.setStyleSheet('color:#d0d4d8;')
        except Exception:
            pass

        main = QVBoxLayout()
        main.addLayout(header)
        main.addLayout(controls)
        main.addLayout(search)
        # add shortcuts hint
        hints = QHBoxLayout()
        hints.addWidget(self.shortcuts_label)
        hints.addWidget(self.wrap_checkbox)
        hints.addStretch()
        main.addLayout(hints)
        main.addWidget(self.log_widget)
        self.setLayout(main)

        # signals
        self.refresh_btn.clicked.connect(self.refresh_devices)
        self.start_btn.clicked.connect(self.start_logcat)
        self.stop_btn.clicked.connect(self.stop_logcat)
        self.clear_btn.clicked.connect(self.clear_logs)
        self.copy_btn.clicked.connect(self.copy_logs)
        self.search_btn.clicked.connect(self.search_logs)
        self.prev_search_btn.clicked.connect(self.navigate_prev)
        self.next_search_btn.clicked.connect(self.navigate_next)
        self.clear_search_btn.clicked.connect(self.clear_search)

        # keyboard shortcuts
        try:
            QtGui.QShortcut(QtGui.QKeySequence('Ctrl+R'), self).activated.connect(self.start_logcat)
            QtGui.QShortcut(QtGui.QKeySequence('Ctrl+S'), self).activated.connect(self.stop_logcat)
            QtGui.QShortcut(QtGui.QKeySequence('F3'), self).activated.connect(self.navigate_next)
            QtGui.QShortcut(QtGui.QKeySequence('Shift+F3'), self).activated.connect(self.navigate_prev)
            QtGui.QShortcut(QtGui.QKeySequence('Ctrl+F'), self).activated.connect(lambda: self.search_edit.setFocus())
            # additional shortcuts: clear and copy
            QtGui.QShortcut(QtGui.QKeySequence('Ctrl+L'), self).activated.connect(self.clear_logs)
            QtGui.QShortcut(QtGui.QKeySequence('Ctrl+Shift+C'), self).activated.connect(self.copy_logs)
        except Exception:
            pass

        # wire wrap toggle and default wrap behavior
        try:
            self.wrap_checkbox.toggled.connect(self.toggle_wrap)
            self.log_widget.setLineWrapMode(QtWidgets.QTextEdit.LineWrapMode.WidgetWidth)
            self.log_widget.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        except Exception:
            pass

        # state
        self.reader = None
        self.devices = []
        self._last_received = None
        # search state
        self.search_matches = []  # list of (start, length)
        self.current_search_index = -1
        # color the start/stop buttons for clarity (placed here after styles are defined)
        self.start_btn.setStyleSheet('background:#2ecc71; color:#012a0f; font-weight:bold;')
        self.stop_btn.setStyleSheet('background:#e74c3c; color:#2b0000; font-weight:bold;')

        self.refresh_devices()
        try:
            self.install_sigint_handler()
        except Exception:
            pass

    def toggle_wrap(self, checked: bool):
        try:
            if checked:
                self.log_widget.setLineWrapMode(QtWidgets.QTextEdit.LineWrapMode.WidgetWidth)
                self.log_widget.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            else:
                self.log_widget.setLineWrapMode(QtWidgets.QTextEdit.LineWrapMode.NoWrap)
                self.log_widget.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        except Exception:
            pass

    def append_html(self, html: str):
        cursor = self.log_widget.textCursor()
        try:
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
            self.log_widget.setTextCursor(cursor)
        except Exception:
            pass
        self.log_widget.insertHtml(html)
        try:
            cursor = self.log_widget.textCursor()
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
            self.log_widget.setTextCursor(cursor)
        except Exception:
            pass

    def insert_colored_line(self, line: str):
        """Insert a line into the QTextEdit using QTextCharFormat per ANSI segment.
        This preserves exact spacing and lets us use Qt colors (better contrast).
        """
        # high-contrast palette (match color_line)
        FG = {
            30: '#6b6f75', 31: '#ff5555', 32: '#50fa7b', 33: '#f1fa8c',
            34: '#6272a4', 35: '#ff79c6', 36: '#8be9fd', 37: '#e6e6e6',
            90: '#5a5f66', 91: '#ff6e6e', 92: '#69ff94', 93: '#ffffa5',
            94: '#caa9ff', 95: '#ff92df', 96: '#a4ffff', 97: '#ffffff'
        }

        # Determine a single line color (prefer the first color code seen)
        overall_color = None
        overall_bold = False
        for m in SGR_RE.finditer(line):
            codes = m.group('code') or '0'
            for c in codes.split(';'):
                try:
                    ci = int(c)
                except Exception:
                    continue
                if ci == 0:
                    # reset - stop considering prior colors
                    if overall_color is None:
                        overall_bold = False
                elif ci == 1:
                    overall_bold = True
                elif 30 <= ci <= 37 or 90 <= ci <= 97:
                    if overall_color is None:
                        overall_color = FG.get(ci)

        # Strip ANSI sequences to get clean text while preserving spacing/newlines
        try:
            clean = SGR_RE.sub('', line)
        except Exception:
            clean = line

        cursor = self.log_widget.textCursor()
        try:
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
            self.log_widget.setTextCursor(cursor)
        except Exception:
            pass

        fmt = QtGui.QTextCharFormat()
        fmt.setFontFamily('monospace')
        if overall_color:
            try:
                fmt.setForeground(QtGui.QBrush(QtGui.QColor(overall_color)))
            except Exception:
                pass
        if overall_bold:
            try:
                fmt.setFontWeight(QtGui.QFont.Weight.Bold)
            except Exception:
                pass

        # insert the full cleaned line as a single formatted chunk
        # preserve trailing newline behavior similar to append
        text_to_insert = clean
        # remove a single trailing newline to avoid double-spacing when using append elsewhere
        if text_to_insert.endswith('\n'):
            text_to_insert = text_to_insert.rstrip('\n') + '\n'
        cursor.insertText(text_to_insert, fmt)
        try:
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
            self.log_widget.setTextCursor(cursor)
        except Exception:
            pass

    def refresh_devices(self):
        devices = []
        try:
            res = subprocess.run(['adb', 'devices'], capture_output=True, text=True, check=False)
            lines = res.stdout.splitlines()[1:]
            for l in lines:
                l = l.strip()
                if not l:
                    continue
                parts = l.split()
                if parts:
                    devices.append(parts[0])
        except FileNotFoundError:
            pass
        self.devices = devices
        self.device_cb.clear()
        if devices:
            self.device_cb.addItems(devices)
            self.start_btn.setEnabled(True)
            self.status_label.setText(f'{len(devices)} device(s)')
        else:
            self.start_btn.setEnabled(False)
            self.status_label.setText('No adb devices')

    def color_line(self, line: str) -> str:
        # Legacy HTML converter kept for compatibility; prefer insert_colored_line for exact spacing.
        FG = {
            # avoid pure black for readability on dark theme
            30: '#6b6f75', 31: '#ff5555', 32: '#50fa7b', 33: '#f1fa8c',
            34: '#6272a4', 35: '#ff79c6', 36: '#8be9fd', 37: '#e6e6e6',
            90: '#5a5f66', 91: '#ff6e6e', 92: '#69ff94', 93: '#ffffa5',
            94: '#caa9ff', 95: '#ff92df', 96: '#a4ffff', 97: '#ffffff'
        }

        # Find the first color/bold SGR and apply it to the whole line
        overall_color = None
        overall_bold = False
        for m in SGR_RE.finditer(line):
            codes = m.group('code') or '0'
            for c in codes.split(';'):
                try:
                    ci = int(c)
                except Exception:
                    continue
                if ci == 0:
                    if overall_color is None:
                        overall_bold = False
                elif ci == 1:
                    overall_bold = True
                elif 30 <= ci <= 37 or 90 <= ci <= 97:
                    if overall_color is None:
                        overall_color = FG.get(ci)

        try:
            clean = SGR_RE.sub('', line)
        except Exception:
            clean = line

        esc = clean.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        style = []
        if overall_color:
            style.append(f'color:{overall_color}')
        if overall_bold:
            style.append('font-weight:bold')
        if style:
            return f"<pre style='white-space:pre; margin:0; font-family:monospace; color:#e6e6e6;'><span style=\"{';'.join(style)}\">{esc}</span></pre>"
        return f"<pre style='white-space:pre; margin:0; font-family:monospace; color:#e6e6e6;'>{esc}</pre>"

    def install_sigint_handler(self):
        def _sigint(signum, frame):
            try:
                QtCore.QTimer.singleShot(0, self._on_sigint_requested)
            except Exception:
                pass
        signal.signal(signal.SIGINT, _sigint)

    def _on_sigint_requested(self):
        ans = QMessageBox.question(self, 'Terminate', 'Ctrl+C detected in terminal. Quit the GUI?', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ans == QMessageBox.StandardButton.Yes:
            try:
                if self.reader and getattr(self.reader, 'process', None):
                    proc = self.reader.process
                    if proc and getattr(proc, 'terminate', None):
                        proc.terminate()
            except Exception:
                pass
            QApplication.quit()

    def start_logcat(self):
        package = self.package_edit.text().strip() or DEFAULT_PACKAGE
        device = self.device_cb.currentText().strip()
        env = os.environ.copy()
        input_text = None
        if device and self.devices and len(self.devices) > 1:
            try:
                idx = self.devices.index(device) + 1
                input_text = str(idx)
            except ValueError:
                input_text = None
        if device:
            env['ANDROID_SERIAL'] = device

        self.status_label.setText(f'Running on {device}')
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        # prefer passing device explicitly to pidcat to avoid interactive prompts
        # Use the short -s DEVICE flag (pidcat uses -s for device serial) and
        # pass the package name as a positional argument.
        if device:
            cmd = [sys.executable, PIDCAT_PATH, '-s', device, package]
        else:
            cmd = [sys.executable, PIDCAT_PATH, package]
        env['PYTHONUNBUFFERED'] = '1'

        self.reader = ProcessReader(cmd, env, input_text=input_text)
        self.reader.line_ready.connect(self.handle_line)
        self.reader.finished.connect(self.on_reader_finished)
        self.reader.start()

    def on_reader_finished(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText('Stopped')

    def handle_line(self, ln: str):
        # If the line contains ANSI escapes, insert colored segments using QTextCursor for exact fidelity;
        # otherwise append plain text (this matches the old raw checkbox behavior).
        if ESC_PRESENT.search(ln):
            try:
                self.insert_colored_line(ln)
            except Exception:
                # fallback to HTML append if anything goes wrong
                self.append_html(self.color_line(ln))
        else:
            self.log_widget.append(ln.rstrip('\n'))
        self._last_received = time.time()

    def stop_logcat(self):
        if self.reader and getattr(self.reader, 'process', None):
            proc = self.reader.process
            try:
                if proc and getattr(proc, 'terminate', None):
                    proc.terminate()
            except Exception:
                pass
        self.status_label.setText('Stopped')

    def clear_logs(self):
        self.log_widget.clear()

    def copy_logs(self):
        clip = QApplication.clipboard() if QApplication.instance() else None
        if clip:
            clip.setText(self.log_widget.toPlainText())
            QMessageBox.information(self, 'Copied', 'Logs copied to clipboard!')
        else:
            QMessageBox.information(self, 'Copied', 'Could not access clipboard.')

    def search_logs(self):
        query = self.search_edit.text()
        if not query:
            return
        # build matches from plain text to avoid HTML issues
        doc_text = self.log_widget.toPlainText()
        self.search_matches = []
        qlen = len(query)
        pos = 0
        if self.case_checkbox.isChecked():
            hay = doc_text.lower()
            needle = query.lower()
        else:
            hay = doc_text
            needle = query
        while True:
            idx = hay.find(needle, pos)
            if idx == -1:
                break
            self.search_matches.append((idx, qlen))
            pos = idx + max(1, qlen)

        self.current_search_index = 0 if self.search_matches else -1
        self.update_search_selection()

    def clear_search(self):
        self.search_matches = []
        self.current_search_index = -1
        self.search_count_label.setText('0/0')
        self.log_widget.setExtraSelections([])

    def navigate_next(self):
        if not self.search_matches:
            return
        self.current_search_index = (self.current_search_index + 1) % len(self.search_matches)
        self.update_search_selection()

    def navigate_prev(self):
        if not self.search_matches:
            return
        self.current_search_index = (self.current_search_index - 1) % len(self.search_matches)
        self.update_search_selection()

    def update_search_selection(self):
        # create ExtraSelections for all matches and a focused one for the current index
        extras = []
        doc = self.log_widget.document()
        for i, (start, length) in enumerate(self.search_matches):
            sel = QtWidgets.QTextEdit.ExtraSelection()
            cursor = self.log_widget.textCursor()
            cursor.setPosition(start)
            cursor.setPosition(start + length, QtGui.QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = cursor
            fmt = QtGui.QTextCharFormat()
            if i == self.current_search_index:
                fmt.setBackground(QtGui.QBrush(QtGui.QColor('#ffd54f')))  # active highlight
                fmt.setForeground(QtGui.QBrush(QtGui.QColor('#000000')))
            else:
                fmt.setBackground(QtGui.QBrush(QtGui.QColor('#6e6e6e')))
            sel.format = fmt
            extras.append(sel)

        self.log_widget.setExtraSelections(extras)
        if self.current_search_index != -1 and self.search_matches:
            s, l = self.search_matches[self.current_search_index]
            cursor = self.log_widget.textCursor()
            cursor.setPosition(s)
            cursor.setPosition(s + l, QtGui.QTextCursor.MoveMode.KeepAnchor)
            self.log_widget.setTextCursor(cursor)
        # update label
        total = len(self.search_matches)
        cur = (self.current_search_index + 1) if self.current_search_index != -1 else 0
        self.search_count_label.setText(f'{cur}/{total}')


def choose_mode():
    print('Choose mode:')
    print('1. CLI')
    print('2. GUI (PyQt6)')
    choice = input('Enter 1 or 2: ').strip()
    if choice == '1':
        assistant = LogcatAssistant()
        assistant.run()
    elif choice == '2':
        if not QT_AVAILABLE:
            print('PyQt6 not available. Install PyQt6 or run in CLI mode.')
            return
        app = QApplication(sys.argv)
        win = LogcatGUI()
        win.show()
        try:
            app.exec()
        except KeyboardInterrupt:
            pass
    else:
        print('Invalid choice')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'gui':
        if not QT_AVAILABLE:
            print('PyQt6 not available. Install PyQt6 or run without args for CLI.')
            sys.exit(1)
        app = QApplication(sys.argv)
        win = LogcatGUI()
        win.show()
        try:
            app.exec()
        except KeyboardInterrupt:
            pass
    else:
        choose_mode()
