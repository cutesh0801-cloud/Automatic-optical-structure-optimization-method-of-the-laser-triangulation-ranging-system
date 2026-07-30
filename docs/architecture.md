# Architecture

Scheimpflug OptiMeter is a Windows-first PySide6 calculation and visualization
application with a small, importable numerical core. The UI never owns or
duplicates optical formulas.

```text
PySide6 UI
  ├─ workbook/CSV input ── workbook solver ── live 2D scene
  ├─ static sensor profiles ── FOV/sampling/range-sensitivity comparison
  ├─ static sensor/lens profiles ── compatibility warnings
  ├─ canonical design ── SciPy/M-PSO optimizers
  ├─ calculated geometry ── 3D Scheimpflug scene
  └─ versioned project JSON + CSV/SVG/PNG export
```

The workbook/CSV path is the primary product path. Paper-derived canonical
optimization and 3D relations are comparison tools; they never replace or
silently alter workbook inputs or results.

There is no device-I/O boundary. The application does not enumerate or connect
cameras, acquire frames, calibrate a physical system, detect a laser stripe, or
produce measured profiles. Camera model names in the catalog identify static
sensor specifications only.

## Boundaries

- Domain objects are immutable, slotted dataclasses with units in field names.
- Core calculations are deterministic pure functions.
- A single calculated result object feeds the numeric table and visualizations.
- Qt signals connect widgets directly; there is no application event bus.
- Projects use versioned JSON; there is no database.
- Projects store authoritative inputs. Derived optical values are recomputed on load.
- Static catalog data never initiates hardware access.

## Coordinate system

The live view consumes named geometry from the selected solver and uses one
world-to-screen scale, so optical angles are not distorted.

In workbook mode, the target reference is `(0,0)`, the laser emitter is
`(0,V)`, and the calculated `s` endpoint lies on the same laser axis. A remote
`s` endpoint is clipped at the view boundary with its full numeric value shown,
so it cannot shrink the optical head to an unreadable size.

The canonical view uses `+Z` along laser propagation and `+X` toward the
receiver. Its laser exit is `E=(0,0)` and nominal target is `T0=(0,d)`.

The live drawing includes the laser line, near/nominal/far targets, working
distance, lens plane, receiver axis, image plane, exact sensor segment, chief
rays, Scheimpflug intersection, and the `W/R` mechanical envelope.

## Threading

- Workbook calculations and 2D scene updates run in the GUI thread after a
  16 ms debounce.
- SciPy and M-PSO optimization run in a cancellable worker thread.
- Inactive 3D rendering is deferred.
- No acquisition or device worker exists.
