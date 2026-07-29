# Architecture

Scheimpflug OptiMeter is a Windows-first PySide6 desktop application with a
small, importable numerical core. The UI never owns optical formulas.

```text
PySide6 UI
  ├─ workbook/CSV input ── workbook solver ── live 2D scene
  ├─ project JSON
  ├─ advanced canonical design / scene geometry ── SciPy optimizers
  ├─ camera backend ── Mock | lazy pypylon
  └─ stripe extraction ── calibration ── triangulation
```

The workbook/CSV path is the product's primary path. Paper-derived canonical
optimization, 3D, calibration, and measurement modules are isolated
advanced/reference functions; they do not replace or silently alter workbook
inputs or results.

## Boundaries

- Domain objects are immutable, slotted dataclasses with units in field names.
- Core calculations are deterministic pure functions.
- Qt signals connect the UI and worker threads; there is no application event bus.
- Camera access is the only optional hardware boundary.
- Projects and calibrations use versioned JSON; there is no database.
- A project stores authoritative inputs. Derived optical values are recomputed on load.

## Coordinate system

The live view consumes named geometry from the selected solver and uses one
world-to-screen scale, so optical angles are not distorted.

In workbook mode, the target reference is `(0,0)`, the laser emitter is
`(0,V)`, and the calculated `s` endpoint lies on the same laser axis. A remote
`s` endpoint is clipped at the view boundary with its full numeric value shown,
so it cannot shrink the optical head to an unreadable size.

The advanced canonical view uses `+Z` along laser propagation and `+X` toward
the receiver. Its laser exit is `E=(0,0)` and nominal target is `T0=(0,d)`.

The live drawing includes the laser line, near/nominal/far targets, working
distance, lens plane, receiver axis, image plane, exact sensor segment, chief
rays, Scheimpflug intersection, and the `W/R` mechanical envelope.

## Threading

- Small design calculations and scene updates run in the GUI thread.
- Optimization and camera acquisition run in workers.
- Camera preview keeps only the latest frame and is rate-limited to 30 fps.
- A missing pylon runtime disables only the Basler backend.
