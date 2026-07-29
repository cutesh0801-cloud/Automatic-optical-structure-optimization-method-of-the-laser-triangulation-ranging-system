# Hardware profiles and integration notes

The built-in catalog is a design aid. Check the current manufacturer drawing
before machining or purchasing parts.

## Basler cameras

| Profile | Active pixels | Pitch | Interface | Mount |
| --- | ---: | ---: | --- | --- |
| ace acA1300-60gm | 1282 × 1026 | 5.3 µm | GigE | C |
| dart daA1280-54um | 1280 × 960 | 3.75 µm | USB3 | S/CS variant |
| dart dmA2048-37gm | 2064 × 1552 | 2.25 µm | GigE | C/S/CS accessory |
| dart daA2448-70um | 2448 × 2048 default | 2.74 µm | USB3 | S/CS variant |

The acA1300-60gm active width and height are 6.7946 × 5.4378 mm and match the
spreadsheet sensor values. It is a C-mount camera; an M12 lens is not a direct
fit.

Official product documentation:

- <https://docs.baslerweb.com/aca1300-60gm>
- <https://docs.baslerweb.com/daa1280-54um>
- <https://docs.baslerweb.com/dma2048-37gm>
- <https://docs.baslerweb.com/daa2448-70um>

## Edmund Optics M12 lenses

The initial focal-length candidates are #33-879 (12 mm), #83-953 (12.5 mm),
#36-376 (16 mm), #83-954 (17.5 mm), #36-385 (25 mm), and #70-646 (35 mm).
Unknown catalog values remain `null`; they are never inferred from a similar
part number.

M12×0.5 does not define a universal flange distance. Focus travel, lens
intrusion, image circle, barrel collision, wavelength, and working distance
must be checked for the exact part.

The #53-675 class C-to-M12 adapter changes the mount only. A separate, rigid
tilt mechanism is required to implement the Scheimpflug geometry on an
acA1300-60gm.

## Basler runtime

Install the Basler pylon Software Suite and the appropriate GigE/USB transport
drivers separately, then install the optional Python dependency:

```powershell
uv sync --extra camera
```

The portable application intentionally does not redistribute pylon drivers.
