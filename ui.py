"""Geintegreerde UI voor Bep-Project.

- Linksboven: live USB-camera (CameraThread, index CAMERA_INDEX)
- Rechtsboven: jog-besturing voor de 3 stepper motors via de Arduino Nano.
- Onder: Moku:Go live fotodetector-plot (MokuThread, embedded).

Afhankelijkheden:
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
from PySide6.QtGui import QFontDatabase, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
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
from camera_settings import CameraSettingsPanel
from lamp import LampPanel
from recording import RecordingPanel
from scan import ScanPanel


CAMERA_INDEX = 0
DEFAULT_PORT = "COM4"
BAUD = 9600
MAX_STEPS = 4096
DEFAULT_SPEED = 500   # AccelStepper setMaxSpeed (steps/s)
MAX_SPEED = 2000
AXIS_NAMES = ("X", "Y", "Z")   # motor 1 = X-as, motor 2 = Y-as, motor 3 = Z-as
# Jog-richting per as: +1 = ▲ verhoogt stappen, -1 = ▲ verlaagt stappen.
# Z is omgedraaid zodat ▲ fysiek omhoog beweegt i.p.v. omlaag.
AXIS_JOG_DIR = (1, 1, -1)


# -------------------- Camera --------------------

class CameraThread(QThread):
    frame_ready = Signal(np.ndarray)

    def __init__(self, index: int = CAMERA_INDEX) -> None:
        super().__init__()
        self._index = index
        self._running = False
        # Thread-safe wachtrij voor OpenCV-property changes (UI → run-loop)
        self._pending_props: dict[int, float] = {}
        self._props_lock = threading.Lock()
        # Zwart-wit toggle — bool reads/writes zijn atomair onder de GIL
        self._grayscale = False

    def run(self) -> None:
        cap = cv2.VideoCapture(self._index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            self.frame_ready.emit(
                np.zeros((360, 480, 3), dtype=np.uint8)
            )
            print(f"Kan camera met index {self._index} niet openen.")
            return

        # ---- Camera tunen voor maximale beeldkwaliteit ----
        # FOURCC vóór resolutie: DirectShow weigert hoge resoluties op YUY2 (raw)
        # over USB 2.0, met MJPG (compressed) gaat 1080p@30 vrijwel altijd wel.
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        # Probeer 1080p eerst, val terug naar 720p, anders houd wat de cam geeft.
        for target_w, target_h in ((1920, 1080), (1280, 720)):
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, target_w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, target_h)
            if (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) == target_w
                    and int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) == target_h):
                break
        cap.set(cv2.CAP_PROP_FPS, 30)
        # BUFFERSIZE=1: nieuwste frame, geen achterstand → sliders voelen direct
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        # Auto-focus/WB aan-by-default — manual override komt in tier 2 UX
        cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
        cap.set(cv2.CAP_PROP_AUTO_WB, 1)
        # Kleur forceren bij elke start: DirectShow bewaart camera-properties in de
        # driver tussen sessies. Een eerdere versie zette grayscale via SATURATION=0;
        # die 0 blijft persistent hangen waardoor het beeld zwart-wit blijft. Hier
        # zetten we 'm terug op een neutrale kleurwaarde (128, gelijk aan brightness/
        # contrast-neutraal). De zwart-wit-optie loopt nu volledig via _grayscale.
        cap.set(cv2.CAP_PROP_SATURATION, 128)

        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        print(f"Camera geopend op {w}x{h} @ {fps:.0f}fps (MJPG)")

        self._running = True
        try:
            while self._running:
                # Drain pending property-changes en pas ze toe vóór 't volgende frame
                with self._props_lock:
                    pending = self._pending_props
                    self._pending_props = {}
                for prop_id, value in pending.items():
                    cap.set(prop_id, value)

                ok, frame = cap.read()
                if not ok:
                    continue
                if self._grayscale:
                    # GRAY→BGR terug zodat downstream (cvtColor BGR2RGB) blijft werken
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    frame = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
                self.frame_ready.emit(frame)
        finally:
            cap.release()

    def stop(self) -> None:
        self._running = False
        self.wait()

    def set_property(self, prop_id: int, value: float) -> None:
        """Thread-safe: wachtrij een OpenCV cap.set() voor het volgende frame."""
        with self._props_lock:
            self._pending_props[prop_id] = value

    def set_grayscale(self, on: bool) -> None:
        self._grayscale = bool(on)


class CameraPanel(QLabel):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(480, 360)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background-color: black; color: white;")
        self.setText("Camera laden...")

    def update_frame(self, frame: np.ndarray) -> None:
        rgb = np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        h, w, ch = rgb.shape
        bytes_per_line = ch * w
        qimg = QImage(rgb.tobytes(), w, h, bytes_per_line, QImage.Format_RGB888)
        pix = QPixmap.fromImage(qimg)
        # Alleen downscalen — upscalen geeft blur, beter native + zwarte rand
        panel = self.size()
        if w > panel.width() or h > panel.height():
            pix = pix.scaled(panel, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.setPixmap(pix)


# -------------------- Motors --------------------

class MotorPanel(QGroupBox):
    def __init__(self, default_port: str = DEFAULT_PORT) -> None:
        super().__init__("Stepper motors (Arduino Nano)")
        self.serial: serial.Serial | None = None
        self.default_port = default_port
        self.targets: list[int] = [0, 0, 0]
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

        # ---- Rij 0: poort + verbind ----
        layout.addWidget(QLabel("Poort:"), 0, 0)
        self.port_combo = QComboBox()
        self._populate_ports()
        layout.addWidget(self.port_combo, 0, 1, 1, 3)
        self.connect_btn = QPushButton("Verbind")
        self.connect_btn.clicked.connect(self._toggle_connect)
        layout.addWidget(self.connect_btn, 0, 4)

        # ---- Rij 1: snelheid ----
        layout.addWidget(QLabel("Snelheid:"), 1, 0)
        self.speed_input = QSpinBox()
        self.speed_input.setRange(10, MAX_SPEED)
        self.speed_input.setSingleStep(50)
        self.speed_input.setValue(DEFAULT_SPEED)
        self.speed_input.setSuffix(" stappen/s")
        layout.addWidget(self.speed_input, 1, 1, 1, 3)
        self.speed_btn = QPushButton("Stuur")
        self.speed_btn.clicked.connect(self._send_speed)
        layout.addWidget(self.speed_btn, 1, 4)

        # ---- Per motor: 2 rijen (↑ + ↓ in kolom 1, rest naast elkaar) ----
        self.step_inputs: list[QSpinBox] = []
        self.target_labels: list[QLabel] = []
        self.zero_btns: list[QPushButton] = []

        for i in range(3):
            row_a = 2 + 2 * i
            row_b = row_a + 1

            # Motor-label spant beide rijen (verticaal gecentreerd)
            motor_lbl = QLabel(f"{AXIS_NAMES[i]}-as")
            layout.addWidget(motor_lbl, row_a, 0, 2, 1, Qt.AlignVCenter)

            # ▲ op row_a, ▼ op row_b — eigen object-name voor duidelijke styling
            up_btn = QPushButton("▲")
            up_btn.setObjectName("JogButton")
            up_btn.setToolTip("Stappen omhoog")
            up_btn.setFixedSize(48, 30)
            up_btn.clicked.connect(lambda _c, n=i: self._jog(n, +1))
            layout.addWidget(up_btn, row_a, 1, Qt.AlignVCenter | Qt.AlignHCenter)

            down_btn = QPushButton("▼")
            down_btn.setObjectName("JogButton")
            down_btn.setToolTip("Stappen omlaag")
            down_btn.setFixedSize(48, 30)
            down_btn.clicked.connect(lambda _c, n=i: self._jog(n, -1))
            layout.addWidget(down_btn, row_b, 1, Qt.AlignVCenter | Qt.AlignHCenter)

            # Spinbox spant beide rijen → komt centraal tussen ▲ en ▼ te staan
            spin = QSpinBox()
            spin.setRange(10, 2_147_483_647)  # geen praktische bovengrens (INT_MAX)
            spin.setSingleStep(10)
            spin.setValue(1000)
            spin.setSuffix(" stappen")
            spin.setFixedWidth(130)
            layout.addWidget(spin, row_a, 2, 2, 1, Qt.AlignVCenter)

            tlbl = QLabel("huidige positie: 0")
            tlbl.setStyleSheet("color: gray;")
            layout.addWidget(tlbl, row_a, 3, 1, 2)

            zero_btn = QPushButton("Zet 0 hier")
            zero_btn.setToolTip(
                "Verklaart de huidige fysieke positie als 0 (soft-home)."
            )
            zero_btn.clicked.connect(lambda _c, n=i: self._set_zero(n))
            layout.addWidget(zero_btn, row_b, 3, 1, 2)

            self.step_inputs.append(spin)
            self.target_labels.append(tlbl)
            self.zero_btns.append(zero_btn)

        # ---- status ----
        status_row = 2 + 2 * 3   # = 8
        self.status = QLabel("Niet verbonden.")
        self.status.setStyleSheet("color: gray;")
        layout.addWidget(self.status, status_row, 0, 1, 5)

        layout.setRowStretch(status_row + 1, 1)

        # render initial mm-target labels
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

    def _refresh_target_label(self, i: int) -> None:
        """Werk positie-label bij — toon mm als gekalibreerd.

        Getoonde positie staat in 'logische' coordinaten (▲ = hoger getal); voor
        omgedraaide assen (Z) is dat het tegengestelde van de hardware-stappen.
        """
        pos = self.targets[i] * AXIS_JOG_DIR[i]
        mm_per_step = self.calibration.motors[i].mm_per_step
        if mm_per_step > 0:
            mm = pos * mm_per_step
            self.target_labels[i].setText(f"huidige positie: {pos}  ({mm:+.4f} mm)")
        else:
            self.target_labels[i].setText(f"huidige positie: {pos}")

    def _open_serial(self, port: str) -> serial.Serial | None:
        """Open seriële poort met DTR/RTS uit zodat de Nano niet reset."""
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
            QMessageBox.critical(self, "Serial fout", f"Kan {port} niet openen:\n{e}")
            return None
        return ser

    def _query_positions(self) -> tuple[int, int, int] | None:
        """Stuur WHERE en parse de POS-respons. None bij timeout/parse-fout."""
        if not (self.serial and self.serial.is_open):
            return None
        prev_timeout = self.serial.timeout
        try:
            # Korte read-timeout zodat een niet-reagerende Nano het verbinden niet
            # seconden lang blokkeert; we begrenzen het totaal met een deadline.
            self.serial.timeout = 0.1
            self.serial.reset_input_buffer()
            self.serial.write(b"WHERE\n")
            self.serial.flush()
            deadline = time.monotonic() + 1.0   # max ~1s wachten op POS-respons
            while time.monotonic() < deadline:
                line = self.serial.readline().decode("ascii", errors="ignore").strip()
                if not line:
                    continue                     # lege read (timeout) → blijf proberen
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
    #  Verbinden / DTR-onderdrukking / restore-prompt
    # -----------------------------------------------------------

    def _toggle_connect(self) -> None:
        if self.serial and self.serial.is_open:
            # Vóór sluiten: vraag laatste positie en sla op in calibration
            self._refresh_calibration_positions(silent=True)
            cal.save(self.calibration)
            self.serial.close()
            self.serial = None
            self.connect_btn.setText("Verbind")
            self.status.setText("Verbinding gesloten — kalibratie opgeslagen.")
            self.status.setStyleSheet("color: gray;")
            return

        port = self.port_combo.currentText()
        ser = self._open_serial(port)
        if ser is None:
            return
        self.serial = ser
        self.connect_btn.setText("Ontkoppel")
        self.status.setText(f"Verbonden met {port} @ {BAUD} baud.")
        self.status.setStyleSheet("color: green;")
        self._send_speed()
        self._maybe_restore_positions()

    def _maybe_restore_positions(self) -> None:
        """Als yaml een laatst-bekende positie heeft maar firmware staat op iets
        anders (typisch (0,0,0) na reset), vraag de user of we moeten herstellen.
        """
        if not self.calibration.any_known_position():
            return
        positions = self._query_positions()
        if positions is None:
            return
        expected = tuple(m.last_position for m in self.calibration.motors)
        if positions == expected:
            # Mooie situatie: DTR-onderdrukking heeft geholpen, geen reset.
            for i, p in enumerate(positions):
                self.targets[i] = p
                self._refresh_target_label(i)
            self.status.setText(
                f"Verbonden — posities consistent met kalibratie: {expected}"
            )
            self.status.setStyleSheet("color: green;")
            return

        msg = (
            "De motor-positie is veranderd sinds de vorige sessie:\n\n"
            f"  Firmware nu:           {positions}\n"
            f"  Laatst opgeslagen:     {expected}\n\n"
            "Heb je sindsdien de motoren NIET fysiek bewogen?\n\n"
            "[Ja]  Stuur SETPOS naar de oude waarden — kalibratie blijft geldig.\n"
            "[Nee] Behoud huidige positie — eik opnieuw door 'Zet 0 hier' te klikken."
        )
        reply = QMessageBox.question(
            self, "Kalibratie herstellen?", msg,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            for i, p in enumerate(expected):
                self._write_raw(f"SETPOS {i + 1} {p}\n")
                self.targets[i] = p
                self._refresh_target_label(i)
            self.status.setText("Kalibratie hersteld — posities teruggezet via SETPOS.")
            self.status.setStyleSheet("color: green;")
        else:
            for i, p in enumerate(positions):
                self.targets[i] = p
                self._refresh_target_label(i)
            self.status.setText("Behoud firmware-positie — eik opnieuw via 'Zet 0 hier'.")
            self.status.setStyleSheet("color: #b8860b;")

    def _refresh_calibration_positions(self, silent: bool = False) -> None:
        positions = self._query_positions()
        if positions is None:
            if not silent:
                self.status.setText("Kon positie niet uitlezen (WHERE timeout).")
                self.status.setStyleSheet("color: red;")
            return
        for i, p in enumerate(positions):
            self.calibration.motors[i].last_position = p

    # -----------------------------------------------------------
    #  Acties: snelheid / jog / set-zero / stop / save+load cal
    # -----------------------------------------------------------

    def _send_speed(self) -> None:
        speed = self.speed_input.value()
        cmd = f"SPEED {speed}\n"
        self._write(cmd, ok_msg=f"Snelheid gezet op {speed} stappen/s.")

    def _jog(self, motor_index: int, direction: int) -> None:
        step_count = self.step_inputs[motor_index].value()
        self.targets[motor_index] += direction * AXIS_JOG_DIR[motor_index] * step_count
        self._refresh_target_label(motor_index)
        target = self.targets[motor_index]
        cmd = f"{motor_index + 1} {target}\n"
        if self._write(cmd, ok_msg=f"Verzonden: {cmd.strip()}"):
            self.calibration.motors[motor_index].last_position = target
            cal.save(self.calibration)

    def _set_zero(self, motor_index: int) -> None:
        if not (self.serial and self.serial.is_open):
            self.status.setText("Niet verbonden — verbind eerst.")
            self.status.setStyleSheet("color: red;")
            return
        cmd = f"SETPOS {motor_index + 1} 0\n"
        if self._write(cmd, ok_msg=f"Motor {motor_index + 1} ({AXIS_NAMES[motor_index]}-as) → 0 (soft-home)"):
            self.targets[motor_index] = 0
            self.calibration.motors[motor_index].last_position = 0
            self._refresh_target_label(motor_index)
            cal.save(self.calibration)

    def _stop_all(self) -> None:
        if not (self.serial and self.serial.is_open):
            self.status.setText("Niet verbonden.")
            self.status.setStyleSheet("color: red;")
            return
        try:
            self.serial.reset_output_buffer()
            self.serial.write(b"STOP\n")
            self.serial.flush()
        except serial.SerialException as e:
            self.status.setText(f"Schrijf-fout: {e}")
            self.status.setStyleSheet("color: red;")
            return
        for i, lbl in enumerate(self.target_labels):
            self.targets[i] = 0
            lbl.setText("huidige positie: ? (gestopt)")
        self.status.setText("STOP verzonden — motoren gestopt op onbekende positie.")
        self.status.setStyleSheet("color: #c0392b; font-weight: bold;")

    def _save_calibration(self) -> None:
        # mm/stap is vast (uit yaml); enkel actuele positie ophalen
        if self.serial and self.serial.is_open:
            self._refresh_calibration_positions(silent=False)
        try:
            cal.save(self.calibration)
        except OSError as e:
            self.status.setText(f"Save fout: {e}")
            self.status.setStyleSheet("color: red;")
            return
        self.status.setText(f"Kalibratie opgeslagen → {cal.CALIBRATION_PATH}")
        self.status.setStyleSheet("color: green;")

    def _load_calibration(self) -> None:
        self.calibration = cal.load()
        for i in range(3):
            self._refresh_target_label(i)
        self.status.setText(
            f"Kalibratie geladen ({self.calibration.saved_at or 'geen tijd'})."
        )
        self.status.setStyleSheet("color: green;")

    # -----------------------------------------------------------
    #  Lage-niveau schrijf-helpers
    # -----------------------------------------------------------

    def _write(self, cmd: str, ok_msg: str, error_style: bool = False) -> bool:
        if not (self.serial and self.serial.is_open):
            self.status.setText("Niet verbonden.")
            self.status.setStyleSheet("color: red;")
            return False
        try:
            self.serial.write(cmd.encode("ascii"))
            self.serial.flush()
        except serial.SerialException as e:
            self.status.setText(f"Schrijf-fout: {e}")
            self.status.setStyleSheet("color: red;")
            return False
        self.status.setText(ok_msg)
        self.status.setStyleSheet("color: green;" if not error_style else "color: #c0392b;")
        return True

    def _write_raw(self, cmd: str) -> None:
        """Stuur zonder status-update (voor batch-acties)."""
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
    #  Public API voor recording.py: mm-conversie
    # -----------------------------------------------------------

    def mm_per_step(self, motor_index: int) -> float:
        return self.calibration.motors[motor_index].mm_per_step


# -------------------- Moku --------------------

MOKU_DEFAULT_ADDRESS = "192.168.73.1"
MOKU_DEFAULT_TIMEBASE = 10e-3   # halve tijdspan in s (toont -T..+T)


class MokuThread(QThread):
    """Pollt de Moku-oscilloscoop en stuurt frames naar de UI.

    Acquisition-config (frontend, source, timebase) loopt over Qt-signals
    naar de GUI-thread.
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
            self.failed.emit(f"moku-pakket niet geïnstalleerd: {e}")
            return
        try:
            self._osc = Oscilloscope(self.address, force_connect=True)
            self._osc.set_frontend(self.channel, impedance="1MOhm",
                                   coupling=self.coupling, range=self.range_)
            self._osc.set_source(self.channel, f"Input{self.channel}")
            self._osc.set_timebase(-self.timebase, self.timebase)
            self.connected.emit(
                f"Verbonden met {self.address} — Input{self.channel}, "
                f"{self.coupling}, {self.range_}"
            )
        except Exception as e:
            self.failed.emit(f"Verbindingsfout: {e}")
            self._cleanup()
            return

        self._running = True
        ch_key = f"ch{self.channel}"
        try:
            while self._running:
                try:
                    data = self._osc.get_data()
                except Exception as e:
                    self.failed.emit(f"Lees-fout: {e}")
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
    # Per-frame re-emit voor luisteraars (RecordingPanel) — zelfde payload als
    # MokuThread.data_ready, maar uitgezonden vanuit de GUI-thread.
    frame = Signal(object, object)

    def __init__(self) -> None:
        super().__init__("Moku:Go fotodetector")
        self.thread: MokuThread | None = None
        self._timebase = MOKU_DEFAULT_TIMEBASE
        self._burst_dl = None
        self._burst_cfg: tuple[str, int, str, str] | None = None
        self._last_values: object = None  # laatste live-frame, voor Set I0
        self.I0: float | None = None      # baseline-voltage voor V→dz1 conversie

        layout = QVBoxLayout(self)

        controls = QGridLayout()
        controls.addWidget(QLabel("IP:"), 0, 0)
        self.address_input = QLineEdit(MOKU_DEFAULT_ADDRESS)
        self.address_input.setMinimumWidth(140)
        controls.addWidget(self.address_input, 0, 1)

        controls.addWidget(QLabel("Kanaal:"), 0, 2)
        self.channel_combo = QComboBox()
        self.channel_combo.addItems(["1", "2"])
        controls.addWidget(self.channel_combo, 0, 3)

        controls.addWidget(QLabel("Range:"), 0, 4)
        self.range_combo = QComboBox()
        self.range_combo.addItems(["10Vpp", "50Vpp"])
        controls.addWidget(self.range_combo, 0, 5)

        controls.addWidget(QLabel("Coupling:"), 0, 6)
        self.coupling_combo = QComboBox()
        self.coupling_combo.addItems(["DC", "AC"])
        controls.addWidget(self.coupling_combo, 0, 7)

        self.connect_btn = QPushButton("Verbind")
        self.connect_btn.clicked.connect(self._toggle_connect)
        controls.addWidget(self.connect_btn, 0, 8)
        controls.setColumnStretch(1, 1)

        layout.addLayout(controls)

        fig = Figure(figsize=(8, 4))
        self.canvas = FigureCanvas(fig)
        self.canvas.setMinimumHeight(280)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.ax = fig.add_subplot(111)
        self.ax.set_xlabel("tijd (s)")
        self.ax.set_ylabel("spanning (V)")
        self.ax.grid(True)
        self.ax.set_xlim(-self._timebase, self._timebase)
        self.line, = self.ax.plot([], [], lw=1.2)
        fig.tight_layout()
        layout.addWidget(self.canvas, stretch=1)

        self.status = QLabel("Niet verbonden.")
        self.status.setStyleSheet("color: gray;")
        layout.addWidget(self.status)

    def _toggle_connect(self) -> None:
        if self.thread is not None and self.thread.isRunning():
            self._stop_thread()
            self.status.setText("Verbinding gesloten.")
            self.status.setStyleSheet("color: gray;")
            return

        address = self.address_input.text().strip()
        if not address:
            self.status.setText("Geef een IP-adres op.")
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

        self.connect_btn.setText("Bezig...")
        self.connect_btn.setEnabled(False)
        self.status.setText(f"Verbinden met {address} ...")
        self.status.setStyleSheet("color: gray;")

    def _on_connected(self, msg: str) -> None:
        self.connect_btn.setText("Ontkoppel")
        self.connect_btn.setEnabled(True)
        self.status.setText(msg)
        self.status.setStyleSheet("color: green;")

    def _on_data(self, t, values) -> None:
        self.frame.emit(t, values)
        self._last_values = values
        self.line.set_data(t, values)
        self.ax.relim()
        self.ax.autoscale_view(scalex=False, scaley=True)
        self.canvas.draw_idle()

    def set_I0_from_current(self) -> float | None:
        """Snapshot de gemiddelde live-voltage als baseline I0. None als geen data."""
        if self._last_values is None:
            return None
        arr = np.asarray(self._last_values, dtype=float)
        if arr.size == 0:
            return None
        self.I0 = float(np.mean(arr))
        return self.I0

    def clear_I0(self) -> None:
        self.I0 = None

    def _on_failed(self, msg: str) -> None:
        self.status.setText(msg)
        self.status.setStyleSheet("color: red;")
        self.connect_btn.setText("Verbind")
        self.connect_btn.setEnabled(True)

    def _stop_thread(self) -> None:
        if self.thread is not None:
            self.thread.stop()
            self.thread = None
        self.connect_btn.setText("Verbind")
        self.connect_btn.setEnabled(True)

    def close_moku(self) -> None:
        if self._burst_dl is not None:
            try:
                self._burst_dl.close()
            except Exception:
                pass
            self._burst_dl = None
        self._stop_thread()

    # ---------- Burst-mode (Datalogger) ----------
    #
    # Wordt gebruikt door ScanPanel: één keer start_burst_mode aan begin van
    # de scan, daarna acquire_burst per punt, end_burst_mode aan het eind.
    # Tijdens burst-mode draait de live Oscilloscope-grafiek niet.

    def start_burst_mode(self) -> None:
        if self._burst_dl is not None:
            return
        if self.thread is None or not self.thread.isRunning():
            raise RuntimeError("Moku niet verbonden — verbind eerst via 'Verbind'.")

        address = self.address_input.text().strip()
        channel = int(self.channel_combo.currentText())
        coupling = self.coupling_combo.currentText()
        range_ = self.range_combo.currentText()
        self._burst_cfg = (address, channel, coupling, range_)

        self._stop_thread()
        i0_msg = f"I0={self.I0:.4f}V → dz1 (mm)" if self.I0 else "geen I0 — V-fallback"
        self.status.setText(
            f"Burst-mode (Datalogger) — live preview gepauzeerd. [{i0_msg}]"
        )
        self.status.setStyleSheet("color: #b8860b;")

        from datalogger import MokuDatalogger
        self._burst_dl = MokuDatalogger(address, channel, range_, coupling, I0=self.I0)
        try:
            self._burst_dl.open()
        except Exception:
            self._burst_dl = None
            self._restart_preview()
            raise

    def acquire_burst(self, fs: int, T: float) -> np.ndarray:
        if self._burst_dl is None:
            raise RuntimeError("Burst-mode niet actief — roep eerst start_burst_mode().")
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
        self.connect_btn.setText("Bezig...")
        self.connect_btn.setEnabled(False)
        self.status.setText(f"Live preview herstarten op {address} ...")
        self.status.setStyleSheet("color: gray;")


