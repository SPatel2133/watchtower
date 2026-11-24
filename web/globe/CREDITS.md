# Credits

## Globe code: dev-Armaan/satellites (MIT)

The globe rendering (Earth, cloud and atmosphere shaders, stars, sun and GMST maths, the HDR post chain and tone
shoulder) is adapted from [dev-Armaan/satellites](https://github.com/dev-Armaan/satellites). The shader files and
their constants are copied unchanged:

| File here | Source file |
| --- | --- |
| `src/globe/shaders/chunks.ts`, `earth.ts`, `clouds.ts`, `atmosphere.ts`, `points.ts` | `src/globe/shaders/*` (verbatim) |
| `src/globe/toneShoulder.ts`, `src/globe/Stars.tsx`, `src/globe/starData.ts` | `src/globe/*` (verbatim) |
| `src/lib/geo.ts`, `geoCore.ts`, `geo3.ts` | `src/lib/*` (verbatim) |
| `src/ui/system/palette.ts` | `src/ui/system/palette.ts` (verbatim) |
| `src/globe/Earth.tsx`, `Post.tsx`, `SunClock.tsx`, `textures.ts`, `textureDecode.worker.ts`, `runtime.ts` | adapted from `src/globe/Earth.tsx`, `Post.tsx`, `Clock.tsx`, `textures.ts`, `textureDecode.worker.ts`, `runtime.ts` |

```
MIT License

Copyright (c) 2026 Armaan Gupta

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Earth textures: Solar System Scope (CC BY 4.0)

`public/textures/earth-{day,night,clouds}-{1k,4k}.webp` are the [Solar System Scope](https://www.solarsystemscope.com/textures/)
Earth textures, licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), based on NASA Blue Marble (day,
clouds) and Black Marble (night lights) imagery, resized and re-encoded to WebP by dev-Armaan/satellites.
`earth-data-*.webp` repacks the elevation (bump) map and ocean mask from the same set and the three.js examples into
one texture (R = elevation, G = ocean mask). Only the 1k and 4k sizes are used.

## Star catalogue

`src/globe/starData.ts`: stars from the Hipparcos catalogue via [d3-celestial](https://github.com/ofrohn/d3-celestial)
(BSD-3-Clause), as packed by dev-Armaan/satellites.

## Fire data: NASA FIRMS

Hotspots come from [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/) (VIIRS S-NPP / NOAA-20 / NOAA-21 and MODIS
near-real-time active fire products) through `python -m watchtower export`. The bundled `public/data/sample/` files
are synthetic and only stand in until a first export.
