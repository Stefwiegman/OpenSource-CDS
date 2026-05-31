# SPDX-License-Identifier: MIT

"""Camera-instellingen panel — past helderheid/contrast/belichting aan via OpenCV.

OpenCV CAP_PROP_*-constanten worden hardcoded zodat dit bestand cv2 zelf niet hoeft te
importeren. De CameraThread accepteert wijzigingen via een thread-safe set_property().

DirectShow-quirks (Windows):
  - CAP_PROP_AUTO_EXPOSURE: 0.25 = manual, 0.75 = auto
  - CAP_PROP_EXPOSURE: log2(seconden); -6 = ~16ms, -13 = ~120µs

Zwart-wit is een software-conversie in CameraThread (BGR→GRAY→BGR), niet via
CAP_PROP_SATURATION — werkt zo betrouwbaar op elke webcam.
"""
from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSlider,
)


# OpenCV CAP_PROP_* — integer-waarden zijn stabiel over cv2-versies
CAP_PROP_BRIGHTNESS = 10
CAP_PROP_CONTRAST = 11
CAP_PROP_EXPOSURE = 15
CAP_PROP_AUTO_EXPOSURE = 21


# (label, prop_id, min, max, default, tooltip)
SLIDERS = [
    ("Belichting", CAP_PROP_EXPOSURE, -13, 0, -9,
     "Belichtingstijd in log2 seconden (-9 ≈ 2ms, -6 ≈ 16ms, -13 ≈ 120µs). "
     "Werkt alleen met Auto-belichting UIT. Lab-licht klipt snel boven -8."),
    ("Helderheid", CAP_PROP_BRIGHTNESS, 0, 255, 128,
     "Digitale helderheids-offset (post-sensor). 128 = neutraal."),
    ("Contrast", CAP_PROP_CONTRAST, 0, 255, 128,
     "Spreidt grijswaarden uit rond het midden."),
]


class _SupportsCamera(Protocol):
    def set_property(self, prop_id: int, value: float) -> None: ...
    def set_grayscale(self, on: bool) -> None: ...


_DEBOUNCE_MS = 150