# -------------------- Main window --------------------

# -------------------- Status pill (top-bar component) --------------------

class StatusPill(QWidget):
    """Compacte 'connected/disconnected'-indicator met dot + label + meta-text."""

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
    """Bovenste statusbalk: brand · pills · acties."""

    def __init__(self, motor_panel: "MotorPanel", moku_panel: "MokuPanel",
                 cam_thread: "CameraThread") -> None:
        super().__init__()
        self.motor_panel = motor_panel
        self.moku_panel = moku_panel
        self.cam_thread = cam_thread
        self._camera_seen = False
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

        # Actions: Herstel positie, Help
        self.restore_btn = QPushButton("↺  Herstel positie")
        self.restore_btn.setObjectName("TopBarAction")
        self.restore_btn.setToolTip(
            "Laad de laatste bekende motorpositie uit calibration.yaml\n"
            "en stuur SETPOS naar de Arduino."
        )
        self.restore_btn.clicked.connect(self._restore_positions)
        h.addWidget(self.restore_btn)

        self.help_btn = QPushButton("?")
        self.help_btn.setObjectName("IconButton")
        self.help_btn.setToolTip("Open README.md")
        self.help_btn.clicked.connect(self._show_help)
        h.addWidget(self.help_btn)

        # Camera detect: pas connected zodra eerste frame binnen is
        self.cam_thread.frame_ready.connect(self._on_first_camera_frame)

        # Polling-timer voor motor/moku (geen wijzigingen aan bestaande klassen)
        self._poll = QTimer(self)
        self._poll.setInterval(500)
        self._poll.timeout.connect(self._refresh_pills)
        self._poll.start()
        self._refresh_pills()

    def _on_first_camera_frame(self, _frame) -> None:
        if not self._camera_seen:
            self._camera_seen = True
            self.camera_pill.set_state(True, f"USB{CAMERA_INDEX}")

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
        # Camera (sticky once seen)
        if not self._camera_seen:
            self.camera_pill.set_state(False, f"USB{CAMERA_INDEX}")

    def _restore_positions(self) -> None:
        mp = self.motor_panel
        if not (mp.serial and mp.serial.is_open):
            QMessageBox.warning(self, "Niet verbonden",
                                "Verbind eerst met de Arduino via de Setup-tab.")
            return
        # Herlaad altijd van schijf — in-memory kan verouderd zijn
        mp.calibration = cal.load()
        if not mp.calibration.any_known_position():
            QMessageBox.information(self, "Herstel positie",
                                    "Geen opgeslagen positie gevonden in calibration.yaml.")
            return
        expected = tuple(m.last_position for m in mp.calibration.motors)
        msg = (
            f"Zet motorposities terug naar de opgeslagen waarden:\n\n"
            f"  Motor 1 ({AXIS_NAMES[0]}-as): {expected[0]} stappen\n"
            f"  Motor 2 ({AXIS_NAMES[1]}-as): {expected[1]} stappen\n"
            f"  Motor 3 ({AXIS_NAMES[2]}-as): {expected[2]} stappen\n\n"
            "Dit stuurt SETPOS naar de Arduino zonder de motoren te bewegen.\n"
            "Alleen doen als de motoren fysiek niet zijn verplaatst."
        )
        reply = QMessageBox.question(self, "Herstel positie?", msg,
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            for i, p in enumerate(expected):
                mp._write_raw(f"SETPOS {i + 1} {p}\n")
                mp.targets[i] = p
                mp._refresh_target_label(i)
            cal.save(mp.calibration)
            mp.status.setText("Kalibratie hersteld — posities teruggezet via SETPOS.")
            mp.status.setStyleSheet("color: green;")

    def _show_help(self) -> None:
        import os
        from pathlib import Path
        readme = Path(__file__).parent / "README.md"
        if readme.exists():
            os.startfile(str(readme))
        else:
            QMessageBox.information(self, "Help", "README.md niet gevonden.")


# -------------------- Camera card (wrapt CameraPanel met titel-rij) --------------------

class CameraCard(QFrame):
    """Cosmetische wrapper rond CameraPanel — toont 'Camera' titel + LIVE-badge."""

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
        sub = QLabel(f"USB{CAMERA_INDEX}")
        sub.setProperty("role", "subtitle")
        header.addWidget(title)
        header.addSpacing(8)
        header.addWidget(sub)
        header.addStretch(1)

        live = QLabel("● LIVE")
        live.setStyleSheet(
            "color: #ef4444; font-weight: 600;"
            " font-family: 'Inter', system-ui, sans-serif;"
            " font-size: 11px; letter-spacing: 1px;"
            " background-color: rgba(239,68,68,0.1);"
            " border: 1px solid rgba(239,68,68,0.3);"
            " border-radius: 4px; padding: 2px 8px;"
        )
        header.addWidget(live)

        v.addLayout(header)
        v.addWidget(camera_panel, stretch=1)


# -------------------- Main window --------------------

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Bep-Project · Confocal")
        self.resize(1400, 900)

        # ---- panels (functioneel ongewijzigd) ----
        self.camera_panel = CameraPanel()
        self.motor_panel = MotorPanel()
        self.lamp_panel = LampPanel(
            get_serial=lambda: self.motor_panel.serial,
            title="Lamp binnen (WS2812B-8, pin A2)",
            command="LAMP",
        )
        self.lamp_panel_buiten = LampPanel(
            get_serial=lambda: self.motor_panel.serial,
            title="Lamp buiten (WS2812B-8, pin A3)",
            command="LAMP2",
        )
        self.moku_panel = MokuPanel()
        self.recording_panel = RecordingPanel(
            moku_panel=self.moku_panel,
            motor_panel=self.motor_panel,
            lamp_panel=self.lamp_panel,
        )
        self.scan_panel = ScanPanel(
            motor_panel=self.motor_panel,
            lamp_panel=self.lamp_panel,
            moku_panel=self.moku_panel,
        )

        # ---- camera-thread ----
        self.cam_thread = CameraThread()
        self.cam_thread.frame_ready.connect(self.camera_panel.update_frame)
        self.cam_thread.start()

        # Camera-instellingen tab (heeft thread nodig voor set_property)
        self.camera_settings_panel = CameraSettingsPanel(self.cam_thread)

        # ---- top bar ----
        self.top_bar = TopBar(
            motor_panel=self.motor_panel,
            moku_panel=self.moku_panel,
            cam_thread=self.cam_thread,
        )

        # ---- camera card (links) ----
        self.camera_card = CameraCard(self.camera_panel)

        # ---- sidebar (rechts) = tabs + altijd-zichtbare lamp ----
        # Onderdruk redundante QGroupBox-titel — de tab-naam volstaat al
        for panel in (self.recording_panel, self.scan_panel,
                      self.motor_panel, self.camera_settings_panel):
            panel.setTitle("")
            panel.setProperty("inTab", True)
            panel.style().unpolish(panel)
            panel.style().polish(panel)

        # Camera-tab = instellingen + beide lamp-panelen (de lamp verlicht het
        # camerabeeld, dus hoort de bediening logisch bij de Camera-tab)
        camera_tab = QWidget()
        camera_tab_v = QVBoxLayout(camera_tab)
        camera_tab_v.setContentsMargins(0, 0, 0, 0)
        camera_tab_v.setSpacing(12)
        camera_tab_v.addWidget(self.camera_settings_panel)
        camera_tab_v.addWidget(self.lamp_panel)
        camera_tab_v.addWidget(self.lamp_panel_buiten)
        camera_tab_v.addStretch(1)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self.recording_panel, "Manual")
        self.tabs.addTab(self.scan_panel, "Auto Scan")
        self.tabs.addTab(self.motor_panel, "Setup")
        self.tabs.addTab(camera_tab, "Camera")
        self.tabs.setCurrentIndex(2)  # start in Setup om eerst te kunnen verbinden

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
        self.moku_panel.setMinimumHeight(380)
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
        root_v.addWidget(body, stretch=1)

        self.setCentralWidget(root)

    def closeEvent(self, event) -> None:
        self.scan_panel.cancel_if_running()
        self.recording_panel.close_recording()
        self.cam_thread.stop()
        self.motor_panel.close_serial()
        self.moku_panel.close_moku()
        super().closeEvent(event)


# -------------------- App entry --------------------

def _load_fonts() -> None:
    """Registreer gebundelde Inter-fonts (otf/ttf) zodat QSS ze kan gebruiken."""
    from pathlib import Path
    fonts_dir = Path(__file__).parent / "fonts"
    if not fonts_dir.exists():
        return
    for pattern in ("*.otf", "*.ttf"):
        for font_file in fonts_dir.glob(pattern):
            QFontDatabase.addApplicationFont(str(font_file))


def _load_stylesheet(app: QApplication) -> None:
    """Laad styles.qss als hij naast ui.py bestaat. Stilte als ontbrekend."""
    try:
        from pathlib import Path
        qss_path = Path(__file__).parent / "styles.qss"
        if qss_path.exists():
            app.setStyleSheet(qss_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Kon styles.qss niet laden: {e}")


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Bep-Project")
    _load_fonts()
    _load_stylesheet(app)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
