# SPDX-License-Identifier: MIT

"""Camera settings panel, adjusts brightness/contrast/exposure via OpenCV.

OpenCV CAP_PROP_* constants are hardcoded so this file does not have to import
cv2 itself. The CameraThread accepts changes via a thread-safe set_property().

DirectShow quirks (Windows):
  - CAP_PROP_AUTO_EXPOSURE: 0.25 = manual, 0.75 = auto
  - CAP_PROP_EXPOSURE: log2(seconds); -6 = ~16ms, -13 = ~120µs

Grayscale is a software conversion in CameraThread (BGR->GRAY->BGR), not via
CAP_PROP_SATURATION, which works reliably on any webcam.
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


# OpenCV CAP_PROP_*, integer values are stable across cv2 versions
CAP_PROP_BRIGHTNESS = 10
CAP_PROP_CONTRAST = 11
CAP_PROP_EXPOSURE = 15
CAP_PROP_AUTO_EXPOSURE = 21


# (label, prop_id, min, max, default, tooltip)
SLIDERS = [
    ("Exposure", CAP_PROP_EXPOSURE, -13, 0, -9,
     "Exposure time in log2 seconds (-9 ≈ 2ms, -6 ≈ 16ms, -13 ≈ 120µs). "
     "Only works with Auto-exposure OFF. Lab light clips quickly above -8."),
    ("Brightness", CAP_PROP_BRIGHTNESS, 0, 255, 128,
     "Digital brightness offset (post-sensor). 128 = neutral."),
    ("Contrast", CAP_PROP_CONTRAST, 0, 255, 128,
     "Spreads grey values around the midpoint."),
]


class _SupportsCamera(Protocol):
    def set_property(self, prop_id: int, value: float) -> None: ...
    def set_grayscale(self, on: bool) -> None: ...


_DEBOUNCE_MS = 150


class CameraSettingsPanel(QGroupBox):
    """Tab panel with sliders for the most-used OpenCV camera properties."""

    def __init__(self, camera_thread: _SupportsCamera) -> None:
        super().__init__("Camera settings")
        self.camera_thread = camera_thread
        self._sliders: list[QSlider] = []
        self._value_labels: list[QLabel] = []
        # Debounce state: slider movements are collected here, and only once the
        # user has been idle for ~_DEBOUNCE_MS do we push to the cap thread. This
        # prevents DirectShow getting dozens of cap.set() calls per second.
        self._pending_values: dict[int, float] = {}
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(_DEBOUNCE_MS)
        self._debounce_timer.timeout.connect(self._flush_pending)
        self._build_ui()
        # Push defaults to the cap only ~500ms after app start, giving the thread
        # time to open VideoCapture
        QTimer.singleShot(500, self._apply_initial)

    def _build_ui(self) -> None:
        layout = QGridLayout(self)
        layout.setVerticalSpacing(12)
        layout.setHorizontalSpacing(10)
        r = 0

        # Toggles at the top, Auto-exposure + Grayscale
        self.auto_exp_cb = QCheckBox("Auto-exposure")
        self.auto_exp_cb.setToolTip(
            "ON = camera controls exposure itself (recommended for changing "
            "lab light). OFF = the manual Exposure slider works."
        )
        self.auto_exp_cb.setChecked(True)  # default auto, consistent with AUTO_WB/AUTOFOCUS
        self.auto_exp_cb.toggled.connect(self._on_auto_exposure)
        layout.addWidget(self.auto_exp_cb, r, 0, 1, 3)
        r += 1

        self.bw_cb = QCheckBox("Grayscale image")
        self.bw_cb.setToolTip(
            "ON = live image in grayscale (software conversion). "
            "Does not affect scan recording, only the preview."
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

        # Exposure slider starts disabled because auto-exposure is on by default
        self._set_exposure_slider_enabled(False)

        # Reset button
        reset_btn = QPushButton("↺ Reset to defaults")
        reset_btn.setToolTip("Set all sliders back to their start value")
        reset_btn.clicked.connect(self._reset_all)
        layout.addWidget(reset_btn, r, 0, 1, 3)
        r += 1

        layout.setColumnStretch(1, 1)
        layout.setRowStretch(r, 1)

    # ---- camera sync -----------------------------------------------

    def _apply_initial(self) -> None:
        """Push initial slider values to the camera thread."""
        # Default: auto-exposure ON (DirectShow: 0.75 = auto, 0.25 = manual)
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
        # Update label immediately (free); debounce cap.set()
        self._value_labels[idx].setText(str(value))
        self._pending_values[prop_id] = float(value)
        self._debounce_timer.start()  # restart countdown

    def _flush_pending(self) -> None:
        """Push collected slider values to the camera thread in one batch."""
        pending = self._pending_values
        self._pending_values = {}
        for prop_id, value in pending.items():
            self.camera_thread.set_property(prop_id, value)

    def _on_grayscale(self, on: bool) -> None:
        self.camera_thread.set_grayscale(on)

    def _on_auto_exposure(self, on: bool) -> None:
        # The toggle is a one-off action, push immediately, no debounce needed.
        # DirectShow: 0.75 = auto, 0.25 = manual.
        self.camera_thread.set_property(CAP_PROP_AUTO_EXPOSURE, 0.75 if on else 0.25)
        self._set_exposure_slider_enabled(not on)
        # If the user just switched to manual, push the current slider value right
        # away so the cam takes the manual exposure instead of its internal fallback.
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
                    slider.setValue(default)  # triggers _on_slider_change
                    break
        self.bw_cb.setChecked(False)
        self.auto_exp_cb.setChecked(True)  # reset to auto-exposure ON
