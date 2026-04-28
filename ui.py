"""Geintegreerde UI voor Bep-Project.

- Linksboven: live USB-camera (zelfde capture als camera.py, index 1)
- Rechtsboven: 3 sliders (0..2048) voor de stepper motors, via COM3 naar de
  Arduino Nano. Commando-formaat: "p1,p2,p3\\n" (zoals de firmware verwacht).
- Onder: Moku:Go live fotodetector-plot (zelfde acquisitie-config als
  moku_live.py, maar embedded i.p.v. eigen window).

Afhankelijkheden:
    pip install PySide6 pyserial opencv-python matplotlib moku
"""
from __future__ import annotations

import sys

import cv2
import numpy as np
import serial
import serial.tools.list_ports

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


CAMERA_INDEX = 0
DEFAULT_PORT = "COM3"
BAUD = 9600
MAX_STEPS = 4096
DEFAULT_SPEED = 500   # AccelStepper setMaxSpeed (steps/s)
MAX_SPEED = 2000


# -------------------- Camera --------------------

class CameraThread(QThread):
    frame_ready = Signal(np.ndarray)

    def __init__(self, index: int = CAMERA_INDEX) -> None:
        super().__init__()
        self._index = index
        self._running = False

    def run(self) -> None:
        cap = cv2.VideoCapture(self._index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            self.frame_ready.emit(
                np.zeros((360, 480, 3), dtype=np.uint8)
            )
            print(f"Kan camera met index {self._index} niet openen.")
            return
        self._running = True
        try:
            while self._running:
                ok, frame = cap.read()
                if not ok:
                    continue
                self.frame_ready.emit(frame)
        finally:
            cap.release()

    def stop(self) -> None:
        self._running = False
        self.wait()


class CameraPanel(QLabel):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(480, 360)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background-color: black; color: white;")
        self.setText("Camera laden...")

    def update_frame(self, frame: np.ndarray) -> None:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()
        pix = QPixmap.fromImage(qimg).scaled(
            self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.setPixmap(pix)


# -------------------- Motors --------------------

class MotorPanel(QGroupBox):
    def __init__(self, default_port: str = DEFAULT_PORT) -> None:
        super().__init__("Stepper motors (Arduino Nano)")
        self.serial: serial.Serial | None = None
        self.default_port = default_port
        self.targets: list[int] = [0, 0, 0]

        layout = QGridLayout(self)

        layout.addWidget(QLabel("Poort:"), 0, 0)
        self.port_combo = QComboBox()
        self._populate_ports()
        layout.addWidget(self.port_combo, 0, 1, 1, 2)
        self.connect_btn = QPushButton("Verbind")
        self.connect_btn.clicked.connect(self._toggle_connect)
        layout.addWidget(self.connect_btn, 0, 3)

        layout.addWidget(QLabel("Snelheid:"), 1, 0)
        self.speed_input = QSpinBox()
        self.speed_input.setRange(10, MAX_SPEED)
        self.speed_input.setSingleStep(50)
        self.speed_input.setValue(DEFAULT_SPEED)
        self.speed_input.setSuffix(" stappen/s")
        layout.addWidget(self.speed_input, 1, 1, 1, 2)
        self.speed_btn = QPushButton("Stuur")
        self.speed_btn.clicked.connect(self._send_speed)
        layout.addWidget(self.speed_btn, 1, 3)

        self.step_inputs: list[QSpinBox] = []
        self.target_labels: list[QLabel] = []
        for i in range(3):
            layout.addWidget(QLabel(f"Motor {i + 1}"), i + 2, 0)

            arrows = QWidget()
            arrows_layout = QVBoxLayout(arrows)
            arrows_layout.setContentsMargins(0, 0, 0, 0)
            arrows_layout.setSpacing(2)
            up_btn = QPushButton("↑")
            up_btn.setFixedWidth(40)
            up_btn.clicked.connect(lambda _c, n=i: self._jog(n, +1))
            down_btn = QPushButton("↓")
            down_btn.setFixedWidth(40)
            down_btn.clicked.connect(lambda _c, n=i: self._jog(n, -1))
            arrows_layout.addWidget(up_btn)
            arrows_layout.addWidget(down_btn)
            layout.addWidget(arrows, i + 2, 1)

            spin = QSpinBox()
            spin.setRange(10, MAX_STEPS)
            spin.setSingleStep(10)
            spin.setValue(1000)
            spin.setSuffix(" stappen")
            spin.setFixedWidth(130)
            layout.addWidget(spin, i + 2, 2)

            tlbl = QLabel("target: 0")
            tlbl.setStyleSheet("color: gray;")
            layout.addWidget(tlbl, i + 2, 3)

            self.step_inputs.append(spin)
            self.target_labels.append(tlbl)

        self.stop_btn = QPushButton("STOP  ■  alle motoren direct stoppen")
        self.stop_btn.setStyleSheet(
            "QPushButton { background-color: #c0392b; color: white;"
            " font-weight: bold; padding: 10px; font-size: 14px; }"
            "QPushButton:pressed { background-color: #922b21; }"
        )
        self.stop_btn.clicked.connect(self._stop_all)
        layout.addWidget(self.stop_btn, 5, 0, 1, 4)

        self.status = QLabel("Niet verbonden.")
        self.status.setStyleSheet("color: gray;")
        layout.addWidget(self.status, 6, 0, 1, 4)

        layout.setRowStretch(7, 1)

    def _populate_ports(self) -> None:
        self.port_combo.clear()
        ports = [p.device for p in serial.tools.list_ports.comports()]
        if self.default_port not in ports:
            ports.insert(0, self.default_port)
        self.port_combo.addItems(ports)
        self.port_combo.setCurrentText(self.default_port)

    def _toggle_connect(self) -> None:
        if self.serial and self.serial.is_open:
            self.serial.close()
            self.serial = None
            self.connect_btn.setText("Verbind")
            self.status.setText("Verbinding gesloten.")
            self.status.setStyleSheet("color: gray;")
            return
        port = self.port_combo.currentText()
        try:
            self.serial = serial.Serial(port, BAUD, timeout=1)
        except serial.SerialException as e:
            QMessageBox.critical(self, "Serial fout", f"Kan {port} niet openen:\n{e}")
            self.serial = None
            return
        self.connect_btn.setText("Ontkoppel")
        self.status.setText(f"Verbonden met {port} @ {BAUD} baud.")
        self.status.setStyleSheet("color: green;")
        self._send_speed()

    def _send_speed(self) -> None:
        speed = self.speed_input.value()
        cmd = f"SPEED {speed}\n"
        self._write(cmd, ok_msg=f"Snelheid gezet op {speed} stappen/s.")

    def _jog(self, motor_index: int, direction: int) -> None:
        step_count = self.step_inputs[motor_index].value()
        self.targets[motor_index] += direction * step_count
        target = self.targets[motor_index]
        self.target_labels[motor_index].setText(f"target: {target}")
        cmd = f"{motor_index + 1} {target}\n"
        self._write(cmd, ok_msg=f"Verzonden: {cmd.strip()}")

    def _stop_all(self) -> None:
        if not (self.serial and self.serial.is_open):
            self.status.setText("Niet verbonden.")
            self.status.setStyleSheet("color: red;")
            return
        try:
            # Drop pending jog commands so STOP isn't queued behind them.
            self.serial.reset_output_buffer()
            self.serial.write(b"STOP\n")
            self.serial.flush()
        except serial.SerialException as e:
            self.status.setText(f"Schrijf-fout: {e}")
            self.status.setStyleSheet("color: red;")
            return
        # Position is unknown after an emergency stop — don't claim it's 0.
        for i, lbl in enumerate(self.target_labels):
            self.targets[i] = 0
            lbl.setText("target: ? (gestopt)")
        self.status.setText("STOP verzonden — motoren gestopt op onbekende positie.")
        self.status.setStyleSheet("color: #c0392b; font-weight: bold;")

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

    def close_serial(self) -> None:
        if self.serial and self.serial.is_open:
            self.serial.close()


# -------------------- Moku --------------------

MOKU_DEFAULT_ADDRESS = "192.168.73.1"
MOKU_DEFAULT_TIMEBASE = 10e-3   # halve tijdspan in s (toont -T..+T)


class MokuThread(QThread):
    """Pollt de Moku-oscilloscoop en stuurt frames naar de UI.

    Acquisition-config (frontend, source, timebase) is identiek aan
    `moku_live.py`, alleen op een ander transport (Qt-signals i.p.v.
    matplotlib FuncAnimation).
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
    def __init__(self) -> None:
        super().__init__("Moku:Go fotodetector")
        self.thread: MokuThread | None = None
        self._timebase = MOKU_DEFAULT_TIMEBASE

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

        fig = Figure(figsize=(8, 3))
        self.canvas = FigureCanvas(fig)
        self.ax = fig.add_subplot(111)
        self.ax.set_xlabel("tijd (s)")
        self.ax.set_ylabel("spanning (V)")
        self.ax.grid(True)
        self.ax.set_xlim(-self._timebase, self._timebase)
        self.line, = self.ax.plot([], [], lw=1.2)
        fig.tight_layout()
        layout.addWidget(self.canvas)

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
        self.line.set_data(t, values)
        self.ax.relim()
        self.ax.autoscale_view(scalex=False, scaley=True)
        self.canvas.draw_idle()

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
        self._stop_thread()


# -------------------- Main window --------------------

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Bep-Project UI")
        self.resize(1200, 800)

        self.camera_panel = CameraPanel()
        self.motor_panel = MotorPanel()
        self.moku_panel = MokuPanel()

        for w in (self.camera_panel, self.motor_panel, self.moku_panel):
            w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        top_splitter = QSplitter(Qt.Horizontal)
        top_splitter.addWidget(self.camera_panel)
        top_splitter.addWidget(self.motor_panel)
        top_splitter.setStretchFactor(0, 2)
        top_splitter.setStretchFactor(1, 1)
        top_splitter.setSizes([800, 400])

        main_splitter = QSplitter(Qt.Vertical)
        main_splitter.addWidget(top_splitter)
        main_splitter.addWidget(self.moku_panel)
        main_splitter.setStretchFactor(0, 2)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setSizes([520, 260])
        main_splitter.setChildrenCollapsible(False)
        top_splitter.setChildrenCollapsible(False)

        self.setCentralWidget(main_splitter)

        self.cam_thread = CameraThread()
        self.cam_thread.frame_ready.connect(self.camera_panel.update_frame)
        self.cam_thread.start()

    def closeEvent(self, event) -> None:
        self.cam_thread.stop()
        self.motor_panel.close_serial()
        self.moku_panel.close_moku()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
