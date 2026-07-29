# Calibration and acceptance

Design geometry is not a substitute for as-built calibration, especially when
an M12 adapter and custom tilt mechanism are used.

## Capture

Use at least 15 sharp checkerboard images. Cover all four image quadrants and
vary distance, pan, and tilt. Disable automatic exposure and gain after a
usable fixed setting has been selected.

## Camera and thick-lens fit

1. Initialize intrinsics and Brown distortion with OpenCV.
2. Reject incomplete checkerboards and duplicate poses.
3. Freeze initial distortion and fit the thick-lens and pose parameters with
   a robust `soft_l1` loss.
4. Assemble the calibrated matrix as `K_f = B @ A`.

An RMS reprojection error up to 0.5 px is accepted, 0.5–1.0 px produces a
warning, and values above 1.0 px cannot be approved.

## Laser plane

Fit the plane with SVD, reject median/MAD outliers, and refit until the inlier
set stabilizes. Keep residual metrics and independent holdout measurements in
the calibration record.

## Identity lock

An approved calibration is bound to camera model and serial, lens SKU, image
resolution, ROI, and sensor direction. A mismatch blocks measurement rather
than silently reusing calibration coefficients.

## Real hardware acceptance

- Enumerate and connect the acA1300-60gm.
- Acquire 1,000 full-resolution Mono8 frames without an unbounded queue.
- Confirm at least 25 fps preview and software-trigger capture.
- Recheck exposure, gain, ROI, disconnect, and reconnect paths.
- Validate distance using a traceable plane, step gauge, or gauge blocks not
  used in calibration.
