"""Camera preview scaffold with a working deterministic mock backend."""

from __future__ import annotations

import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class CameraPreviewWidget(QWidget):
    """Preview the latest frame without coupling the UI to pypylon."""

    frame_ready = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._backend: Any | None = None
        self._last_frame_id = -1
        self._last_overlay_time = 0.0
        self._last_forward_time = 0.0
        self._last_camera_frame: Any | None = None
        self._stripe_result: Any | None = None
        self._stripe_future: Future | None = None
        self._stripe_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="stripe-preview",
        )
        self._shutting_down = False

        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.backend_selector = QComboBox()
        self.backend_selector.addItem("모의 카메라 (Mock)", "mock")
        self.backend_selector.addItem("Basler pypylon", "basler")
        self.connect_button = QPushButton("연결")
        self.start_button = QPushButton("미리보기 시작")
        self.start_button.setEnabled(False)
        self.trigger_button = QPushButton("단일 프레임")
        self.trigger_button.setEnabled(False)
        self.overlay_checkbox = QCheckBox("레이저 중심선 표시")
        self.overlay_checkbox.setChecked(True)
        controls.addWidget(self.backend_selector)
        controls.addWidget(self.connect_button)
        controls.addWidget(self.start_button)
        controls.addWidget(self.trigger_button)
        controls.addWidget(self.overlay_checkbox)
        controls.addStretch(1)
        layout.addLayout(controls)

        settings = QFormLayout()
        self.exposure = QDoubleSpinBox()
        self.exposure.setRange(10.0, 10_000_000.0)
        self.exposure.setDecimals(1)
        self.exposure.setValue(2_000.0)
        self.exposure.setSuffix(" µs")
        self.gain = QDoubleSpinBox()
        self.gain.setRange(0.0, 48.0)
        self.gain.setValue(0.0)
        self.gain.setSuffix(" dB")
        self.frame_rate = QDoubleSpinBox()
        self.frame_rate.setRange(0.1, 240.0)
        self.frame_rate.setValue(30.0)
        self.frame_rate.setSuffix(" fps")
        self.roi_width = QSpinBox()
        self.roi_width.setRange(1, 10000)
        self.roi_width.setValue(1282)
        self.roi_height = QSpinBox()
        self.roi_height.setRange(1, 10000)
        self.roi_height.setValue(1026)
        settings.addRow("노출", self.exposure)
        settings.addRow("게인", self.gain)
        settings.addRow("프레임률", self.frame_rate)
        settings.addRow("ROI 폭", self.roi_width)
        settings.addRow("ROI 높이", self.roi_height)
        layout.addLayout(settings)

        self.preview = QLabel("카메라를 연결하세요.")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(640, 420)
        self.preview.setStyleSheet("background:#10151d;color:#9aa7b3;border:1px solid #33404f;")
        layout.addWidget(self.preview, 1)
        self.status = QLabel("연결 안 됨")
        layout.addWidget(self.status)

        self._timer = QTimer(self)
        self._timer.setInterval(33)  # UI preview is deliberately capped near 30 fps.
        self._timer.timeout.connect(self._poll_latest_frame)
        self.connect_button.clicked.connect(self._toggle_connection)
        self.start_button.clicked.connect(self._toggle_preview)
        self.trigger_button.clicked.connect(self._trigger)

    def _make_backend(self):
        selection = self.backend_selector.currentData()
        if selection == "mock":
            from scheimpflug_optimeter.camera import MockCameraBackend

            return MockCameraBackend(
                width_px=self.roi_width.value(),
                height_px=self.roi_height.value(),
            )
        from scheimpflug_optimeter.camera import BaslerCameraBackend

        return BaslerCameraBackend()

    def _toggle_connection(self) -> None:
        if self._backend is not None and self._backend.connected:
            self._stop()
            self._backend.disconnect()
            self._backend = None
            self.connect_button.setText("연결")
            self.start_button.setEnabled(False)
            self.trigger_button.setEnabled(False)
            self.status.setText("연결 안 됨")
            return
        try:
            backend = self._make_backend()
            devices = backend.enumerate_devices()
            if not devices:
                raise RuntimeError(
                    "카메라를 찾지 못했습니다. pylon runtime과 연결 상태를 확인하세요."
                )
            device = backend.connect(devices[0].serial)
            from scheimpflug_optimeter.camera import CameraConfig, Roi

            backend.configure(
                CameraConfig(
                    exposure_us=self.exposure.value(),
                    gain_db=self.gain.value(),
                    frame_rate_hz=self.frame_rate.value(),
                    roi=Roi(
                        0,
                        0,
                        self.roi_width.value(),
                        self.roi_height.value(),
                    ),
                )
            )
        except Exception as exc:  # Device/SDK errors must remain visible in the tab.
            self._backend = None
            self.status.setText(f"연결 실패: {exc}")
            return
        self._backend = backend
        self.connect_button.setText("연결 해제")
        self.start_button.setEnabled(True)
        self.trigger_button.setEnabled(True)
        self.status.setText(f"{device.model} / {device.serial} 연결됨")

    def _toggle_preview(self) -> None:
        if self._backend is None:
            return
        if self._backend.running:
            self._stop()
            return
        try:
            self._backend.start()
        except Exception as exc:
            self.status.setText(f"획득 시작 실패: {exc}")
            return
        self._timer.start()
        self.start_button.setText("미리보기 정지")
        self.status.setText("최신 프레임만 유지하며 미리보기 중")

    def _stop(self) -> None:
        self._timer.stop()
        if self._backend is not None:
            try:
                self._backend.stop()
            except Exception as exc:
                self.status.setText(f"획득 정지 오류: {exc}")
        self.start_button.setText("미리보기 시작")

    def _trigger(self) -> None:
        if self._backend is None:
            return
        try:
            frame = self._backend.software_trigger()
        except Exception as exc:
            self.status.setText(f"단일 프레임 실패: {exc}")
            return
        self._display_frame(frame, force_forward=True)
        self.status.setText(f"단일 프레임 #{frame.frame_id}")

    def _poll_latest_frame(self) -> None:
        if self._backend is None:
            return
        try:
            frame = self._backend.latest_frame(0.0)
        except Exception as exc:
            self._stop()
            self.status.setText(f"카메라 오류: {exc}")
            return
        if frame is not None and frame.frame_id != self._last_frame_id:
            self._display_frame(frame)

    def _display_frame(
        self,
        frame,
        *,
        schedule_extraction: bool = True,
        force_forward: bool = False,
    ) -> None:
        self._last_camera_frame = frame
        image = np.ascontiguousarray(frame.image)
        height, width = image.shape
        now = time.monotonic()
        self._consume_stripe_result()
        if (
            schedule_extraction
            and self.overlay_checkbox.isChecked()
            and self._stripe_future is None
            and now - self._last_overlay_time >= 1.0 / 15.0
        ):
            from scheimpflug_optimeter.measurement import extract_stripe

            self._stripe_future = self._stripe_executor.submit(
                extract_stripe,
                image.copy(),
                orientation="vertical",
            )
            self._last_overlay_time = now
            if self._backend is not None and not self._backend.running:
                QTimer.singleShot(25, self._finish_single_frame_overlay)

        stripe = self._stripe_result if self.overlay_checkbox.isChecked() else None
        if stripe is not None:
            rgb = np.repeat(image[:, :, None], 3, axis=2)
            rows = stripe.profile_indices_px[stripe.valid_mask].astype(np.intp)
            columns = np.rint(stripe.coordinates_px[stripe.valid_mask]).astype(np.intp)
            inside = (rows >= 0) & (rows < height) & (columns >= 0) & (columns < width)
            rows = rows[inside]
            columns = columns[inside]
            for offset in (-1, 0, 1):
                overlay_columns = np.clip(columns + offset, 0, width - 1)
                rgb[rows, overlay_columns] = (255, 45, 35)
            qimage = QImage(
                rgb.data,
                width,
                height,
                rgb.strides[0],
                QImage.Format.Format_RGB888,
            ).copy()
            valid_count = int(np.count_nonzero(stripe.valid_mask))
            mean_confidence = (
                float(np.mean(stripe.confidence[stripe.valid_mask])) if valid_count else 0.0
            )
            self.status.setText(
                f"프레임 #{frame.frame_id} · 레이저 {valid_count}/{height} 행 · "
                f"평균 신뢰도 {mean_confidence:.2f}"
            )
        else:
            qimage = QImage(
                image.data,
                width,
                height,
                image.strides[0],
                QImage.Format.Format_Grayscale8,
            ).copy()
        pixmap = QPixmap.fromImage(qimage).scaled(
            self.preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview.setPixmap(pixmap)
        self._last_frame_id = frame.frame_id
        if force_forward or now - self._last_forward_time >= 0.1:
            self._last_forward_time = now
            self.frame_ready.emit(frame)

    def _consume_stripe_result(self) -> None:
        future = self._stripe_future
        if future is None or not future.done():
            return
        self._stripe_future = None
        try:
            self._stripe_result = future.result()
        except Exception as exc:
            self._stripe_result = None
            self.status.setText(f"레이저 중심선 검출 실패: {exc}")

    def _finish_single_frame_overlay(self) -> None:
        if self._shutting_down or self._stripe_future is None:
            return
        if not self._stripe_future.done():
            QTimer.singleShot(25, self._finish_single_frame_overlay)
            return
        self._consume_stripe_result()
        if self._last_camera_frame is not None:
            self._display_frame(
                self._last_camera_frame,
                schedule_extraction=False,
            )

    def shutdown(self) -> None:
        self._shutting_down = True
        self._stop()
        if self._backend is not None:
            try:
                self._backend.disconnect()
            finally:
                self._backend = None
        if self._stripe_future is not None:
            self._stripe_future.cancel()
        self._stripe_executor.shutdown(wait=False, cancel_futures=True)
