# @anima/scene-render

Die geteilten Renderer-Routinen des Szenen-Vertrags
(`docs/schnittstellen-3d.md`, Teil B). Konsumenten:

- `frontend/` — Admin-Grundriss-Vorschau und 2D-Untergrund der Karte
- `client3d/` — 3D-Weltkarte

Kein Build-Schritt, kein Publish: npm-Workspace-Symlink, `exports` zeigt
direkt auf `src/index.ts`, Vite und `tsc` beider Seiten übersetzen mit.

## Warum es das gibt

Beide Renderer hatten diese Routinen vorher je einmal selbst. Der
Clipping-Shader (§ B1) wurde nachweislich **zweimal unabhängig gebaut** — und
die zwei Fassungen waren dann nicht einmal gleich: die eine lud das Polygon
geschlossen mit fester Array-Größe und brach den Shader-Loop dynamisch ab, die
andere setzte `CLIP_N` als Compile-Zeit-Konstante. Auch die Payload-Typen
standen doppelt und waren auseinandergelaufen (`elevator_*` hier Pflicht, dort
optional).

Die Regel daraus: **was beide Renderer geometrisch brauchen, gehört hierher —
nicht in eine der beiden Apps.**

## Inhalt

Eine Zeile je Modul, mit ALLEN Exporten — `scripts/smoke_docs_scene_render_readme.py`
hält Tabelle und `src/index.ts` zusammen (jeder Export hat eine Zeile, jede
Zeile nennt nur, was es gibt). Die §-Nummern verweisen auf
`docs/schnittstellen-3d.md`.

