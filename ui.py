# SPDX-License-Identifier: MIT

"""Integrated UI for the Bep-Project.

- Top left: live microscope camera feed (CameraThread, external USB camera).
- Top right: jog control for the 3 stepper motors via the Arduino Nano.
- Bottom: Moku:Go live photodetector plot (MokuThread, embedded).

The laptop's built-in webcam is intentionally never opened: the camera thread
only streams once an external microscope camera is connected.

Dependencies:
    pip install PySide6 pyserial opencv-python matplotlib moku
"""
from __future__ import annotations

import sys
import threading
import time

import cv2
import numpy as np
import serial
import serial.tools.list_ports

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QFontDatabase, QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

import calibration as cal
from calibration_graph import CalibrationGraphPanel
from camera_settings import CameraSettingsPanel
from lamp import LampPanel
from recording import RecordingPanel


# The microscope camera is matched by NAME, not by index, because the OpenCV /
# DirectShow index depends on USB enumeration order (which varies per machine and
# plug order). On this setup the microscope is "Innomaker-U20CAM-1080p-S1" and
# the laptop built-in is "HP HD Camera", but the indices can swap.
# INCLUDE patterns positively identify the microscope; EXCLUDE patterns are
# cameras we must never open (laptop built-in, virtual cameras). Matching is
# case-insensitive substring.
MICROSCOPE_NAME_INCLUDE = ("innomaker", "u20cam", "usb cam", "usb video", "microscope")
CAMERA_NAME_EXCLUDE = ("hp hd camera", "hp truevision", "integrated", "obs", "virtual")
# Last-resort indices to probe only when device names cannot be read (pygrabber
# missing). Name-based detection is strongly preferred.
MICROSCOPE_CAMERA_INDICES = (0, 1, 2, 3)

DEFAULT_PORT = "COM4"
BAUD = 9600
MAX_STEPS = 4096
DEFAULT_SPEED = 500   # AccelStepper setMaxSpeed (steps/s)
MAX_SPEED = 2000
AXIS_NAMES = ("X", "Y", "Z")   # motor 1 = X axis, motor 2 = Y axis, motor 3 = Z axis
# Jog direction per axis: +1 = up arrow increases step count, -1 = up arrow lowers it.
# Z is inverted so the up arrow physically moves up instead of down.
AXIS_JOG_DIR = (1, 1, -1)
# Hard software limit per axis: max |logical position| in micron. A jog that
# would go beyond this is blocked (see MotorPanel._jog).
AXIS_LIMIT_UM = (500.0, 500.0, 500.0)


# -------------------- Camera --------------------

class CameraThread(QThread):
    """Streams the external microscope camera.

    The microscope camera is identified by device name (see MICROSCOPE_NAME_INCLUDE
    / CAMERA_NAME_EXCLUDE), so the laptop's built-in webcam and virtual cameras are
    never opened regardless of their index. The thread keeps scanning until a
    microscope camera is connected and only then starts streaming; if it is
    unplugged the thread drops back to scanning.
    """

    frame_ready = Signal(np.ndarray)
    camera_connected = Signal(int, str)   # (index, device name) when streaming starts
    camera_lost = Signal()                # emitted when the camera disconnects

    def __init__(self, indices: tuple[int, ...] = MICROSCOPE_CAMERA_INDICES) -> None:
        super().__init__()
        self._indices = tuple(indices)
        self._running = False
        # Thread-safe queue for OpenCV property changes (UI -> run loop)
        self._pending_props: dict[int, float] = {}
        self._props_lock = threading.Lock()
        # Grayscale toggle. bool reads/writes are atomic under the GIL.
        self._grayscale = False

    def run(self) -> None:
        self._running = True
        while self._running:
            cap, index, name = self._open_microscope_camera()
            if cap is None:
                # No microscope camera yet. Wait and rescan; laptop cam stays off.
                self._sleep(1.5)
                continue
            self.camera_connected.emit(index, name)
            self._stream(cap)
            cap.release()
            if self._running:
                self.camera_lost.emit()

    @staticmethod
    def _enumerate_cameras() -> list[str] | None:
        """Return DirectShow camera names (same order as OpenCV indices), or None.

        None means the names could not be read (pygrabber missing), so the caller
        falls back to a plain index probe.
        """
        try:
            from pygrabber.dshow_graph import FilterGraph
            return list(FilterGraph().get_input_devices())
        except Exception:
            return None

    @staticmethod
    def _pick_microscope(names: list[str]) -> int:
        """Pick the microscope camera index from device names; -1 if none suitable."""
        # 1) a device positively identified as the microscope wins
        for i, name in enumerate(names):
            low = name.lower()
            if any(p in low for p in MICROSCOPE_NAME_INCLUDE):
                return i
        # 2) otherwise the first camera that is not the laptop built-in or virtual
        for i, name in enumerate(names):
            low = name.lower()
            if not any(p in low for p in CAMERA_NAME_EXCLUDE):
                return i
        return -1

    def _open_microscope_camera(self):
        """Find and open the microscope camera. Returns (cap, index, name)."""
        names = self._enumerate_cameras()
        if names is not None:
            idx = self._pick_microscope(names)
            candidates = [] if idx < 0 else [idx]

            def name_of(i: int) -> str:
                return names[i] if 0 <= i < len(names) else f"USB{i}"
        else:
            # Names unavailable: last-resort index probe (cannot tell cameras apart).
            candidates = list(self._indices)

            def name_of(i: int) -> str:
                return f"USB{i}"

        for index in candidates:
            if not self._running:
                return None, -1, ""
            cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap.release()
                continue
            # Validate with a few read attempts: some cameras need a warm-up frame.
            ok = False
            for _ in range(5):
                ok, _frame = cap.read()
                if ok:
                    break
                time.sleep(0.05)
            if not ok:
                cap.release()
                continue
            self._configure(cap, index, name_of(index))
            return cap, index, name_of(index)
        return None, -1, ""

    def _configure(self, cap, index: int, name: str = "") -> None:
        """Tune the camera for maximum image quality."""
        # FOURCC before resolution: DirectShow refuses high resolutions on YUY2
        # (raw) over USB 2.0; with MJPG (compressed) 1080p@30 almost always works.
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        # Try 1080p first, fall back to 720p, otherwise keep what the cam gives.
        for target_w, target_h in ((1920, 1080), (1280, 720)):
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, target_w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, target_h)
            if (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) == target_w
                    and int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) == target_h):
                break
        cap.set(cv2.CAP_PROP_FPS, 30)
        # BUFFERSIZE=1: newest frame, no backlog, so sliders feel instant.
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        # Auto focus/WB on by default; manual override lives in the Camera tab.
        cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
        cap.set(cv2.CAP_PROP_AUTO_WB, 1)
        # Force colour on every start: DirectShow persists camera properties in the
        # driver between sessions. An earlier version set grayscale via SATURATION=0;
        # that 0 stays stuck so the image keeps coming up black and white. Here we
        # reset it to a neutral colour value (128, matching neutral brightness/
        # contrast). The grayscale option now runs entirely through _grayscale.
        cap.set(cv2.CAP_PROP_SATURATION, 128)

        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        label = name or f"index {index}"
        print(f"Microscope camera opened: {label} (index {index}) "
              f"{w}x{h} @ {fps:.0f}fps (MJPG)")

    def _stream(self, cap) -> None:
        """Read frames until stopped or the camera disconnects."""
        consecutive_failures = 0
        while self._running:
            # Drain pending property changes and apply them before the next frame.
            with self._props_lock:
                pending = self._pending_props
                self._pending_props = {}
            for prop_id, value in pending.items():
                cap.set(prop_id, value)

            ok, frame = cap.read()
            if not ok:
                consecutive_failures += 1
                if consecutive_failures > 30:   # camera likely unplugged
                    return
                time.sleep(0.02)
                continue
            consecutive_failures = 0
            if self._grayscale:
                # GRAY->BGR back so downstream (cvtColor BGR2RGB) keeps working.
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                frame = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            self.frame_ready.emit(frame)

    def _sleep(self, seconds: float) -> None:
        """Sleep in small steps so stop() stays responsive."""
        end = time.monotonic() + seconds
        while self._running and time.monotonic() < end:
            time.sleep(0.05)

    def stop(self) -> None:
        self._running = False
        self.wait()

    def set_property(self, prop_id: int, value: float) -> None:
        """Thread-safe: queue an OpenCV cap.set() for the next frame."""
        with self._props_lock:
            self._pending_props[prop_id] = value

    def set_grayscale(self, on: bool) -> None:
        self._grayscale = bool(on)


