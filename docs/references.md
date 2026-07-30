# References and implementation provenance

No source PDF or spreadsheet is distributed in this repository.

1. Z. Nan, T. Wei, and H. Zhao, “Automatic optical structure optimization
   method of the laser triangulation ranging system under the Scheimpflug
   rule,” *Optics Express* 30(11), 18667 (2022).
   <https://doi.org/10.1364/OE.458076>
2. D. Guo, J. Cui, and Y. Wu, “Linear-Structured-Light Measurement System
   Based on Scheimpflug Camera Thick-Lens Imaging,” *Sensors* 24, 5124
   (2024). <https://doi.org/10.3390/s24165124>
3. N. Meraz et al., “Scheimpflug cameras for range-resolved observations of
   the atmospheric effects on laser propagation,” *Proc. SPIE* 13472,
   1347208 (2025). <https://doi.org/10.1117/12.3054806>
4. K. Kobayashi, M. Ichikawa, and K. Nishi, “Three-dimensional Scheimpflug
   principle and its application to full-focus positioning,” *JOSA A* 42(11),
   1705–1717 (2025). <https://doi.org/10.1364/JOSAA.571923>

The workbook-derived regression fixtures contain only numeric inputs,
formula identifiers, and expected values. All diagrams are rendered from
application geometry rather than copied from the publications.

Implementation scope:

- The workbook/CSV equations are authoritative for the default calculation.
- The 2022 paper supports interpretation of the optical geometry and the
  optional optimization comparison.
- The 2024 thick-lens and both 2025 papers provide background context only.
  Their acquisition, calibration, observation and two-axis full-focus models
  are not implemented. In particular, the 2025 paper's object-plane
  tilt/pan variables are not interchangeable with this workbook's 2D
  observation and sensor angles.
