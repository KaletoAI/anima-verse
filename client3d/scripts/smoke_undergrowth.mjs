#!/usr/bin/env node
/**
 * Smoke check for THE AUTOMATIC UNDERGROWTH — the layer nobody authored, as it
 * stands after the camera-local rebuild (plan-undergrowth-rettung.md,
 * 2026-08-16). Two modules, one subject: the numbers in
 * `client3d/src/scene/scatterLod.ts` (`UNDERGROWTH_*`) and everything that is
 * not a plain number in `client3d/src/scene/undergrowth.ts` — the cell raster,
 * the blade texture, the crossed quads and the field that grows them.
 *
 * Usage:  node client3d/scripts/smoke_undergrowth.mjs
 *
 * WHERE THESE CASES COME FROM. Sections (E) and part of (C) are the old
 * section (K) of `smoke_scatter_math.mjs`, moved here whole: the layer is no
 * longer a variant of the authored scatter (it has its own raster, its own
 * seed shape and its own look), so its checks no longer belong in the file
 * about where a PROP stands. `smoke_scatter_math.mjs` went from 239 to 180
 * checks in that move, and the cases that did NOT come along are the ones the
 * rebuild deleted: the per-AREA count rule (`undergrowthCount`), its 20 000
 * ceiling and the "capped" report (`undergrowthCapped`) — the area is not the
 * unit any more, so there is no per-area number to check.
 *
 * Same discipline as `smoke_scatter_math.mjs` and `smoke_height_tiles.mjs`:
 * every expected number below is derived BY HAND in this header and NEVER
 * recorded from the current output.
 *
 * TWO LOADERS, for two kinds of module. `scatterLod.ts` has no import at all,
 * so a plain esbuild transpile is enough. `undergrowth.ts` imports three and
 * the shared sampler, so it is BUNDLED with `external: ['three']` and pulled
 * in against node's own three — the trick `smoke_occlusion.mjs` uses, and what
 * lets section (F)/(G) build REAL materials and REAL instanced meshes instead
 * of asserting against a copy of the code.
 *
 * ============================================================================
 * (A) THE CELL RASTER — `wantedUndergrowthCells`, the `heightTiles` pattern
 * ============================================================================
 * The world is cut into an ORIGIN-ANCHORED raster of `UNDERGROWTH_CELL_M`
 * (64 m) and the cells within `UNDERGROWTH_CELL_RADIUS_M` (128 m) of the
 * anchor are held. The test is SQUARE-to-point: `dx` is the distance from the
 * anchor to the cell's box, 0 on the axes where the anchor is inside it.
 *
 * (A1) THE ANCHOR IN THE MIDDLE OF ITS CELL, (32, 32) — cell (0, 0).
 *      first = floor((32 − 128)/64) = floor(−1.5) = −2
 *      last  = floor((32 + 128)/64) = floor(2.5)  = 2      -> 5 columns
 *      dx per column (−2 … 2):  96, 32, 0, 32, 96
 *        cx = −2: the box runs −128 … −64, so dx = 32 − (−64) = 96
 *        cx = −1: −64 … 0,     dx = 32 − 0 = 32
 *        cx =  0: 0 … 64,      the anchor is inside, dx = 0
 *      and the same five by symmetry on z. Accepted when dx² + dz² ≤ 128²
 *      = 16384:
 *        96² + 96² = 18432  > 16384  -> the FOUR corners fall out
 *        96² + 32² = 10240  ≤        -> in
 *        96² + 0   =  9216  ≤        -> in
 *      -> 25 − 4 = 21 cells, and the first of them is the anchor's own
 *         ("0,0", distance 0).
 *
 * (A2) THE ANCHOR ON A CELL CORNER, (0, 0). Now the raster is asymmetric
 *      about the anchor, which is exactly the case a centre-to-point test
 *      would get wrong:
 *      first = floor(−2) = −2, last = floor(2) = 2
 *      dx per column (−2 … 2): 64, 0, 0, 64, 128
 *        cx = −1 (−64 … 0) and cx = 0 (0 … 64) both TOUCH the anchor -> 0
 *        cx =  2 (128 … 192) is a full 128 m away — the very edge
 *      accepted:
 *        dx = 64: dz ∈ {64, 0, 0, 64} in (8192 / 4096 ≤ 16384), dz = 128 out
 *                 -> 4 rows each, twice           =  8
 *        dx =  0: every dz, 128 included (0 + 16384 = 16384, EQUAL -> in)
 *                 -> 5 rows each, twice           = 10
 *        dx = 128: only dz = 0 (16384 + 0), i.e. cz ∈ {−1, 0}
 *                                                 =  2
 *      -> 20 cells. Four of them are at distance 0 ("−1,−1", "−1,0", "0,−1",
 *         "0,0"), so the tie-break by key decides the first: "−1,−1".
 *
 * (A3) THE BORDER CROSSING, which is the whole point of the want set. Walking
 *      from (32, 32) to (96, 32) is one cell to the east, and since both are
 *      cell CENTRES the set is (A1) shifted by one column: still 21 cells, and
 *      the difference is
 *        dropped: the whole cx = −2 column of (A1), which is |cx| = 2 and
 *                 therefore only cz ∈ {−1, 0, 1}          -> 3
 *                 plus (−1, ±2), which in the shifted set ARE corners  -> 2
 *                                                          -> 5
 *        added:   the mirror image of that                 -> 5
 *
 * (A3b) AND THE SET MOVES WITHIN A CELL TOO, because the radius is measured
 *      from the POINT and not from the cell — the very reason
 *      `heightTiles.ts` re-asks on every poll instead of only on a crossing,
 *      and the reason the field does. From (63, 32), still in cell (0, 0):
 *        first = floor((63 − 128)/64) = −2, last = floor(191/64) = 2
 *        dx per column (−2 … 2): 127, 63, 0, 1, 65
 *        dz is (A1)'s:            96, 32, 0, 32, 96
 *        cx = −2: 127² = 16129, so dz² ≤ 255 -> only dz = 0          -> 1
 *        every other column clears 128 for all five rows             -> 20
 *      -> 21 cells again, but NOT the same 21: (−2, ±1) have dropped out and
 *         (2, ±2) have come in. Two out, two in.
 *
 * (A4) JUNK IN, NOTHING OUT: a NaN anchor, an infinite one and a negative
 *      radius all answer with no cells rather than with a loop over the world.
 *      A radius of 0 is the anchor's own cell and nothing else.
 *
 * ============================================================================
 * (B) THE SEED — one per (area, cell)
 * ============================================================================
 * `undergrowthCellSeed(id, cx, cz)` = `terrain:undergrowth:<id>:<cx>,<cz>`.
 * Two things hang on that string and each has its own counter-check.
 *
 * (B1) THE NAMESPACE keeps the layer out of the authored scatter's stream
 *      (`terrain:scatter:<id>:<index>`): two different strings are two
 *      different FNV-1a states, so the tufts cannot stand on the props.
 *
 * (B2) THE CELL keeps neighbours apart. Sampled with the real seed, cell
 *      (0, 0) and cell (1, 0) give point lists whose offsets INSIDE the cell
 *      differ; asked for the same cell twice, they are identical to the last
 *      bit — that is what "walking back gives the same tufts" means.
 *
 * (B3) THE RED COUNTER-CHECK, by mutating the source: the seed drops the cell
 *      and becomes `terrain:undergrowth:<id>`. Every cell then draws the same
 *      sequence of random numbers, and since each maps them onto its own box
 *      the mutant's two neighbouring cells are the SAME tuft pattern stamped
 *      out 64 m apart — measured as "the in-cell offsets are equal to the last
 *      decimal", which the real seed is asserted NOT to be.
 *
 * ============================================================================
 * (C) HOW MANY — the density, per CELL and no longer per shape
 * ============================================================================
 * (C1) THE BASE DENSITY IS 0.80/m2 (0.40 before the sight acceptance of
 *      2026-08-16, 0.15 before the camera-local rebuild). The catalog value is
 *      a SHARE of it, so the density handed to the sampler is
 *        per 100 m2 = 0.80 · 100 · min(value, 1) = 80 · value
 *      forest 0.6 -> 48 · grass 0.3 -> 24 · full 1.0 -> 80.
 *      In spacing: 1/√0.8 = 1.12 m between tufts at full value and 1.44 m at
 *      the seeded forest 0.6. UNCHANGED by the sight round of 2026-08-16,
 *      which shrank the TUFT to 60 % — so a tuft is now drawn 1.25 · 0.33 =
 *      0.41 m wide against those 1.12 m and the silhouettes no longer touch
 *      (they did at the old 0.69 m). That is a deliberate consequence and it
 *      is written down in both places: the volume of the layer now comes from
 *      the third quad of the star, not from the width of one tuft.
 *
 * (C2) ONE FULL CELL is 64 · 64 = 4096 m2, so
 *        count = round(4096/100 · 80 · value) = round(3276.8 · value)
 *        0.6 -> round(1966.08) = 1966     the number the design names
 *        0.3 -> round(983.04)  =  983
 *        1.0 -> round(3276.8)  = 3277
 *      and the sampler really places 1966 of them in a cell that lies wholly
 *      inside the shape — the count rule and `scatterInstances` must not drift
 *      apart in the last bit of a float.
 *
 * (C3) THE CEILING IS 8000 PER CELL AND CANNOT BE REACHED. The catalog value
 *      is clamped to 1, so the densest legal ground asks for 3277 — 41 % of
 *      it, and the cap would first bite at a value of 8000/3276.8 = 2.44,
 *      which the clamp forbids. That is the difference to the old per-area
 *      ceiling, which ordinary worlds hit and were silently thinned by: 1 km2
 *      at 0.6 wanted 90 000 tufts, got 20 000, i.e. 0.02/m2. Pinned as "the
 *      cap is above what full density asks", not as a number the code can
 *      produce.
 *
 * (C4) "NOT GIVEN" AND THE CLAMP, because the value crosses a JSON boundary:
 *        0 / −1 / NaN / 'thick' / null / undefined -> density 0, count 0
 *        5 -> clamped to 1 -> 3277, not 16384
 *
 * ============================================================================
 * (D) THE BLADE TEXTURE — a pure pixel function
 * ============================================================================
 * 64 × 64 RGBA, ROW 0 AT THE BOTTOM (a `DataTexture` is uploaded unflipped and
 * the quad's v = 0 is its foot). NINE blades since 2026-08-16 (seven before —
 * a fuller tuft is the other half of the closed grass floor), blade `i`:
 *   rootX  = (i + 0.5)/9 · 64      -> 3.556, 10.667, 17.778, 24.889, 32,
 *                                     39.111, 46.222, 53.333, 60.444
 *   height = [0.55, 0.725, 0.90][i mod 3] · 64 -> 35.2, 46.4, 57.6 in turn
 *   bend   = ±0.12 · 64 = ±7.68, + for even i
 *   x(t)   = rootX + bend · t²,  halfW(t) = 2.88 · (1 − t),  t = py/height
 *   cov    = clamp(halfW − |px − x| + 0.5, 0, 1),  px = c + 0.5, py = r + 0.5
 *   grey   = round(255 · (0.7 + 0.3 · py/64))     written EVERYWHERE
 *
 * (D1) THE SHAPE OF THE ARRAY: 64 · 64 · 4 = 16384 bytes, `Uint8ClampedArray`.
 *
 * (D2) A BLADE IS OPAQUE DOWN THE MIDDLE. Blade 4 has rootX = 4.5/9 · 64 = 32
 *      exactly, bend +7.68 (even i), height 46.4. In row 0 (py = 0.5):
 *        t = 0.5/46.4 = 0.01077586,  x = 32 + 7.68 · t² = 32.00089
 *        halfW = 2.88 · (1 − t) = 2.84897
 *        c = 31 -> px 31.5, |dx| = 0.50089, cov = 2.84897 − 0.50089 + 0.5
 *                  = 2.848 -> clamped to 1 -> alpha 255
 *        c = 32 -> px 32.5, |dx| = 0.49911 -> likewise 255
 *
 * (D3) …AND TRANSPARENT BETWEEN BLADES — still, at nine of them, which is the
 *      point of the count's own ceiling. Blades 4 and 5 sit at 32.001 and
 *      39.111, so c = 35 (px 35.5) is 3.50 from the one and 3.61 from the
 *      other, both past their halfW + 0.5 (3.35 and 3.36) -> alpha 0.
 *
 * (D4) THE EDGE IS ANTIALIASED, which is what the alpha cut of 0.35 is set
 *      against. Still blade 4, row 0, c = 29 -> px 29.5, |dx| = 2.50089:
 *        cov = 2.84897 − 2.50089 + 0.5 = 0.84808 -> alpha = round(216.26)
 *        = 216.  No other blade reaches that column (blade 3 stands at
 *        24.888 with halfW 2.839, i.e. 4.61 away).
 *
 * (D5) THE TIP IS NARROWER THAN THE FOOT, and it is measurable exactly. The
 *      summed coverage of ONE ROW is the summed WIDTH of the blades crossing
 *      it: a unit box filter reproduces the area of a ramp of unit slope
 *      exactly, whatever the phase (true while halfW ≥ 0.5, which holds in
 *      both rows below).
 *        row 0  (py = 0.5): every blade crosses it, 2·halfW = 5.76 · (1 −
 *          0.5/h), and nine blades are three of each height:
 *          3 · 5.678182 + 3 · 5.697931 + 3 · 5.71 = 51.2583
 *        row 46 (py = 46.5): 35.2 is long gone and 46.4 ends at py = 46.4, so
 *          only the three 57.6 blades (i = 2, 5, 8) are long enough — but
 *          blade 8 has LEANED OUT of the texture: t = 46.5/57.6 = 0.807292,
 *          x = 60.444 + 7.68 · t² = 65.45, and its whole 1.11-texel width
 *          lies past the last texel centre (63.5), so it writes nothing.
 *          Blades 2 and 5 stand at 22.78 and 34.11:
 *          2·halfW = 5.76 · 0.192708 = 1.11 each -> 2.22
 *      Both to a tolerance that only covers the 8-bit rounding of the alpha
 *      channel (±0.5/255 per texel).
 *
 * (D6) THE TOP TENTH IS EMPTY, on purpose: the tallest blade stops at 0.90 of
 *      the edge (57.6), so every row with py > 57.6 — that is r ≥ 58 — is
 *      alpha 0 from end to end. A silhouette touching the border would be cut
 *      off by the clamp instead of ending in a tip.
 *
 * (D7) THE GREY IS THE ROW'S OWN and is written into every texel, transparent
 *      ones included — a black transparent texel bleeds a dark rim into every
 *      mip level.
 *        row 0  -> round(255 · (0.7 + 0.3 · 0.5/64))  = round(179.098) = 179
 *        row 63 -> round(255 · (0.7 + 0.3 · 63.5/64)) = round(254.402) = 254
 *      and R = G = B in both.
 *
 * (D8) HOW MUCH INK THE FOOT CARRIES, exactly. Over the ten lowest rows the
 *      row rule of (D5) applies to every blade (halfW is near its maximum and
 *      the leaning tips have not yet reached each other — at py = 9.5 the
 *      largest lean is 7.68 · 0.27² = 0.56 texels, and neighbours lean the
 *      OTHER way, so 1.12 texels of relative shift against a spacing of 7.11
 *      and a covered half-extent of 2.6: no two blades overlap and "max" and
 *      "sum" are the same picture):
 *        Σ_{r=0}^{9} 5.76 · (1 − (r + 0.5)/h) = 5.76 · [10 − 50/h]
 *        h = 35.2 -> 49.418     three blades of each height, so
 *        h = 46.4 -> 51.393     3 · (49.418 + 51.393 + 52.600) = 460.23
 *        h = 57.6 -> 52.600
 *      The WHOLE texture is deliberately not pinned to a number: above the
 *      foot the blades lean across each other (±7.68 texels at the tip against
 *      a spacing of 7.11), and a texel takes the strongest blade rather than
 *      the sum, so the total is under the 2.88 · Σh = 2.88 · 417.6 = 1202.7
 *      the widths alone would give. What IS derivable is a BOUND, and it is
 *      the one worth having: the ink is at most 1202.7 texels and an
 *      antialiased edge adds at most one partly covered texel per side per
 *      row, i.e. 2 · (3·35 + 3·46 + 3·58) = 834 — so at most 2037 of the 4096
 *      texels carry any alpha at all and at least 2059 are pure hole. A tuft
 *      is mostly hole even at nine blades, which is what an alpha cut is for.
 *
 * (D9) THE RED COUNTER-CHECK: the alpha is written as a flat 255. The picture
 *      is then a solid square — 4096 texels of ink and not one transparent
 *      texel — so a material with `alphaTest` would draw two solid crossed
 *      boards. That the REAL function leaves thousands of texels fully
 *      transparent is the counter-assertion, and it is stated against (D8)'s
 *      own bounds rather than against a recorded number: under a THIRD of the
 *      mutant's ink (at most 1202.7 of 4096) and at least 2059 pure holes
 *      where the mutant has none. Nine blades instead of seven move both, and
 *      the bound moves with them.
 *
 * ============================================================================
 * (E) THE LOD LADDER — moved here from section (K) of smoke_scatter_math
 * ============================================================================
 * (E1) HOW TALL, out of the instance's own yaw. SIXTY PER CENT of the
 *      0.4 … 0.7 m the layer stood at until the sight round of 2026-08-16
 *      ("the blades could be a little smaller"), i.e. 0.24 … 0.42 m — ankle-
 *      to shin-high on the 1.70 m figure:
 *        h(yaw) = 0.24 + 0.18 · frac(yaw / 2π)
 *        yaw 0 -> 0.24 · π -> 0.33 (the geometry's own height) ·
 *        1.5π -> 0.24 + 0.135 = 0.375 · 2π -> 0.24 (one full turn is the same
 *        blade) · NaN / 'x' -> 0.24, never a NaN scale (which removes the
 *        instance instead of shrinking it)
 *      Both ends are exactly 0.6 of the old pair, which is the one arithmetic
 *      relation the decision consisted of and is asserted as such.
 *
 * (E2) HOW FAR — its own ladder, half the props':
 *        share(d) = 1 up to 30 m, then 1 − (d − 30)/(60 − 30), 0 past 60 m
 *        0 -> 1 · 30 -> 1 · 37.5 -> 0.75 · 45 -> 0.5 · 52.5 -> 0.25 ·
 *        60 -> 0 · 60.001 -> 0 · NaN -> 0
 *      THE FLOOR IS 0 AND THE PROPS' IS 0.25, the one place the two ladders
 *      disagree on purpose: at 45 m the scatter still draws everything while
 *      the carpet is halved, at 60 m the scatter is at 0.85 while the carpet
 *      is gone. Asserted side by side, so a copy of the props' constants
 *      cannot pass.
 *
 * (E3) WHICH tufts survive — properties, never a table:
 *        - inside 30 m all 1000 are drawn;
 *        - at 60 m none is (share exactly 0), which is what makes the missing
 *          hysteresis right: nothing can pop at the cull line;
 *        - STABLE: the set at 45 m built twice is the same set;
 *        - MONOTONE: the set at 52.5 m is a SUBSET of the one at 37.5 m;
 *        - the COUNT is the share within 5 % of 1000 · share;
 *        - tuft 0 (hash 0) is drawn as long as anything is: 59.9 m yes,
 *          60 m no.
 *
 * ============================================================================
 * (F) THE LOOK — a star of quads with an alpha cut, built for real
 * ============================================================================
 * (F1) THE GEOMETRY of one tuft at the reference height 0.33 m: THREE cards
 *      in a star, twelve vertices, base at y = 0 (B16) and 0.33 · 1.25 =
 *      0.4125 m wide (half-width 0.20625). Card `q` is the xy-plane card
 *      turned by `UNDERGROWTH_STAR_DEG[q]` about +Y, so its own +X axis is
 *      (cos, 0, −sin) and its FIRST vertex is (−halfW·cos, 0, +halfW·sin):
 *        q = 0, 0°:   cos 1, sin 0            -> (−0.20625, 0, 0)
 *        q = 1, 55°:  cos 0.5735764, sin 0.8191520
 *                     -> (−0.1183001, 0, 0.1689501)
 *        q = 2, 118°: cos −0.4694716, sin 0.8829476
 *                     -> (+0.0968285, 0, 0.1821079)
 *      THREE and not two because two cards seen from the side ARE a row — one
 *      edge-on, one flat — which is the finding word for word ("one sees very
 *      much that it is always a row of blades, and it lacks volume").
 *
 * (F1a) THE STAR IS NOT SYMMETRIC, for the reason the old pair was 80° and not
 *      90°: three planes at exactly 60° repeat every third of a turn and the
 *      eye finds the grid. Read back OUT of the vertices — the angle of card q
 *      is atan2(z, −x) of its first vertex, which is 0 / 55 / 118 — the GAPS
 *      are 55°, 63° and 62° (the third to the first is 180 − 118).
 *      THE RED COUNTER-CHECK is the fully symmetric star: mutating the source
 *      list to [0, 60, 120] gives gaps of exactly 60, 60, 60 and moves the
 *      third card's first vertex from x = +0.0968285 to +0.103125 (halfW/2) —
 *      a difference of 0.0063 m, measured at the angle rather than guessed at
 *      from a picture.
 *
 * (F1b) THE NORMALS POINT UP — all twelve of them (0, 1, 0), which is not what
 *      `computeVertexNormals` would give a vertical card. A card's own normal
 *      is horizontal, so under a sun at the zenith `dot(N, L)` is 0 and the
 *      whole carpet loses the sun at midday: with this world's noon lighting
 *      (sun 2.25 overhead, hemisphere 1.55, fill ≈ 0.25) that is 1.55 against
 *      the 4.05 the GROUND beneath receives — a dark stain on a bright meadow.
 *      Pointing them up lights the tuft exactly like the ground it grows from.
 *
 * (F1c) …AND EVERY CARD IS WOUND BOTH WAYS: 36 indices over those same 12
 *      vertices, the second eighteen being the first six triangles reversed.
 *      three flips the normal of a BACK face, so one winding plus `DoubleSide`
 *      would give a tuft 4.05 from one side and — at N = (0, −1, 0) — the
 *      hemisphere's ground colour with no sun from the other, i.e. the same
 *      tuft swinging by 2.6× as the camera orbits it. Both windings make both
 *      faces FRONT faces, so nothing is ever flipped and the material stays
 *      `FrontSide`. Back-face culling still draws six triangles per tuft from
 *      any one direction.
 *
 * (F2) THE MATERIAL is alpha-CUT and not transparent: `alphaTest` 0.35,
 *      `transparent` false, `castShadow` off on the mesh. That is what keeps a
 *      cell of a thousand tufts in the opaque pass — one draw call, no
 *      sorting. `side` is `FrontSide` for the reason in (F1c), and that is not
 *      a step back from "both faces are drawn": the geometry draws them.
 *
 * (F3) THE TINT is the kind's own colour times 0.75 (the authored tuft's
 *      logic), because the texture is greyscale: #6a994e -> (0.4·0.75,
 *      0.6·0.75, 0.306·0.75) in linear-ish terms — asserted through three's
 *      own `Color` so the colour space of the comparison is three's, not ours.
 *      KEPT after (F1b): the tuft and its ground now take the same light, so
 *      0.75 is pure albedo — times the texture's mean grey of ≈ 0.85 that is
 *      about 0.64 of the ground's own colour, a growth a third darker than
 *      what it grows out of.
 *
 * (F4) THE CHAIN IS ABSOLUTE. `applySway` first, `applyOcclusionFade` after
 *      it, both CHAINED into `onBeforeCompile` — so the combined program cache
 *      key of a material on a kind that blows at 0.06 m reads
 *      `ground-sway@0.06+occlusion-corridor`. An assignment by either would
 *      throw the other away and the key would be one of the two alone.
 *
 * (F5) THE RED COUNTER-CHECK: `alphaTest` drops out of the material. three
 *      then reports 0, i.e. every texel of the quad is drawn and the tuft is
 *      three solid boards — the picture (D9) describes from the texture side.
 *
 * ============================================================================
 * (F6) THE SHADE OF ONE TUFT — `instanceColor`, and no drift
 * ============================================================================
 * The third answer to the sight round: "they should have different shades of
 * colour". Every tuft carries a per-instance MULTIPLIER on the material
 * colour, mixed between two ends out of a hash of WHERE IT STANDS.
 *
 * (F6a) THE TWO ENDS, by hand from the two swings (brightness 0.12, hue 0.06,
 *      written per channel as `1 ∓ (bright ± hue)` so the pair sums exactly):
 *        A = (1 − 0.12 − 0.06, 1 − 0.12, 1 − 0.12 + 0.06) = (0.82, 0.88, 0.94)
 *        B = (1 + 0.12 + 0.06, 1 + 0.12, 1 + 0.12 − 0.06) = (1.18, 1.12, 1.06)
 *      A is the darker, colder green and B the brighter, yellower one; A + B
 *      is (2, 2, 2) to the last bit.
 *
 * (F6b) THE MIX IS STRAIGHT: h = 0 -> A, h = 1 -> B, h = 0.5 -> (1, 1, 1),
 *      i.e. exactly the material colour. h = 0.25 -> (0.91, 0.94, 0.97) and
 *      h = 0.75 -> (1.09, 1.06, 1.03) fall out of the same line. Junk (NaN, a
 *      string, undefined) is the MIDDLE and never a NaN colour — an instance
 *      must not be removed by arithmetic (the rule `undergrowthHeight`
 *      follows for the scale).
 *
 * (F6c) NO DRIFT, which is the property the whole feature hangs on: the mean
 *      tint over a field must be the terrain kind's own colour, or every
 *      meadow in the world changes green. The hash is uniform on [0, 1), so
 *      the mean is (A + B)/2 = (1, 1, 1) — measured over 1000 tufts standing
 *      on a 1 m grid, within 2 % per channel.
 *      THE RED COUNTER-CHECK is a ONE-SIDED mixture (the mutant halves the
 *      mix parameter, so the field only ever draws from A to the middle): its
 *      mean h is ≈ 0.25 and its mean tint therefore ≈ (0.91, 0.94, 0.97) —
 *      9 % off on red, i.e. four times outside the band the real one holds.
 *
 * (F6d) THE HASH IS ON THE POSITION AND NOT ON THE INDEX, and that is not a
 *      matter of taste: the LOD thins the layer by `instanceHash(index) <
 *      share`, so an index-keyed shade would be perfectly correlated with the
 *      thinning. At 45 m (share 0.5) exactly the instances with hash < 0.5
 *      survive, whose mean hash is ≈ 0.25 — the carpet would lose its bright
 *      half between 30 m and 60 m. Both numbers are measured side by side over
 *      the survivors of 2000 instances at 45 m: the index hash means ≈ 0.25,
 *      the position hash means ≈ 0.5.
 *
 * (F6e) AND THE SHADE TRAVELS WITH THE MATRIX. The binning COMPACTS the drawn
 *      tufts into the front of the buffer, so slot ≠ index; a colour buffer
 *      left in index order would hand each drawn tuft the shade of whichever
 *      instance the compaction displaced, and the whole carpet would repaint
 *      itself on every LOD tick. Measured at the consumer: for every drawn
 *      slot, the colour in `mesh.instanceColor` is the tint of the POSITION in
 *      `mesh.instanceMatrix` at that same slot — EXACTLY, all 3183 of them,
 *      which is what `undergrowthShade`'s `Math.fround` buys: the shade is
 *      keyed on the position as the buffer stores it, so re-deriving it from
 *      that buffer cannot disagree with the build by a rounding.
 *      THE RED COUNTER-CHECK removes the colour half of the compaction and
 *      counts how many slots then disagree — hundreds, not zero.
 *
 * ============================================================================
 * (G) THE FIELD, END TO END — cells appear, are binned, and disappear
 * ============================================================================
 * Built with a flat ground (`heightAt` = 0), one painted shape covering
 * everything at value 0.6 and no footprints.
 *
 * (G1) NOTHING IS BUILT BEFORE THERE IS AN ANCHOR: `setAreas` alone leaves the
 *      group empty. The window follows the play, and before the first tick
 *      there is no play to follow.
 *
 * (G2) THE ANCHOR BUILDS THE WANT SET: after `setAnchor(32, 32)` the group
 *      holds one mesh per cell of (A1) — 21 — and each of them has room for
 *      exactly the 1966 instances of (C2), because the shape covers the whole
 *      cell.
 *
 * (G3) NOTHING IS DRAWN UNTIL IT IS BINNED: every mesh is `visible === false`
 *      with `count === 0` until the first `tick`. A buffer filled for one
 *      camera must not be shown at the count of another.
 *
 * (G4) WHAT THE TICK DRAWS, as an area integral. The layer is thinned from
 *      30 m and gone at 60 m, so the drawn instances of a camera standing on
 *      flat ground at the anchor are
 *        0.48/m2 · ∫₀^60 share(r) · 2πr dr
 *        = 0.48 · [ π·30² + 2π·(r² − r³/90) from 30 to 60 ]
 *        = 0.48 · [ 2827.43 + 2π·(1200 − 600) ]
 *        = 0.48 · [ 2827.43 + 3769.91 ] = 0.48 · 6597.34 = 3167
 *      — the fill-rate figure the density decision was taken against, and it
 *      did NOT move in the sight round of 2026-08-16 because the density did
 *      not: about three thousand tufts in view, now of three quads each, i.e.
 *      19 000 alpha-tested triangles after back-face culling against the
 *      12 700 of the old pair. The PIXELS went the other way: 3 quads at 36 %
 *      of their old area (0.6 in each dimension) against 2 at 100 % is
 *      3 · 0.36 / 2 = 0.54 of the fill the layer used to cost.
 *      to within a few per cent — the hash is a hash, not a quota. And EVERY
 *      drawn instance is within 60 m of the camera, which is the property the
 *      integral is only a consequence of.
 *
 * (G5) THE WINDOW MOVES WITH THE ANCHOR: `setAnchor(96, 32)` is one cell east
 *      and leaves 21 meshes standing, five of which are new (A3); the step to
 *      (63, 32) inside the same cell exchanges two of them (A3b) and leaves
 *      the other nineteen as the very same objects — not merely the same
 *      count, so a rebuild disguised as a no-op cannot pass.
 *
 * (G6) `dispose` empties the group.
 *
 * (G7) A BORDER DOES NOT THICKEN THE CARPET. Paint a second shape with no
 *      undergrowth of its own over the eastern half of the world and the wood
 *      keeps only its western half — about 1966/2 ≈ 983 tufts per full cell,
 *      NOT 1966 squeezed into half the ground.
 *
 *      That is what `triesPerPoint: 1` buys and why the cell case needs it.
 *      The shared sampler re-rolls a rejected candidate up to twelve times,
 *      because a RING fills only part of its bounding box and a shape sampled
 *      without re-rolls would come out thinner than its density. A CELL is its
 *      own bounding box, so nothing is ever rejected for missing the ring —
 *      and the rejections that are left (a building's footprint, ground
 *      painted over this shape) are exactly the ones that have to SUBTRACT.
 *      Asserted from both sides: the same cell sampled the sampler's default
 *      way tops itself back up to the full 1966.
 *
 * (G8) A FOOTPRINT ON THE OTHER SIDE OF THE WORLD COSTS NOTHING. Every
 *      candidate of every cell used to be turned into the frame of EVERY
 *      placed location (`pointInFootprint`: two multiplications and a sine
 *      each), so a world with two hundred places paid two hundred of those on
 *      each of ~1966 candidates per cell — while the player walks. The cell now
 *      keeps only the footprints whose CIRCUMSCRIBED box (`half · √2`, so the
 *      turn never has to be read and nothing that could block is dropped)
 *      meets it.
 *
 *      MEASURED, not asserted about the source alone: the footprint handed in
 *      is an object whose `pos_x` is a getter that counts its reads. Both the
 *      pre-filter and `pointInFootprint` read that field exactly once into a
 *      local before doing anything else, so the count is "how often was this
 *      place looked at at all".
 *        a 10 m place at (5000, 5000), anchor (32, 32): 21 reads — ONE box
 *          test per built cell (A1) and not one per candidate.
 *        a 20 m place at (32, 32): its circumscribed box runs 17.86 … 46.14 on
 *          both axes, so it lies wholly inside the anchor's own cell 0 … 64
 *          and inside no other -> 21 + 1966, the 21 box tests plus one
 *          evaluation for each candidate of that single cell. That second row
 *          is what proves the counter would have noticed a miss.
 *      And the far place changes no tuft: the cell's instance count is the
 *      same 1966 with it and without it.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as THREE from 'three';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const LOD_SRC = join(ROOT, 'client3d/src/scene/scatterLod.ts');
const UG_SRC = join(ROOT, 'client3d/src/scene/undergrowth.ts');
const GROUND_SRC = join(ROOT, 'client3d/src/scene/ground.ts');

/** `scatterLod.ts` has no import at all (see its header), so a transpile is
 *  all it takes. */