class CameraPanel(QLabel):
    def __init__(self) -> None:
        super().__init__()
        # Keep this small so the whole window can still shrink to fit a laptop
        # screen; the feed scales up to fill whatever space the splitter gives it.
        self.setMinimumSize(320, 240)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background-color: black; color: white;")
        self.setText("Waiting for microscope camera...")

    def update_frame(self, frame: np.ndarray) -> None:
        rgb = np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        h, w, ch = rgb.shape
        bytes_per_line = ch * w
        qimg = QImage(rgb.tobytes(), w, h, bytes_per_line, QImage.Format_RGB888)
        pix = QPixmap.fromImage(qimg)
        # Only downscale: upscaling blurs, better native + black border.
        panel = self.size()
        if w > panel.width() or h > panel.height():
            pix = pix.scaled(panel, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.setPixmap(pix)

    def show_waiting(self) -> None:
        """Clear the feed and show the waiting message (camera disconnected)."""
        self.clear()
        self.setText("Waiting for microscope camera...")


# -------------------- Motors --------------------

class MotorPanel(QGroupBox):
    def __init__(self, default_port: str = DEFAULT_PORT) -> None:
        super().__init__("Stepper motors (Arduino Nano)")
        self.serial: serial.Serial | None = None
        self.default_port = default_port
        self.targets: list[int] = [0, 0, 0]
        # Logical commanded position in micron. Tracked separately from the
        # integer step count so the display shows the exact value you asked for
        # (e.g. 10.00 um) instead of the step-quantised value (e.g. 9.99 um).
        self.target_um: list[float] = [0.0, 0.0, 0.0]
        self.calibration: cal.Calibration = cal.load()

        layout = QGridLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(10)
        layout.setColumnStretch(0, 0)
        layout.setColumnStretch(1, 0)
        layout.setColumnStretch(2, 1)
        layout.setColumnStretch(3, 0)
        layout.setColumnStretch(4, 1)

        # ---- Row 0: port + connect ----
        layout.addWidget(QLabel("Port:"), 0, 0)
        self.port_combo = QComboBox()
        self._populate_ports()
        layout.addWidget(self.port_combo, 0, 1, 1, 3)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self._toggle_connect)
        layout.addWidget(self.connect_btn, 0, 4)

        # ---- Row 1: speed ----
        layout.addWidget(QLabel("Speed:"), 1, 0)
        self.speed_input = QSpinBox()
        self.speed_input.setRange(10, MAX_SPEED)
        self.speed_input.setSingleStep(50)
        self.speed_input.setValue(DEFAULT_SPEED)
        self.speed_input.setSuffix(" steps/s")
        layout.addWidget(self.speed_input, 1, 1, 1, 3)
        self.speed_btn = QPushButton("Send")
        self.speed_btn.clicked.connect(self._send_speed)
        layout.addWidget(self.speed_btn, 1, 4)

        # ---- Per motor: 2 rows (up + down in column 1, rest side by side) ----
        self.jog_inputs: list[QDoubleSpinBox] = []
        self.target_labels: list[QLabel] = []
        self.zero_btns: list[QPushButton] = []

        for i in range(3):
            row_a = 2 + 2 * i
            row_b = row_a + 1

            # Motor label spans both rows (vertically centred)
            motor_lbl = QLabel(f"{AXIS_NAMES[i]} axis")
            layout.addWidget(motor_lbl, row_a, 0, 2, 1, Qt.AlignVCenter)

            # up on row_a, down on row_b, own object-name for clear styling
            up_btn = QPushButton("▲")
            up_btn.setObjectName("JogButton")
            up_btn.setToolTip("Micron up")
            up_btn.setFixedSize(48, 30)
            up_btn.clicked.connect(lambda _c, n=i: self._jog(n, +1))
            layout.addWidget(up_btn, row_a, 1, Qt.AlignVCenter | Qt.AlignHCenter)

            down_btn = QPushButton("▼")
            down_btn.setObjectName("JogButton")
            down_btn.setToolTip("Micron down")
            down_btn.setFixedSize(48, 30)
            down_btn.clicked.connect(lambda _c, n=i: self._jog(n, -1))
            layout.addWidget(down_btn, row_b, 1, Qt.AlignVCenter | Qt.AlignHCenter)

            # Spinbox spans both rows so it sits centred between up and down.
            # Input is in micron; on jog this is converted to steps via the
            # calibration (see _jog).
            spin = QDoubleSpinBox()
            spin.setRange(0.1, 100_000.0)   # um
            spin.setDecimals(2)
            spin.setSingleStep(1.0)
            spin.setValue(10.0)
            spin.setSuffix(" µm")
            spin.setFixedWidth(130)
            layout.addWidget(spin, row_a, 2, 2, 1, Qt.AlignVCenter)

            tlbl = QLabel("current position: 0")
            tlbl.setStyleSheet("color: gray;")
            layout.addWidget(tlbl, row_a, 3, 1, 2)

            zero_btn = QPushButton("Set 0 here")
            zero_btn.setToolTip(
                "Declares the current physical position as 0 (soft-home)."
            )
            zero_btn.clicked.connect(lambda _c, n=i: self._set_zero(n))
            layout.addWidget(zero_btn, row_b, 3, 1, 2)

            self.jog_inputs.append(spin)
            self.target_labels.append(tlbl)
            self.zero_btns.append(zero_btn)

        # ---- status ----
        status_row = 2 + 2 * 3   # = 8
        self.status = QLabel("Not connected.")
        self.status.setStyleSheet("color: gray;")
        layout.addWidget(self.status, status_row, 0, 1, 5)

        layout.setRowStretch(status_row + 1, 1)

        # render initial position labels
        for i in range(3):
            self._refresh_target_label(i)

    # -----------------------------------------------------------
    #  Helpers / utilities
    # -----------------------------------------------------------

    def _populate_ports(self) -> None:
        self.port_combo.clear()
        ports = [p.device for p in serial.tools.list_ports.comports()]
        if self.default_port not in ports:
            ports.insert(0, self.default_port)
        self.port_combo.addItems(ports)
        self.port_combo.setCurrentText(self.default_port)

    def _sync_target_um_from_steps(self, i: int) -> None:
        """Recompute the logical micron position from the integer step count.

        Used whenever the position originates from the hardware (restore paths)
        rather than from a commanded jog.
        """
        mm_per_step = self.calibration.motors[i].mm_per_step
        pos_steps = self.targets[i] * AXIS_JOG_DIR[i]
        self.target_um[i] = pos_steps * mm_per_step * 1000.0 if mm_per_step > 0 else 0.0

    def _refresh_target_label(self, i: int) -> None:
        """Update the position label, showing micron when calibrated.

        The shown position is in 'logical' coordinates (up arrow = higher number);
        for inverted axes (Z) that is the opposite of the hardware steps. The
        micron value is the commanded value (self.target_um), so a 10 um jog
        reads as 10.00 um rather than the step-quantised 9.99 um.
        """
        pos_steps = self.targets[i] * AXIS_JOG_DIR[i]
        mm_per_step = self.calibration.motors[i].mm_per_step
        if mm_per_step > 0:
            um = self.target_um[i]
            self.target_labels[i].setText(
                f"current position: {um:+.2f} µm  ({pos_steps} steps)"
            )
        else:
            self.target_labels[i].setText(
                f"current position: {pos_steps} steps (not calibrated)"
            )

    def _open_serial(self, port: str) -> serial.Serial | None:
        """Open the serial port with DTR/RTS off so the Nano does not reset."""
        ser = serial.Serial()
        ser.port = port
        ser.baudrate = BAUD
        ser.timeout = 1
        try:
            ser.dtr = False
            ser.rts = False
        except Exception:
            pass
        try:
            ser.open()
        except serial.SerialException as e:
            QMessageBox.critical(self, "Serial error", f"Cannot open {port}:\n{e}")
            return None
        return ser

    def _query_positions(self) -> tuple[int, int, int] | None:
        """Send WHERE and parse the POS response. None on timeout/parse error."""
        if not (self.serial and self.serial.is_open):
            return None
        prev_timeout = self.serial.timeout
        try:
            # Short read timeout so an unresponsive Nano does not block connecting
            # for seconds; we bound the total with a deadline.
            self.serial.timeout = 0.1
            self.serial.reset_input_buffer()
            self.serial.write(b"WHERE\n")
            self.serial.flush()
            deadline = time.monotonic() + 1.0   # wait up to ~1s for the POS response
            while time.monotonic() < deadline:
                line = self.serial.readline().decode("ascii", errors="ignore").strip()
                if not line:
                    continue                     # empty read (timeout), keep trying
                if line.startswith("POS "):
                    parts = line.split()
                    if len(parts) >= 4:
                        return (int(parts[1]), int(parts[2]), int(parts[3]))
        except (serial.SerialException, ValueError):
            return None
        finally:
            self.serial.timeout = prev_timeout
        return None

    # -----------------------------------------------------------
    #  Connect / DTR suppression / restore prompt
    # -----------------------------------------------------------

    def _toggle_connect(self) -> None:
        if self.serial and self.serial.is_open:
            # Before closing: query the last position and store it in calibration
            self._refresh_calibration_positions(silent=True)
            cal.save(self.calibration)
            self.serial.close()
            self.serial = None
            self.connect_btn.setText("Connect")
            self.status.setText("Connection closed, calibration saved.")
            self.status.setStyleSheet("color: gray;")
            return

        port = self.port_combo.currentText()
        ser = self._open_serial(port)
        if ser is None:
            return
        self.serial = ser
        self.connect_btn.setText("Disconnect")
        self.status.setText(f"Connected to {port} @ {BAUD} baud.")
        self.status.setStyleSheet("color: green;")
        self._send_speed()
        self._maybe_restore_positions()

    def _maybe_restore_positions(self) -> None:
        """If the yaml has a last-known position but the firmware is on something
        else (typically (0,0,0) after a reset), ask the user whether to restore.
        """
        if not self.calibration.any_known_position():
            return
        positions = self._query_positions()           # hardware steps from firmware
        if positions is None:
            return
        # last_position is stored logically; convert firmware to logical.
        positions_log = tuple(p * AXIS_JOG_DIR[i] for i, p in enumerate(positions))
        expected = tuple(m.last_position for m in self.calibration.motors)  # logical
        if positions_log == expected:
            # Best case: DTR suppression helped, no reset.
            for i, p in enumerate(positions):
                self.targets[i] = p
                self._sync_target_um_from_steps(i)
                self._refresh_target_label(i)
            self.status.setText(
                f"Connected, positions consistent with calibration: {expected}"
            )
            self.status.setStyleSheet("color: green;")
            return

        msg = (
            "The motor position changed since the previous session:\n\n"
            f"  Firmware now (logical): {positions_log}\n"
            f"  Last saved:            {expected}\n\n"
            "Have you NOT physically moved the motors since then?\n\n"
            "[Yes] Send SETPOS to the old values, calibration stays valid.\n"
            "[No]  Keep current position, re-zero with 'Set 0 here'."
        )
        reply = QMessageBox.question(
            self, "Restore calibration?", msg,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            for i, p_log in enumerate(expected):
                hw = p_log * AXIS_JOG_DIR[i]           # logical -> hardware
                self._write_raw(f"SETPOS {i + 1} {hw}\n")
                self.targets[i] = hw
                self._sync_target_um_from_steps(i)
                self._refresh_target_label(i)
            self.status.setText("Calibration restored, positions set back via SETPOS.")
            self.status.setStyleSheet("color: green;")
        else:
            for i, p in enumerate(positions):
                self.targets[i] = p
                self._sync_target_um_from_steps(i)
                self._refresh_target_label(i)
            self.status.setText("Keeping firmware position, re-zero via 'Set 0 here'.")
            self.status.setStyleSheet("color: #b8860b;")

    def _refresh_calibration_positions(self, silent: bool = False) -> None:
        positions = self._query_positions()
        if positions is None:
            if not silent:
                self.status.setText("Could not read position (WHERE timeout).")
                self.status.setStyleSheet("color: red;")
            return
        # Store logically (negative = moved negative), consistent with _jog.
        for i, p in enumerate(positions):
            self.calibration.motors[i].last_position = p * AXIS_JOG_DIR[i]

    # -----------------------------------------------------------
    #  Actions: speed / jog / set-zero / stop / save+load cal
    # -----------------------------------------------------------

    def _send_speed(self) -> None:
        speed = self.speed_input.value()
        cmd = f"SPEED {speed}\n"
        self._write(cmd, ok_msg=f"Speed set to {speed} steps/s.")

    def _jog(self, motor_index: int, direction: int) -> None:
        um = self.jog_inputs[motor_index].value()
        mm_per_step = self.calibration.motors[motor_index].mm_per_step
        if mm_per_step <= 0:
            self.status.setText(
                f"{AXIS_NAMES[motor_index]} axis not calibrated, "
                "micron conversion not possible."
            )
            self.status.setStyleSheet("color: red;")
            return

        # Micron -> steps via the calibration (rounded to whole steps).
        um_per_step = mm_per_step * 1000.0
        steps = round(um / um_per_step)
        delta = direction * AXIS_JOG_DIR[motor_index] * steps      # hardware steps
        new_target = self.targets[motor_index] + delta
        # Logical commanded micron position. We accumulate the exact requested
        # value (not the step-quantised value) so the display reads cleanly.
        new_um = self.target_um[motor_index] + direction * um

        # Hard limit: the logical position may not go beyond +-AXIS_LIMIT_UM.
        # Deliberately before sending: blocks the whole jog, no half move.
        limit = AXIS_LIMIT_UM[motor_index]
        if abs(new_um) > limit + 1e-6:
            self.status.setText(
                f"Blocked: {AXIS_NAMES[motor_index]} axis limit ±{limit:.0f} µm "
                f"(would go to {new_um:+.1f} µm)."
            )
            self.status.setStyleSheet("color: red;")
            return

        self.targets[motor_index] = new_target
        self.target_um[motor_index] = new_um
        self._refresh_target_label(motor_index)
        cmd = f"{motor_index + 1} {new_target}\n"
        ok = (
            f"{um:.2f} µm = {steps} steps -> "
            f"{AXIS_NAMES[motor_index]} axis to {new_um:+.1f} µm"
        )
        if self._write(cmd, ok_msg=ok):
            # Store the logical position (negative = moved negative).
            self.calibration.motors[motor_index].last_position = (
                new_target * AXIS_JOG_DIR[motor_index]
            )
            cal.save(self.calibration)

    def _set_zero(self, motor_index: int) -> None:
        if not (self.serial and self.serial.is_open):
            self.status.setText("Not connected, connect first.")
            self.status.setStyleSheet("color: red;")
            return
        cmd = f"SETPOS {motor_index + 1} 0\n"
        if self._write(cmd, ok_msg=f"Motor {motor_index + 1} ({AXIS_NAMES[motor_index]} axis) -> 0 (soft-home)"):
            self.targets[motor_index] = 0
            self.target_um[motor_index] = 0.0
            self.calibration.motors[motor_index].last_position = 0
            self._refresh_target_label(motor_index)
            cal.save(self.calibration)

    def _stop_all(self) -> None:
        if not (self.serial and self.serial.is_open):
            self.status.setText("Not connected.")
            self.status.setStyleSheet("color: red;")
            return
        try:
            self.serial.reset_output_buffer()
            self.serial.write(b"STOP\n")
            self.serial.flush()
        except serial.SerialException as e:
            self.status.setText(f"Write error: {e}")
            self.status.setStyleSheet("color: red;")
            return
        for i, lbl in enumerate(self.target_labels):
            self.targets[i] = 0
            self.target_um[i] = 0.0
            lbl.setText("current position: ? (stopped)")
        self.status.setText("STOP sent, motors stopped at unknown position.")
        self.status.setStyleSheet("color: #c0392b; font-weight: bold;")

    def _save_calibration(self) -> None:
        # mm/step is fixed (from yaml); only fetch the current position
        if self.serial and self.serial.is_open:
            self._refresh_calibration_positions(silent=False)
        try:
            cal.save(self.calibration)
        except OSError as e:
            self.status.setText(f"Save error: {e}")
            self.status.setStyleSheet("color: red;")
            return
        self.status.setText(f"Calibration saved -> {cal.CALIBRATION_PATH}")
        self.status.setStyleSheet("color: green;")

    def _load_calibration(self) -> None:
        self.calibration = cal.load()
        for i in range(3):
            self._sync_target_um_from_steps(i)
            self._refresh_target_label(i)
        self.status.setText(
            f"Calibration loaded ({self.calibration.saved_at or 'no time'})."
        )
        self.status.setStyleSheet("color: green;")

    # -----------------------------------------------------------
    #  Low-level write helpers
    # -----------------------------------------------------------

    def _write(self, cmd: str, ok_msg: str, error_style: bool = False) -> bool:
        if not (self.serial and self.serial.is_open):
            self.status.setText("Not connected.")
            self.status.setStyleSheet("color: red;")
            return False
        try:
            self.serial.write(cmd.encode("ascii"))
            self.serial.flush()
        except serial.SerialException as e:
            self.status.setText(f"Write error: {e}")
            self.status.setStyleSheet("color: red;")
            return False
        self.status.setText(ok_msg)
        self.status.setStyleSheet("color: green;" if not error_style else "color: #c0392b;")
        return True

    def _write_raw(self, cmd: str) -> None:
        """Send without a status update (for batch actions)."""
        if not (self.serial and self.serial.is_open):
            return
        try:
            self.serial.write(cmd.encode("ascii"))
            self.serial.flush()
        except serial.SerialException:
            pass

    def close_serial(self) -> None:
        if self.serial and self.serial.is_open:
            self._refresh_calibration_positions(silent=True)
            try:
                cal.save(self.calibration)
            except OSError:
                pass
            self.serial.close()

    # -----------------------------------------------------------
    #  Public API for recording.py: mm conversion
    # -----------------------------------------------------------

    def mm_per_step(self, motor_index: int) -> float:
        return self.calibration.motors[motor_index].mm_per_step


# -------------------- Moku --------------------

MOKU_DEFAULT_ADDRESS = "192.168.73.1"
MOKU_DEFAULT_TIMEBASE = 10e-3   # half time span in s (shows -T..+T)


class MokuThread(QThread):
    """Polls the Moku oscilloscope and pushes frames to the UI.

    Acquisition config (frontend, source, timebase) runs over Qt signals to the
    GUI thread.
    """

    data_ready = Signal(object, object)
    connected = Signal(str)
    failed = Signal(str)

    def __init__(self, address: str, channel: int, coupling: str,
                 range_: str, timebase: float) -> None:
        super().__init__()
        self.address = address
        self.channel = channel
        self.coupling = coupling
        self.range_ = range_
        self.timebase = timebase
        self._running = False
        self._osc = None

    def run(self) -> None:
        try:
            from moku.instruments import Oscilloscope
        except ImportError as e:
            self.failed.emit(f"moku package not installed: {e}")
            return
        try:
            self._osc = Oscilloscope(self.address, force_connect=True)
            self._osc.set_frontend(self.channel, impedance="1MOhm",
                                   coupling=self.coupling, range=self.range_)
            self._osc.set_source(self.channel, f"Input{self.channel}")
            self._osc.set_timebase(-self.timebase, self.timebase)
            self.connected.emit(
                f"Connected to {self.address} — Input{self.channel}, "
                f"{self.coupling}, {self.range_}"
            )
        except Exception as e:
            self.failed.emit(f"Connection error: {e}")
            self._cleanup()
            return

        self._running = True
        ch_key = f"ch{self.channel}"
        try:
            while self._running:
                try:
                    data = self._osc.get_data()
                except Exception as e:
                    self.failed.emit(f"Read error: {e}")
                    break
                if not data or "time" not in data:
                    continue
                values = data.get(ch_key)
                if not values:
                    continue
                self.data_ready.emit(data["time"], values)
        finally:
            self._cleanup()

    def _cleanup(self) -> None:
        if self._osc is not None:
            try:
                self._osc.relinquish_ownership()
            except Exception:
                pass
            self._osc = None

    def stop(self) -> None:
        self._running = False
        self.wait(3000)


class MokuPanel(QGroupBox):
    # Per-frame re-emit for listeners (RecordingPanel), same payload as
    # MokuThread.data_ready but emitted from the GUI thread.
    frame = Signal(object, object)

    def __init__(self) -> None:
        super().__init__("Moku:Go photodetector")
        self.thread: MokuThread | None = None
        self._timebase = MOKU_DEFAULT_TIMEBASE
        self._burst_dl = None
        self._burst_cfg: tuple[str, int, str, str] | None = None

        layout = QVBoxLayout(self)

        controls = QGridLayout()
        controls.addWidget(QLabel("IP:"), 0, 0)
        self.address_input = QLineEdit(MOKU_DEFAULT_ADDRESS)
        self.address_input.setMinimumWidth(140)
        controls.addWidget(self.address_input, 0, 1)

        controls.addWidget(QLabel("Channel:"), 0, 2)
        self.channel_combo = QComboBox()
        self.channel_combo.addItems(["1", "2"])
        controls.addWidget(self.channel_combo, 0, 3)

        controls.addWidget(QLabel("Range:"), 0, 4)
        self.range_combo = QComboBox()
        # Only the 50Vpp range is used in this setup.
        self.range_combo.addItems(["50Vpp"])
        controls.addWidget(self.range_combo, 0, 5)

        controls.addWidget(QLabel("Coupling:"), 0, 6)
        self.coupling_combo = QComboBox()
        self.coupling_combo.addItems(["DC", "AC"])
        controls.addWidget(self.coupling_combo, 0, 7)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self._toggle_connect)
        controls.addWidget(self.connect_btn, 0, 8)
        controls.setColumnStretch(1, 1)

        layout.addLayout(controls)

        fig = Figure(figsize=(8, 4))
        self.canvas = FigureCanvas(fig)
        self.canvas.setMinimumHeight(280)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.ax = fig.add_subplot(111)
        self.ax.set_xlabel("time (s)")
        self.ax.set_ylabel("voltage (V)")
        self.ax.grid(True)
        self.ax.set_xlim(-self._timebase, self._timebase)
        self.line, = self.ax.plot([], [], lw=1.2)
        fig.tight_layout()
        layout.addWidget(self.canvas, stretch=1)

        self.status = QLabel("Not connected.")
        self.status.setStyleSheet("color: gray;")
        layout.addWidget(self.status)

    def _toggle_connect(self) -> None:
        if self.thread is not None and self.thread.isRunning():
            self._stop_thread()
            self.status.setText("Connection closed.")
            self.status.setStyleSheet("color: gray;")
            return

        address = self.address_input.text().strip()
        if not address:
            self.status.setText("Enter an IP address.")
            self.status.setStyleSheet("color: red;")
            return
        channel = int(self.channel_combo.currentText())
        coupling = self.coupling_combo.currentText()
        range_ = self.range_combo.currentText()

        self.thread = MokuThread(address, channel, coupling, range_,
                                 self._timebase)
        self.thread.connected.connect(self._on_connected)
        self.thread.data_ready.connect(self._on_data)
        self.thread.failed.connect(self._on_failed)
        self.thread.start()

        self.connect_btn.setText("Connecting...")
        self.connect_btn.setEnabled(False)
        self.status.setText(f"Connecting to {address} ...")
        self.status.setStyleSheet("color: gray;")

    def _on_connected(self, msg: str) -> None:
        self.connect_btn.setText("Disconnect")
        self.connect_btn.setEnabled(True)
        self.status.setText(msg)
        self.status.setStyleSheet("color: green;")

    def _on_data(self, t, values) -> None:
        self.frame.emit(t, values)
        self.line.set_data(t, values)
        self.ax.relim()
        self.ax.autoscale_view(scalex=False, scaley=True)
        self.canvas.draw_idle()

    def _on_failed(self, msg: str) -> None:
        self.status.setText(msg)
        self.status.setStyleSheet("color: red;")
        self.connect_btn.setText("Connect")
        self.connect_btn.setEnabled(True)

    def _stop_thread(self) -> None:
        if self.thread is not None:
            self.thread.stop()
            self.thread = None
        self.connect_btn.setText("Connect")
        self.connect_btn.setEnabled(True)

    def close_moku(self) -> None:
        if self._burst_dl is not None:
            try:
                self._burst_dl.close()
            except Exception:
                pass
            self._burst_dl = None
        self._stop_thread()

    # ---------- Burst mode (Datalogger) ----------
    #
    # Used by RecordingPanel: start_burst_mode before the burst, acquire_burst
    # for the measurement, end_burst_mode afterwards. During burst mode the live
    # Oscilloscope graph does not run.

    def start_burst_mode(self) -> None:
        if self._burst_dl is not None:
            return
        if self.thread is None or not self.thread.isRunning():
            raise RuntimeError("Moku not connected, connect first via 'Connect'.")

        address = self.address_input.text().strip()
        channel = int(self.channel_combo.currentText())
        coupling = self.coupling_combo.currentText()
        range_ = self.range_combo.currentText()
        self._burst_cfg = (address, channel, coupling, range_)

        self._stop_thread()
        self.status.setText(
            "Burst mode (Datalogger), live preview paused."
        )
        self.status.setStyleSheet("color: #b8860b;")

        from datalogger import MokuDatalogger
        self._burst_dl = MokuDatalogger(address, channel, range_, coupling)
        try:
            self._burst_dl.open()
        except Exception:
            self._burst_dl = None
            self._restart_preview()
            raise

    def acquire_burst(self, fs: int, T: float) -> np.ndarray:
        if self._burst_dl is None:
            raise RuntimeError("Burst mode not active, call start_burst_mode() first.")
        return self._burst_dl.acquire_burst(fs, T)

    def end_burst_mode(self) -> None:
        if self._burst_dl is None:
            return
        try:
            self._burst_dl.close()
        except Exception:
            pass
        self._burst_dl = None
        self._restart_preview()

    def _restart_preview(self) -> None:
        if self._burst_cfg is None:
            return
        address, channel, coupling, range_ = self._burst_cfg
        self.thread = MokuThread(address, channel, coupling, range_,
                                 self._timebase)
        self.thread.connected.connect(self._on_connected)
        self.thread.data_ready.connect(self._on_data)
        self.thread.failed.connect(self._on_failed)
        self.thread.start()
        self.connect_btn.setText("Connecting...")
        self.connect_btn.setEnabled(False)
        self.status.setText(f"Restarting live preview on {address} ...")
        self.status.setStyleSheet("color: gray;")


