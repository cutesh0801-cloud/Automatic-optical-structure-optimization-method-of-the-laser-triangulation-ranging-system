# Changelog

All notable changes to this project are documented here.

## Unreleased

Product-version releases are intentionally reserved for reviewed, large
updates. Routine work remains unreleased unless a maintainer explicitly
authorizes an append-only maintenance build.

## 0.1.0 maintenance build 2026-07-30 (`build-20260730.1`)

- Increased the desktop type scale and clarified the input, workspace, result,
  warning and application-status hierarchy.
- Added backed label callouts and collision-aware placement to keep 2D values
  readable over optical lines.
- Added Korean input names, equation symbols, units, contextual help and
  mode-specific formula cards.
- Kept laser, lens and sensor cues visible at extreme 2D zoom levels while
  reducing callout-layout latency.
- Reworked the 3D view with schematic camera, lens, sensor and laser bodies,
  labelled planes, normals, a legend and head/full-assembly view controls.
- Added per-profile Basler FOV, object sampling and geometric range-sensitivity
  calculations and comparison UI.
- Added an original Scheimpflug geometry logo to the application, Windows
  executable and repository documentation.
- Replaced automatic publication with an explicit, append-only maintenance or
  product-version release workflow and documented the approval rules.
- Updated GitHub-hosted packaging actions to their Node 24 runtime majors.

## 0.1.0

- Added workbook-compatible and canonical Scheimpflug design solvers.
- Added live 2D optical geometry and 3D full-focus visualization.
- Added static Basler sensor and Edmund Optics lens specification profiles.
- Added deterministic SciPy and M-PSO optimization paths.
- Added schema-v1 project files and Windows portable packaging.
- Kept the product scope simulation-only: no camera connection, acquisition,
  calibration, laser detection, or physical measurement workflow.
