"""Bediening van de WCMCU-2812B-8 (WS2812B, 8 pixels) via de Arduino Nano.

De firmware ontvangt ASCII-commando's:
    LAMP <0-255>\n   -> zet helderheid (0 = uit, 255 = vol)

We delen de serial-verbinding van MotorPanel via dependency injection
(get_serial callback), zodat er maar een proces de COM-poort claimt.
"""
from __future__ import annotations

from typing import Callable, Optional

import serial

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QGroupBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
)


LAMP_MIN = 0
LAMP_MAX = 255
THROTTLE_MS = 50          # max ~20 updates/s naar de Arduino
DEFAULT_BRIGHTNESS = 0


class LampPanel(QGroupBox):
    def __init__(self, get_serial: Callable[[], Optional[serial.Serial]]) -> None:
        super().__init__("Lamp (WS2812B-8, pin A2/D16)")
        self._get_serial = get_serial
        self._last_sent: int = -1                       # forceert eerste send
        self._pending: int = DEFAULT_BRIGHTNESS
        self._previous_on_value: int = 128              # toggle-AAN gebruikt deze

        self._throttle = QTimer(self)
        self._throttle.setSingleShot(True)
        self._throttle.setInterval(THROTTLE_MS)
        self._throttle.timeout.connect(self._flush)

        layout = QGridLayout(self)

        layout.addWidget(QLabel("Helderheid:"), 0, 0)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(LAMP_MIN, LAMP_MAX)
        self.slider.setValue(DEFAULT_BRIGHTNESS)
        self.slider.setTickPosition(QSlider.TicksBelow)
        self.slider.setTickInterval(32)
        self.slider.valueChanged.connect(self._on_slider_change)
        layout.addWidget(self.slider, 0, 1, 1, 2)

        self.spin = QSpinBox()
        self.spin.setRange(LAMP_MIN, LAMP_MAX)
        self.spin.setValue(DEFAULT_BRIGHTNESS)
        self.spin.setFixedWidth(70)
        self.spin.valueChanged.connect(self.slider.setValue)
        self.slider.valueChanged.connect(self.spin.setValue)
        layout.addWidget(self.spin, 0, 3)

        self.toggle_btn = QPushButton("AAN")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.clicked.connect(self._toggle_on_off)
        layout.addWidget(self.toggle_btn, 1, 0, 1, 2)

        self.off_btn = QPushButton("UIT")
        self.off_btn.setToolTip("Forceer lamp direct uit (LAMP 0)")
        self.off_btn.clicked.connect(self._force_off)
        layout.addWidget(self.off_btn, 1, 2, 1, 2)

        self.status = QLabel("Niet verbonden (verbind eerst de motoren).")
        self.status.setProperty("role", "status")
        layout.addWidget(self.status, 2, 0, 1, 4)

        layout.setColumnStretch(1, 1)

    # ---- slider/throttle plumbing ----------------------------------

    def _on_slider_change(self, value: int) -> None:
        """Single source of truth — toggle-state + tekst worden hier gesynct."""
        self._pending = value
        if not self._throttle.isActive():
            self._throttle.start()
        if value > 0:
            self._previous_on_value = value
            self.toggle_btn.setChecked(True)
            self.toggle_btn.setText("UIT")
        else:
            self.toggle_btn.setChecked(False)
            self.toggle_btn.setText("AAN")

    def _flush(self) -> None:
        if self._pending == self._last_sent:
            return
        if self._send(self._pending):
            self._last_sent = self._pending

    # ---- knop-acties ------------------------------------------------

    def _toggle_on_off(self, checked: bool) -> None:
        """Toggle-knop: aan = vorige waarde (of 128), uit = 0. State-sync via slider."""
        if checked:
            target = self._previous_on_value or 128
            self.slider.setValue(target)
        else:
            self.slider.setValue(0)

    def _force_off(self) -> None:
        """Expliciete UIT-knop: stuur direct LAMP 0 zonder throttle."""
        self.slider.setValue(0)
        # Bypass throttle voor onmiddellijke respons
        if self._send(0):
            self._last_sent = 0
            self._pending = 0
            self._throttle.stop()

    # ---- serial -----------------------------------------------------

    def _send(self, brightness: int) -> bool:
        ser = self._get_serial()
        if ser is None or not ser.is_open:
            self.status.setText("Niet verbonden (verbind eerst de motoren).")
            self.status.setStyleSheet("color: red;")
            return False
        try:
            ser.write(f"LAMP {brightness}\n".encode("ascii"))
            ser.flush()
        except serial.SerialException as e:
            self.status.setText(f"Schrijf-fout: {e}")
            self.status.setStyleSheet("color: red;")
            return False
        self.status.setText(f"Helderheid = {brightness} / 255")
        self.status.setStyleSheet("color: green;")
        return True
