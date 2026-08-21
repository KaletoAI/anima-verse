# @anima/scene-render

Die geteilten Renderer-Routinen des Szenen-Vertrags
(`/home/dev/projekte/shared/schnittstellen-3d.md`, Teil B). Konsumenten:

- `frontend/` — Admin-Grundriss-Vorschau und 2D-Untergrund
- `client3d/` — 3D-Weltkarte

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

| Export | Vertrag | Zweck |
|---|---|---|
| `placeModelSpec`, `FIT_BOX_MARGIN` | § B2 | DIE Platzierungs-Routine: Fix-Euler → messen → skalieren → Yaw als Eltern-Rotation → BBox auf `bottom_y`/`anchor` setzen |
| `applyClipOutline`, `disposeClipMaterials`, `CLIP_MAX_POINTS` | § B1 | Diorama auf den Raum-Grundriss beschneiden (Fragment-Discard per Punkt-im-Polygon) |
| `applyCutouts`, `CUTOUT_MAX_POLYS/-POINTS` | § B1 | Flächen-Locations: Löcher aus dem Location-Modell schneiden — derselbe Paritätstest, INVERTIERT und über eine Union mehrerer Polygone; `setEnabled` schaltet sie per Uniform mit der Innenansicht |
| `buildPlate`, `buildWall`, `buildExtra`, `buildPlaceholder`, `wallLength` | § B1 | Die Primitiv-Builder: Kontur→Extrusion bzw. Box aus `from`/`to`/`base_y`, Extra-Box aus Zentrum+Größe, Platzhalter-Box für ein Prop ohne Mesh |
| `plateTargets`, `wallTargets` | § B5a | Welche Zahlen ein Primitiv treffen muss (Wand: `base_y`/`top_y`/`centre.x`/`centre.z`; Platte: `top_y`, bei Körper `bottom_y`) |
| `SpecVerifier`, `VERIFY_EPS` | § B5a | BBox-vs-Spec-Diff mit ε 0,01 m — Rechnen statt Screenshots |
| Payload-Typen | § B1 | `ScenePayload` und alles darin |

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

## Kein Build-Schritt

Das Paket wird als TypeScript-Quelle konsumiert (npm-Workspace-Symlink,
`exports` zeigt auf `src/index.ts`). Vite und `tsc` beider Seiten übersetzen es
mit. `npm install` im Wurzelverzeichnis genügt.

## Ändern

Eine Änderung hier trifft **beide** Renderer. Die Abnahme dafür ist numerisch
und in beiden Apps vorhanden:

```bash
# Admin: Grundriss-Vorschau öffnen, ✓-Schalter, Konsole lesen
#        -> "[verify] N numbers checked, no deviation > 0.01 m"
# Client: http://localhost:5183/?verify=1 laden, ~5 min warten
#        -> window.__sceneVerify, Summe über alle Locations
```

Stand 2026-07-26: Vollclient-Verify **1757 geprüfte Zahlen, 0 Abweichungen,
85/85 Modelle** (Welt `anima-dome`, 26 Locations mit Rezept). Die absolute Zahl
gilt nur, solange die Welt stillsteht — die **0 Abweichungen** sind die
eigentliche Aussage.
