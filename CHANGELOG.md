# Changelog

All notable changes to this project are documented here.

## Unreleased

Product-version releases are intentionally reserved for reviewed, large
updates. Every completed routine fix, refinement, or small feature is released
as a new append-only maintenance build while the application version remains
unchanged.

- Rebuilt the Workbook input sheet around the original editable and derived
  cells, with Korean names, equation variables, units and compact source-aware
  formulas.
- Corrected the Workbook geometry so the CMOS plane remains perpendicular to
  the laser axis, `β=90°−α` stays a derived complement, and the lens housing is
  placed backward from its verified `S1→H` datum without inventing an absolute
  `H′` position.
- Added project-local user lens presets with create, official-profile clone,
  edit and delete flows for optical values, M12 mechanics, `S1→H` and
  `SL→H′`; incomplete mechanics remain usable for calculation but cannot
  masquerade as a verified physical 3D model.
- Made preset and project loading atomic, validated every stored user lens
  before selection, preserved manual focal overrides during partial CSV
  imports and migrated older schema-v1 projects deterministically.
- Removed the unsupported 3D laser-plane extrusion; the workbook model now
  remains a single laser irradiation line in both 2D and 3D.
- Removed the unmapped `γ/δ` readout, a duplicate ideal-focus plane and an
  invented hinge reference that were not derived from workbook inputs.
- Removed persistent text, numeric ticks, callouts and legends from inside the
  3D canvas so geometry remains readable while rotating and zooming.
- Made the desktop and 2D-scene typography respond continuously to the window
  and viewport size instead of using one enlarged fixed font.
- Reduced the 2D canvas to seven primary callouts, moved the color key into the
  toolbar and kept remote ray/Scheimpflug intersections from collapsing the
  working-area scale.
- Added zoom-independent schematic laser, lens and camera cues, boundary
  direction markers for remote geometry and mode-specific workbook/canonical
  terminology.
- Reworked the formula card into compact tagged equation rows with concise
  variable hints and full definitions in accessible tooltips.
- Kept the result names and values readable at 1280×720 by removing nested
  scrolling and allocating the columns from measured content width.
- Clarified that the workbook display reports the non-negative ray-intersection
  distance `|s|`, while the saved calculation value retains its directional
  sign.
- Replaced the folder-based portable bundle with a directly downloadable
  PyInstaller single-file Windows executable and matching SHA-256 file.
- Deferred NumPy/Matplotlib until the 3D tab is opened and SciPy until a
  canonical root solve or optimization actually needs it; the default
  workbook screen no longer pays for unused numerical stacks.

## 0.1.0 maintenance build 2026-07-30 (`build-20260730.2`)

- Increased the desktop type scale and clarified the input, workspace, result,
  warning and application-status hierarchy.
- Added backed label callouts and collision-aware placement to keep 2D values
  readable over optical lines.
- Added Korean input names, equation symbols, units, contextual help and
  mode-specific formula cards.
- Kept laser, lens and sensor cues visible at extreme 2D zoom levels while
  reducing callout-layout latency.
- Reworked the 3D view with schematic camera, lens, sensor and laser bodies,
  labelled optical planes, normals, a legend and head/full-assembly controls.
- Added per-profile Basler FOV, object sampling and geometric range-sensitivity
  calculations and comparison UI.
- Added an original Scheimpflug geometry logo to the application, Windows
  executable and repository documentation.
- Replaced automatic publication with an explicit, append-only maintenance or
  product-version release workflow and documented the approval rules.
- Updated GitHub-hosted packaging actions to their Node 24 runtime majors.

## 0.1.0

- Added workbook-compatible and canonical Scheimpflug design solvers.
- Added live 2D optical geometry and a schematic 3D view of the same
  meridional calculation.
- Added static Basler sensor and Edmund Optics lens specification profiles.
- Added deterministic SciPy and M-PSO optimization paths.
- Added schema-v1 project files and Windows portable packaging.
- Kept the product scope simulation-only: no camera connection, acquisition,
  calibration, laser detection, or physical measurement workflow.
