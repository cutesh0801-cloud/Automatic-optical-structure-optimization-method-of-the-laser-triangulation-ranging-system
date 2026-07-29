# Static sensor and lens profiles

The built-in catalog supplies dimensions to the optical simulation. It does
not discover, connect, configure, or acquire images from any device. Check the
current manufacturer drawing before purchasing parts or machining a mount.

## Basler sensor specification presets

| Static profile | Active pixels | Pitch | Active size | Documented rate | Interface | Mount |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| ace acA1300-60gm | 1282 × 1026 | 5.3 µm | 6.7946 × 5.4378 mm | 60 fps | GigE | C |
| dart daA1280-54um | 1280 × 960 | 3.75 µm | 4.8000 × 3.6000 mm | 54 fps | USB3 | S |
| dart dmA2048-37gm | 2064 × 1552 | 2.25 µm | 4.6440 × 3.4920 mm | 32.6 fps default; 37.2 fps performance settings | GigE | model variant |
| dart daA2448-70um | 2448 × 2048 default | 2.74 µm | 6.7075 × 5.6115 mm | 29.8 fps default; 72.8 fps without link limit | USB3 | S |

`acA1300-60gm` is the default because its 6.7946×5.4378 mm active dimensions
match the spreadsheet values used for regression. Selecting it only makes
these constants available to the solver. No pylon runtime, driver, network
connection, serial number, or physical camera is involved.

For one optical solution, the application recalculates every profile rather
than scaling the selected profile's result. The comparison includes:

- horizontal and vertical object-space FOV;
- average horizontal and vertical object sampling in µm/px;
- near, centre, far and worst local range sensitivity in mm/px;
- native pixel count, pixel pitch, active area and documented frame rate.

The selected triangulation axis uses the exact tilted-sensor inverse mapping.
The orthogonal axis uses the nominal reference-plane magnification. Therefore
the two FOV values are not interchangeable, and rotating the sensor changes
which physical dimension controls the nonlinear range field.

“Range sensitivity” means geometric distance change per sensor pixel. It is
not quantum efficiency, signal-to-noise ratio or minimum detectable
illumination. Those photometric quantities depend on wavelength, exposure,
gain, lens transmission and noise data that this simulator does not model.

Official product pages used for the static metadata:

- <https://docs.baslerweb.com/aca1300-60gm>
- <https://docs.baslerweb.com/daa1280-54um>
- <https://docs.baslerweb.com/dma2048-37gm>
- <https://docs.baslerweb.com/daa2448-70um>

## Edmund Optics M12 lens specification presets

The focal-length candidates are #33-879 (12 mm), #83-953 (12.5 mm),
#36-376 (16 mm), #83-954 (17.5 mm), #36-385 (25 mm), and #70-646 (35 mm).
Unknown catalog values remain `null`; they are never inferred from a similar
part number.

M12×0.5 does not define a universal flange distance. Focus travel, lens
intrusion, image circle, barrel collision, wavelength and recommended working
distance are therefore shown as design checks only.

The #53-675 class C-to-M12 adapter changes the mount only. It does not create a
Scheimpflug tilt. These mounting notes are static compatibility warnings, not
instructions or evidence that the simulated assembly has been built.