| Modul | Vertrag | Zweck | Exporte |
|---|---|---|---|
| `place.ts` | § B2 | **DIE** Platzierungs-Routine: Fix-Euler → messen → skalieren → Yaw als Eltern-Rotation → BBox auf `bottom_y`/`anchor` setzen | `placeModelSpec` · Typen: `PlaceOptions` |
| `leafPivot.ts` | § C1 | Der Drehpunkt eines Türblatts aus `door.leaf_bbox` (Roh-Modellraum) und die Fix-Matrix dazu | `leafPivot`, `fixMatrix` · Typen: `LeafBox`, `FixEuler`, `LeafPivotSpec` |
| `surface.ts` | § C3 | Die EINE Sample-Formel des gebackenen Oberflächen-Rasters — zeilengleicher Zwilling von `app/core/model_surface.surface_height_at` | `surfaceHeightAt`, `highestSurfaceAt`, `surfaceScale` · Typen: `PlacedSurface`, `SurfacePlacement` |
| `storeyGround.ts` | § A16.9 | Wo eine Platzierung auf Etage 0 steht: Boden-Datum der Kachel, Hebung und Neu-Datierung | `flatGround`, `storeyGroundLift`, `storeyGroundRelift`, `tileDatumStep` · Typen: `GroundSampler`, `StoreyGroundStep`, `TileDatumStep` |
| `clip.ts` | § B1 | Diorama auf den Raum-Grundriss beschneiden (Fragment-Discard per Punkt-im-Polygon) | `applyClipOutline`, `disposeClipMaterials`, `CLIP_MAX_POINTS` |
| `clipRetarget.ts` | § A8 | Einen Bibliotheks-Clip als Rotation GEGEN die Rest-Pose des Referenz-Rigs lesen und auf eine fremde Bind-Pose setzen | `normBoneName`, `restPoseOf`, `restCorrections`, `bindRelativeValues`, `bindRelativeClip` · Typen: `RestPose`, `RestCorrection` |
| `depthCut.ts` | § C3 | Der Tiefenschnitt eines Props (`cut_plane`) — der halbe Tisch an der Wand | `applyDepthCut`, `disposeCutMaterials` |
| `slotMaterials.ts` | § C3 | Textur-Slots eines Props: das Bild im Rahmen, der Look der Scheibe, die Material-Presets | `applySlotMaterials`, `disposeSlotMaterials`, `GLASS_PRESET`, `MATERIAL_PRESETS` · Typen: `SlotTextureLoader` |
| `mirrorSurface.ts` | § C3 | Preset `mirror`: aus einem Slot wird ein planarer Reflektor, mit app-weitem, rotierendem Budget | `planeOfFaces`, `MirrorBudget`, `sharedMirrorBudget`, `attachMirror`, `disposeMirror`, `mirrorPlaneOf` · Typen: `MirrorPlane`, `MirrorOptions`, `MirrorInfo` |
| `cutouts.ts` | § B1 | Flächen-Locations: Löcher aus dem Location-Modell schneiden (invertierter Clip-Test über eine Union); `setEnabled` schaltet sie mit der Innenansicht | `applyCutouts` · Typen: `CutoutHandle` |
| `worldHeight.ts` | § A16 | Die EINE Höhenantwort der offenen Welt: Kachel-Index, bilineares Sampling, Spannweite, Boden-Strahl | `bilinear`, `latticeSample`, `sampleWorldHeight`, `worldHeightRange`, `tileKeyAt`, `heightAt`, `finestStep`, `rayGroundHit` · Typen: `RayGroundOpts`, `WorldHeightField`, `WorldHeightTiles`, `WorldHeightTileStats` |
| `hillshade.ts` | § A16.10 | Die Relief-Schattierung der 2D-Karten (Azimut 315°, Überhöhung `MAP_RELIEF_Z_FACTOR`) | `hillshadeImage`, `MAP_RELIEF_Z_FACTOR` · Typen: `HillshadeOpts`, `HillshadeImage` |
| `layerCut.ts` | § A16.7 | Der Layer-Schnitt des Bodens — welches Material hier liegt, samt GLSL für beide Renderer | `decodeSd`, `layerPairAt`, `layerSdAt`, `layerSdBlockAt`, `layerWeight`, `lcPushedSd`, `packLayerWindow`, `terrainLayerGlsl`, `terrainLayerVertexGlsl`, `topLayerAt` · Typen: `LayerMaskWindow`, `TerrainLayer`, `TerrainLayerBatch`, `TerrainLayerFormat`, `TerrainLayerIndex`, `TerrainLayerOverview`, `TerrainLayerTile` |
| `groundAreas.ts` | § A1.5 | Die Geometrie einer gemalten Terrain-Fläche (Ring → Shape → BufferGeometry), plus die Polygon-Grundrechnungen | `buildAreaGeometry`, `signedArea`, `polygonArea`, `cleanRing`, `shapePoints` · Typen: `AreaGeometry`, `Point2` |
| `scatter.ts` | § A9a/§ A9b | Streu-Props: wie viele, wo, wie gedreht, wie tief — deterministisch aus Seed und Fläche, mit Fremdabständen und Zellen-Fenster | `propGroundFit`, `scatterInstances`, `scatterSeed`, `scatterWantedCount`, `scatterSeedHash`, `scatterVariantIndex`, `scatterYaw`, `reshuffleEpoch`, `seededRandom`, `pointInRing`, `pointInFootprint`, `worldToLocalXZ`, `footprintBlocks`, `footprintDistance`, `scatterClearM`, `propBoxFootprint`, `propBoxFootprints`, `SCATTER_CLEAR_HEIGHT_RATIO`, `SCATTER_MAX_PER_ENTRY`, `scatterCellAt`, `scatterCellInstances`, `scatterCellRing`, `scatterCellSeed`, `scatterCellSpan`, `scatterCellsInBox`, `scatterCellCountInBox`, `wantedScatterCells`, `SCATTER_CELL_M`, `SCATTER_CELLS_MAX`, `SCATTER_MAX_PER_CELL` · Typen: `PropGroundFit`, `ScatterCellOptions`, `ScatterEntry`, `ScatterFootprint`, `ScatterInstance`, `ScatterOccupancy`, `ScatterPlaceMode`, `ScatterPoint2`, `ScatterPropBox`, `ScatterSampleOptions`, `ScatterYawMode` |
| `scatterAxis.ts` | § A9a | Platzierung RELATIV zum Umriss: lokale Achse, Pol der Unzugänglichkeit, Stationen am Rand | `ringEdgeAxis`, `ringSelectedEdges`, `ribbonSelectedEdges`, `lineAxis`, `areaAxis`, `polylabel`, `ringStations`, `scatterEdgeInstances`, `scatterCenterInstance` · Typen: `PoleOfInaccessibility`, `RingStation`, `RingStationOptions`, `ScatterEdgeOptions`, `ScatterCenterOptions` |
| `occupancy.ts` | § A9a | Was frühere Zeilen schon gepflanzt haben — der Belegungsraster, an dem spätere vorbei müssen | `OccupancyGrid`, `cellOccupancy` · Typen: `CellGrids`, `CellOccupancy` |
| `stroke.ts` | § A9 | Wie eine gezeichnete Linie gebogen wird, bevor sie verbreitert wird (Stil, Seed, Mittellinie, Stationen) | `STROKE_STYLES`, `isStrokeStyle`, `strokeSeed`, `decorateStroke`, `MAX_DECORATED_POINTS`, `STROKE_SPACING_DEFAULT_M`, `STROKE_AMPLITUDE_DEFAULT_M`, `strokeCentreLine`, `strokeStations`, `alongSeed` · Typen: `StrokeStyle`, `StrokeDeco`, `DecoratedStroke`, `StrokeRecipe`, `StrokeStationOptions` |
| `verify.ts` | § B5a | BBox-vs-Spec-Diff mit ε 0,01 m — Rechnen statt Screenshots | `SpecVerifier`, `VERIFY_EPS` · Typen: `PrimitiveTarget`, `VerifyRow` |
| `primitives.ts` | § B1 | Die Primitiv-Builder: Kontur→Extrusion, Box aus `from`/`to`/`base_y`, Extra-Box aus Zentrum+Größe, Platzhalter-Box — plus ihre Verify-Soll-Felder | `buildPlate`, `buildWall`, `buildExtra`, `buildPlaceholder`, `wallLength`, `plateTargets`, `wallTargets` |
| `types.ts` | § B1 | `ScenePayload` und alles darin — EIN Typsatz für beide Renderer; `pickVariant` ist die eine Auflösungsregel der Modellstufen | `pickVariant`, `pickModelVariant` · Typen: `ScenePayload`, `ScenePlate`, `SceneWall`, `SceneExtra`, `SceneModelSpec`, `ModelTier`, `SceneMarker`, `SceneStyle`, `SceneOpening`, `SceneRoom`, `SceneFloor`, `SceneBoundaryOpening`, `SceneCorridor`, `SceneCutPlane`, `SceneDoorway`, `SceneProblem`, `SceneSlotValues`, `SceneStairs`, `SceneSurface` |
| `figure.ts` | § A3/§ A4 | Wo eine Figur auf eine markierte Fläche trifft: Vertragsgröße 1,70 m, Hüft-Absenkung, Wurzel-y | `FIGURE_HEIGHT_M`, `anchorFigureBind`, `clipHipsDrop`, `figureRootY`, `hipsTrackMedian` |
| `placeGeometry.ts` | § C4 | Slots eines Platzes und die beiden Hälften eines Paar-Clips, für einen Renderer ohne komponiertes Payload | `markerSlots`, `pairYaw`, `rotateXZ`, `pairPoints` · Typen: `XZ` |
| `materials.ts` | § A9 | Wie eine Oberflächen-ART gemalt wird (inkl. Wasser-Fließen und Himmel-Uniform) — beide Renderer zeigen denselben See | `surfaceMaterial`, `updateSurfaceMaterials`, `setSurfaceSky`, `surfaceTimeUniform`, `surfaceSkyUniform`, `surfaceWaveNormal`, `waterFlowFactor`, `WATER_FLOW_FACTOR_MIN`, `WATER_FLOW_SPEED_DEFAULT_M_S`, `WATER_FLOW_SPEED_MAX_M_S` · Typen: `SurfaceMaterialSpec`, `SurfaceMaterialOptions` |
| `waterfall.ts` | § C5 | Wo ein Fluss fällt — aus derselben Achse gelesen, auf der schon der Spiegel steht | `strokeWidthM`, `waterfallsFrom`, `WATERFALL_MIN_DROP_M`, `WATERFALL_MIN_SLOPE` · Typen: `Waterfall`, `WaterfallAxis`, `WaterfallKnot` |

