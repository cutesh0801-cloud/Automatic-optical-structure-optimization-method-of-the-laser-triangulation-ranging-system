# Optical formulas

All internal lengths are millimetres and angles are radians. UI angles are
degrees. A near-zero denominator is an invalid design, not a numeric result.

## Workbook compatibility

The compatibility solver reproduces the supplied workbook without embedding
the workbook itself:

```text
β = 90° - α
b = V tan(α)
x = L / 2
W = b + x
R = V - d
fp = b cos(β)
lo = V cos(α)
s = x lo sin(β) / (fp sin(α) - x sin(α + β))
f = 1 / (1/lo + 1/fp)
```

`L` is required. The source workbook contained formula references to empty
length cells, which spreadsheet software silently treated as zero; the
application rejects that state.

The sanitized regression fixture records all 16 workbook positions across two
sheets and two calculation blocks. Four positions have complete inputs and are
checked at relative tolerance `1e-9` and absolute tolerance `1e-10`. The other
12 reference absent `L` source cells (`W24`, `AB24`, `AG24`, `W53`, `AB53`,
or `AG53`) and are intentionally blocked. Unlabelled `M34 = 98.2 mm`, the
32,767-space `J33` cell, and formula-free RM-CMOS/FOV literals are provenance,
not authoritative equations.

## Canonical thin-lens model

The low-angle solution for an observation angle is the root of

```text
sin²(α) cos(α) = f / V
```

within `0 < α < 54.735610317°`. It exists only when
`0 < f/V < 2/(3√3)`.

For independently selected observation and sensor angles:

```text
r  = tan(β) / tan(α)
lo = f(1 + r)
fp = f(1 + 1/r)
```

This satisfies both `1/lo + 1/fp = 1/f` and
`lo tan(α) = fp tan(β)`.

A range displacement `s` maps to signed image coordinate

```text
x(s) = s fp sin(α) /
       (lo sin(β) + s sin(α + β))
```

The active image length is `x(S/2)-x(-S/2)`. Because the mapping is nonlinear,
the exact segment is generally asymmetric about the nominal image point. The
application draws this exact segment solid and the paper's centred packaging
proxy dashed.

## Thick-lens calibration

The calibrated imaging matrix is assembled from the paper's component
matrices as `K_f = B @ A`. The expanded printed form is not hard-coded.
Principal-plane separation, two-axis sensor tilt, laser-plane parameters, and
the camera pose are stored with calibration residuals.

## Three-dimensional full focus

For object tilts `α, β`, magnification `m`, and sensor tilts `γ, δ`:

```text
tan(γ) = m tan(α)
tan(δ) = m (cos(γ) / cos(α)) tan(β)
```

The exact trigonometric form is authoritative. Small-angle results are shown
only as a comparison.
