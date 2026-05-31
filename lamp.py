# SPDX-License-Identifier: MIT

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
    def __init__(
        self,
        get_serial: Callable[[], Optional[serial.Serial]],
        title: str = "Lamp (WS2812B-8, pin A2/D16)",
        command: str = "LAMP",
    ) -> None:
        super().__init__(title)
        self.setProperty("compact", True)               # strakkere QSS-padding
        self._get_serial = get_serial
        self._command = command                          # "LAMP" (binnen) of "LAMP2" (buiten)
        self._last_sent: int = -1                       # forceert eerste send
        self._pending: int = DEFAULT_BRIGHTNESS
        self._previous_on_value: int = 128              # toggle-AAN gebruikt deze

        self._throttle = QTimer(self)
        self._throttle.setSingleShot(True)
        self._throttle.setInterval(THROTTLE_MS)
        self._throttle.timeout.connect(self._flush)

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setVerticalSpacing(8)
        layout.setHorizontalSpacing(8)

        layout.addWidget(QLabel("Helderheid:"), 0, 0)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(LAMP_MIN, LAMP_MAX)
        self.slider.setValue(DEFAULT_BRIGHTNESS)
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
        self.toggle_btn.setFixedHeight(24)
        self.toggle_btn.clicked.connect(self._toggle_on_off)
        layout.addWidget(self.toggle_btn, 1, 0, 1, 4)

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

    # ---- serial -----------------------------------------------------

    def _send(self, brightness: int) -> bool:
        ser = self._get_serial()
        if ser is None or not ser.is_open:
            return False
        try:
            ser.write(f"{self._command} {brightness}\n".encode("ascii"))
            ser.flush()
        except serial.SerialException:
            return False
        return True