class CameraSettingsPanel(QGroupBox):
    """Tab-paneel met sliders voor de meest-gebruikte OpenCV camera-properties."""

    def __init__(self, camera_thread: _SupportsCamera) -> None:
        super().__init__("Camera-instellingen")
        self.camera_thread = camera_thread
        self._sliders: list[QSlider] = []
        self._value_labels: list[QLabel] = []
        # Debounce-state: slider-bewegingen verzamelen we hier, en pas wanneer
        # de gebruiker ~_DEBOUNCE_MS niks doet pushen we naar de cap-thread.
        # Zo voorkomen we dat DirectShow tientallen cap.set() calls per sec krijgt.
        self._pending_values: dict[int, float] = {}
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(_DEBOUNCE_MS)
        self._debounce_timer.timeout.connect(self._flush_pending)
        self._build_ui()
        # Defaults pas ~500ms na app-start naar de cap pushen — geeft thread
        # tijd om VideoCapture te openen
        QTimer.singleShot(500, self._apply_initial)

    def _build_ui(self) -> None:
        layout = QGridLayout(self)
        layout.setVerticalSpacing(12)
        layout.setHorizontalSpacing(10)
        r = 0

        # Toggles bovenaan — Auto-belichting + Zwart-wit
        self.auto_exp_cb = QCheckBox("Auto-belichting")
        self.auto_exp_cb.setToolTip(
            "AAN = camera regelt belichting zelf (aanbevolen voor wisselend "
            "lab-licht). UIT = handmatige Belichting-slider werkt."
        )
        self.auto_exp_cb.setChecked(True)  # default auto — consistent met AUTO_WB/AUTOFOCUS
        self.auto_exp_cb.toggled.connect(self._on_auto_exposure)
        layout.addWidget(self.auto_exp_cb, r, 0, 1, 3)
        r += 1

        self.bw_cb = QCheckBox("Zwart-wit beeld")
        self.bw_cb.setToolTip(
            "AAN = live beeld in grayscale (software-conversie). "
            "Beïnvloedt scan-recording niet, alleen de preview."
        )
        self.bw_cb.toggled.connect(self._on_grayscale)
        layout.addWidget(self.bw_cb, r, 0, 1, 3)
        r += 1

        # Sliders per property
        for label, prop_id, min_v, max_v, default, tooltip in SLIDERS:
            lbl = QLabel(label)
            lbl.setMinimumWidth(90)
            lbl.setToolTip(tooltip)
            layout.addWidget(lbl, r, 0)

            slider = QSlider(Qt.Horizontal)
            slider.setRange(min_v, max_v)
            slider.setValue(default)
            slider.setProperty("prop_id", prop_id)
            slider.setToolTip(tooltip)
            slider.valueChanged.connect(self._on_slider_change)
            layout.addWidget(slider, r, 1)

            val_lbl = QLabel(str(default))
            val_lbl.setMinimumWidth(50)
            val_lbl.setProperty("role", "value")
            layout.addWidget(val_lbl, r, 2)

            self._sliders.append(slider)
            self._value_labels.append(val_lbl)
            r += 1

        # Belichting-slider start uitgeschakeld omdat auto-belichting default AAN is
        self._set_exposure_slider_enabled(False)

        # Reset-knop
        reset_btn = QPushButton("↺ Reset naar defaults")
        reset_btn.setToolTip("Zet alle sliders terug naar hun start-waarde")
        reset_btn.clicked.connect(self._reset_all)
        layout.addWidget(reset_btn, r, 0, 1, 3)
        r += 1

        layout.setColumnStretch(1, 1)
        layout.setRowStretch(r, 1)

    # ---- camera-sync -----------------------------------------------

    def _apply_initial(self) -> None:
        """Push initiële slider-waarden naar de camera-thread."""
        # Default: auto-belichting AAN (DirectShow: 0.75 = auto, 0.25 = manual)
        self.camera_thread.set_property(CAP_PROP_AUTO_EXPOSURE, 0.75)
        for slider in self._sliders:
            prop_id = int(slider.property("prop_id"))
            self.camera_thread.set_property(prop_id, float(slider.value()))

    def _on_slider_change(self, value: int) -> None:
        slider = self.sender()
        if slider is None:
            return
        prop_id = int(slider.property("prop_id"))
        idx = self._sliders.index(slider)
        # Label direct updaten (gratis); cap.set() debouncen
        self._value_labels[idx].setText(str(value))
        self._pending_values[prop_id] = float(value)
        self._debounce_timer.start()  # restart countdown

    def _flush_pending(self) -> None:
        """Push opgespaarde slider-waarden in één batch naar de camera-thread."""
        pending = self._pending_values
        self._pending_values = {}
        for prop_id, value in pending.items():
            self.camera_thread.set_property(prop_id, value)

    def _on_grayscale(self, on: bool) -> None:
        self.camera_thread.set_grayscale(on)

    def _on_auto_exposure(self, on: bool) -> None:
        # Toggle is een one-off action → direct pushen, geen debounce nodig.
        # DirectShow: 0.75 = auto, 0.25 = manual.
        self.camera_thread.set_property(CAP_PROP_AUTO_EXPOSURE, 0.75 if on else 0.25)
        self._set_exposure_slider_enabled(not on)
        # Als gebruiker net naar manual switcht, push direct de huidige slider-waarde
        # zodat de cam meteen de manual exposure pakt i.p.v. zijn interne fallback.
        if not on:
            for slider in self._sliders:
                if int(slider.property("prop_id")) == CAP_PROP_EXPOSURE:
                    self.camera_thread.set_property(CAP_PROP_EXPOSURE, float(slider.value()))
                    break

    def _set_exposure_slider_enabled(self, enabled: bool) -> None:
        for slider in self._sliders:
            if int(slider.property("prop_id")) == CAP_PROP_EXPOSURE:
                slider.setEnabled(enabled)
                break

    def _reset_all(self) -> None:
        for label, prop_id, _, _, default, _ in SLIDERS:
            for slider in self._sliders:
                if int(slider.property("prop_id")) == prop_id:
                    slider.setValue(default)  # triggert _on_slider_change
                    break
        self.bw_cb.setChecked(False)
        self.auto_exp_cb.setChecked(True)  # reset naar auto-belichting AAN