# -------------------- Status pill (top-bar component) --------------------

class StatusPill(QWidget):
    """Compact connected/disconnected indicator with dot + label + meta text."""

    def __init__(self, label: str) -> None:
        super().__init__()
        self.setProperty("role", "pill")
        self.setProperty("connected", False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 12, 0)
        layout.setSpacing(8)

        self.dot = QLabel()
        self.dot.setProperty("role", "pill-dot")
        self.dot.setProperty("connected", False)

        self.label = QLabel(label)
        self.label.setProperty("role", "pill-label")

        self.meta = QLabel("—")
        self.meta.setProperty("role", "pill-meta")

        layout.addWidget(self.dot)
        layout.addWidget(self.label)
        layout.addWidget(self.meta)

    def set_state(self, connected: bool, meta: str) -> None:
        connected_changed = self.property("connected") != connected
        self.setProperty("connected", connected)
        self.dot.setProperty("connected", connected)
        self.meta.setText(meta if meta else ("—" if not connected else ""))
        if connected_changed:
            # Force QSS re-evaluation
            for w in (self, self.dot):
                w.style().unpolish(w)
                w.style().polish(w)


# -------------------- Top bar --------------------

class TopBar(QWidget):
    """Top status bar: brand, pills, actions."""

    def __init__(self, motor_panel: "MotorPanel", moku_panel: "MokuPanel",
                 cam_thread: "CameraThread") -> None:
        super().__init__()
        self.motor_panel = motor_panel
        self.moku_panel = moku_panel
        self.cam_thread = cam_thread
        self._camera_connected = False
        self._camera_index = -1
        self.setObjectName("TopBar")
        self.setFixedHeight(50)

        h = QHBoxLayout(self)
        h.setContentsMargins(20, 0, 20, 0)
        h.setSpacing(20)

        # Brand
        brand_box = QHBoxLayout()
        brand_box.setSpacing(6)
        mark = QLabel("◈"); mark.setObjectName("BrandMark")
        name = QLabel("Bep-Project"); name.setObjectName("BrandName")
        sep = QLabel("·"); sep.setObjectName("BrandSep")
        sub = QLabel("Confocal"); sub.setObjectName("BrandSub")
        for w in (mark, name, sep, sub):
            brand_box.addWidget(w)
        brand_wrap = QWidget()
        brand_wrap.setLayout(brand_box)
        h.addWidget(brand_wrap)

        # Vertical divider
        div = QFrame()
        div.setFrameShape(QFrame.VLine)
        div.setFixedHeight(22)
        div.setStyleSheet("color: #252c36;")
        h.addWidget(div)

        # Pills
        self.motor_pill = StatusPill("Motors")
        self.moku_pill = StatusPill("Moku")
        self.camera_pill = StatusPill("Camera")
        for p in (self.motor_pill, self.moku_pill, self.camera_pill):
            h.addWidget(p)

        h.addStretch(1)

        # Actions: Restore position, Help
        self.restore_btn = QPushButton("↺  Restore position")
        self.restore_btn.setObjectName("TopBarAction")
        self.restore_btn.setToolTip(
            "Load the last known motor position from calibration.yaml\n"
            "and send SETPOS to the Arduino."
        )
        self.restore_btn.clicked.connect(self._restore_positions)
        h.addWidget(self.restore_btn)

        self.help_btn = QPushButton("?")
        self.help_btn.setObjectName("IconButton")
        self.help_btn.setToolTip("Open README.md")
        self.help_btn.clicked.connect(self._show_help)
        h.addWidget(self.help_btn)

        # Camera detect: the thread tells us when a microscope camera connects/drops.
        self.cam_thread.camera_connected.connect(self._on_camera_connected)
        self.cam_thread.camera_lost.connect(self._on_camera_lost)

        # Polling timer for motor/moku (no changes to existing classes)
        self._poll = QTimer(self)
        self._poll.setInterval(500)
        self._poll.timeout.connect(self._refresh_pills)
        self._poll.start()
        self._refresh_pills()

    def _on_camera_connected(self, index: int, name: str = "") -> None:
        self._camera_connected = True
        self._camera_index = index
        # Show a short device name when available, else the USB index.
        meta = (name or f"USB{index}")
        if len(meta) > 22:
            meta = meta[:21] + "…"
        self.camera_pill.set_state(True, meta)

    def _on_camera_lost(self) -> None:
        self._camera_connected = False
        self.camera_pill.set_state(False, "scanning")

    def _refresh_pills(self) -> None:
        # Motors
        ser = self.motor_panel.serial
        if ser is not None and ser.is_open:
            self.motor_pill.set_state(True, self.motor_panel.port_combo.currentText())
        else:
            self.motor_pill.set_state(False, self.motor_panel.port_combo.currentText())
        # Moku
        if self.moku_panel.thread is not None and self.moku_panel.thread.isRunning():
            self.moku_pill.set_state(True, self.moku_panel.address_input.text())
        else:
            self.moku_pill.set_state(False, self.moku_panel.address_input.text())
        # Camera
        if not self._camera_connected:
            self.camera_pill.set_state(False, "scanning")

    def _restore_positions(self) -> None:
        mp = self.motor_panel
        if not (mp.serial and mp.serial.is_open):
            QMessageBox.warning(self, "Not connected",
                                "Connect to the Arduino first via the Setup tab.")
            return
        # Always reload from disk, in-memory may be stale
        mp.calibration = cal.load()
        if not mp.calibration.any_known_position():
            QMessageBox.information(self, "Restore position",
                                    "No saved position found in calibration.yaml.")
            return
        expected = tuple(m.last_position for m in mp.calibration.motors)
        msg = (
            f"Set the motor positions back to the saved values:\n\n"
            f"  Motor 1 ({AXIS_NAMES[0]} axis): {expected[0]} steps\n"
            f"  Motor 2 ({AXIS_NAMES[1]} axis): {expected[1]} steps\n"
            f"  Motor 3 ({AXIS_NAMES[2]} axis): {expected[2]} steps\n\n"
            "This sends SETPOS to the Arduino without moving the motors.\n"
            "Only do this if the motors have not been physically moved."
        )
        reply = QMessageBox.question(self, "Restore position?", msg,
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            for i, p in enumerate(expected):
                mp._write_raw(f"SETPOS {i + 1} {p}\n")
                mp.targets[i] = p
                mp._sync_target_um_from_steps(i)
                mp._refresh_target_label(i)
            cal.save(mp.calibration)
            mp.status.setText("Calibration restored, positions set back via SETPOS.")
            mp.status.setStyleSheet("color: green;")

    def _show_help(self) -> None:
        import os
        from pathlib import Path
        readme = Path(__file__).parent / "README.md"
        if readme.exists():
            os.startfile(str(readme))
        else:
            QMessageBox.information(self, "Help", "README.md not found.")


# -------------------- Camera card (wraps CameraPanel with a title row) --------------------

class CameraCard(QFrame):
    """Cosmetic wrapper around CameraPanel, shows a 'Camera' title + LIVE badge."""

    def __init__(self, camera_panel: CameraPanel) -> None:
        super().__init__()
        self.setObjectName("CameraCard")
        self.setStyleSheet(
            "QFrame#CameraCard {"
            " background-color: #161b22;"
            " border: 1px solid #252c36;"
            " border-radius: 8px;"
            "}"
        )

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 12)
        v.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Camera feed")
        title.setProperty("role", "title")
        self.subtitle = QLabel("microscope")
        self.subtitle.setProperty("role", "subtitle")
        header.addWidget(title)
        header.addSpacing(8)
        header.addWidget(self.subtitle)
        header.addStretch(1)

        self.live = QLabel("● OFFLINE")
        self._set_live_style(False)
        header.addWidget(self.live)

        v.addLayout(header)
        v.addWidget(camera_panel, stretch=1)

    def _set_live_style(self, on: bool) -> None:
        if on:
            self.live.setText("● LIVE")
            self.live.setStyleSheet(
                "color: #ef4444; font-weight: 600;"
                " font-family: 'Inter', system-ui, sans-serif;"
                " font-size: 11px; letter-spacing: 1px;"
                " background-color: rgba(239,68,68,0.1);"
                " border: 1px solid rgba(239,68,68,0.3);"
                " border-radius: 4px; padding: 2px 8px;"
            )
        else:
            self.live.setText("● OFFLINE")
            self.live.setStyleSheet(
                "color: #6b7280; font-weight: 600;"
                " font-family: 'Inter', system-ui, sans-serif;"
                " font-size: 11px; letter-spacing: 1px;"
                " background-color: rgba(107,114,128,0.1);"
                " border: 1px solid rgba(107,114,128,0.3);"
                " border-radius: 4px; padding: 2px 8px;"
            )

    def set_live(self, on: bool) -> None:
        self._set_live_style(on)


