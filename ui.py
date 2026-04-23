"""Geintegreerde UI voor Bep-Project.

- Linksboven: live USB-camera (zelfde capture als camera.py, index 1)
- Rechtsboven: 3 sliders (0..2048) voor de stepper motors, via COM3 naar de
  Arduino Nano. Commando-formaat: "p1,p2,p3\\n" (zoals de firmware verwacht).
- Onder: Moku:Go placeholder (komt later in de plaats van moku_live.py).

Afhankelijkheden:
    pip install PySide6 pyserial opencv-python matplotlib
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


CAMERA_INDEX = 1
DEFAULT_PORT = "COM3"
BAUD = 9600
MAX_STEPS = 2048


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

        self.step_inputs: list[QSpinBox] = []
        self.target_labels: list[QLabel] = []
        for i in range(3):
            layout.addWidget(QLabel(f"Motor {i + 1}"), i + 1, 0)

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
            layout.addWidget(arrows, i + 1, 1)

            spin = QSpinBox()
            spin.setRange(10, MAX_STEPS)
            spin.setSingleStep(10)
            spin.setValue(1000)
            spin.setSuffix(" stappen")
            spin.setFixedWidth(130)
            layout.addWidget(spin, i + 1, 2)

            tlbl = QLabel("target: 0")
            tlbl.setStyleSheet("color: gray;")
            layout.addWidget(tlbl, i + 1, 3)

            self.step_inputs.append(spin)
            self.target_labels.append(tlbl)

        self.stop_btn = QPushButton("STOP  ■  alle motoren direct stoppen")
        self.stop_btn.setStyleSheet(
            "QPushButton { background-color: #c0392b; color: white;"
            " font-weight: bold; padding: 10px; font-size: 14px; }"
            "QPushButton:pressed { background-color: #922b21; }"
        )
        self.stop_btn.clicked.connect(self._stop_all)
        layout.addWidget(self.stop_btn, 4, 0, 1, 4)

        self.status = QLabel("Niet verbonden.")
        self.status.setStyleSheet("color: gray;")
        layout.addWidget(self.status, 5, 0, 1, 4)

        layout.setRowStretch(6, 1)

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

    def _jog(self, motor_index: int, direction: int) -> None:
        step_count = self.step_inputs[motor_index].value()
        self.targets[motor_index] += direction * step_count
        target = self.targets[motor_index]
        self.target_labels[motor_index].setText(f"target: {target}")
        cmd = f"{motor_index + 1} {target}\n"
        self._write(cmd, ok_msg=f"Verzonden: {cmd.strip()}")

    def _stop_all(self) -> None:
        if not self._write("STOP\n", ok_msg="STOP verzonden.", error_style=True):
            return
        for i, lbl in enumerate(self.target_labels):
            self.targets[i] = 0
            lbl.setText("target: 0")
        self.status.setStyleSheet("color: #c0392b; font-weight: bold;")

    def _write(self, cmd: str, ok_msg: str, error_style: bool = False) -> bool:
        if not (self.serial and self.serial.is_open):
            self.status.setText("Niet verbonden.")
            self.status.setStyleSheet("color: red;")
            return False
        try:
            self.serial.write(cmd.encode("ascii"))
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


# -------------------- Moku placeholder --------------------

class MokuPlaceholder(QGroupBox):
    def __init__(self) -> None:
        super().__init__("Moku:Go data (placeholder)")
        layout = QVBoxLayout(self)
        fig = Figure(figsize=(8, 3))
        self.canvas = FigureCanvas(fig)
        ax = fig.add_subplot(111)
        ax.set_xlabel("tijd (s)")
        ax.set_ylabel("spanning (V)")
        ax.grid(True)
        ax.text(
            0.5, 0.5,
            "Moku:Go integratie volgt — hier komt de live-plot uit moku_live.py",
            ha="center", va="center", transform=ax.transAxes,
            fontsize=11, color="gray",
        )
        fig.tight_layout()
        layout.addWidget(self.canvas)


# -------------------- Main window --------------------

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Bep-Project UI")
        self.resize(1200, 800)

        self.camera_panel = CameraPanel()
        self.motor_panel = MotorPanel()
        self.moku_panel = MokuPlaceholder()

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
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