**Bewusst NICHT hier:** Kamera, LOD, Fades, Culling-Anwendung, Labels,
Wegfindung, NPC-Logik, Editor-Overlays. Sicht-Zustand bleibt pro App.

**Der Schnitt bei den Primitiven: Geometrie hier, MATERIAL beim Aufrufer.**
Genau dort unterscheiden sich die beiden Seiten echt — der Client kachelt
Surface-Texturen im Weltmaßstab, der Admin malt Vorschau-Farben mit
Raum-Palette und Auswahl-Hervorhebung. `side`/`transparent`/Deckkraft sind
deshalb Material-Entscheidungen und fallen nicht hier. Ebenso bleiben
Schatten-Flags und Culling-Registrierung beim Aufrufer. Jeder Builder baut um
seinen EIGENEN Ursprung und platziert nichts: der Client rechnet ums
Kachelzentrum, der Admin um den Ursprung — dieselbe Trennung, die
`placeModelSpec` über `origin` löst.

Die Berichte bleiben ebenfalls bei den Konsumenten: der Admin zeichnet ein
Overlay, der Client schreibt nach `window.__sceneVerify`. Geteilt ist nur die
Rechnung.

**`three` steht in `peerDependencies`**, nicht in `dependencies`: die beiden
Apps bringen ihre eigene Kopie mit, und zwei Kopien im selben Bild wären zwei
verschiedene `Vector3`-Klassen.