# -------------------- Main window --------------------

def _wrap_scroll(widget: QWidget) -> QScrollArea:
    """Put *widget* inside a scrollable area so it never gets clipped.

    When the available space is at least the widget's minimum size, the widget
    fills the viewport exactly as before (no scrollbars). When the window is too
    small or the display is heavily scaled, scrollbars appear instead of the
    content being cut off, so every control stays reachable on any screen size.

    The area is transparent and borderless so the existing QSS background and
    card styling show through unchanged.
    """
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setWidget(widget)
    scroll.viewport().setStyleSheet("background: transparent;")
    scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
    return scroll


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Bep-Project · Confocal")
        # Preferred size; _fit_to_screen() in main() clamps this to the actual
        # display so the window never opens larger than the screen it lands on.
        self.resize(1400, 900)

        # ---- panels (functionally unchanged) ----
        self.camera_panel = CameraPanel()
        self.motor_panel = MotorPanel()
        self.lamp_panel = LampPanel(
            get_serial=lambda: self.motor_panel.serial,
            title="Inner lamp (WS2812B-8, pin A2)",
            command="LAMP",
        )
        self.lamp_panel_buiten = LampPanel(
            get_serial=lambda: self.motor_panel.serial,
            title="Outer lamp (WS2812B-8, pin A3)",
            command="LAMP2",
        )
        self.moku_panel = MokuPanel()
        # Calibration graph before the recording panel: the manual tab reads its
        # linearization live to convert burst voltage to displacement.
        self.calibration_graph_panel = CalibrationGraphPanel()
        self.recording_panel = RecordingPanel(
            moku_panel=self.moku_panel,
            motor_panel=self.motor_panel,
            lamp_panel=self.lamp_panel,
            calibration_graph_panel=self.calibration_graph_panel,
        )

        # ---- camera thread ----
        self.cam_thread = CameraThread()
        self.cam_thread.frame_ready.connect(self.camera_panel.update_frame)
        self.cam_thread.start()

        # Camera settings tab (needs the thread for set_property)
        self.camera_settings_panel = CameraSettingsPanel(self.cam_thread)

        # ---- top bar ----
        self.top_bar = TopBar(
            motor_panel=self.motor_panel,
            moku_panel=self.moku_panel,
            cam_thread=self.cam_thread,
        )

        # ---- camera card (left) ----
        self.camera_card = CameraCard(self.camera_panel)

        # Camera connect/disconnect drives the card badge and the panel message.
        self.cam_thread.camera_connected.connect(lambda *_: self.camera_card.set_live(True))
        self.cam_thread.camera_lost.connect(lambda: self.camera_card.set_live(False))
        self.cam_thread.camera_lost.connect(self.camera_panel.show_waiting)

        # ---- sidebar (right) = tabs + always-visible lamp ----
        # Suppress the redundant QGroupBox title, the tab name already says it
        for panel in (self.recording_panel, self.calibration_graph_panel,
                      self.motor_panel, self.camera_settings_panel):
            panel.setTitle("")
            panel.setProperty("inTab", True)
            panel.style().unpolish(panel)
            panel.style().polish(panel)

        # Camera tab = settings + both lamp panels (the lamp lights the camera
        # image, so its control logically belongs with the Camera tab)
        camera_tab = QWidget()
        camera_tab_v = QVBoxLayout(camera_tab)
        camera_tab_v.setContentsMargins(0, 0, 0, 0)
        camera_tab_v.setSpacing(12)
        camera_tab_v.addWidget(self.camera_settings_panel)
        camera_tab_v.addWidget(self.lamp_panel)
        camera_tab_v.addWidget(self.lamp_panel_buiten)
        camera_tab_v.addStretch(1)

        # Each tab page is wrapped in a scroll area so a tall page (e.g. the
        # Camera tab with both lamp panels) scrolls instead of being clipped on
        # a short sidebar; the panels themselves are unchanged.
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(_wrap_scroll(self.recording_panel), "Manual")
        self.tabs.addTab(_wrap_scroll(self.calibration_graph_panel), "Calibration graph")
        self.tabs.addTab(_wrap_scroll(self.motor_panel), "Setup")
        self.tabs.addTab(_wrap_scroll(camera_tab), "Camera")
        self.tabs.setCurrentIndex(2)  # start in Setup so you can connect first

        sidebar = QWidget()
        sidebar_v = QVBoxLayout(sidebar)
        sidebar_v.setContentsMargins(0, 0, 0, 0)
        sidebar_v.setSpacing(12)
        sidebar_v.addWidget(self.tabs, stretch=1)

        # ---- horizontal splitter (camera | sidebar) ----
        h_splitter = QSplitter(Qt.Horizontal)
        h_splitter.addWidget(self.camera_card)
        h_splitter.addWidget(sidebar)
        h_splitter.setStretchFactor(0, 3)
        h_splitter.setStretchFactor(1, 2)
        h_splitter.setSizes([840, 560])
        h_splitter.setChildrenCollapsible(False)

        # ---- vertical splitter (top | moku) ----
        # Low enough that the window still fits on a 768 px-tall laptop screen;
        # the plot grows to use any extra height the splitter hands it.
        self.moku_panel.setMinimumHeight(260)
        v_splitter = QSplitter(Qt.Vertical)
        v_splitter.addWidget(h_splitter)
        v_splitter.addWidget(self.moku_panel)
        v_splitter.setStretchFactor(0, 1)
        v_splitter.setStretchFactor(1, 1)
        v_splitter.setSizes([460, 440])
        v_splitter.setChildrenCollapsible(False)

        # ---- root widget ----
        root = QWidget()
        root.setObjectName("root")
        root_v = QVBoxLayout(root)
        root_v.setContentsMargins(0, 0, 0, 0)
        root_v.setSpacing(0)
        root_v.addWidget(self.top_bar)

        body = QWidget()
        body_v = QVBoxLayout(body)
        body_v.setContentsMargins(12, 12, 12, 12)
        body_v.setSpacing(0)
        body_v.addWidget(v_splitter)
        # Below this comfortable size the full layout (camera feed + sidebar +
        # Moku plot) would have to squash to fit. Instead we keep it at this size
        # and let the surrounding scroll area show scrollbars, so the whole UI
        # stays usable on small or DPI-scaled laptop screens.
        body.setMinimumSize(1040, 720)
        root_v.addWidget(_wrap_scroll(body), stretch=1)

        self.setCentralWidget(root)

    def closeEvent(self, event) -> None:
        self.recording_panel.close_recording()
        self.cam_thread.stop()
        self.motor_panel.close_serial()
        self.moku_panel.close_moku()
        super().closeEvent(event)