async function loadLod() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'undergrowth-'));
  try {
    const source = await readFile(LOD_SRC, 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'module.mjs');
    await writeFile(file, out.code, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/**
 * Bundle `undergrowth.ts` together with the wind patch it is handed and the
 * shared sampler it draws from, and import the lot. `external: ['three']`
 * keeps node's own three the only one in play, which is what lets sections
 * (F) and (G) inspect REAL materials and REAL instanced meshes.
 *
 * `mutate` rewrites the BUILT text before the import — that is how (B3), (D9)
 * and (F5) get a wrong module to compare against without a second copy of the
 * code lying around to rot.
 */
async function loadField(mutate) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-ug-'));
  try {
    const entry = `export * from '${UG_SRC}';\n`
      + `export { applySway } from '${GROUND_SRC}';\n`
      + "export { scatterInstances, scatterSeed } from '@anima/scene-render';\n";
    const built = await esbuild.build({
      stdin: { contents: entry, resolveDir: dir, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'undergrowth.mjs'), external: ['three', 'three/*'],
    });
    const text = built.outputFiles[0].text;
    const source = mutate ? mutate(text) : text;
    const file = join(dir, 'undergrowth.mjs');
    await writeFile(file, source, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/** Section (B3)'s mutant: the seed forgets the CELL, so every cell of an area
 *  draws the same sequence of random numbers — one tuft pattern stamped out
 *  across the world every 64 m. */
function seedWithoutCell(text) {
  const anchor = /return `terrain:undergrowth:\$\{areaId\}:\$\{cx\},\$\{cz\}`;/;
  if (!anchor.test(text)) throw new Error('the cell seed is no longer where the probe looks');
  return text.replace(anchor, 'return `terrain:undergrowth:${areaId}`;');
}

/** Section (D9)'s mutant: every texel is opaque, so the blades stop being a
 *  silhouette and the alpha cut has nothing left to cut. */
function opaqueTexture(text) {
  const anchor = 'out[o + 3] = Math.round(255 * cov);';
  if (!text.includes(anchor)) throw new Error('the alpha write is no longer where the probe looks');
  return text.replace(anchor, 'out[o + 3] = 255;');
}

/** Section (F5)'s mutant: the material loses its alpha cut and draws every
 *  texel of all three quads — three solid boards per tuft. */
function noAlphaTest(text) {
  const anchor = 'alphaTest: UNDERGROWTH_ALPHA_TEST,';
  if (!text.includes(anchor)) throw new Error('the alpha cut is no longer where the probe looks');
  return text.replace(anchor, '');
}

/** Section (F1a)'s mutant: the star becomes fully symmetric, so a field of
 *  tufts repeats every third of a turn. */
function symmetricStar(text) {
  const anchor = 'UNDERGROWTH_STAR_DEG = [0, 55, 118]';
  if (!text.includes(anchor)) throw new Error('the star angles are no longer where the probe looks');
  return text.replace(anchor, 'UNDERGROWTH_STAR_DEG = [0, 60, 120]');
}

/** Section (F6c)'s mutant: the mix only ever runs from A to the middle, so
 *  the whole layer drifts towards the dark end of its own palette. */
function oneSidedTint(text) {
  const anchor = 'Number.isFinite(v) ? Math.min(Math.max(v, 0), 1) : 0.5;';
  if (!text.includes(anchor)) throw new Error('the tint mix is no longer where the probe looks');
  return text.replace(anchor,
    'Number.isFinite(v) ? Math.min(Math.max(v, 0), 1) * 0.5 : 0.5;');
}

/** Section (F6e)'s mutant: the binning compacts the matrices but leaves the
 *  colours in index order, so a drawn tuft wears its displaced neighbour's
 *  shade. */
function noColorCompaction(text) {
  const anchor = 'if (colBuf) copyColor(layer.srcColor, i, colBuf, n);';
  if (!text.includes(anchor)) throw new Error('the colour compaction is no longer where the probe looks');
  return text.replace(anchor, '');
}

let failed = 0;
let passed = 0;
function check(label, actual, expected, eps = 1e-9) {
  const ok = compare(actual, expected, eps);
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}`);
    console.log(`       expected ${JSON.stringify(expected)}`);
    console.log(`       actual   ${JSON.stringify(actual)}`);
  }
}

function checkNot(label, actual, forbidden, eps = 1e-9) {
  const same = compare(actual, forbidden, eps);
  if (!same) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}`);
    console.log(`       must NOT equal ${JSON.stringify(forbidden)}`);
  }
}

function compare(a, b, eps) {
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((v, i) => compare(v, b[i], eps));
  }
  if (typeof a === 'number' && typeof b === 'number') {
    return Number.isNaN(a) ? Number.isNaN(b) : Math.abs(a - b) <= eps;
  }
  if (a && b && typeof a === 'object' && typeof b === 'object') {
    const ka = Object.keys(a);
    const kb = Object.keys(b);
    return ka.length === kb.length && ka.every((k) => compare(a[k], b[k], eps));
  }
  return a === b;
}