## Zwei Eigenheiten

**`three` kommt als Parameter, nie als Import.** Ein statischer Import zöge die
Bibliothek in das Haupt-Bundle des Admins, der sie verzögert nachlädt.
Typ-Importe sind unkritisch, die verschwinden beim Übersetzen.

**`placeModelSpec` hat zwei Optionen**, weil die Aufrufer sich echt
unterscheiden und das Verhalten nicht eingeebnet werden sollte:

```ts
placeModelSpec(THREE, source, spec)                            // Admin
placeModelSpec(THREE, source, spec, { clone: false, clip: false })  // 3D-Client
```

- `clone` — die Admin-Vorschau platziert dasselbe gecachte Objekt mehrfach und
  muss klonen; der Client übergibt es zur Übernahme.
- `clip` — der Client clippt selbst, nachdem er eingehängt hat: sein Polygon
  liegt relativ zum Kachelzentrum, der Shader misst aber in Weltkoordinaten.

## Ändern

`npm install` im Wurzelverzeichnis genügt — es gibt nichts zu bauen.
Eine Änderung hier trifft **beide** Renderer. Die Abnahme dafür ist numerisch
und in beiden Apps vorhanden:

```bash
# Admin: Grundriss-Vorschau öffnen, ✓-Schalter, Konsole lesen
#        -> "[verify] N numbers checked, no deviation > 0.01 m"
# Client: http://localhost:5183/?verify=1 laden, ~5 min warten
#        -> window.__sceneVerify, Summe über alle Locations
```

**0 Abweichungen** ist die Aussage. Die absolute Zahl geprüfter Werte hängt
an der Welt (Zahl der Locations, Modelle und Primitive) und sagt für sich
nichts — sie taugt nur als Vergleich zwischen zwei Läufen über derselben,
stillstehenden Welt.
