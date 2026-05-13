"""Camera-instellingen panel — past contrast/helderheid/scherpte/belichting aan via OpenCV.

OpenCV CAP_PROP_*-constanten worden hardcoded zodat dit bestand cv2 zelf niet hoeft te
importeren. De CameraThread accepteert wijzigingen via een thread-safe set_property().

DirectShow-quirks (Windows):
  - CAP_PROP_AUTO_EXPOSURE: 0.25 = manual, 0.75 = auto
  - CAP_PROP_EXPOSURE: log2(seconden); -6 = ~16ms, -13 = ~120µs
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
CAP_PROP_SATURATION = 12
CAP_PROP_GAIN = 14
CAP_PROP_EXPOSURE = 15
CAP_PROP_SHARPNESS = 20
CAP_PROP_AUTO_EXPOSURE = 21
CAP_PROP_GAMMA = 22


# (label, prop_id, min, max, default, tooltip)
SLIDERS = [
    ("Belichting", CAP_PROP_EXPOSURE, -13, 0, -6,
     "Belichtingstijd in log2 seconden (-6 ≈ 16ms, -13 ≈ 120µs). "
     "Hoger = langer belicht = helderder. Werkt alleen met Auto-belichting UIT."),
    ("Helderheid", CAP_PROP_BRIGHTNESS, 0, 255, 128,
     "Digitale helderheids-offset (post-sensor). 128 = neutraal."),
    ("Contrast", CAP_PROP_CONTRAST, 0, 255, 128,
     "Spreidt grijswaarden uit rond het midden."),
    ("Verzadiging", CAP_PROP_SATURATION, 0, 255, 128,
     "Kleurintensiteit. 0 = grijswaarden, 255 = neon."),
    ("Scherpte", CAP_PROP_SHARPNESS, 0, 255, 128,
     "Edge-enhancement. Te hoog = ruis-versterking."),
    ("Gain", CAP_PROP_GAIN, 0, 255, 50,
     "Sensor-versterking. Verhoogt helderheid in donker maar voegt ruis toe."),
    ("Gamma", CAP_PROP_GAMMA, 1, 500, 100,
     "Non-lineaire helderheids-curve. <100 = donkere tinten ophogen, "
     ">100 = lichte tinten ophogen."),
]


class _SupportsSetProperty(Protocol):
    def set_property(self, prop_id: int, value: float) -> None: ...


class CameraSettingsPanel(QGroupBox):
    """Tab-paneel met sliders voor de meest-gebruikte OpenCV camera-properties."""

    def __init__(self, camera_thread: _SupportsSetProperty) -> None:
        super().__init__("Camera-instellingen")
        self.camera_thread = camera_thread
        self._sliders: list[QSlider] = []
        self._value_labels: list[QLabel] = []
        self._build_ui()
        # Defaults pas ~500ms na app-start naar de cap pushen — geeft thread
        # tijd om VideoCapture te openen
        QTimer.singleShot(500, self._apply_initial)

    def _build_ui(self) -> None:
        layout = QGridLayout(self)
        layout.setVerticalSpacing(12)
        layout.setHorizontalSpacing(10)
        r = 0

        # Auto-belichting toggle bovenaan
        self.auto_exp_cb = QCheckBox("Auto-belichting")
        self.auto_exp_cb.setToolTip(
            "AAN = camera regelt belichting zelf. "
            "UIT = handmatige Belichting-slider werkt."
        )
        self.auto_exp_cb.toggled.connect(self._on_auto_exposure)
        layout.addWidget(self.auto_exp_cb, r, 0, 1, 3)
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
        self.camera_thread.set_property(CAP_PROP_AUTO_EXPOSURE, 0.25)  # manual
        for slider in self._sliders:
            prop_id = int(slider.property("prop_id"))
            self.camera_thread.set_property(prop_id, float(slider.value()))

    def _on_slider_change(self, value: int) -> None:
        slider = self.sender()
        if slider is None:
            return
        prop_id = int(slider.property("prop_id"))
        idx = self._sliders.index(slider)
        self._value_labels[idx].setText(str(value))
        self.camera_thread.set_property(prop_id, float(value))

    def _on_auto_exposure(self, on: bool) -> None:
        # DirectShow conventie: 0.75 = auto, 0.25 = manual
        self.camera_thread.set_property(CAP_PROP_AUTO_EXPOSURE,
                                        0.75 if on else 0.25)
        # Disable de Belichting-slider als auto aan staat
        for slider in self._sliders:
            if int(slider.property("prop_id")) == CAP_PROP_EXPOSURE:
                slider.setEnabled(not on)
                break

    def _reset_all(self) -> None:
        for label, prop_id, _, _, default, _ in SLIDERS:
            for slider in self._sliders:
                if int(slider.property("prop_id")) == prop_id:
                    slider.setValue(default)  # triggert _on_slider_change
                    break
        self.auto_exp_cb.setChecked(False)