# -------------------- App entry --------------------

def _load_fonts() -> None:
    """Register bundled Inter fonts (otf/ttf) so QSS can use them."""
    from pathlib import Path
    fonts_dir = Path(__file__).parent / "fonts"
    if not fonts_dir.exists():
        return
    for pattern in ("*.otf", "*.ttf"):
        for font_file in fonts_dir.glob(pattern):
            QFontDatabase.addApplicationFont(str(font_file))


def _fit_to_screen(win: QMainWindow) -> None:
    """Clamp the window to the screen it opens on.

    The layout is designed around a 1400x900 window, but on a smaller or
    heavily DPI-scaled laptop screen that size would overflow off-screen (the
    title bar can end up unreachable). We shrink the window to the available
    work area, keep a margin for the taskbar, and maximize it when the preferred
    size does not fit. On a large monitor nothing changes.
    """
    screen = win.screen() or QGuiApplication.primaryScreen()
    if screen is None:
        return
    avail = screen.availableGeometry()
    pref_w, pref_h = 1400, 900
    fits = pref_w <= avail.width() and pref_h <= avail.height()
    target_w = min(pref_w, avail.width() - 40)
    target_h = min(pref_h, avail.height() - 80)
    win.resize(max(target_w, 800), max(target_h, 600))
    win.move(avail.center() - win.rect().center())
    if not fits:
        # Defer actual display to the win.show() in main().
        win.setWindowState(win.windowState() | Qt.WindowMaximized)


def _load_stylesheet(app: QApplication) -> None:
    """Load styles.qss if it sits next to ui.py. Silent if missing."""
    try:
        from pathlib import Path
        qss_path = Path(__file__).parent / "styles.qss"
        if qss_path.exists():
            app.setStyleSheet(qss_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Could not load styles.qss: {e}")


def main() -> None:
    # PassThrough keeps fractional Windows display scaling (e.g. 125% / 150%)
    # smooth instead of snapping to whole integers. Must be set before the
    # QApplication is created.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Bep-Project")
    _load_fonts()
    _load_stylesheet(app)
    win = MainWindow()
    _fit_to_screen(win)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