/** The in-cell offsets of a sampled point list — what makes "these two cells
 *  are the same pattern" a measurement rather than an impression. */
function offsets(points, cx, cz, cellM) {
  return points.map((p) => [p.x - cx * cellM, p.z - cz * cellM]);
}

async function main() {
  const lod = await loadLod();
  const field = await loadField();
  const {
    UNDERGROWTH_CELL_M, UNDERGROWTH_CELL_RADIUS_M, UNDERGROWTH_CULL_M,
    UNDERGROWTH_DENSITY_PER_M2, UNDERGROWTH_FADE_M, UNDERGROWTH_H_MAX,
    UNDERGROWTH_H_MIN, UNDERGROWTH_MAX_PER_CELL, UNDERGROWTH_MIN_SHARE,
    SCATTER_MIN_SHARE, instanceHash, instanceShare, SCATTER_LOD_DEFAULTS,
    undergrowthCellCount, undergrowthDensityPer100m2, undergrowthHeight,
    undergrowthShare, undergrowthVisible,
  } = lod;
  const {
    createUndergrowthField, scatterInstances, scatterSeed,
    undergrowthCellKey, undergrowthCellSeed,
    undergrowthGeometry, undergrowthMaterial, undergrowthShade,
    undergrowthTexture, undergrowthTexturePixels, undergrowthTint,
    wantedUndergrowthCells, applySway,
    UNDERGROWTH_ALPHA_TEST, UNDERGROWTH_H_REF_M, UNDERGROWTH_TEX_SIZE,
    UNDERGROWTH_BLADES, UNDERGROWTH_TINT_A, UNDERGROWTH_TINT_B,
  } = field;
  const TAU = Math.PI * 2;

  console.log('(A) the cell raster — which cells the layer holds');
  check('A the raster is 64 m, the window 128 m',
    [UNDERGROWTH_CELL_M, UNDERGROWTH_CELL_RADIUS_M], [64, 128]);
  check('A the key is "cx,cz"', undergrowthCellKey(-2, 3), '-2,3');
  // A cell owns its LOWER edge (`Math.floor`), which a radius of 0 shows
  // directly: it answers with the anchor's own cell and nothing else.
  check('A a point is in the cell that starts at its own floor',
    [wantedUndergrowthCells(0, 0, 0), wantedUndergrowthCells(63.9, 64, 0),
      wantedUndergrowthCells(-0.1, -64, 0)],
    [['0,0'], ['0,1'], ['-1,-1']]);

  // (A1) the anchor in the middle of its cell
  const midCell = wantedUndergrowthCells(32, 32);
  check('A1 an anchor at a cell centre holds 21 cells — 25 less four corners',
    midCell.length, 21);
  check('A1 …and the nearest is its own', midCell[0], '0,0');
  check('A1 …the four corners are exactly the ones missing',
    ['-2,-2', '-2,2', '2,-2', '2,2'].filter((k) => midCell.includes(k)), []);
  check('A1 …while their neighbours along the axes are in',
    ['-2,-1', '-2,0', '2,1', '0,2'].every((k) => midCell.includes(k)), true);

  // (A2) the anchor on a corner — the asymmetric case
  const cornerCell = wantedUndergrowthCells(0, 0);
  check('A2 an anchor ON a cell corner holds 20', cornerCell.length, 20);
  check('A2 …and the tie between the four cells it touches goes by key',
    cornerCell[0], '-1,-1');
  check('A2 …the cell whose near edge is exactly 128 m away is still in',
    cornerCell.includes('2,0'), true);
  check('A2 …but its neighbour one row up is out',
    cornerCell.includes('2,1'), false);

  // (A3) the crossing
  const eastCell = wantedUndergrowthCells(96, 32);
  const dropped = midCell.filter((k) => !eastCell.includes(k));
  const added = eastCell.filter((k) => !midCell.includes(k));
  check('A3 one cell east is still 21 cells', eastCell.length, 21);
  check('A3 …five of them are new and five are gone',
    [dropped.length, added.length], [5, 5]);
  const nudged = wantedUndergrowthCells(63, 32);
  check('A3b a step INSIDE the cell still moves the window — it is the POINT '
    + 'the radius is measured from', nudged.length, 21);
  check('A3b …two out, two in',
    [midCell.filter((k) => !nudged.includes(k)).sort(),
      nudged.filter((k) => !midCell.includes(k)).sort()],
    [['-2,-1', '-2,1'], ['2,-2', '2,2']]);

  // (A4) junk
  for (const [x, z, name] of [[NaN, 0, 'a NaN anchor'],
    [0, Infinity, 'an infinite anchor']]) {
    check(`A4 ${name} holds no cells`, wantedUndergrowthCells(x, z), []);
  }
  check('A4 a negative radius holds no cells',
    wantedUndergrowthCells(32, 32, -1), []);
  check('A4 a radius of 0 is the anchor\'s own cell and nothing else',
    wantedUndergrowthCells(32, 32, 0), ['0,0']);

  console.log('\n(B) the seed — one per (area, cell)');
  check('B1 the seed names the area AND the cell',
    undergrowthCellSeed('ta_1', -2, 3), 'terrain:undergrowth:ta_1:-2,3');
  check('B1 …and is not the authored scatter\'s',
    undergrowthCellSeed('ta_1', 0, 0) !== scatterSeed('ta_1', 0), true);

  // (B2) the cell keeps neighbours apart — measured on the in-cell offsets
  const CELL = UNDERGROWTH_CELL_M;
  const cellRing = (cx, cz) => [
    [cx * CELL, cz * CELL], [(cx + 1) * CELL, cz * CELL],
    [(cx + 1) * CELL, (cz + 1) * CELL], [cx * CELL, (cz + 1) * CELL],
  ];
  const sampleCell = (cx, cz, seed) => scatterInstances({
    ring: cellRing(cx, cz),
    areaM2: CELL * CELL,
    densityPer100m2: undergrowthDensityPer100m2(0.6),
    seed,
    maxPoints: UNDERGROWTH_MAX_PER_CELL,
  });
  const cell00 = sampleCell(0, 0, undergrowthCellSeed('ta_1', 0, 0));
  const cell10 = sampleCell(1, 0, undergrowthCellSeed('ta_1', 1, 0));
  check('B2 the same cell asked twice is the same tufts',
    sampleCell(0, 0, undergrowthCellSeed('ta_1', 0, 0)).slice(0, 5),
    cell00.slice(0, 5));
  checkNot('B2 …while the cell next door is a different pattern',
    offsets(cell10, 1, 0, CELL).slice(0, 5),
    offsets(cell00, 0, 0, CELL).slice(0, 5));

  // (B3) the red counter-check
  const noCell = await loadField(seedWithoutCell);
  const stamped00 = sampleCell(0, 0, noCell.undergrowthCellSeed('ta_1', 0, 0));
  const stamped10 = sampleCell(1, 0, noCell.undergrowthCellSeed('ta_1', 1, 0));
  check('B3 the "seed without the cell" mutant stamps ONE pattern everywhere',
    offsets(stamped10, 1, 0, CELL).slice(0, 5),
    offsets(stamped00, 0, 0, CELL).slice(0, 5));
  check('B3 …which the real seed measurably is not',
    compare(offsets(cell10, 1, 0, CELL).slice(0, 5),
      offsets(cell00, 0, 0, CELL).slice(0, 5), 1e-9), false);

  console.log('\n(C) how many — the density, per cell');
  check('C1 the base density is 0.80 tufts per square metre',
    UNDERGROWTH_DENSITY_PER_M2, 0.80);
  check('C1 the share becomes 80 * value per 100 m2',
    [undergrowthDensityPer100m2(0.6), undergrowthDensityPer100m2(0.3),
      undergrowthDensityPer100m2(1)], [48, 24, 80]);
  check('C2 a full cell of the seeded forest carries 1966 tufts',
    undergrowthCellCount(0.6), 1966);
  check('C2 …of the seeded grass 983, at full value 3277',
    [undergrowthCellCount(0.3), undergrowthCellCount(1)], [983, 3277]);
  check('C2 …and the sampler really places 1966 of them',
    cell00.length, 1966);
  check('C3 the ceiling is 8000 per cell', UNDERGROWTH_MAX_PER_CELL, 8000);
  check('C3 …which full density does not come near',
    undergrowthCellCount(1) < UNDERGROWTH_MAX_PER_CELL, true);
  for (const [bad, name] of [[0, '0'], [-1, '-1'], [NaN, 'NaN'],
    ['thick', 'a string'], [null, 'null'], [undefined, 'undefined']]) {
    check(`C4 a value of ${name} grows nothing`,
      [undergrowthCellCount(bad), undergrowthDensityPer100m2(bad)], [0, 0]);
  }
  check('C4 a hand-edited 5 is clamped to full density, not multiplied',
    undergrowthCellCount(5), 3277);

  console.log('\n(D) the blade texture — a pure pixel function');
  const N = UNDERGROWTH_TEX_SIZE;
  const tex = undergrowthTexturePixels(N);
  const at = (r, c) => (r * N + c) * 4;
  check('D1 the texture is 64 x 64 and nine blades wide',
    [N, UNDERGROWTH_BLADES], [64, 9]);
  check('D1 …and comes back as RGBA bytes',
    [tex.length, tex instanceof Uint8ClampedArray], [64 * 64 * 4, true]);
  check('D2 a blade is opaque down its middle',
    [tex[at(0, 31) + 3], tex[at(0, 32) + 3]], [255, 255]);
  check('D3 …and there is nothing at all between two blades',
    tex[at(0, 35) + 3], 0);
  check('D4 the blade edge is antialiased, not a hard step',
    tex[at(0, 29) + 3], 216);
  const rowInk = (r) => {
    let sum = 0;
    for (let c = 0; c < N; c += 1) sum += tex[at(r, c) + 3] / 255;
    return sum;
  };
  check('D5 the foot row carries 51.26 texels of ink', rowInk(0), 51.2583, 0.15);
  check('D5 …and the row at 46.5 only 2.22 — the taper, measured',
    rowInk(46), 2.22, 0.05);
  let topInk = 0;
  for (let r = 58; r < N; r += 1) topInk += rowInk(r);
  check('D6 the top tenth of the texture is empty', topInk, 0);
  check('D7 the grey is the row\'s own, and greyscale',
    [tex[at(0, 0)], tex[at(0, 0) + 1], tex[at(0, 0) + 2], tex[at(63, 0)]],
    [179, 179, 179, 254]);
  let footInk = 0;
  for (let r = 0; r < 10; r += 1) footInk += rowInk(r);
  check('D8 the ten lowest rows carry exactly 460.23 texels of ink',
    footInk, 460.234, 0.5);
  let ink = 0;
  let clear = 0;
  for (let r = 0; r < N; r += 1) {
    for (let c = 0; c < N; c += 1) {
      const a = tex[at(r, c) + 3];
      ink += a / 255;
      if (a === 0) clear += 1;
    }
  }
  check('D8 the whole texture stays under the 1202.7 texels the widths allow',
    ink < 1202.7, true);
  check('D8 …so at least 2059 of its 4096 texels are pure hole',
    clear >= 2059, true);

  // (D9) the red counter-check
  const solid = await loadField(opaqueTexture);
  const solidTex = solid.undergrowthTexturePixels(N);
  let solidClear = 0;
  let solidInk = 0;
  for (let i = 3; i < solidTex.length; i += 4) {
    solidInk += solidTex[i] / 255;
    if (solidTex[i] === 0) solidClear += 1;
  }
  check('D9 the "always opaque" mutant is a solid square, not a tuft',
    [solidInk, solidClear], [64 * 64, 0]);
  check('D9 …which is measurably not what the real function draws',
    [ink < solidInk / 3, clear >= 2059], [true, true]);

  console.log('\n(E) the LOD ladder — its own numbers, beside the props\'');
  check('E the layer is drawn to 60 m and thinned from 30 m',
    [UNDERGROWTH_FADE_M, UNDERGROWTH_CULL_M], [30, 60]);
  check('E …and it fades to NOTHING, where the props keep a quarter',
    [UNDERGROWTH_MIN_SHARE, SCATTER_MIN_SHARE], [0, 0.25]);
  check('E a tuft is shin-high, 0.24 .. 0.42 m',
    [UNDERGROWTH_H_MIN, UNDERGROWTH_H_MAX], [0.24, 0.42]);
  check('E …which is exactly 60 % of the 0.4 .. 0.7 m of the round before',
    [UNDERGROWTH_H_MIN / 0.4, UNDERGROWTH_H_MAX / 0.7], [0.6, 0.6], 1e-12);
  check('E1 yaw 0 is the shortest blade', undergrowthHeight(0), 0.24);
  check('E1 yaw pi is the middle — the geometry\'s own height',
    undergrowthHeight(Math.PI), 0.33);
  check('E1 yaw 1.5pi', undergrowthHeight(1.5 * Math.PI), 0.375);
  check('E1 a full turn is the same blade again', undergrowthHeight(TAU), 0.24);
  for (const [bad, name] of [[NaN, 'NaN'], ['x', 'a string'],
    [undefined, 'undefined']]) {
    check(`E1 a yaw of ${name} is the shortest blade, never a NaN scale`,
      undergrowthHeight(bad), 0.24);
  }
  check('E2 share at 0 m is 1', undergrowthShare(0), 1);
  check('E2 …at 30 m still 1', undergrowthShare(30), 1);
  check('E2 …at 37.5 m 0.75', undergrowthShare(37.5), 0.75);
  check('E2 …at 45 m half the carpet', undergrowthShare(45), 0.5);
  check('E2 …at 52.5 m a quarter', undergrowthShare(52.5), 0.25);
  check('E2 …and at 60 m nothing at all', undergrowthShare(60), 0);
  check('E2 past the cull distance nothing', undergrowthShare(60.001), 0);
  check('E2 a NaN distance draws nothing', undergrowthShare(NaN), 0);
  check('E2 at 45 m the props draw everything while the carpet is halved',
    [instanceShare(45, SCATTER_LOD_DEFAULTS), undergrowthShare(45)], [1, 0.5]);
  check('E2 …and at 60 m they are at 0.85 while it is gone',
    [instanceShare(60, SCATTER_LOD_DEFAULTS), undergrowthShare(60)], [0.85, 0]);
  const grown = (d, n = 1000) => {
    const out = [];
    for (let i = 0; i < n; i += 1) if (undergrowthVisible(i, d)) out.push(i);
    return out;
  };
  check('E3 inside 30 m every tuft is drawn', grown(30).length, 1000);
  check('E3 at the cull distance none is — nothing can pop there',
    grown(60).length, 0);
  check('E3 the set at 45 m is the SAME set when asked again',
    grown(45), grown(45));
  const near375 = new Set(grown(37.5));
  check('E3 what is drawn at 52.5 m is still drawn at 37.5 m',
    grown(52.5).filter((i) => !near375.has(i)).length, 0);
  for (const [d, share] of [[37.5, 0.75], [45, 0.5], [52.5, 0.25]]) {
    const n = grown(d).length;
    check(`E3 ${d} m draws ${1000 * share} of 1000, within 5 % (got ${n})`,
      Math.abs(n - 1000 * share) <= 0.05 * 1000 * share, true);
  }
  check('E3 tuft 0 survives as long as anything of the layer does',
    [undergrowthVisible(0, 59.9), undergrowthVisible(0, 60)], [true, false]);

  console.log('\n(F) the look — a star of quads with an alpha cut');
  check('F the geometry stands at the middle of the height span',
    UNDERGROWTH_H_REF_M, 0.33);
  const geo = undergrowthGeometry(UNDERGROWTH_H_REF_M);
  const gp = geo.getAttribute('position');
  check('F1 three cards: twelve vertices', gp.count, 12);
  check('F1 card 0 spans +-0.20625 m at z = 0',
    [gp.getX(0), gp.getY(0), gp.getZ(0), gp.getX(1)],
    [-0.20625, 0, 0, 0.20625], 1e-6);
  check('F1 …card 1 is it turned by 55 degrees',
    [gp.getX(4), gp.getY(4), gp.getZ(4)],
    [-0.1183001, 0, 0.1689501], 1e-6);
  check('F1 …and card 2 by 118 — past the right angle, into the third plane',
    [gp.getX(8), gp.getY(8), gp.getZ(8)],
    [0.0968285, 0, 0.1821079], 1e-6);
  geo.computeBoundingBox();
  check('F1 the tuft STANDS on the ground (B16): y runs 0 .. 0.33',
    [geo.boundingBox.min.y, geo.boundingBox.max.y], [0, 0.33], 1e-6);
  // The angle of a card, read back OUT of its first vertex
  // (−halfW·cos, 0, halfW·sin) — so the assertion is about the built geometry
  // and not about the constant the builder read.
  const cardDeg = (g, q) => {
    const a = (Math.atan2(g.getZ(q * 4), -g.getX(q * 4)) * 180) / Math.PI;
    return Math.round(a * 1e6) / 1e6;
  };
  check('F1a the three planes stand at 0, 55 and 118 degrees',
    [cardDeg(gp, 0), cardDeg(gp, 1), cardDeg(gp, 2)], [0, 55, 118], 1e-4);
  check('F1a …so the gaps are UNEVEN — 55, 63, 62 and not three times 60',
    [cardDeg(gp, 1) - cardDeg(gp, 0), cardDeg(gp, 2) - cardDeg(gp, 1),
      180 - cardDeg(gp, 2)], [55, 63, 62], 1e-4);
  const gn = geo.getAttribute('normal');
  const upNormals = [];
  for (let i = 0; i < gn.count; i += 1) {
    upNormals.push([gn.getX(i), gn.getY(i), gn.getZ(i)]);
  }
  check('F1b every normal points STRAIGHT UP, not out of the card',
    upNormals, new Array(12).fill([0, 1, 0]));
  const idx = geo.getIndex();
  check('F1c …and every card is wound both ways: 36 indices, not 18',
    idx.count, 36);
  const tri = (n) => [idx.getX(n * 3), idx.getX(n * 3 + 1), idx.getX(n * 3 + 2)];
  const rev = (t) => [t[0], t[2], t[1]];
  check('F1c …the second eighteen being the first six triangles reversed',
    [tri(6), tri(7), tri(8), tri(9), tri(10), tri(11)],
    [rev(tri(0)), rev(tri(1)), rev(tri(2)), rev(tri(3)), rev(tri(4)),
      rev(tri(5))]);

  // (F1a) the red counter-check — the fully symmetric star
  const evenStar = await loadField(symmetricStar);
  const evenGeo = evenStar.undergrowthGeometry(UNDERGROWTH_H_REF_M);
  const evenPos = evenGeo.getAttribute('position');
  check('F1a the "0/60/120" mutant repeats every third of a turn',
    [cardDeg(evenPos, 0), cardDeg(evenPos, 1), cardDeg(evenPos, 2)],
    [0, 60, 120], 1e-4);
  check('F1a …and its third card starts 0.0063 m further out in x',
    evenPos.getX(8) - gp.getX(8), 0.103125 - 0.0968285, 1e-6);
  checkNot('F1a …neither of which the real star does',
    [cardDeg(gp, 0), cardDeg(gp, 1), cardDeg(gp, 2)], [0, 60, 120], 1e-4);

  const dataTex = undergrowthTexture();
  check('F the one shared texture is a 64 x 64 DataTexture',
    [dataTex.image.width, dataTex.image.height], [64, 64]);
  const mat = undergrowthMaterial(dataTex, '#6a994e', 0.06, applySway);
  check('F2 the material CUTS its alpha at 0.35',
    [mat.alphaTest, UNDERGROWTH_ALPHA_TEST], [0.35, 0.35]);
  check('F2 …and is NOT transparent — it stays in the opaque pass',
    mat.transparent, false);
  check('F2 …and it never draws a BACK face, so no normal is ever flipped',
    mat.side, THREE.FrontSide);
  check('F2 …through the blade texture', mat.map === dataTex, true);
  const want = new THREE.Color('#6a994e').multiplyScalar(0.75);
  check('F3 the tint is the kind\'s colour times 0.75',
    [mat.color.r, mat.color.g, mat.color.b], [want.r, want.g, want.b], 1e-9);
  check('F4 wind and camera corridor are BOTH on it, in that order',
    mat.customProgramCacheKey(), 'ground-sway@0.06+occlusion-corridor');

  // (F5) the red counter-check
  const cut = await loadField(noAlphaTest);
  const cutMat = cut.undergrowthMaterial(cut.undergrowthTexture(), '#6a994e',
                                         0.06, cut.applySway);
  check('F5 the "no alpha cut" mutant draws every texel of all three quads',
    cutMat.alphaTest, 0);
  checkNot('F5 …which the real material does not', mat.alphaTest, 0);

  console.log('\n(F6) the shade of one tuft — instanceColor, and no drift');
  check('F6a the dark end is 0.82 / 0.88 / 0.94 of the kind\'s colour',
    [...UNDERGROWTH_TINT_A], [0.82, 0.88, 0.94], 1e-12);
  check('F6a …and the bright end 1.18 / 1.12 / 1.06',
    [...UNDERGROWTH_TINT_B], [1.18, 1.12, 1.06], 1e-12);
  check('F6a …so the two of them sum to exactly (2, 2, 2)',
    [UNDERGROWTH_TINT_A[0] + UNDERGROWTH_TINT_B[0],
      UNDERGROWTH_TINT_A[1] + UNDERGROWTH_TINT_B[1],
      UNDERGROWTH_TINT_A[2] + UNDERGROWTH_TINT_B[2]], [2, 2, 2], 1e-12);
  check('F6b h = 0 is the dark end', undergrowthTint(0), [...UNDERGROWTH_TINT_A],
    1e-12);
  check('F6b h = 1 is the bright end', undergrowthTint(1),
    [...UNDERGROWTH_TINT_B], 1e-12);
  check('F6b h = 0.5 is the kind\'s own colour, untouched',
    undergrowthTint(0.5), [1, 1, 1], 1e-12);
  check('F6b h = 0.25 and h = 0.75 sit on the same line',
    [undergrowthTint(0.25), undergrowthTint(0.75)],
    [[0.91, 0.94, 0.97], [1.09, 1.06, 1.03]], 1e-12);
  for (const [bad, name] of [[NaN, 'NaN'], ['x', 'a string'],
    [undefined, 'undefined']]) {
    check(`F6b a shade of ${name} is the middle, never a NaN colour`,
      undergrowthTint(bad), [1, 1, 1], 1e-12);
  }
  check('F6b …and one outside [0, 1] is CLAMPED to an end, not extrapolated',
    [undergrowthTint(-1), undergrowthTint(2)],
    [[...UNDERGROWTH_TINT_A], [...UNDERGROWTH_TINT_B]], 1e-12);

  // (F6c) no drift — measured over a grid of a thousand standing places
  const meanTint = (tintOf, shadeOf) => {
    const sum = [0, 0, 0];
    for (let i = 0; i < 1000; i += 1) {
      const t = tintOf(shadeOf((i % 40) - 20, Math.floor(i / 40) - 12));
      sum[0] += t[0]; sum[1] += t[1]; sum[2] += t[2];
    }
    return sum.map((v) => v / 1000);
  };
  const tintMean = meanTint(undergrowthTint, undergrowthShade);
  check(`F6c the mean tint over 1000 tufts is the kind's own colour within `
    + `2 % (got ${tintMean.map((v) => v.toFixed(4)).join(', ')})`,
    tintMean.every((v) => Math.abs(v - 1) <= 0.02), true);
  const oneSided = await loadField(oneSidedTint);
  const driftMean = meanTint(oneSided.undergrowthTint, oneSided.undergrowthShade);
  check('F6c the "one-sided mix" mutant drifts to the dark end of the palette',
    driftMean, [0.91, 0.94, 0.97], 0.02);
  check('F6c …i.e. measurably outside the band the real mix holds',
    Math.abs(driftMean[0] - 1) > 0.04, true);

  // (F6d) the position hash is not the LOD's index hash
  const survivors = [];
  for (let i = 0; i < 2000; i += 1) if (undergrowthVisible(i, 45)) survivors.push(i);
  const meanOf = (xs) => xs.reduce((a, b) => a + b, 0) / xs.length;
  const byIndex = meanOf(survivors.map((i) => instanceHash(i)));
  const byPos = meanOf(survivors.map((i) => undergrowthShade((i % 50) * 1.3,
                                                             Math.floor(i / 50) * 1.3)));
  check(`F6d an index-keyed shade would lose its bright half at 45 m `
    + `(mean ${byIndex.toFixed(3)})`, Math.abs(byIndex - 0.25) <= 0.02, true);
  check(`F6d …while the POSITION-keyed one keeps the whole palette `
    + `(mean ${byPos.toFixed(3)})`, Math.abs(byPos - 0.5) <= 0.05, true);
  // …and the palette is really used from end to end, not clustered in the
  // middle: over a thousand places both ends are reached to within 1 %.
  let lowest = 1;
  let highest = 0;
  for (let i = 0; i < 1000; i += 1) {
    const h = undergrowthShade((i % 40) * 0.7 - 14, Math.floor(i / 40) * 0.7 - 8);
    if (h < lowest) lowest = h;
    if (h > highest) highest = h;
  }
  check(`F6d the whole palette is in use, both ends included `
    + `(${lowest.toFixed(3)} … ${highest.toFixed(3)})`,
    [lowest < 0.01, highest > 0.99], [true, true]);
  checkNot('F6d …while the tuft a metre away has its own shade',
    undergrowthShade(12.5, -7.25), undergrowthShade(13.5, -7.25));
  check('F6d a junk position is the middle of the palette, not a NaN',
    [undergrowthShade(NaN, 0), undergrowthShade(0, Infinity)], [0.5, 0.5]);

  console.log('\n(G) the field, end to end');
  const BIG = 2000;
  const area = {
    id: 'ta_wood',
    kind: 'forest',
    ring: [[-BIG, -BIG], [BIG, -BIG], [BIG, BIG], [-BIG, BIG]],
    bounds: [-BIG, -BIG, BIG, BIG],
    value: 0.6,
    color: '#6a994e',
    swayM: 0.06,
  };
  const grown3d = createUndergrowthField({ heightAt: () => 0, applySway });
  grown3d.setAreas([area], []);
  check('G1 nothing is built before there is an anchor',
    grown3d.group.children.length, 0);
  grown3d.setAnchor(32, 32);
  check('G2 the anchor builds one mesh per wanted cell',
    grown3d.group.children.length, midCell.length);
  check('G2 …each with room for the cell\'s own 1966 tufts',
    grown3d.group.children.map((m) => m.instanceMatrix.count),
    midCell.map(() => 1966));
  check('G3 and nothing is DRAWN until the first tick',
    grown3d.group.children.some((m) => m.visible || m.count > 0), false);
  check('G3 …nor does any of it cast a shadow',
    grown3d.group.children.every((m) => m.castShadow === false), true);

  const cam = new THREE.Vector3(32, 0, 32);
  grown3d.tick(cam);
  let drawn = 0;
  let farthest = 0;
  const m4 = new THREE.Matrix4();
  const at3 = new THREE.Vector3();
  for (const mesh of grown3d.group.children) {
    drawn += mesh.count;
    for (let i = 0; i < mesh.count; i += 1) {
      m4.fromArray(mesh.instanceMatrix.array, i * 16);
      at3.setFromMatrixPosition(m4);
      const d = at3.distanceTo(cam);
      if (d > farthest) farthest = d;
    }
  }
  check('G4 the tick draws the 3167 tufts the thinning integral asks for',
    Math.abs(drawn - 3167) <= 0.08 * 3167, true);
  check(`G4 …and not one of them past the cull distance (${farthest.toFixed(1)} m)`,
    farthest <= UNDERGROWTH_CULL_M, true);

  // (F6e) the shade travels with the matrix — measured at the CONSUMER, i.e.
  // in the two buffers three actually uploads.
  const shadeMismatch = (mod, group) => {
    let slots = 0;
    let wrong = 0;
    const mm = new THREE.Matrix4();
    const pt = new THREE.Vector3();
    for (const mesh of group.children) {
      if (!mesh.instanceColor) return { slots: 0, wrong: -1 };
      for (let i = 0; i < mesh.count; i += 1) {
        mm.fromArray(mesh.instanceMatrix.array, i * 16);
        pt.setFromMatrixPosition(mm);
        const want = mod.undergrowthTint(mod.undergrowthShade(pt.x, pt.z));
        slots += 1;
        for (let k = 0; k < 3; k += 1) {
          if (Math.abs(mesh.instanceColor.array[i * 3 + k] - want[k]) > 1e-6) {
            wrong += 1;
            break;
          }
        }
      }
    }
    return { slots, wrong };
  };
  const shades = shadeMismatch(field, grown3d.group);
  check(`G4b every drawn slot wears the shade of the tuft standing there `
    + `(${shades.slots} slots)`, [shades.slots > 3000, shades.wrong], [true, 0]);
  // …and the red counter-check: the colour half of the compaction removed.
  const looseColor = await loadField(noColorCompaction);
  const loose3d = looseColor.createUndergrowthField({
    heightAt: () => 0, applySway: looseColor.applySway,
  });
  loose3d.setAreas([area], []);
  loose3d.setAnchor(32, 32);
  loose3d.tick(cam);
  const loose = shadeMismatch(looseColor, loose3d.group);
  check('G4b the "colours stay in index order" mutant misplaces hundreds of '
    + `them (${loose.wrong} of ${loose.slots})`, loose.wrong > 300, true);
  loose3d.dispose();

  const before = grown3d.group.children.slice();
  grown3d.setAnchor(63, 32);
  const nudgedMeshes = grown3d.group.children.slice();
  check('G5 a step inside the cell exchanges the two cells of (A3b)…',
    [nudgedMeshes.length,
      before.filter((m) => !nudgedMeshes.includes(m)).length],
    [21, 2]);
  check('G5 …and leaves the other nineteen as the very same meshes',
    before.filter((m) => nudgedMeshes.includes(m)).length, 19);
  grown3d.setAnchor(96, 32);
  check('G5 a border crossing moves the window, and it stays 21 cells',
    grown3d.group.children.length, eastCell.length);
  check('G5 …five of the meshes standing at the cell centre really went',
    before.filter((m) => !grown3d.group.children.includes(m)).length, 5);
  grown3d.dispose();
  check('G6 dispose empties the group', grown3d.group.children.length, 0);

  // (G7) the border, and the re-roll that must not happen there
  const path = {
    id: 'ta_path',
    kind: 'path',
    ring: [[0, -BIG], [BIG, -BIG], [BIG, BIG], [0, BIG]],
    bounds: [0, -BIG, BIG, BIG],
    value: 0,
    color: '#a0a0a0',
    swayM: 0,
  };
  const halved = createUndergrowthField({ heightAt: () => 0, applySway });
  halved.setAreas([area, path], []);
  halved.setAnchor(-32, 32);
  // The anchor's own cell (-1, 0) runs x −64 … 0, so it lies wholly west of
  // the path and keeps everything — and it is built FIRST, the want set being
  // nearest-first.
  check('G7 a cell wholly west of the border still carries its 1966',
    halved.group.children[0].instanceMatrix.count, 1966);
  // The want set at (−32, 32) is (A1) shifted one column west, so the columns
  // east of the border (cx = 0 and 1) grow nothing at all: 21 cells less
  // cx = 0 (five rows) and cx = 1 (three, being a |cx| = 2 column) -> 13.
  check('G7 …and the thirteen cells west of it are the only ones with a layer',
    halved.group.children.length, 13);
  const straddling = scatterInstances({
    ring: cellRing(-1, 0),
    areaM2: CELL * CELL,
    densityPer100m2: undergrowthDensityPer100m2(0.6),
    seed: undergrowthCellSeed('ta_wood', -1, 0),
    occluders: [[[-32, -BIG], [BIG, -BIG], [BIG, BIG], [-32, BIG]]],
    maxPoints: UNDERGROWTH_MAX_PER_CELL,
    triesPerPoint: 1,
  });
  check('G7 half the cell covered keeps about half the tufts, not all of them',
    Math.abs(straddling.length - 983) <= 0.1 * 983, true);
  const topped = scatterInstances({
    ring: cellRing(-1, 0),
    areaM2: CELL * CELL,
    densityPer100m2: undergrowthDensityPer100m2(0.6),
    seed: undergrowthCellSeed('ta_wood', -1, 0),
    occluders: [[[-32, -BIG], [BIG, -BIG], [BIG, BIG], [-32, BIG]]],
    maxPoints: UNDERGROWTH_MAX_PER_CELL,
  });
  check('G7 …while the sampler\'s DEFAULT re-roll tops it back up to 1966 — '
    + 'double density against the border', topped.length, 1966);
  halved.dispose();

  // (G8) the footprint pre-filter, measured on a counting footprint
  const counting = (x, z, w) => {
    const fp = { pos_z: z, plan_width_m: w, yaw_deg: 0, reads: 0 };
    // BOTH the cell's pre-filter and `pointInFootprint` read the centre's x
    // EXACTLY once into a local before doing anything else, so this counter is
    // "how often was this place looked at at all".
    Object.defineProperty(fp, 'pos_x', {
      get() { fp.reads += 1; return x; },
      enumerable: true,
    });
    return fp;
  };
  const far = counting(5000, 5000, 10);
  const withFar = createUndergrowthField({ heightAt: () => 0, applySway });
  withFar.setAreas([area], [far]);
  withFar.setAnchor(32, 32);
  check('G8 a place on the other side of the world costs one box test per '
    + 'built cell and not one per candidate', far.reads, midCell.length);
  check('G8 …and it changes no tuft: the anchor cell still carries its 1966',
    withFar.group.children[0].instanceMatrix.count, 1966);
  withFar.dispose();
  const near = counting(32, 32, 20);
  const withNear = createUndergrowthField({ heightAt: () => 0, applySway });
  withNear.setAreas([area], [near]);
  withNear.setAnchor(32, 32);
  check('G8 …while a place INSIDE the anchor cell — and inside no other — is '
    + 'asked once per candidate on top of that',
    near.reads, midCell.length + 1966);
  withNear.dispose();

  console.log('\n(H) the wiring, pinned by reading the source');
  const ugSrc = await readFile(UG_SRC, 'utf8');
  const groundSrc = await readFile(GROUND_SRC, 'utf8');
  check('H the layer samples every cell under its own (area, cell) seed',
    ugSrc.includes('seed: undergrowthCellSeed(area.id, cx, cz),'), true);
  check('H …and hands the sampler its own per-cell ceiling',
    ugSrc.includes('maxPoints: UNDERGROWTH_MAX_PER_CELL,'), true);
  check('H the cell subtracts its rejections instead of re-rolling them',
    ugSrc.includes('triesPerPoint: 1,'), true);
  check('H the footprints are cut to the cell by their circumscribed box',
    /const reach = \(w \/ 2\) \* Math\.SQRT2;\s*return meetsCell\(/.test(ugSrc),
    true);
  check('H …and it is the cut list the sampler gets',
    ugSrc.includes('footprints: nearFootprints,'), true);
  check('H the shade is written at build and compacted at every binning',
    ugSrc.includes('mesh.setColorAt(i, tint.setRGB(tr, tg, tb));')
      && ugSrc.includes('if (colBuf) copyColor(layer.srcColor, i, colBuf, n);'),
    true);
  check('H the chain is wind first, camera corridor after it',
    /applySway\(mat, swayM, UNDERGROWTH_H_REF_M\);\s*applyOcclusionFade\(mat\);/
      .test(ugSrc), true);
  check('H ground.ts no longer builds the layer itself',
    /buildUndergrowth|UNDERGROWTH_MAX_PER_AREA/.test(groundSrc), false);
  check('H …it hands over the shapes on every rebuild',
    groundSrc.includes('undergrowth.setAreas(undergrowthAreas, footprints);'),
    true);
  check('H …the height tiles\' own anchor',
    groundSrc.includes('undergrowth.setAnchor(x, z);'), true);
  check('H …and the LOD beat',
    groundSrc.includes('undergrowth.tick(cameraPos);'), true);
  // The authored tuft cones are untouched by this round, and the one place
  // that still patches a material of its own in ground.ts is theirs.
  const fadeCalls = groundSrc.match(/applyOcclusionFade\(mat\);/g);
  check('H the authored tuft keeps its own patched material, and only it',
    fadeCalls ? fadeCalls.length : 0, 1);
  const seedCalls = groundSrc.match(/scatterSeed\(/g);
  check('H …and scatterSeed is still used exactly once, for the authored rows',
    seedCalls ? seedCalls.length : 0, 1);

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
