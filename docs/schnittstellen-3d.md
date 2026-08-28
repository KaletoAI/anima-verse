# Schnittstellen 3D — Gesamtvertrag v6 „Gebiete" (2026-08-19)

> **v6 — Die Location ist ein gezeichnetes Polygon, alle Inhalte sind Meter.**
> Beschlossen 2026-08-19 (User-Freigabe Option 2, `development_instructions/`
> `analyse-gebiete-und-unterbereiche.md` + `plan-assets-im-szenenkontext.md`,
> Etappe 1). **Kein Migrationscode** — Welten werden neu aufgebaut; ein
> Quadrat ist ab jetzt nur ein Spezialfall des Polygons. Diese Liste
> überschreibt alles Folgende, wo es widerspricht:
>
> 1. **Der Fußabdruck ist ein Polygon, kein Quadrat.** Eine Location trägt
>    `map3d.boundary`: eine geschlossene Punktfolge in **lokalen Metern
>    relativ zum Anker-Pin** (`pos_x`, `pos_z`) und dessen Drehung
>    (`yaw_deg`) — transformiert mit der EINEN Abbildung aus § A1.1
>    (unverändert gültig). ≤ 64 Punkte, auto-geschlossen, im Uhrzeigersinn;
>    Selbstschnitt ist eine Warnung in `problems[]`, kein Fehler. **Konkave
>    Umrisse sind zugelassen** (E1.1). Unplatziert bleibt `pos_x/pos_z null`.
>    Ohne `boundary` hat eine Location KEINE Fläche (nur einen Pin) — das
>    frühere „ohne Anker 10-m-Quadrat" entfällt ersatzlos.
>
>    > **Übergangs-Synthese beendet 2026-08-19.** Bis dahin hat
>    > `world_geometry.effective_boundary` einer Location, die nur noch den
>    > alten `plan_width_m`-Regler trug, ein zentriertes Quadrat
>    > untergeschoben, damit Altwelten spielbar blieben. Diese Synthese ist
>    > gelöscht, zusammen mit allen Quadrat-Helfern des Moduls
>    > (`point_in_footprint`, `footprint_distance`, `footprint_corners`,
>    > `segment_hits_footprint`, `footprint_hits_aabb`, `placed_footprint`).
>    > **Ohne gezeichnete Boundary keine Fläche** — nirgends: nicht im
>    > Server (Nav-Grid, `location_at_point`, Plateau-Pass, Eintritts-Gate),
>    > nicht im Payload (`boundary: null`, `plan_width_m: null`), nicht in
>    > einem der beiden Renderer (bloßer Pin). **Alt-Welten repariert der
>    > Seed-Knopf**: „Seed missing boundaries (N)" im Karten-Editor
>    > (`POST /world/locations/seed-boundaries`) schreibt jeder platzierten
>    > Location ohne Umriss genau dieses Quadrat als ECHTE, editierbare
>    > Boundary. Eine ausdrückliche Nutzer-Aktion, kein Fallback-Leser.
> 2. **Das Bruchteil-System ist gelöscht.** Raum-Rechtecke (`x/y/w/d`),
>    Raum-`outline`, Kurven-Kontrollpunkte, Marker-`at`, Prop-`at`,
>    `model_at`, Fahrstuhl — alles wird in **Metern im lokalen Rahmen**
>    gespeichert und ausgeliefert (Szenengraph Welt → Location(Pin+Yaw) →
>    Raum(Position+Drehung) → Inhalt). `[0,1]²`-Domäne,
>    `plan_width_m`-Regler und der Anker-Zwang (`_require_scale_anchor`)
>    existieren nicht mehr. `plan_width_m`/`extent_m` bleiben AUSSCHLIESSLICH
>    als **abgeleitete Rechengröße** (Breite der Bounding-Box des Boundary-
>    Polygons) in den Payloads, damit Verbraucher-Verträge (Laderadius,
>    Viewport, Backdrop) weiterleben; `k = 1` bleibt dokumentiert konstant.
>    **`plan_width_m` ist seit 2026-08-19 KEINE EINGABE mehr**: der Sanitizer
>    (`world_ops._sanitize_map3d`) verwirft einen gesendeten Wert kommentarlos
>    und schreibt das Feld nur dort, wo eine Boundary gezeichnet ist — ohne
>    Umriss gibt es keine Breite, so wie es keine Fläche gibt. Es gibt daher
>    auch kein Eingabefeld mehr dafür (Grundriss-Editor: reine Anzeige).
>
>    > **Nr. 2 EINGELÖST (Server-Hälfte, 2026-08-19).** Ab hier gilt die
>    > folgende Feld-Semantik wörtlich; wo irgendwo unten noch eine
>    > `[0,1]`-Fraktion für eine dieser Größen steht, ist sie überschrieben.
>    > **Kein Migrationscode** — eine Welt aus der Bruchteil-Ära liefert
>    > schlicht winzige Räume; das ist die vereinbarte Neuaufbau-Semantik und
>    > wird NICHT per Sonderfall repariert.
>    >
>    > * **Raum-Rechteck `layout.x/y/w/d`** — Meter. `x/y` ist die
>    >   **Minimal-Ecke** des Raums im **LOCATION-LOKALEN Rahmen** (Ursprung =
>    >   Anker-Pin, Achsen nach § A1.1 — derselbe Rahmen, in dem
>    >   `map3d.boundary` liegt); negative Werte sind normal. `w/d` sind Meter
>    >   > 0.
>    > * **`layout.outline`** — Punkte in Metern **relativ zur eigenen
>    >   Minimal-Ecke des Raums**, also im Bereich 0…`w` / 0…`d`. Die
>    >   Kontrollpunkte von `layout.outline_curves` liegen im selben Rahmen
>    >   (dürfen die Hülle verlassen; Klemmung ±500 m statt der alten
>    >   `[-1, 2]`-Bbox-Regel). `x/y/w/d` tragen weiterhin IMMER die aus der
>    >   tessellierten Hülle gefaltete Bounding-Box.
>    > * **`layout.markers[].at`, `layout.props[].at`, `layout.model_at`** —
>    >   Meter, ebenfalls relativ zur Minimal-Ecke des Raums. Fehlendes
>    >   `model_at` heißt weiterhin „zentriert", also `[w/2, d/2]`.
>    > * **`layout.level`, `rotation`, `floor_offset_y`, `model_offset_y`,
>    >   `offset_y`, `always_visible`, `no_walls`, `clip_model`,
>    >   `surfaces`** — unverändert. (`relief_flat` ist seit Nr. 12 gelöscht;
>    >   `floor_offset_y` ist seither reine Feinjustage, keine Wasserlinie.)
>    > * **Öffnungen an Raumkanten** (`layout.openings[]`): `at` bleibt eine
>    >   **Fraktion der Kante** — ein kantenrelatives Verhältnis ist keine
>    >   Weltgröße —, `width_m`/`height_m`/`sill_m` bleiben Meter. Genauso
>    >   `map3d.boundary_openings[].at` (§ B1 Nr. 13).
>    > * **`map3d.outline`** (gezeichnete Gebäude-Kontur) und
>    >   **`map3d.elevator`** — lokale Meter wie `boundary`, keine `[0,1]²`-
>    >   Domäne mehr. Andere `[0,1]²`-Felder gibt es in `map3d` nicht.
>    > * **`_require_scale_anchor` ist GELÖSCHT** (Server). Ein Grundriss
>    >   braucht keinen Anker mehr; `plan_width_m` ist nur noch die
>    >   ABGELEITETE Bounding-Box-Breite der Boundary und wird beim Speichern
>    >   aus ihr überschrieben. `location_model3d.has_scale_anchor` ist mit
>    >   entfallen.
>    > * **Speicherauflösung**: alle Meter-Felder auf **Zentimeter** gerundet
>    >   (2 Nachkommastellen) und auf **±500 m** geklemmt — dieselbe Regel wie
>    >   bei `boundary`/`plan_width_m`.
>    > * **Der komponierte Payload ändert Form UND Werte NICHT.** Er war immer
>    >   schon in Weltmetern; entfallen ist nur die Denormalisierung
>    >   `(f − 0,5) · extent_m` auf dem Weg dorthin. `scene.extent_m` bleibt
>    >   als Feld erhalten (Verbraucher-Verträge: Laderadius, Viewport,
>    >   Backdrop) und trägt weiterhin die Bounding-Box-Breite.
>    > * **~~Die Ausnahme des Relief-Stützgitters~~ — GEGENSTANDSLOS seit
>    >   Nr. 12** (2026-08-21). Sie beschrieb, wie das szenen-eigene
>    >   17 × 17-Gitter über die Bounding-Box der Boundary spannt und dafür
>    >   `scene.terrain.origin` mitbekommt. Das ganze Gitter ist gelöscht
>    >   (Nr. 12 / § A16, v5-Präambel Nr. 14): es gibt kein `scene.terrain`
>    >   mehr, keinen `terrain_frame` und keine zweite Höhenquelle neben
>    >   `h_final`.
>
> 3. **EIN Skalengesetz, jetzt wirklich überall: real_size.** `tile_fit`
>    („größte Seite füllt die Kante") ist gelöscht; auch Gebäude- und
>    Flächen-Modelle skalieren über eine **deklarierte reale Breite in
>    Metern** (Sidecar `width_m`, wie Dioramen § B2a). `map3d.size` (der
>    ]0,1]-Füllfaktor) entfällt. § B6 #8 ist damit auf Location-Ebene
>    gegenstandslos.
>
>    > **Nr. 3 EINGELÖST (2026-08-19).** Ab hier gilt wörtlich:
>    >
>    > * **Das Gebäude-/Flächen-Modell trägt `max_m` = seine DEKLARIERTE
>    >   reale Breite in Metern** (Sidecar `width_m`, gesetzt über
>    >   `POST /world/locations/{id}/model3d/width` — derselbe Setter, den
>    >   Raum-Dioramen benutzen). Ein 15-m-Stall auf einem 40-m-Grundstück
>    >   ist ein 15-m-Stall; ein Anteil am Grundstück ist keine Größe.
>    > * **`measure` bleibt `"yawed_xz"`.** „Nach der Drehung ins Grundstück
>    >   passen" ist bei einer Gebäude-Hülle weiter die sinnvolle Messung;
>    >   der Orientierungs-Fix steckt darin auf 90° GERUNDET (v5.1 Nr. 4,
>    >   unverändert) — ein fein eingestellter Fix schrumpft nichts.
>    > * **Ohne deklarierte Breite** ist `max_m` die Bounding-Box-Breite der
>    >   effektiven Boundary (`extent_m` = `plan_width_m`), und die Spec sagt
>    >   es über `width_estimated: true` (wie beim Diorama), damit die UI zur
>    >   Eichung auffordern kann. Das ist **exakt die Zahl, die `tile_fit`
>    >   mit `size = 1` lieferte** (`extent_m × 1`) — Bestandswelten rendern
>    >   also identisch weiter, bis jemand eine Breite deklariert.
>    > * **`map3d.size` IST WEG**: Sanitizer (`_sanitize_map3d`) verwirft ein
>    >   übergebenes Feld, der `Map3D`-Typ kennt es nicht mehr, der
>    >   Anteil-Regler im Gebäude-Panel ist durch den Meter-Regler ersetzt.
>    >   Kein Migrationscode, kein Alias — eine einmal gespeicherte Location
>    >   verliert das Feld.
>    > * **Für `display: "ground"` gilt dasselbe Gesetz.** Vorher war `size`
>    >   dort zwangsweise 1; jetzt füllt eine Flächen-Location ohne erklärte
>    >   Breite ihre Boundary (dieselbe Zahl) und folgt mit erklärter Breite
>    >   der Deklaration. Der ANKER ändert sich nicht (Gehfläche auf Etage 0).
> 4. **Die Level-Platte ist das triangulierte Boundary-Polygon**, nicht mehr
>    ein Quadrat; das Relief-Raster spannt über der Bounding-Box und wird am
>    Polygon geclippt (Rand-Pinning auf 0 bleibt). `_rotate_scene`
>    (90°-Kachel-Drehung des fertigen Payloads) entfällt — gedreht wird
>    ausschließlich über den Pin (§ A1.1-Kette).
> 5. **`boundary_openings` liegen auf Polygon-Kanten**: `edge` ist ein
>    Kanten-INDEX (0-basiert, Kante i = Punkt i → i+1) statt der Buchstaben
>    N/S/E/W, `at ∈ [0,1]` läuft entlang dieser Kante. Die ausgelieferten
>    Felder `at_world` + `inward` (Normale zeigt nach innen) bleiben — der
>    Client rechnet weiterhin nichts selbst.
> 6. **Punkt-in-Location: die kleinste FLÄCHE gewinnt** (E1.2, Nachfolger
>    der Kleinste-Breite-Regel in § A1.1). Überlappung bleibt legal; der
>    Karten-Apply warnt, verbietet nicht.
> 7. **Die Planierung (§ A16.4) wird ein Polygon-Distanzfeld**: innen = im
>    Polygon, Rampenring = Kanten-Distanz ≤ Rampenbreite; die Plateau-Höhe
>    wird an einem **garantiert inneren, deterministischen Punkt** gelesen
>    (nicht am Zentroid — der liegt bei konkaven Formen ggf. außerhalb).
>    `height_sig` hasht die Polygonpunkte.
> 8. **Fog of War war DEAKTIVIERT** (E1.3) und ist seit 2026-08-24 als
>    **Dunst** zurück (`plan-fog-schleier-v2.md`, § A12): halbtransparent
>    über unerkundeten Zellen, zoomabhängig, und der Server filtert die
>    Figuren darunter weg. **Die Wissens-Filterung galt durchgehend**: was
>    der Server wegen `known_locations` nicht ausliefert, existiert für den
>    Client nicht.
> 9. **`problems[]` neu: `room_outside_boundary`** — ein Raum, dessen
>    Grundriss über den Location-Umriss ragt (Warnung, kein Fehler).
>    Der Grundriss-Editor zeichnet im Viewport der Boundary-Bounding-Box
>    (Meter-Raster, Snap an Boundary-Kanten und Nachbar-Wände,
>    1,70-m-Referenzfigur); offene/geschlossene **Unterbereiche** sind die
>    Bedien-Sprache für das Flag-Paar (`always_visible` + `no_walls`) — die
>    Felder selbst bleiben. (`relief_flat` ist mit dem Szenen-Relief gelöscht,
>    Nr. 12.)
>
> 10. **~~`map3d.rotation`~~ ("Rotation on tile") — ERSATZLOS GESTRICHEN**
>     (2026-08-20). Sie drehte das Gebäude-Mesh um genau die Achse, die der
>     Orientierungs-Fix des Modell-Sidecars (`fix_euler` y) schon dreht —
>     ein zweiter Regler auf einer Achse, also nur eine Fehlerquelle. Ein
>     `role: "building"`-Spec trägt `yaw_deg` jetzt konstant `0.0`; gedreht
>     wird das Mesh vom Sidecar-Fix, der Ort von seinem Anker-Pin (§ A1.1).
>     Gelöscht sind der Sanitizer-Zweig (`world_ops._sanitize_map3d`), der
>     Editor-Regler, der Typ in beiden Clients und `scene_recipe._building_yaw`
>     — kein Alias, kein Fallback-Leser, keine Migration. `map_rotation_2d`
>     bleibt ausschließlich die 90°-Anzeigedrehung des flachen KARTEN-ICONS
>     und ist damit auch aus der Szenen-Signatur und dem
>     `POST /play/scene-preview`-Body raus. Räume, Props, Extras und Marker
>     behalten ihren eigenen Platzierungs-Yaw.
>
> 11. **`layout.rotation` dreht den GANZEN Raum — um seine Rechteck-Mitte**
>     (2026-08-20). Bisher drehte das Feld nur das Raum-MODELL: ein um 30°
>     gedrehter Raum zeigte gedrehte Inhalte in einer geraden Hülle. Das war
>     kein Entwurf, sondern eine Lücke aus der Referenzquadrat-Ära, in der das
>     Feld gespeichert, aber ausschließlich als Modell-Yaw ausgewertet wurde
>     (die 90°-Taste im Grundriss-Editor buk den Dreh stattdessen in jede
>     gespeicherte Koordinate ein — und zwar im entgegengesetzten Drehsinn zum
>     Feld). **Ab jetzt gilt wörtlich:**
>
>     * **Ein Winkel, ein Drehpunkt: die Mitte des Rechtecks**
>       `(x + w/2, y + d/2)` im Location-lokalen Rahmen, gedreht mit der EINEN
>       Abbildung aus § A1.1 (`world_geometry.local_to_world`,
>       `x' = cx + lx·cos θ + lz·sin θ`, `z' = cz − lx·sin θ + lz·cos θ`).
>       Positive Grad drehen also im Weltrahmen genauso herum wie ein
>       Platzierungs-Yaw (`rotation.y = +rad(θ)` in beiden Renderern) — auf dem
>       y-nach-unten-Grundriss ist das gegen den Uhrzeigersinn, weshalb jede
>       CSS/SVG-Darstellung des Winkels `-θ` zeichnet.
>     * **Was mitdreht:** die Bodenplatte und die Hülle (`outline`, inklusive
>       tessellierter Kurven und `outline_curves`), die Schalenwände, die
>       Öffnungen (sie sitzen auf den gedrehten Kanten — **die Kanten-INDIZES
>       und `at` ändern sich nicht**, eine Drehung erhält die Umlaufrichtung),
>       die Schwellen (`doorways`), Marker (Position **und** `facing`),
>       Prop-Placements (Position **und** `yaw`, samt ihrer Prop-Marker), der
>       Diorama-Anker (`model_at`) und die Streu-Kopien. Der Diorama-Spec
>       trägt weiterhin `yaw_deg = layout.rotation`: einen starren Körper um
>       die Rechteck-Mitte zu drehen IST „Anker mitdrehen + Mesh um den Anker
>       drehen", und der Anker dreht jetzt mit.
>     * **Gespeichert wird UNGEDREHT.** `layout.x/y/w/d` bleiben das gerade
>       Rechteck, `outline`/`markers[].at`/`props[].at`/`model_at` bleiben
>       Meter in dessen geradem Rahmen. Der Dreh ist eine Abbildung auf dem
>       Weg nach draußen (`room_recipe.room_transform` — der einzige Ort, an
>       dem ein Raum-Meter zu einem Location-Meter wird; im Editor
>       `planGeometry.roomToLocal`/`localToRoom`). **Gezeichnet wird gerade,
>       gedreht wird danach**: neue Geometrie entsteht immer im geraden Rahmen
>       des Raums, der Editor rechnet den Cursor dafür zurück.
>     * **Die 90°-Taste backt nichts mehr ein.** Sie setzt nur noch den
>       Winkel (+90); es gibt keinen w/d-Tausch, kein Umindizieren von
>       Öffnungen und keine mitgedrehten Marker/Props in der Speicherung mehr.
>       Damit endet auch der alte Vorzeichen-Widerspruch (Bake im
>       Uhrzeigersinn, Feld dagegen). Freie Winkel stehen im Raum-Panel;
>       gespeichert wird weiterhin ganzzahlig 0…359.
>     * **Türen bleiben KOLLINEARITÄTS-Sache.** Eine gemeinsame Wand entsteht
>       nur dort, wo zwei (gedrehte) Hüllenkanten tatsächlich kollinear und
>       antiparallel laufen (`SHARE_TOL_M` 0,15 m, Überlappung ab 0,8 m —
>       `room_recipe._mirrored_openings`, `scene_recipe._doorways`,
>       `planGeometry.sharedEdges`). Ein um 30° gedrehter Raum an einem
>       geraden hat schlicht **keine** gemeinsame Wand und bekommt daher keine
>       gespiegelte Öffnung. Das ist dokumentiert, nicht repariert — es gibt
>       keine „fast kollinear"-Sonderregel.
>     * **Der Dreh kann einen Raum vom Grundstück schieben.** `problems[]
>       room_outside_boundary` (Nr. 9) misst die GEDREHTE Hülle, ebenso der
>       Überlappungs-Check des Karten-Apply (`layout_apply`).
>     * **Kein Migrationscode.** Eine Welt, in der ein Raum bisher nur sein
>       Modell drehte, zeigt jetzt den ganzen Raum gedreht — das ist die
>       Korrektur, keine Regression. Ebenso entfällt der Rotations-Tausch in
>       der modellabgeleiteten Rechteckgröße des Editors (er war die
>       Kompensation genau dieser Lücke).
>
> 12. **EIN Boden — die Höhe ist eine Funktion, das Material ein Schnitt, das
>     Wasser eine Zahl** (2026-08-21, `development_instructions/plan-ein-boden.md`,
>     Etappen E1–E6). Die Welt hatte zwei unabhängige Böden — das Weltgelände
>     und die flachen Platten der Location-Szene —, und der erste war in sich
>     uneins: dieselbe Stelle trug auf Übersicht und Kachel bis zu **1,104 m**
>     Unterschied. Ab jetzt gilt wörtlich, ausgeschrieben in **§ A16**:
>
>     * **Eine Höhen-Wahrheit.** `h_final(x, z)` ist eine reine Funktion,
>       serverseitig aus fünf Stufen gebacken (Höhenflächen → Mikro-Relief →
>       Wasser-Carve → Location-Plateaus → Zonen-Wasser-Carve). Jede Rasterung
>       — Übersicht, Kachel, Mip-Ebene — ist nichts als diese Funktion auf einem
>       Gitter abgetastet, und zwei Gitter tragen an jedem gemeinsamen Punkt
>       dieselbe Zahl. Keine Stufe misst mehr „eine Rasterzelle"; alle Breiten
>       sind Meter.
>     * **Kein Renderer misst Dreiecke, um den Boden zu finden.** Die
>       Mesh-Raycast-Stufen der Figuren-, Spot- und Klick-Ketten sind gelöscht;
>       Render-LOD (CDLOD) ist reine Sampling-Dichte, und die Spiel-Logik
>       sampelt immer die feinste Ebene — ein Höhensprung beim Zoomen ist ein
>       Rendering-Übergang, nie ein Datenwechsel.
>     * **Ein Layer-Schnitt für alles Boden-Material.** Karten-Flächen,
>       Natur-Zonen und **Etage-0-Raumböden** sind Layer EINER Fläche; pro
>       Stelle gewinnt genau einer (der letzte enthaltende Eintrag), und die
>       Übergangsbreite ist `edge_blend_m` — je Terrain-Art (Default 1,5 m), je
>       Raumboden (Default 0, der harte Schnitt). Drape-Stapel,
>       renderOrder-/polygonOffset-Leitern und Alpha-Fransen sind ersatzlos weg.
>     * **Auf Etage 0 gibt es keine Bodenplatte.** `plates[]` trägt nur noch
>       DEKLARIERTE Etagen (`level != 0`); die Etage-0-Räume reisen als
>       `floor_plan`-Polygone mit. `LEVEL_PLATE_TOP` / `ROOM_PLATE_TOP` /
>       `OVERLAY_SURFACE_LIFT` sind ausschließlich die Datums einer deklarierten
>       Etage. Die Kachel-Fußabdruckplatte, ihr Sockel und der Backstop sind
>       gelöscht, ebenso das Payload-Flag `natural_floor`.
>     * **`level_ground` gibt es nicht mehr.** Wer sein Grundstück planiert,
>       entscheidet `models.heightfield.draws_built_floor` — eine gezeichnete
>       Gebäude-Kontur ODER mindestens ein geschlossener Raum. Die Natur stanzt
>       nichts; ihr Boden IST das Relief.
>     * **Wasser ist die einzige ebene Sonderfläche.** Eine gemalte Fläche wie
>       ein Wasser-Raumboden trägt `water_level` / `water_depth_m` /
>       `shore_ramp_m`, die Bake carvt ihr Bett (`h ≤ Spiegel − ε`, in jedem
>       Mip), und der Renderer legt eine ebene Platte auf
>       `water_level_effective`. `layout.floor_offset_y` ist **keine Wasserlinie
>       mehr**, sondern nur noch der Feinjustage-Regler eines einzelnen Raums.
>     * **Das szenen-eigene 17 × 17-Relief ist gelöscht** (`scene.terrain`,
>       `map3d.relief`, `layout.relief_flat`). Lokales Relief autoriert man über
>       Höhenflächen der Karte.
>
>     Wo unten eine Etage-0-Platte, ein Kachel-Sockel, ein `level_ground`-Flag,
>     ein `natural_floor`-Payload-Feld, ein Szenen-Relief oder eine gedrapte
>     Bodenfläche steht, gilt § A16.
>
> Wo der Rest des Dokuments „Quadrat", „Kante `plan_width_m`", eine
> `[0,1]`-Fraktion, `tile_fit`, `map3d.size` oder Kanten-Buchstaben
> N/S/E/W nennt, gilt die Liste oben. Numerische Verifikation weiterhin
> nach § B5a (Handwerte, nie Screenshots).

# Schnittstellen 3D — Gesamtvertrag v5 (2026-07-28)

> **v5 — EIN Rahmen, EIN Maßstabsfaktor, EIN Anker (2026-07-28).**
> Drei Änderungen, die alles Folgende überschreiben, wo es widerspricht:
>
> 1. **Das Bezugsquadrat ist der Fußabdruck der Location** — seit **E4**
>    (2026-08-09) seine Kante `map3d.plan_width_m`, nicht mehr feste 8 m und
>    nicht mehr der Welt-Meter-Regler `map3d.extent_m` (der Kachel-Ära; wird
>    nirgends mehr gelesen und beim nächsten Speichern verworfen). Es ist
>    zugleich die Box, die das Location-Modell füllt:
>    `max_m = extent_m × map3d.size` mit `size ∈ ]0, 1]`, Default 1. Die
>    0,92-Kachelmarge entfällt ersatzlos. Damit gilt **Grundriss-Rand =
>    Modell-Rand**; vorher standen Kachel (10), Modell (10 × 0,92 × size) und
>    Grundriss (8) unverbunden nebeneinander und die äußeren 0,6 m eines
>    size-1-Modells waren von keiner Fraktion erreichbar.
>    **`k = 1`** — ein Welt-Meter IST ein realer Meter, innen wie außen;
>    `extent_m` reist im Payload mit (`scene.extent_m` = `plan_width_m`) und
>    Konsumenten dürfen KEINE Konstante annehmen.
> 2. **Ein Modell wird mit EINEM Faktor auf allen drei Achsen skaliert.**
>    `scale_mode`/`box`/`scale_axes`/`fit_box` sind weg; jede Spec trägt
>    `max_m` + `measure` (`yawed_xz` | `xz` | `xyz`), `place()` rechnet
>    `s = max_m / gemessene Ausdehnung`. Nichts wird mehr in einer Dimension
>    gestaucht — mit `height_m`/`floors` (Sidecar) und `level_height` (map3d)
>    verschwinden auch die Regler, die das taten. Etagenhöhe ist
>    `map3d.storey_height_m` in Metern (seit E4 ohne Faktor). Der Y-Morph
>    des Clients (Kachelsicht uniform ↔ Detailsicht) ist gelöscht: er ließ
>    dieselbe Location bis zu 1,0 m anders hoch stehen als die Vorschau.
> 3. **Zwei Anker-Arten, deklariert statt geraten.** `models[].display`
>    unterscheidet `shell` (Gebäude STEHT auf dem Boden: Unterkante =
>    0,06 + `offset_y`, blendet beim Reinzoomen weg) von `ground`
>    (Flächen-Location, das Modell IST der Boden: seine BEGEHBARE FLÄCHE
>    liegt auf `offset_y`, das Mesh hängt darunter; bleibt sichtbar und
>    bekommt `cutouts`). Der Client hat „Fläche" vorher aus
>    `cutouts.length > 0` geschlossen und lag bei Flächen ohne Grundriss
>    falsch — der Mondscheinsee verschwand beim Reinzoomen komplett.
>    **Wo im Mesh die begehbare Fläche liegt, sagt ausschließlich der
>    `walk_y`-Regler** (Meter über der Unterkante; fehlt/0 = die
>    Unterkante selbst). Die frühere Messung („dominante horizontale Lage",
>    `walk_frac`/`bbox_fixed`) ist ersatzlos gelöscht: ein Modell
>    automatisch auszurichten ist genau die Reparatur, die dieser Vertrag
>    nicht macht — und sie lag dort falsch, wo es zählte (Bernstein Academy:
>    Dächer 0,38 projizierte Fläche gegen 0,67 des Bodens ⇒ die Heuristik
>    erklärte die DÄCHER für begehbar und versenkte das Modell 7,7 reale
>    Meter). Der Benutzer setzt den Basiswert, alles andere rechnet daraus.
>    Folge: Platten, Marker, Dioramen und Overlay-Zonen liegen automatisch
>    auf derselben Höhe wie die Modelloberfläche (Mondscheinsee vorher:
>    Overlay 1,12 / Marker −0,02 / Diorama 0,07 / Unterkante 0,06).
>
> Der Rest des Dokuments beschreibt weiterhin korrekt, WAS komponiert wird;
> wo eine 8, eine 0,92, ein `scale_mode`, `height_m`, `floors` oder
> `level_height` auftaucht, gilt die Liste oben. **Wo ein `× k` steht, ist es
> seit E4 eine Multiplikation mit 1** — die Felder `extent_m`/`k`/`storey_m`
> bleiben im Payload (Verbraucher-Verträge), `k` ist dokumentiert konstant 1.
>
> *Stage-Hinweis 2026-08-09 (E4, erledigt): der Kachelbezug des
> Bezugsquadrats („Default 10 = genau eine Kachel") ist weg. Teil B liefert
> `k = 1`, `extent_m = plan_width_m`, und Innen wie Außen rechnen in echten
> Metern (§ A1.8). Ohne Maßstabsanker fällt das Quadrat auf 10 m zurück.*
>
> **Nachtrag v5.1 (2026-07-28, aus der ersten echten Nutzung):**
>
> 4. **Objektgrößen sind drehungsunabhängig.** `measure: "xz"`/`"xyz"`
>    (Dioramen, Props) messen die Ausdehnung mit einem auf 90° GERUNDETEN
>    Orientierungs-Fix: die achsparallele Hülle einer gedrehten Kiste ist
>    größer als die Kiste, und der Maßstab wurde dadurch kleiner, ohne dass
>    sich das Objekt geändert hätte (Nixenstand: Fix 0/110/357 blies die
>    gemessene Seite von 1,000 auf 1,306 und schrumpfte das Modell um 23 %).
>    Nur `yawed_xz` (Gebäude) misst weiter die gedrehte Hülle — dort IST
>    „nach der Drehung ins Grundstück passen" der Zweck. **Der FIX steckt
>    aber auch dort gerundet drin** (Nachtrag 2026-07-28): gemessen wird der
>    YAW mit auf 90° gerundetem Fix, gezeichnet mit dem echten. Vorher
>    schrumpfte auch ein Location-Modell, sobald man seinen Fix fein
>    einstellte. Geprüft in `client3d/scripts/smoke_place_rotation.mjs` — und zwar am
>    SKALIERUNGSFAKTOR, nicht an der achsparallelen Hülle: die Hülle eines
>    gekippten 4-m-Würfels ist bis zu 4·√3 groß, und das ist richtig.
> 5. **Eine `ground`-Location bringt ihren Boden mit.** Kein Renderer legt
>    dort seine eigene Kachel-/Bühnenplatte darunter. Der 3D-Client zeichnete
>    eine undurchsichtige 10 × 10-Platte bei y 0,04 in ein Modell hinein, das
>    von −0,80 bis +2,69 reicht — Seebecken und Strand lagen dahinter.
>    *(Seit v6 Nr. 12 gilt das für JEDE Location: die Kachelplatte samt Sockel
>    und Backstop ist ersatzlos gelöscht, der Boden IST das Gelände.)*
> 6. **Marker tragen zwei Neigungsachsen.** `markers[].tilt` (Kopf hoch/tief)
>    und `markers[].roll` (seitlich kippen), Grad ±90, Default 0, angewandt
>    NACH dem Facing im Figuren-System ('YXZ'). Vorher konnte eine Figur nur
>    senkrecht stehen — schräg auf dem Sand liegen war nicht ausdrückbar.
> 8. **Ein Raum hat einen eigenen Höhen-Offset.** `layout.floor_offset_y`
>    (Meter, ±, Default 0) hebt den ganzen Raum gegenüber seiner
>    Etage: Platte, Wände, Props, Marker, Ausgang und das Diorama. Innerhalb
>    eines Gebäudes bleibt er 0. *(Seit v6 Nr. 12 ist das seine EINZIGE Rolle:
>    reine Feinjustage eines einzelnen Raums. Er gleicht keinen zweiten Boden
>    mehr aus — es gibt keinen — und er ist KEINE Wasserlinie mehr, dafür gibt
>    es `layout.water_level`, § A16.3.)* NICHT mitbewegt werden Konturwände
>    und Fahrstuhl — die gehören dem Gebäude. `model_offset_y` bleibt daneben, was es ist: die Lage des
>    MODELLS relativ zum Raumboden.
> 9. **Eine Overlay-Zone mit erklärter Boden-Art bekommt ihre Fläche**
>    (2026-07-29). Outdoor-Räume außerhalb des Grundrisses liegen auf dem
>    Modell und bekommen normalerweise keine Platte — eine Fläche auf
>    ETAGENHÖHE schnitte durch das Gelände. Setzt der Raum aber
>    `surfaces.floor`, wird die Fläche auf der Höhe der ZONE ausgegeben
>    (`overlay.y` + 0,01 gegen Z-Fighting), `thickness` 0, mit der Art als
>    `texture_kind`. *(Seit v6 Nr. 12 gilt das nur noch für DEKLARIERTE Etagen
>    — auf Etage 0 ist eine Zone ein LAYER im Bake, keine Fläche im Payload,
>    § A16.7/§ A16.9. Und ein gezeichneter Bereich wird zum See, indem sein
>    Boden eine Wasser-Art trägt und der Bake sein Bett carvt; der Spiegel ist
>    `layout.water_level`, NICHT mehr `floor_offset_y`.)* Ohne erklärte Art
>    ändert sich nichts, das Modell zeigt weiter seine eingebackene Textur.
> 7a. **Der Diorama-Bodenabstand ist 0,02 über dem Boden, auf dem der Raum
>    steht** — der Raumplatte einer DEKLARIERTEN Etage (0,10 + 0,02 = die
>    vertraute 0,12), sonst dem Boden selbst. Ein Outdoor-Raum hat keine
>    Platte (§ A5); die 0,12 dort zu zitieren hob das Diorama 10 cm über den
>    Boden, während die PROPS desselben Raums schon richtig darauf standen.
>    *(Seit v6 Nr. 12 ist der Boden auf Etage 0 `h_final`, das Diorama liegt
>    dort also auf 0,02 — § A16.9.)*
> 7. **Der Boden einer `ground`-Location liegt auf ihrer Etage 0** — das ist
>    keine Einstellung. `offset_y` gilt dort nicht; die einzige Angabe ist
>    `walk_y` (wo im Mesh der Boden sitzt), daraus folgt, wie tief das Modell
>    hängt. Vorher konnten die beiden auseinanderlaufen: Willowbrook trug
>    `offset_y −0,75` aus der Mess-Ära, also stand sein Dorfplatz (ein
>    Level-0-Raum) auf −0,75, während Etage 0 auf 0 und Etage −1 auf −0,8475
>    liegt — Figuren auf Kellerhöhe an einem Platz ohne Keller.
>
> **Nachtrag v5.2 — Detailszenen für Flächen-Locations (2026-08-02,
> `development_instructions/plan-area-detail-scenes.md`):**
>
> 10. **Drittes Display `shell_area`.** `map3d.area_detail` (nur zusammen mit
>     `area_model`) macht aus dem `ground`-Modell eine AUSBLENDENDE Hülle:
>     `models[].display: "shell_area"` fadet beim Reinzoomen wie `shell`,
>     behält aber das `ground`-ANKER-Gesetz (begehbare Fläche auf Etage 0,
>     `offset_y` gilt nicht — Nr. 7; die Größe kommt seit v6 Nr. 3 aus
>     `width_m` bzw. der Boundary-Breite). Die Rezept-Innenwelt
>     komponiert wie ein Gebäude-Interieur: keine `cutouts`, keine
>     Overlay-Zonen; Outdoor-Räume behalten ihre Textur-Platten (§ A5).
>     *(Der Kachelboden des Renderers, der dort dem Fade folgte und nah als
>     Backstop diente, ist mit v6 Nr. 12 gelöscht — es gibt nur das Gelände.)*
> 11. **Kurven sind Editor-Daten, der Payload bleibt Polygon.**
>     `layout.outline_curves` = `[{edge, c:[u,v]}]` — pro Kante höchstens ein
>     quadratischer Bezier-Kontrollpunkt (bbox-lokal wie die Outline-Punkte,
>     Klemme [−1, 2]). Der SERVER tesselliert beim Komponieren:
>     `B(t) = (1−t)²·P0 + 2t(1−t)·C + t²·P1` an `t = k/8` (7 eingefügte
>     Punkte je Kurvenkante); Opening-Kantenindizes werden über die
>     Einfüge-Map verschoben. Openings AUF einer Kurvenkante sind v1
>     abgelehnt. Die bbox-Invariante (x/y/w/d = echte Bounding-Box) gilt
>     über die TESSELLIERTEN Punkte — ein Bogen, der über das
>     Kontrollpolygon hinausragt, zählt mit. Beide Renderer sehen weiter
>     nur Polygone. Punkte-Kappung dafür angehoben: `clip_outline` und
>     `cutouts` je Polygon ≤ **64** Punkte (vorher 32).
> 12. **Scatter ist eine PLATZIERUNGS-Eigenschaft** (Neufassung 2026-08-02;
>     die separate Raum-Liste `layout.scatter` ist ersatzlos weg). Eine
>     normale Prop-Platzierung trägt optional `scatter_count` (Σ ≤ 120 je
>     Raum), `scatter_seed` (uint32) und `scatter_spacing_m` (0..5): die
>     Platzierung selbst bleibt als manuell gesetzter Anker stehen,
>     `scatter_count` Kopien werden beim KOMPONIEREN über die Raumfläche
>     gestreut, nie gespeichert, und landen als normale
>     `placements`/`models`-Einträge (`scattered: true`, ohne Prop-Marker)
>     im Payload. PRNG ist xorshift32 (`x ^= x<<13; x ^= x>>17; x ^= x<<5`,
>     uint32; Seed 0 → 1), pro Kandidat GENAU drei Züge u, v, yaw
>     (`next()/2³²`; yaw × 360) über der Outline-Bbox. Akzeptiert wird ein
>     Kandidat im Raum-Polygon, außerhalb aller Keep-outs (Nachbar-Hüllen
>     gleicher Etage — tesselliert —, Quadrate um Openings ±(width/2 +
>     0,6 m), Marker ±0,5 m) und mit Mittelpunktsabstand ≥
>     `scatter_spacing_m` zu den Kopien DERSELBEN Platzierung.
>     `scatter_spacing_m` ist die GANZE Dichteregel: 0 = Kopien dürfen
>     überlappen (Baumkronen tun das) — die frühere Footprint-Untergrenze
>     hielt jeden Baum eine Kronenbreite auf Abstand (User-Befund
>     2026-08-02). Versuchsbudget `count × 30`, Unterbelegung erlaubt.
>     Identischer Seed ⇒ identische Szene in Admin-Vorschau und Client;
>     § B5a prüft exakte Positionen gegen die von Hand gerechnete Folge.
>     **Der wirksame Seed ist nicht immer der gespeicherte:** trägt die
>     Location ein `variant_seed` ≠ 0 — die EINE Zahl, die ein auf die Karte
>     gesetzter Klon besitzt —, dann leitet sich JEDER Seed dieser Location
>     (Scatter hier wie Relief-`seed` in Nr. 14) aus
>     `variant_mix(gespeicherter Seed, variant_seed)` ab: EIN xorshift32-Zug
>     auf `gespeicherter Seed ⊕ (variant_seed · 0x9E3779B1 & 0xFFFFFFFF)`.
>     Ohne `variant_seed` (fehlend oder 0) gilt der gespeicherte Seed
>     unverändert. Grund: ein Klon erbt seine Seeds mitsamt der Vorlage und
>     sähe ihr sonst bis zum letzten Grashalm gleich. Die Handrechnung nach
>     § B5a rechnet mit dem wirksamen Seed.
> 13. **`scene.boundary_openings`** — Durchgänge an der LOCATION-Grenze
>     (Straße quert die Zelle): `[{edge: <Kanten-Index>, at_world: [x, z],
>     width_m, type: "passage", room_id?, inward: [nx, nz]}]`, Punkt in
>     LOKALEN Metern um den Pin. **Seit v6 (Nr. 5)** ist `edge` der 0-basierte
>     INDEX der Boundary-Kante (Kante i = Punkt i → i+1) und `at ∈ [0,1]`
>     läuft entlang dieser Kante; die Buchstaben N/E/S/W sind gestrichen.
>     `inward` = GEMESSENE einwärtige Einheits-Normale (float, keine
>     Achsenrichtung mehr — ein gezeichnetes Polygon hat schräge Kanten).
>     **`at`-Degradierung (eine Regel für beide
>     Verbraucher, seit E4):** fehlendes, nicht-numerisches oder nicht-endliches
>     `at` ist die KANTENMITTE 0,5, Werte außerhalb werden auf [0, 1] geklemmt —
>     `scene_recipe._boundary_openings` und `boundary_entry` liefern damit
>     denselben Punkt (vorher stand hier 0, also die Ecke, und der Renderer bot
>     einen Eingang an, den das Eintritts-Gate ablehnte).
>     **Konsum — seit v6 über die WELTKARTE, nicht mehr über die Szene:**
>     das „Betreten"-Angebot liest `worldmap.locations[].openings` (§ A1.3),
>     wo dieselben Öffnungen fertig in WELT-Metern samt Welt-Normale stehen —
>     eine Quelle für jeden Ort, auch für den, dessen Szene 404 antwortet
>     (gemalte Wiese mit gezeichnetem Tor). Der Client rechnet an einer
>     Öffnung damit **gar nichts** mehr: kein Anker, keine Halbkanten-Formel,
>     keine Drehung. Die Kanten-Filterung ist mit dem Kachel-Schritt
>     gestrichen — auf der freien Ebene kreuzt ein Weg keine Kante, es zählt
>     nur der Abstand, und genau den misst auch der Server. Die
>     `scene.boundary_openings` bleiben, was sie sind: die LOKALE Variante
>     für die Detailszene (verriegelte Schwellen-Marken). Und der SERVER
>     lässt niemanden anders hinein als über eine autorisierte Öffnung
>     (`app/core/boundary_entry.py`, verdrahtet im ENTRY-Gate von
>     `POST /play/pos`, § A15) — eine Location ohne jede Opening hat
>     dagegen eine FREIE Grenze (E4 Task 5, § A15: sie hat nie gesagt, wo
>     ihr Weg hinein ist; die Regel-Gates gelten trotzdem). Der
>     Eintritt routet in den verknüpften Raum (der Verweis heißt `room` in
>     den Autoren-Daten unter `map3d` und `room_id` im gelieferten Payload —
>     dasselbe Feld, zwei Namen); eine Opening OHNE ihn ist trotzdem gültig
>     — sie sagt dann nichts über den Raum, und es entscheidet die
>     Ankunftsregel (`world.get_arrival_room_id`: der erklärte `entry_room`,
>     sonst die Grundfläche). Seit § A13 kommt niemand mehr raumlos an.
>     **Das Verlassen entscheidet EINE Funktion**
>     (`boundary_entry.may_leave`). Drei Wege hinaus, und es genügt, dass
>     EINER zutrifft: über eine autorisierte Öffnung DIESER Kante aus dem
>     Raum heraus, den sie verknüpft — ohne Verknüpfung führt sie auf die
>     Grundfläche, also ist die Grundfläche der Raum, aus dem sie
>     herauslässt (der Rundweg derselben Öffnung); aus dem `entry_room`,
>     dem Gameplay-Gate jeder anderen Kante; und von überall, wenn die
>     Location keinen `entry_room` erklärt.
>     Einen Kompass, der das vorab **pro Richtung** beantwortet, gibt es
>     nicht mehr: `GET /world/avatar/neighbors` ist mit dem Kachel-Schritt
>     zusammen gestrichen — auf einer Meter-Karte gibt es keine vier Pfeile
>     mehr, die man vorab beurteilen könnte. `may_leave` lebt im **EXIT-Gate
>     von `POST /play/pos`** weiter und entscheidet am gemeldeten Standpunkt,
>     nicht auf Vorrat (die Gate-Reihenfolge steht in **§ A15**).
>     **`width_m` wird beim Speichern geklemmt, nie verworfen:**
>     [0,5 … `plan_width_m`] Meter (ohne Anker steht 10 ein) — die Kante
>     ist die Obergrenze, und eine gespeicherte Öffnung, die stillschweigend
>     verschwindet, kostet den Autor seine Arbeit. Der Journey-Durchlauf ist
>     weiterhin eine spätere Etappe.
> 14. **~~`scene.terrain` — deterministisches Geländerelief~~ — ERSATZLOS
>     GESTRICHEN** (2026-08-21, v6 Nr. 12 / § A16). Das szenen-eigene
>     17 × 17-Stützgitter ist weg, ohne Ersatzschiene: `scene.terrain` im
>     Payload, `map3d.relief` samt Sanitizer, `layout.relief_flat`,
>     `scene_recipe.compose_terrain` / `terrain_frame` / `_clip_grid_to_boundary`,
>     `relief.scene_ground_lift` / `has_relief` / `ground_lift_at`, die
>     Relief-Zweige von `scatter_curves` und `sampleTerrain` / `drapeGeometry` /
>     `TERRAIN_CELLS` in `@anima/scene-render`. Es gibt EIN Höhenfeld
>     (`world_geometry.ground_y` → § A16), und lokales Relief autoriert man als
>     **Höhenfläche der Karte**. Kein Alias, kein Fallback-Leser, keine
>     Migration. Die frühere Formel steht in der Git-Historie.
>     Raum-Rezept — Regler, Würfel und Checkbox bewegen also die Signatur.
> 15. **~~`map3d.tile_rotation`~~ — MIT v6 (Nr. 4) ERSATZLOS GESTRICHEN.**
>     Gedreht wird ausschließlich über den Anker-Pin (§ A1.1); es gibt keine
>     Payload-Drehung mehr (`_rotate_scene`, `rotate_terrain_grid`,
>     `tile_rotation_steps` und der Sanitizer-Zweig sind gelöscht, ohne
>     Alias-Leser). Der Absatz bleibt nur als Historie stehen:
>
>     Eine
>     Straße, die ost–west durch die Zelle läuft, wurde EINMAL als Vorlage
>     gezeichnet und auf mehrere Kartenzellen geklont; jeder Klon setzt
>     `tile_rotation` ∈ {90, 180, 270} (Grad im Uhrzeigersinn, andere Werte
>     werden im Sanitizer verworfen, fehlend = ungedreht). Gedreht wird
>     **ausschließlich der komponierte Payload**, um die Kachelmitte, ganz am
>     Ende von `compose_scene` — **der Editor zeigt die Vorlage UNROTIERT**,
>     im gespeicherten Plan bewegt sich kein einziger Punkt, und beide
>     Renderer bleiben dumm (§ B5). Zwei Regeln, je 90°-Schritt, in der
>     Draufsicht (x Ost, z Süd, also Bildschirm von oben mit y nach unten):
>     **Welt-Punkt/-Vektor** `(x, z) → (−z, x)` — Ursprung ist die
>     Kachelmitte, dieselbe Matrix gilt also für Punkte UND Richtungen
>     (`outward_normal`, `inward`, keine Translation); **Plan-Fraktion**
>     `(u, v) → (1 − v, u)` (dieselbe Drehung im Einheitsquadrat, dessen
>     Mitte 0,5 ist). Daraus folgt der Rest:
>     - `plates[].outline`, `walls[].from|to`, `models[].anchor` /
>       `clip_outline` / `cutouts`, `markers[].at_world`,
>       `doorways[].at_world` **und `doorways[].along`**,
>       `rooms[].overlay.centre|rect` → Welt-Regel; `rooms[].outline` →
>       Fraktions-Regel. Bei den Türschwellen trägt dieselbe Matrix beides
>       (Punkt UND Richtung, Ursprung ist die Kachelmitte); `width_m`,
>       `base_y`, `rooms` und `outside` sind drehinvariant.
>     - `models[].yaw_deg` = `(yaw + 90·k) % 360`. Ein `extras`-Kasten behält
>       seine Höhe, tauscht bei ungeradem k w/d und dreht sein `side`-Wort
>       N→E→S→W.
>     - **Kompass-Regel:** `markers[].facing` (und die `rotation` eines
>       Raum-Markers) ist der Figuren-Kompass 0 = Süd, 90 = Ost — er wächst
>       gegen den Uhrzeigersinn. Ein Szenen-Schritt im Uhrzeigersinn dreht
>       eine nach Süden schauende Figur nach Westen, also
>       `facing_neu = (facing + 270·k) % 360`.
>     - **Rand-Öffnungen:** Buchstabe N→E→S→W, `at` wie `rotateOpeningCW` im
>       Editor (N→E `at`, E→S `1−at`, S→W `at`, W→N `1−at`); `at_world` wird
>       aus dem gedrehten Paar über den Rahmen des Bezugsquadrats NEU
>       gerechnet, `inward` als Vektor gedreht (beides deckungsgleich).
>     - **Terrain-Gitter:** neu berechnet statt transformiert, denn
>       `h_neu(u,v) = h_alt(rot⁻¹(u,v))` mit `rot⁻¹(u,v) = (v, 1−u)`
>       (Gegenuhrzeiger). Mit `(u,v) = (i/n, j/n)` folgt `i_alt = j`,
>       `j_alt = n − i`, also **`neu[j][i] = alt[n−i][j]`** je Schritt;
>       `step` und `amplitude_m` bleiben.
>     - **Unberührt:** `signature` (`tile_rotation` liegt im gehashten
>       `map3d` und bewegt sie von allein), `extent_m`, `k`, `storey_m`,
>       `levels`, `style`, `figures`, `outdoor_rooms`, `area_detail` sowie
>       jede Höhe (`y`, `base_y`, `top_y`, `bottom_y`, `y_world`) — die
>       Drehachse IST +y.
>
> **Nachtrag v5.3 — Auflösungsstufen (2026-08-03,
> `development_instructions/plan-3d-lod-und-betreten.md`):**
>
> 16. **`models[].url` ist ersetzt durch `models[].variants`** — ein Objekt
>     `{"full": "<url>", "low": "<url>"}` mit einem Eintrag je Stufe, die es
>     WIRKLICH gibt (fehlende Stufe fehlt im Objekt, leeres Objekt = kein
>     Mesh → `placeholder_dims`). Kein Alias-Feld `url` daneben. Gilt für
>     `role` building/room/prop gleichermaßen; die URLs tragen den
>     Stufen-Parameter (`…/model?tier=full`).
>     **Konsumentenregel:** gewünschte Stufe nehmen, sonst die beste
>     vorhandene (Reihenfolge `full`, `low`, dann alles Weitere) — eine
>     fehlende Low-Variante darf ein Objekt nie verschwinden lassen. Die
>     Regel steht EINMAL als `pickVariant()` in `@anima/scene-render`; beide
>     Renderer rufen sie auf, keiner baut sie nach.
>     **Serving:** `GET /play/locations/{id}/model`, `/play/rooms/{id}/model`
>     und `/assets/props/{id}/model` nehmen `?tier=` (Default `full`, weiter
>     ETag/304); eine unbekannte Stufe bekommt die beste vorhandene, 404 nur
>     ohne jedes Mesh. `…/model/meta` liefert zusätzlich
>     `tiers: {"<stufe>": {signature, url}}`.
>     **Fehlendes `low` stößt den Bau an — beim PAYLOAD-BAU, nicht beim
>     Abruf** (2026-08-15): Da ein Payload nur vorhandene Stufen nennt und
>     `pickVariant()` daraus wählt, fordert nie ein Client ein `low`, das es
>     nicht gibt — ein Trigger an der Serving-Route wäre toter Code. Er sitzt
>     deshalb dort, wo die Stufen-Liste eines Subjekts ENTSTEHT
>     (`props.model_tiers`/Prop-Record für Props, `get_client_meta` für
>     Gebäude und Räume): fehlt `low`, während ein Voll-Modell da ist, startet
>     im HINTERGRUND die CPU-Reduktion (Blender Decimate, Schalter „Build
>     distance meshes on demand“). Kein Payload und kein Abruf wartet je
>     darauf; höchstens zwei Bauten laufen gleichzeitig, ein gescheitertes
>     Subjekt wird bis zum Neustart nicht erneut versucht (der Admin-Knopf
>     darf es trotzdem).
>     **Signaturen decken ALLE Stufen ab:** die Meta-Signatur ist der Hash
>     über Dateiname + `created_at` JEDER selektierten Stufe (vorher nur die
>     aktive Datei — eine neu erzeugte Low-Variante blieb unbemerkt), und
>     `placements[].model_sig` im Raum-Rezept trägt dasselbe für Props in die
>     Szenen-Signatur. `placements[].model_url` ist entfallen, dafür nennt
>     `placements[].model_tiers` die vorhandenen Stufen.
>     **Stufen-WAHL ist Sicht-Zustand des Clients** (Etappe 3, 2026-08-03):
>     welcher Konsument wann `low` fordert, entscheidet jeder Renderer für
>     sich — client3d nimmt Fernsicht-Gebäudemodelle distanzbasiert mit
>     Hysterese und lädt das Innenleben von `area_detail`-Locations `low`,
>     solange deren Detail-Ansicht nicht geöffnet ist; die Admin-Vorschau
>     fordert immer `full`. Der Payload bleibt davon unberührt — `variants`
>     nennt nur, was existiert, und `pickVariant()` bleibt die eine
>     Auflösungsregel.

# Schnittstellen 3D — Gesamtvertrag v4 (2026-07-24)

**Vollständiger Neuschrieb.** Dieses Dokument ERSETZT und konsolidiert:
`schnittstellen-3d.md` (Stand 2026-07-13), `backend-note-scale-anchors.md`
(v3 + alle Nachträge), `backend-note-room-recipe.md` (+ Nachträge 2026-07-22
bis -24) und `backend-note-asset-sizing.md`. Die alten Dateien bleiben als
Verweis-Stubs liegen.

Der Vertrag hat zwei Teile:

- **Teil A — Ist-Vertrag (verbindlich heute):** der konsolidierte Stand
  aller bisherigen Notizen, bereinigt um Historie und Widersprüche. Beide
  Renderer (Game-Admin-Vorschau UND 3D-Client) müssen exakt das hier tun.
- **Teil B — Ziel-Vertrag „Szenen-Rezept" (v4, beschlossen 2026-07-24):**
  der Umbau auf „**der Server rechnet, der Client stellt dar**". Neue
  Payloads sind hier spezifiziert; Koexistenzregel wie immer: **die
  Datenlage entscheidet, kein Flag** — liefert der Server das neue Feld,
  rendert der Client dumm; sonst gilt Teil A.

---

# Teil A — Ist-Vertrag (konsolidiert)

## A1. Freie Weltkarte (Meter) — neu geschrieben 2026-08-07

`development_instructions/plan-freie-weltkarte.md`, Etappe **E1**
(Commits `dc85876`…`6e773d2`). **Das Kachelraster ist ersatzlos
gestrichen.** Die Welt ist eine durchgehende Ebene in Metern, Locations
sind Inseln darauf, das Gelände dazwischen wird gemalt. Wo der Rest des
Dokuments noch von einer Kachel, von `grid_x`/`grid_y` oder von
`grid_bounds` spricht, gilt dieser Abschnitt.

### A1.1 Koordinaten und Fußabdruck

- **EIN Maßstab: 1 Welt-Meter = 1 realer Meter.** Keine Zelle, kein
  `CELL`, keine Nachbarschaft aus Ganzzahl-Arithmetik. Entfernung ist
  Strecke, Nachbarschaft ist Nähe.
- **Achsen:** `x` wächst nach **Osten**, `z` nach **Süden** — die
  Bodenebene beider Renderer. `y` ist keine Koordinate der Wahrheit
  (A1.2).
- **Eine Location ist ein Quadrat**: Kantenlänge `plan_width_m`
  (der Maßstabsanker aus `map3d.plan_width_m`), Mittelpunkt
  (`pos_x`, `pos_z`), gedreht um `yaw_deg` um die Hochachse.
  **Unplatziert** = `pos_x`/`pos_z` `null` — sie steht auf keiner Karte
  und verrät nichts (Template-Stellvertreter). **Ohne positiven Anker**
  (`plan_width_m` fehlt oder ≤ 0) hat sie keine Fläche und kann keinen
  Punkt für sich beanspruchen; sie hat dann nur einen Mittelpunkt.
- **Die Transformation ist Server-Code** (`app/core/world_geometry.py`),
  beide Renderer rechnen sie identisch nach:

  ```
  x = cx + lx·cos(yaw) + lz·sin(yaw)
  z = cz − lx·sin(yaw) + lz·cos(yaw)
  ```

  `world_to_local` ist die Umkehrung (Drehung um −yaw). **Verbindlich ist
  diese Abbildung, nicht ein Richtungswort:** bei `yaw_deg` 90 zeigt die
  lokale +x-Achse auf Welt **−z**. In three.js ist das
  `rotation.y = +rad(yaw_deg)` — **derselbe Drehsinn wie überall sonst in
  diesem Vertrag** (§ A1.8: `rotation.y = +rad(yaw)`, angeglichen mit E4).
  Seit v6 Nr. 10 ist der Anker-Pin die EINZIGE Drehung einer Location: die
  zweite, `map3d.rotation`, ist gelöscht.
  **Entschieden 2026-08-07:** Dieser Drehsinn ist ab jetzt DER Standard
  dieses Vertrags — für jede Rotation, Karte wie Szene. `k = 1` ist mit E4
  gelandet (2026-08-09), und mit **E4/Task 3** (2026-08-09) ist auch die
  früher gegenläufige Szenen-Kette angeglichen: **der Server liefert die
  Yaw-Werte unverändert, das Vorzeichen ist in den RENDERERN gekippt**
  (`packages/scene-render/src/place.ts`, `client3d/src/scene/sceneRecipe.ts`,
  `frontend/src/tabs/characters/Model3DViewer.tsx`,
  `frontend/src/tabs/world/FloorPlanPreview.tsx`). Der eigene Wand-Yaw in
  `primitives.ts` war hergeleitet korrekt und ist bewusst NICHT gekippt
  worden (§ A1.8).
- **Überlappung ist legal** (die Hütte auf dem Dorfplatz). Bei der Frage,
  in welcher Location ein Punkt liegt, gewinnt der **kleinste** treffende
  Fußabdruck — die spezifischste Antwort (`location_at_point`).
- Das lokale Szenen-Koordinatensystem der Innenansicht (Teil B) bleibt
  unverändert; (pos, yaw) setzt es in die Welt.

### A1.2 `ground_y(x, z)` — die Höhen-Reservierung (bindend)

Bodenhöhe ist eine **Funktion**, kein Feld.

- **Keine Position in irgendeinem Payload trägt ein `y`** — weder ein
  Charakterpunkt noch eine Fläche noch eine Reise-Polyline.
- Jeder Konsument leitet `y` **immer** über die Funktion ab und
  persistiert es **nie**.
- Das Höhenrelief (E8) tauscht **ausschließlich** diese Implementierung.
  Wer sich daran hält, sieht die Welt einfach hügelig werden; wer ein y
  gespeichert hat, hängt in der Luft.

> **Eingelöst mit E8 Task 2 (2026-08-13).** `ground_y` liefert nicht mehr
> konstant `0.0`, sondern das **autorierte Weltrelief**: bilinear aus dem
> Höhen-Gitter (**§ A16**), `0.0` überall dort, wo niemand etwas modelliert
> hat. Der Satz oben bleibt Wort für Wort gültig — genau deshalb hat der
> Umbau KEIN einziges Payload-Feld gekostet: die Höhe ist weiterhin
> **ableitbar** und steht in keiner Position. Wer sie ableitet, sieht Hügel;
> wer sie irgendwo gespeichert hat, hängt jetzt tatsächlich in der Luft.
>
> **Seit „Ein Boden" (v6 Nr. 12, § A16) ist es EIN Feld.** Das zweite —
> das szenen-eigene Relief, das `relief.ground_lift_at` obendrauf addierte —
> ist gelöscht. `ground_y(x, z)` IST `h_final(x, z)`: eine Funktion, fünf
> Backstufen, dieselbe Antwort für Serverregeln, Client-Regeln und das Bild.
> Ein Ort auf einem Hügel fährt mit dem Hügel hoch, ein gebauter Ort steht auf
> dem Plateau, das der Bake unter ihm gestanzt hat.

### A1.3 `GET /play/worldmap` — Payload v2

Eine Location-Zeile trägt genau ihre Kartengeometrie plus die
3D-Metadaten, die sie schon immer hatte:

| Feld | Typ | Bedeutung |
|---|---|---|
| `id` | `str` | |
| `name` | `str` | |
| `pos_x` | `float \| null` | Welt-Meter; `null` = unplatziert |
| `pos_z` | `float \| null` | Welt-Meter; `null` = unplatziert |
| `yaw_deg` | `float` | IMMER vorhanden, `0.0` wenn ungesetzt |
| `plan_width_m` | `float \| null` | **ABGELEITET**, nie autoriert: die breitere Seite der Bounding-Box von `boundary` (`world_geometry.polygon_plan_width_m` — dieselbe Funktion, mit der der Sanitizer das Feld schreibt, und dieselbe Boundary, aus der `world_bounds` entsteht; Eintrag und Flächen-Regel können also nicht auseinanderlaufen). `null` bedeutet deshalb **zweierlei**: der Ort ist **unplatziert** ODER er hat keine gezeichnete Boundary — beides heißt „keine Fläche“. Ein Client, der die Breite eines unplatzierten Ortes braucht, findet sie bis dahin nur in `map3d` |
| `boundary` | `[[x, z], …] \| null` | **v6:** DER Fußabdruck als gezeichnetes Polygon in LOKALEN Metern um den Pin, aus `map3d` hochgezogen (`world_geometry.effective_boundary`) — der Client hat keinen Quadrat-Pfad mehr, weil es keine Quadrate mehr gibt. **Seit 2026-08-19 wird nichts mehr synthetisiert**: `null` = der Ort hat KEINE Fläche und wird als bloßer Pin gezeichnet (Alt-Welten repariert der Seed-Knopf, siehe v6 Nr. 1) |
| `openings` | `[{edge, at_world, inward, room}, …]` | **v6:** die autorierten Grenz-Durchgänge, FERTIG GERECHNET (§ B1 Nr. 13): `edge` = Kanten-INDEX des Boundary-Polygons, `at_world` = `[x, z]` in WELT-Metern, `inward` = einwärtige Einheits-Normale in WELT-Achsen, `room` = verknüpfter Raum (`""` = keiner, dann entscheidet die Ankunftsregel). Immer vorhanden; **leere Liste = FREIE Grenze** (der Ort hat nie gesagt, wo sein Weg hinein ist, E4 Task 5). Gerechnet von `boundary_entry.opening_world_frames` — derselben Funktion, mit der das Eintritts-Gate von `POST /play/pos` misst, damit Angebot und Übertritt nicht auseinanderlaufen können. **Der Client rechnet an einer Öffnung nichts mehr selbst**: kein Buchstabe, keine Halbkanten-Formel, keine Kachel-Drehung |
| `map3d` | `object` | **optionaler Schlüssel** — nur wenn nicht leer (inkl. der abgeleiteten `floors`-Ersatzangabe aus den Raum-Layouts) |
| `layout_sig` | `str` (10) | **optionaler Schlüssel** — nur wenn mindestens ein Raum ein Layout hat ODER `map3d` nicht leer ist (AV3D-2⁺). Die Signatur deckt **beides** ab: die Raum-Layouts **und** die szenenformenden `map3d`-Metadaten des Ortes (gezeichnete `boundary`, Grenz-Durchgänge, `rotation`, `plan_width_m`, `storey_height_m`, `floors` …). Ändert sich eines von beiden, holt der Client die Szene neu — ein gezeichnetes Tor erreicht so auch einen laufenden Client (E5 B11) |

Wurzelfelder des Payloads: `avatar` · `current_location_id` ·
`locations` · `characters` · `events_by_location` · `world_bounds` ·
`terrain_sig` · `height_sig` · `fogged` · `max_step_height_m` ·
`max_slope_deg` · `backdrop` (**optionaler Schlüssel** — nur wenn die
Fernkulisse eingeschaltet ist, § A17).

| Wurzelfeld | Typ | Bedeutung |
|---|---|---|
| `world_bounds` | `{"min_x","min_z","max_x","max_z"} \| null` | Ausdehnung der Welt in Metern, auf 2 Stellen gerundet; **vor** dem Fog-Filter berechnet (A1.6) |
| `terrain_sig` | `str` (10) | Signatur über gemalte Flächen + Welt-Typenzeilen. Ändert sie sich, holt der Client `GET /play/terrain` neu — sonst nie |
| `height_sig` | `str` (10) | Signatur über **alles, was die fünf Backstufen von `h_final` lesen** (§ A16.1): die autorierten Höhenflächen, das Mikro-Relief der gemalten **Flächen** (`relief_inputs` — relief-freies Malen zählt nicht mit), die Wasser-Polygone samt ihren effektiven Zahlen (`water_basis`: Spiegel, beide Profil-Enden, Fließrichtung, aufgelöste Tiefe/Rampe — W1; ~~`zone_water_basis`~~ ist gelöscht) und die **Platzierungen der GEBAUTEN Orte** (ein verschobener Ort verschiebt sein Plateau; ein Ort, der einen Raum schließt oder öffnet, tritt in `placed_footprints()` ein oder aus — `level_ground` ist aus der Signatur verschwunden, § A16.4). Ändert sie sich, holt der Client `GET /play/heightfield` neu **und verwirft Kachel-Index samt aller geladenen Kacheln** (§ A16.5) — sonst nie. Wie `terrain_sig` **nie gefoggt**: ein Bergrücken ist von weit außerhalb sichtbar, und ein verstecktes Relief ließe Bild und Laufregel auseinanderlaufen |
| `fogged` | `bool` | `true` = gefilterte Sicht (§ A12) |
| `game_time` | `{…}` | Die **Spieluhr** zu genau diesem Payload — derselbe Zeitpunkt, auf den alle Reisen unten gerechnet wurden. Fertig aufgeschlüsselt: `canonical` (`"Y0002-D109T14:00:00"`), `total_seconds`, `year`, `day_of_year`, `season`, `season_name`, `day_of_season`, `hour`, `minute`, `second`, `hour_fraction` (Sonnenstand), `weekday`/`weekday_name` (`null`/`""`, wenn die Welt keine Wochen kennt), `label`, `date_label`, `time` (HH:MM), `is_night`, `day_bucket`, `atmosphere` (`{season, temperature, weather, note, label}` — Temperatur/Wetter gehören der **Season**, nicht der Welt; `label` z. B. `"freezing, snow — often fog in the morning"`). **Nie gefoggt** — die Tageszeit sieht jeder. Der Client RENDERT daraus, er rechnet nichts: es gibt keine Weltzeitzone und kein reales Datum mehr, aus dem sich eine Spielstunde ableiten ließe |
| `max_step_height_m` | `float` | Welt-Einstellung `game.max_step_height_m` (Default 0,4; validiert und geklemmt auf [0,05; 5]). Höchste Stufe, die eine Figur nimmt — Teil des Höhen-Gates von `POST /play/pos` (§ A15 Nr. 9) |
| `max_slope_deg` | `float` | Welt-Einstellung `game.max_slope_deg` (Default 40; geklemmt auf [10; 89]). Steilste Steigung, die eine Figur erklimmt — dasselbe Gate |
| `backdrop` | `{"height_m","seed","arcs"} \| fehlt` | Die **Fernkulisse** (§ A17) — reine Optik. Fehlt der Schlüssel, ist sie aus (oder der Server ist älter); beides ist für den Client derselbe Zustand |

**Jede Signatur hasht eine Server-Code-Version mit.** `height_sig`
(`HEIGHT_BAKE_VERSION` in `app/core/heightfield.py`), die Szenen-`signature`
aus § B1 (`SCENE_RECIPE_VERSION` in `app/core/scene_recipe.py`) sowie
`terrain_sig` samt dem serverinternen `layers_sig` (beide `LAYER_CUT_VERSION`
in `app/core/terrain_layers.py`) nehmen ihre Konstante als `code_version` in
die gehashte Basis auf. Grund: die Payloads sind Funktionen des **Codes** so gut
wie der Daten — eine geänderte Geometrie-, Back- oder Schnittregel ließ die
Signatur früher stehen, und Client wie Prozess-Caches hielten das alte
Ergebnis, bis jemand zufällig eine Fläche oder einen Ort speicherte. Wer die
ableitende Rechnung ändert, erhöht die Konstante um 1; damit bewegt sich die
Signatur für **alle** Welten und jeder Client holt neu. Ein Downgrade des
Servers ist derselbe Fall in der Gegenrichtung — auch dort ist die Signatur
eine andere, also wird neu geholt.

**Warum die beiden Grenzwerte hier reisen (E8 Task 1).** Der Server beurteilt
jeden gemeldeten Punkt mit genau diesen zwei Zahlen, und der Client spiegelt
die Regel, damit die Figur gar nicht erst in eine Absage läuft. Sie brauchen
keinen eigenen Endpunkt: dieser Poll läuft ohnehin, er wird **nie gefoggt**
(ein Grenzwert verrät nichts über die Welt) und er trägt schon das, was der
Läufer sonst braucht — die Karte. Ein Client, der die Felder nicht findet
(älterer Server), nimmt dieselben Defaults, auf die `app/core/relief.py`
zurückfällt.

**`world_bounds` — die Regel samt ihrer Randfälle.** Gerechnet wird über
ALLE Locations mit numerischem `pos_x`/`pos_z` **und über alle gemalten
Terrain-Flächen**, und zwar:

1. Location **mit Maßstabsanker** → der volle achsparallele Kasten des
   **UNGEDREHTEN** Quadrats, `cx ± w/2` / `cz ± w/2`. Bewusst ungedreht:
   die Ausdehnung ist ein Viewport-Hinweis, kein Kollisionsvolumen.
2. Location **ohne Maßstabsanker** → der **blanke Mittelpunkt** `(cx, cz)`,
   ohne ±w/2.
3. **Gemalte Fläche** → der achsparallele Kasten über alle Punkte ihres
   Polygons. Unlesbare oder nicht-endliche Punkte werden übersprungen,
   nie in die Ausdehnung gerechnet.

Daraus folgt die Invariante: **keine Location, die der Payload zeigt, und
keine gemalte Fläche liegt außerhalb von `world_bounds`.** Eine groß
gemalte Karte mit wenigen platzierten Orten wird also nicht mehr auf deren
Kasten beschnitten. `null` ist es genau dann, wenn **weder etwas platziert
NOCH etwas gemalt** ist — eine reine Terrain-Welt ohne jede platzierte
Location hat sehr wohl einen Rahmen. **Der Kasten DARF entartet sein**
(`min == max`, wenn nur ankerlose Locations platziert sind oder nur eine
einzige) — wer die Ausdehnung als Divisor benutzt (Zoom-Anschlag,
Minimap-Maßstab), muss das abfangen.

### A1.4 Charaktere: freier Punkt und Wildnis

Die Feldnamen des Charakter-Eintrags sind unverändert; neu ist **`pos`**
(E1), und **`travel`** hat mit E3 eine andere INNERE Form bekommen (§ A11).
Die Reihenfolge lautet `name`, `location_id`, **`pos`**, `height_cm`,
`room_id`, `activity`, `activity_animation`, `animation_set`,
`animation_sets`, `mood`, `movement_target_id`, `movement_target_name`,
`travel`, `interaction` (§ A8a), `place` (§ A8a), `avatar_url`.

| Feld | Typ | Bedeutung |
|---|---|---|
| `pos` | `{"x": float, "z": float} \| null` | Freier Meterpunkt. **Die Wahrheit**; `location_id` wird daraus abgeleitet (Punkt im Fußabdruck). `null` = der Charakter hat keinen Punkt (nie gesetzt, oder seine Location ist selbst unplatziert) — erst dann fällt ein Client auf den Location-Mittelpunkt zurück |
| `travel` | `{…} \| null` | Laufende Reise als **Meter-Polyline** (`target_id`, `waypoints`, `progress_m`, `total_m`, `eta_game`, `eta_hhmm`, `eta_label`, `speed_m_s_real`, `pace_m_s_real`) — Felder und Formeln in **§ A11**. `null` = keine Reise. Solange der Block MIT `waypoints` da ist, kommt die Render-Position aus ihm, nicht aus `pos` (das nur im Ticker-Takt nachgeführt wird); ohne `waypoints` (Fog, § A11 — dort sind auch alle Zahlen des Blocks `null`) bleibt `pos` die Position |

- **„Außerhalb jeder Location" ist ein legaler Zustand.** Ein Charakter
  mit `location_id: ""` UND einem `pos` steht in der **Wildnis**. Beim
  Übertritt nach draußen räumt der Server neben der Location auch
  `current_room` — sonst hörte die Figur weiter in den Raum hinein, den
  sie gerade verlassen hat.
- Weder Location noch `pos` ⇒ der Charakter steht gar nicht auf der
  Karte und fehlt im Payload (unverändert).
- **Im gefoggten Payload entscheidet draußen die SICHTWEITE**: ein
  Wildnis-Charakter steht im Payload, wenn er höchstens
  `game.discovery_range_m` Meter vom Avatar entfernt ist (E6, Regel und
  Randfälle in § A12); der Avatar selbst immer, Reisende ebenfalls — aber
  nur, solange überhaupt ein Avatar aktiv ist. Ohne aktiven Avatar steht
  draußen niemand im Payload.

### A1.5 `GET /play/terrain` — gemaltes Gelände

Ein eigener Endpoint, damit die 3-Sekunden-Abfrage der Weltkarte das
Gelände nicht jedes Mal mitschleppt. Auth wie die Weltkarte
(`get_current_user`), **kein** Admin-Gate, **nie gefoggt** — Gelände ist
immer sichtbar, nur Locations verstecken sich.

```
{ default_kind: str,          # Boden der unbemalten Welt
  types:  [ {kind, name, color, passable, speed_factor, surface?, meta}, … ],
  areas:  [ {id, kind, polygon, z_order, meta}, … ],
  stamps: { <area-id>: <updated_at>, … },   # nur für den Karten-Editor
  sig:    str }               # identisch mit worldmap.terrain_sig
```

- `types` ist der **wirksame** Katalog, nach `kind` sortiert.
- `areas` kommen **von unten nach oben**: `z_order` aufsteigend, bei
  Gleichstand die Malreihenfolge. Der LETZTE Eintrag liegt oben.
- `polygon` = `[[x, z], …]` in Welt-Metern, auf 2 Stellen gerundet, 3–2050
  Punkte, automatisch geschlossen. Die Obergrenze setzt das LINIENWERKZEUG:
  eine `wavy`-Linie wird alle 3 m abgetastet, ein Kilometer Fluss sind 335
  Mittellinien-Punkte und das gehrte Band darum ist doppelt so breit.
- `stamps` ist der **Versionsstempel** jeder Fläche (`{id: updated_at}`) und
  geht nur den Karten-Editor an: er schreibt seine Bearbeitungen als lokalen
  Entwurf und speichert sie in EINEM Batch
  (`PUT /world/terrain-areas/bulk`, Plan `plan-map-save-batch.md`), wobei jede
  gepufferte Änderung den Stempel mitführt, mit dem sie geladen wurde — daran
  lehnt der Batch genau die Objekte ab, die inzwischen jemand anders
  gespeichert hat. Renderer ignorieren den Block. Er fährt NEBEN den Flächen
  und geht bewusst NICHT in `sig` ein: sonst würde ein erneutes Speichern ohne
  Formänderung jeden Client neu backen lassen.
- `sig` ist dieselbe Signatur wie `terrain_sig` in der Weltkarte: einmal
  holen, bei Signaturwechsel neu holen. Sie deckt die Flächen **und den
  WIRKSAMEN Katalog** ab (Grundstock + Welt-Zeilen, Runde 2 der
  E8-Sichtabnahme) — auch eine geänderte Saat erreicht damit laufende
  Clients und den Routing-Cache, nicht erst den nächsten Neustart.

**Geländeregeln (für beide Renderer gleich):**

- **Die oberste Fläche gewinnt.** Ein Punkt gehört der letzten Fläche,
  die ihn enthält (`z_order`, dann Malreihenfolge) — genau so, wie der
  Editor malt.
- **Unbemalt = `default_kind`.** Der Wert kommt aus der Welt-Einstellung
  `game.default_terrain_kind`, und zwar über EINE Auflösung
  (`terrain_query.default_kind()`): fehlender ODER leerer Schlüssel
  ergibt `"grass"`. Der Endpoint darf nie eine andere Vorgabe melden, als
  die Laufregeln anwenden.
- **`passable`, `speed_factor`, `meta.move_anim` und `meta.idle_anim` kommen
  AUSSCHLIESSLICH aus dem Typen-Katalog** — nie aus der Fläche, nie aus einer
  Client-Tabelle, nie aus dem Namen. Eine Art ohne Katalogeintrag (Typ
  nachträglich gelöscht) gilt als begehbar mit Faktor 1,0 und ohne
  Boden-Clips: ein Loch im Katalog darf niemanden stranden lassen.
- **`passable` beurteilt die WILDNIS, nicht das Innere einer platzierten
  Location** (Entscheidung 2026-08-13, „Footprint gewinnt", Gate-Kette in
  § A15). Innerhalb eines Fußabdrucks entfällt das Gelände-Verbot ganz —
  die Platte ERSETZT den Boden fürs Stehen-Dürfen. Wer hinein darf, regeln
  Öffnungen und Regeln. Ein Renderer, der die Figur selbst hält, MUSS es
  genauso machen — sonst weigert sich das Bild zu laufen, wo der Server
  jede Meldung annimmt.
- **`speed_factor`, `meta.move_anim` und `meta.idle_anim` gelten SO WEIT, WIE
  DER HIMMEL REICHT** (Befund 3 der E8-Sichtabnahme, 2026-08-13; Reichweite in Runde 2
  entschieden). Drei Orte, von innen nach außen gefragt:

  | Wo die Figur steht | Gilt das Gelände? |
  |---|---|
  | **In einem RAUM** | nur wenn er ein **Outdoor-Raum** ist (`always_visible`, § A5) — ein Innenraum hat einen Fußboden |
  | Sonst **in einem Fußabdruck** | nur wenn es eine **Flächen-Location** ist (`passable` oder `map3d.area_model`) — ein Gebäude bringt seine eigene Platte mit |
  | Sonst: **Wildnis** | immer |

  Ein Dorf auf einem See wird durchwatet, die Halle daneben nicht; die
  Terrasse eines Hauses watet, das Haus selbst nicht. Gemaltes Wasser unter
  einer Flächen-Location ist genau die Ansage dafür. **Zweite neutrale
  Stelle: Faktor `<= 0` in einer Flächen-Location gilt als 1,0** — eine 0 ist
  kein Tempo, sondern ein „dieser Boden war nie zum Begehen gemeint" (Fels),
  und wer dort einen Ort hinsetzt, erklärt ihn für begehbar. **Neutral heißt
  immer: Tempo 1,0 UND keiner der beiden Boden-Clips** — durch eine geflieste
  Halle im See schwimmt niemand, und niemand tritt darin Wasser.

  Die zwei Regeln stehen einmal je Sprache: `terrain_query.ground_scope` +
  `terrain_query.effective_speed_factor` (Server, auch fürs NPC-Routing und
  die Reisezeit — dort ist die Raum-Hälfte immer `None`, eine Route läuft
  zwischen den Orten) und `game/walk.groundScope` + `game/walk.terrainPace`
  + `game/walk.moveClip`/`idleClip` (3D-Client, Klemme 0,25 statt 0,1 — sie schützt
  einen Lauf-SCHRITT vor der Stillstands-Erkennung, nicht eine Kostensumme
  vor der Unendlichkeit). Ob eine Location Fläche ist, beantwortet
  `world_geometry.is_area_location` bzw. `scene/tiles.isAreaLocation` — aus
  den AUTORIERTEN Feldern, nie aus einem Stil- oder Namensraten.
- Der Katalog ist **datengetrieben**: der geteilte Grundstock
  `shared/terrain/types.json` plus Welt-Zeilen, die pro `kind` den ganzen
  Eintrag **ersetzen** (Override-Replace wie die Aktivitäten-Bibliothek).
  Eine Welt-Zeile löschen holt den geteilten Eintrag zurück.
- `kind` ist die ID (klein, ohne Leerzeichen), `name` der Anzeigetext,
  `color` (`#rrggbb`) die Farbe der 2D-Schemakarte.
- **`surface` sagt, welche Oberflächen-Art (§ A9) den Boden bekleidet**
  (2026-08-16) — die ID aus `/assets/surface-textures`, vom Autor gesetzt.
  Bis dahin entschied der NAME: eine Art trug die gleichnamige
  Bibliothek-Art. Dieser Namensabgleich ist **ersatzlos weg**. Ein Typ ohne
  `surface` — und ebenso einer, dessen `surface` die Bibliothek nicht kennt —
  rendert den Standardboden aus `color`, genau wie vorher ein Typ ohne
  gleichnamigen Eintrag. Renderer greifen NIE auf `kind` zurück: zwei Typen
  dürfen dasselbe Material tragen, ein Typ ein anders benanntes, und das
  Umbenennen eines Bibliothek-Eintrags zieht keinem Boden mehr die Textur
  aus. Bestandswelten füllt eine einmalige Boot-Migration
  (`app/core/terrain_surface_migration.py`) mit genau der Zuordnung, die die
  alte Regel ableitete.
- `types[].meta` ist **frei-form mit GENAU ZWEI vertraglichen Schlüsseln**:
  `move_anim` und `idle_anim` (§ A9). Was auf einem Boden WÄCHST, hängt seit
  Befund B17 an der Fläche, nicht an der Art; eine alte `meta.scatter` an einem Typ liegt
  tot in der DB.

**`areas[].meta.scatter` — die Streuung (Vertrag für BEIDE Renderer):**

Eine **Liste** je Fläche, höchstens 8 Einträge, jeder Eintrag genau vier
Felder (Server-Whitelist `app/models/terrain._sanitize_scatter_list`):

```
scatter: [ {density_per_100m2: float,   # Instanzen je 100 m² der Fläche, 0 = keine
            model?: str,                # /assets/props/<id>/model; fehlt = eingebautes Büschel
            height_m?: float,           # ZIELHÖHE: das Prop wird uniform darauf skaliert
            min_spacing_m?: float}, … ] # Mindestabstand der EIGENEN Instanzen, 0..100 m
```

- **Fehlende oder leere Liste = es wächst nichts.** Es gibt keine Vorgabe.
- **`min_spacing_m` ist der Mindestabstand der Instanzen EINES Eintrags
  untereinander** (Metern, 0..100, zwei Nachkommastellen; fehlend oder 0 =
  keine Bedingung). Beide Renderer geben ihn unverändert an den einen Sampler
  weiter (`@anima/scene-render` → `minSpacingM`), der Kandidaten so verwirft:

  ```
  verworfen  <=>  hypot(x − a.x, z − a.z) < min_spacing_m
                  für eine in DIESEM Lauf bereits angenommene Instanz a
  ```

  Echt kleiner, genau wie die Freihaltung um einen Grundriss: ein Prop im
  exakt eingestellten Abstand steht. Der Test läuft NACH Ring, Occludern und
  Grundrissen auf einem Kandidaten, der seine drei Zahlen schon gezogen hat —
  eine weitere Ablehnung, die nur SUBTRAHIERT, also bleiben Kandidaten-Ordinal
  (Varianten-Formel unten) und die Präfix-Eigenschaft der Vorschau unberührt.
  Er gilt je **Eintrag** (Farne dürfen unter Bäumen stehen) und je **Zelle**
  (eine Zelle ist ein eigener Lauf, an der Naht kann ein Paar enger stehen).
  **Das Try-Budget bleibt `wanted · triesPerPoint`:** ein Eintrag, dessen
  Abstand seine Dichte nicht zulässt, endet einfach mit weniger Instanzen.
- **Der Server hängt an einen Eintrag mit Prop-`model` zusätzlich
  `variants: {tier: "/assets/props/<id>/model?tier=<tier>"}`** — nur die
  Stufen, die das Prop WIRKLICH hat, aufgelöst mit derselben einen Regel
  `pickVariant` wie die Szenen-Props (§ B1); fremde/absolute URLs und Props
  ohne Mesh bekommen den Schlüssel nicht, und ohne `variants` lädt ein Client
  weiter `model`. Welche Stufe er wann nimmt, ist **Anzeige-Politik des
  Clients** (Distanz-Hysterese, Sichtweite, Instanz-Budget — in
  `development_instructions/done/plan-scatter-lod.md` festgehalten), kein
  Payload-Vertrag: gespeichert bleiben die drei Felder oben.
- **Hat das Prop mehrere Modell-Varianten, hängt der Server zusätzlich
  `model_variants` an** — eine Stufen-Karte je AKTIVER Variante MIT Mesh, in
  der Reihenfolge des Props, gebaut wie überall sonst (§ B2-Nachtrag): die
  primäre behält ihre query-lose URL, jede weitere trägt `?variant=<i>`.
  **`variants` IST Element 0.** Das Feld kommt NUR bei mehr als einer Variante
  mit, also merkt ein Prop mit einer Variante von der Sache nichts.
  **Welche Instanz welche Variante zeigt, steht NICHT im Payload** — und das
  ist die eine Stelle, an der der gemalte Scatter von jeder anderen
  Platzierung abweicht: seine Instanzen entstehen erst im Kamera-Fenster des
  Clients, es gibt also keine Server-Zeile, an die eine Zahl gehängt werden
  könnte. Stattdessen rechnen **beide Renderer dieselbe eine Formel** über den
  Zellen-Seed, den der Sampler ohnehin hat (`@anima/scene-render`
  → `scatterVariantIndex`, § B2-Nachtrag):

  ```
  variant = ( FNV-1a(scatterCellSeed(area, row, cx, cz)) + Kandidat ) mod n
  ```

  `Kandidat` ist die laufende Nummer im Strom der Zelle, **verworfene
  eingeschlossen** — aus demselben Grund, aus dem der Yaw vor dem Test gezogen
  wird: eine Ablehnung muss SUBTRAHIEREN. Ein über die Überlebenden gezählter
  Index würde jeden Baum hinter einem neu gemalten Gebäude zu einer anderen
  Baumart machen, und zwar auch dann noch, wenn nur die gemessene Prop-Breite
  nachträglich genauer wird. `n <= 1` antwortet immer 0, also ist das Ergebnis
  Zeichen für Zeichen das alte. Der 3D-Client baut daraus **eine
  `InstancedMesh` je (Zeile, Variante)** statt je Zeile
  (`ground.ts buildScatter`); Zahlen von Hand in
  `client3d/scripts/smoke_scatter_math.mjs` Abschnitt (N). Die
  Karten-Editor-Vorschau bleibt Punkte und fragt gar nicht erst nach Varianten.
- **Der Server hängt an denselben Eintrag zusätzlich `prop_height_m`** — die
  ECHTE Höhe des Props in Metern aus seinem Bibliotheks-Datensatz
  (`app/core/props.prop_scatter_facts`, dieselbe Zahl, die der Props-Tab
  zeigt und editiert). Auch das ist reine Auslieferung, nie gespeichert: eine
  im Props-Tab korrigierte Höhe wirkt beim nächsten Refetch. Fremde/absolute
  URLs und Einträge ohne `model` bekommen den Schlüssel nicht; ein Datensatz hat
  IMMER eine Höhe (ohne eigene Maße den 1-m-Platzhalterwürfel), „kein
  Schlüssel" heißt also „kein Prop", nicht „keine Höhe".
- **`height_m` ist die Zielhöhe, nicht die Modellgröße:** das geladene Mesh
  wird uniform skaliert, bis seine Bounding-Box so hoch ist. Die **Rangfolge
  je Eintrag** ist (Befund 12 der Sichtabnahme):
  `height_m` am Eintrag → `prop_height_m` des Props → **2,0 m** als letzte
  Vorgabe. Also: was jemand für DIESEN Boden hingeschrieben hat, sonst wie
  groß das Prop wirklich ist, und die flache Vorgabe nur noch dort, wo es gar
  kein Prop gibt (fremde URL). Die Autorengröße der Datei gilt nie — „was die
  Datei sagt" ist in einer Meter-Welt keine Größe (Befund 1 der E8-Sichtabnahme:
  ein in Zentimetern exportierter Baum stand 2 cm hoch neben der 1,70-m-Figur;
  Befund 12 war die Gegenrichtung: mit der flachen Vorgabe stand jeder Baum
  avatarhoch). Der Karten-Editor sät deshalb KEINE Höhe mehr in eine neue
  Zeile, er zeigt die geerbte als Platzhalter.
  Das eingebaute Büschel ohne `height_m` ist **0,8 m** hoch (hüfthoch statt
  kniehoch). **Jedes Prop steht AUF dem Boden**: die Geometrie wird auf
  Unterkante = 0 geschoben, nachdem die Mesh-Transform innerhalb der GLB
  eingebacken ist (Befund B16).
- **Die Platzierung ist deterministisch und für beide Renderer DIESELBE
  FUNKTION** (`@anima/scene-render` → `scatterInstances`; der Karten-Editor
  zeichnet damit seine Draufsicht-Vorschau, der 3D-Client bepflanzt damit).
  Seed: `terrain:scatter:<area_id>:<index>` — flächen- UND eintrags-stabil.
  Verfahren: Rejection-Sampling in der Bounding-Box des bereinigten Rings,
  DREI Zufallszahlen je Kandidat (x, z, Yaw), Yaw bewusst VOR dem Test.
- **Gestreut wird nur, wo die Fläche selbst die oberste ist** (Befund 2 der
  E8-Sichtabnahme). `areas` kommt von unten nach oben (`z_order` ASC,
  `created_at` ASC), also ist die Listenreihenfolge die Stapelreihenfolge: ein
  Kandidat, der im bereinigten Ring IRGENDEINER späteren Fläche liegt, fällt
  weg. Der Wald unter dem darübergemalten Fluss wächst nicht mehr durchs
  Wasser. Getestet mit derselben Even-odd-Regel wie der eigene Ring
  (`pointInRing`, Server-Semantik `point_in_polygon`), und weil der Yaw auch
  hier vorher gezogen wird, ist es wieder eine reine **Subtraktion**.
- **Grundflächen platzierter Locations werden ausgespart** (Befund B18):
  ein Kandidat im Footprint-Quadrat (Zentrum, `yaw_deg`, `plan_width_m` —
  das GEHOBENE Feld) fällt weg. Weil der Yaw vorher gezogen wird, ist das
  eine **Subtraktion**: ein neu gesetztes Gebäude räumt genau die Props weg,
  auf denen es steht, und verschiebt die übrigen nicht.
- **Der Client sieht dabei nur die ihm BEKANNTEN Locations, und das ist so
  gewollt.** Unter dem Fog steht ein unentdeckter Ort nicht im Payload, sein
  Boden wird also mitbestreut. Andersherum wäre es ein Leak: eine Lichtung
  in Gebäudegröße verriete genau den Ort, den der Schleier verbirgt. Die
  Props korrigieren sich beim Entdecken von selbst (die Zeile kommt, die
  Footprint-Signatur bewegt sich, die Fläche wird neu gesampelt). Niemals
  „reparieren", indem der Client die ungefilterte Liste holt.
- **Ein Location-Umzug ändert `terrain_sig` NICHT.** Ein Client, der
  Footprints aussparen will, braucht die Footprint-Signatur (Zentrum, Yaw
  UND Kantenlänge) als ZWEITEN Rebuild-Auslöser; ohne sie stehen die Bäume
  bis zum Reload im frisch platzierten Gebäude.

### A1.6 Fog: was gefiltert wird und was nicht

Vollständig in § A12. Für die Kartengeometrie zählt:

- **Platzierte** Locations laufen durch `location_visible_to_character`;
  **unplatzierte** passieren immer (sie stehen auf keiner Karte).
- `world_bounds` wird **vor** dem Filter gerechnet: der Kartenrahmen darf
  nicht springen, sobald der Avatar etwas entdeckt.
- **Gelände wird nie gefoggt** — `GET /play/terrain` kennt keinen
  Fog-Modus. Der Dunst (seit 2026-08-24) ändert daran nichts: er liegt als
  Sicht-Effekt ÜBER der Landschaft, die Geometrie kommt vollständig.
- **Figuren dagegen schon**: seit 2026-08-24 filtert der Server jede Figur
  weg, die in einer unerkundeten Zelle steht (§ A12, Zeile `characters[]`).

### A1.7 Editor-CRUD (Game-Admin, E2)

Schreibseite der beiden neuen Datenbestände; alle Antworten `{"status":
"success", …}`, ungültige Eingaben **400**. Angelegt wird ausschließlich
über `POST` (die Id vergibt der Server); ein `PUT` auf eine unbekannte
Id antwortet **404**, legt also nichts an — ein wiederholter alter `PUT`
kann eine gelöschte Fläche nicht zurückholen. Bei den Terrain-Typen ist
der `PUT` dagegen bewusst ein Upsert: dort IST der Pfad-`kind` die
fachliche Id, und „Override setzen“ heißt anlegen-oder-ersetzen.
Dieselbe Auth-Lage wie die übrigen Location-Schreibrouten desselben
Routers.

| Route | Antwort / Wirkung |
|---|---|
| `GET /world/terrain-types` | `{types (nach kind sortiert), sources}` — `sources` sagt pro `kind` `"shared"` oder `"world"` |
| `PUT /world/terrain-types/{kind}` | Legt/ersetzt den **Welt-Override** einer Art → `{status, type}` |
| `DELETE /world/terrain-types/{kind}` | Entfernt nur den Override (der geteilte Eintrag kommt zurück); **404**, wenn es keinen gab |
| `GET /world/terrain-areas` | `{areas (unten→oben), sig}` |
| `POST /world/terrain-areas` | Neue Fläche, **die Id vergibt der Server** → `{status, area}` |
| `PUT /world/terrain-areas/{id}` | Ersetzt `kind`/`polygon`/`z_order`/`meta` einer **bestehenden** Fläche → `{status, area}`; **404**, wenn es die Id nicht gibt |
| `DELETE /world/terrain-areas/{id}` | Löscht eine Fläche; **404**, wenn es sie nicht gab |
| `GET /world/height-areas` | `{areas, sig, step_m, default_step_m, tile_step_m, max_slope_deg, max_step_height_m}` — die autorierten **Höhenflächen** (§ A16) in stabiler Anlege-Reihenfolge, dazu der aktuelle Übersichts-Schritt und der feinste (Befund 14: die Vergröberung ist sonst unsichtbar) sowie der **Kachel-Schritt**, aus dem der Editor die Plateau-Rampe `tan(max_slope_deg) · tile_step_m` rechnet (§ A16.4). Die beiden **Lauf-Grenzen** fahren seit 2026-08-16 mit (dieselben Werte wie in der Weltkarte, aus denselben `core.relief`-Gettern): jeder Editor, der eine Relief-Zahl zeigt, muss auch sagen können, ab wann sie unbegehbar wird — dafür soll niemand die ganze Weltkarte ziehen |
| `POST /world/height-areas` | Neue Höhenfläche, **die Id vergibt der Server** → `{status, area, step_m}`; `step_m` ist der Schritt DANACH (der Schreibvorgang rastert synchron neu), also eine Tatsache und keine Prognose |
| `PUT /world/height-areas/{id}` | Ersetzt `polygon`/`height_m`/`falloff_m`/`meta` einer **bestehenden** Fläche → `{status, area, step_m}`; **404**, wenn es die Id nicht gibt |
| `DELETE /world/height-areas/{id}` | Löscht eine Höhenfläche (der Boden dort fällt auf die flache Welt zurück); **404**, wenn es sie nicht gab |

Geprüft wird **beim Schreiben**, nicht beim Lesen (die Leser scheitern
still): Art muss im Katalog stehen · Polygon 3–2050 endliche
`[x, z]`-Punkte, Betrag ≤ 100 000, auf 2 Stellen gerundet · `z_order`
geklemmt auf ±10 000 · `speed_factor` geklemmt auf 0…2 (nicht-endlich →
1,0) · `color` genau `#rrggbb` · `kind` klein, 1–40 Zeichen aus
`[a-z0-9_-]`.

Für **Höhenflächen** gilt dieselbe Polygon-Regel; die beiden Zahlen werden
dagegen **geklemmt statt abgelehnt** (ein Vertipper soll den Boden auf die
Grenze schieben, nicht die gezeichnete Form kosten): `height_m` auf
±50 m, unlesbar/fehlend → 0,0 (eine flache Fläche, die nichts ändert),
`falloff_m` auf 0…1 000 m — 0 heißt „kein Übergang“, eine Wand an der
Kontur. Das ist erlaubt (ein Plateau, das man über eine Öffnung betritt);
der Editor warnt nur — und zwar gegen BEIDE Lauf-Grenzwerte, nicht nur gegen
`max_slope_deg`: eine Rampe hat die feste Steigung `|height_m| / falloff_m`,
und begehbar ist sie, solange die unter `min(tan(max_slope_deg),
max_step_height_m / 1 m)` bleibt. Bei den Vorgaben ist die STUFE die härtere
Schranke (0,4 gegen tan 40° = 0,84); wer nur gegen die Steigung warnt, nennt
Rampen begehbar, auf denen der Server jede kurze Meldung ablehnt (Review
2026-08-13).

### A1.8 Was aus dem alten § A1 weitergilt (Innenszene)

Diese Konventionen gehören zur **Szene**, nicht zur Karte, und sind von
E1 unberührt:

- **Referenzquadrat / Anker-Kette: `k = 1` seit E4** (2026-08-09).
  `extent_m` ist kein Regler mehr — das Bezugsquadrat IST der Fußabdruck
  (`plan_width_m`, § A1.1), Innen wie Außen rechnen in echten Metern. Das
  Feld `k` bleibt im Payload und ist konstant 1; wer damit multipliziert,
  rechnet weiterhin richtig.
- **Etagenhöhe** `storey = map3d.storey_height_m` (Meter), sonst 3.
  Etagenboden von Level n = `n × storey`.
- **Yaw-Kette der Szene: MIT v6 (Nr. 10) ERSATZLOS GESTRICHEN.** Ein
  GEBÄUDE-Spec trägt `yaw_deg` konstant `0.0`; gedreht wird das Mesh allein
  vom Orientierungs-Fix seines Sidecars (`fix_euler` y) und der Ort allein
  von seinem Anker-Pin (§ A1.1) — die alte Kette
  `map3d.rotation` → `map_rotation_2d` war ein ZWEITER Regler auf derselben
  Achse und damit nur eine Fehlerquelle. `map3d.rotation` ist gelöscht
  (Sanitizer-Zweig, Editor-Regler, Typ, `_building_yaw`), ohne Migration und
  ohne Alias-Leser; `map_rotation_2d` bleibt ausschließlich die Anzeige-
  Drehung des flachen KARTEN-ICONS (§ A1.9) und erreicht keinen 3D-Renderer
  mehr. Räume, Props und Extras behalten ihren eigenen Platzierungs-Yaw.
  Die Renderformel bleibt three.js **`rotation.y = +rad(yaw)`**.
  **Erledigt mit E4 (2026-08-09, Task 3):** das frühere Minus ist weg,
  verbindlicher Drehsinn ist die Weltkarten-Konvention `yaw_deg` (§ A1.1) —
  für jede Rotation, Karte wie Szene. Der SERVER ändert dafür nichts:
  `models[].yaw_deg` und `markers[].facing` kommen unverändert (§ B1); das
  Vorzeichen ist in ALLEN vier Renderstellen gemeinsam gekippt worden
  (`packages/scene-render/src/place.ts`, `client3d/src/scene/
  sceneRecipe.ts`, `frontend/src/tabs/characters/Model3DViewer.tsx`,
  `frontend/src/tabs/world/FloorPlanPreview.tsx`). Der eigene Wand-Yaw in
  `primitives.ts` wurde geprüft und ist **nicht** gekippt worden — er ist
  hergeleitet korrekt (eine achsparallele Wand hätte gleich AUSGESEHEN,
  deshalb war das eine Rechnung, kein Blick). Alte `map3d.rotation`-Werte
  drehten seitdem gespiegelt — bewusst, ohne Migration; mit v6 Nr. 10 ist das
  Feld ganz weg.
- **Rotations-Fixe** (Modell-Meta, Prop-Bibliothek): Euler **'YXZ'**, in
  Grad, VOR jeder Messung anwenden. Yaw (y) außen, Tilt (x) und Roll (z)
  im schon gedrehten Rahmen — „nach vorn kippen" heißt damit unabhängig
  von der Blickrichtung dasselbe, und die Marker-Neigung benutzt dieselbe
  Reihenfolge. Bei nur EINER belegten Achse identisch zum früheren
  'XYZ'.
- **Kompass für Blickrichtungen** (`facing`, Marker-`rotation`): 0 = Süd,
  90 = Ost, 180 = Nord, 270 = West; Figur `rotation.y = +rad(facing)`.
  **Seit E4 wächst er im GLEICHEN Drehsinn wie der Modell-Yaw.** Beide gehen
  durch dieselbe Renderformel `rotation.y = +rad(…)`, also durch dieselbe
  Matrix `R_y(+a)` — mehr steckt nicht dahinter. Der frühere Satz „er wächst
  GEGENSINNIG zum Modell-Yaw, und der Yaw-Umbau ändert daran nichts" stammt
  aus der Zeit VOR dem Umbau (Modelle renderten mit `rotation.y = −rad(yaw)`,
  Figuren schon mit `+rad(facing)`); mit dem Kippen der vier Renderstellen ist
  er falsch geworden und wird hiermit zurückgezogen.
  Konsequenz für jede Stelle, die Facing GEGEN einen Yaw verrechnet:
  * ein Layout-/Platzierungs-Yaw wird auf das Facing **addiert**
    (`facing_neu = (facing + yaw) % 360`), nicht abgezogen;
  * ein zugehöriger Offset-Vektor dreht mit `R_y(+yaw)`, nicht mit `R_y(−yaw)`
    (§ A2, Prop-Kette);
  * eine Szenendrehung (`tile_rotation`; EIN Schritt im Uhrzeigersinn ist
    `(x, z) → (−z, x)`, also `R_y(−90)`) verschiebt beide um denselben
    Betrag: `R_y(−90)·R_y(a) = R_y(a − 90)`, d. h. Modell-Yaw UND Facing
    laufen auf `(a + 270 · steps) % 360`.
- Alle Felder mit Suffix `_m` sind Meter — seit E4 zugleich Welt-Meter
  (k = 1), es ist nichts mehr umzurechnen. `offset_x/y/z` waren schon immer
  WELT-Meter.

### A1.9 Ersatzlos gestrichen (keine Aliase, keine Fallback-Leser)

- **Kachel 10 × 10** als Location-Fläche, `CELL`, `gridToWorld`,
  Zellen-Nachbarschaft.
- `grid_x`, `grid_y` an der Location; `grid_bounds` im Payload (→
  `world_bounds`).
- `template_location_id` im Weltkarten-Eintrag. (`passable` stand hier
  auch — es ist mit **E3/Task 5** zurückgekommen: eine Ziel-Liste muss
  Durchgangs-Kacheln fallen lassen können, und die Karte darf eine Straße
  anders zeichnen als einen Ort. Der Weltkarten-Eintrag trägt es also
  wieder.)
- `terrain` und `surface_kind` **im Weltkarten-Eintrag** (das gemalte
  Gelände kommt aus `GET /play/terrain`; § A9 gilt weiter für die
  Detailszene und `/world/locations`).
- Die Kachelbild-Felder `map_rotation_2d`, `map_image_off`,
  `map_patch_2d`, `map_patch_span` — **im Weltkarten-Eintrag**. Die
  **Kachelbild-Maschinerie ist mit E7 ausgebaut**: 3×3-Patches,
  Nachbar-Blending, Outpainting, der Bildtyp `map_3x3` und ihre Routen
  sind ersatzlos gelöscht (sie waren seit E1 ohne Aufrufer, und
  **gezeichnet** hat die Kachelbilder zuletzt der Spieler-Panel, der seit
  **E5** eine Schemakarte ist, § A11). Geblieben sind allein
  `map_image_2d` und `map_rotation_2d`: das Footprint-Icon der Karte und
  **allein dessen 90°-Anzeigedrehung**. Der früher daran hängende Yaw der
  Szenen-Kette ist mit v6 Nr. 10 weg (§ A1.8) — `map_rotation_2d` erreicht
  keinen 3D-Renderer, keine Szenen-Signatur und keine Draft-Vorschau mehr.

Der **Reise-Payload (§ A11) war in E1 unverändert** (Zellen-Felder auf einer
Meter-Karte, praktisch aber `travel: null`, weil ohne Raster keine Reise
startete). **Mit E3 ist er eine Meter-Polyline** — die Zellen-Felder sind
ersatzlos gestrichen, siehe § A11.

## A2. Die Platzierungsketten (heute drei — v4 vereinheitlicht sie, § B2)

*⚠️ Legacy-Ketten — die Gebäude-Kette rechnete in Kachel-Maßen und ist mit
**E7** ersatzlos gestrichen; wie ein Gebäudemodell auf der Meter-Karte sitzt,
sagen § A1 (Fußabdruck), der v5-Kopf und die EINE Routine in § B2. Die Prop-
und Diorama-Ketten unten leben als Legacy neben § B2 weiter; ihr `× k` ist
mit E4 gefallen (k = 1). Der Anker `walk_y` des Gebäudemodells ist geblieben:
optional, Meter über der Modell-Unterkante, Regler in der Modell-Galerie —
das Rezept liefert daraus `walk_y_world` am Building-Spec (die Standhöhe der
Overlay-Zonen einer Flächen-Location; ohne das Feld stehen Figuren auf der
Modell-Unterkante `bottom_y`).*

**Raum-Diorama** (`/play/rooms/{id}/model` + Meta):
1. Normalisieren: rohe BBox messen (NIE dem Pivot trauen), größte XZ-Seite
   = 1, XZ zentriert, Unterkante y = 0.
2. Fit: uniform `min(w/fp_x, d/fp_z) × 0,96`, an der UNROTIERTEN Box.
   ⚠ Diese Rechteck-Einpassung ist ab v4 nur noch der FALLBACK — der
   Größenabgleich mit Props/Figuren läuft über die Real-Size-Regel in
   § B2a (Diorama skaliert wie ein Prop über `width_m`).
3. Meta-Fix (innere Gruppe) → Layout-Yaw (Eltern-Gruppe).
4. Rotierte Box NEU messen und NEU erden: Unterkante =
   `Etagenboden + 0,12 + layout.model_offset_y`; XZ-Anker =
   `layout.model_at` (Fraktionen des Raum-Rechtecks; fehlt = zentriert).
   **Raum-Sidecar-`offset_y` ist stillgelegt** — für Räume nicht mehr aus
   dem Meta lesen (Gebäude unverändert).

**Props — REAL-SIZE-Regel** (`/assets/props`, Rezept-`placements`):
1. GLB laden, Orientierungs-Fix aus der Bibliothek anwenden.
2. BBox des GEFIXTEN Meshes messen → maxExtent = max(x, y, z).
3. `s = max(width_m, depth_m, height_m) / maxExtent` (UNIFORM — eine
   Platzierung skaliert nie).
4. `rotation.y = +rad(yaw)`. (Seit E4 — § B2 Schritt 3.)
5. Ergebnis-BBox messen → Unterkante auf **Raumplatten-Oberkante + 0,01**
   (outdoor: Etagenboden + 0,01) + `offset_y`, XZ-Zentrum auf
   `placements.at`. (Klarstellung v4 — vorher nannten Vorschau/Client/
   Rezept drei verschiedene Werte: 0,05 / 0,11 / 0. Möbel stehen auf dem
   Raumboden; die `prop_markers`-Höhen reiten denselben Hub mit.)
- `missing: true` → Platzhalter rendern, Platzierung nie verwerfen;
  `has_model: false` → Platzhalter in `dims`-Größe.
- **Zahlenbeispiel zum Diffen** — rohe Box [1,0/0,5/2,0], Fix y = 90°, Dims
  W 1,2 / D 0,6 / H 0,3, Marker `at [0,5/1,0/0,25]` mit `facing 90`,
  Platzierungs-`yaw 90`. Die Rechnung steht ausgeschrieben da, weil das
  Ergebnis mit E4 gekippt ist (vorher `offset_m [0, −0,3]`, `facing 0` — das
  war `R_y(−yaw)` und `facing − yaw`, siehe § A1.8):
  1. Fix `R_y(+90)` auf die Ecken der Box [0, size]: `(x, z) → (z, −x)`, also
     `x ∈ [0, 1] → z' ∈ [−1, 0]` und `z ∈ [0, 2] → x' ∈ [0, 2]` →
     gefixte Ausdehnung [2,0/0,5/1,0], `lo = [0/0/−1]`, `hi = [2/0,5/0]`.
  2. `s = max(dims) / max(extents) = 1,2 / 2,0 = 0,6` (× k, und k = 1).
  3. Markerpunkt roh `[0,5·1,0 / 1,0·0,5 / 0,25·2,0] = [0,5/0,5/0,5]` →
     gefixt `[0,5/0,5/−0,5]`. Anker ist die Mitte der Unterkante
     `[(lo+hi)_x/2 / lo_y / (lo+hi)_z/2] = [1,0/0/−0,5]`, also
     `pre = 0,6 · [−0,5/0,5/0,0] = [−0,3/0,3/0,0]`.
  4. Der Platzierungs-Yaw dreht diesen Offset mit **derselben** Matrix, die
     das Mesh dreht (`rotation.y = +rad(yaw)`, § B2 Schritt 3):
     `dx = pre_x·cos 90 + pre_z·sin 90 = 0`,
     `dz = −pre_x·sin 90 + pre_z·cos 90 = +0,3`
     → `offset_m [0, +0,3]`, `height_m 0,3`.
  5. Facing im gleichen Drehsinn (§ A1.8):
     `facing = (90 + 90) % 360 = 180`.

**Verankerung IMMER:** BBox-Unterkante des fertig transformierten Modells,
gemessen NACH Fix → Yaw → Skalierung; Offsets als letzter Schritt.

## A3. Standhöhen & Figuren-Maßstab — Klärung der 0,12-Frage

- **Verbindlich: 0,12 ist eine KONSTANTE in Welt-Metern, ohne ×k.** Die
  Admin-Vorschau rechnet `Etagenboden + 0,12 + offset` (FloorPlanPreview,
  Grounding-Zeile) — die §2e-Formulierung „0,12 × k" der Rezept-Note war
  falsch und ist hiermit zurückgezogen. Euer Client rechnet bereits
  richtig.
- Figuren stehen auf dem Boden, den die DATEN nennen — die Deklaration eines
  Dioramas, sonst eine DEKLARIERTE Etagen-Platte, sonst `h_final`; die
  Konstante verankert nur Modelle. **Auf Etage 0 gibt es keine Platte mehr**
  (v6 Nr. 12, § A16.9), drinnen so wenig wie draußen: dort ist der Boden das
  Gelände, und der Diorama-Abstand misst von ihm.
- **Figuren-Basishöhe: 1,70 m** — überall, in **Welt-Metern**, Karte wie
  Innenszene. **Seit E4 ohne jede Umrechnung**: `figures.base_height_m_world`
  ist konstant 1,70 (kein `× k`, kein Legacy `1,7 × storey/3` mehr). Der
  frühere Client-Default 1,75 m ist mit E4 angeglichen (§ B6 Nr. 1).
  `height_cm` der Charaktere skaliert relativ dazu.
- Es gibt **keinen Kachelbezug mehr**: „Figur relativ zur 10-m-Kachel"
  war die Doppelmaßstab-Quelle, die die Seamless-World-Umstellung
  beseitigt.

## A4. Raum-Rezept `GET /play/rooms/{room_id}/recipe`

*Stage-Hinweis: der Abschnitt gilt unverändert; das `× k` an allen
`_m`-Feldern ist mit **E4** weggefallen (Teil B liefert `k = 1`, § A1.8),
und „Fraktionen des 8×8-Quadrats" heißt Fraktionen des Fußabdruck-Quadrats
(`plan_width_m`).*

404 = Raum ohne Layout (Auto-Grid-Fallback). Sonst:

```
{ room_id, level, rotation?,          # rotation nur für Diorama-Fallback —
                                      # im Rezept-Pfad ist alles eingebacken
  outline: [[x, y], …],               # Hüllen-Polygon, ABSOLUTE Fraktionen
                                      # des 8×8-Quadrats, auto-geschlossen,
                                      # IM UHRZEIGERSINN; nur EIN Codepfad
  surfaces?: { floor?, wall? },       # Surface-Texture-Kinds
  openings: [{ edge, at, width_m, height_m, sill_m, type, to?,
               mirrored?, prop_id? }],
  markers?,                           # = layout.markers (Platz-Typen, s. u.)
  placements: [{ prop_id, id, label, prop_name, at: [x, y], yaw, offset_y,
                 dims: {width_m, depth_m, height_m}, has_model, missing? }],
                                      # id = stabile Platzierungs-ID,
                                      # label = optionale Beschriftung,
                                      # prop_name = Name aus der Bibliothek
  prop_markers: [{ placement, id, group, capacity, spacing_m,
                   offset_m: [dx, dz], height_m, facing }],
                                      # id = Marker-ID am Objekt, group =
                                      # Platz-Typ des Posen-Katalogs
  always_visible?,                    # Outdoor-Flag (§ A5)
  clip_model?,                        # Diorama-Clip-Opt-in (§ B1)
  no_walls?,                          # Raum emittiert KEINE walls-Einträge
                                      # (offene Zone, Pavillon, Bereich in
                                      # einem Area-Modell): keine Segmente,
                                      # keine Fenster-Brüstung/-Sturz, kein
                                      # Glas. Öffnungen bleiben Editor-Daten,
                                      # Platte/Marker unberührt; die
                                      # Konturwände des Gebäudes ebenfalls
                                      # (der Raum gibt auch keine
                                      # Kontur-Strecke mehr frei).
  model_at?, model_offset_y?,         # Diorama-Anker/-Höhe (reisen im
                                      # Payload mit, damit die Signatur
                                      # sich bei Regler-Änderung bewegt —
                                      # 2026-07-26)
  signature }                         # md5, deckt Layout + Prop-Sidecars
                                      # + Nachbarraum-Öffnungen ab
```

- **Koexistenz (geändert 2026-07-25, User-Entscheid):** Die Hülle kommt
  IMMER aus dem Rezept (sobald ein Layout existiert), und das Diorama
  KOEXISTIERT immer — es wird wie ein weiteres Prop behandelt (Anker
  `model_at`, Maßstab `width_m` § B2a, Standhöhe `walk_y`), egal ob
  der Raum `placements` trägt. Ein Raum ohne Diorama hat schlicht kein
  Modell. Die alte Weiche „placements verdrängen das Diorama" ist
  aufgehoben; `/scene` emittiert die Diorama-Spec entsprechend immer.
- **Hülle:** Bodenplatte = `outline`-Fläche; Wände = Kanten × Etagenhöhe,
  in Segmente um die Öffnungen geteilt (kein CSG). Öffnungen referenzieren
  die Kante per INDEX (Kante i = Punkt i → i+1); `at` = MITTE der Öffnung,
  0..1 entlang der gerichteten Kante; Spanne `at ± width_m / 2`, an
  den Kantenenden geklemmt. Fenster = Brüstung (0..`sill_m`) + Glas
  (`sill_m`..`sill_m+height_m`) + Sturz; Tür/Passage = Lücke.
  (Bis E3 stand hier überall ein `× k`; seit E4 ist k = 1.)
- **Gespiegelte Öffnungen:** eine physische Öffnung, im Besitzer-Raum
  definiert, erscheint in BEIDEN Wänden — der Nachbar bekommt sie mit
  eigenem Kanten-Index und gespiegeltem `at` fertig geliefert; exakt wie
  eigene behandeln, nichts umrechnen. `mirrored: true` ist rein
  informativ. Gilt für Türen, Passagen und Fenster.
- **Kein Exit-Punkt mehr (2026-08-06, `plan-betreten-und-tueren.md` § 4/§ 6):**
  `layout.exit` und `exit_derived` sind ersatzlos weg — aus Rezept, Payload,
  Editor und Speicher. **Die Tür IST der Weg hinein und hinaus**; wo ein Raum
  betreten wird, sagt allein seine begehbare Öffnung (`door`/`passage`), und
  fertig komponiert steht sie als `doorways[]` im Szenen-Rezept (§ B1).
  Kein Fallback-Reader liest das alte Feld: eine **Einmal-Migration beim
  Boot** (`world.migrate_room_exits_once`, `world_kv`-Marker
  `migration.room_exit_doors_v1`) projiziert jeden gespeicherten Exit-Punkt
  auf die nächste Hüllenkante und legt dort eine Tür in der Editor-Vorgabe an
  (1,0 m breit, 2,1 m hoch, `sill_m` 0 — dieselbe `OPENING_DEFAULT` wie beim
  Zeichnen). Nichts wird erfunden: übersprungen wird, wo diese Kante schon
  eine begehbare Öffnung trägt, gekrümmt ist oder schmaler als die Tür.
  Danach ist `exit` aus dem Layout entfernt — das ist die Idempotenz —, und
  der Boot-Log nennt die Zahlen (Räume mit Exit, erzeugte Türen,
  übersprungen, ohne brauchbare Hülle).
- **Marker:** `prop_markers` sind FERTIG komponiert (Fix → Real-Size →
  Yaw durchgerechnet) — eine Zeile beim Konsumenten:
  `marker = platzierungspunkt + [dx,dz]`, Höhe = Etagenboden +
  `height_m`, `facing` = Welt-Kompass. Objektlokale Fraktionen dürfen
  −0,5..1,5 (Y: −1..1,5) — nur die Wertebereiche werden größer.
  **Die Kette ist Schritt für Schritt die von § B2** (`compose_prop_marker`),
  denn ihr Ergebnis wird auf genau den Anker addiert, auf dem das Mesh sitzt:
  Fix in 'YXZ' · Maßstab am **90°-GERUNDETEN** Fix (§ B2 Schritt 2, v5.1
  Nr. 4) · Sitzpunkt = Boden-Mitte der Box mit dem ECHTEN Fix, VOR dem Yaw
  (§ B2 Schritt 3) · Yaw. Alle drei Punkte waren bis 2026-08-20 anders
  gerechnet als im Renderer — Maßstab am exakten Fix (bis 21 % zu klein),
  Euler-Ordnung 'XYZ' statt 'YXZ' und der Sitz an der ungedrehten Box gegen
  die gedrehte Hülle des Renderers (bis 0,50 m). Rest-Ungenauigkeit, offen
  benannt: bei einem Fix, der KEIN 90°-Schritt ist, ist die gedrehte Box nicht
  das gedrehte Mesh (Kiste um Kiste überschätzt) — gemessen 5 cm am einzigen
  solchen Prop im Feld (Hocker, Fix x 350). Ein 90°-Schritt ist exakt.
  **Facing-Default (2026-07-25):** `prop_markers` tragen IMMER ein
  `facing` — fehlt es am Objekt-Marker, gilt Prop-Front = Süd im
  Objektraum und der Sitzende erbt die Platzierungs-Drehung
  (`facing = (0 − yaw) mod 360`); zeigt die Front eines Props nicht nach
  Süden, einmal am Objekt-Marker korrigieren. (Befund Café-Terrasse:
  gedrehte Stühle, alle Sitzenden schauten in dieselbe Richtung.)
  Raum-Marker (`markers`) = unverändert `layout.markers` (raumlokal:
  `id`/`group`/`at`/`capacity?`/`spacing_m?`/`rotation`/`offset_y` additiv
  zur abgetasteten Auflagehöhe/`tilt`/`roll`). **Ein Marker nennt seit v7
  keinen Clip mehr, sondern einen PLATZ-TYP** (`group` = Gruppe des
  Posen-Katalogs: seat/bed/floor/counter/stand …, Nachtrag 2026-08-28);
  die fertigen Sitzplätze (`slots`) rechnet allein das Szenen-Rezept.
- `placements[].model_url` ist deprecated — immer über
  `/assets/props/{id}/model` laden.
- **Signatur-Polling** genügt; eine Änderung im NACHBARRAUM bewegt die
  Signatur mit (geteilte Wand).

## A5. Outdoor-Räume (`always_visible`)

- Kennzeichnet Terrassen/Gärten, die nicht im Gebäudemodell stecken; der
  Raum ist in jeder Zoomstufe sichtbar.
- **Keine Hüllen-Wände, keine eigene Boden-GEOMETRIE** — sichtbar ist nur
  die Boden-TEXTUR flach auf dem Untergrund (`surfaces.floor`-Kachelung,
  sonst Level-/Terrain-Boden). Öffnungen wirken nur über die Spiegelung
  in den Nachbarraum-Wänden. Gilt für Rezept- UND Diorama-Pfad
  (`layout.always_visible`).
- Admin-Vorschau rendert Outdoor-Räume als reine Umriss-Linien ohne
  Körper (Referenz; Commits f72e25a/d22a51b).

## A6. Gebäude-Grundriss, Etagen, Fahrstuhl (AV3D-12)

- `map3d.outline`: Polygon (Fraktionen, auto-geschlossen) → pro genutzter
  Etage Bodenplatte in Konturform + Wände entlang der Kontur.
  „Genutzte Etagen" = `level`-Werte der Layout-Räume.
- Rezeptwerte (heute Client-seitig, v4 → Server, § B3): Etagen-Platte nach
  unten extrudiert, Oberkante `level × storey + 0,08`, Dicke 0,14;
  Kontur-Wände Basis 0,08; Wand-Höhe `max(0,6; storey − 0,15)`, Dicke
  0,07; Reststücke < 0,06 entfallen;
  Obergeschosse halbtransparent. **Die Hülle nimmt ihr Loch von der Tür**
  (2026-08-05, `plan-betreten-und-tueren.md` § 4.2): jede Außen-Türschwelle
  (`doorways[].outside`) wird entlang ihrer EIGENEN Normale nach vorn auf die
  Kontur projiziert und öffnet sie dort in ihrer LICHTEN Breite, auf ihrer
  eigenen Etage. „Nach vorn" ist die Türrichtung, nicht der kürzeste Abstand
  zum Polygon — ein zurückgesetzter Raum öffnet die Hülle vor sich, nicht an
  der zufällig nächsten Wand. Eine schräg auftreffende Tür behält ihre
  Breite, eine in die Ecke geklemmte verliert den überstehenden Teil, statt
  auf die Nachbarkante zu wandern. Quelle ist ausschließlich der gelieferte
  `doorways`-Block, nie ein zweites Mal die Öffnungen.
  **Die frühere Fallback-Tür** (0,8 m mittig im südlichsten Wandstück, wenn
  keine Tür nah genug lag) **ist ersatzlos weg** — ein Gebäude ohne Außentür
  bleibt zu und wird als `problems[]`-Befund gemeldet (§ B1).
  **Klarstellung 2026-07-26:**
  opak (`opacity_role: "ground"`) ist die UNTERSTE genutzte Etage, alles
  darüber ist `"upper"` — bei einem Keller (`level -1`) ghostet also auch
  die Terrain-Etage 0, sonst läge der Keller unsichtbar unter opakem
  Boden. Enum unverändert, Clients unverändert. **Nicht mehr gültig seit
  2026-08-05:** „Türen sind eine Level-0-Sache" — das Loch folgt der Etage
  SEINER Tür (Schnitt je `(Tür-Etage, Kante)`). Nur der Befund
  `no_building_entrance` fragt weiterhin nach Etage 0: eine Tür im ersten
  Stock öffnet die Hülle dort und lässt von außen trotzdem niemanden
  hinein.
- **Raum-Ebene (Klarstellung v4; seit v6 Nr. 12 nur noch für DEKLARIERTE
  Etagen, `level != 0` — § A16.9):** Raum-Bodenplatte Oberkante
  `level × storey + 0,10` (liegt damit AUF der Etagen-Platte; Dicke
  0,02), Raumhüllen-Wände Basis 0,10; Props auf Platte + 0,01 (§ A2);
  Diorama-Unterkante bleibt bei + 0,12 (§ A3). **Auf Etage 0 sind alle vier
  Zahlen 0,00 / 0,00 / 0,01 / 0,02** — gemessen von `h_final`. Der Legacy-Fahrstuhl (ohne
  Anker: reale Meter × `storey / 3`) ist mit **E4** ersatzlos weg — der
  Schacht misst seine Vertragsmaße, immer.
- `map3d.level_floors?: {"<level>": "<kind>"}`: Etagenplatte mit der
  aktiven Textur des Kinds kacheln (`size_m`); Raum-Böden liegen
  darüber. Ohne Eintrag: auf **Etage 0** das aus `terrain` aufgelöste
  Kind (§ A9 — die Etage 0 IST die Terrain-Etage, der Boden draußen), auf
  jeder anderen Etage das globale `floor`-Kind; trifft `terrain` nichts,
  gilt `floor` auch auf Etage 0. Ein `level_floors`-Eintrag schlägt beides,
  auf jeder Etage — ein Dielenboden im ersten Stock ist kein Terrain.
  Die Reihenfolge steht in `scene_recipe.level_plate_kind`.
- `map3d.elevator`: `[x, y]`-Fraktion, gilt für alle Etagen. Rezept:
  Schacht 1,8 m², Ecksäulen 0,14, Glas 3 Seiten (offene Seite Richtung
  Gebäudemitte), Pads 1,6 m², Kabine 1,4 m² × 0,6 storey — alles echte
  Meter. Figuren-Routing: Türschwelle → Treppe (wo eine steht) oder
  Fahrstuhl → vertikal → weiter.
- `map3d.stairs`: eine Liste von Treppenläufen, je Eintrag
  `{at:[x,z], from_level, dir_deg}` in lokalen Metern — EIN Lauf je
  Etagensprung, max. 8 je Location. Rezept: Stufen 1,20 breit × 0,26 tief,
  Steigung teilt den Etagenabstand gleichmäßig, Pad 0,9 m² an jedem Ende.
  Wo ein Lauf steht, gewinnt er gegen den Fahrstuhl; der bleibt Fallback.
  Zahlen und Handrechnung: Nachtrag „Treppen (v4)" am Dateiende.
- Legacy: prozedurale Innen-Wände + Auto-Grid NUR, wenn kein Raum der
  Location ein Layout hat.

## A7. Modelle & Meta-Endpunkte

```
GET /play/locations/{id}/model/meta → { format, rig:"none", rotation{x,y,z},
      offset_y, offset_x, offset_z, floors, height_m, signature } | 404
GET /play/locations/{id}/model      → GLB (ETag)
GET /play/rooms/{id}/model/meta     → { format, rotation, offset_y*,
      width_m, walk_y?, signature } | 404
      (*für Räume stillgelegt, § A2 — entfällt mit v4 ganz aus dem
       Raum-Meta; Höhen-Offset für Räume ist AUSSCHLIESSLICH
       layout.model_offset_y)
GET /play/rooms/{id}/model          → GLB (ETag)
GET /characters/{name}/model3d      → { model: {url, format, rig,
      texture_url?}, signature } | 404
GET /play/test-figure/meta|/model   → Referenz-Figur der Admin-Vorschau
GET /assets/props                   → Bare Array (§ A2 Props)
GET /assets/props/{id}/model        → GLB (ETag; 404 = kein Mesh)
GET /assets/animation-clips         → [{ kind, set?, url }]
GET /assets/surface-textures        → Flächen + Blends (§ A9)
```

- **404 ist überall der Normalzustand** (kein Modell / Generierung läuft;
  keine Zwischenstände). ETag/304 auf allen Binärdateien; `signature` im
  Meta erkennt Regenerationen ohne Reload.
- `floors` ist float (2,5 = Dach/Attika zählt halb); `height_m` =
  geschätzte Gesamthöhe; `width_m` = geschätzte reale Raumbreite (macht
  den Inhalts-Maßstab explizit). `offset_*` ±25 Welt-Meter.
- Template-Kacheln (`template_location_id`) fragen das Modell der
  Template-ID an; Klone teilen die Geometrie.
- Rig-Typen: `mixamo` (humanoid, EIN GLB, Skelett 52 Joints
  `mixamorig:`, Textur eingebettet) · `generic` (FBX + separates
  basecolor-Bild, keine Bibliotheks-Clips → prozedurales Idle) ·
  `none` (Gebäude/Räume/Props, unrigged GLB). Richtwert ≤ ~30 MB,
  Texturen ≤ 2048; Raum-/Gebäude-Texturen gern als JPEG eingebettet.
- **Metal-Roughness (AV3D-14):** GLBs können eine kombinierte MR-Textur
  tragen (G = Roughness, B = Metalness, Faktoren 1.0, TEXCOORD_0);
  Koexistenz-Verhalten des Clients (MR vorhanden → nutzen + neutrale
  Env-Map, sonst Metalness neutralisieren) ist Vertrag. Kleine uniforme
  MR-Maps sind valide, keine Fail-Bake-Artefakte.
  **Ausnahme FIGUREN (2026-07-26, Befund Rosi):** Charakter-Bakes liefern
  ~0,5 Metalness über Haut/Stoff (gemessen Ø B = 127) — physikalisch
  Unsinn. Renderer setzen bei Charakter-Modellen `metalness = 0`
  (Roughness-Kanal derselben Map bleibt aktiv); die Env-Map-Regel gilt
  nur für Gebäude/Räume/Props. Langfristig gehört die MR-Einbettung im
  Charakter-Workflow des Gateways abgeschaltet oder der Bake repariert.
- **Asset-Größen:** Face-Count/Texturgröße werden pro Generierung
  gesteuert (Dialog; Auto-Pfad „Furnish": Face = clamp(6000 × größte
  Kante, 2000, 20000), Textur 512/1024/2048 nach Größe). Für den Client
  ändert sich nichts — Signaturen + ETags erkennen alles.

## A8. Animation & Aktivität

- Clips: Mixamo-FBX „Without Skin", alle aus derselben Quelle. Offenes
  `kind`-Vokabular (idle/walk/run/sit/…); **Sets** = Unterverzeichnis
  (`female`/`male`/`animal`/frei); Fallback-Kette
  `<kind>_<set1>` → … → `<kind>` über `animation_sets` des Charakters.
- **Server-authoritativ:** `activity_animation` (per Worldmap) bestimmt
  den Clip; nennt der Server keinen, steht die Figur (`idle`). Die
  Keyword-Heuristik `activityToClipKind` im Client ist gelöscht (2026-08-28,
  Task 13 plan-posen-plaetze.md).

## A8a. Paar-Interaktionen — zwei Figuren, ein Clip-Paar, ein Anker (2026-08-20)

**Clip-Paar.** Ein Paar-Clip besteht aus zwei Dateien, die ZUSAMMEN aufgenommen
wurden: `<kind>__a.fbx` + `<kind>__b.fbx` (Doppel-Unterstrich = Rollentrenner,
sonst gilt die Kind-Regel von § A8). Beide Hälften liegen in EINEM Bezugsrahmen:
Ursprung = XZ-Mitte der beiden Wurzeln am Ankerframe, **+X zeigt von A nach B**,
Boden bei y = 0. Jede Hälfte behält ihre volle Root-Bewegung (Hüft-Position) in
diesem Rahmen — die Annäherung des Handschlags, das Wandern eines Tanzes. Ein
Sidecar `<kind>.json` neben den Dateien trägt `duration_s`, `fps`, `frames` und
`geometry` (`anchor_s`, `root_distance_m`, `roles.{a,b}.anchor_xz_m` = Hüft-XZ
der Rolle am Ankerframe, in m). `GET /assets/animation-clips` liefert pro Clip
`role` (`a`/`b`/leer) sowie `pair_kinds` + `pairs.<kind>` (= Sidecar).
Erzeugung: `scripts/clip_import_cmu.py` (CMU-Mocap → Mixamo-Skelett, Blender
headless) — die CMU-Daten sind frei weitergebbar, anders als Mixamo.

**Zustand (Server).** `app/core/interaction_engine.py` bindet zwei Charaktere an
ein Paar: Profil-Dict `interaction` auf BEIDEN, reine Funktion der SPIELZEIT wie
`journey` (Freeze friert die Geste ein). Auslöser: Katalog-Pose mit `solo:false`,
deren `animation` ein vollständiges Paar ist (Verb `InteractWith`, Plugin
`plugins/interact`). **Anker:** Hat der Raum einen freien Platz der Gruppe der
Paar-Pose (plan-posen-plaetze.md § 4) mit ≥ `places` freien Slots, ist der
Anker dessen Mitte (Mittelwert der Slots — bei Kapazität 2 die Marker-Position),
`yaw` = Marker-Facing − 90° + `yaw_offset` der Pose (Clip-+X entlang des
Facings; ohne Facing = Süd), und `anchor.place_id` nennt den Platz — beide
Profile halten ihn als `place.slot = "pair"`, das Paar belegt `places` Slots.
Sonst (nur Gruppe `stand`) Anker = Mittelpunkt der beiden Positionen, `yaw` so,
dass Clip-+X auf die Weltrichtung Actor→Partner fällt, `place_id` `null`; eine
Sitz-Pose ohne freien Sitz wird abgelehnt. Der Server setzt beide
Spielzustands-Positionen auf `anchor + R(yaw)·anchor_xz_m` der Rolle (so sehen
Wahrnehmung, Regeln und Karte die beiden dort, wo der Clip sie am Anker hält).
Ende: Ticker (`settle_finished`, Spielzeit ≥ `duration_s`), Reise, manuelle
Positionsänderung, neue Pose — immer für BEIDE.

**Payload (Worldmap, pro Charakter):**

```json
"interaction": {
  "id": "049b7a009533", "kind": "handshake", "role": "a", "partner": "Bob",
  "anchor": {"x": 10.0, "z": 22.0, "yaw": -1.5708, "place_id": null},
  "started_at_game": "Y0001-D001T12:00:00",
  "elapsed_s": 0.8, "duration_s": 2.533, "rate": 1.0
}
```
`null`, wenn keine läuft (auch unter Nebel ausgedünnt). `elapsed_s` ist die
Clip-Zeit in SPIELsekunden zum Payload-Zeitpunkt, `rate` Spielsekunden pro
Realsekunde (0 = Freeze).

Daneben `place: {id, slot, x, z, facing?, room_id} | null` — der Platz
(Raum- oder Prop-Marker, plan-posen-plaetze.md § 4), auf den der Server die
Figur mit ihrer Pose gesetzt hat: `x`/`z` ist der Weltpunkt des gehaltenen
Slots (`slot` = Index; `"pair"` bei einem Paar, dann die Platzmitte = Anker —
ein Platz trägt höchstens EIN Paar), `facing` das Marker-Facing in
Kompassgrad (fehlt am Marker → `null`). **Der Server hat gestellt; ein Client
zeichnet die Figur auf dem Slot und wählt nicht mehr selbst.** `null`, wenn die
Figur keinen Platz hält (Pose ohne Marker im Raum, verschwundener Marker), unter
Nebel ausgedünnt. Das SSE-Ereignis `activity_changed` trägt dasselbe Profilfeld
`place` (`{id, slot, room_id}` oder `null`) neben `activity`/`animation`; der
Avatar setzt über `POST /play/self/activity` (`{"activity": ""}` = Pose und
Platz löschen, `{"place_id", "pose"}` = angeklickter Platz — 400 Pose passt
nicht zur Gruppe, 404 kein solcher Platz im Raum, 409 belegt). Was er anklicken
kann, sagt `GET /play/places` (Task 13): die Plätze seines aktuellen Raums als
`{room_id, places: [{id, label, group, capacity, free, free_slots, poses: [{key,
label}]}]}` — `free_slots` indiziert die `slots[]` des Szenen-Payloads, der
Avatar selbst zählt nicht als Belegung (sein eigener Platz bleibt mit einer
anderen Pose der Gruppe wählbar), `poses` sind die SOLO-Posen der Gruppe,
Default zuerst. Der 3D-Client macht daraus zwei Klickziele (Beschluss
2026-08-28, `placeGlyphs.ts`): ein Platz AUF einem Prop wird am **Prop-Mesh**
selbst angeklickt — es leuchtet unter dem Zeiger auf, der Cursor wird zum
Zeigefinger, und der Treffpunkt entscheidet, welchen seiner Plätze das
Posen-Menü anbietet (der mit dem nächsten freien Slot) —, während ein Platz
OHNE Prop (`source: "room"`) weiterhin je freiem Slot einen flachen Ring in
Gruppenfarbe bekommt. Reihenfolge des Klicks: Figur → Prop → Ring → Boden.
Verbindung Prop-Mesh ↔ Marker ist der Platzierungs-Anker (`markers[].anchor`
== `models[].anchor`); die Auswahl selbst ist rein
(`placement.pickablePlaceFor`, `client3d/scripts/smoke_place_lift.mjs` [2]).

**Renderer.** Figur-Root = `anchor + R_y(yaw)·clipRoot(t)` mit der three.js-
Y-Drehung (`x' = x·cos + z·sin`, `z' = −x·sin + z·cos`); `clipRoot(t)` ist die
Hüft-XZ der Hälfte (cm → m) — im Client aus dem ROHEN Clip gezogen, weil
`adaptExternalClips` die horizontale Hüftbewegung für alle Clips entfernt. Der
Root wird um `yaw` gedreht, die Körperrichtung steckt im Clip. Nennt der Anker
einen `place_id`, steht das Paar auf der Slot-Höhe dieses Platzes (der Client
kennt sie aus seinem Platz-Inventar, `slots[0].y`), sonst auf dem Boden. Clip-Zeit `t`
läuft lokal mit `rate` weiter und wird nur gegen einen NEUEN Poll nachgezogen
(> 0,3 s Drift). Die Hälfte `<kind>__<role>` ist eine normale Action der Figur;
fehlt sie auf dem Rig, gilt die gewöhnliche Platzierung + `activity_animation`.
Marker-Blickrichtung und Nachbar-Blick greifen während einer Interaktion nicht.
Der Avatar meldet währenddessen keine Position (die Clip-Bewegung wäre sonst
ein „Move", der die Interaktion serverseitig beendet).

**Numerische Prüfung (§ B5a):** `scripts/smoke_interaction.py` (Anker, Yaw,
Rollen-Positionen, Spielzeit-Ende, Abbrüche, Payload),
`client3d/scripts/smoke_clip_pair.mjs` (echte FBX-Hälften per FBXLoader:
Root-Bahn am Ankerframe = Sidecar, Anker-Transformation = Server-Formel).
Bekannte Grenze des Piloten: Handkontakt ist nicht garantiert — die Proportionen
des Mixamo-Skeletts sind nicht die der Schauspieler (Handschlag: Hände ~25 cm
statt 11 cm auseinander); Körpergrößen-Unterschiede (`height_cm`) skalieren die
Figur, nicht den Abstand. Beides wäre IK, nicht Teil des Piloten.

## A9. Terrain & Oberflächen (AV3D-13 v2)

- **Nachtrag 2026-08-20 (E2c) — JAHRESZEITEN.** Eine Art darf je Jahreszeit
  eine andere ihrer gespeicherten Fassungen zeigen; die Auswahl steht in
  `shared/surface_textures/selection.json` (`{"": <Datei>, "<saison>":
  <Datei>}`), aufgelöst wird sie SERVERSEITIG in
  `surface_textures.texture_file`. Der Vertrag ändert sich damit **nicht**:
  Räume und Terrain nennen weiterhin nur die `kind`, und
  `/assets/surface-textures` liefert wie immer genau EINE `url` je Art — nur
  eben die der laufenden Jahreszeit, mit der saisonlosen Fassung als Rückfall.
  Weil jede Fassung ihren eigenen Dateinamen hat, ist auch kein Cache
  betroffen. **Offen:** der 3D-Client holt diese Liste NUR beim Start; ein
  Jahreszeitenwechsel erreicht seine Böden erst beim Neuladen (die
  Admin-Vorschau holt sie bei jedem Mount neu).
- Location sagt per `terrain` WELCHE Art; `/assets/surface-textures`
  sagt WIE: Flächen (`url` kachelbar, `size_m`, Kachelung im
  Welt-Maßstab) oder Zusammenstellungen (`blend` mit `toward`/`zones`/
  `noise`, Zonen von der toward-Kante, `kind:"neighbor"` = häufigste
  Nicht-toward-Nachbar-Art). 404/leer/unbekannt → eingebaute prozedurale
  Fallbacks. 2D-Map-Icons werden NICHT als Boden verwendet
  (`map-icon-2d` ist für den 3D-Pfad tot — README-Verweis streichen).
- **Die Zuordnung `terrain` → Bibliotheks-Kind macht der SERVER**
  (2026-08-05, plan-grundflaeche.md § 5). Jede Location-Auslieferung, die
  `terrain` trägt (`/world/locations`; **seit E1 NICHT mehr der
  Weltkarten-Payload** — dessen Boden kommt aus den gemalten Flächen,
  § A1.5), trägt daneben
  `surface_kind`: die aufgelöste ID, oder `""`, wenn `terrain` keinen
  Eintrag trifft. Regel: kleinschreiben, trimmen, nachschlagen — ein
  Fehlgriff wird nie geraten. Clients lesen `surface_kind` und schlagen
  NICHTS selbst nach; bei `""` bleibt ihr prozeduraler Boden stehen, genau
  wie bei einer Location ganz ohne `terrain`. (Vorher tat das nur der
  3D-Client und nur für die Weltkarte — die Detailszene bekam ihre Platte
  vom Server, also zwei Wege mit zwei Ergebnissen.)
- **`kind` ist die ID, `name` der Anzeigetext** (2026-07-28). Jeder
  Eintrag — Fläche wie Zusammenstellung — trägt `name`; gespeichert und
  referenziert (terrain, `level_floors`, Raum-Boden-/Wandarten,
  `blend.toward`) wird ausschließlich die ID. Sie ist klein, ohne
  Leerzeichen, nach dem Anlegen unveränderlich und taucht in **keinem**
  Bildprompt auf. Ein Client, der Arten zur Auswahl stellt, zeigt `name`
  und schickt `kind`; fehlt `name`, ist die ID als Wörter zu lesen
  (`dark_stone` → „dark stone"). Die dritte Angabe, die **Description**,
  ist reine Server-/Admin-Sache — sie erzeugt das Bild und steht in
  keinem Client-Vertrag.
- **`material` sagt, WIE eine Art beleuchtet wird** (2026-07-28, optional;
  fehlt = `matte`, also unverändert). `{class, tint, …}`, serverseitig
  geklemmt, und **jede Klasse trägt nur ihre eigenen Zahlen** — ein Spec
  behauptet nie einen Regler, den seine Klasse ignoriert:

  | class | Felder | Shader? |
  |---|---|---|
  | `matte` | — (kein Eintrag) | nein |
  | `water` | map_strength, wave_m, speed, sky_mix, roughness | ja |
  | `ice` | dieselben, aber speed 0 als Vorgabe | ja |
  | `gloss` | map_strength, roughness, metalness | **nein** |
  | `glow` | map_strength, glow | **nein** |

  Nur Wasser und Eis brauchen den Shader, und zwar wegen der Bewegung bzw.
  der Fresnel-Spiegelung; `gloss` und `glow` sind reine Materialwerte, die
  das Standardmaterial ohnehin kann. Eine eigene Klasse `metal` gibt es
  nicht — `gloss` trägt `metalness`. `water` heißt: bewegte Kräuselung aus zwei
  gegenläufig scrollenden Normalmap-Lagen (UV aus der WELTposition, sonst
  hätten Nachbarkacheln eine Naht), niedrige Rauheit und ein Fresnel-Anteil
  Richtung Himmelsfarbe. Beide Renderer bauen das Material aus **einer**
  Routine (`surfaceMaterial` in `@anima/scene-render`); die Himmelsfarbe
  reicht der Client aus seiner Tageszeit durch, die Vorschau einen festen
  Tagwert. Die Textur der Art bleibt die Basisfarbe. Das gilt auch für die
  GEMALTEN Weltflächen (§ A1.5): eine Fläche einer Wasser-Art kräuselt und
  spiegelt dort genauso wie Szenen-Wasser, weil der Boden-Patch des 3D-Clients
  (Keller-Loch) sich an den Wasser-Patch ANHÄNGT statt ihn zu überschreiben
  (Befund 2026-08-14).
- **Eine Zusammenstellung übernimmt das Material ihrer `toward`-Art**
  (2026-07-29) und wendet es NUR auf deren Zonen an. Eine Küste ist eine
  Platte mit einer gebackenen Textur; ohne Maske kräuselte der Sandstreifen
  mit. Der Client backt die Maske in derselben Zonen-Schleife wie die
  Textur — gleiche Kante, gleiche Ausfransung — und der Shader multipliziert
  Kräuselung, Rauheit und Fresnel damit. Gelesen wird sie über die
  KACHEL-UV, während die Wellen aus der WELTLAGE rechnen: die Maske gehört
  zur Kachel, die Wellen laufen über Kachelgrenzen. Trägt die
  `toward`-Art keine Klasse, entsteht keine Maske und nichts ändert sich.
- Das Blend-BAKING (Canvas-Komposition, Noise) bleibt bewusst
  Client-Sache — rein visuell, kein Geometrie-Vertrag.
- **`move_anim` — der Clip, mit dem man über einen Boden kommt** (Befund 3
  der E8-Sichtabnahme, 2026-08-13). Ein Gelände-TYP (§ A1.5, nicht die
  Oberflächen-Bibliothek) darf in `meta.move_anim` eine Animations-Art
  nennen; der Server whitelistet diesen `meta`-Schlüssel
  (getrimmter String, höchstens 40 Zeichen wie eine `kind`, leer = Schlüssel
  weg — „keine Animation" ist nie ein leerer String).

  ```
  types: [ …, {kind: "water", …, "speed_factor": 0.4,
               "meta": {"move_anim": "swim"}} ]
  ```

  Vertrag für die Renderer: **bewegt sich eine Figur** — Avatar, NPC oder
  Reisender — **auf einem obersten Gelände mit `move_anim`, spielt sie
  diesen Clip statt `walk`/`run`**, so weit wie die Gelände-Regel dort reicht
  (§ A1.5: Wildnis und offene Orte ja, Gebäude und Innenräume nein); es gibt
  kein Rennen darüber, ein See wird nicht gesprintet. Die
  Art gehört ins OFFENE Clip-Vokabular (§ A8) und wird nirgends gegen eine
  Liste geprüft; fehlt der Clip am Modell, greift die normale
  Ersatzkette (`swim` → `walk` → `idle`). Der Client bezieht die Antwort aus
  EINER Stelle für alle Figuren — sonst tanzen Avatar und NPC im selben
  Wasser verschieden.
- **`idle_anim` — der Clip, mit dem man auf einem Boden WARTET** (Wasser-Runde
  der Abnahme, 2026-08-13). Derselbe Vertrag für den Stand: ein zweiter
  whitelisteter `meta`-Schlüssel mit derselben Formregel, und **steht eine
  Figur auf einem obersten Gelände mit `idle_anim`, spielt sie diesen Clip
  statt ihres eigenen Steh-Clips** — so weit wie dieselbe Gelände-Regel reicht
  (in einer gefliesten Halle im See wird kein Wasser getreten). Nur wo der Boden
  nichts sagt, gilt die alte Ordnung: `activity_animation` vor der
  Aktivitäts-Heuristik (§ A8). Die Boden-Absenkung des Clips (die Figur steht
  auf dem Boden, nicht auf ihrer autorierten Wasserlinie) gilt für BEIDE
  Boden-Clips; `treading-water` fällt am Modell ohne ihn über `idle` zurück.

  ```
  types: [ …, {kind: "water", …, "meta": {"move_anim": "swim",
                                          "idle_anim": "treading-water"}} ]
  ```
- **`move_sink_m` / `idle_sink_m` — wie tief man IN einem Boden steht**
  (2026-08-13, Befund 13). ZWEI whitelistete `meta`-Schlüssel, je eine Zahl in
  Metern (geklemmt 0…1,5, zwei Dezimalen, 0/leer/auf 0 gerundet = Schlüssel
  weg). Die Boden-Normierung setzt den TIEFSTEN Körperpunkt eines Boden-Clips
  auf die Oberfläche — beim Schwimmer ist das ein angewinkeltes Knie, der
  Körper liegt also auf dem Wasser statt darin. Die Absenkung gehört dem BODEN,
  nicht dem Clip: derselbe Zug liegt im See tiefer als in der Furche.

  **Warum zwei Zahlen:** die POSEN hängen verschieden. Der bewegte Schwimmer
  liegt waagerecht, sein tiefster Punkt ist ein Knie handbreit unter dem
  Körper; der Wassertreter steht senkrecht, sein tiefster Punkt ist ein Fuß
  eine ganze Körperlänge tiefer. Auf dieselbe Oberfläche normiert ergibt EINE
  Absenkung für eine der beiden Posen das falsche Bild — Schwimmer abgetaucht
  oder Treter auf dem See stehend. Es gibt bewusst keinen dritten
  Mittelwert-Schlüssel: der Renderer weiß, welcher der beiden Clips läuft.

  Vertrag für die Renderer, in dieser Reihenfolge:
  1. **Wahl nach Zustand:** bewegt sich die Figur → `move_sink_m`; wartet sie →
     `idle_sink_m`, **aber nur, wenn der Boden auch `idle_anim` nennt**. Ohne
     ihn behält die Figur ihren EIGENEN Steh-Clip, und der bringt seine eigene
     Bezugshöhe mit (`sleep` ist auf einem Bett animiert) — den zu versenken
     hieße, den Schläfer durch die Matratze zu schieben. Die Bewegung braucht
     dieses Gate nicht: `walk`/`run` stehen auf dem Boden, auf dem sie laufen,
     ein Moor darf also auch ohne eigenen Clip die Knöchel schlucken.
  2. **Reichweite:** dieselbe wie bei den beiden Clips (§ A1.5 — Wildnis und
     offene Orte ja, Gebäude und Innenräume nein). In einer gefliesten Halle
     im See sinkt niemand ein.
  3. **Verrechnung:** `Absenkung = Clip-Offset × Figurenskalierung + Tiefe`,
     die Tiefe in Weltmetern und NICHT mit der Figur skaliert (ein halber Meter
     Wasser ist für Kind und Riese ein halber Meter); Rückstellung auf exakt
     den Bind-Anker, sobald der Boden-Zustand endet.

  Saat: `water` trägt `move_sink_m` 0,35 und `idle_sink_m` 1,3.

  ```
  types: [ …, {kind: "water", …, "meta": {"move_anim": "swim",
                                          "idle_anim": "treading-water",
                                          "move_sink_m": 0.35,
                                          "idle_sink_m": 1.3}} ]
  ```
- **`swim_from_m` — AB WELCHER WASSERTIEFE die vier Schlüssel oben überhaupt
  gelten** (W4c, 2026-08-23). Ein whitelisteter `meta`-Schlüssel, eine Zahl in
  Metern (geklemmt 0…10, zwei Dezimalen; **0 IST EIN WERT** — „ab der Kante
  schwimmen", das Verhalten jeder Wasser-Art vor dieser Runde — nur Junk lässt
  den Schlüssel weg, fehlender Schlüssel = 1,0 m). Schwimmen war bis dahin eine
  Eigenschaft der ART: `move_anim: swim` lief auf JEDEM Pixel einer
  Wasserfläche, knöcheltief auf der Uferrampe eingeschlossen.

  Vertrag für die Renderer, eine Zeile: `Tiefe = Wasserspiegel − Boden` an der
  Figur (beides liegt vor — lokales Niveau aus `meta.water_profile`, Höhe aus
  der Höhen-Pyramide).
  - `Tiefe ≥ swim_from_m` → SCHWIMMEN: `move_anim`/`idle_anim` und die beiden
    Absenkungen wie oben, der Körper hängt unter dem SPIEGEL.
  - `Tiefe < swim_from_m` → WATEN: der Boden sagt **nichts** — eigener
    Geh-/Lauf- bzw. Steh-Clip, Absenkung 0, und der SPIEGEL gilt für die
    Figur nicht (sie steht auf dem Bett). Die vier Felder werden GEMEINSAM
    abgeschaltet: bliebe das Niveau stehen, hübe `max(Boden, Spiegel)` den
    Watenden auf die Wasseroberfläche.

  Passierbarkeit und Tempo bleiben Sache der ART: `speed_factor` gilt für die
  ganze Fläche, Waten ist ebenfalls langsam. Der Server trägt die Zahl nur
  (Katalog-Sanitizer), gerechnet wird sie im Client
  (`client3d/src/game/walk.wadeGate`). Saat: `river` trägt 1,0 neben Tiefe
  1,2 m und Uferrampe 1,0 m; `water`/`deep_water` nennen keinen Schlüssel und
  bekommen damit dieselbe 1,0.

  ```
  types: [ …, {kind: "river", …, "meta": {"water": true,
                                          "water_depth_m": 1.2,
                                          "shore_ramp_m": 1.0,
                                          "move_anim": "swim",
                                          "idle_anim": "treading-water",
                                          "move_sink_m": 0.35,
                                          "idle_sink_m": 1.3,
                                          "swim_from_m": 1.0}} ]
  ```
- **`sway_m` — wie weit das WEHT, was auf einem Boden wächst** (2026-08-14).
  Ein whitelisteter `meta`-Schlüssel, eine Zahl in Metern (geklemmt 0,01…0,5,
  zwei Dezimalen, 0/leer/Junk = Schlüssel weg) = maximale seitliche Auslenkung
  der SPITZE. Vertrag für die Renderer: die Zahl hängt an der ART der Fläche,
  also wehen ALLE Streu-Einträge einer solchen Fläche — Büschel wie
  Modell-Props —, die Flächen-FÜLLUNG dagegen nie (dort animiert allein die
  Wasser-Klasse). Die Auslenkung wächst QUADRATISCH mit der Höhe über dem
  Boden (Fuß steht, Spitze trägt die volle Zahl), jede Instanz bekommt aus
  ihrer Weltlage eine eigene Phase, und Frequenz wie Windrichtung stehen fest
  im Renderer — es gibt dafür keine weiteren Katalog-Schlüssel. **Die Zahl gilt
  je Instanz, nicht je Geometrie** (2026-08-15): wo eine Instanz eigens
  skaliert wird (der Unterwuchs skaliert jedes Büschel auf seine Höhe), teilt
  der Renderer die Amplitude durch diese Skalierung — eine 0,7-m- und eine
  0,4-m-Instanz derselben Geometrie lenken die Spitze beide um genau `sway_m`
  aus. Saat: `grass`
  0,06 und `forest` 0,04; eine Welt-Zeile ersetzt den geteilten Eintrag ganz,
  also fehlt der Schlüssel dort, bis er im Typen-Dialog gesetzt wird.
  **Wie stark ein EINZELNES Prop davon mitmacht, sagt das Prop** (2026-08-14):
  jeder Bibliotheks-Eintrag trägt einen `sway_factor` 0..1 (Default 1, im
  Props-Reiter gesetzt), den `GET /play/terrain` wie `prop_height_m` an den
  Streu-Eintrag hängt — und nur dann, wenn er vom Default abweicht, so dass ein
  fehlendes Feld überall „weht ganz" heißt. Die wirksame Auslenkung ist das
  Produkt `sway_m(Art) × sway_factor(Eintrag)`; ein Findling mit Faktor 0 steht
  still in derselben Wiese, deren Farne voll wehen. Die Art beantwortet „wie
  stark weht es hier", das Prop „wie sehr bewege ich mich darin" — es gibt
  dafür weiterhin keinen Katalog-Schlüssel und keinen Override pro
  Streu-Eintrag. **Die Stillstands-Schwelle liegt bei 0,005 m:** das Produkt
  wird auf zwei Dezimalen gerundet, und der Renderer weist alles unter
  `SWAY_MIN_M` (0,01) ab — ein Produkt unter 0,005 ist damit exakt 0, das Prop
  steht still und bekommt kein eigenes Material. Auf `grass` (0,06) steht
  folglich jeder Faktor bis 0,08 still, auf einer 0,01-Fläche jeder unter 0,5.
  Gewollt: ein Wackeln, das der Shader ohnehin verwirft, soll keinen
  Material-Klon je Fläche kosten.

  ```
  types: [ …, {kind: "grass", …, "meta": {"sway_m": 0.06}} ]
  # so ausgeliefert (nicht so gespeichert — das Feld hängt am Prop):
  areas: [ …, {"meta": {"scatter": [{…, "model": "/assets/props/rock/model",
                                     "sway_factor": 0.0}]}} ]
  ```

  **Wie tief ein Prop im Boden steht, sagt ebenfalls das Prop** (2026-08-20):
  `ground_offset_m` (± Meter, Zentimeter-Schritte, Grenze ±5) hängt genau wie
  `sway_factor` am Bibliotheks-Eintrag und reist nur mit, wenn er nicht 0 ist.
  Jede Instanz wird bei `heightAt(x, z) + ground_offset_m` gesetzt — dieselbe
  Zahl, mit der dasselbe Prop in jedem Raum und an jedem Welt-Punkt steht.
  Ausführlich im Nachtrag 2026-08-20 (§ B2/§ A9/§ A9a) am Ende dieses Dokuments.
- **`undergrowth` — wie viel auf einem Boden VON SELBST wächst** (2026-08-15,
  Erzeugung umgebaut 2026-08-16). Ein whitelisteter `meta`-Schlüssel, eine
  Zahl 0…1 (zwei Dezimalen, 0/leer/Junk = Schlüssel weg) = Anteil der vollen
  Unterwuchs-Dichte des Clients. Der Server liefert NUR diese Zahl; Position,
  Höhe, Distanzen und Geometrie gehören dem Renderer, es gibt dafür keine
  weiteren Katalog-Schlüssel und kein Authoring pro Fläche.

  **Vertrag für die Renderer — KAMERA-LOKAL, nicht pro Fläche.** Der Unterwuchs
  wird NICHT mehr über die ganze gemalte Form vorgebaut, sondern pro ZELLE
  eines ursprungsverankerten 64-m-Rasters im Umkreis von 128 m um denselben
  Anker, den die feinen Höhen-Kacheln nutzen (§ A16.5: der Avatar, solange der
  Spieler ihn steuert, sonst das Kamera-Bodenziel). Basis-Dichte **0,80
  Instanzen/m² × Wert** (0,40 bis zur Sicht-Abnahme 2026-08-16, 0,15 vor dem
  Umbau), Deckel **8000 je Zelle** — ein Schutz gegen handgeschriebenen Unsinn,
  den die auf 1 geklemmte Katalog-Zahl nie erreicht (volle Dichte will 3277 je
  Zelle). Der alte Flächen-Deckel von 20 000 ist ersatzlos weg: er war auf
  einem Quadratkilometer nicht Schutz, sondern die Dichte (0,02/m², sichtbar
  leerer Wald). Damit ist ein 10-km²-Wald lokal exakt so dicht wie eine kleine
  Wiese, und die Kosten sind konstant (~21 Zellen à ~1966 Büschel bei
  forest 0,6).

  Die Verdopplung von 0,40 auf 0,80 ist die Antwort auf den Abnahme-Befund
  „vereinzelte Grasbüschel“: bei 0,40 steht bei vollem Wert alle 1,6 m ein
  Büschel, bei 0,80 alle 1,1 m — und weil ein Büschel 1,25 × seiner Höhe breit
  gezeichnet wird (~0,69 m bei der Referenzhöhe 0,55 m), berühren sich die
  Silhouetten und die Schicht liest sich als geschlossene Grasdecke. Beides
  gehört dem Renderer; der Server liefert weiterhin nur die 0…1.

  **Positionen** kommen aus demselben seed-stabilen Sampler wie die autorierte
  Streu, aber unter EIGENEM Seed **pro (Fläche, Zelle)**:
  `terrain:undergrowth:<area_id>:<cx>,<cz>`. Der Namensraum hält die Schicht
  aus dem Strom der autorierten Props (`terrain:scatter:…`), damit sich
  vorhandene Props nicht verschieben; die Zellkoordinate hält Nachbarzellen
  auseinander — ohne sie stünde dasselbe Büschel-Muster alle 64 m gestanzt in
  der Welt. Eine Zelle sampelt über die Flächen, die sie schneiden, in der
  Terrain-Reihenfolge (last-hit-wins wie `terrain_query`); Fußabdrücke und
  überdeckende Flächen respektiert sie wie normale Streu.

  **Eine Regel gilt NUR für Zellen, nicht für Formen:** die Zelle ist ihre
  eigene Bounding-Box, also wird nie ein Kandidat verworfen, weil er den Ring
  verfehlt — der Sampler läuft mit `triesPerPoint: 1`, damit die
  verbleibenden Ablehnungen (Fußabdruck, darüberliegende Fläche) SUBTRAHIEREN
  statt nachgewürfelt zu werden. Beim Sampeln einer FORM ist das Nachwürfeln
  richtig (ein Ring füllt seine Box nur teilweise); bei einer Zelle würde es
  eine ganze Zellfüllung in die sichtbare Hälfte quetschen, also doppelte
  Dichte an jeder Hauswand.

  Die Schicht weht mit dem `sway_m` der Art (ohne `sway_factor` — sie ist kein
  Prop), nimmt am Verdeckungs-Korridor teil und hat ein EIGENES, kürzeres LOD:
  voll sichtbar bis 30 m, danach linear ausgedünnt bis auf 0 bei 60 m (kein
  25-%-Sockel wie bei der Objekt-Streu — ein kniehohes Büschel ist an der
  Kante ohnehin unsichtbar, es gibt also nichts, was poppen könnte). Höhen
  variieren 0,4…0,7 m. Saat: `forest` 0,6 und `grass` 0,3; eine Welt-Zeile
  ersetzt den geteilten Eintrag ganz, der Schlüssel fehlt dort also, bis er im
  Typen-Dialog gesetzt wird.

  ```
  types: [ …, {kind: "forest", …, "meta": {"sway_m": 0.04,
                                           "undergrowth": 0.6}} ]
  ```

## A9a. Welt-Props — einzeln gesetzte Props auf der Weltebene (E2.2)

Beschlossen 2026-08-19, Programm „Prop-Welt statt Dioramen", Etappe 2 Nr. 2.
Die gemalte Fläche (§ A9, `meta.scatter`) sagt, wie DICHT ein Boden etwas
wachsen lässt — eine Statistik. Eine Statistik kann nicht sagen „DIESER
Findling, HIER, so gedreht". Genau das ist ein **Welt-Prop**: ein Prop aus
der Bibliothek, von Hand an EINEN Punkt in Weltmetern gesetzt, außerhalb
jeder Location.

**Speicher:** eigene Tabelle `world_props` in `world.db`
(`app/models/world_props.py`), CRUD unter `/world/world-props`
(GET/POST/PUT/DELETE, die Formgleiche der Terrain-Flächen nebenan).
Autoriert werden genau sechs Größen: `prop_id`, `x`, `z` (Weltmeter),
`yaw_deg`, `offset_y` und ein optionaler `variant`-Index.

**Deko, sonst nichts (v1, Beschluss E2.1).** Ein Welt-Prop blockiert
NICHTS: er steht in keinem Nav-Grid, er schiebt keine Figur beiseite, er
gehört zu keiner Location. Was umlaufen werden muss, ist ein
Location-Fußabdruck oder eine gemalte Fläche — kein Prop.

**Nie gefoggt.** Der Block wird ungefiltert ausgeliefert, und das ist die
Entscheidung, nicht ein Versehen: reine Deko verrät keine Ortskenntnis,
und ein Schleier, der Möbel wegnimmt, ließe die Wildnis beim Entdecken ihr
Mobiliar wechseln.

**Weiche Obergrenze 500 je Welt.** Ein CREATE darüber wird mit 400
abgelehnt (`at most 500 world props per world`); ein UPDATE nie — eine
volle Welt muss ihre Props noch verschieben dürfen. Ab **200** warnt der
Karten-Editor im Zähler-Chip. Die Grenze ist ein Zeichenbudget, kein
Speicherproblem: heute ist jede Platzierung ein eigener Draw-Call in beiden
Renderern (Instancing des Rests ist vertagt).

### Payload — Wurzelfeld `world_props` in `GET /play/worldmap` (§ A1.3)

Zwei neue Wurzelfelder, immer vorhanden:

| Wurzelfeld | Typ | Bedeutung |
|---|---|---|
| `world_props` | `[{…}, …]` | Die gesetzten Props, in Autorenreihenfolge. **Leere Liste = keine.** Nie gefoggt |
| `world_props_sig` | `str` (10) | Signatur über den FERTIGEN Block — dieselbe Aufgabe wie `terrain_sig`: bewegt sie sich, baut der Client seine Meshes neu, sonst nie. Gehasht über die ausgelieferten Zeilen, nicht über die Tabelle, denn die Zeilen tragen die abgeleitete Hälfte mit (ein im Hintergrund erzeugtes `low`-Mesh ändert keine DB-Zeile und muss trotzdem ankommen) |

Eine Zeile:

```
{ id: "wp_1a2b3c4d",           # Platzierungs-ID, stabil; SEED der Varianten-Formel
  prop_id: "bench-ab12cd",     # Bibliotheks-Prop
  name: "Park bench",          # Anzeigetext aus der Bibliothek (Editor/Debug)
  x: 12.5, z: -40.0,           # WELTMETER
  yaw_deg: 45.0,               # Grad, Drehsinn dieses Vertrags (§ A1.1/§ B2)
  offset_y: 0.0,               # Anhebung ÜBER dem Boden, Meter (±50)
  max_m: 1.8,                  # größte ECHTE Kante der GEZEIGTEN Variante, Meter
  measure: "xyz",              # das EINE Maßstabsgesetz von place() (§ B2)
  fix_euler: {x:0, y:90, z:0}, # Orientierungs-Fix des Props, Grad
  variants: {full: "…", low: "…"},   # Stufen-Karte der PRIMÄREN Variante
  model_variants: [ {…}, {…} ],      # NUR wenn das Prop mehr als eine hat
  variant: 1 }                       # dito — der aufgelöste Index
```

- **Maßstab ist `max_m` + `measure: "xyz"`, nicht `height_m`.** Ein
  Welt-Prop läuft durch dieselbe `place()`-Routine wie ein Szenen-Prop
  (§ B2), also gilt dasselbe Gesetz: größte reale Kante geteilt durch
  größte gemessene Kante, EIN Faktor auf alle drei Achsen. Eine Bank vor
  dem Haus ist damit so groß wie dieselbe Bank im Haus. Die Autorengröße
  der GLB gilt nie — die Normalisierung hat den Maßstab zerstört. (Die
  Streu nebenan skaliert auf eine ZIELHÖHE, weil dort niemand ein einzelnes
  Objekt meint, sondern „kniehoch" oder „baumhoch".)
- **`max_m` und `fix_euler` sind ABGELEITET, nie gespeichert** — genau wie
  die Zusatzfelder der Streu-Einträge (§ A9): eine im Props-Tab korrigierte
  Größe oder ein nachgezogener Fix wirkt beim nächsten Poll. `max_m` gehört
  seit dem Nachtrag 2026-08-24 zur **gezeigten Variante**, nicht zum Prop:
  trägt die Variante hinter `variant` eigene Maße, sind es deren Maße —
  dieselbe Liste, derselbe Index, also kann eine Zeile nie auf ein Mesh
  skaliert werden, das sie gar nicht zeichnet.
- **Der Boden kommt vom Client.** Der Server schickt `offset_y`, der
  Renderer setzt `bottom_y = Bodenhöhe(x, z) + offset_y` mit **seinem**
  Höhen-Sampler (`heightAt`, § A16.5) — derselbe, mit dem die Streu steht.
  Nur so bleibt ein Prop auf dem Relief kleben, das der Client wirklich
  zeichnet, statt auf einem, das der Server einmal gerastert hat.
- **Zeilen ohne Mesh fallen weg.** Ein Prop, das gelöscht wurde oder keine
  aktive Variante mit Mesh hat, erzeugt keine Payload-Zeile — eine Zeile
  ohne Modell wäre ein Loch in jeder Renderer-Schleife. Sichtbar wird so
  eine Platzierung im Karten-Editor (`GET /world/world-props` liefert
  `missing: true`); und das Löschen eines Props räumt seine Platzierungen
  gleich mit weg (`DELETE /world/props/{id}` → `world_props_removed`).

### Welche Variante ein Welt-Prop zeigt

Dieselbe Arbeitsteilung wie überall (§ B2-Nachtrag): **der Server wählt,
der Renderer führt aus.** Zwei Fälle, eine Formel:

```
variant = autorierter Index                              (wenn gesetzt)
        = int(md5(placement_id).hexdigest()[:8], 16) mod n   (sonst)
```

`n` = Anzahl der AKTIVEN Varianten MIT Mesh, also `len(model_variants)`.
Implementierung: `app/models/world_props.variant_index`. Der Index wird
**modulo** gerechnet, nie geklemmt — die Variantenzahl bewegt sich, wenn
ein Admin ein Mesh ergänzt oder löscht, und eine Platzierung darf davon
nicht verschwinden.

Warum die Platzierungs-ID der Seed ist: sie ist die einzige stabile Zahl,
die eine EINZELNE Platzierung hat (eine Streu-Kopie hat Flächen-Seed plus
Instanz-Nummer, eine handgesetzte hat weder noch). Gezogen wird aus dem
MD5 der ID und nicht aus Pythons `hash()`, das pro Prozess gesalzen ist —
sonst zeigte derselbe Findling nach jedem Neustart ein anderes Mesh.

**Handrechnung zur Nachprüfung (§ B5a), 3 aktive Varianten:**

| `placement_id` | `md5[:8]` | als Zahl | `mod 3` |
|---|---|---|---|
| `wp_00000001` | `9b65e854` | 2607147092 | **2** |
| `wp_1a2b3c4d` | `e3f1ba37` | 3824269879 | **1** |
| `wp_deadbeef` | `f33a24d6` | 4080674006 | **2** |
| `wp_c0ffee01` | `ee5538df` | 3998562527 | **2** |

Bei 2 Varianten: 0, 1, 0, 1. Bei 4: 0, 3, 2, 3.

**Auflösung im Renderer:** unverändert `pickModelVariant(spec, tier)` aus
`@anima/scene-render` — die Zeile trägt genau die Felder, die diese
Routine liest.

### Wo Welt-Props NICHT auftauchen

- **Spieler-Karte und Minimap: gar nicht.** Deko ist v1 rein 3D. Eine
  2D-Karte, die jede Bank einzeichnet, ist keine Karte mehr; ob und wie
  ein Landmarken-Prop dort ein Symbol bekommt, ist eine eigene
  Entscheidung.
- **Nav-Grid, Perzeption, Prompts: gar nicht.** Ein Welt-Prop ist für die
  Simulation nicht vorhanden.

## A9b. Prop-Boxen — die Streu wächst nicht durch eine Bank (2026-08-23)

**Befund des Nutzers:** die Streu (§ A9) stand mitten in einzeln gesetzten
Welt-Props (§ A9a). Der Sampler kannte bis dahin nur gesetzte **Locations**
(`ScatterFootprint`, Befund B18) — und ein Prop ist keine Location.

**Die Regel — es ist keine neue Regel.** Der Server liefert pro Platzierung
die **Grundfläche**, die sie belegt; beide Renderer machen daraus einen
Footprint wie jeden anderen und geben ihn dem geteilten Sampler
(`packages/scene-render/src/scatter.ts`) mit. Im Sampler ändert sich **nichts**
— nur die Quelle ist neu.

```
ausgeschlossen  <=>  footprintBlocks(box, x, z, clearM)
```

also exakt dieselbe Freihaltung, die auch eine Location bekommt: der Abstand
des Streu-Exemplars (`clearM`, halbe Eigenbreite) zählt mit, ein 8-m-Baum hängt
also auch nicht über die Bank.

### Payload — `prop_boxes`

Ein Block, EINE Quelle: `app/models/world_props.prop_boxes()`. Ausgeliefert an
beiden Stellen, an denen der jeweilige Verbraucher ohnehin liest:

| Route | Verbraucher |
|---|---|
| `GET /play/terrain` → `prop_boxes` | 3D-Client (`client3d/src/scene/ground.ts`) |
| `GET /world/world-props` → `prop_boxes` | Karten-Editor (`frontend/src/tabs/map/MapTab.tsx`) |

| Feld | Typ | Bedeutung |
|---|---|---|
| `id` | `str` | die Platzierungs-ID (§ A9a) |
| `x`, `z` | `float` | Anker in Welt-Metern — dieselben Zahlen wie in `world_props` |
| `yaw_deg` | `float` | Drehung der Platzierung, 0…360 |
| `half_w` | `float` | halbe REALE Breite (lokales x) **plus Rand** |
| `half_d` | `float` | halbe REALE Tiefe (lokales z) **plus Rand** |

Die realen Maße sind die der **gezeigten Variante** (Nachtrag 2026-08-24) —
aufgelöst über dieselbe Formel wie die Payload-Zeile (`variant` der
Platzierung, sonst `variant_index(id, n)`), damit die freigehaltene Fläche die
Fläche des Meshes ist, das dort wirklich steht. Ein Prop mit Datensatz, aber
ohne jedes Mesh, behält seine Box in den Maßen der primären Variante.

Der Rand ist `world_props.PROP_BOX_MARGIN_M` = **0,25 m**, auf beide
Halbachsen addiert — eine Handbreit blanker Boden um das Objekt. Bewusst EINE
Zahl für alle Props: ein Rand pro Prop wäre ein zweiter Größenregler neben den
echten Maßen, nirgends autoriert.

**Gedreht, nicht achsenparallel.** `ScatterFootprint` ist ein Polygon, und
`propBoxFootprint()` (im geteilten Paket) rechnet die vier Ecken über die EINE
§-A1.1-Abbildung aus — über die lokalen Ecken (−hw,−hd), (+hw,−hd), (+hw,+hd),
(−hw,+hd):

```
x = cx + lx·cos(yaw) + lz·sin(yaw)
z = cz − lx·sin(yaw) + lz·cos(yaw)
```

Eine achsenparallele Box um ein um 30° gedrehtes Prop wäre an zwei Ecken zu
groß (kahler Fleck) und an zwei Ecken zu klein (Baum in der Bank) — beides auf
der Karte sichtbar. Handrechnung dazu in
`client3d/scripts/smoke_scatter_math.mjs` Abschnitt (P), inkl. rotem
Gegenversuch (Mutant mit cos 1 / sin 0).

**Was KEINE Box bekommt:**

- eine Platzierung, deren Prop-Datensatz weg ist — sie hat keine Größe und
  rendert ohnehin nichts;
- eine Platzierung **innerhalb der Boundary einer gesetzten Location**: dieses
  Outline schließt die Streu bereits über seine ganze Fläche aus
  (`boundary_contains`), die Box wäre dieselbe Antwort ein zweites Mal in jedem
  Payload jeder Welt. Redundant, nicht falsch — der Sampler liefert mit Box
  dasselbe Ergebnis (Smoke (P5)).

Eine Platzierung, deren Prop nur **noch kein Mesh** hat, bekommt ihre Box
dagegen sehr wohl: der Autor hat sie gesetzt, der Boden ist vergeben.

**Streu-Kopien sind nie in diesem Block.** „Gesetzt" heißt von Hand gesetzt.
Die Instanzen jeder Fläche — der eigenen wie jeder anderen — werden um diese
Boxen herum gesampelt; eine Streu-Kopie dünnt umgekehrt nichts aus.

**Signatur:** `terrain_sig` hasht die Boxen mit (dieselbe Doktrin wie bei der
Streu-Anreicherung, § A9). Eine um einen Meter versetzte Bank bewegt also die
Signatur, der Client holt `/play/terrain` neu und sampelt den Wald um sie herum
neu. Der Karten-Editor braucht das nicht: er lädt `/world/world-props` nach
jedem Prop-Schreibvorgang ohnehin neu.

**Prüfungen (§ B5a):** `client3d/scripts/smoke_scatter_math.mjs` (P1)–(P6),
`scripts/smoke_world_props.py` [9].

## A10. Kamera & Steuerung (Referenz, unverändert)

FOV 45°, near 0,5, far 800; Orbit um Bodenpunkt, dist 2,5..150,
zoomgekoppelter Pitch `lerp(18°, 62°, sqrt(norm(dist)))` + Offset ±35°
(gesamt 8..85°); exponentielle Glättung ~8/s. Links ziehen = bodenver-
ankertes Pan, Mitte/Shift = Drehen/Neigen (0,005 rad bzw. 0,25°/px),
Rad = Zoom auf Cursor (`dist *= exp(ΔY·0,0012)`), Klick = Auswahl bei
< 0,15 Einheiten Bewegung. Q/E ±45°, +/− Zoom-Stufen, WASD Pan.
Im **Avatar-Modus** (embodied) dreht bereits das blanke Linksziehen — die
Kamera folgt dort der Figur, ein Pan hätte keine Wirkung; Klick bleibt Klick
(Geh-Befehl) bis 4 px Zeigerweg. In der Übersicht gilt unverändert das obige.
Raum-Vorschau-Start: dist 22, Pitch-Offset +28°, Target Kachelmitte.

## A11. Reise-Payload (server-autoritative Bewegung) — Meter-Polyline seit E3 (2026-08-09)

Ein Charakter wechselt die Location nicht schlagartig, sondern **läuft eine
Polylinie in Welt-Metern ab**. `GET /play/worldmap` liefert dafür pro
Charakter das Feld **`travel`** — `null`, solange keine Reise läuft.

> **Die Zellen-Ära ist vorbei.** `path` (Location-Kette), `seg`, `frac`,
> `progress_cells` und `cell_seconds_real` sind **ersatzlos gestrichen**;
> die Welt-Einstellung heißt `game.travel_speed_m_s` (Meter pro SPIEL-Sekunde,
> Default 1,4, geklemmt auf 0,1…20), nicht mehr `travel_seconds_per_cell`.
> Ein Client, der noch gegen die alten Felder baut, sieht ab E3 nur
> `undefined`.

| Feld | Typ | Bedeutung |
|---|---|---|
| `target_id` | `str` | Ziel-Location (identisch mit `movement_target_id`) |
| `waypoints` | `[[x, z], …] \| null` | Route in Welt-Metern, auf 2 Stellen gerundet, **inkl. Start- und Zielpunkt**. **Ohne Zeiten** — die beim Start gebackenen Zeitmarken (`t_cum`) bleiben serverintern, der Client rechnet über die STRECKE. Die Formel unten kommt auch mit einer entarteten Ein-Punkt-Linie klar (Reise ohne Weg). **`null` im gefoggten Payload für JEDEN außer dem Avatar** — siehe Fog-Absatz unten |
| `progress_m` | `float \| null` | bereits gelaufene Strecke **entlang der Polylinie**, in Metern. **`null` im gefoggten Payload für JEDEN außer dem Avatar** (E6) — siehe Fog-Absatz unten |
| `total_m` | `float \| null` | Gesamtlänge der Polylinie in Metern. **Gefoggt `null`** wie `progress_m` |
| `eta_game` | Kalenderzeit `\| null` | nominelle Ankunft auf der **Spieluhr**, als **kanonischer Weltkalender-Stempel** `"Y0002-D109T14:00:00"` (Jahr 4-stellig, Tag im Jahr 3-stellig). Kein ISO-Datum, **keine Weltzeitzone** — die gibt es nicht mehr. Der Client PARST das Feld nicht: es ist der Vergleichs-/Sortierwert, die Anzeige kommt aus den beiden Feldern darunter. **Gefoggt `null`** wie `progress_m` |
| `eta_hhmm` | `str \| null` | Ankunftszeit als fertiges `"HH:MM"` — vom Server gerendert. **Gefoggt `null`** wie `progress_m` |
| `eta_label` | `str \| null` | Ankunft als vollständiges, lokalisiertes Kalender-Label (z. B. `"Summer, day 17 · 14:23 · Year 3"`; Sprache = die des Avatars). Für Reisen, die über Mitternacht laufen, ist das die einzige vollständige Angabe. **Gefoggt `null`** wie `progress_m` |
| `speed_m_s_real` | `float \| null` | **Nominal**-Reisetempo in Metern pro **ECHTER** Sekunde (`speed_m_s × Zeitfaktor`); `null`, wenn nicht extrapoliert werden darf: eingefrorene Welt bzw. Zeitfaktor 0 — und ebenso, wenn die Reise kein brauchbares `speed_m_s` trägt (fehlend, 0 oder negativ). **Gefoggt `null`** wie `progress_m` |
| `pace_m_s_real` | `float \| null` | **Echtes** Tempo des Segments, das die Figur GERADE läuft, in Metern pro ECHTER Sekunde: `\|w[seg+1] − w[seg]\| / (t[seg+1] − t[seg]) × Zeitfaktor` aus denselben gebackenen Zeitmarken (seit **E4**, 2026-08-09). Damit steckt der Gelände-`speed_factor` drin, den `speed_m_s_real` nicht kennt. `null`, wenn es kein aktuelles Segment gibt oder nichts extrapoliert werden darf: eingefrorene Welt / Zeitfaktor 0, angekommen (Zeit über dem Ende), entartetes Segment (Länge 0 oder Zeitspanne 0). **Gefoggt `null`** wie `progress_m` |

**Semantik**

- **Die Position ist eine reine Funktion der Spieluhr.** Server und alle
  Clients rechnen aus demselben Payload dieselbe Position — es gibt kein
  client-eigenes Pathfinding und keine eigene Reisezeit. Aus `progress_m`
  wird der Punkt durch **Ablaufen der Strecke** gewonnen:

  ```
  d = progress_m
  für i = 0 … n−2:
      L = |waypoints[i+1] − waypoints[i]|
      wenn d ≤ L:  pos = lerp(waypoints[i], waypoints[i+1], d / L); fertig
      d −= L
  sonst:           pos = waypoints[n−1]
  ```

  Das ist die EINE Formel; ein Segmentindex steht bewusst nicht im Payload
  (er wäre eine zweite Wahrheit neben `progress_m`).
- **`speed_m_s` ist Meter pro SPIEL-Sekunde und steht auf der Reise.** Sie
  wird beim START aus `game.travel_speed_m_s` (Admin → Game) gelesen und
  festgeschrieben — laufende Reisen behalten ihr Tempo, eine geänderte
  Einstellung re-timet niemanden. Der Client bekommt sie nur in
  Realzeit-Form (`speed_m_s_real`) und rechnet ausschließlich damit.
  **Faktor-Richtung:** eine DAUER wird durch den Zeitfaktor geteilt (so
  rechnete v1 `cell_seconds_real`), ein TEMPO mit ihm multipliziert —
  Faktor 2 heißt doppelt so viele Meter pro echter Sekunde.
- **Zwei Tempo-Felder, und `pace_m_s_real` ist das, mit dem gerechnet wird.**
  Der Gelände-`speed_factor` (§ A1.5) steckt ausschließlich in den
  serverinternen Zeitmarken der Reise, nicht in `speed_m_s`. Auf zähem
  Untergrund (Faktor 0,5) läuft die Figur real halb so schnell, wie
  `speed_m_s_real` sagt; auf schnellem Untergrund umgekehrt. Seit **E4**
  liefert der Server deshalb zusätzlich `pace_m_s_real`, das echte Tempo des
  aktuellen Segments, aus denselben Zeitmarken:

  ```
  pace_m_s_real = |w[seg+1] − w[seg]| / (t[seg+1] − t[seg]) × Zeitfaktor
  ```

  * **Extrapoliert wird mit `pace_m_s_real`**, `speed_m_s_real` ist nur der
    Rückfall, wenn es `null` ist (Regel 2 unten). Innerhalb eines Segments ist
    das exakt, nicht genähert; das Schnappen am Poll bleibt nur für den
    Segmentwechsel dazwischen übrig.
  * `speed_m_s_real` bleibt der NOMINALE Wert (die Reisegeschwindigkeit, mit
    der die Reise gestartet wurde) und macht keine Aussage über den
    Untergrund.
  * Die Restzeit-Division unten bleibt eine Näherung — sie rechnet mit EINEM
    Tempo über den ganzen Restweg, der durch beliebiges Gelände führt.
    **Autoritativ für die Ankunft ist `eta_game`** — es kennt die
    Gelände-Zeiten, die Division kennt sie nicht. Ein Countdown darf
    gerechnet werden, ein *Termin* wird angezeigt.
- **`pos` (§ A1.4) und `travel` widersprechen sich nicht.** `pos` ist der vom
  Reise-Ticker geschriebene Punkt und wird nur im **Ticker-Takt (5 s)**
  nachgeführt; `travel` erlaubt die stetige Ableitung dazwischen. Für einen
  Charakter MIT `travel` UND `waypoints` ist die Render-Position die aus
  `waypoints` + `progress_m` abgeleitete; ohne `travel` — und ebenso bei
  `waypoints: null` (Fog, s. u.) — ist es `pos`. Beide stammen aus
  derselben Funktion und stimmen im Ticker-Takt exakt überein.
- **`location_id` folgt dem Punkt, nicht der Route.** Unterwegs steht ein
  Reisender meist in der **Wildnis** (`location_id: ""`, § A1.4) — das ist
  der Normalzustand einer Reise, kein Fehler. Die Ziel-Location wird erst
  bei der Ankunft gesetzt.
- **Ankunft erkennt der Client daran, dass `travel` verschwindet.** Der
  Ticker verbucht sie, sobald die Spielzeit `eta_game` erreicht hat — also
  bis zu einem Ticker-Takt (5 s echt) SPÄTER, nicht früher (die halbe Zelle
  Vorlauf aus v1 gibt es nicht mehr). Solange kann `progress_m == total_m`
  stehen bleiben. Clients verzweigen auf **„Feld weg"**, niemals auf
  `progress_m == total_m` oder auf das Erreichen von `eta_game`.

  **Ausnahme mit derselben Wirkung — die Route KREUZT das Ziel.** Der
  Wegfinder nimmt den Footprint des Ziels für dessen eigene Route aus (sonst
  wäre eine abgewandte Tür unerreichbar), die Route läuft also mitunter durch
  das Gebäude. Steht der interpolierte Punkt eines Takts INNERHALB des Ziels,
  ist die Figur dort — der Server verbucht diesen Takt als Ankunft und schickt
  ihn durch dasselbe Zugangs-Gate (`check_access` + `accessible_when`).
  `travel` verschwindet dann vor `eta_game`. Für Clients ändert das nichts:
  die Regel bleibt „Feld weg = angekommen", und `location_id` folgt wie immer
  dem Punkt.

  **Welcher RAUM dabei herauskommt, entscheidet der RESTWEG** (seit E4;
  vorher ein 0,5-m-Umkreis um den letzten Wegpunkt): ist
  `total_m − progress_m` höchstens ein Ticker-Takt weit (5 s × `speed_m_s`
  der Reise, in SPIEL-Sekunden gerechnet, also unabhängig vom Zeitfaktor),
  gilt die Figur als auf dem Schlussanflug und bekommt den Raum hinter der
  angepeilten Tür (`entry_room` der Öffnung). Sonst ist es der ANKUNFTSRAUM
  des Ziels — dann ist die Figur irgendwo anders ins Gebäude gelaufen und
  hat auf den Raum hinter jener Tür keinen Anspruch. Der Umkreis war für die
  häufigste Geometrie falsch: läuft der Schlussanflug WANDPARALLEL auf die
  eigene Tür zu (der Wegfinder liefert das laufend), liegt die Route ihre
  letzten Meter schon im Footprint — der Ticker erwischt die Kreuzung ein
  paar Meter vor der Tür, und 0,5 m Umkreis nannten das „woanders".
- **Ankunft ist nicht garantiert.** Verweigert die Zugangsregel am Ziel den
  Eintritt — `rules.check_access` ODER das `accessible_when` des Ziels —,
  endet die Reise auf dem letzten Routenpunkt VOR dem Ziel („Standoff");
  bei einer vorzeitigen Ankunft (s. o.) auf dem letzten Punkt des BEREITS
  GELAUFENEN Stücks, nie einem weiter vorn. Auch dann verschwindet `travel`
  einfach.
- **Freeze:** steht die Spieluhr, stehen alle Reisen. `progress_m` bleibt
  konstant, `speed_m_s_real` und `pace_m_s_real` sind `null` — genau dann
  darf nicht extrapoliert werden.
- **Ein laufender Restzeit-Countdown rechnet in ECHTEN Sekunden**,
  näherungsweise `(total_m − progress_m) / speed_m_s_real` — NICHT `eta_game`
  gegen eine lokale Uhr (die Spieluhr läuft mit Faktor und kann springen).
  Das Wurzelfeld `game_time` nennt zwar das Spiel-Jetzt dieses Payloads, aber
  nur zum ANZEIGEN: zwischen zwei Polls läuft es nicht weiter. Der
  ANGEZEIGTE Ankunftszeitpunkt kommt immer aus `eta_hhmm`/`eta_label` —
  fertig gerendert, weil kein Client einen Weltkalender rechnen soll.
- **Fog (§ A12) gilt auch für Reisende:** ein Charakter in einer dem Avatar
  unbekannten Location fehlt komplett — mitsamt seiner Reise. Der
  `target_id` im eigenen Block wird NICHT verschwiegen (wie
  `movement_target_id`), wohl aber der Name: `movement_target_name` bleibt
  leer, solange der Avatar das Ziel nicht kennt.
  **In der Wildnis bleibt ein Reisender dagegen stehen** — die
  Sichtweiten-Regel für Wildnis-Charaktere (§ A12) gilt für ihn NICHT: eine
  Reise läuft die meiste Zeit durchs Freie, und eine Figur, die dafür die
  ganze Reise lang verschwindet, ist genau der Fehler, den § A11 seit E4
  beschreibt. Seine Zeile bleibt, ausgedünnt nach der nächsten Regel.
- **Die ROUTE ist Avatar-Wissen — und ihre ZAHLEN auch** (Ausdünnung seit
  **E6**). Im gefoggten Payload trägt nur der Avatar selbst seine
  `waypoints`; bei allen anderen Charakteren ist das Feld `null`. Grund: die
  Polylinie endet an der Türöffnung des Ziels — sie wäre eine meter-genaue
  Kartenmarke für einen Ort, den der Avatar nicht kennt. **Dasselbe sagen
  aber auch die Zahlen daneben**: aus Position, Restweg (`total_m −
  progress_m`), Ankunftszeit und Tempo lässt sich das unbekannte Ziel
  einkreisen. Gefoggt sind für jeden außer dem Avatar deshalb ALLE acht
  Felder `null` — `waypoints`, `progress_m`, `total_m`, `eta_game`,
  `eta_hhmm`, `eta_label`, `speed_m_s_real`, `pace_m_s_real`. Die Schlüssel
  bleiben stehen, damit
  „nicht mitgeteilt" von „leer" unterscheidbar ist. Es bleibt genau
  **`target_id`**, eine opake Id, die der Fog nie verborgen hat (wie
  `movement_target_id`, dessen NAMEN die Figurenliste sehr wohl
  zurückhält). Eine fremde Figur wird dann an ihrem `pos` gezeichnet, ohne
  Zwischen-Poll-Interpolation. `show_all=1` (Admin) liefert alles ungekürzt.

**Client-Erwartung**

1. Figur auf der Server-Position rendern (Formel oben), nicht auf dem
   Mittelpunkt von `location_id` und nicht auf `pos`, solange `travel` MIT
   `waypoints` da ist. Ohne `waypoints` (Fog, s. o.) bleibt `pos` die
   Position.
2. Zwischen zwei Polls darf extrapoliert werden, mit
   **`pace_m_s_real ?? speed_m_s_real`** (das Segment-Tempo zuerst, das
   nominale nur als Rückfall):
   `progress_m += Δt_real × tempo`, geklemmt auf `total_m`
   (sind beide `null`: einfrieren). Extrapoliert wird **`progress_m`** — der
   Punkt wird daraus jedes Frame neu abgelaufen, nie ein Segment einzeln
   hochgezählt (sonst bleibt die Figur an jedem Knick stehen, bis der
   nächste Poll kommt).
3. Beim nächsten Poll: Abweichung `|progress_m_client − progress_m_server|`
   > 1,0 m ⇒ hart auf den Server-Wert schnappen. Darunter weich nachziehen.
   Mit `pace_m_s_real` ist das der Ausnahmefall (Segmentwechsel zwischen
   zwei Polls); wer nur `speed_m_s_real` benutzt, schnappt auf Gelände mit
   `speed_factor ≠ 1` bei jedem Poll.
4. Blickrichtung/Clip bleiben Client-Sache (Laufrichtung aus dem aktuellen
   Segment); `activity_animation` wird bewusst NICHT auf „walk" gezwungen
   (§ A8).

**Ein Vokabular mit dem Spieler-Panel.** `GET /play/scene` trägt für den
Avatar denselben Block in Ein-Personen-Form: `target_id`, `eta_game`,
`eta_hhmm`, `eta_label`, `progress_m` und `total_m` bedeuten dort dasselbe —
`eta_game` also auch dort der kanonische Kalender-Stempel, die Anzeige
weiterhin aus den beiden gerenderten Feldern. Zusätzlich nur `target_name`
und `arrived`; die `waypoints` fehlen — das Panel zeichnet keine Karte.
`POST /play/travel` antwortet mit genau diesem Block unter `journey`.

**Verifikation** — numerisch nach dem Prinzip § B5a: der Verify-Modus difft
die Welt-Position der Figur gegen den aus `waypoints`/`progress_m`
abgelaufenen Routenpunkt (Toleranz ε = 0,01 Welt-Meter) und meldet
Objekt/Feld/Ist/Soll als Zahlen — keine Screenshot-Beurteilung. Der
Payload selbst ist handgerechnet abgesichert:
`scripts/smoke_worldmap_travel.py` (Polylinie 30 m + 40 m bei 1,0 m/s,
eingefrorene Uhr bei t = 35 s ⇒ `progress_m` 35,0 · `total_m` 70,0 ·
`speed_m_s_real` `null` · `pace_m_s_real` `null`; dieselbe Linie mit
80 s statt 40 s auf dem zweiten Schenkel ⇒ bei Faktor 2
`speed_m_s_real` 2,0 gegen `pace_m_s_real` 1,0 — die beiden Felder sind
messbar verschieden). Die **Ausdünnung** prüfen dieselbe Datei (Fall 6:
gefoggter Fremder ⇒ alle sechs Felder `null`, `target_id` bleibt) und
`scripts/smoke_fog_worldmap.py` (Fall 7: Reisender 100 m entfernt, also weit
außerhalb jeder Sichtweite, steht trotzdem mit `pos` im Payload).

**Konsumenten (Stand E5, 2026-08-12): beide migriert.** Die v1-Felder haben
damit KEINEN Leser mehr — weder `path` noch `progress_cells`.

* `client3d` — **erledigt (E4 Tasks 2 + 4).** `MapTravel` trägt v2
  (`waypoints`/`progress_m`/`total_m`/`eta_game`/`speed_m_s_real`/
  `pace_m_s_real`), der Zellen-Zweig samt `path`/`seg`/`frac`/
  `cell_seconds_real` und dem `Array.isArray`-Notbremsen-Guard ist
  **ersatzlos gelöscht**. Reisende werden entlang der Polylinie
  interpoliert (`client3d/src/scene/travelPath.ts`: Bogenlänge,
  Extrapolation mit `pace_m_s_real ?? speed_m_s_real`, doppelt geklemmt,
  Ankunfts-Snap ab 2 m) und werden dabei VOR der Ortsgruppierung
  eingesammelt — vorher fiel jeder Reisende mit leerer `location_id` aus
  dem NPC-Update und war für die ganze Reise unsichtbar.
* `frontend/src/player/MapPanel.tsx` — **erledigt (E5 Task 1).** Der
  Spieler-Panel ist als Schemakarte der Meter-Welt neu gebaut: Grundrisse in
  echter Größe, gemaltes Gelände, Figuren an ihrem `pos` — und die Reise als
  Linie. Der Typ kommt aus `frontend/src/tabs/map/mapTypes.ts`
  (`WorldmapTravel`, v2-Felder), die eigene v1-Deklaration mit
  `progress_cells`/`path` ist **ersatzlos gelöscht**. Gezeichnet wird der
  REST der Route: `waypoints` ab dem Fußpunkt zur gemeldeten Position
  (`nearestOnPolyline` in `mapMath.ts`, Fälle handgerechnet im Docstring) —
  keine zweite Bogenlängen-Rechnung neben `client3d/src/scene/travelPath.ts`,
  weil der Server die Position ohnehin liefert. Unter Fog hat nur der Avatar
  `waypoints`, alle anderen zeigen bloß ihren Punkt (§ A12). Mit demselben
  Umbau ist auch der letzte `grid_bounds`-Leser weg: der Kartenrahmen kommt
  aus `world_bounds`.

---

## A12. Fog of War im Worldmap-Payload — neu 2026-08-05

`GET /play/worldmap` liefert standardmäßig NICHT mehr die ganze Welt, sondern
nur, was der aktive Avatar kennt. Gebaut wird der Payload in EINER Funktion —
`app/core/world_ops.build_worldmap_payload(avatar_name, show_all)`; die Route
macht nur noch Auth, Parameter und 403.

**Sichtbarkeitsregel** — maßgeblich ist `location_visible_to_character`
(`app/models/world.py`): der Ort muss in den `known_locations` des Avatars
stehen (strict — leere Liste = nichts) und ein eventuelles
`knowledge_item_id` muss im Inventar liegen.

| Feld | Gefiltert? | Regel |
|---|---|---|
| `locations[]` | ja | **platzierte** Orte (beide `pos_x`/`pos_z` gesetzt) nur wenn sichtbar. Orte OHNE Meterposition passieren immer — sie stehen nicht auf der Karte und verraten nichts (Template-Stellvertreter) |
| `characters[]` | ja | der Avatar selbst immer; jeder andere nur, wenn seine `location_id` sichtbar ist. Unsichtbarer Ort ⇒ Figur fehlt komplett. **Wildnis** (`location_id: ""` mit `pos`): seit **E6** die Sichtweiten-Regel unten — nur wer nah genug am Avatar steht, ist da; Reisende bleiben (§ A11), solange ein Avatar aktiv ist. **Seit 2026-08-24 zusätzlich der DUNST-Filter** (`plan-fog-schleier-v2.md`, unten): wessen Punkt in einer vom Avatar **unerkundeten** 64-m-Zelle liegt, fehlt ebenfalls — Ausnahmen sind nur der Avatar selbst, wer im **selben Ort** wie der Avatar steht, und wer gar keinen Punkt hat. Diese Regel gilt auch für **Reisende**: eine Figur, die über gezeichneten Dunst läuft, darf nicht sichtbar sein |
| `characters[].movement_target_id` | nein | das Reiseziel bleibt — der Client zeichnet die Richtung |
| `characters[].movement_target_name` | ja | `""`, wenn das Ziel nicht sichtbar ist. Ohne diese Regel leckten Ortsnamen über die Figurenliste |
| `characters[].travel` | teilweise | der Block bleibt (die Figur ist ja sichtbar), aber bei **jedem außer dem Avatar** sind ALLE acht Zahlen/Listen `null`: `waypoints`, `progress_m`, `total_m`, `eta_game`, `eta_hhmm`, `eta_label`, `speed_m_s_real`, `pace_m_s_real`. Es bleibt `target_id` — opak, wie `movement_target_id`. Begründung und Feldliste: § A11 („Die ROUTE ist Avatar-Wissen — und ihre ZAHLEN auch") |
| `events_by_location` | ja | nur Schlüssel sichtbarer Orte |
| `world_bounds` | **nein** | siehe unten |
| `terrain_sig` | **nein** | Gelände wird nie gefoggt (§ A1.5) |
| `game_time` | **nein** | die Spieluhr sieht jeder — Tageszeit ist keine Ortskenntnis |
| `max_step_height_m`, `max_slope_deg` | **nein** | die zwei Lauf-Grenzwerte (§ A1.3, § A15 Nr. 9). Regeln sind keine Ortskenntnis — ein Grenzwert verrät nichts über die Welt |
| `avatar`, `current_location_id` | nein | der Avatar sieht sich selbst |

Unplatzierte Orte gelten dabei als **sichtbar** — sie passieren den Filter, und
damit werden auch die Charaktere und Events, die an ihnen hängen, mitgeliefert
(sie stehen auf keiner Karte und verraten keine Position).

**Sichtweite im Freien (E6).** Draußen gibt es keine Location, an der die
Sichtbarkeit hängen könnte — also entscheidet die **Entfernung**: ein
location-loser Charakter steht im gefoggten Payload genau dann, wenn
`hypot(avatar.pos − char.pos) <= game.discovery_range_m` ist. Das ist
bewusst DIESELBE Zahl, mit der man einen Ort durch Näherkommen entdeckt
(`app/core/discovery.py`, § A1.4) — eine einzige „wie weit sehe ich
draußen"-Einstellung, keine zweite daneben. Drei Fälle geben `false`:
Sichtweite `0` (= abgeschaltet), kein eigener Punkt des Avatars, kein Punkt
des anderen. Der Avatar selbst ist immer dabei, ein **Reisender** ebenfalls
(§ A11) — seine Zeile ist ausgedünnt, aber sie verschwindet nicht mitten auf
der Strecke. **Die Reisenden-Ausnahme gilt nur bei aktivem Avatar:** ohne
einen (eingeloggter Nutzer ohne übernommenen Charakter — die Route reicht
dann `""` durch) kennt die Sicht gar nichts, es passiert keine einzige
Location, und dann steht auch draußen niemand. `show_all=1` kennt die Regel
nicht.

**Zwei Radien, bewusst getrennt.** Draußen gelten zwei Einstellungen
nebeneinander: `game.hearing_radius_m` bestimmt, wen der Avatar HÖRT (die
Nachbarn im Szenen-Panel von `GET /play/scene`, § A1.4/E6), und
`game.discovery_range_m` bestimmt, wen und was er SIEHT (die Wildnis-Figuren
oben und das Entdecken von Orten). Sie dürfen auseinanderlaufen: in einer Welt
mit Hörweite > Sichtweite nennt das Szenen-Panel einen Nachbarn, den die Karte
nicht zeichnet — das ist so gewollt und kein Payload-Widerspruch.

**Gelände ist nie gefoggt.** `GET /play/terrain` kennt keinen Fog-Modus und
kein `all`-Flag: die gemalte Landschaft ist immer sichtbar, verdeckt wird nur,
was in ihr steht. Damit bleibt die Karte auch im Nebel eine Landschaft statt
einer leeren Fläche.

**Neue Wurzelfelder**

| Feld | Typ | Bedeutung |
|---|---|---|
| `world_bounds` | `{"min_x", "min_z", "max_x", "max_z"} \| null` | Ausdehnung der Welt in METERN über ALLE platzierten Orte UND alle gemalten Terrain-Flächen, **vor** dem Filter berechnet. `null`, wenn nichts platziert und nichts gemalt ist. Regel und Randfälle: § A1.3 |
| `fogged` | `bool` | `true` = gefilterte Sicht (`= not show_all`). Clients zeigen daran „hier ist noch Nebel" an, statt eine leere Karte zu vermuten |
| `explored_sig` | `string` | Signatur des **Erkundungs-Gedächtnisses** des Avatars (siehe unten). Ändert sie sich, holt der Client `GET /play/explored` neu. `""` ohne übernommenen Charakter |

### Der Schleier hat ein Gedächtnis — neu 2026-08-16

> **Stand seit 2026-08-24 (`plan-fog-schleier-v2.md`): der Schleier ist
> zurück — als DUNST, nicht als Decke.** Zwischen 2026-08-19 (v6 Nr. 8 /
> E1.3) und diesem Tag zeichnete der Client gar nichts; das Gedächtnis lief
> ohne Leser weiter, damit eine Welt, die in der Zwischenzeit gespielt wurde,
> ihre erkundeten Zellen nicht erst ab dem Tag der Neukonzeption kennt. Neu
> sind zwei Hälften, und die erste ist die tragende:
>
> 1. **Der Server filtert FIGUREN** (siehe Zeile `characters[]` oben): wer in
>    einer für den Avatar unerkundeten Zelle steht, verlässt den
>    Spieler-Payload. Der Dunst ist kein Vorhang, den ein Client wegziehen
>    könnte — was darunter liegt, verlässt den Server nicht.
> 2. **Der Client zeichnet Dunst** (`client3d/src/scene/fogVeil.ts`): ein
>    halbtransparenter Schleier über unerkundeten Zellen, dessen Deckkraft mit
>    der Kamerahöhe wächst (0 in Bodennähe, voll in der Übersicht). Die
>    Geländeform bleibt lesbar, Props und Bewuchs bleiben gezeichnet — nur die
>    Figuren fehlen, und die fehlen schon im Payload.
>
> Der v2-Dunst spart **nur die erkundeten Zellen** aus, nicht mehr zusätzlich
> die Grundflächen bekannter Orte: ein bekannter Ort steht mit seinem Gebäude
> und seiner Bodenplatte ohnehin sichtbar auf der Karte (die stehen ÜBER dem
> Gelände und tragen den Dunst nicht), und eine zweite Aussparungsregel wäre
> eine zweite Wahrheit darüber, was der Avatar gesehen hat.

Der **Übersichts-Schleier** (nur `client3d`, nur die Übersichts-Kamera; im
verkörperten Nahmodus gab es ohnehin nie einen Schleier) spart seit
2026-08-16 **zwei** Dinge aus: die Grundflächen der **bekannten Orte** — das
war er immer — **und** die **erkundeten Zellen**, also den Boden, auf dem der
Avatar schon gestanden hat. Vorher blieb ein Wald zwischen zwei Orten für
immer bedeckt, egal wie oft man hindurchging (Befund B14, Option 2).

Das **Gedächtnis ist Server-Wahrheit** (`app/core/exploration.py`, Tabelle
`explored_cells`), nicht Client-Zustand:

- **Raster:** Zellen von `EXPLORED_CELL_M` = **64 m**, **im Weltursprung
  verankert** — Zelle `(cx, cz)` deckt `[cx·64, (cx+1)·64)` auf beiden Achsen,
  `cx = floor(x / 64)`. Dieselbe Kantenlänge wie die Schleier-Kachelung
  (`FOG_TILE_M`) und derselbe Anker wie das Höhengitter (§ A16): eine Welt, die
  an ihrem Rand wächst, darf keine schon erkundete Zelle verschieben. Eine
  ausgesparte Zelle **ersetzt** damit genau eine Kachel, statt ein Loch in ein
  Quad schneiden zu müssen.
- **Markiert wird 3×3** um die Zelle der Position (Nahsicht, kein Fußabdruck),
  und zwar an genau den zwei Stellen, an denen ein Punkt geschrieben wird:
  bei einer **akzeptierten** `POST /play/pos`-Meldung (eine abgelehnte hat
  niemanden bewegt und merkt sich nichts) und im **Reise-Ticker**
  (`advance_all_journeys`) für jeden Charakter mit Punkt.
- **Rein additiv, pro Charakter.** Nichts löscht je eine Zelle, es gibt keine
  UI dafür, und das Gedächtnis eines NPC ist nicht das des Avatars.

**`GET /play/explored`** — Auth wie `/play/terrain` (jeder eingeloggte Nutzer,
kein `all`-Flag), aber strikt für den **eigenen** übernommenen Charakter; ohne
Avatar ist die Antwort leer, nie die eines anderen.

```json
{"cells": ["-1,0", "0,0", "0,1"], "sig": "3"}
```

`sig` ist die Zeilenzahl — weil die Tabelle nur wächst, ist sie eine
Revisionsnummer. Der Client holt den Payload **nur bei Signatur-Wechsel**
(Muster `height_sig`/`terrain_sig`), nie im 3-s-Poll: die Liste ist flach und
vollständig, und eine lange gespielte Welt kann Zehntausende Zellen haben
(60 000 Zellen = 245 km² erkundeter Boden ≈ 600 kB JSON). Das ist ein paar Mal
pro Sitzung bezahlbar und im Poll nicht.

**„Gelände ist nie gefoggt" bleibt** — der Schleier ist ein Übersichts-Effekt
über der Landschaft, kein Vorhang vor ihr. Das Gedächtnis nimmt ihm nur dort
Fläche weg, wo der Spieler ohnehin war; es verrät nichts Neues.

`world_bounds` ist bewusst UNGEFILTERT: Kartenrahmen, Zoom-Anschlag und
Mini-Map-Maßstab dürfen nicht springen, sobald der Avatar einen Ort entdeckt.
Die Ausdehnung verrät nur, wie groß die Welt ist — nicht, was in ihr steht.
Sie darf entartet sein (`min == max`), also nie ungeprüft als Divisor dienen.

**Admin-Override:** `GET /play/worldmap?all=1` liefert die ungefilterte Sicht
(`fogged: false`). Nur für Rolle `admin` — sonst **403**. Ohne aktiven Avatar
ist die gefilterte Sicht leer (nur die rasterlosen Einträge), nicht etwa voll.

**Spielmechanik, keine Sicherheitsgrenze.** Der Filter macht das Entdecken zum
Spielinhalt; er ist kein Mandantenschutz. Wer die Welt wirklich nicht sehen
soll, bekommt keinen Zugang — nicht bloß Nebel.

---

## A13. Die Grundfläche ist ein Raum — neu 2026-08-05

`plan-grundflaeche.md` §§ 3/6. **Den Zustand „in keinem Raum" gibt es nicht
mehr.** Jede Location trägt einen **reservierten Raum** mit fester Id
`__ground__` (`world.GROUND_ROOM_ID`) — die Fläche, die kein anderer Raum
einnimmt. Der Server bringt ihn mit (Einmal-Migration, danach
`ensure_ground_room` bei jedem Schreiben; Klone erben ihn von ihrer Vorlage);
der Autor legt ihn nie an und kann ihn nicht löschen, nur benennen.

- **Keine Geometrie.** Die Grundfläche trägt kein `layout` und damit kein
  Rezept (`compose_recipe` liefert ohne Layout `None`). Sie taucht in
  **keiner** Platte, keiner Wand und keinem `rooms[]`-Block des Szenen-
  Rezepts (§ B1) auf und wird nie als Fläche gezeichnet. Sichtbar ist sie
  als das, was ohnehin unter den Räumen liegt: **das Weltgelände selbst**,
  mit der Bodenart, die der Layer-Bake dort schneidet (§ A16.7). Bis v6
  Nr. 12 war das eine Etagenplatte, die nur mit einem Grundriss
  (`map3d.outline`) entstand; heute ist der Boden immer da — ohne Grundriss
  gibt es in der Detailszene keine
  Etagenplatte, und das Boden-Kind wird dort nirgends sichtbar.
- **Adressiert wird sie wie jeder Raum, über ihre Id.** `GET /play/scene`
  führt sie in `rooms[]` mit `is_ground: true`; **von dort holen Clients die
  Id** — die reservierte Konstante bleibt Server-Sache und wird in keinem
  Renderer nachgebaut. `POST /play/enter-room` bildet ein leeres `room_id`
  auf sie ab und schickt sie durch dieselbe Regel-Prüfung wie jeden anderen
  Raum: eine Block-Regel kann auch die Grundfläche sperren.
- **Name am Raum**, wie bei jedem anderen; ohne Namen greift überall dasselbe
  übersetzte Wort (`get_ground_name`). Das frühere Location-Feld
  `ground_name` ist ersatzlos weg.
- **Ankommen:** `entry_room` ist damit **optional** — gesetzt = man kommt
  dort an, leer = man kommt auf der Grundfläche an. Das entscheidet EINE
  Funktion für jeden Ankunftsweg (`world.get_arrival_room_id`: Avatar-
  Schritt, Reise, Scheduler, Bewegungs-Skills, Admin-Versetzung). Eine
  Boundary-Öffnung mit Raumverweis schlägt beides (§ B1 Nr. 13).
- **Hörweite gewöhnlich.** Wer auf der Grundfläche steht, ist in einem Raum
  wie jeder andere und hört nicht mehr in geschlossene Räume hinein — die
  sichtbarste Verhaltensänderung dieses Umbaus.
- **Für Renderer heißt das:** eine Figur, die in keinem Raum-Umriss liegt,
  steht auf der Grundfläche, nicht „nirgends". Die Raum-Heuristik hat damit
  ein gültiges Ziel statt eines Lochs (client3d, `groundRoomId` aus dem
  Payload) — vorher behielt sie den Raum der VORIGEN Location.

### A13a. Die Grundfläche trägt einen REDUZIERTEN Grundriss — neu 2026-08-20

Programm „Prop-Welt statt Dioramen", Etappe 2 Nr. 1. **Die Grundfläche bleibt
ohne Geometrie — aber nicht mehr ohne Inhalt.** Der Hof einer Location war
prop-frei, weil „kein Layout" bisher auch „keine Platzierungen" hieß; die
beiden Sätze sind ab hier getrennt. Der Raum `__ground__` DARF ein Layout
tragen, das AUSSCHLIESSLICH aus `props[]` und `markers[]` besteht (samt der
Streufelder einer Platzierung). Der Satz aus § A13 „die Grundfläche trägt kein
`layout`" ist genau in diesem Umfang überschrieben; alles andere dort bleibt
wörtlich gültig.

- **Der Rahmen ist die Location, nicht der Raum.** Die Grundfläche hat kein
  Rechteck und damit keine Minimal-Ecke, an der etwas hängen könnte:
  `props[].at` und `markers[].at` sind **lokale Meter der Location** —
  derselbe Rahmen, in dem `map3d.boundary` liegt (§ A1.1, Präambel v6 Nr. 2).
  Kein `x/y/w/d`, kein `outline`/`outline_curves`, keine `openings`, keine
  `surfaces`, kein `level`, kein `model_at`/`rotation`/`floor_offset_y` und
  keine Raum-Flags (`always_visible`, `no_walls`, `clip_model`).
- **Der Sanitizer wirft den Rest weg, nicht das Ganze**
  (`world_ops._sanitize_ground_layout`): ein für die Grundfläche gesendetes
  Geometriefeld wird verworfen und **protokolliert** (eine Zeile, die die
  Felder nennt) — die Platzierungen bleiben stehen. Sonst gelten dieselben
  Regeln wie für jeden Raum: Zentimeter-Rundung, ±500-m-Klemmung, ≤ 100
  manuelle Platzierungen, Σ `scatter_count` ≤ 120, ≤ 50 Marker. Ein Layout
  ohne Props UND ohne Marker ist kein Layout und wird entfernt.
- **Im Rezept bleibt sie geometrielos.** Die Grundfläche liefert weiterhin
  KEINE Platte, KEINE Wand, KEINEN `rooms[]`-Block (§ B1), keine Türschwelle
  und keinen Beitrag zu `outdoor_rooms`; ihr Rezept trägt `is_ground: true`
  und eine leere `outline`. Was sie liefert, sind Einträge in `models[]`
  (role `prop`) und in `markers[]` — wie bei jedem Raum, nur mit `at` =
  lokaler Meter **verbatim** (Ankerrahmen = Location, keine Minimal-Ecke
  addiert) und ohne Plattenaufschlag: `bottom_y` rechnet wie bei einem
  Außenraum ohne `ROOM_PLATE_TOP`.
- **Sie steht auf dem Gelände.** Wo eine Location ein Relief trägt, IST die
  Grundfläche das Gelände: sie zählt zu den `relief_rooms`, ihre Props und
  Marker werden am eigenen Anker angehoben (derselbe `lift`-Sampler wie bei
  einem Außenraum), und sie flacht das Höhenfeld nirgends ab — sie steuert
  keinen flachen Hull bei.
- **Streuung hält die Boundary ein.** Keep-in ist das Boundary-Polygon der
  Location (konkav zugelassen; ohne gezeichnete Boundary keine Fläche und
  damit keine Streuung), Keep-out sind die Hüllen der Räume auf Ebene 0, die
  Eintrittszonen der `boundary_openings` und die eigenen Marker — dieselbe
  Mechanik wie im Raum, nur ein anderer Rahmen.
- **Spielmechanik unverändert.** Anstand, Regeln, Hörweite, Ankommen und
  Benennung der Grundfläche berührt das alles nicht: sie bleibt der Raum aus
  § A13.
- **Editor:** der Grundriss-Editor bietet die Grundfläche als eigenes Planziel
  an („Yard"); sichtbar ist die Boundary als ihre Fläche, bedienbar sind
  Prop-, Marker- und Streuwerkzeuge — Raumgeometrie (verschieben, skalieren,
  drehen, Umriss, Öffnungen, Oberflächen, Raummodell) ist dort abgeschaltet.
- **Möblieren:** ein Furnish-Auftrag darf die Grundfläche als Ziel haben; der
  Solver rechnet dort in lokalen Metern der Location über dem
  Boundary-Polygon, mit den Eintrittszonen der Boundary-Öffnungen als
  Sperrzonen. **Adressiert wird so ein Auftrag über eine zusammengesetzte
  Id** — `__ground__@<location_id>` —, denn die reservierte Raum-Id ist die
  einzige, die nicht welteindeutig ist; aus demselben Grund weist
  `GET /play/rooms/__ground__/recipe` mit 400 ab: den Hof liefert
  `GET /play/locations/{id}/scene`.

---

## A14. Der Sperr-Zustand kommt vom Server — neu 2026-08-06

`plan-betreten-und-tueren.md` § 5. **Der Server sagt WAS gesperrt ist, der
Client sagt WIE es aussieht.** Beide Spieler-Payloads tragen den Zustand
fertig, samt der Begründung in der Sprache des Spielers; kein Renderer leitet
je eine Sperre selbst ab.

- **`GET /play/scene` → `rooms[]`** (der Spieler-Payload, § A13) — jeder
  Eintrag `{id, name, is_entry, is_ground, enterable, reason}`. `enterable`
  kommt aus demselben `check_access`, mit dem `POST /play/enter-room`
  ablehnt (`world_ops.build_avatar_rooms`), also können angebotener und
  akzeptierter Raum nicht auseinanderlaufen; `reason` ist der Satz der Regel
  und leer genau dann, wenn der Raum offen ist.
- **`POST /play/pos` → Absage-Payload** — die Reihenfolge der Gates ist die
  Begründung, die der Spieler liest: EXIT (`may_leave` + `check_leave`) vor
  ENTRY (Öffnungs-Nähe, `accessible_when`, `check_access`), erste Absage
  gewinnt. Die Kette steht ausgeschrieben in **§ A15**. (Der frühere
  Himmelsrichtungs-Kompass `GET /world/avatar/neighbors` ist mit dem
  Kachel-Schritt zusammen gestrichen — auf einer Meter-Karte gibt es keine
  vier Pfeile mehr, die man vorab beurteilen könnte.)
- **Trennlinie:** der Sperr-Zustand gehört EINEM Avatar in EINEM Moment und
  steht deshalb **niemals** im signatur-gecachten Szenen-Rezept (§ B1) — das
  ist für alle dieselbe Geometrie. Clients binden ihn zur Render-/
  Interaktionszeit **über die Id**.
- **Was die Renderer daraus machen** (reiner Sicht-Zustand, bewusst nicht
  geteilt): client3d zeichnet eine Türschwelle verschlossen, wenn ein Raum
  auf der ANDEREN Seite gesperrt ist — die Zuordnung läuft über
  `doorways[].rooms`, und der Raum, in dem der Avatar gerade steht, ist von
  der Beurteilung ausgenommen (eine Regel gegen das Betreten sagt nichts über
  das Verlassen, sonst wirkte jeder eigene Raum als Käfig). Die
  Raumwechsel-Heuristik schlägt gesperrte Räume nicht vor (der eigene bleibt
  Kandidat, sonst liefe die Figur im Stehen hinaus), und das
  „Betreten"-Angebot nennt beim gesperrten Ziel den Server-Satz, statt zu
  schweigen.

---

## A15. Freies Laufen — `POST /play/pos` — neu 2026-08-09 (E4)

**Die Meter-Welt hat keine Zellen, also auch keinen Kompass-Schritt.** Der
Client läuft die Figur selbst und **meldet**, wo sie steht; der Server fragt
nicht mehr pro Kante um Erlaubnis, sondern **beurteilt einen gemeldeten
Punkt**. `POST /world/avatar/step` ist mit E3 gelöscht und hat hier keinen
Nachfolger pro Richtung.

**Request** `{"x": <Meter>, "z": <Meter>, "seq": <Zähler>, "t_ms": <ms>}` ·
**Antwort** `{ok: true, pos: {x, z}, location_id, room_id}`.

**Meldefrequenz:** ~3/s während der Bewegung plus einmal beim Anhalten.
Server-Drossel ~4/s.

**`seq` + `t_ms` — das Reihenfolge-Paar (2026-08-23, optional).** `seq` ist
ein Zähler, den der Client pro Meldung SEINER Sitzung hochzählt, `t_ms` seine
eigene Dauer-Uhr (`performance.now()`) im Moment der Messung. Beide existieren
für EINEN Fehlerfall: eine **blockierte Event-Loop**. Der Client hat pro
Meldung eine Frist (8 s), bricht danach ab und läuft weiter — der Request
läuft auf dem Server aber weiter und wird Sekunden später doch verarbeitet.
Ohne das Paar wird dieser Nachzügler als neuester Punkt akzeptiert, die
Basislinie des Servers fällt hinter die Figur zurück, die nächste ehrliche
Meldung gilt als 12-Meter-Satz „in 0,4 s" und wird abgelehnt — der Spieler
wird beim Geradeauslaufen immer wieder zurückgerissen. Mit dem Paar gilt:

* eine Meldung, deren `seq` **nicht neuer** ist als die der letzten
  AKZEPTIERTEN, wird STILL verworfen (200 `{ok: false, stale: true}`) — nichts
  wird geschrieben, **keine Korrektur** gesendet; der Client behandelt sie wie
  `throttled` (Punkt bleibt ungemeldet und wird erneut gesendet). Die
  Basislinie verfällt nach 10 s Serverzeit bzw. sobald die Client-Uhr mehr als
  15 s zurückfällt, damit ein **Reload** (Zähler startet wieder bei 1) sich von
  selbst fängt;
* die Schrittweite (Nr. 5) misst über `t_ms − letztes t_ms` — die Zeit, die
  wirklich beim LAUFEN verging — statt über den Abstand zweier Handler-Läufe,
  den ein Stillstand auf null zusammendrückt. Geklemmt nach unten auf das
  Drossel-Intervall, nach oben auf 30 s (eine Client-Uhr ist keine
  vertrauenswürdige Uhr).

Ein Client, der die beiden Felder **nicht** schickt, wird exakt wie bisher
beurteilt (Serverzeit als Maß, keine Reihenfolge-Prüfung).

**Die Gate-Kette, in genau dieser Reihenfolge** (jede Absage trägt
`{reason, message, pos, location_id}`, wobei `pos` der LETZTE GÜLTIGE Punkt
ist — der Client snappt die Figur darauf zurück, damit die beiden Sichten nie
auseinanderstehen):

| # | Prüfung | Absage |
|---|---|---|
| 0 | **Überholt** — eine andere Meldung DESSELBEN Avatars steckt schon im Handler. Der Server wartet nie darauf (das würde pro Meldung einen Threadpool-Worker parken und der Punkt wäre bis dahin ohnehin alt); STILL verworfen wie die Drossel, die nächste Meldung ≤ 250 ms später trägt einen frischeren Punkt | 200 `{ok: false, superseded: true}` |
| 1 | Party-**Follower** besitzt keine eigene Bewegung | 403 `party_follower` |
| 2 | `x`/`z` sind endliche Zahlen | 400 |
| 3 | **Nachzügler** — `seq` nicht neuer als die letzte akzeptierte Meldung; STILL verworfen, kein Fehler-Toast, keine Korrektur | 200 `{ok: false, stale: true}` |
| 4 | **Drossel** ~4 Meldungen/s — Überschuss wird STILL verworfen, kein Fehler-Toast | 200 `{ok: false, throttled: true}` |
| 5 | **Schrittweite** gegen die vergangene Zeit seit der letzten AKZEPTIERTEN Meldung (Client-`t_ms`, sonst Serverzeit) | 409 `too_far` |
| 6 | **Location des Punktes** ableiten (`location_at_point`) — entscheidet Nr. 7 | — |
| 7 | Gelände `passability_at` am Punkt (§ A1.5) — **nur in der WILDNIS** (`location_id == ""`); NUR die Passierbarkeit, das Tempo wird hier nie geprüft | 409 `impassable` |
| 8 | **Location-Übergang** — EXIT vor ENTRY | 403 (siehe unten) |
| 9 | **Höhe** des Punktes gegen den letzten gültigen — nur BERGAUF (Steigung immer, Stufe zusätzlich unter 1 m; ein Abstieg geht seit 2026-08-28 immer durch — siehe unten) | 409 `too_steep` |

**Die Erlaubnis in Nr. 5 hat DREI Terme**, und der dritte ist keine
Verzierung:

```
allowance = max( 5 m,
                 3 × travel_speed_m_s × Zeitfaktor × elapsed,
                 3 × 3,4 m/s × elapsed )
```

Boden, **Spieluhr-Term** und **Echtzeit-Term**. Freies Laufen hängt nicht an
der Spieluhr: in einer eingefrorenen Welt (Faktor 0) oder einer langsamen
kollabiert der mittlere Term, während der Spieler weiter 3,4 m pro echter
Sekunde läuft — ohne den dritten Term sammelte ein ehrlicher Läufer dort
409er. Das Ganze ist eine **Anti-Teleport-Schranke, kein Präzisions-
Anticheat**; ohne Basislinie (frische Sitzung, Übernahme, Admin-Move) wird
der erste Punkt ungeprüft genommen.

**FOOTPRINT GEWINNT — FÜR DIE PASSIERBARKEIT (Nr. 6 vor Nr. 7, Entscheidung
2026-08-13, präzisiert durch Befund 3).** Gemaltes Gelände beurteilt, wo man
STEHEN darf, zwischen den Orten. Liegt der gemeldete Punkt in
IRGENDEINEM platzierten Fußabdruck (eigener wie fremder), entfällt der
Gelände-Check ganz — eine Location wird AUF die Welt gesetzt und erbt nicht
den Boden, den jemand darunter gemalt hat. Sonst wäre eine Halle auf einem
Felsplateau oder ein Dorf auf einer Insel im See ein Ort, in dem man keinen
Schritt tun kann und jede Meldung eine Absage bekommt (Abnahme-Befund B1);
das Tor eines Ortes sind seine Öffnungen und Regeln (Nr. 8), nie der Fels
darunter. Das ist zugleich die **Voraussetzung für das E8-Plateau**: dort
wird die Heightmap unter dem Fußabdruck planiert (sofern der Ort es
verlangt, § A16.4), und der Fels unter dieser Planierung darf die geebnete
Fläche nicht weiter sperren. Diese Passierbarkeits-Regel hängt NICHT am
`draws_built_floor` — sie gilt für jeden Fußabdruck.

Dieselbe Regel gilt im **NPC-Routing** (`nav_grid`): eine Zelle stirbt am
fremden Fußabdruck (SAT) oder am Gelände in ihrer Mitte — Letzteres nur
außerhalb jedes Fußabdrucks. Ohne das wäre ein Ort auf Fels für die Reise
unerreichbar, während sein Avatar darin frei umherläuft. Am GELÄNDE stirbt
sie drinnen also nie; an der STEILHEIT dagegen schon, wenn der Ort nicht
planiert (§ A16.4) — die beiden Ausnahmen sind zwei Regeln, und nur die
zweite fragt `draws_built_floor`.

**TEMPO UND ANIMATION GEHÖREN DAGEGEN DEM OBERSTEN GELÄNDE, SO WEIT WIE DER
HIMMEL REICHT** (Befund 3 der E8-Sichtabnahme, 2026-08-13; Reichweite in
Runde 2 entschieden). Der Fußabdruck nimmt dem Boden das VERBOT, nicht seine
Beschaffenheit — aber nur dort, wo der Ort selbst offener Grund ist: ein Dorf
auf einem See wird durchwatet und mit `move_anim` „swim" auch so animiert,
eine Halle auf demselben See nicht. Die volle Reichweiten-Tabelle (Raum →
Fußabdruck → Wildnis) steht in § A1.5; neutral heißt dort immer Tempo 1,0 UND
keiner der beiden Boden-Clips (`move_anim` im Gehen, `idle_anim` im Stehen).
Server und Client tragen beide Regeln je einmal
(`terrain_query.ground_scope`/`effective_speed_factor` bzw.
`game/walk.groundScope`/`terrainPace`/`moveClip`/`idleClip`); die Reisezeit
(`segment_costs` → Reise-Engine) und der Schritt des Avatars erben sie
automatisch. **Die Gate-Kette oben ändert sich dadurch NICHT** — das Tempo
ist keine Erlaubnis, es wird nirgends geprüft, es wird gelaufen.

**Der Übergang (Nr. 8).** Gleiche Location oder Wildnis → Wildnis ist frei.
Sonst:

* **EXIT** — `boundary_entry.may_leave` mit dem Raum, in dem der Avatar
  steht: über eine NAHE Öffnung aus dem Raum, den sie verlinkt, aus dem
  `entry_room` über jede Kante, oder frei, wenn die Location gar keinen
  Eintrittsraum deklariert. **UND** `rules.check_leave` — die Regel-Hälfte,
  die jeder andere Bewegungspfad fragt (`/play/travel`, der Reise-Ticker, der
  SetLocation-Skill, der Scheduler). Geometrie allein ist nicht das Tor:
  eine `confine`- oder Gefahr-Regel muss auch gegen die FÜSSE halten, sonst
  hebt der Bewegungskanal still auf, was `/play/notices` dem Spieler im
  selben Moment sagt.
* **ENTRY** — der Punkt muss innerhalb **1,5 m** eines Öffnungs-Weltpunkts
  des Ziels liegen (§ A1.1 / § B1 Nr. 13), und `accessible_when` +
  Zugangsregeln (`check_access`) müssen passen. Das sind exakt die Gates, die
  `/play/travel` vor dem Losgehen anlegt; ein Läufer, der daran vorbeispazieren
  könnte, machte jedes davon zur Dekoration (E3-C1).
* **FREIE GRENZE (Entscheidung E4 Task 5).** Eine Location **ohne jede
  autorisierte Öffnung** hat eine freie Grenze: sie hat nie gesagt, wo ihr Weg
  hinein ist — das Spiegelbild von `may_leave`s „kein Eintrittsraum = überall
  hinaus". Ohne diese Regel wäre ein gemalter Platz, eine Wiese oder jeder
  `passable` Transitort eine Wand, und man KANN um sie herum nicht für jede
  Anlaufrichtung eine Öffnung zeichnen. **Hat** eine Location Öffnungen, sind
  genau die ihre Wege hinein und alles andere ist Wand (Strenge-Entscheidung
  2026-08-04). Die Regel-Gates gelten in beiden Fällen — die freie Grenze
  nimmt die GEOMETRISCHE Hälfte des Tors weg, nie die Regeln.
* **Location → Location** (angrenzende oder **verschachtelte** Fußabdrücke —
  eine Hütte auf einem Dorfplatz) ist beides: EXIT der alten, dann ENTRY der
  neuen.

**DAS HÖHEN-GATE (Nr. 9) — neu 2026-08-13 (E8 Task 1).** Bis hierher hat in
dieser Welt keine einzige REGEL nach einer Höhe gefragt: das Szenen-Payload hob
Props, die Renderer drapierten den Boden, und eine Felswand ließ sich so leicht
hochlaufen wie eine Wiese. Jetzt vergleicht der Server den Boden unter dem
letzten gültigen Punkt mit dem Boden unter dem gemeldeten:

```
Δh = lift(neuer Punkt) − lift(letzter Punkt)
Δh <= 0     ->  frei (ein ABSTIEG wird nicht beurteilt)
sonst       ->  STEIGUNG:  atan(Δh / dist) > game.max_slope_deg   (Default 40°)
dist < 1 m  ->  UND STUFE: Δh > game.max_step_height_m            (Default 0,4 m)
```

**Zwei Grenzwerte statt einem**, weil eine 1-m-Mauer und 1 m Anstieg über 20 m
nicht dasselbe Hindernis sind: das erste klettert niemand, das zweite ist ein
sanfter Hügel. Die Ein-Meter-Marke ist die Länge einer Meldung selbst (~3/s bei
3,4 m/s), also genau die Strecke, über der ein Anstieg etwas ist, das man
hinaufgeht statt hinaufklettert.

**Und sie gelten ZUSAMMEN, nicht entweder/oder** (Review 2026-08-13). Die
Entweder-Oder-Form — Stufe unter einem Meter, Steigung darüber — war aus zwei
Gründen falsch. Erstens messen die beiden Seiten des Spiegels über
VERSCHIEDENE Längen: der Client prüft einen Lauf-Vorgriff von ~0,15 m, der
Server einen Melde-Schritt von ~1,12 m. Das ganze Band zwischen
`max_slope_deg` und dem Winkel, den dieselbe Höhe über einen Vorgriff macht
(bei den Defaults 40° bis 69°), war damit für den Client unsichtbar und für
den Server eine Absage — die Figur lief weiter, während der Server sie 3×/s
zurückschnappte. Zweitens machte die Entweder-Oder-Form jede Steigung durch
LANGSAMES Gehen erkletterbar: 0,1 m pro Meldung verwandelt eine 76°-Wand in
lauter legale „Stufen". Ein Grenzwert, den man durch Geduld umgeht, ist keiner.

**Die Richtung zählt (User-Regel, 2026-08-28)**: das Gate verweigert NUR das
KLETTERN, ein Abstieg geht immer durch — Δh ist vorzeichenbehaftet, und bei
`Δh <= 0` fragt die Regel gar nicht erst nach Stufe oder Winkel. Bergab zu
gehen ist das, was ein Körper ungefragt tut; es zu verweigern liest sich als
Welt, die die Figur grundlos festhält. Der Preis ist benannt und akzeptiert:
man kann irgendwo hinuntersteigen, wo man nicht mehr hochkommt, und dort
stranden — bis 2026-08-28 war genau die Symmetrie des Gates das, was das
verhindert hat.

**Woher die Höhe kommt: EINE Quelle, EINE Antwort**
(`app/core/relief.ground_at` → `world_geometry.ground_y` →
`heightfield.world_height`). Das ist `h_final` (§ A16.1), bilinear aus der
2-m-Kachel gelesen; es gilt drinnen wie draußen. Unter einem GEBAUTEN Ort
(`draws_built_floor`, § A16.4) ist das Feld durch den Plateau-Stempel eben,
unter jedem anderen läuft die Landschaft einfach durch. In einer Welt, in der
niemand etwas modelliert hat, ist es 0 und das Gate vollständig inert.

> **Die ZWEITE Quelle ist gelöscht** (v6 Nr. 12): das szenen-eigene
> 17 × 17-Relief samt `relief.ground_lift_at` / `scene_ground_lift`, dem
> `terrain`-Block im Szenen-Payload und der Auflösungsregel „die innerste
> ENTHALTENDE Location MIT Relief gewinnt". Es gibt EIN Feld; lokales Relief
> autoriert man als Höhenfläche der Karte.

Der Client spiegelt dieselbe Zahl (`main.ts reliefLiftAt` →
`terrainGround.heightAt`): die BILINEARE Lesung des Feldes, denn dieser
Spiegel sagt die Server-Antwort voraus und der Server liest das Feld. Ein
Modell-Raycast kommt dabei nirgends mehr vor — er kannte eine
Mesh-Oberfläche, die der Server nicht kennt, und die beiden Sichten müssen
sich einig bleiben. (Bis E8 Task 4 fehlte dem Spiegel der Welt-Term — das war
das Gummiband auf jedem Welt-Hügel: der Client lief die Figur hoch, der Server
holte sie 3×/s zurück.)

**Seit v6 fragt Nr. 8 die STANDHÖHE, nicht die Geländehöhe**
(`model_surface.stand_height_at`, Nachtrag „Oberflächen-Raster" 2026-08-27):
`max(ground_at(x, z), höchstes antwortendes Oberflächen-Raster der Location)` —
mit derselben Sample-Formel, die beide Renderer benutzen, und nur mit Rastern
auf Etage 0, genau wie die Boden-Leiter des Clients. Der Modell-Raycast bleibt
gelöscht: der Server kennt die Mesh-Oberfläche jetzt als DATEN, die Blender
einmal gebacken hat, und beide Sichten bleiben sich einig, weil sie dieselben
Zahlen lesen. Δh misst damit zwischen zwei Standhöhen, jede an SEINER Location
(`location_at_point` für den Vorpunkt). Eine Location ohne Szene, ein Punkt
ohne Raster oder ein defekter Sidecar lassen es beim nackten Gelände — das Tor
ist eine Plausibilitätsprüfung und nie der Grund, warum jemand nicht laufen
kann. Praktisch heißt das: eine 0,3-m-Kiste ist eine Stufe, ein 0,8-m-Block
eine Wand, und zwar auf beiden Seiten der Leitung.

**Dieselbe Regel im NPC-Routing** (`nav_grid`, E8 Task 4). Eine Zelle ist
blockiert, wenn der Boden AN IHRER MITTE steiler steht als `max_slope_deg` —
gemessen als ZENTRALE Differenz über die je zwei Gegennachbarn
(`rise = hypot(h(x+c,z)−h(x−c,z), h(x,z+c)−h(x,z−c))`, `run = 2 · NAV_CELL_M`).
Dieser `rise` ist ein BETRAG und damit nie negativ, die Kletter-Regel von
2026-08-28 ändert hier also nichts: eine Zelle hat keine Richtung, sie ist
steil oder nicht. Zentral und nicht einseitig: der flache Boden am FUSS einer Klippe erbte sonst
deren Steilheit, und das Ufer jedes Sees wäre unbegehbar. Ausgenommen sind
Zellen INNERHALB eines **GEBAUTEN** Fußabdrucks (Footprint gewinnt; nur DORT
ist das Feld planiert — `draws_built_floor`, § A16.4, und unter einem
natürlichen Ort läuft die autorierte Landschaft durch, die dann genauso
beurteilt wird wie der Boden draußen) und Zellen an einer Öffnung
(`OPENING_EXEMPT_M` = 1,5 m Toleranz + eine Zelle) — dieselbe
Rampenenden-Ausnahme wie unten. Die PASSIERBARKEITS-Ausnahme („Footprint
gewinnt" bei gemaltem Untergrund) fragt gar nichts: sie gilt für jeden
Fußabdruck, gebaut oder nicht. Dazu kostet
jeder Höhenmeter `SLOPE_COST_S_PER_M` = 4 Spielsekunden extra, als STRAFE und
nie als Bonus (die A*-Heuristik kennt kein Relief; ein Bonus machte sie
unzulässig). Die Strafe steckt auch in `segment_costs` — die Reisezeit erbt den
Berg — und in der Kosten-Prüfung der Linien-Glättung, die den Umweg um einen
Hang sonst wieder wegzöge; die Sichtlinie lehnt zusätzlich jede Abkürzung über
eine zu steile Zelle ab. Der Routing-Cache hält Öffnungen und beide
Grenzwerte, also stehen sie in seinem Schlüssel: eine neu autorierte Öffnung
ändert weder Gelände noch Höhenfläche noch Platzierung, und ein Admin-Regler
ändert gar nichts an der Welt — beides muss den Router trotzdem neu bauen,
sonst urteilt er nach der Tür und der Grenze von gestern.

**~~Verschachtelung: der INNERSTE UMSCHLIESSENDE Ort MIT Relief gewinnt~~ —
GEGENSTANDSLOS seit v6 Nr. 12.** Die Regel löste auf, welches von mehreren
szenen-eigenen Reliefs an einem Punkt gilt. Es gibt kein szenen-eigenes Relief
mehr und damit keine Auflösung: EIN Feld, und wer es formt, entscheidet der
Bake einmal (`draws_built_floor`, § A16.4). Verschachtelte Orte staffeln sich
über ihre Plateaus — die kleinste Fläche schreibt zuletzt und gewinnt, dieselbe
Ordnung wie bei `location_at_point`.

**Nr. 8 steht NACH dem Übergang (Nr. 7)**, weil die Höhe eines Punktes davon
abhängt, welche Location ihn besitzt — und weil ein Eintritt, den die Geometrie
erlaubt, nicht mit „zu steil" beantwortet werden darf, wenn in Wahrheit eine
Regel greift.

**ÖFFNUNGEN SIND RAMPENENDEN.** Eine autorisierte Öffnung liegt auf der Kante
eines Ortes — also genau dort, wo der Boden auf sein Plateau steigt —, und eine
Öffnung IST per Definition der Weg hinein. Jeder Punkt innerhalb der
Übergangs-Toleranz von 1,5 m (`_POS_OPENING_TOLERANCE_M`) einer Öffnung der
abgeleiteten ODER der aktuellen Location ist deshalb von Nr. 8 ausgenommen, und
zwar an BEIDEN Enden des Schritts (eine Überquerung hat einen Fuß auf jeder
Seite). Ohne die Ausnahme wäre ein Ort auf eigenem Plateau hinter seiner
eigenen Tür verschlossen.

An einem PLANIERENDEN Ort (§ A16.4) ist am Weltrelief ohnehin nichts zu
überqueren: der gepinnte Ring reicht eine Zelle ÜBER den Fußabdruck hinaus,
die Öffnung liegt also auf ebenem Grund. Die Ausnahme trägt den Fall, für den sie
da ist: an einem NATÜRLICHEN Ort steigt der autorierte Hang durch die
Türschwelle, weil dort nichts gestanzt wird. Dazu den Rest-Rand eines
gebauten Ortes an einer sehr steilen Flanke — die Rampe erreicht dort bis zu
46,4° (die 1,5-fache Spitze des `smoothstep`, § A16.4). Bis zur Plateau-Rampe eine Zelle
weiter draußen reicht sie bewusst nicht: das ist die Autorierungs-Grenze aus
§ A16.4, kein Loch in der Regel.

**Die Meldung nennt das Hindernis** (Lektion aus Befund B1): eine Stufe und
eine Steigung bekommen zwei verschiedene Sätze, und die Absage wird geloggt wie
jeder andere Grund hier. **Ohne Vorpunkt** (frische Sitzung, Übernahme,
Admin-Move) gibt es nichts zu vergleichen und Nr. 8 entfällt — dieselbe Regel
wie bei der Schrittschranke. In einer Welt ganz ohne Relief ist Δh immer 0 und
das Gate damit vollständig inert.

**Nur der gemeldete PUNKT wird beurteilt, nie der Weg dorthin.** Das ist
Absicht: bei ~3 Meldungen/s liegt gut ein Meter dazwischen, was nichts
überspringen kann, was die Welt hat — und den Pfad serverseitig zu
rekonstruieren wäre ein ZWEITES Bewegungsmodell neben dem, das der Client
läuft, also genau das Modell, das dann mit dem Bild streitet. Die
Schrittschranke (Nr. 4) hält die Lücke klein genug, damit das trägt.

**Nebenwirkungen einer akzeptierten Meldung:** eine laufende Reise wird
**abgebrochen** (freies Laufen überschreibt Reisen bewusst — sonst zöge der
Reise-Ticker die Figur beim nächsten Tick auf ihre gebackene Polylinie
zurück), und ein **schlafender Avatar wacht auf** (dieselbe Regel wie bei
`/play/enter-room` und `/play/travel`; sie steht NACH den Gates, denn eine
abgelehnte Meldung hat niemanden bewegt).

**Was der CLIENT dazu tut** (reiner Sicht-/Eingabe-Zustand, nicht Vertrag):
er hält die Figur selbst aus unpassierbarem Gelände (nach derselben Regel:
nur außerhalb der Fußabdrücke — `walk.terrainBlocks`) und aus fremden
Fußabdrücken (`walk.slideBlocked`, Gleiten statt Anhalten), bietet den
Eintritt ab 3 m an
einer Öffnung an und läuft dann auf den Öffnungspunkt zu, und beantwortet ein
4xx mit Gleiten (≤ 8 m) oder Sprung auf den zurückgegebenen Punkt plus einem
Toast pro Grund. **Kein Client-A\*** — Klick-Laufen ist Luftlinie mit
Wandgleiten (E5+, falls mehr gebraucht wird).

**Unter dem Schleier ist der Client STRENGER als der Server, und das ist
hinnehmbar:** ein unentdeckter Ort steht nicht im Weltkarten-Payload, hat
also keine Kachel — `tileAt` antwortet dort nichts, und gemalter Fels unter
diesem Fußabdruck hält die Figur weiter auf, obwohl der Server den Punkt
annähme. Es korrigiert sich beim Entdecken von selbst (die Zeile kommt, die
Kachel entsteht), und die Gegenrichtung wäre ein Leak: eine begehbare Insel
im Fels verriete genau den Ort, den der Schleier verbirgt.

**Verifikation:** `scripts/smoke_play_pos.py` ruft die Handler-Funktion
direkt (ohne Server) gegen eine Wegwerf-Welt und rechnet alle 20 Fälle von
Hand vor — Öffnungspunkte, Schrittschranke (inkl. Echtzeit-Term bei
eingefrorener Uhr, Fall [19]), Gelände und jeden Ast der Übergangs-Gates
inklusive verschachtelter Fußabdrücke ([16]), `check_leave` ([17]) und
Aufwachen ([18]). Fall [20] ist „Footprint gewinnt" mit Gegenprobe: derselbe
Fels-Punkt wird INNERHALB der Location angenommen und, nachdem die Location
gelöscht ist, als `impassable` abgelehnt. Die Routing-Hälfte steht in
`scripts/smoke_nav_grid.py` [12].

---

## A16. Ein Boden — Höhe, Material und Wasser der offenen Welt

*Neu geschrieben 2026-08-21 (Etappe E6 aus `development_instructions/`
`plan-ein-boden.md`). Dieses Kapitel ERSETZT das alte § A16 („Das Weltrelief"
samt § A16.1 Planierung, § A16.2 Mikro-Relief, § A16.3 Kachel-Höhenfeld), die
drei § B1-Nachträge vom 2026-08-20 („EIN Boden" / „EIN Datum" / „die Natur
zeichnet KEINE Platte") und die fünf Etappen-Nachträge E1/E3/E4/E5a/E5b. Wo
irgendwo sonst im Dokument eine Etage-0-Platte, ein Kachel-Sockel, ein
`level_ground`-Flag, ein Szenen-Relief oder eine gedrapte Bodenfläche steht,
gilt dieses Kapitel.*

**DAS GESETZ, in drei Sätzen.** Es gibt genau EINEN Boden: die Höhenfunktion
`h_final(x, z)`, serverseitig gebacken, von jedem Verbraucher aus denselben
Daten gelesen. Sein MATERIAL ist genau EIN Schnitt: pro Stelle gewinnt ein
Layer, und die Übergangsbreite ist eine Eigenschaft dieses Layers. Die einzige
ebene Sonderfläche ist WASSER, und ihre Höhe ist eine Zahl in den Daten
(`water_level_effective`), keine Schätzung eines Renderers.

Daraus folgt alles Übrige: **kein Renderer misst Dreiecke, um zu erfahren, wie
hoch der Boden ist**, es gibt auf Etage 0 keine Bodenplatte im Szenen-Payload
mehr, und Render-LOD ist reine Sampling-Dichte — nie ein Datenwechsel.

---

### A16.1 `h_final(x, z)` — eine reine Funktion, fünf Backstufen

`app/core/heightfield.HeightModel` hält die ganze autorierte Welt und
beantwortet `final(x, z)` für jeden reellen Punkt. **Jede Rasterung in diesem
Modul — die Übersicht, eine Kachel, jede Mip-Ebene — ist nichts als diese
Funktion auf einem Gitter abgetastet.** Reihenfolge, jede Stufe wegen der
vorigen:

```
1. Höhenflächen          (stärkste Auslenkung gewinnt)
2. Mikro-Relief          (ADDITIV)
3. Wasser-Carve (Karte)  (min, senkt nur, gegen das LOKALE Niveau — W1)
4. Location-Plateaus     (smoothstep-Rampe, kleinste Fläche zuletzt)
~~5. Zonen-Wasser-Carve~~  GELÖSCHT (W1, 2026-08-21)
```

Stufe 5 steht ausdrücklich hinter Stufe 4: ein Teich im Innenhof liegt auf
einem Grundstück, das der Plateau-Stempel eben hobelt — vor dem Stempel
gecarvt wäre er wieder weggehobelt.

> **INVARIANTE 1 — Reinheit über alle Gitter.** Zwei Gitter über demselben
> Modell tragen an jedem gemeinsamen Punkt dieselbe Zahl — **by construction,
> nicht by agreement.** Kein Schritt der Pipeline misst „eine Rasterzelle";
> alle Breiten sind METER. (Vorher taten es zwei: die Kantenregel des
> Mikro-Reliefs fragte die vier GITTER-Nachbarn, und die Plateau-Rampe war EINE
> Zelle breit — dieselbe Welt war auf der 2-m-Kachel eine andere Landschaft als
> auf der vergröberten Übersicht, gemessen Median 0,058 m, p95 0,675 m, **max
> 1,104 m** am selben Weltpunkt.) Die Kantenregel des Reliefs sondiert seither
> bei festen `RELIEF_EDGE_PROBE_M` = 2,0 m — dem Kachel-Schritt, damit die
> Kacheln exakt die Höhen behalten, die sie hatten.

**Wer die Funktion liest:** Serverregeln (`world_geometry.ground_y` →
`heightfield.world_height`, `nav_grid`, das Steilheits-Gate von
`POST /play/pos`),
Client-Regeln (Figur, Props, Scatter, Unterwuchs, Klick) und **das Bild** (der
Terrain-Vertex-Shader). Serverseitig ist der Vorrang `Kachel, sonst 0` — die
Übersicht liest der Server überhaupt nicht.

**`height_sig`** hasht alles, was die fünf Stufen lesen: die Höhenflächen, das
Mikro-Relief (`relief_inputs`), die Wasser-Polygone samt ihren drei Zahlen
(`water_basis`, seit W1 mit Profil-Enden und Fließrichtung) und die
Platzierungen der **gebauten** Orte — dafür braucht es kein eigenes Feld: ein Ort, der einen
Raum schließt, tritt in `placed_footprints()` ein, ein Ort, der ihn öffnet,
verlässt sie. Ändert sich die Signatur, holt der Client `GET /play/heightfield`
neu und **verwirft Kachel-Index samt aller geladenen Kacheln** — sonst nie. Wie
`terrain_sig` wird sie **nie gefoggt**: ein Bergrücken ist von weit außerhalb
sichtbar, und ein verstecktes Relief ließe Bild und Laufregel auseinanderlaufen.

---

### A16.2 Stufe 1 + 2 — die Autorierung

**Höhenflächen.** Eine Höhenfläche ist ein Polygon in Weltmetern plus
`height_m` (wie hoch der Boden darin steht) und `falloff_m` (über wie viele
Meter er dorthin ansteigt):

```
h_flaeche(p) = height_m · min(1, Abstand(p, Kontur) / falloff_m)
               für p INNERHALB der Kontur, sonst sagt die Fläche nichts
```

Die Fläche trifft die Welt also **auf ihrer eigenen Kontur** bei 0 und braucht
keinen passenden Nachbarn, um stetig auszusehen. `falloff_m` 0 heißt „kein
Übergang" — eine Wand an der Kante. **Überlappung: die STÄRKSTE Auslenkung
gewinnt** (größter `|Wert|`, bei Gleichstand der höhere) — als Auslenkung
formuliert, damit eine **Senke** (negatives `height_m`) nicht von der 0 der
flachen Welt drumherum geschlagen wird.

> **Bekannte Autorierungsgrenze** (Entscheid 2026-08-13, bewusst so): eine
> schwächere Fläche kann sich nicht RELATIV in eine stärkere einschneiden — ein
> 2-m-Graben quer über ein 9-m-Plateau bleibt Plateau. Wer eine Mulde im
> Hochland will, autoriert sie als eigene Fläche mit der ABSOLUTEN Höhe (7 m),
> nicht als Differenz.

`height_m` ist auf **±50 m** geklemmt (§ A1.7).

**Mikro-Relief der gemalten FLÄCHE.** Zwei whitelistete Felder je **Fläche**
(`meta.relief_amplitude_m`, `meta.relief_wave_m`) erzeugen zufällige kleine
Hügel überall dort, wo diese Fläche liegt — **eingebacken, nicht gerendert**,
also im EINEN Feld, das Server-Gate, Client-Spiegel und beide Renderer lesen.
Es gibt bewusst **keinen TS-Zwilling**.

> **Es ist eine Eigenschaft der INSTANZ, nicht der Art** (Entscheid
> 2026-08-23). Bis dahin trug die Terrain-ART die zwei Zahlen, womit jede Wiese
> einer Welt exakt so hügelig war wie jede andere: „Grasland" konnte nicht
> gleichzeitig eine wellige Hochebene und eine ebene Weide sein. Die Felder
> sind ohne Rückfall-Leser zur Fläche gewandert — die Art kennt sie nicht mehr,
> es gibt keinen Art-Default, und eine Fläche ohne die Keys ist eben. Eine
> einmalige Boot-Migration (`core/terrain_relief_migration.py`) schreibt den
> Wert, den die alte Regel benutzt hätte, in jede Fläche der betreffenden Art
> und räumt die Art-Zeilen leer; das Bild bleibt dabei exakt stehen, weil der
> Seed weiterhin aus dem ART-NAMEN kommt.

```
seed(art)  = FNV-1a 32 über den ART-NAMEN (es gibt KEIN Seed-Feld):
             h = 2166136261; je UTF-8-Byte b:  h = ((h XOR b)·16777619) mod 2^32
rnd(u, v)  = XorShift32((seed + u·73856093 + v·19349663) mod 2^32).next01()·2 − 1
u, v       = floor(x/wave), floor(z/wave);   tx, tz = die Nachkommateile
h_relief   = bilinear(rnd über die vier Ecken) · relief_amplitude_m
```

Der Seed ist ein Hash des NAMENS, weil ein gespeicherter Seed durch jede
Katalog-Änderung, jeden Export und jeden Klon mitgeschleppt werden müsste, nur
um den Boden stillzuhalten. Negative Ecken sind sauber definiert
(`& 0xFFFFFFFF`), zwei Flächen derselben Art **mit denselben zwei Zahlen**
setzen sich also nahtlos fort. Der Seed bestimmt das MUSTER, die Fläche, wie
hoch und wie breit es ausfällt: zwei Flächen einer Art mit verschiedenen
Amplituden lesen sich als derselbe Boden, der hier stärker wellt als dort.

**Klemmen.** `relief_amplitude_m` 0,05…2,0 m (fehlend oder 0 = kein Relief).
Die Obergrenze ist eine **Begehbarkeits**-Grenze: zwei Nachbar-Stützpunkte
können sich um höchstens 2·Amplitude über einen Gitterschritt unterscheiden,
auf dem 2-m-Kachelraster also `atan(2·2,0/2,0)` = **63°** im Maximum. Der
Editor **warnt** ab `tile_step_m · tan(max_slope_deg) / 2` (0,84 m bei den
Vorgaben) — beide Zahlen kommen vom Server (`heightMath.reliefWarnAmpM`),
geklemmt wird nichts. `relief_wave_m` **4**…200 m, fehlend = **32 m**; die
Untergrenze ist 2 × `TILE_STEP_M` (**Nyquist**). Beide Klemmen liegen seit dem
Umzug in `models/terrain.py` (`RELIEF_AMPLITUDE_MIN_M`/`_MAX_M`,
`RELIEF_WAVE_MIN_M`/`_MAX_M`, `DEFAULT_RELIEF_WAVE_M`) — beim Sanitizer, der
sie schreibt.

**Welche Fläche an einem Punkt gilt**, ist die Regel von
`terrain_query.kind_at` — die OBERSTE gemalte Fläche, die ihn enthält (letzter
Treffer gewinnt). Eine flache Fläche über einer hügeligen nimmt das Relief also
wieder weg, und zwei hügelige derselben Art entscheidet dieselbe Regel: die
obere antwortet, ganz. Ein Punkt,
den KEINE Fläche bedeckt, bekommt kein Relief: die unbemalte Welt bleibt eben,
und nur deshalb ist das Gitter überhaupt begrenzbar.

**Die Randregel: am Rand hebt das Relief nur noch.** Sondiert man von einem
Punkt aus `RELIEF_EDGE_PROBE_M` = 2,0 m in die vier Richtungen und trägt eine
Probe KEIN Relief (flache oberste Art oder unbemalter Grund), wird der
Rausch-Beitrag auf `max(0, Rauschen)` geklemmt — Positives läuft sanft in den
Nachbarboden aus (das Ufer hebt sich), Negatives endet auf dem autorierten
Niveau. Sonst zöge eine Senke im Gras die Naht des Sees mit sich nach unten.
**Die Probe ist ein METER-Abstand, kein Gitter-Nachbar** — genau das ist
Invariante 1 an dieser Stelle.

---

### A16.3 Stufe 3 + 5 — Wasser senkt sein Bett

> **ÜBERHOLT durch den Nachtrag „Ein Wasser-Gesetz — W1" (2026-08-21).** Es
> gibt keine fünfte Stufe (Zonen-Wasser) mehr, die Art trägt die Vorgaben für
> Tiefe und Rampe, und der Spiegel ist ein PROFIL statt einer Zahl. Was hier
> unverändert weitergilt: das `meta.water`-Flag als EINZIGES Prädikat, der
> Rand-Median als Default, die `min`-Regel des Carves und Invariante 2 — nur
> gegen `water_level_at(x, z)` statt gegen `water_level`.
>
> **Und die Achse dieses Profils ist seit W4a eine POLYLINIE** (Nachtrag
> „W4a", 2026-08-23): eine mit dem Linienwerkzeug gezeichnete Fläche fließt
> entlang ihrer eigenen Mittellinie (`meta.flow_along`), der See ist die
> Polylinie mit EINEM Knoten und die gerade Achse von W1 die mit zweien.

Ob eine Bodenart **Wasser** ist, sagt der Katalog: `meta.water` am Terrain-Typ
(`terrain_types.is_water_kind`) bzw. die Material-KLASSE der
Surface-Bibliothek (`water`/`ice`). **Nie über den Namen** — Arten sind ein
offenes Vokabular, eine Welt darf ihre Seen „lagoon" nennen.

Die drei Zahlen liegen an der **Fläche** (`terrain_areas.meta`) bzw. am
**Raum-Layout** (`layout.*`, Zonen-Wasser), weil zwei Seen in einer Welt auf
zwei Höhen stehen:

| Feld | Typ | Bedeutung |
|---|---|---|
| `water_level` | `float` (Welt-y, m) | Der Spiegel. **Optional**: fehlt er, nimmt die Bake den **Median der Höhe entlang des Umrisses** (alle 2 m abgetastet, gelesen NACH den Plateaus). `models.terrain.save_area` schreibt diesen Wert bei einer gemalten Fläche beim Speichern fest, damit der See nicht mitwandert, wenn jemand einen Hügel daneben malt |
| `water_depth_m` | `float` 0,2…20 (Default **2,0**) | Wie tief das Bett unter dem Spiegel liegt, sobald die Ufer-Rampe durch ist |
| `shore_ramp_m` | `float` 0…20 (Default **3,0**) | Wie weit INNERHALB des Umrisses die volle Tiefe erreicht ist; 0 = Stufe (Becken) |
| `water_level_effective` | `float` (nur Ausgabe) | Der Spiegel, mit dem die Bake wirklich gecarvt hat. Fährt additiv in `GET /world/terrain-areas`, `GET /play/terrain` und `GET /play/terrain-layers` mit und wird **nie** in das Autorenfeld zurückgeschrieben |
| `water_depth_effective` | `float` (nur Ausgabe) | Die TIEFE, mit der die Bake wirklich gecarvt hat: Art-Vorgabe + Flächen-Überschreibung + Klemme, schon aufgelöst. Fährt neben `water_level_effective` mit; der Renderer zieht daraus die Deckkraft (§ A16.3 Nr. 4, W4b) |

Der Median-Default deckt **beide** Fälle mit einer Regel ab: auf einer GEBAUTEN
Location hat der Plateau-Stempel das Grundstück eben gehobelt, also trägt jede
Randprobe die Plateauhöhe und der Median IST sie; auf einer natürlichen ist es
die Landschaft ringsum.

Carve pro Punkt innerhalb des Polygons:

```
h = min(h, water_level − water_depth_m · smoothstep(min(d_innen / shore_ramp_m, 1)))
```

`d_innen` = Abstand zum **Umriss**. `min`, nie Zuweisung: der Carve darf den
Boden nur senken — ein Ufer, das ohnehin unter dem Spiegel liegt, bleibt liegen.
Am Rand (`d_innen = 0`) ist der Carve `min(h, Spiegel)` — die Platte trifft das
Gelände, und genau das ist die Uferlinie.

> **INVARIANTE 2 — kein Texel über dem Spiegel.** Für jede Probe, die tiefer
> als `shore_ramp_m` im Polygon liegt, gilt `h_final ≤ water_level − ε` mit
> `ε = min(water_depth_m, 0,25)`. Damit ist „grünes Terrain sticht fern durchs
> Wasser" **datenseitig** unmöglich, in jedem LOD.
>
> **Das ist ein BEWEIS, keine Stichprobe.** Jenseits der Rampe ist
> `smoothstep(1) = 1` exakt, das zweite Argument des `min` also die KONSTANTE
> `Spiegel − water_depth_m` — was auch immer die Naturhöhe dort tut. Eine
> +40-m-Kuppe mitten im See kommt genauso auf `Spiegel − water_depth_m` heraus:
> ein Gelände-Texel über dem Spiegel in der Tiefzone ist nicht
> unwahrscheinlich, es ist arithmetisch unmöglich.

~~Die Polygone des Zonen-Wassers kommen aus derselben Funktion, aus der auch das
Material kommt.~~ **Gelöscht mit W1** — es gibt kein Zonen-Wasser mehr; ein Raum
auf Kartenwasser trägt nur noch den Verweis `map_water` in seinem
`floor_plan`-Eintrag.

---

### A16.4 Stufe 4 — Gebäude stanzen ihr Grundstück

**`level_ground` gibt es nicht mehr.** Es war ein manuelles Opt-in-Flag; wer
stempelt, ist jetzt eine Eigenschaft der Location selbst und entscheidet
`models.heightfield.draws_built_floor(loc)` — **der eine Name dieses Gesetzes**:

* es gibt ein **`map3d.outline`** (eine gezeichnete Gebäudekontur, ≥ 3 Punkte),
  ODER
* es gibt mindestens einen **geschlossenen Raum** (nicht `always_visible`; die
  Grundfläche `__ground__` zählt nie mit).

Ein natürlicher Ort (See, Lichtung, Wald) stempelt nichts — sein Boden IST das
Relief, seine Zonen sind Layer (§ A16.6). Die gezeichnete `boundary` zählt
nicht mit: sie ist das Grundstück, und wo ein See aufhört zu sein ist kein
Boden. Ein übrig gebliebenes `level_ground` in gespeicherten Daten wird
ignoriert; es gibt **keinen Fallback-Leser**.

**Zielhöhe** = **Median** der Höhen unter dem Grundriss, abgetastet auf dem
2-m-Weltgitter (vorher: eine einzige Probe am garantierten Innenpunkt — ein
Buckel entschied, wo das Haus steht).

**Rampe**, AUSSERHALB des Umrisses, `smoothstep` über

```
w = clamp(PLATEAU_RAMP_FACTOR · sqrt(Fläche/π), 2, 8)   Meter    (Faktor 0,5)
```

und, wenn die Randstufe `Δ = max |h0 − h_bisher|` entlang des Umrisses steiler
wäre als `tan(35°) · w`, verbreitert auf `w = Δ / tan(35°)`.

```
h = h0 + (h_bisher − h0) · smoothstep(d / w)      d = Polygonabstand, 0 innen
```

`h_bisher` ist ausdrücklich der Stand der Pipeline, **nicht** die unberührte
Landschaft: eine Hütte auf dem Dorfplatz läuft auf das Plateau des Platzes
hinunter, nicht auf den Hang darunter. Überlappung: **größte Fläche zuerst,
kleinste schreibt zuletzt** (das Verschachtelungsgesetz von
`location_at_point`).

> **EHRLICHE GRENZE — die 1,5-fache Spitze.** Die 35° sind die MITTLERE
> Steigung, und ein `smoothstep` erreicht das `SMOOTHSTEP_PEAK` = **1,5**-fache
> seines Mittels. Eine bis zur Kappung verbreiterte Rampe hat also einen
> steilsten Meter von `atan(1,5 · tan 35°)` = **46,4°** — immer noch über der
> Laufgrenze von 40°. Ein Ort an einer sehr steilen Flanke behält damit einen
> Rand, den seine Öffnungs-Ausnahme tragen muss (§ A15 Nr. 9). Was der Stempel
> bringt: der Rand ist eine mehrere Meter breite Rampe statt einer
> Ein-Zellen-Klippe von bis zu 68°.

`nav_grid` fragt dieselbe Funktion: die Steilheits-Ausnahme innerhalb eines
Ortes gilt für **gebaute** Orte statt für geflaggte (`Region.level_ground` ist
seither nur noch der interne Feldname dieses Ergebnisses). Die
PASSIERBARKEITS-Ausnahme („Fußabdruck gewinnt" bei gemaltem Untergrund) fragt
gar nichts: sie gilt für jeden Fußabdruck.

---

### A16.5 Die Lieferung — Übersicht, Kacheln, Mip-Pyramide

**Ein Gitter kann nicht beides sein.** Es gibt zwei Rasterungen derselben
Funktion, und **vermischt werden sie nie**:

- die **Übersicht** — ein Gitter über alles, vergröberbar. Ein BILD für die
  Ferne, sonst nichts; **keine Regel liest sie.**
- die **Kacheln** — 256-m-Quadrate im immer feinen **2-m-Schritt**, auf Anfrage
  gerechnet. Alles, was der Boden ENTSCHEIDET, liest diese.

**Das Gitter hängt am WELT-URSPRUNG, nie an `world_bounds`:**

```
origin = floor(min / step) · step − step          # ein Ring AUSSERHALB der Daten
punkte = ceil((max + step − origin) / step) + 1   # und einer dahinter
```

Damit verschiebt eine neu gemalte Fläche am Weltrand **keinen einzigen**
bestehenden Stützpunkt, und weil der komplette Rand außerhalb aller Flächen
liegt, ist er 0: **außerhalb des Gitters gilt der Randwert**, und das bedeutet
exakt „die flache Welt". `step_m` der Übersicht ist standardmäßig **4 m** und
reist MIT dem Datensatz; reicht die Ausdehnung über das Punktbudget (120 000
Stützpunkte), wird der Schritt **verdoppelt**, bis es passt. Diese Vergröberung
ist im Karten-Editor SICHTBAR (die Schreib- und Lese-Antworten von
`/world/height-areas` liefern `step_m`, `default_step_m` und `tile_step_m`) —
eine zweite Verdopplungs-Logik im Client wäre die Zwillings-Regel, die
auseinanderläuft.

**Kachelmaß 256 m, Anker ist der Welt-Ursprung.** Kachel `(tx, tz)` deckt
`[tx·256, (tx+1)·256] × [tz·256, (tz+1)·256]` ab; ihre Stützpunkte SIND globale
Gitterpunkte (`tile_key(x, z) = (floor(x/256), floor(z/256))`). **129 × 129
Punkte — die Ränder gehören dazu, in BEIDEN Nachbarn** (1,57 % Mehrdaten):
bilineares Sampling INNERHALB einer Kachel braucht damit nie einen Punkt der
Nachbarkachel, und weil beide Seiten denselben Punkt tragen, ist der Boden über
die Naht **stetig** statt nur beinahe.

**Zwischen den Stützpunkten ist das Feld BILINEAR**, und zwar in beiden
Sprachen gleich (`heightfield.sample_height` ↔ `@anima/scene-render`
`sampleWorldHeight`):

```
fx = clamp((x − origin_x)/step, 0, cols−1);  i = min(floor(fx), cols−2);  tx = fx − i
fz = clamp((z − origin_z)/step, 0, rows−1);  j = min(floor(fz), rows−2);  tz = fz − j
nord = h[j][i]·(1−tx) + h[j][i+1]·tx
sued = h[j+1][i]·(1−tx) + h[j+1][i+1]·tx
h    = nord·(1−tz) + sued·tz
```

Ein Feld mit weniger als 2 × 2 Punkten trägt kein Relief und antwortet 0.

**Die Mip-Pyramide ist Arithmetik auf der Kachel, keine zweite Auswertung.**
Weil die Mip-Gitter **Teilmengen** des 2-m-Basisgitters sind (4/8/16/32/64 m
sind Vielfache von 2 und teilen die 256 m Kantenlänge), entsteht sie durch
Downsampling.

```jsonc
// GET /play/heightfield  (Auth wie /play/terrain, nie gefoggt)
{ "origin_x": …, "origin_z": …,   // Weltmeter von heights[0][0]
  "step_m": 4.0, "rows": …, "cols": …,
  "heights": [[float, …], …],     // heights[j][i] bei (origin+i·step, origin+j·step)
  "sig": "…",                     // identisch mit worldmap.height_sig
  "tile_m": 256.0, "tile_step_m": 2.0,
  "tiles": ["tx,tz", …],          // der KACHEL-INDEX, sortiert nach tx, dann tz
  "mip_levels_m": [4.0, 8.0, 16.0, 32.0, 64.0],
  "tile_stats": { "1,0": { "min": -9.0, "max": 10.445,
                           "err": [0.5862, 0.85, 1.0, 1.1636, 3.3132] } },
  "tile_stats_complete": true }   // false: der Rest kommt mit den Kacheln

// GET /play/heightfield/tiles?keys=tx:tz,tx:tz   (BATCH_MAX 64 Schlüssel)
{ "sig": "…", "tile_m": 256.0, "step_m": 2.0,
  "mip_levels_m": [4.0, 8.0, 16.0, 32.0, 64.0],
  "tiles": { "1,0": { "origin_x": 256.0, "origin_z": 0.0,
                      "rows": 129, "cols": 129, "heights": [[…], …],
                      "stats": { "min": …, "max": …, "err": […] },
                      // ADDITIV seit HEIGHT_BAKE_VERSION 7 (Wasser v2 K-A E1):
                      // das WASSER-RASTER derselben Kachel, auf demselben
                      // Gitter. FEHLT, wenn die Kachel kein Wasser trägt.
                      "water": { "level": [[float|null, …], …],
                                 // ADDITIV seit v9: die vorzeichenbehaftete
                                 // Distanz zum GEMALTEN Umriss (+ innen,
                                 // − im Dilatationsring, null wie `level`) —
                                 // das einzige Feld, das sagt, wo der Autor
                                 // das Wasser gezogen hat. Der Fluss ist seit
                                 // v9 zusätzlich geglättet (Box, 8 m).
                                 "sd": [[float|null, …], …],
                                 "flow_x": [[float, …], …],   // optional
                                 "flow_z": [[float, …], …] } } } }

// GET /play/heightfield/stats?keys=tx:tz,tx:tz   (höchstens 64 Schlüssel)
{ "sig": "…",                     // wie oben ZUERST gelesen, vor jeder Rasterung
  "tile_stats": { "1,0": { "min": …, "max": …, "err": […] } } }
```

**`/play/heightfield/stats` liefert NUR die Statistik** — dieselben Zahlen wie
`tile_stats` der Übersicht, ohne Gitter und damit ohne Kilobytes. Es ist die
andere Hälfte von `tile_stats_complete: false`: ein CDLOD-Client nimmt seinen
größten senkrechten Fehler JE STUFE über alle Kacheln, für die er eine
Statistik hat, also unterschätzt er ihn auf einer Welt mit mehr als 64 Kacheln
und zeichnet die Ferne zu grob, bis diese Kacheln zufällig geladen werden. Der
Client holt den Rest im Hintergrund nach (`scene/ground.ts`, Stapel zu 64) und
rechnet nur seine Stufen-Fehler neu (`TerrainLod.refreshStats`) — die Pyramiden
hängen an den HÖHEN und bleiben stehen. Nicht indizierte Kacheln fehlen in der
Antwort wie beim Kachel-Batch; **über der Kappe antwortet der Endpunkt aber
400 statt zu kürzen**, denn eine still fehlende Statistik liest sich auf der
Client-Seite nicht als „flach dort", sondern als „vollständig".

`err[k]` ist der **größte senkrechte Fehler in Metern**, den ein Renderer
macht, wenn er die Kachel auf Ebene `mip_levels_m[k]` zeichnet statt auf der
2-m-Basis: `max |h_mip − h_basis|` über die Kachel, wobei `h_mip` das grobe
Gitter bilinear zurückinterpoliert.

> **INVARIANTE 3 — `err[k]` ist eine EXAKTE Schranke, keine Stichprobe.**
> Innerhalb einer Basiszelle sind beide Felder bilinear (das grobe auch, weil
> eine bilineare Funktion auf einem Teilrechteck bilinear bleibt), ihre
> Differenz also ebenfalls — und eine bilineare Funktion nimmt ihre Extrema **in
> den Ecken** an. Das Maximum über die Basis-Stützpunkte IST damit das Maximum
> über das Kontinuum.

`min`/`max` sind die Höhen-Spanne der Kachel — die andere Hälfte dessen, was
ein Quadtree-Knoten für Frustum und Occlusion braucht.

**Zwei Schreibweisen desselben Schlüssels, absichtlich verschieden:** in der
QUERY trennt `:` innerhalb eines Schlüssels und `,` zwischen ihnen
(`keys=0:0,1:0,-1:2`); im PAYLOAD heißt die Kachel `"tx,tz"`. Duplikate fallen
auf ihre ERSTE Position zusammen, **die Kappung greift NACH dem Entdoppeln**,
unlesbare Tokens werden übersprungen und **je einmal** geloggt. **Nicht
indizierte Kacheln fehlen einfach in der Antwort** — kein Fehler, kein
Null-Gitter: der Index hat dem Client schon gesagt, dass dort die flache Welt
ist.

**Kosten** (gemessen 2026-08-21, 2×2-km-Welt mit Relief, drei Seen, zwanzig
Grundstücken): Modellbau 20–30 ms, eine Kachel ~80 ms, ihre Statistik ~20 ms,
die 253²-Übersicht ~370 ms. `GET /play/heightfield` liefert die Statistik für
höchstens `TILE_STATS_MAX` = 64 indizierte Kacheln — diese Arbeit ist keine
zusätzliche, sondern nur vorgezogene: die Kacheln landen im Prozess-LRU
(`TILE_CACHE_MAX` = 128, Schlüssel `(Generation, tx, tz)`). Persistiert wird
weiterhin nur die Übersicht.

---

### A16.6 CDLOD — Render-LOD ist Sampling-Dichte, nie ein Datenwechsel

`client3d/src/scene/terrainLod.ts` zeichnet das ganze Gelände als EIN
instanziertes Patch-Mesh über einen Quadtree:

| Größe | Wert | Bedeutung |
|---|---|---|
| `PATCH_N` | 32 | Zellen je Achse und Knoten — ein Geometrie-Puffer für alles |
| `MAX_LOD_LEVELS` | 6 | Tiefe des Quadtrees |
| `MIN_LOD_DISTANCE_M` | 128 | Reichweite der feinsten Stufe; jede weitere verdoppelt |
| `MORPH_START` | 0,5 | ab 50 % der Stufen-Range morpht ein Vertex auf seinen groben Zwilling |
| `MAX_PIXEL_ERROR` | 2 | die Schranke, gegen die `err[k]` (§ A16.5) beurteilt wird |
| `MAX_NODES` | 4096 | Sicherung gegen entartete Kameras |

**Die drei Gesetze, die daraus folgen:**

1. **Die Höhe kommt IMMER aus derselben Pyramide.** Der Vertex-Shader zieht sie
   mit vier `texelFetch` + manuell bilinear aus `R32F` — bitgleich zur
   CPU-Formel (`|h_gpu − h_cpu| < 1e-4`, als Smoke assertiert). Der GLSL-Baustein
   dafür ist einmal da (`terrainLodSampleGlsl`, aus `terrainLodGlsl`
   herausgelöst, weil ein Fragment-Shader kein `attribute` deklarieren darf) und
   wird auch vom Wasser-Shader benutzt.
2. **Die SPIEL-Logik sampelt immer die feinste Ebene** (`nodeStep = 0`). Ein
   Höhensprung durch Kachel-Ladezustand ist damit ein Rendering-Übergang
   (Geomorph), nie ein Datenwechsel. Die alte Entweder-oder-Leiter
   („Kachel ODER Übersicht, nie gemischt") ist damit kein Vorrang mehr, sondern
   eine Ladefrage: der Client hält die indizierten Kacheln im Radius
   `HEIGHT_TILE_RADIUS_M` = **560 m** um seinen Anker, der Szenennebel endet bei
   **520 m**, die Naht liegt also konstruktionsbedingt hinter dem Nebelband.
3. **Es gibt kein zweites Boden-Mesh.** Keine Fußabdruckplatte, kein Sockel,
   keine gedrapte Fläche je gemalter Art, keine renderOrder-/polygonOffset-Leiter
   und keine y-Haarlinien. `smoke_layer_cut.mjs` liest die Quellen darauf ab —
   eine Löschung ist das Einzige, was eine positive Prüfung nicht messen kann.

---

### A16.7 Der Layer-Schnitt — `GET /play/terrain-layers`

**Bindende User-Vorgabe (2026-08-21):** Texturen werden nicht mehr
übereinandergelegt, sondern **geschnitten** — pro Stelle gewinnt genau ein
Layer, alles liegt auf EINER Fläche, die Übergangsbreite ist pro Bodenart
einstellbar.

`app/core/terrain_layers.py` bäckt zwei Masken je 256-m-Kachel, auf **denselben
Kachel-Schlüsseln** wie das Höhenfeld (`heightfield.tile_key`) — ein Anker, ein
Fenster, damit Form und Material des Bodens nie über verschiedenen Quadraten
geschärft werden.

| Maske | Auflösung | Format | Filter | Inhalt |
|---|---|---|---|---|
| `id` | **1 m/Texel** (256²) | RG8UI, 2 Byte | **NEAREST** | das PAAR (A, B) der Layer-Indizes an der nächsten Grenze |
| `sd` | **0,5 m/Texel** (512²) | R8 | **NEAREST (texelFetch)** | die SIGNIERTE Distanz zu genau dieser Grenze, in Metern — interpoliert wird im Shader, aus den VIER Texeln des eigenen id-Texels |

> **DAS PAAR IST KANONISCH — und das ist der ganze Trick.** Beide Seiten einer
> Grenze tragen dasselbe (A, B): **A ist immer der SPÄTER gemalte Layer**,
> niemals „der, auf dem ich stehe". Nur das VORZEICHEN von `sd` sagt, auf
> welcher Seite ein Texel liegt. Damit setzen ein NEAREST-Integer-Zugriff und
> eine LINEAR interpolierte Distanz eine durchgehende Kante zusammen: die id
> darf an jeder Texel-Naht auf die andere Seite springen, ohne je zu ändern,
> WELCHE zwei Materialien gemischt werden, und wo der Schnitt genau läuft, kommt
> allein aus der interpolierten Distanz — subtexel-scharf, in jedem Zoom, ohne
> ein einziges zusätzliches Dreieck. Wäre das Paar nach „der Layer hier"
> geordnet, kippten A und B über der Linie, das Vorzeichen mit ihnen, und die
> Kante risse an jeder Naht auf.

> **…UND KANONISCH IST ES NUR JE GRENZE.** Stehen in einer Nachbarschaft
> MEHRERE Grenzen (die Westwand eines Zimmers und die Küche an seiner Nordwand;
> der Rand eines Strandes gegen den Wald und sein Rand gegen den See), dann las
> ein Texel sein PAAR von der einen und sein VORZEICHEN von der anderen — und
> beides zusammen ergab einen Boden, der an keiner von beiden liegt. Gemessen an
> den Masken der laufenden Welt (Befundrunde 2026-08-21, Wohnzimmerboden „Haus
> von Kai", Welt −1551,95 / −761,50): id-Texel = Paar der Westwand
> (`wood | grass`) bei 2,75 m, sd-Texel = Vorzeichen der Nordlinie
> (`rubber | wood`) bei 2,75 m, komponiert `A = wood, sd = −2,77` → **Wiese,
> drei Meter innerhalb des Raums.** 627 solche Texel in den drei fotografierten
> Regionen, 0 danach. Drei Regeln halten das Paar seitdem zusammen:
>
> 1. **Eine Grenze ist ein LAYER-Wechsel, kein Rangwechsel.** Zwei Formen
>    derselben Bodenart, die sich berühren (ein Strand in drei Strichen gemalt),
>    haben keine Kante dazwischen; eine Naht dort hat vorher das Distanzfeld
>    ringsum von der echten Kante weggezogen.
> 2. **Ein Texel nimmt nur Grenzen an, an denen sein EIGENER Layer beteiligt
>    ist.** „Liege ich auf A's Seite" ist für einen dritten Boden keine Frage
>    mit Antwort — sie wurde als „B" gelesen.
> 3. **Ein id-Texel und die vier sd-Texel darunter sprechen von EINER Grenze:**
>    die id nimmt die nächste der vier, alle vier werden gegen DIESES Paar
>    signiert. Jenseits der Breite, in der der Übergang überhaupt noch gezeichnet
>    wird (`collapse_band_m` = halbe Blendbreite + Rausch-Ausschlag + 1 m
>    Reserve), **kollabiert das Paar auf (own, own)**: ein Texel tief in einem
>    Boden braucht keinen Zweitplatzierten, und keinen zu nennen ist genau das,
>    was aus einer Mittelachse keinen Haarstrich der falschen Art mehr macht.
>    Die Distanz bleibt dabei unverändert.

> **…UND DESHALB DARF DIE INTERPOLATION DAS id-TEXEL NIE VERLASSEN**
> (Befundrunde 2026-08-21, zweiter Durchgang). Regel 3 hält die vier sd-Texel
> EINES id-Texels zusammen und verspricht jenseits davon nichts — ein
> LINEAR-Filter der Hardware aber greift einen halben Texel ÜBER den Rand des
> id-Texels hinaus, in Texel, die zum Nachbarn gehören und gegen dessen Grenze
> signiert sind. Das Vorzeichen heißt „auf A's Seite MEINES Paares", also sind
> zwei Texel mit zwei Paaren zwei Zahlen auf zwei Skalen, und zwischen ihnen zu
> mischen ist Arithmetik über verschiedene Einheiten. Gemessen an den Masken der
> laufenden Welt (Wohnzimmer „Haus von Kai", Welt −1553,0 / −759,9): das Texel
> bei −1553,25 trägt **+1,26 m** gegen das Paar `wood | grass` der Westwand, sein
> Nachbar bei −1552,75 trägt **−1,26 m** gegen `rubber | wood` der Küchenlinie —
> benachbart, entgegengesetzt, beide für ihr eigenes Paar richtig. Der gefilterte
> Griff kam bei (−1552,95 / −759,95) auf **+0,47** und malte damit einen Streifen
> **Küchen-Gummiboden anderthalb Meter tief im Wohnzimmer**, entlang der ganzen
> Mittelachse der beiden Grenzen. Deshalb liest der Shader die Distanz per
> `texelFetch` und interpoliert die VIER Texel seines eigenen id-Texels selbst
> (`@anima/scene-render` `lcSdAt` / `layerSdBlockAt`) — **bilinear und über die
> Texelmitten hinaus EXTRAPOLIERT statt geklemmt**: ein Distanzfeld ist lokal
> eine Ebene, also ist der Viertelmeter bis zum Texelrand exakt, und wo zwei
> id-Texel dieselbe Grenze nennen, rekonstruieren beide dieselbe Ebene — die
> Kante bleibt über die Naht hinweg stetig und subtexel-scharf. Zahlen der
> Abnahme: 10 032 Sonden auf 0,05 m durch beide geschlossenen Räume und die
> Pool-Zone, 26 Texel tiefer als 0,5 m im Raum falsch → **0**; dieselbe
> Rekonstruktion über 100 × 100 m offenes Gelände: 9 Abweichungen → 6, alle
> innerhalb des Rausch-Ausschlags einer weichen Kante.

**Warum eine Integer-Textur für die id:** `usampler2D` + `texelFetch`. Eine
Integer-Textur kann *gar nicht* gefiltert werden — NEAREST erzwingt das FORMAT
und nicht eine Sampler-Einstellung, die ein Treiber anders auslegen könnte.

**Quantisierung, ausgeschrieben:** `code = clamp(round(sd · 127/8) + 128, 1,
255)`, zurück `sd = (code − 128) / (127/8)`. 127 Codes je Seite einer EXAKT
darstellbaren Null (128), Schritt 8/127 = 0,063 m, Band ±8 m. Code 0 wird nie
geschrieben. Server: `terrain_layers.encode_sd/decode_sd`; Client:
`@anima/scene-render` `decodeSd`, das seine zwei Zahlen aus dem PAYLOAD liest
und nicht aus einer Konstante.

**DIE PRIORITÄTSREGEL — der letzte enthaltende Eintrag gewinnt**, in dieser
Reihenfolge:

1. gemalte Terrain-Flächen (z_order, dann Malreihenfolge — genau die Regel, mit
   der `terrain_query.kind_at` Punktabfragen beantwortet);
2. je Location, **größte Fläche zuerst** — die KLEINSTE schreibt zuletzt und
   gewinnt (das Verschachtelungsgesetz von `location_at_point`);
3. innerhalb einer Location: offene Zonen, dann geschlossene Räume, je in
   Raum-Reihenfolge.

Die Bake füllt dafür ein Raster aus **Malrängen** (0 = ungemalte Welt, r = die
r-te Fläche der Liste), sodass „wer liegt oben" ein Integer-Vergleich ist.
**Bild und Regeln lesen damit erstmals dieselbe Antwort auf „welche Bodenart ist
hier?".**

**Übergangsbreite `edge_blend_m` — die Franse wird ein Regler.** Am Terrain-Typ
(`meta.edge_blend_m`, 0…8 m, Default **1,5**) und am Etage-0-Raumboden
(`layout.edge_blend_m`, 0…8 m, Default **0**). Der Unterschied ist Absicht: ein
gemalter Boden wächst, **ein Raumboden wird gezeichnet.**

> **DAS EINZIGE Katalogfeld, in dem 0 ein WERT ist** und nicht „nicht gesetzt":
> 0 ist der HARTE SCHNITT — Raumboden, Bordstein, gepflasterter Weg — und
> überlebt deshalb einen Save. Es geht bewusst nicht durch
> `_clamped_meta_number`, sondern durch `terrain_layers.sanitize_edge_blend`.

Der Shader schneidet:

```glsl
// EIN PIXEL, IN METERN BODEN — an der WELTPOSITION gemessen, vor jedem Zweig
float pixelM = max( length( dFdx( world ) ), length( dFdy( world ) ) );
float soft = smoothstep( -0.5*b, 0.5*b, sd );                  // b > 0
float hard = clamp( sd / max(pixelM, 1e-6) + 0.5, 0.0, 1.0 );  // b == 0
w = b > 0.0 ? soft : hard;
```

`b` kommt aus der Layer-Tabelle, **nach Art A**. Die halbe Breite liegt auf
jeder Seite, also sind „1,5 m Übergang" wirklich 1,5 m Boden und nicht drei.
Bei `b = 0` ist der Schnitt ein **ein Pixel breiter** Schritt, wo die Kamera
auch steht: nah ist ein Pixel zentimeterklein und die Kante rasiermesserscharf,
fern ist er metergroß und derselbe Ausdruck MITTELT die beiden Böden, statt zu
flimmern. Die Ableitung steht außerhalb jedes Zweigs — eine Ableitung in
Kontrollfluss, der über ein Quad hinweg auseinanderläuft, ist in GLSL ES
undefiniert, und genau dieser Zweig läuft an jeder Grenze auseinander.

> **`pixelM` wird an der WELTPOSITION gemessen, nie als `fwidth( sd )`**
> (Befundrunde 2026-08-21, Befund 3). Ein Distanzfeld hat den Gradienten 1, also
> sind beide dieselbe Zahl, **solange das Feld glatt ist** — an einem Texel,
> dessen Nachbar eine andere Grenze nennt, und am Rand des geladenen
> Masken-Fensters ist es das nicht: dort explodiert die Ableitung der GESAMPELTEN
> Distanz, „ein Pixel" wird metergroß, und der harte Schnitt fällt für dieses
> eine Quad auf ein 50/50-Mittel zweier Böden zurück. Das war das
> **hellblaue Aufblitzen einzelner Flächenstücke beim Drehen der Kamera** — die
> Quad-Raster wandert mit der Kamera, also wandern die Flecken. Die
> Weltposition ist per Konstruktion stetig.

Weil `b` nach Art A gelesen wird, ist **eine Art bei zwei Breiten zwei Layer**;
die Tabelle führt Einträge je `(kind, edge_blend_m)` und wächst über die
Terrain-Arten hinaus auf die Boden-Arten (eine Boden-Art trägt sich selbst als
`surface`, weil `surfaces.floor` direkt eine Bibliotheks-Id ist).

**Die Franse ist nicht weg, nur ihr Mechanismus.** Das Rauschen, das die Grenze
organisch aussehen ließ, überlebt unverändert (0,5 m Ausschlag über 2 m
Wellenlänge, `LC_EDGE_NOISE_M`/`LC_EDGE_WAVE_M`) — es schiebt jetzt die LINIE
statt der Alpha, und sein Ausschlag ist auf die halbe Breite gedeckelt: bei
`b = 0` also auf **null**, damit der harte Schnitt auf dem Meter endet, auf dem
er gemalt wurde.

**Der Endpunkt — einer, zwei Modi**, weil es zwei Hälften desselben Fensters
sind:

```jsonc
// OHNE keys — der INDEX
{ "sig": "…", "tile_m": 256.0,
  "id_step_m": 1.0, "sd_step_m": 0.5, "sd_band_m": 8.0,
  "sd_zero": 128, "sd_codes_per_m": 15.875,
  "layers": [ { "index": 0, "kind": "grass", "surface": "grass",
                "edge_blend_m": 1.5, "water": false }, … ],
  "overview": { "origin_x": …, "origin_z": …, "step_m": 8.0,
                "cols": 250, "rows": 250, "id": "<base64 cols·rows·2>" },
  "tile_keys": ["0,0", "1,0", …],
  "waters": [ { "location_id": "…", "room_id": "pond", "kind": "water",
                "polygon": [[295.0,-5.0], …],       // WELT-Meter
                "water_level_effective": 0.0 } ] }

// MIT keys=tx:tz,tx:tz — die BATCH, höchstens BATCH_MAX = 16 Kacheln
{ "sig": "…", …, "layers": […],
  "tiles": {
    "1,0": { "origin_x": 256.0, "origin_z": 0.0,
             "id_size": 256, "sd_size": 512,
             "id": "<base64 256·256·2>", "sd": "<base64 512·512>" },
    "2,0": { "origin_x": 512.0, "origin_z": 0.0, "uniform": 3 } } }
```

`layers[0]` IST der blanke Boden (die `game.default_terrain_kind` der Welt);
eine Fläche, die in der Default-Art gemalt ist, bildet auf 0 zurück statt einen
Zwilling zu bekommen. Byte-Reihenfolge zeilenweise vom Kachel-Ursprung, Texel
`(i, j)` deckt `[i·step, (i+1)·step)`. Eine Kachel ohne jede Grenze antwortet
`uniform` und schickt **kein** Array — der Normalfall draußen, und der
Unterschied zwischen 40 Byte und 384 kB. `waters` führt die Wasser-RAUMBÖDEN in
derselben Form, in der eine gemalte Fläche ihren Spiegel führt — damit ein
Client den Teich eines Raums mit der Maschinerie zeichnet, mit der er einen See
zeichnet. Ein Raum, den der Bake nie gesehen hat (unplatzierte Location), bleibt
**WEG** statt eine geratene Höhe zu bekommen.

> **W1-Nachtrag:** die `waters`-Liste des Index ist ersatzlos gestrichen, und
> ein Wasser-Layer trägt `bed_kind` und malt die Oberfläche seines BETTS.

**Der Vertrag zum Refetch:** die Masken hängen an `terrain_sig` (die gemalten
Flächen + der Art-Katalog) bzw. an `layers_sig` (`floors_basis`, die
Grundrisse). Ein eigener Poll existiert nicht.

**Der Kompositor im Client** (`client3d/src/scene/layerGround.ts`) hängt sich
als LETZTES Patch in die Material-Kette der CDLOD-Fläche (`patchHole` →
`applyNaturalGround` → **dies**) — und läuft damit als ERSTES im Shader, weil
jedes Boden-Patch seinen Rumpf direkt hinter `#include <map_fragment>` einsetzt.
Genau das ist verlangt: der Kompositor schreibt die Albedo, die Naturstufen
(Farbflecken, Höhen-AO) arbeiten auf dem KOMPONIERTEN Ergebnis. Das
Terrain-Material trägt **keine `map`** — mit einer wäre `USE_MAP` gesetzt und
die Anti-Kachel-Stufe blendete die Breitprobe der DEFAULT-Art über jeden Wald;
die Anti-Kachelung liegt statt dessen im Kompositor, **pro Layer** (`lcSurface`).
Die Oberflächen liegen in EINER `DataArrayTexture`, eine Schicht je
Layer-Index, jede auf 512² gebracht. Zwei Fenster wie beim Höhenfeld: die
geladenen Kacheln werden zu EINEM Rechteck gepackt (`packLayerWindow`) und
folgen dem Höhen-Anker über dieselbe Wunschmenge; darüber hinaus antwortet die
weltweite GROBE `overview`-Maske — sie trägt keine Distanz, denn bei 8 m/Texel
ist jeder Übergang schmaler als ein Texel, also ist ein harter Schnitt die
einzige ehrliche Antwort.

**Der Unterwuchs liest dieselbe Maske** (User-Entscheidung 5.2): ein Büschel
wächst nur, wo die OBERSTE Bodenart an seinem eigenen Punkt wirklich die Art
ist, der es gehört (`@anima/scene-render` `topLayerAt`, im Client
`layerGround.topLayerIndexAt`). Die Polygon-Occluder bleiben als billiger
erster Durchgang davor — zwei Implementierungen von „oberste Art" sind zwei
Antworten, die auseinanderlaufen werden.

**Kostenbudget** (2 × 2-km-Welt): eine Kachel roh 393 216 Byte (id 131 072 + sd
262 144), ganze Welt **24,0 MB** roh / 32,0 MB base64 (61 Kacheln), ein Fenster
von 9 Kacheln auf der GPU 3,54 MB, Übersichtsmaske (8 m) **127 kB**. Bake einer
Kachel MIT Grenzen ~0,32 s (kalt, danach LRU), ohne Grenze ~0,04 s bei 40 Byte
Antwort. Fragment-Kosten: 1 id-Fetch + **4 sd-Fetches** (die vier Texel des
eigenen id-Texels, die der Shader selbst interpoliert — ein gefilterter Griff
läse den Nachbarn mit) + 4 Array-Fetches (vier statt
zwei, weil die Anti-Kachelung PRO LAYER schmal und breit probt). Dafür ist das
Terrain **1 Draw-Call** statt einem Mesh je gemalter Fläche plus Platten.

---

### A16.8 Der Wasserspiegel — eine Platte, ein Ufer, ein Schwimmer

> **TOT, soweit es die PLATTE und ihr UFER-GLSL betrifft — Wasser v2 K-A
> (E3/E4/E5, Nachtrag „Das Wasser-Raster", Punkte 7a/9/10).** Es gibt kein
> Wasser-Mesh mehr: das Terrain hebt seine eigenen Vertices auf
> `max(h, w_level)` (E3) und schattiert dieselben Pixel als Wasser (E4); der
> Bauer `addMirror`, `scene/waterPlane.ts`, die Attribute `aWaterFlow` /
> `aWaterOpaque`, die Streifen-Schnitte, der Ufer-`discard` und die
> Transparenz-Sortierung sind mit E5 gelöscht. Was von diesem Abschnitt WEITER
> GILT: die Zahlen der Uferkurven (Tabelle unten, ohne `WATER_SHORE_BAND_M` und
> `WATER_FOAM_ALPHA`), die Tiefen-Definition `Pegel − h(x, z)`, und der ganze
> SCHWIMMER-Teil (`floatRootY`, `groundWaterLevel`, `typeAt`) — der liest den
> Spiegel exakt aus `meta.water_profile` und ist von allem Render-Umbau
> unberührt. Der Rest steht hier als Geschichte.

**Die Fläche ist eben, und ihre Höhe IST die Geometrie.** Pro Wasserfläche —
gemalte Karten-Fläche wie Zonen-Wasser, **derselbe Bauer** (`scene/ground.ts`
`addMirror`) — eine **flache Earcut-Platte** auf `y = water_level_effective`,
ohne jede Unterteilung: eine Ebene braucht in der Mitte keine Stützpunkte. Ein
Kilometer See sind ein paar Dreiecke.

`transparent: true`, `depthTest: true`, `depthWrite: false`, gezeichnet nach
dem opaken Gelände. **Kein `renderOrder`, kein `polygonOffset`, kein Lift** —
die Platte ist mit dem Bett konstruktionsbedingt nicht koplanar (Invariante 2,
in jedem Mip).

**Der Spiegel steckt in der Platten-y, nicht in einem Uniform.** Der Fragment
liest seine eigene Weltlage (`vWaterPlane.y`), und die ist bei einer ebenen
Platte genau der Spiegel. Deshalb teilen sich **alle Seen einer Bodenart EIN
Material**, egal auf wie vielen Höhen sie stehen: zwei Seen auf zwei Höhen sind
zwei Meshes, nicht zwei Shader.

**Zwei Bedingungen entscheiden über eine Platte, und beide sind Daten:** die
KLASSE sagt, wie die Oberfläche aussieht (`isWaterClass` — nie die Farbe, nie
der Name der Art), `water_level_effective` sagt, ob die Bake ein Bett gecarvt
hat und auf welcher Höhe. Fehlt der Spiegel, gibt es **keine Platte** — eine
auf Geländehöhe geratene Ebene wäre die alte Drape von vorn. `null` ist die
Form von „der Bake hat das nie gesehen" und darf **nicht** zu 0 werden
(`Number(null)` IST 0, und eine Ebene auf Welt-Null über einem Innenhof-Teich
wäre genau die geratene Höhe). Das AUTORIERTE `water_level` wird bewusst nicht
gelesen: es darf leer sein.

**Das Ufer kommt aus der TIEFE, nicht aus einem Depth-Pass:**

```glsl
float wsDepth = vWaterPlane.y - tlodHeight( vWaterPlane.xz, 0.0 );
if ( wsDepth <= 0.0 ) discard;
```

`tlodHeight` ist **derselbe Lookup, mit dem der Terrain-Vertex-Shader seine
Höhen zieht** (§ A16.6). Kein Screen-Space-Depth, kein Depth-Prepass, kein
zweites Render-Target: der Boden ist bereits eine Funktion, die man fragen kann.
Der **Discard bei `wsDepth ≤ 0`** ist das einzige Band, in dem Platte und
Gelände dieselbe Fläche sind — das ist die Uferlinie, und ein Fragment, das dort
am Tiefentest teilnimmt, flimmert, wie klein sein Alpha auch ist.

> **ÜBERHOLT, soweit es die EBENHEIT betrifft** (Nachtrag „Ein Wasser-Gesetz
> — W1"): der Spiegel einer Fläche mit `flow_dir_deg` ist eine GENEIGTE Ebene,
> und ab W2 zieht der Client seine Platten-Vertices aus
> `meta.water_profile`. Alles andere in diesem Abschnitt bleibt: die Höhe
> steckt weiterhin in der GEOMETRIE der Platte, das Ufer kommt aus der Tiefe,
> `null` wird nie 0 — und der Zonen-Wasser-Vorrang in `typeAt` stirbt mit den
> Zonen-Wassern.

**Die Zahlen** (`client3d/src/scene/waterPlaneMath.ts`):

| Größe | Wert | Woher |
|---|---|---|
| `waterOpaqueDepthM(Tiefe)` | **¾ der eigenen Bett-Tiefe** (Default-See: 1,5 m) | Deckung = `smoothstep(0, Band, Tiefe)`. Beim Default-See (`water_depth_m` 2,0 über `shore_ramp_m` 3,0) ist ¾ genau `smoothstep = 0,75`, also `t ≈ 0,6736` → volle Deckung **2,02 m** innerhalb des Umrisses. Ein 0,6-m-Tümpel erreicht gegen die Band-Zahl des SEES nie 1 (0,352) — gegen sein eigenes Band schon (W4b; die feste Konstante `WATER_SHORE_BAND_M` ist mit dem Mesh gelöscht) |
| `WATER_FOAM_BAND_M` | 0,6 m | `1 − smoothstep(0, 0,6, Tiefe)`; endet ungefähr dort, wo das Waten ins Schwimmen kippt |
| `WATER_FOAM_STRENGTH` | 0,6 | wie weit die Gischt das Licht Richtung Weiß zieht |
| `WATER_EDGE_FADE_M` | 0,05 m TIEFE | die Randrampe, die an der Wasserlinie exakt 0 erreicht — beim Mesh gegen den `discard`, seit K-A gegen die trockene Nachbarschaft |

Deckungs-Stützstellen (Default-Band 1,5 m): Tiefe 0,15 → 0,028 · 0,3 → 0,104 ·
0,75 → 0,5 · 1,125 → 0,84375 · 1,5 → 1. Das zusätzliche Rand-Alpha der Gischt
(`WATER_FOAM_ALPHA` 0,15) war eine Eigenschaft der TRANSPARENTEN Platte und ist
mit ihr gelöscht: ein Wasserpixel ist heute opaker Boden.

**Schwimmen liest den Spiegel** — eine exportierte Funktion für Avatar, NPCs und
Reisende (`walk.floatRootY`):

```
root = waterLevel === null ? groundY : max( groundY + sink, waterLevel )
body = root − sink                      (unverändert, figures.Figure.play)
     = waterLevel === null ? groundY − sink : max( groundY, waterLevel − sink )
```

> **Der Übergang fällt aus dem `max`, er ist keine zweite Regel.** Die beiden
> Zweige sind gleich, wo `groundY + sink = waterLevel` — bei einer Wassertiefe
> von **exakt `sink`**. Flacher wird GEWATET (Füße auf dem Bett), tiefer
> GESCHWOMMEN (Körper `sink` unter der Wasserlinie, egal wie tief das Bett
> fällt). Das Maximum zweier stetiger Funktionen ist stetig: ins Wasser laufen
> ist ein glatter Abstieg, ohne Stufe an der Wasserlinie und ohne Stufe am
> Übergang.

Mit dem Wasser-Seed der Welt (`move_sink_m` 0,35, `idle_sink_m` 1,3) und
Spiegel `L`:

| Tiefe | root (Schwimmer) | root (Treter) | body (Schwimmer) | body (Treter) |
|---|---|---|---|---|
| 0,00 | L+0,35 | L+1,30 | L | L |
| 0,35 | L | L+0,95 | L−0,35 | L−0,35 |
| 1,30 | L | L | L−0,35 | L−1,30 |
| 2,00 | L | L | L−0,35 | L−1,30 |

**Woher der Spiegel unter einem Punkt kommt: `typeAt` — und ZONEN gewinnen.**
Ein Raumboden aus Wasser rangiert **über** einer gemalten Fläche, exakt wie
sein Boden im Layer-Bake (§ A16.7 Priorität 2/3); unter mehreren Zonen gewinnt
die LETZTE (`waterPlaneMath.zoneWaterAt`, dieselbe Letzter-gewinnt-Lesung wie
die Maske). Ohne diese Sprosse watete eine Figur mitten im See auf dem gecarvten
Bett zwei Meter unter der Ebene, die sie sah. Kennt der Terrain-Katalog die
Bodenart einer Zone nicht (eine Boden-Art ist eine Surface-Bibliotheks-Id, kein
Terrain-Kind), leiht sie sich die Sink-/Animations-/Tempo-Zahlen der ersten
katalogisierten Art mit `meta.water` — deterministisch nach Schlüssel sortiert;
trockenen Fußes AUF einem See zu stehen ist der sichtbare Fehler, gegen den das
existiert.

**Reichweite wie beim Sink.** `walk.groundWaterLevel(level, scope)` ist der
exakte Zwilling von `groundSink`: eine geflieste Halle im See ist ein BODEN, in
ihr schwimmt niemand (`scope === 'built'` → `null`). Die Passierbarkeit
entscheidet weiter der Server, art-basiert. **KEIN Zusatzabstand über dem
Bett** — ein positiver Clearance höbe einen Watenden von dem Grund ab, auf dem
er steht, und kaufte nichts: die Stetigkeit ist Sache des `max`.

---

### A16.9 Die Szene über dem Boden — was nach E5 im Rezept steht

**Auf Etage 0 gibt es keine Bodenplatte mehr.** Ersatzlos aus `plates[]`
verschwunden sind: die Etagenplatte der Kontur (Oberkante 0,08, Körper 0,14),
die Raum-Bodenplatte je geschlossenem Raum (0,10), die Zonen-Fläche je
`always_visible`-Raum (0,09) und die Overlay-Fläche einer Zone auf einem
Flächenmodell (Modell-Oberfläche + 0,01). Ihr Ersatz ist das gestanzte Plateau
(§ A16.4) für die HÖHE und der Layer-Bake (§ A16.7) für das MATERIAL.

**`plates[]` trägt nur noch DEKLARIERTE Etagen** — `level != 0`. Nicht „oben":
ein Keller auf −1 liegt eine Etage unter dem Gelände und behielte sonst gar
keinen Boden.

**Die Höhenleiter, in einer Funktion:**

```python
storey_floor_y(level, storey) = level*storey + (0.0 if level == 0 else LEVEL_PLATE_TOP)
```

Alles, was auf einem Boden steht, misst von hier plus dem, was der RAUM
darüberlegt (`scene_recipe._plate_top`): **0 auf Etage 0**, sonst
`ROOM_PLATE_TOP` 0,10 (geschlossener Raum), 0,09 (Zone, `slab +
OVERLAY_SURFACE_LIFT`) bzw. 0,08 (Hof). **Die drei Konstanten `LEVEL_PLATE_TOP`
/ `ROOM_PLATE_TOP` / `OVERLAY_SURFACE_LIFT` sind seither ausschließlich die
Datums einer deklarierten Etage** und kommen auf Etage 0 in keinem `top_y`,
`base_y` oder `bottom_y` mehr vor.

Die Laufketten von „Haus von Kai" (gebaut) und „Mondscheinsee" (natürlich),
alt → neu:

| Größe | gebaut, ALT | natürlich, ALT | BEIDE, NEU |
|---|---|---|---|
| Etagenplatte Oberkante | 0,08 | — | — |
| Raumplatte / Zonenfläche | 0,10 / 0,09 | 0,01 | — |
| Boden, auf dem gestanden wird | 0,10 | 0,01 | **0,00** (`h_final`) |
| Wandfuß (Raum / Kontur) | 0,10 / 0,08 | — | **0,00**, gesäumt auf −0,14 (s. u.) |
| Prop `bottom_y` | 0,11 | 0,02 | **0,01** |
| Diorama `bottom_y` (ohne Regler) | 0,12 | 0,03 | **0,02** |
| Türschwelle ohne Deklaration | 0,10 | — | **0,00** |
| Gebäudemodell `walk_y_world` | 0,08 + `offset_y` | 0,00 + `offset_y` | **`offset_y`** |
| Aufzugs-Pad (Mitte) | +0,055 | — | **−0,025** |

**Die beiden NEU-Spalten sind identisch — das ist der Punkt.** Die drei alten
BODEN-Zahlen 0,10 / 0,09 / 0,01 sind die roten Gegenproben dieser Etappe. Die
0,01, die bleibt, ist die Anti-Z-Fight-Haarlinie des PROPS über dem Gelände
(`PROP_CLEARANCE`), nie ein Boden. Eine DEKLARIERTE Etage hat sich um keinen
Millimeter bewegt: die Kontur-Platte der Etage 1 liegt weiter auf
`1·2,8 + 0,08 = 2,88`, die Raumplatte darauf auf `1·2,8 + 0,10 = 2,90`, ein
Keller-Raum auf `−2,8 + 0,10 = −2,70`.

**Vier Sprossen seit v6** (Nachtrag „Oberflächen-Raster", 2026-08-27). Über
diese Datums-Leiter ist eine Sprosse gekommen, und sie steht ganz oben:
**das gebackene Oberflächen-Raster → die Deklaration `walk_y_world` → die
Stockwerks-Platten → das Terrain**. Sprosse 0 ist der Nutzlast-Block `surface`
eines Dioramas oder eines `walkable`-Props, gelesen durch die eine Sample-Formel
(`surfaceHeightAt`) — das höchste antwortende Raster gewinnt, ohne
`plateCeiling`-Kappung, und wo keines antwortet, geht die Leiter unverändert
weiter. `standY = max(Kachel-Antwort, Weltboden)` bleibt, wie es ist: das
Terrain ist weiterhin die Untergrenze. Der `lift` dieses Abschnitts gilt für das
Raster genauso wie für sein Modell — es steht, wo das Modell steht.

**Der Wandfuß bekommt einen SAUM** (Befundrunde 2026-08-21). Ein Wandfuß ist
eine gerade waagerechte Linie, der Boden darunter ist es nicht. Bis E5a fiel das
nie auf, weil der Fuß in einem PLATTENKÖRPER steckte: eine Konturwand auf
`LEVEL_PLATE_TOP` 0,08 über einer Etagenplatte, die bis 0,08 − 0,14 = −0,06
reichte — **0,14 m Material unter dem Fuß**. Die Platte ist weg, der Fuß trifft
das nackte Gelände, und jeder Millimeter, den der Boden unter der Wand wegläuft,
reißt eine beleuchtete Lücke auf.

Also behält die Wand genau diesen Körper als Saum: **auf Etage 0 beginnt ein
Wandstück `WALL_SINK_M` = `LEVEL_PLATE_THICKNESS` = 0,14 m UNTER der Bodenlinie
und ist um denselben Betrag höher** (`scene_recipe`, Kontur- wie Raumwand).

| | ALT (E5a) | NEU |
|---|---|---|
| Etage 0, Kontur | `base_y` 0,00 · `height` 2,85 | **−0,14 · 2,99** |
| Etage 0, Raum | `base_y` 0,00 · `height` 2,85 | **−0,14 · 2,99** |
| Etage 1, Kontur | 3,08 · 2,85 | 3,08 · 2,85 |
| Etage 1, Raum | 3,10 · 2,85 | 3,10 · 2,85 |

Drei Eigenschaften, und alle drei sind der Grund für genau diese Zahl:

* **Die OBERKANTE bewegt sich nicht.** `base_y + height` ist unverändert, also
  ändert sich über dem Boden nichts — kein Fenster, kein Sturz, kein Konsument,
  der `base_y + height` liest.
* **Nur der FUSS bekommt ihn.** Ein Fensterbrüstungsstück beginnt auf dem Boden
  und wird gesäumt; Sturz und Glasband hängen höher und bleiben unberührt. Eine
  **Türschwelle ist keine Wand** — `doorways[].base_y` ist die STANDHÖHE der
  angrenzenden Räume und bleibt 0,00.
* **Eine DEKLARIERTE Etage wird gar nicht gesäumt.** Dort steht die Platte noch,
  und 0,14 ist exakt die Tiefe, in der ein Konturfuß die UNTERSEITE der
  Etagenplatte erreichte (3,08 − 0,14 = 2,94) und aus der Decke darunter zu
  hängen begänne. Das ist die OBERGRENZE des Saums; die UNTERGRENZE ist der
  Plateau-Rampenfall: die Außenfläche einer Wand liegt `WALL_THICKNESS/2` =
  0,035 m außerhalb des Rumpfes, dem der Stempel folgt, und gleich außerhalb des
  Grundstücks darf der Boden mit vollen `max_slope_deg` = 40° fallen —
  0,035 · tan 40° = **0,029 m**. 0,14 trifft die Obergrenze und schlägt die
  Untergrenze um das 4,8-fache. Beide Enden hergeleitet in
  `scripts/smoke_scene_recipe.py` [4a].

**Eine Platzierung auf Etage 0 steht auf dem Gelände AN IHREM EIGENEN (x, z)**
(Befundrunde 2026-08-21). Das Payload nennt jede Zahl gegen das Datum des
Szenen-Rahmens — `y = 0` ist der Boden unter dem ANKER-PIN, EINE Höhe für den
ganzen Ort. Auf einem gebauten Grundstück stimmt das exakt (§ A16.4 stempelt
eben auf genau diese Höhe); auf einem NATÜRLICHEN Ort stimmt es an einem Punkt
und sonst nirgends. Gemessen an „Mondscheinsee" (Pin-Boden −2,00 m, das Seebett):
seine beiden Ufer-Dioramen sind auf `bottom_y` −0,28 komponiert, werden also auf
−2,28 gezeichnet, während das Gelände unter ihren eigenen Ankern auf +0,277 bzw.
+0,335 steht — **2,56 m und 2,62 m tief begraben**, bei 5,08 m Relief über dem
Ort.

Die Regel ist die der WELT-PROPS (§ A9a), auf die Szene angewandt — der Renderer
hebt um

```
lift = groundAt(x, z) − datum          # datum = Boden unter dem Anker-Pin
```

und sie steht **einmal**, in `packages/scene-render/src/storeyGround.ts`
(`storeyGroundLift`), mit dem Höhen-Sampler als PARAMETER. Der 3D-Client reicht
`heightAt` hinein, die Admin-Vorschau `flatGround(0)` — deren Bühne ist eben,
also antwortet dieselbe Formel dort 0. Keine zweite Regel, keine Ausnahme.

* **`level != 0` wird NICHT gehoben.** Eine deklarierte Etage steht auf einer
  PLATTE; das Gelände reicht nicht an sie heran und darf sie nicht bewegen —
  derselbe Schnitt, den dieses Kapitel schon für `plates[]`, `storey_floor_y`
  und die Figuren-Leiter zieht.
* **Das GEBÄUDE-/FLÄCHEN-Modell auch nicht.** `role: "building"` steht nicht auf
  dem Grundstück, es IST das Grundstück, und es hat sein eigenes Ankergesetz
  (`walk_y_world`, `offset_y`), das die Figuren-Leiter zurückliest.
* **Das `walk_y_world` eines Dioramas fährt MIT.** Sonst stünden die Figuren des
  Raums weiter auf der komponierten Höhe, während die Hütte am Hang sitzt.
* **Raum-Mitte, Stellplätze und Raum-Marker brauchen nichts davon**: die holen
  ihre Höhe ohnehin schon punktweise aus dem Höhen-Sampler (`roomFloorWorldY`,
  oben) — dort wird der Term nur überschrieben, nie doppelt gezählt.
* **Ein `fixed`-Marker (Prop-Marker) bekommt ihn aber sehr wohl.** Er ist aus
  der Bounding-Box SEINES Props komponiert und bleibt sonst unberührt; stiege
  das Prop ans Ufer und die Sitzmarke nicht, säße die Figur in der Luft, wo der
  Stuhl einmal stand. Er wird an seinem EIGENEN Punkt gehoben.

**Und das DATUM selbst ist auch nur eine Höhen-Abtastung** (Befundrunde
2026-08-24, „Haus von Kai" schwebt). `datum` ist der Boden unter dem Anker-Pin,
im 3D-Client `tile.center.y` — gelesen aus genau dem Feld, das spät eintrifft
und bei jedem neuen Bake wieder wandert, und gelesen **einmal**, beim Bau der
Kachel. Für alles mit einem `lift` ist das folgenlos: `lift = ground − datum`
kürzt das Datum aus `datum + bottom_y + lift` heraus. Für das eine, das die
Regel bewusst NICHT hebt — das Gebäudemodell, das ja das Grundstück IST —, ist
das Datum die ganze Antwort, und ein veraltetes Datum ist exakt die Höhe, in der
das Haus in der Luft hängt.

Also trägt die Kachel ihr Datum genauso nach wie eine Platzierung ihren Lift
(`tileDatumStep` in derselben Datei, `redatumTile` im Client, auf demselben
`heightRevision`-Takt): **der RAHMEN wird bewegt, und die Nachhebung der
Platzierungen zieht denselben Betrag sofort wieder ab** — jedes gehobene Objekt
hängt IM Rahmen, wandert also mit und landet wieder auf `ground(anker) +
bottom_y`. Nur Gebäude, Platten, Wände und Labels stehen danach woanders, und
zwar dort, wo eine mit fertigem Feld gebaute Kachel sie hingestellt hätte. Die
`fixed`-Marker sind das einzige, was der Rahmen nicht trägt (sie sind in
WELT-Koordinaten komponiert) — die werden von `redatumTile` mitgeführt. „Nichts
zu sagen" (kein Sampler, NaN) hält auch hier das Datum fest: eine aus dem Cache
gefallene Kachel darf nicht auf die Welt-Null durchsacken. Der Vorgänger dieser
Prüfung war `main.relevelTiles`; sie ging mit der Bodenplatte („Ein Boden" E3),
deren Drapierung ihre zweite Klausel überwachte. Handzahlen:
`client3d/scripts/smoke_walk_math.mjs` § S3.

`offset_y` je Platzierung, `ground_offset_m` je Prop und `model_offset_y` je
Diorama wirken **unverändert** weiter (Entscheidung 4 des Plans) — nur messen
sie jetzt überall von derselben Null, und diese Null ist seit der Befundrunde
die unter dem Objekt statt die unter dem Pin. `layout.floor_offset_y` überlebt als
**reiner Feinjustage-Regler** eines einzelnen Raums (hebt, was IM Raum steht);
seine zwei alten Nebenjobs sind weg: es gleicht keinen zweiten Boden mehr aus,
und es ist **keine Wasserlinie** mehr — dafür gibt es `layout.water_level`
(§ A16.3).

**`floor_plan` — die Etage-0-Räume als Daten.** Additiv im Szenen-Payload, eine
Zeile je Raum auf Etage 0, in Rezept-Reihenfolge:

```jsonc
"floor_plan": [
  { "room_id": "hall",
    "polygon_world": [[-4,-4],[0,-4],[0,-1],[-4,-1]],   // SZENEN-Frame (m)
    "floor_kind": "wood",
    "closed": true },
  { "room_id": "pond", "polygon_world": [...], "floor_kind": "water",
    "closed": false, "water_level_effective": 8.0 }     // ABSOLUTES Welt-y
]
```

* `polygon_world` ist der Raumrumpf im **Szenen-Frame** (lokale Meter um den
  Anker-Pin) — tesselliert und gedreht, also Punkt für Punkt der Rumpf, den auch
  der Bake benutzt.
* `floor_kind` ist die Bodenart: `surfaces.floor`, sonst `"floor"` für einen
  GESCHLOSSENEN Raum und der **leere String** für eine Zone, die keine nennt
  (dort scheint das Gelände durch, und der Bake malt dort ebenfalls nichts).
* `closed` unterscheidet Raum von offener Zone (§ A5).
* `water_level_effective` steht nur auf einem Wasserboden und ist **die einzige
  absolute Welt-y-Zahl in diesem Payload**.
* **Keine Höhen sonst.** Raum-Spots, NPC-Plätze und Labels holen ihre Höhe aus
  dem Höhen-Sampler an genau dem Punkt, um den es geht.

Der Hof (`__ground__`, § A13a) steht nicht drin: er hat keinen Rumpf, er IST das
Grundstück. Etagen ≠ 0 stehen nicht drin: die haben Platten.

**Die Figuren-Leiter im Client — drei Sprossen, alle aus Daten:**

```
tileWalkY(tile, at) =
  1. declaredFloorAt(tile.declaredFloors, …)   ein Raum sagt seinen Boden an
  2. recipeFloorAt(tile.walkPlates, …)         eine DEKLARIERTE Etage (≠ 0)
  3. tile.center.y                             das Gelände
tileGroundY = standY(tileWalkY, heightAt(x, z))
```

Die MESH-Sprosse ist gelöscht, und mit ihr der ganze Strahlenapparat. Die
begehbare Fläche eines Flächenmodells IST die Zahl, die seine Spec deklariert
(`walk_y_world`); wo es keine deklariert, antwortet das Gelände, über das es
gezeichnet wurde. Der Strahl war nur ein Weg herauszufinden, welcher von ZWEI
Böden vorn liegt — es gibt einen. `plateCeiling` **bleibt** und gilt jetzt für
jedes `display` gleich: das ist die Etagen-Frage, und ein ungedeckelter
Plattengriff hübe eine Figur im Erdgeschoss auf die Platte darüber.

**Auf Etage 0 bekommt die LAUFENDE FIGUR keinen `WALK_CLEARANCE_M`** (Sprosse 3
antwortet blank): draußen läuft sie auf genau `heightAt`, und drinnen jetzt auf
ebendiesem Boden. Die Zugabe wird nur auf den beiden DEKLARIERTEN Sprossen
addiert, wo der Boden eine gezeichnete Fläche ist — und auf den Raum-SPOTS
(Mitte, Stellplätze, Sitz-/Liegepunkte), die eine Standmarke sind und keine
Bodenhöhe.

**Raum-Spots kommen aus dem Grundriss** (`scene/tiles.deriveRoomSpots`,
gefüttert aus `floor_plan`; die reinen Regeln in `client3d/src/game/ground.ts`):

* **Raum-Mitte** = Flächen-**Schwerpunkt** des gezeichneten Rumpfes
  (`polygonCentroid`, Shoelace — nicht der Eckenmittelwert, den eine mit zehn
  Punkten gezeichnete Wand gegen die gegenüberliegende zöge). Liegt der
  Schwerpunkt AUSSERHALB des Raums — bei einem L-Grundriss der Normalfall —,
  gewinnt der nächstgelegene Rasterpunkt.
* **Stellplätze** = ein 6 × 6-Raster über 0,78 der Raum-Umschließenden
  (`roomSpotGrid`) mit POLYGON-Test. Jeder Platz bekommt seine EIGENE Datenhöhe;
  `SPOT_FLAT_M` = 12 cm bleibt als Toleranz, gemessen gegen die Höhen-DATEN.
  Unter einem gebauten Raum ist sie konstruktionsbedingt wirkungslos (§ A16.4
  hobelt das Grundstück eben), bei einer offenen Zone hält sie die Traube vom
  Hang, den die Zone hinaufläuft.
* **Bodenhöhe je Raum** (`roomFloorWorldY`): die Deklaration des Payloads, wo es
  eine gibt — ein Dioramen-`walk_y_world`, eine Etagen-Platte, oder die
  `overlay.y` einer Zone auf einem Flächenmodell —, sonst der HÖHEN-SAMPLER an
  genau diesem Punkt.
* **Sitz-/Liegeflächen werden weiter GEMESSEN**, und das ist kein Widerspruch:
  eine Sitzhöhe ist eine Eigenschaft eines OBJEKTS und wird an der eigenen
  Bounding-Box des platzierten Props abgelesen. Nicht mehr gemessen wird der
  BODEN, gegen den sie beurteilt wird. Die Fenster sind für eine 1,70-m-Figur
  hergeleitet (`furnitureUse`): Sitzfläche 0,25…0,70 m über dem Boden, Liegefläche
  zusätzlich mindestens 1,6 × 0,7 m.
* **Tür-Referenz**: kein Strahl. `tile.roomDoors` kommt direkt aus `doorways[]`
  (Position **und** `base_y`).
* **Marker** werden nur noch um die Differenz zwischen dem Boden des RAUMS und
  dem Etagen-Datum verschoben, gegen das der Server sie komponiert hat. Auf einem
  gebauten Erdgeschoss ist diese Differenz 0 und die Schleife ändert nichts —
  genau der Punkt. `fixed`-Marker (Prop-Marker) bleiben unberührt.

**Das szenen-eigene 17 × 17-Relief ist gelöscht** (Entscheidung 1 des Plans,
ohne Ersatzschiene): `scene_recipe.compose_terrain`/`terrain_frame`, der
`terrain`-Block im Payload, `map3d.relief`, `layout.relief_flat`,
`relief.scene_ground_lift`/`has_relief`/`ground_lift_at` und die
Relief-Zweige von `scatter_curves`. **Lokales Relief autoriert man über
Höhenflächen der Karte.** Was an ihre Stelle tritt, ist überall dieselbe Zeile:
`world_geometry.ground_y`. Die Auflösungsregel „die innerste ENTHALTENDE
Location mit einem Feld gewinnt" ist damit weg — es gibt EIN Feld, und wer es
formt, entscheidet der Bake einmal (`draws_built_floor`).
`shared/world_dev_schemas` darf `flat` weiter nennen; es erzeugt kein Feld mehr.

**Admin.** `FloorPlanPreview` zeichnet die Etage-0-Böden als flache texturierte
Polygone auf `y = 0` aus `floor_plan`; eine LEERE Art zeichnet **nichts**.
Etagen ≠ 0 behalten ihre Platten. Die Bühnenplatte liegt auf 0, schreibt keine
Tiefe und wird zuerst gezeichnet — sie ist eine Messhilfe, kein Boden.
`PlanSidePanel` trägt für Etage-0-Räume „Edge transition (m)"
(`layout.edge_blend_m`, 0…8, Default 0 — **0 ist ein Wert**) und für einen
Wasser-Boden „Water level (m)" (optional, leer = der Bake entscheidet),
„Depth (m)" (0,2…20, Default 2,0) und „Shore ramp (m)" (0…20, Default 3,0). Ob
ein Boden Wasser ist, entscheidet die **Material-KLASSE** der Surface-Bibliothek
(`water`/`ice`) — nie der Name, nie die Farbe.

---

### A16.10 Die 2D-Karten schattieren das Relief

Spielerkarte (`frontend/src/player/MapPanel.tsx`) und Minimap des 3D-Clients
(`client3d/src/hud/Minimap.tsx`) legen dieselbe Schattierung über ihre
Terrain-Farben: `hillshadeImage()` aus `@anima/scene-render` — Normale aus dem
Höhen-Gradienten, Licht aus Nordwest (Azimut 315°, Höhe 45°), neutrales Grau
moduliert, Alpha proportional zur Hangneigung (maximal 0,35; **ebener Grund
schreibt Alpha 0**). Beide rufen mit `MAP_RELIEF_Z_FACTOR` = 3, der
kartografischen Überhöhung: die Quelle ist die **Übersicht** (eine Karte ist die
Fernsicht), und ohne Überhöhung bliebe ein 5-m-Hügel dort rund eine von 255
Stufen. Nachgeladen wird **nur bei Wechsel von `height_sig`**, über den ohnehin
laufenden Worldmap-Poll. Zeile 0 des Bildes ist die nördlichste Gitterlinie und
landet in beiden Projektionen oben, ohne Achsen-Spiegelung.

**Was hier NICHT passiert:** der Karten-EDITOR bleibt bewusst ohne Hillshade —
er zeigt Höhenflächen als eigene Ebene mit Zahl-Label
(`frontend/src/tabs/map/HeightLayer.tsx`), weil ein schattiertes Bild eine
zweite, hübschere Antwort auf „wie hoch ist es hier" wäre, die niemand mit der
Zahl vergleichen kann, die die Regeln benutzen.

**Nebel und Raycasts.** Nebel-Quads werden auf ~64 m gekachelt (`FOG_TILE_M`)
und hängen je Kachel auf `max(Höhe darin) + 5 cm`; **gekachelt wird nur, wo das
Gelände sich bewegt** — ein Schleier-Rechteck, unter dem die Spannweite des
Bodens unter `FOG_FLAT_EPS_M` = 0,25 m bleibt, bleibt EIN Quad. Eine Welt ohne
Relief kostet damit exakt so viele Draw Calls wie vor dem Relief.

---

### A16.11 Die Beweise — welcher Smoke zeigt was (§ B5a)

Numerische Verifikation, nie Screenshots. Jede Zahl wird im Docstring des
Skripts **von Hand aus der Spec hergeleitet**; das Skript misst nur, ob der Code
sie produziert.

**Server — die Höhenfunktion und ihre Stempel**

| Skript | was es herleitet |
|---|---|
| `scripts/smoke_height_bake.py` | die Pipeline: [1b] Wasser-Invariante über die ganze Fläche, [4] Reinheit über 2/4/8/16/32/64-m-Gitter (EXAKTE Gleichheit an allen gemeinsamen Punkten), [6] die `err[k]`-Schranke auf 513², [8] der Zonen-Wasser-Carve nach den Plateaus |
| `scripts/smoke_heightfield.py` | Rasterung, Rampe, Überlappung inkl. Senke, Sanitizer-Klemmen, Signatur/Store/`ground_y`, Ursprungs-Verankerung, Vergröbern, [8] die bilineare Handtabelle, [13] das Mikro-Relief (xorshift Schritt für Schritt, negative Lattice-Indizes, Null-Ring, oberste Art gegen `kind_at`), [14] Übersicht == Kacheln auf dem Kachel-Schritt, [14b] die 4-m-Übersicht gegen die Kacheln, [14d] die Kosten |
| `scripts/smoke_plateau_polygon.py` | der Auto-Plateau auf konkavem Umriss — samt roter Gegenprobe, dass ein gespeichertes `level_ground` nichts mehr stempelt |
| `scripts/smoke_slope_gate.py` | das Steilheits-Gate und die Ausnahme für **gebaute** Orte (`draws_built_floor`), plus die rote Gegenprobe „`natural_floor` steht in keinem Payload" |
| `scripts/smoke_nav_grid.py` | Routing: Steilheits-Tod je Zelle, Fußabdruck-/Öffnungs-Ausnahmen, Höhenstrafe |
| `scripts/smoke_world_geometry.py` | `ground_y` als die eine Lesung |
| `scripts/smoke_model_surface.py` | das Oberflächen-Raster (v6): **part 0** die Gründe eines Backens, **part 1** die Zellenregel Knoten für Knoten an einer rein in Python geschriebenen Mini-GLB (80/20/20/90 cm + `null`) samt beider Boxen, `extent_snapped` unter zwei Fixen und der Gültigkeitsprüfung, dazu der WELT-Schritt (`target_m` 20 → `s` 10 → `step` 0,025 Modell-Einheiten, 81×81 Knoten, 80/20/**20** cm an den verschobenen Indizes — die 0,6 Modell-Einheiten unter der Kante sind bei `s` 10 sechs WELT-Meter Luft, also gewinnt die Basis; `target_m` 0 lässt 9×9 @ 0,25; die `max_cells`-Kappe greift NACH der Umrechnung — mit 100 Zellen verdoppelt sich 0,025 bis auf 0,4 Modell-Einheiten = 4 m Welt (6×6); eine v2-Datei liest sich als `stale`), dazu die **Hütte** (geschlossene Hülle, `target_m` 5 → `s` 2: innen und in der Tür antwortet der BODEN, auf der Wand und unter dem Dachüberstand die Dachoberkante) und ihre Gegenprobe mit 0,5 m Innenhöhe (zu niedrig → Dach), **part 2** die Sampler-Handtabelle |
| `scripts/smoke_play_pos.py` **[23]** | die Höhensperre auf demselben Raster: 0,3-m-Kiste erlaubt, 0,8-m-Block `too_steep` (als STUFE), wieder herunter erlaubt — dazu Etage-0-Filter, Anker-Lift, TTL-Cache und der defekte Sidecar, der auf Boden zurückfällt statt zu 500 |
| `scripts/smoke_improvement_types.py` **[14]/[15]** | der Bestands-Bake: Kandidaten und `is_done` über `read_surface`, der bei APPLY neu gelesene Fix, `busy` = `CandidateBusy` (verbraucht keinen Versuch) gegen den echten Fehlschlag, das Cache-Vergessen je Subject |
| `scripts/smoke_water_meta.mjs` | was die Admin-UI über Wasser liest und zeichnet: die Leser aus dem freien `meta` (Zahlen, Profil, gewrappte Fließrichtung, Bett-Art), das EINE Prädikat `meta.water` gegen Namen und Material-Klasse, Art-Vorgabe vs. Flächen-Überschreibung, die Yaw-Konvention des Pfeils samt Flächen-Schwerpunkt (W3), und der `map_water`-Verweis des Lageplans |
| `scripts/smoke_height_math.mjs` | die Autorierungs-Arithmetik des Karten-Editors (`heightMath.ts`) |

**Server — Material und Szene**

| Skript | was es herleitet |
|---|---|
| `scripts/smoke_terrain_layers.py` | [1] Raster == `rank_at` == `kind_at` an 500 Gitterproben, die sd-Quantisierung, der Endpunkt in beiden Modi, `uniform`, `waters` |
| `scripts/smoke_terrain_types.py` [9] | die Sanitizer der Katalog-Felder (`edge_blend_m` mit 0 als WERT, Relief-Amplitude/Welle) |
| `scripts/smoke_scene_recipe.py` | die Rezept-Zahlen der neuen Leiter, die roten Gegenproben (0,08 / 0,09 / 0,10 dürfen auf Etage 0 in keinem `top_y`/`base_y`/`bottom_y` auftauchen), `floor_plan`, `draws_built_floor`; **[4a]** der Wandsaum — beide Grenzen des 0,14-Maßes von Hand, die feste Oberkante, der ungesäumte Sturz, die ungesäumte Türschwelle und die unbewegte deklarierte Etage |
| `scripts/smoke_scene_recipe.py` **[7g]/[7h]** | das Oberflächen-Raster am Spec (v6): `code_version` **8** (siehe [7i]), der Block unverändert am Raum-Spec, `walkable` + Block nur am getaggten Prop, die bewegte Signatur — und je Kopie eines mehrvariantigen Props das Raster IHRER Store-Variante |
| `scripts/smoke_terrain_query.py` / `scripts/smoke_terrain_areas.py` | `kind_at` und die Flächen-Speicherung, aus der die Priorität kommt |

**Client — Höhe, Schnitt, Wasser, Szene**

| Skript | was es herleitet |
|---|---|
| `client3d/scripts/smoke_terrain_lod.mjs` | CDLOD: Stufen-Ranges, Morph-Fenster, `err`-Auswahl gegen `MAX_PIXEL_ERROR`, `h_gpu == h_cpu`, der analytische Klick-Marsch |
| `client3d/scripts/smoke_world_height.mjs` | EINE Lesung statt zweier — die Zahlen, die der zweite Term nicht mehr erzeugt |
| `client3d/scripts/smoke_height_tiles.mjs` | die Ladepolitik: Wunschmenge im 560-m-Radius, Batching, Cache-Kappe |
| `client3d/scripts/smoke_relief_math.mjs` | das Feld-Lesen und die zwei Reiselinien-Ableitungen (auf Weltfeld + Reiselinie zurückgeschnitten) |
| `client3d/scripts/smoke_layer_cut.mjs` | die Schnitt-Arithmetik (sd-Interpolation, `b = 0`-Kante, `fwidth`-AA), EIN Spiegel-Bauer von beiden Quellen gespeist, und die **Löschungs-Prüfung**: die gestrichenen Drape-/Platten-Namen kommen in den Quellen nicht mehr vor, `rebuildAreas` setzt **gar keine** `position.y` |
| `client3d/scripts/smoke_water_plane.mjs` | [3] die E1-Invariante unabhängig nachgerechnet samt Gegenprobe, die Ufer-Alpha-Stützstellen, [5] die Zonen-Wasser unter einem Punkt (Vorrang vor gemalten Flächen, Letzter-gewinnt, `null` wird nie 0, der Schwimmer am Zonen-Spiegel) |
| `client3d/scripts/smoke_walk_math.mjs` | die Figuren-Leiter, die identische Kette gebaut == natürlich, die roten Gegenproben auf 0,10 / 0,09 / 0,01, und dass `walkCeiling`/`acceptsWalkHit`/`groundLift` nicht mehr existieren; **§ S** `storeyGroundLift` — die Mondscheinsee-Zahlen von Hand, die ebene Bühne der Admin-Vorschau, und die drei Nicht-Heber (deklarierte Etage, Gebäudemodell, fehlender Sampler) |
| `client3d/scripts/smoke_surface_math.mjs` | `surfaceHeightAt`/`highestSurfaceAt` gegen DIESELBE Handtabelle wie der Python-Zwilling (`smoke_model_surface.py` part 2), Zahl für Zahl — Knotenwert, Bilinear-Mitte, `null`-Nachbar, Punkt außerhalb, Yaw, `measure xyz`, `lift`, höchstes gewinnt |
| `client3d/scripts/smoke_room_spots.mjs` | Schwerpunkt (inkl. L-Raum, dessen Schwerpunkt draußen liegt), Raster + Polygon-Filter, Flachheits-Tor, Möbel-Fenster, Zonen-Wasser-Auswahl |
| `client3d/scripts/smoke_undergrowth.mjs` § J | der Unterwuchs-Filter gegen die Maske, mit Gegenprobe |
| `client3d/scripts/smoke_natural_ground.mjs` | die drei Naturstufen auf dem KOMPONIERTEN Ergebnis |
| `client3d/scripts/smoke_hillshade.mjs` | die Schattierungs-Tabelle samt Überhöhung und den roten Gegenproben |


## A17. Die Fernkulisse — `backdrop` im Worldmap-Payload — neu 2026-08-14

**Reine Optik: der Server autoriert, der Renderer zeichnet.** Die Fernkulisse
ist ein Gebirgs-Schattenriss am Welthorizont — kein Kollisionskörper, keine
Höhe, kein Nav-Einfluss, nichts, wohin man laufen könnte. Wer die Ferne
sperren will, malt unpassierbares Gelände; die Kulisse schließt den Blick,
nicht den Weg. Sie reist im Worldmap-Poll mit, aus denselben Gründen wie die
beiden Laufgrenzen (§ A1.3): sie ist eine Welt-Einstellung, dieser Poll läuft
ohnehin, und sie wird **nie gefoggt** — eine Silhouette am Horizont ist von
überall sichtbar und verrät nichts über die Welt. **Fehlt der Schlüssel, ist
sie aus** (das ist auch, was ein älterer Server schickt): absent und
ausgeschaltet sind für den Client ein und derselbe Zustand, es gibt keinen
Default-Ring.

```jsonc
"backdrop": {
  "height_m": 120.0,                     // Kammhöhe in Welt-Metern
  "seed": 1,                             // uint32, Profil ist reine Funktion
  "arcs": [[157.5, 202.5]]               // fertige Winkelbereiche in Grad
}
```

**Die Bögen sind serverseitig fertig gerechnet** (`app/core/backdrop.py`). Die
Autorierung nennt Himmelsrichtungen (`game.backdrop_arc`, kommasepariert aus
{N, NE, E, SE, S, SW, W, NW}; leer = Vollring), der Client bekommt nur noch
Grad. Verbindlich ist der Figuren-Kompass dieses Vertrags (§ A1.8): **0 = Süd,
90 = Ost, 180 = Nord, 270 = West**, also Bodenrichtung
`(x, z) = (sin a, cos a)` bei x nach Osten und z nach Süden. Jedes Segment
deckt 45° zentriert auf seine Richtung ab (N = 180 ± 22,5 → `[157.5, 202.5]`),
benachbarte Segmente wachsen zu EINEM Bogen zusammen, und **ein Bogen wickelt
nicht um**: `0 ≤ start < 360` und `start < end ≤ start + 360`, ein über 0
laufender Lauf wird also als `[337.5, 382.5]` geliefert und nicht in zwei
Stücke zerlegt — der Renderer streicht nur von `start` nach `end`. Der
Vollring ist der eine Bogen `[0, 360]`. Die drei Zahlen sind validiert und
geklemmt: `height_m` auf [20; 300] (Default 120), `seed` auf uint32 (Default
1), Unbrauchbares fällt auf den Default zurück (Muster `relief.py`, ein
Warn-Log pro Einstellung). Autoriert wird in `/admin/settings → Game`
(`backdrop_enabled` / `backdrop_arc` / `backdrop_height_m` / `backdrop_seed`);
die Seite ist serverseitig gerendert, die FELDER erscheinen also erst nach
einem Server-Neustart — die WERTE wirken danach mit dem nächsten Poll.

**Verifikation:** `scripts/smoke_backdrop.py` (Kompass gegen die
Richtungsformel, die Handfälle "N" / "N,S" / "N,NE,NW" / Vollring / Junk, die
Klemmen und der Payload-Block; rote Gegenprobe mit der gespiegelten
Grad-Konvention 0 = Nord), Client-Seite in
`client3d/scripts/smoke_backdrop_math.mjs`.

---

# Teil B — Ziel-Vertrag v4: das Szenen-Rezept

Kern des Umbaus: EIN Endpoint liefert die komplette darstellbare Szene
einer Location als **fertige Primitive und Platzierungs-Specs**. Der
Client (und die Admin-Vorschau) besitzen danach genau ZWEI generische
Geometrie-Routinen — „Primitiv bauen" und „Modell platzieren" — und
keine einzige eigene Geometrie-Entscheidung mehr.

## B1. `GET /play/locations/{location_id}/scene`

*Stand E4 (abgeschlossen 2026-08-10): der Composer liefert **`k = 1`** und
`extent_m = plan_width_m` — jedes `_m`-Feld IST damit ein Welt-Meter
(§ A1.8). Die Felder `extent_m`, `k` und `storey_m` bleiben im Payload:
Konsumenten rechnen weiter mit dem GELIEFERTEN `k` (× 1 ist richtig), nie
mit einer eigenen Konstante — `extent_m` schon gar nicht, es ist jetzt so
groß wie die Location. **Beide Renderer sind nachgezogen** (E4 Task 3): der
3D-Client hat seinen eigenen zweiten Maßstab ausgebaut (Figuren-, Raum- und
Laufgeschwindigkeits-Faktoren gelöscht, `k` wird einmal pro Sitzung gegen 1
geprüft), Locations stehen auf `(pos_x, pos_z)` mit der Kante
`plan_width_m`, und der Yaw-Drehsinn ist überall der der Weltkarte.
`map3d.extent_m` ist auch als ADMIN-REGLER weg (E4 Task 7) — der Sanitizer
verwirft das Feld, es gibt keinen Schreiber mehr.*

```
{
  signature,                 # deckt map3d + alle Raum-Layouts + Modell-
                             # Metas + Prop-Sidecars der Location ab —
                             # dazu die aktuelle Jahreszeit als Token
                             # (E2c): Prop-Varianten und Boden-Texturen
                             # wechseln mit der Spielzeit, ohne dass ein
                             # gespeicherter Wert sich bewegt
  k, storey_m,               # abgeleitete Skalare (Welt-Einheiten)
  levels: [ { level, floor_y } ],
  style: { wall_color, floor_color, glass_color, glass_opacity, door_color,
           upper_wall_opacity, upper_floor_opacity, room_palette: [...],
           elevator_frame_color, elevator_pad_color, elevator_cabin_color,
           elevator_cabin_opacity, elevator_glass_opacity },
           # Editor-Overlays (Marker/Lineal) bleiben bewusst lokal —
           # Vorschau-AIDs, keine Vertragsgeometrie

  # --- fertige Primitive (Reihenfolge egal, alles Welt-Koordinaten) ---
  plates:  [ { level, outline: [[x,z],…], top_y, thickness,
               texture_kind?, opacity_role: "ground"|"upper",
               room_id? } ],
  walls:   [ { level, from: [x,z], to: [x,z], base_y, height, thickness,
               texture_kind?, glass?, leaf?, lintel?, opacity_role, room_id?,
               outward_normal: [nx,nz] } ],
                                           # lintel = das Stück ÜBER einer
                                           # begehbaren Öffnung (Nachtrag
                                           # 2026-08-25): wird gezeichnet wie
                                           # jede Wand, sperrt aber NICHTS im
                                           # Grundriss — wer 2D-Kollider aus
                                           # `walls` ableitet, überspringt es
                                           # leaf = das TÜRBLATT IN der
                                           # Öffnung (Nachtrag 2026-08-25):
                                           # dünn wie ein Glasband, opak in
                                           # `style.door_color`, aus dem
                                           # Fassaden-Culling ausgenommen wie
                                           # eine Scheibe — und ebenfalls kein
                                           # Kollider
  extras:  [ { kind: "elevator_shaft"|"elevator_pad"|"elevator_cabin"|…,
               … je Kind eine feste Primitiv-Form … } ],
                                           # stair_step (Nachtrag 2026-08-25):
                                           # eine MASSIVE Stufe, center+size
                                           # wie jeder extras-Kasten, dazu
                                           # `level` (die untere Etage) und
                                           # `stair` (Index des Laufs)
                                           # stair_pad: der Trigger am Fuß und
                                           # am Kopf des Laufs, `end`:
                                           # "foot"|"head", `level` = die
                                           # Etage, auf der er liegt — Oberkante
                                           # ist deren Boden, wie beim
                                           # elevator_pad

  # --- Modell-Platzierungen (eine Spec-Form für ALLES) ---
  models:  [ { role: "building"|"room"|"prop",
               id,
               variants,                   # {"full": url, "low": url} —
                                           # ETag-Endpoints je Auflösungs-
                                           # stufe (Nachtrag v5.3 Nr. 16);
                                           # fehlende Stufe fehlt, {} = kein
                                           # Mesh. Konsument: gewünschte
                                           # Stufe, sonst beste vorhandene
                                           # (pickVariant in
                                           # @anima/scene-render).
               room_id?, level,
               fix_euler: {x,y,z},         # 'YXZ', Grad — vor Messung
               yaw_deg,                    # Eltern-Rotation, +rad im Client
               max_m,                      # Ziel-Ausdehnung in WELT-Metern,
                                           # EIN Faktor auf alle drei Achsen
                                           # (v5 Nr. 2). Seit v6 Nr. 3 IMMER
                                           # eine deklarierte reale Breite —
                                           # Gebäude/Fläche: Sidecar width_m,
                                           # sonst die Boundary-Breite
                                           # (extent_m) plus width_estimated
               measure: "yawed_xz"|"xz"|"xyz",
                                           # woran gemessen wird: yawed_xz =
                                           # GEDREHTE Hülle (Gebäude), xz =
                                           # gefixte XZ-Seite (Dioramen),
                                           # xyz = größte Kante (Props).
                                           # Der Fix steckt gerundet drin
                                           # (v5.1 Nr. 4)
               width_estimated?,           # true = max_m ist nur der
                                           # Notbehelf (Boundary-/Rechteck-
                                           # Breite), die UI soll eichen
               anchor: [x,z], bottom_y,    # Welt; BBox-Unterkante & Zentrum
               clip_outline?,              # [[x,z],…] Welt — Renderer verwirft
                                           # Fragmente AUSSERHALB des Polygons
                                           # (Shader-Discard, beliebige/konkave
                                           # Hüllen; Schnittkanten bleiben offen
                                           # → DoubleSide). Opt-in pro Raum
                                           # (layout.clip_model); Punkte = die
                                           # Raum-Hülle, max. 32.
               cutouts?,                   # NUR Flächen-Locations
                                           # (map3d.area_model, 2026-07-27):
                                           # [[[x,z],…],…] Welt — Renderer
                                           # verwirft Fragmente INNERHALB
                                           # irgendeines Polygons (Union;
                                           # invertierter clip_outline-Test),
                                           # aber NUR solange die Innenansicht
                                           # aktiv ist — Fernsicht zeigt das
                                           # Modell intakt. Inhalt: Gebäude-
                                           # Grundriss als Ganzes + Umriss
                                           # jedes platzierten Indoor-Raums,
                                           # der nicht vollständig darin liegt.
                                           # Max. 16 Polygone × 32 Punkte;
                                           # Schnittkanten offen → DoubleSide.
                                           # Das Modell fadet bei diesen
                                           # Locations NIE.
               placeholder_dims? } ],      # dims-Box bei missing/has_model=false

  # --- Rezept-Vokabular pro Raum (PLAN-Fraktionen, für den 2D-Editor) ---
  rooms:   [ { room_id, level, always_visible,
               outline,                    # absolute Fraktionen des Quadrats
               openings,                   # normalisiert INKL. gespiegelter —
                                           # Ghost-Öffnungen kommen von HIER,
                                           # nie aus lokaler Spiegel-Logik
               overlay? } ],               # NUR Flächen-Locations: Outdoor-Raum
                                           # AUSSERHALB des Grundrisses = Zone
                                           # AUF dem Modell — {centre:[x,z],
                                           # rect:{x,z,w,d}, y}, alles Welt-
                                           # Meter, y = begehbare Modell-Höhe
                                           # (walk_y_world, sonst bottom_y).
                                           # Solche Räume haben KEINE Platten/
                                           # Wände im Payload; NPC-/Marker-/
                                           # Label-Positionen kommen von HIER.

  # --- Figuren & Marker ---
  figures: { base_height_m_world,          # = 1,70 (konstant seit E4)
             stand_clearance: 0.12 },      # Welt-Meter, Konstante
  markers: [ { room_id, id, group, label, capacity,
               at_world: [x,z], slots: [[x,z], …],   # Länge = capacity
               y_world, root_offset, facing?, tilt?, roll?,
               anchor?: [x,z],               # NUR Prop-Marker
               source: "room"|"prop" } ], # ALLE fertig in Welt-Koordinaten
                                           # id = Raum-Marker-ID bzw.
                                           # "<placement.id>/<marker.id>";
                                           # group = Platz-Typ des Posen-
                                           # Katalogs (groups); label =
                                           # Platzierungs-Label, sonst Prop-
                                           # Name, sonst Gruppen-Label;
                                           # root_offset =
                                           # groups[group].root_drop × 1,70;
                                           # Slots quer zur Blickrichtung,
                                           # Kapazität 1 ⇒ slots == [at_world]
                                           # (Nachtrag 2026-08-28, v7);
                                           # anchor = Anker SEINER Platzierung,
                                           # dieselbe Zahl wie models[].anchor
                                           # (Nachtrag 2026-08-28): der Punkt,
                                           # an dem die Gelände-Hebung § A16.9
                                           # abgetastet wird (EIN Prop, EIN
                                           # Boden) UND die einzige Verbindung
                                           # Marker → Mesh — models[].id ist
                                           # die PROP-ID und gilt für jede
                                           # Kopie. Fehlt am Raum-Marker.

  # --- Türschwellen & Befunde (2026-08-05) ---
  doorways: [ { level, at_world: [x,z], along: [ux,uz], type, width_m,
                height_m, base_y, rooms: [room_id, …], outside } ],
                                           # IMMER da, leer = keine Tür
                                           # base_y = STEH-Höhe der Raumseite
                                           # height_m = lichte Höhe; darüber
                                           # steht der Sturz als eigener
                                           # `walls`-Eintrag mit `lintel`
                                           # type = "door" | "passage"; eine
                                           # `door` hat ein Blatt im Loch
                                           # (`walls`-Eintrag mit `leaf`)
  problems: [ { kind, location_id?, room_id?, message } ],
                                           # IMMER da, leer = alles sauber
  outdoor_rooms: [ room_id, … ]
}
```

**`doorways[]` — jede begehbare Schwelle der Location als fertiges
Primitiv** (`plan-betreten-und-tueren.md` § 4.1). Eine Schwelle ist EXAKT die
Lücke, die eine Öffnung aus einer Wand schneidet: dieselbe Quelle, dieselbe
Klemmung wie das Wand-Splitting (`scene_recipe._room_wall_edges`), keine
zweite Ableitung.

- **Konsumentenregel: nichts nachrechnen.** `width_m` ist die LICHTE Breite
  in Welt-Metern NACH der Kantenklemmung — nicht die autorierte `width_m`,
  die noch jemand klemmen müsste; `at_world` ist die Mitte dieser lichten Lücke,
  `along` die Einheitsrichtung der Wand (die Schwelle läuft ENTLANG davon).
  `height_m` ist genauso die LICHTE Höhe nach derselben Klemmung gegen die
  Wand (Nachtrag 2026-08-25): `base_y + height_m` ist die Unterkante des
  Sturzes, den der Composer als eigenen `walls`-Eintrag mit `lintel` liefert.
- **`base_y` IST die Steh-Höhe der Raumseite** (Befund 2026-08-16,
  schwebende Schwellen). Der Server rechnet sie: wo das Diorama eines
  angrenzenden Raums seine begehbare Fläche DEKLARIERT (Admin-Dial `walk_y`,
  aufgelöst als `walk_y_world` am Modell-Spec), ist das die Steh-Höhe dieses
  Raums, sonst der Fuß genau der Wand, zu der die Lücke gehört. Grenzt die Tür
  an ZWEI Räume, gewinnt die HÖHERE Steh-Höhe — man tritt ÜBER eine Schwelle,
  nie hinein. Eine Außentür hat nur die Raumseite; die Geländeseite decken die
  Grenz-Marken (`boundary_openings`). Die Regel steht als reine Funktion in
  `scene_recipe.threshold_base_y` und ist in `scripts/smoke_scene_recipe.py`
  [3e] von Hand nachgerechnet.
  **Konsumenten heben NICHT nach:** die Zahl ist ein Kachel-Meter wie jede
  andere im Payload, gehört also in den Kachel-Rahmen (die Schwellen-Quads
  hängen dort, wo auch die Wände hängen) plus höchstens einen konstanten
  Zeichen-Offset gegen Z-Fighting. Der 3D-Client hatte die Höhe gegen seine
  eigenen abgetasteten Raumböden gehoben und dabei Kachel- mit Welt-Metern
  vermischt — Ergebnis: jede Schwelle schwebte 10–15 cm, auf einer Kachel mit
  Plateau beliebig weit.
- **Eine Lücke in der Wand = EIN Eintrag.** Zwei Kandidaten sind dasselbe
  Loch, wenn drei geometrische Fragen zugleich mit Ja beantwortet werden:
  gleiche Wand-RICHTUNG (zuerst — zwei in dieselbe Ecke geklemmte Türen
  liegen null Meter auseinander und trotzdem auf zwei Wänden), gleiche
  Wand-LINIE (die beiden Wandflächen höchstens `SHARE_TOL_M` Meter
  auseinander, plus die Rundung eines gespiegelten `at`), und geklemmte
  Spannen, die sich auf dieser Linie wirklich TREFFEN. So verschmelzen die
  gespiegelte Kopie des Nachbarn, eine von beiden Räumen gezeichnete
  Trennwand-Tür und dieselbe Tür doppelt im selben Raum. Die breitere Spanne
  gewinnt die Geometrie und den ersten Platz: **`rooms[0]` besitzt immer die
  Wand, aus der der Eintrag geschnitten wurde.**
- **`outside` ist GEOMETRIE, kein Autorentext:** nach der Deduplizierung
  heißt genau ein Raum, dass keine zweite Raumwand an dieser Lücke steht —
  sie führt also aus dem Gebäude, auf die Grundfläche. Eine unbeschriftete
  Tür ist damit eine richtige Außentür, kein Durchgang ins Nichts. Die
  GRUNDFLÄCHE steht nie in `rooms`: sie hat keine Wände, und `outside` sagt
  es bereits.
- Ein Fenster ist kein Weg hinaus, ein Raum ohne Hülle (Outdoor-Zone,
  `no_walls`, entartete Kontur) hat keine Schwelle, und die Reihenfolge ist
  deterministisch (Etage, Position, Räume) — Konsumenten diffen ganze
  Payloads.

**`problems[]` — Befunde statt stiller Reparatur** (§ 4.3). Der Composer
stellt nur fest; **Floor-Plan-Editor und 3D-Client zeigen es an, mehr nicht**
— keiner leitet die Regel nach, keiner erfindet eine Reparatur. `kind` ist
der stabile Schlüssel, `message` der englische Server-Satz (eine Oberfläche
darf einen `kind`, den sie kennt, übersetzen und fällt sonst auf den Text
zurück; Zahlen stehen NIE im `message`, sondern in eigenen Feldern, weil der
Satz als Ganzes übersetzt wird). Heute gibt es drei:

- **`no_building_entrance`** — die Location hat eine Kontur, mindestens ein
  Raum MIT HÜLLE steht auf Etage 0 (eine Kontur über lauter
  Outdoor-/`no_walls`-Räumen ist kein Gebäude, dort könnte der Autor gar keine
  Tür setzen), und **keine einzige** Türschwelle auf Etage 0 führt nach
  draußen. Dann kommt niemand hinein, und seit die Fallback-Tür weg ist
  (§ A6) verdeckt das auch nichts mehr.
- **`rooms_without_layout`** (Diagnose 2026-08-15) — die Location hat eine
  Kontur und Räume, aber **kein einziger** Raum liefert ein Recipe (Layout
  fehlt oder ist entartet). Ohne Recipe gibt es auch keine Hülle, also bleibt
  `shell_levels` leer und `no_building_entrance` schweigt: die gezeichnete
  Kontur stünde still über gar nichts. `room_count` nennt die Zahl der Räume;
  der GROUND-Raum zählt nie mit — weder als Raum noch mit seinem Rezept: ein
  möblierter Hof (§ A13a) ist kein betretbarer Raum und darf den Befund nicht
  verstummen lassen.
- **`openings_without_walls`** (Diagnose 2026-08-15) — mindestens ein Raum hat
  Öffnungen im Layout, bekommt aber wegen `no_walls` (bzw. Outdoor
  `always_visible`) gar keine Wände: Tür, Fenster, Glas und Schwelle
  entstehen nirgends, während die 2D-Planzeichnung sie weiter zeigt. Ein
  wandloser Raum OHNE Öffnungen ist erlaubt (offene Zone, Pavillon) und
  bleibt still — nur die Kombination meldet sich, einmal pro Location mit
  `room_count` der betroffenen Räume.

**Damit wandern in den Server:** Wand-Splitting um Öffnungen inkl.
Fenster-Brüstung/-Sturz/Glas UND Tür-Sturz als eigene `walls`-Einträge
(Nachtrag 2026-08-25), Türlücken der
Außenkontur (aus den Schwellen projiziert, § A6), Spiegelungen,
Fahrstuhl-Primitive, Etagenplatten, Raum-Platten, alle Konstanten
(0,07 / 0,14 / 0,96 / 0,92 / 0,12 / < 0,06 /
max(0,6; storey−0,15)), Farben und Opacities (`style`),
Marker-Kompositionen und Türschwellen in Weltkoordinaten, Figuren-Maßstab.

**Was der Client noch tut:** GLB/FBX laden, BBox messen, die EINE
place()-Routine (§ B2) ausführen, Primitive als Box/ExtrudeGeometry
bauen, Texturen kacheln. Dazu weiterhin alles Sicht-/Interaktions-
Zustandliche: Kamera, LOD/Fades, Etagen-Umschalter (per `opacity_role`
und `level` gesteuert), Kamera-Culling (`outward_normal` liegt bei),
Labels, Pathfinding, Tag/Nacht, Terrain-Blends, Animations-Retargeting.

## B2. Die EINE Platzierungs-Routine

```
place(mesh, spec):
  1. fix_euler auf 90° GERUNDET anwenden ('YXZ'), BBox messen (v5.1 Nr. 4:
     gemessen wird gerundet, gezeichnet mit dem echten Fix)
  2. EIN Faktor auf alle drei Achsen: s = max_m / gemessene Ausdehnung
     measure "xyz":       max(B_x, B_y, B_z) der gefixten Box (Props)
     measure "xz":        max(B_x, B_z) der gefixten Box (Dioramen)
     measure "yawed_xz":  max(B_x, B_z) der GEYAWTEN Box (Gebäude/Fläche —
                          erst Schritt 3, dann messen: ein schräg
                          gestelltes Haus soll auf sein Grundstück passen)
     `fit_box`, `tile_fit`, `scale_axes` und jede achsengetrennte
     Skalierung sind ersatzlos weg (v5 Nr. 2 / v6 Nr. 3).
  3. Objekt auf seine EIGENE Mitte hängen: BBox mit dem ECHTEN Fix, aber
     OHNE Yaw messen, Mittelpunkt in den Ursprung — dann
     rotation.y = +rad(yaw_deg) als Eltern-Rotation, die das Objekt um
     genau diesen Punkt dreht.
     ✔ Seit **E4** (2026-08-09, Task 3): verbindlicher Drehsinn ist die
     Weltkarten-Konvention (§ A1.1), das frühere Minus ist in allen
     Renderstellen gekippt (§ A1.8). Der Server liefert `yaw_deg`
     unverändert. `markers[].facing` bleibt unberührt (Kompass, § A1.8),
     ebenso der hergeleitete Wand-Yaw in `primitives.ts`.
  4. Aufhängepunkt = anchor; Unterkante der Ergebnis-BBox = bottom_y
     (die Höhe ist yaw-unabhängig, also weiterhin am Ergebnis gemessen)
```

**Revision 2026-08-20 zu Schritt 3/4: gemessen wird VOR dem Yaw.** Bis dahin
lautete Schritt 4 „Ergebnis-BBox messen → XZ-Zentrum = anchor", also wurde die
FERTIGE, gedrehte Hülle mittig auf den Anker gesetzt. Damit hing die Position
eines Objekts an seinem Winkel: gemessen an den Meshes im Feld rutschte das
Ecksofa bei Yaw 45° um **0,50 m**, die Kabelzug-Station um 0,33 m, das
King-Size-Bett um 0,12 m — und bei Yaw 90° wieder auf null zurück, weil dort
beide Boxen dieselbe sind. Ein Anker soll sagen, WO das Objekt steht; drehen
soll es an Ort und Stelle drehen.

Der zweite, schwerere Grund: das alte Datum ist eines, das der SERVER nicht
nachrechnen kann. Er kennt vom Prop nur dessen `bbox` — nie die gedrehte Hülle
des echten Meshes. Die **Prop-Marker** (§ A4) werden aber serverseitig fertig
komponiert und auf genau diesen Anker addiert, also landete jeder Sitz- und
Liegeplatz eines schräg gestellten Props um exakt diese Differenz neben seinem
Prop (User-Befund: die Figur sitzt in der Grundriss-Vorschau woanders als der
Marker im Props-Tab steht). Mit dem Yaw um die eigene Mitte rechnen beide
Enden dieselbe Zahl: die Mitte einer Box IST rotations-kovariant.

Unberührt bleibt das GRÖSSEN-Gesetz: `measure` sagt weiter, worauf gemessen
wird, `yawed_xz` misst weiter die GEYAWTE Hülle (ein schräg gestelltes Haus
soll auf sein Grundstück passen) — das ist die Skalierung, nicht der Sitz.
`verify` (§ B5a) prüft `anchor` achsenparallel weiter an der Welt-BBox-Mitte
und diagonal am Aufhängepunkt der platzierten Gruppe.

Ersetzt die früheren drei Spezialketten vollständig (§ A2 führt nur noch
Diorama und Props als Legacy) — Gebäude, Diorama
und Props unterscheiden sich nur noch in den vom SERVER gelieferten
Spec-Werten, nicht im Code: `measure` sagt, WORAUF gemessen wird, `max_m`,
worauf skaliert wird. Beides ist seit v6 Nr. 3 für alle drei dasselbe
Gesetz — eine deklarierte reale Breite.

## B2a. Größenabgleich Diorama ↔ Props ↔ Figuren — EIN Maßstabsgesetz

Befund (2026-07-24): Dioramen skalieren per Rechteck-Einpassung, Props
und Figuren per reale Meter (× k; k = 1 seit E4). Konsistent ist das nur,
solange der Editor das Raum-Rechteck auf `width_m / plan_width_m` hält — zur
Renderzeit erzwingt das niemand; frei gezogene/alte Räume driften, und
seit Dioramen, Props und NPCs im SELBEN Raum stehen, fällt das sofort
auf (Diorama-Sofa ≠ Prop-Stuhl ≠ Figur).

**Neue Regel (v4): Das Diorama skaliert wie ein Prop.**

- `width_m` deklariert → `max_m = width_m`,
  `measure: "xz"` (width_m ist die größte XZ-Seite; die Höhe folgt
  uniform). Das Raum-RECHTECK hat damit KEINEN Einfluss mehr auf den
  Diorama-Maßstab — es bleibt Grundriss-Fläche für Platte/Wände/
  Begehbarkeit. Anker/Erdung unverändert (`model_at`,
  Etagenboden + 0,12 + `model_offset_y`).
- Ohne `width_m` → Fallback: die reale Breite des Raum-Rechtecks steht ein
  und die Spec sagt es (`width_estimated`), damit die UI nach einer
  Kalibrierung fragen kann statt still nach einem anderen Gesetz zu
  skalieren.
- Der Editor hält weiterhin (v3) die lange Rechteck-Seite auf
  `width_m / plan_width_m` — jetzt nur noch als AID, damit Platte/Hülle
  optisch mit der Diorama-Kante abschließen; ein Überstehen des
  real-size-Dioramas über sein Rechteck ist legitim und wird über
  `width_m`/`model_at` justiert, nicht über das Rechteck.
- Damit gilt raumübergreifend EIN Gesetz: **alles in echten Metern** (seit
  E4 ohne jeden Faktor) — Dioramen (`width_m`), Props (`dims`), Figuren
  (1,70 m + `height_cm`), Öffnungen (`width_m`/`sill_m`/`height_m`),
  Fahrstuhl. **Seit v6 Nr. 3 gilt es auch für die Gebäude-/Flächen-Hülle**:
  auch sie trägt eine eigene Realgröße (`width_m`, gemessen `yawed_xz`) und
  füllt nur noch dann das Bezugsquadrat, wenn keine erklärt ist — die
  frühere Ausnahme „`extent_m × size`" ist gestrichen.
- **Kalibrierung im Game-Admin:** eine Vergleichsfigur (fix 1,70 m,
  skaliert NIE mit) wird IN das Diorama gestellt; der Admin stellt
  `width_m` ein, bis die Möbel zur Figur passen, und `walk_y`, bis sie
  auf dem sichtbaren Boden steht. `width_m` ist damit nicht mehr „am
  Quellbild geschätzt", sondern an der Figur geeicht — die Genauigkeit
  von Props/Markern in diesem Raum hängt direkt daran.

## B3. Draft-Vorschau für den Admin

```
POST /play/scene-preview        # Body: location-Draft (map3d + rooms
                                # inkl. ungespeicherter layouts + terrain)
                                # → identischer Payload wie /scene
```

Gleicher Composer, keine Persistenz. Damit konsumiert die
Game-Admin-Vorschau (`FloorPlanPreview`) dieselbe Vertragsfläche wie der
Client; `planGeometry.ts`-Duplikate (Spiegelung, Edge-Normalisierung) und
die Konstanten-Kopien entfallen ersatzlos.
`floorplan.html` des Clients bleibt Debug-Werkzeug und rendert dann
automatisch identisch.

## B4. Server-vermessene Meshes (Ausbaustufe)

Der Server vermisst jedes GLB einmal beim Ingest (Generierung/Upload)
und legt `bbox_raw` + `bbox_fixed` im Sidecar ab. Dann kann `/scene`
`scale_axes`/absolute Transformen fertig liefern und `place()` schrumpft
auf „Matrix anwenden". Assets ohne Vermessung (Bestand) laufen über die
Spec-Parameter aus § B2 — Koexistenz per Datenlage. (Erst nach B1–B3.)

## B5. Rollen ab v4

**Leitprinzip v4:** Jede Geometrie-Entscheidung existiert genau EINMAL —
im Backend. Beide Renderer konsumieren dieselben server-gerechneten Daten;
die Admin-Vorschau ist nicht länger „Referenz per Reimplementation",
sondern erster Konsument derselben Vertragsfläche. (Das war 2026-07-24 der
Grund für v4: die Geometrie-Ketten lagen damals dreifach — Backend,
Admin-Vorschau, 3D-Client — und jeder Drift-Bug jener Wochen kam daher.
Der Befund selbst ist mit `@anima/scene-render` und § B3 erledigt und mit
**E7** aus diesem Dokument entfernt; das Prinzip bleibt.)

- **Backend** = einzige Geometrie-Autorität (`room_recipe.py` wächst zum
  `scene_recipe`-Composer; Konstanten/Farben ziehen dorthin um).
- **Admin-Vorschau** = Konsument Nr. 1 (`/play/scene-preview`), Referenz
  nur noch fürs Sicht-Verhalten (Toggles, Editor-Overlays).
- **3D-Client** = Konsument Nr. 2 (`/play/locations/{id}/scene`), behält
  ausschließlich Sicht/Interaktion/Animation.
- `/play/rooms/{id}/recipe` bleibt während der Migration bestehen
  (Untermenge von `/scene`); danach Rückbau nach Absprache.

## B5a. Verifikation: Arithmetik statt Screenshots (User-Vorgabe 2026-07-24)

Screenshot-Vergleiche taugen nicht als Nachweis — weder für eine KI-Session
noch als Regressionsschutz. Verbindlich ab v4:

- **Das Szenen-Rezept ist das Soll.** Jeder Renderer besitzt einen
  Debug-/Verify-Modus, der NACH dem Aufbau für jedes platzierte Objekt
  und Primitiv die Welt-BBox misst und gegen die Spec difft
  (BBox-Unterkante = `bottom_y`, XZ-Zentrum = `anchor`, Ausdehnung =
  Zielbox/max_m; Wände/Platten gegen from/to/base_y/height). Toleranz
  ε = 0,01 Welt-Meter; Ausgabe als maschinenlesbare Tabelle
  (Konsole/JSON), Abweichungen einzeln mit Ist/Soll.
- **Befunde zwischen den Sessions werden als ZAHLEN gemeldet** (Objekt,
  Feld, Ist, Soll — wie die bisherigen Zahlenbeispiele Hörsaal/
  Mondscheinsee), nie als Bildbeschreibung. Screenshots sind nur noch
  für Menschen (Abnahme-Optik), nie Diskussionsgrundlage zwischen
  Sessions.
- Server-seitig sichert der Composer-Smoke dieselben Zahlen (Fixture →
  erwartete Segmente/Transformen hart geprüft).
- Perspektivisch (nach Block N, beschlossen): `place()` + Primitive-
  Builder als GETEILTES TS-Modul für Admin-Vorschau und Client — dann
  ist auch der letzte doppelte Code weg und der Verify-Modus kommt aus
  einer Quelle.

## B6. Divergenz-Fixliste (aus der Analyse 2026-07-24)

Stand **E7** (2026-08-13) — jede Zeile am Verbraucher nachgeprüft. Sieben von
acht sind zu; offen bleibt allein #3. Nr. 9 ist 2026-08-27 dazugekommen und
gleich zu (Nachtrag „Oberflächen-Raster (v6)").

| # | Befund | Stand |
|---|---|---|
| 1 | Figuren-Basishöhe Client 1,75 m vs. Vertrag 1,70 m | **Historisch, erledigt (E1/E4):** 1,70 m in Welt-Metern gilt überall (§ A1.1/§ A3), das `× k` ist mit E4 weg — und der Client steht auf 1,70 (`client3d/src/scene/figures.ts BASE_FIGURE_HEIGHT_M`, Payload-Default `1.7`) |
| 2 | „0,12 × k" in §2e der Rezept-Note | **Historisch, erledigt:** zurückgezogen — 0,12 Welt-Meter konstant (§ A3) |
| 3 | `activityToClipKind`-Keyword-Heuristik im Client | **Erledigt — gelöscht 2026-08-28, Task 13 (plan-posen-plaetze.md):** die Funktion ist aus `figures.ts` raus, `npcs.ts` steht bei leerem `activity_animation` auf `idle`; die Pose kommt aus dem Katalog, ein Marker nennt seit v7 keinen Clip mehr |
| 4 | README des Clients nennt `map-icon-2d` als Bodenquelle; `mapIconUrl()` tot | **Erledigt — aber die Diagnose war FALSCH (E7-Korrektur):** `mapIconUrl()` lebt und liefert das Footprint-Icon der Karte (`frontend/src/tabs/map/PlacementLayer.tsx:78`, Konsumenten `MapTab`, `KnownLocationsEditor`, `LocationEditor`). Nichts daran ist Dead Code, `map_image_2d`/`map_rotation_2d` bleiben ausdrücklich (§ A1.9). Weg ist nur die README-Zeile des Clients |
| 5 | `implementierung-3d-pipeline.md` nennt `/characters/{name}/model[/meta]` | **Erledigt:** `client3d/docs/implementierung-3d-pipeline.md:80` sagt heute selbst, dass es diese Routen NICHT gibt, und nennt `GET /characters/{name}/model3d` (JSON) |
| 6 | `placements[].model_url` | **Erledigt:** im Szenen-Payload existiert das Feld nicht mehr (`model_tiers`/`variants` statt dessen, v5-Kopf). `model_url` gibt es nur noch als Feld der Prop-BIBLIOTHEK (`app/core/props.py`) — anderer Namensraum, kein Rest |
| 7 | Diorama-Böden mit Löchern — begehbare Höhe nicht messbar | **Erledigt:** `walk_y` (Meter über Modell-Unterkante) ist Sidecar-Anker mit Admin-Regler; das Rezept rechnet ihn zu `walk_y_world` aus (`app/core/scene_recipe.py`) |
| 8 | Diorama-Maßstab (Rechteck-Fit) ≠ Prop-/Figuren-Maßstab (×k) im selben Raum | **Historisch, erledigt (E4):** § B2a — Diorama skaliert real-size über `width_m` (measure xz), Rechteck-Breite nur noch Fallback; bei `k = 1` sind „real-size" und „Welt-Maßstab" dasselbe. **Seit v6 Nr. 3 auf Location-Ebene gegenstandslos**: das Gebäude-/Flächen-Modell skaliert nach demselben Gesetz (`width_m`, measure `yawed_xz`), es gibt keinen Füllfaktor mehr |
| 9 | Mesh-Oberfläche nicht begehbar (Klippen, Props): die Figur läuft auf dem Land unter dem Diorama statt auf dessen Oberfläche | **Erledigt (v6, 2026-08-27):** ein server-gebackenes Höhenraster je Modell (`app/blender/scripts/heightgrid.py` → `<modell>.surface.json`), inline am Spec (`surface`, am Prop nur mit Tag `walkable`), EINE Sample-Funktion für beide Renderer (`packages/scene-render/src/surface.ts`) und ein zeilengleicher Python-Zwilling, mit dem der Server dasselbe Raster liest (`model_surface.stand_height_at` in `POST /play/pos`). Siehe Nachtrag „Oberflächen-Raster (v6)" |

## Nachtrag 2026-07-27: Eine Wand, ein Besitzer (Kontur vs. Raumhülle)

Wo eine INDOOR-Raumhülle kolinear auf der Gebäudekontur liegt (Toleranz
0,09 m ≈ Wanddicke + Spiel), liefert `/scene` dort KEIN Konturwand-Stück
mehr — die Raumwand besitzt die Strecke (sie trägt Textur und
Öffnungen). Outdoor-Räume lassen die Kontur unberührt. Befund-Anlass:
deckungsgleiche Wände z-fighteten, sobald eine Wand-Textur gesetzt war
(Haus von Kai, 27 Paare / 16,47 m doppelt — jetzt 0/0).

## Nachtrag 2026-08-19 (§ B2): Ein Prop, mehrere Modell-Varianten

Ein Prop trägt seit E2.3 nicht mehr ein Mesh, sondern eine **geordnete Liste
aktiver Modell-Varianten** — mehrere Meshes DESSELBEN Gegenstands. Ein
gestreuter Wald ist damit vier Kiefernsorten statt zwanzig Mal derselben
Kiefer. Obergrenze ist `image_generation.prop_variant_max` (Vorgabe 4).

**Payload (`models[]`, Rolle `prop`).** Zwei neue Felder, und sie stehen NUR
an einem Prop mit mehr als einer Variante:

| Feld | Bedeutung |
|---|---|
| `model_variants` | Eine Stufen-Karte (`{tier → url}`) je AKTIVER Variante MIT Mesh, in der Reihenfolge des Props. Jede Karte ist gebaut wie `variants` seit je (§ B1), plus `?variant=<i>` an der URL. |
| `variant` | Index in `model_variants` für DIESE Platzierung. Fehlt = 0. |

Zwei Indizes, die man nicht verwechseln darf: `variant` ist die **Position in
`model_variants`**, das `?variant=<i>` in der URL die **Ablage-Nummer der
Variante im Prop**. Schaltet der Admin Variante 1 ab, stehen im Payload noch
die Varianten 0 und 2 — Position 1 trägt dann `?variant=2`. Ein Renderer
rechnet mit Positionen und schickt URLs unverändert weiter; er leitet nie eine
URL aus einer Position ab.

`variants` bleibt, was es war: die Stufen-Karte der **primären** Variante,
also **`variants == model_variants[0]`**. Das ist kein Kompatibilitäts-Alias,
sondern der definierte Primär-Varianten-Vertrag — ein Konsument, der von
Varianten nichts weiß, rendert weiter genau das, was er vorher gerendert hat,
und die primäre Variante behält ihre bisherige URL ohne Query (`…/model` bzw.
`…/model?tier=low`), sodass kein Client-Cache durch das Feature entwertet
wird. Die primäre Variante ist die **erste AKTIVE** der Liste — nicht
zwangsläufig die zuerst erzeugte.

**Nachtrag 2026-08-20 (E2c) — JAHRESZEITEN.** Eine Variante darf die
Jahreszeiten nennen, die sie zeigt (`seasons` auf dem Prop-Sidecar, Namen aus
`game_seasons` der Welt, unabhängig von Groß-/Kleinschreibung gematcht).
**Wirksam aktiv = manuell aktiv UND (kein Tag ODER aktuelle Spiel-Jahreszeit
dabei)**; „aktiv" heißt ab hier überall dieses Wirksam-Aktiv
(`props._effective_indices` — EIN Tor, das Streuung, Platzierungen und
Welt-Props gemeinsam lesen). **Der Payload ändert seine FORM nicht:** es
kommen keine Felder dazu, es stehen nur andere Einträge in `model_variants`,
und die primäre Variante ist die erste wirksam aktive — die query-lose URL
folgt ihr mit (`/assets/props/<id>/model` liefert dieselbe Datei wie
`model_variants[0]`). Zwei Randregeln: ist KEINE Variante in der Saison, gilt
wieder der manuelle Satz (eine Platzierung wird nie zum Loch), und eine Welt
ohne Jahreszeiten ignoriert die Tags vollständig. Renderer bleiben dumm — sie
sehen nur eine andere Liste. Was sie sehen MÜSSEN, ist der Wechsel: die
Szenen-`signature` (§ B1) nimmt die aktuelle Jahreszeit als Token auf, und
`terrain_sig`/`world_props_sig` hashen ohnehin den angereicherten Block.

**Nachtrag 2026-08-24 — MASSE JE VARIANTE.** Eine Variante ist eine ganze
Fassung des Gegenstands, und Fassungen sind nicht gleich groß: der Setzling
neben der ausgewachsenen Kiefer, die niedrige neben der hohen Mauer. Eine
Variante darf deshalb `width_m` / `depth_m` / `height_m` selbst führen —
jeweils als **Überschreibung** des Prop-Wertes und nach demselben Gesetz wie
`seasons`: gespeichert wird nur, was etwas aussagt, ein fehlender Schlüssel
heißt „so groß wie das Prop". Geklemmt wird wie beim Prop-Feld (`(0, 100]`
Meter); Müll, 0 und negative Werte verlieren den Schlüssel.

Die **Auflösungsregel steht an EINER Stelle** (`props.variant_dims`): *die
eigene Zahl der Variante, sonst die des Props*. Der Prop-Datensatz behält seine
PROP-Maße — das ist, was das Admin-Formular bearbeitet und worüber die
Mesh-Proportionen verteilt werden —, und alles, was weiß, WELCHE Variante es
zeichnet, löst über diese eine Funktion auf: die Platzierung im Raum/Hof (auch
jede Streu-Kopie, über ihren aufgelösten `variant`-Index), das Welt-Prop
(`max_m`), die Boden-Box der Streu-Aussparung (§ A9b) und die Stapel-Regel
(„Teekanne auf den Tisch") für Ziel UND Unterlage. Wer keine Variante in der
Hand hält, bekommt die PRIMÄRE — wie bei jedem anderen unqualifizierten Zugriff
hier. Das betrifft genau einen Leser: die gemalte Terrain-Streu (§ A9,
`prop_height_m`), deren Instanzen erst im Client gesampelt werden und dort ihre
Variante ziehen; sie trägt die Höhe der primären Variante, so wie sie deren URL
trägt.

**Am Payload ändert sich keine Form.** Es sind dieselben Felder mit denselben
Bedeutungen, sie tragen nur die Zahlen der Variante statt die des Props —
Renderer bleiben dumm.

**Wer die Variante wählt: der Server. Wer sie ausführt: der Renderer.**
Der Index steht fertig in der Spec; kein Renderer würfelt und keiner rechnet
ihn nach. Für Streu-Kopien einer Platzierung (`scatter_count`/`scatter_seed`,
§ A4) lautet die EINE Formel

```
variant = (scatter_seed + Instanz-Index) mod Anzahl aktiver Varianten
```

(`app/core/props.py scatter_variant_index`, angewandt in
`app/core/room_recipe.py`, aufgelöst in `app/core/scene_recipe.py
_prop_models`). Beide Eingaben sind gespeicherte Zahlen, also steht derselbe
Baum nach jedem Neuladen wieder an derselben Stelle mit demselben Mesh — und
in Admin-Vorschau wie 3D-Client mit demselben. Eine einzeln gesetzte
Platzierung trägt ihren Index selbst (Editor-Bedienung folgt; heute 0).

Handrechnung zur Nachprüfung (§ B5a): 3 aktive Varianten, `scatter_seed = 7`,
Instanzen 0…5 → `(7+0…5) mod 3` = **1, 2, 0, 1, 2, 0**.

**Auflösung im Renderer.** Genau eine Routine, geteilt:
`pickModelVariant(spec, tier)` aus `@anima/scene-render` — erst die Karte mit
Index `variant` aus `model_variants`, dann die Stufe daraus mit dem
unveränderten `pickVariant`. Ohne `model_variants` ist das Zeichen für
Zeichen das alte `pickVariant(spec.variants, tier)`. Der Index wird MODULO
gerechnet, nicht geklemmt: die Variantenzahl bewegt sich, wenn der Admin ein
Mesh ergänzt oder löscht, und eine Platzierung darf davon nicht verschwinden.

**Ausliefern.** `GET /assets/props/{id}/model?variant=<i>&tier=<t>`.
Ohne `variant` die primäre Variante. Ein Index, für den das Prop keine
Variante hat, ist 404 — nie stillschweigend ein anderes Mesh.

**Nachtrag 2026-08-20: der GEMALTE Gelände-Scatter mischt jetzt auch.**
Er war als einziger ausgenommen, weil seine Instanzen client-seitig in einem
Kamera-Fenster entstehen — es gibt keine Server-Zeile je Kopie, an die ein
Index gehängt werden könnte. Die Zelle liefert ihn: der Seed **ist** stabil
(`scatterCellSeed(area, row, cx, cz)`, eine reine Funktion aus Fläche, Zeile
und Zellindex), und die laufende Nummer des KANDIDATEN in dieser Zelle
ebenfalls. Also gilt dieselbe Formel mit gehashtem Seed —

```
variant = ( FNV-1a(Zellen-Seed) + Kandidaten-Nummer ) mod Anzahl aktiver Varianten
```

— gerechnet im Sampler selbst (`@anima/scene-render` → `scatterVariantIndex`,
und `scatterSeedHash` ist genau der Zustand, aus dem `seededRandom` seinen
Strom startet). Der Server liefert am Streu-Eintrag die LISTE
(`model_variants`, § A9), der Client teilt die Punkte einer Zelle in einen
Eimer je Variante und baut **eine `InstancedMesh` je (Zeile, Variante)**
(`ground.ts buildScatter`). Der Kandidat und nicht der Überlebende wird
gezählt, damit eine Ablehnung wie überall in diesem Modul nur SUBTRAHIERT:
sonst wechselt jeder Baum hinter einem neu gesetzten Gebäude die Art. Bei
einer Variante ist alles Zeichen für Zeichen wie vorher — kein Payload-Feld,
kein zweites Mesh, `variant` steht nicht einmal an der Instanz.

Handrechnung zur Nachprüfung (§ B5a): `FNV-1a('A') = 3 289 118 412`, das ist
durch 3 teilbar, also gehen die Kandidaten 0…5 einer Zelle mit diesem Seed bei
3 Varianten als **0, 1, 2, 0, 1, 2** los; wird Kandidat 2 von einer
darübergemalten Fläche verworfen, bleiben **0, 1, 0, 1** — nicht 0, 1, 2, 0.
Vollständige Ableitung inklusive der Hash-Arithmetik in
`client3d/scripts/smoke_scatter_math.mjs` Abschnitt (N).

### Ergänzung 2026-08-20: Das Quellbild gehört der Variante

Eine Variante ist nicht nur ein Mesh, sondern eine ganze **Fassung des
Gegenstands** — und dazu gehört das Produktfoto, aus dem sie gemesht wurde.
Das Bild folgt deshalb demselben Gesetz wie die Meshes, über **denselben
gespeicherten Stamm-Suffix**:

| Variante | Mesh-Stamm | Quellbild |
|---|---|---|
| 0 (historisch) | `model` | `source.png` |
| weitere | `model-v<n>` | `source-v<n>.png` |

Der Name folgt dem **Stamm**, nicht der Listenposition — eine gelöschte
Variante in der Mitte benennt das Bild ihrer Nachbarin so wenig um wie deren
Meshes. Und wie bei den Meshes IST diese Benennung der Migrationsweg: ein
bestehendes Prop behält sein `source.png` unangetastet.

Damit ist alles am Bild variantenweise: **Erzeugen** (`image_only` rendert
genau die Variante, die der Admin offen hat), **Hochladen**, **Neu-Meshen**
(liest das Bild SEINER Variante), **Ausliefern** und **Löschen** — eine
gelöschte Variante nimmt ihr Bild mit, und ein wieder freigegebener Stamm
startet ohne Bild. Auch die Herkunft (Backend, Prompt, Negativ, Zeitpunkt)
liegt bei der Variante: der Basis-Stamm behält die Felder des Master-Records
(`backend_image` / `prompt` / `negative` / `source_generated_at`), jede
weitere Variante trägt sie unter `image` an ihrem Varianten-Eintrag.

Befund-Anlass: es gab EIN `source.png` je Prop. Jede weitere Erzeugung
überschrieb es, also verlor jede ältere Variante ihr Bild — und ein
Neu-Meshen dieser Variante machte ein Mesh aus dem **falschen** Bild.

**Ausliefern.** `GET /assets/props/{id}/source?variant=<i>`, mit `<i>` als
**Ablage-Nummer** wie bei `/model`. Ohne `variant` die primäre Variante, also
byte-genau die Datei, die diese URL immer schon geliefert hat — das ist kein
Alias, sondern derselbe Primär-Varianten-Vertrag wie beim Mesh. Ein Index,
für den das Prop keine Variante hat, ist 404.

**Hochladen.** `POST /world/props/{id}/variants/{i}/source` (Multipart,
`file`); unqualifiziert `POST /world/props/{id}/source` für die primäre
Variante. Das Bild wird als PNG mit höchstens 1024 px abgelegt, **Alpha
bleibt erhalten** — ein freigestelltes Bild ist außerhalb des
Objekts transparent, und ein plattgerechnetes Bild gäbe dem Mesher einen
Hintergrund zurück, den er gerade loswerden sollte.

Nachprüfbar in `scripts/smoke_prop_variants.py` (§ B5a, Abschnitte 10–14):
Handrechnung der Namen aus den Stämmen, ein Lauf in Variante 1 lässt
`source.png` byte-identisch, das Neu-Meshen bekommt `source-v2.png` gereicht.

### ~~Ergänzung 2026-08-20: Woher das Bild stammt (`origin`)~~ — ENTFALLEN 2026-08-21

Die Szenenkontext-Pipeline, die als einzige ein `origin` schrieb, ist ersatzlos
entfernt. `GET /world/props/{id}/variants` liefert je Variante nur noch die vier
Herkunftsfelder des Bildes (`backend`, `prompt`, `negative`, `generated_at`);
`origin` / `origin_location` / `origin_location_id` / `origin_ts` gibt es nicht mehr.

## Nachtrag 2026-08-20 (§ B1/B2): Dach-Modelle (`roof_only`)

Ein Gebäudemodell ERSETZT die Fernsicht-Hülle: sobald ein Servermodell
eintrifft, nimmt der Client seine aus den § B Primitiven gebaute Hülle weg
(`dropFarShell`), denn das Modell IST das Gebäude. Seit dem LLM-Blender-Dach
(`docs/llm-blender-models.md`) gibt es ein Gebäudemodell, für das das nicht
gilt: ein **parametrisch über den Umriss gebautes Dach**, ohne Wände. Als
normales Gebäudemodell abgelegt, würde es genau die Wände verstecken, auf die
es gehört.

**Ein Feld, am `models[]`-Spec der Rolle `building`:**

| Feld | Bedeutung |
|---|---|
| `roof_only` | `true` = das Modell ist NUR das Dach. Ein Renderer, der eine eigene Fernsicht-Hülle aus Platten und Wänden baut, LÄSST SIE STEHEN und setzt das Modell obendrauf. Fehlt/`false` = unverändert: das Modell ist das Gebäude und ersetzt die Hülle. |

Alles andere am Spec bleibt das eines Gebäudes — `display: "shell"`, dieselbe
`place()`-Routine (§ B2), dieselbe Maßgabe `measure: "yawed_xz"` mit
deklarierter `width_m`. Das Dach blendet beim Reinzoomen aus wie ein Dach, und
zwar GEMEINSAM mit der Hülle: beide liegen in `roofParts`/`roofMats`.

Drei Stellen im Client, mehr nicht (`client3d/src/scene/sceneRecipe.ts`):
`hasBuildingModel` zählt ein `roof_only`-Spec NICHT mit (sonst entstünde die
Hülle gar nicht erst), `applySceneBuilding` überspringt `dropFarShell` und
HÄNGT an `roofParts`/`roofMats` an statt sie zurückzusetzen, und der
Stufen-Tausch entsorgt nur die Material-Klone, die er wirklich ersetzt hat.
Die Label-Höhe misst Hülle + Dach zusammen.

Der Server setzt das Flag aus dem Sidecar des Modells
(`location_model3d` → `get_client_meta` → `scene_recipe._building_model`); es
entsteht ausschließlich beim Dach-Bau, nie beim Meshen eines Bildes.

## ~~Nachtrag 2026-08-20 (§ B1/B2): EIN Boden — Teile 1–3~~ — ERSETZT durch § A16

Die drei Teile („der Anker des Gebäudemodells und die Steh-Höhe", „EIN Datum —
der gezeichnete Boden der Etage", „die Natur zeichnet KEINE Platte") haben eine
Welt beschrieben, in der es auf Etage 0 eine Etagenplatte (0,08 / 0,14 dick),
Raumplatten (0,10), Zonenflächen (0,09 / 0,01), einen Kachel-Sockel
(`SOCLE_Y_M` 0,045), einen Backstop (`tiles.tilePlateY`, −0,05 / −0,13 / 0,04)
und ein Payload-Flag `natural_floor` gab. **Nichts davon existiert mehr** — die
Etage-0-Höhe ist `h_final`, das Etage-0-Material ist der Layer-Bake.

Was aus diesen Nachträgen WEITERGILT, steht in **§ A16.9**: der Anker eines
Gebäudemodells ist seine BEGEHBARE Fläche und nicht seine Unterkante
(`walk_y_world`, auf Etage 0 also schlicht `offset_y`); die Deklaration eines
Raums (`walk_y_world` eines Dioramas) wird ZUERST gefragt und schlägt jede
andere Sprosse; bei zwei Ansagen gewinnt die KLEINERE Hülle (v6 Nr. 6). Die
übrigen Zahlen und Tabellen von damals stehen in der Git-Historie (`8672c756`,
`47abc26b`, `8a44c891`).

## Nachtrag 2026-08-20 (§ B2/§ A9/§ A9a): Ein Prop steht überall gleich tief — `ground_offset_m`

Ein Prop trägt seit heute eine eigene **Höhe über dem Boden**: `ground_offset_m`
auf dem Prop-Sidecar, in Metern, negativ versenkt, positiv hebt an. Es ist eine
Eigenschaft des GEGENSTANDS, keine der Platzierung: ein Stamm ohne Wurzelteller,
eine Truhe ohne Bodenplatte, ein Findling, der zur Hälfte in der Erde steckt —
das gilt in jedem Raum, in jedem Hof, in jedem gemalten Wald und an jedem
einzeln gesetzten Punkt der Weltebene gleichermaßen. Vorher gab es dafür nur
`offset_y` je Platzierung, also dieselbe Zahl hundertmal getippt.

**Speicherung (Sidecar).** Ein Feld, eine Darstellung — dieselbe Regel wie bei
`sway_factor` (`app/core/props.py`), nur mit der Vorgabe am anderen Ende:

| Eingabe | gespeichert |
|---|---|
| `-0.2` | `-0.2` |
| `-0.207` | `-0.21` (auf Zentimeter gerundet — die Schrittweite des Reglers) |
| `-99` / `99` | `-5.0` / `5.0` (geklemmt, nie abgelehnt: ein Tippfehler kostet das Limit, nie den Datensatz) |
| `0`, `-0.004` | **kein Schlüssel** |
| `"junk"`, `""` | **kein Schlüssel** |

**ABWESENHEIT IST DIE AUSSAGE.** Ein gespeicherter `0.0` und ein fehlender
Schlüssel wären für jeden Leser dasselbe, also darf nur eines von beiden
existieren. Lesen ist so nachsichtig wie Schreiben streng: `ground_offset_of({NaN})`
ist 0,0, und der Admin-Datensatz (`get_prop`) meldet immer den WIRKSAMEN Wert.

**Die Rechnung, überall dieselbe.** Für JEDE Instanz eines Props:

```
Unterkante = automatische Basis  +  ground_offset_m  [ +  offset_y ]
```

Die automatische Basis bleibt, was sie war (Platte/Datum bzw. Gelände nach dem
Nachtrag 47abc26b), und `offset_y` bleibt, was es war: der additive **Trimm
EINER Instanz**. Beide werden je Pfad an GENAU EINER Stelle addiert:

| Pfad | Basis | wo addiert |
|---|---|---|
| Platzierung im Raum/Hof (auch Streu-Kopien) | Plattenoberkante + `PROP_CLEARANCE` (+ Relief-Probe) | `scene_recipe._prop_models` → `bottom_y`; das Rezept trägt den Wert je Platzierung (`room_recipe._carry_ground_offset`) |
| Prop-Marker derselben Platzierung | dieselbe | `scene_recipe`-Markerpfad (`y_world`) |
| Gemalte Terrain-Streu (§ A9) | `heightAt(x, z)` des Clients | `client3d/src/scene/ground.ts`, `scatterGroundOffset(entry.ground_offset_m)` |
| Welt-Props (§ A9a) | `heightAt(x, z)` des Clients | `client3d/src/scene/worldProps.ts`, `worldPropBottom()` |

**Payload-Gesetz (§ A9/§ A9a): fehlt = 0.** Genau wie `sway_factor` reist der
Wert nur mit, wenn er nicht die Vorgabe ist — auf der Streu-Zeile
(`GET /play/terrain`), auf der Welt-Prop-Zeile (`world_props` im
Worldmap-Payload) und auf der Rezept-Platzierung. Beides sind abgeleitete
Fakten über das PROP, nie gespeicherte Felder der Bemalung oder der Platzierung:
ein korrigierter Wert erreicht jeden Client beim nächsten Poll, ohne dass eine
Fläche oder eine Platzierung angefasst wird (die Signaturen bewegen sich mit).

**Marker reiten das Mesh.** Ein versenkter Stamm versenkt seinen Sitzplatz mit —
`y_world − bottom_y` bleibt die komponierte Markerhöhe. Das ist gewollt und
hier festgeschrieben: die Sitzfläche gehört zum Gegenstand, nicht zum Boden.

**Handrechnung (§ B5a).** Raum „a" des Rezept-Smokes, Plattenoberkante 0,10,
Prop-Abstand 0,01, komponierte Markerhöhe 0,30, Prop mit `ground_offset_m −0.20`:

```
bottom_y   = 0.10 + 0.01 − 0.20            = −0.09
Marker     = −0.09 + 0.30                  =  0.21     (Abstand bleibt 0,30)
mit offset_y +0.05:  bottom_y = −0.04,  Marker = 0.26
doppelt gezählt (die klassische Fehlerform) wäre bottom_y = −0.29
```

Belegt in `scripts/smoke_scene_recipe.py` [9a],
`scripts/smoke_terrain_areas.py` [15], `scripts/smoke_world_props.py`
[3], `client3d/scripts/smoke_scatter_math.mjs` (H8) und
`client3d/scripts/smoke_world_props.mjs` [2a] — jeweils mit rotem Gegenversuch.

**Bedienung.** Props-Tab → Prop → „Ground offset (m)". Der Regler bekommt seinen
Bezug mit (Nutzer-Vorgabe „Maße brauchen Bezug"): eine Seitenansicht mit
Bodenlinie, Metermaß, der 1,70-m-Figur (nie mitskaliert) und der Kiste des Props
in seinen echten Maßen; der Reglerweg folgt der Prop-Höhe (mindestens ±0,5 m,
höchstens das gespeicherte ±5 m), damit ein Schemel in seinen Zentimetern und
eine Tanne in ihren Metern eingestellt wird.

## ~~Nachträge 2026-08-21 (§ A16–§ A20): Ein Boden — E1 / E3 / E4 / E5a / E5b~~ — ZUSAMMENGEZOGEN in § A16

Die fünf Etappen-Nachträge — E1 die reine Höhenfunktion, E3 der Layer-Schnitt,
E4 der Wasserspiegel, E5a das Ende der Etage-0-Platten, E5b die Renderer aus
Daten — sind in Etappe E6 zu EINEM Kapitel zusammengezogen: **§ A16 „Ein
Boden"**. Dort steht der Stand als Gesetz statt als Etappen-Diff, samt der
Beweiskarte (§ A16.11), die sagt, welcher Smoke welche Zahl herleitet.

Die Etappen-Texte mit ihren Vorher/Nachher-Tabellen, ihren Zwischenzuständen
(„bis E4 zeichnet Wasser noch seine Drape", „bis E5 rendern Zonenplatten
weiter") und ihren Löschlisten stehen in der Git-Historie: `81a9bb3c` (E1),
`2f501d0e` (E2), `9062dbf9` (E3), `9e85bb18` (E4), `c9874527` (E5a),
`9b7a424d` (E5b), `67f776d0` (Zonen-Wasser im Schwimmen).

## Nachtrag 2026-08-21 (§ A16.3 / § A16.7 / § A16.8 / § B1): Ein Wasser-Gesetz — W1 (Server)

*Etappe W1 aus `development_instructions/plan-fliessgewaesser.md`. Dieser
Nachtrag **ersetzt** die Wasser-Aussagen von § A16.3 (die drei Zahlen, die
Zonen-Wasser-Stufe), die `waters`-Liste in § A16.7, den Satz „die Fläche ist
eben" in § A16.8 und die `zone_water_basis`-Erwähnung in der
`height_sig`-Zeile (§ A1.3). W2 (Client) und W3 (Admin-UI) folgen; bis W2
zeichnet der Client weiter EINE flache Platte — dafür fährt
`water_level_effective` unverändert mit.*

**DAS GESETZ, in vier Sätzen.** Wasser ist eine **ART**, kein Name und kein
Raum: `meta.water` am Terrain-Typ macht JEDE Art zur Wasser-Art, und die Art
trägt die Vorgaben `water_depth_m` (0,2…20, Default 2,0) und `shore_ramp_m`
(0…20, Default 3,0). Wasser ist eine **FLÄCHE auf der Karte**: eine gemalte
Fläche überschreibt die beiden Zahlen, setzt ihren Spiegel und wählt ihr Bett.
Der Spiegel ist ein **PROFIL**, keine Zahl: ohne Fließrichtung eine Konstante
(der See von bisher), mit einer eine entlang der Fließachse geneigte Ebene.
Und ein **RAUM hat kein Wasser mehr** — die fünfte Backstufe ist gelöscht.

### 1. Die Art trägt die Vorgaben, die Fläche überschreibt sie

| Feld | Wo | Typ | Bedeutung |
|---|---|---|---|
| `meta.water` | **Art** | `bool` | Diese Bodenart IST Wasser. **Das EINE Prädikat** (`terrain_types.is_water_kind`) — Layer-Tabelle, Bake, Sanitizer und Lageplan fragen dieses und kein zweites. Das frühere zweite Buch (die Material-KLASSE der Surface-Bibliothek für Raumböden) ist ersatzlos weg. |
| `meta.water_depth_m` | **Art** | 0,2…20 (2,0) | Vorgabe: wie tief das Bett unter dem Spiegel liegt, sobald die Uferrampe durch ist |
| `meta.shore_ramp_m` | **Art** | 0…20 (3,0) | Vorgabe: wie weit INNERHALB des Umrisses die volle Tiefe erreicht ist. **0 ist ein WERT** (das Becken) und überlebt einen Save, wie `edge_blend_m` |
| `meta.water_depth_m` / `meta.shore_ramp_m` | **Fläche** | dieselben Klemmen | Überschreiben die Vorgabe der Art. Fehlt der Schlüssel, antwortet die Art — deshalb wird ein unlesbarer Wert GELÖSCHT und nicht auf den Modul-Default gesetzt |
| `meta.water_level` | **Fläche** | Welt-y (m) | Der Spiegel STEHENDEN Wassers. Fehlt er, leitet der Bake ihn her (Rand-Median); `save_area` friert ihn dann ein |
| `meta.water_level_up` / `_down` | **Fläche** | Welt-y (m) | Die beiden Enden eines FLIESSENDEN Spiegels. Jedes überschreibt sein eigenes Ende; ein einfaches `water_level` setzt beide |
| `meta.flow_dir_deg` | **Fläche** | 0…360, gewrappt | Die FLIESSRICHTUNG (stromabwärts) von POLYGON-Wasser. Buchstabiert wie jeder andere Yaw des Vertrags (§ A1.1): `dir = (sin θ, cos θ)`, also 0° nach +z, 90° nach +x. Sie treibt das Profil UND (ab W2) die Ripple-Scrollrichtung. Trägt die Fläche eine Linie, die sie entlangfließt, wird sie **ignoriert** (W4a) |
| `meta.flow_along` | **Fläche** | `"forward"` / `"reverse"` / fehlt | **W4a:** Fließt eine mit dem LINIENWERKZEUG gezeichnete Fläche entlang ihrer Mittellinie (`meta.stroke.points`) — in Zeichenreihenfolge oder gegen sie; fehlt der Schlüssel, steht das Wasser. Alles andere verliert den Schlüssel. Ein Fluss macht Biegungen, und eine einzelne Gradzahl kann nicht sagen, wo ein Mäander langläuft |
| `meta.flow_speed_m_s` | **Fläche** | 0…2 m/s, geklemmt, 2 Nachkommastellen | **Befund 2026-08-23 Nr. 2:** Wie schnell genau DIESE Fläche läuft. Überschreibt den `flow_speed`-Regler ihrer SURFACE-ART (Default **0,5 m/s** seit der Nutzer-Entscheidung 2026-08-25, davor 0,15, `surface_textures`), fehlt der Schlüssel, antwortet die Art. Reine OPTIK: Bake, Spiegel und Fließachse lesen ihn nicht, deshalb steht er auch nicht in `heightfield.WaterMeta`. Die Renderer bekommen ihn NICHT als Meter pro Sekunde, sondern als VERHÄLTNIS `Fläche ÷ Art` in der LÄNGE des Vertex-Attributs `aWaterFlow` (`waterFlowFactor`, `@anima/scene-render`) — der Shader rechnet `wSpeed = uFlowSpeed · wLen`, ein Material bleibt pro Art. Ohne Schlüssel ist die Länge exakt 1 (der Einheits-Tangens seit W4a), eine authorierte 0 wird auf 1e-3 geklemmt: 0 wäre die Länge, die der Shader als STEHEND liest, und stehendes Wasser driftet mit `uSpeed` = 0,25 m/s, also SCHNELLER |
| `meta.bed_kind` | **Fläche** | Art-Id | Welche Bodenart der Layer-Bake UNTER dem Wasser malt. Default: die blanke Welt (`game.default_terrain_kind`) — genau die Ersetzung, die der Client bisher selbst vornahm |

Die Art kann den SPIEGEL nicht beantworten: zwei Seen einer Art stehen auf zwei
Höhen. Alles andere darf sie.

### 2. Das Spiegel-PROFIL — `water_level_at(x, z)`

`app/core/heightfield.WaterProfile` ist die reine Funktion, und sie fährt
additiv im Payload mit (`meta.water_profile`, siehe Nr. 4). **Seit W4a ist die
Achse eine POLYLINIE**, das Feld `axis`: Knoten `[x, z, s, level]` in
Fließreihenfolge, `s` = Bogenlänge ab dem ersten Knoten, `level` = Welt-y dort.

```
s      = Bogenkoordinate des NÄCHSTEN Punktes auf der Polylinie
         (jedes Segment mit Klemme projiziert, kürzester Abstand gewinnt)
level  = linear zwischen den beiden Knoten, zwischen denen s liegt,
         an beiden Enden geklemmt
```

* **Beide alten Gesetze sind Sonderfälle, kein Zweig daneben.** Stehendes
  Wasser ist EIN Knoten (am Flächen-Schwerpunkt): der nächste Punkt ist dieser
  Knoten, die Klemme antwortet überall sein Niveau. Ein gerader Fluss aus
  `flow_dir_deg` ist ZWEI Knoten — die Extreme des Polygons auf der Achse mit
  `level_up`/`level_down` —, und die Projektion auf dieses eine Segment IST das
  `clamp((s − s_min)/(s_max − s_min), 0, 1)` von W1, Klemme inklusive.
* **Warum überhaupt eine Polylinie:** projiziert man eine 180°-Schleife auf eine
  Gerade, liegen Ober- und Unterlauf am selben Achsenpunkt und der Spiegel der
  Biegung kann gar nicht fallen. Entlang der eigenen Linie kann er es immer.
* **Die Knoten-Niveaus einer gezeichneten Linie**: je Knoten der **Median der
  Naturhöhe über einen QUERSCHNITT** — 9 Proben senkrecht zur lokalen Tangente,
  verteilt über `width_m`/2 + Uferrampe zu jeder Seite (der Rand-Median von oben,
  lokal statt je Drittel). Danach **stromabwärts monoton** (laufendes Minimum):
  Wasser fließt nie bergauf. Erst dann gewinnt der Autor: `water_level` macht
  alle Knoten gleich (gezeichnet, aber stehend), `water_level_up`/`_down`
  ersetzen den ersten/letzten Knoten und die inneren werden **affin** in die
  neue Spanne eingepasst — ihre Form bleibt, ihre Enden werden die autorierten.
* **Die Knoten sind NICHT die Klicks** (W5b, 2026-08-24). Vor den
  Querschnitts-Medianen wird die gezeichnete Linie **nach Bogenlänge abgetastet**
  — `heightfield.WATER_AXIS_STEP_M` = 2 m, je Teilstrecke gleichmäßig in
  `ceil(Länge/Schritt)` Teile, die geklickten Punkte bleiben Knoten. Danach
  laufen die Regeln oben unverändert (Median je Knoten, laufendes Minimum,
  autorierte Enden). Zum Schluss wird die Knotenliste wieder **vereinfacht**:
  Douglas-Peucker auf `(s, level)`, Toleranz `WATER_AXIS_SIMPLIFY_M` = 0,05 m,
  je Teilstrecke mit den Klicks als festen Ankern, Abweichung **senkrecht in
  der Höhe** gemessen (genau der Fehler, den ein Leser von `water_level_at`
  sieht). Eingefügte Knoten liegen auf der geraden Teilstrecke zwischen zwei
  Klicks, ihr Wegfall kann die Achse also nicht um einen Millimeter versetzen;
  Klick-Knoten sind Biegungen und fallen nie weg. Ein Fluss über gleichmäßigem
  Gefälle liefert damit exakt die gezeichneten Punkte, ein Fluss über eine
  3-m-Kante zwei Knoten dies- und jenseits der Kante. Obergrenze
  `WATER_AXIS_MAX_KNOTS` = 256 eingefügte Knoten (darüber wächst der Schritt).
  **Grund:** mit Knoten nur an den Klicks war der Spiegel zwischen zwei Klicks
  EINE Rampe — er sank lange vor der Kante unter den Boden (Carve schnitt eine
  Schlucht) und stand lange danach in der Luft, und `waterfallsFrom` konnte die
  Kante nicht sehen, weil kein Knoten in ihrer Nähe lag. `HEIGHT_BAKE_VERSION`
  ist deshalb auf 3.
* **Die beiden Enden von POLYGON-Wasser**, wo der Autor sie offen lässt: der
  **Rand-Median des jeweiligen DRITTELS** der Achsen-Spanne — `level_up` über die
  Randproben mit `s ≤ s_min + Spanne/3`, `level_down` über die mit
  `s ≥ s_max − Spanne/3`. Ein Drittel und nicht „die zwei Extrempunkte": ein mit
  vier Ecken gezeichneter Fluss hätte je Ende genau eine Probe und nähme sein
  Niveau von einem willkürlichen Quadratmeter Landschaft.
* **Die neun Zahlen bleiben** — für einen Leser, der die Polylinie nicht kennt,
  die beste EINE geneigte Ebene: `level_up`/`level_down` sind das Niveau des
  ERSTEN und des LETZTEN Knotens, `axis_x/axis_z` der erste Knoten (bei
  Polygon-Wasser weiter der Flächen-Schwerpunkt), `flow_dir_deg` die Peilung der
  **Sehne erster → letzter Knoten** (bei Polygon-Wasser die autorierte) und
  `s_min`/`s_max` die Spanne auf dieser Sehne. Bei stehendem Wasser bleibt
  `flow_dir_deg` `null` und `s_min == s_max == 0`.

### 3. Der Carve rechnet gegen das LOKALE Niveau

```
h = min(h, water_level_at(x, z) − water_depth_m · smoothstep(min(d_in/shore_ramp_m, 1)))
```

> **INVARIANTE 2, jetzt PUNKTWEISE.** Für jede Probe tiefer als `shore_ramp_m`
> im Polygon gilt `h_final ≤ water_level_at(x, z) − ε`, `ε = min(depth, 0,25)` —
> nicht gegen einen Mittelwert, sondern gegen den Spiegel AN DIESER STELLE.
> Jenseits der Rampe ist `smoothstep(1) = 1` exakt, das zweite Argument des
> `min` also `level_at(x,z) − depth`: arithmetisch, nicht gesampelt.

**Die rote Gegenprobe steht im Smoke** (`scripts/smoke_height_bake.py` [8h]).
Derselbe Fluss mit EINEM Spiegel auf dem Mittelniveau 5,0 lässt den Boden
stromabwärts bei 2,35 stehen, während das lokale Niveau dort 1,025 ist — die
Invariante ist um 1,575 m verletzt, und ein flacher Spiegel schneidet stromauf
durch einen Boden, der 2,65 m über ihm liegt. Der geneigte Carve antwortet an
derselben Stelle 0,025 und hält sie.

### 4. Payload — additiv, und `water_level_effective` bleibt

`GET /world/terrain-areas` und `GET /play/terrain` liefern je Wasser-Fläche
unverändert `meta.water_level_effective` und **zusätzlich** `meta.water_profile`:

```jsonc
"meta": {
  "flow_dir_deg": 270,
  "water_level_up": 7.4, "water_level_down": 2.6,
  "water_level_effective": 5.0,          // OUTPUT: das MITTELNIVEAU des Profils
  "water_depth_effective": 1.2,          // OUTPUT: die BETT-TIEFE des Carves
  "water_profile": {                     // OUTPUT: die neun Zahlen …
    "level_up": 7.4, "level_down": 2.6, "flow_dir_deg": 270.0,
    "axis_x": 50.0, "axis_z": -30.0, "dir_x": -1.0, "dir_z": 0.0,
    "s_min": -30.0, "s_max": 30.0,
    // … und seit W4a die WAHRHEIT daneben: die Knoten [x, z, s, level] in
    // Fließreihenfolge, auf 3 Nachkommastellen. Ein Knoten = stehend, zwei =
    // die gerade Achse oben, N = die gezeichnete Linie.
    "axis": [[80.0, -30.0, -30.0, 7.4], [20.0, -30.0, 30.0, 2.6]] } }
```

**`water_level_effective` ist ab jetzt das MITTELNIVEAU** (das Mittel der beiden
Enden = das Niveau in der Mitte der eigenen Achse). Für stehendes Wasser ist es
exakt der Spiegel, der es immer war; für einen Fluss ist es die eine Ebene, die
an beiden Enden am wenigsten danebenliegt — die ehrlichste Zahl für den
FLACHEN Client, den W2 ablöst. Wer die Wahrheit will, liest `water_profile` und
wertet die Formel aus Nr. 2 selbst aus. Beides ist **Ausgabe** und wird nie in
die Autorenfelder zurückgeschrieben (der Sanitizer wirft beide auf dem Weg
hinein weg).

**`water_depth_effective` ist dasselbe für das BETT** (W4b): die Tiefe, mit der
der Carve wirklich gerechnet hat — die Vorgabe der ART, mit der Überschreibung
der FLÄCHE und den Klemmen von Nr. 1 schon angewendet (`heightfield.water_meta`).
Sie steht neben `water_level_effective`, weil sie dieselbe Art Antwort ist: das
Ergebnis einer Auflösung, die ein Client sonst ein zweites Mal implementieren
müsste. Er braucht sie, weil die **Deckkraft** einer Wasserfläche ¾ ihrer
eigenen Tiefe ist (`client3d/src/scene/waterPlaneMath.waterOpaqueDepthM`,
Vertex-Attribut `aWaterOpaque`): ein 1,2-m-Fluss ist ab 0,9 m Tiefe deckend, ein
2-m-See erst ab 1,5 m — mit EINER Konstante blieb der schmale Fluss bis zur
Mitte durchsichtig. Fehlt der Schlüssel (die Fläche hat kein gecarvtes Bett),
rechnet der Client mit dem Vorgabe-See weiter.

### 5. Der Layer-Schnitt: Wasser trägt sein BETT

Ein Wasser-Layer bleibt ein voller Layer — die Maske muss „hier ist Wasser"
beantworten, für den Unterwuchs-Filter und für jede Punktabfrage. Was er
**malt**, ist ab W1 der Boden DARUNTER:

* `surface` des Layers = die Oberfläche der **Bett-Art** (`meta.bed_kind`,
  Default: die blanke Welt). Der Wasser-Layer malt also nie die Wasser-Textur
  auf das Gelände — der Spiegel ist eine eigene Fläche darüber, und den See
  zweimal zu malen ließ die beiden gegeneinander arbeiten.
* `edge_blend_m` = die Übergangsbreite der **Bett-Art**, sobald eine autoriert
  ist; ohne autoriertes Bett bleibt es die der Wasser-Art (heutige Zahl).
* Der Tabellen-Eintrag nennt sein Bett: **`bed_kind`** (additiv, nur auf
  Wasser-Layern). Der Schlüssel eines Layers ist damit `(kind, edge_blend_m,
  bed_kind)`: **zwei Teiche einer Art auf zwei Betten sind zwei Layer.**
* Das Feld `water` jeder Tabellenzeile — Karten-Arten wie Boden-Arten —
  kommt aus dem EINEN Prädikat.
* **Die `waters`-Liste des Index ist WEG.** Es gibt keine Zonen-Wasser mehr zu
  listen. (Der laufende Client liest sie als `index.waters ?? []` und zeichnet
  dann keine Zonen-Platten mehr — kein Fehler, nur das Ende eines Features.)

### 6. Wasser verlässt den Lageplan — ersatzlos, ohne Kompat-Leser

**Gelöscht** (keine Alias-Felder, keine Fallback-Reader):

`heightfield.ZoneWaterInput` · `ZoneWaterStamp` · `HeightModel._build_zone_water`
· `HeightModel._carve_zone` · `HeightModel.zone_water` ·
`HeightModel.zone_water_level_by_room` · der Parameter `zone_waters` aller
Bake-Einstiege · `models.heightfield.placed_zone_waters` · `zone_water_basis`
(und ihr Eintrag in `height_sig`) · `terrain_layers.waters_payload` ·
`is_water_floor` · `floor_water_meta` · `surface_classes` · die vier
Wasser-Felder von `terrain_layers.Floor` · die drei Raum-Layout-Felder
`water_level` / `water_depth_m` / `shore_ramp_m` (E5b-Regler) · das Feld
`water_level_effective` im `floor_plan` der Szene.

**Eine Boden-Art eines Raums darf keine Wasser-Art mehr sein.** Der Sanitizer
(`world_ops._sanitize_room_layout`) wirft ein solches `surfaces.floor` mit einer
Log-Zeile weg — an dem einen Schreibpfad, an dem es entstehen kann.

**Stattdessen ein VERWEIS.** Der `floor_plan`-Eintrag eines Raums, dessen
Grundriss (mehrheitlich, nach FLÄCHE) in einer gemalten Wasser-Fläche liegt,
trägt additiv:

```jsonc
{ "room_id": "pond", "polygon_world": [...], "floor_kind": "sand",
  "closed": false,
  "map_water": { "area_id": "ta_pool", "kind": "water" } }
```

**Abgeleitet beim Komponieren, nie gespeichert** — deshalb kann er nicht
hängen: verschwindet der See, verschwindet die Zeile. Mehrheit heißt STRIKT
mehr als die Hälfte (genau halb liegt nicht darauf), gemessen auf einem festen
32 × 32-Raster über der Hülle; bei Gleichstand gewinnt die SPÄTER gemalte
Fläche — das Vorrangsgesetz des ganzen Bodens (§ A16.7), nicht ein hier
erfundener Tie-Break. Raum-Semantik (Zugehörigkeit, Wahrnehmung) ändert sich
nicht.

### 7. Signaturen

* `height_sig` hasht `water_basis()` mit den **effektiven** Zahlen (Spiegel,
  beide Enden, Fließrichtung, aufgelöste Tiefe/Rampe): eine Welt, die ihre
  Art „river" von 2 m auf 6 m dreht, ändert jedes Flussbett, ohne dass eine
  Fläche angefasst wird — und die Signatur trägt das mit. `zone_water_basis`
  ist aus dem Basis-Objekt raus.
* `layers_sig` hasht zusätzlich das **`bed_kind` je Fläche**: das Bett malt,
  also gehört es in den Schnitt, nicht in die Höhe. `surface_classes` ist raus.

### 8. Die Beweise (§ B5a)

| Skript | was es herleitet |
|---|---|
| `scripts/smoke_height_bake.py` **[8]** | die Fließachse (Yaw-Konvention, Wrapping), die beiden Drittel-Rand-Mediane von Hand (7,4 / 2,6 aus 31 Randproben je Ende), `level_at(x) = 0,08·x + 1,0`, der Carve gegen das lokale Niveau, Art-Vorgabe gegen Flächen-Überschreibung, die ungeflaggte Art (kein Carve), Invariante 2 punktweise über 2916 Proben (schlechtester Abstand exakt die Tiefe 1,0 m), die **roten** Gegenproben gegen den konstanten Spiegel, das Einfrieren beider Enden beim Save und die neun Payload-Zahlen |
| `scripts/smoke_height_bake.py` **[8k]** | **W4a:** die Fließachse als POLYLINIE — die drei Knoten-Niveaus 10/8/6 einer Haarnadel als Querschnitts-Mediane von Hand, das Niveau am mittleren Knoten (8,0) gegen die **rote** Gegenprobe der geraden W1-Sehne (6,0: die Biegung projiziert hinter das eigene Unterlauf-Ende), Bogenlängen 101/153 und die Mitten-Niveaus 9,0/7,0, der Carve gegen das lokale Niveau, das laufende Minimum (10/11/6 → 10/10/6, seit W5b mit dem Eckknoten dort, wo die Linie wieder auf 10 fällt: 10/10/**10**/6 bei (239,4 | 300), rückwärts gezeichnet 6/6/6), autorierte Enden 12/4 über 10/8/6 → 12/8/4, `water_level` = alle Knoten gleich, `flow_along` schlägt `flow_dir_deg`, der Sanitizer der zwei Wörter und das EINE Prädikat `is_flowing` samt Settle-Pfad |
| `scripts/smoke_height_bake.py` **[8l]** | **W5b:** die Verdichtung der Achse — eine harte 3-m-Kante bei x = 41 (Höhenfläche mit `falloff_m` 0), ein mit ZWEI Klicks gezeichneter Fluss (0,0)→(100,0), Abtastung alle 2 m ⇒ Achse `[0,3] [40,3] [42,0] [100,0]`, der ganze Abfall in EINEM 2-m-Segment (Gefälle 1,5 ⇒ genau ein Wasserfall), Spiegel 10 m vor der Kante = 3,0 und 10 m danach = 0,0, Bett-Tiefe oberhalb exakt `water_depth_m`; **rote** Gegenproben der Zwei-Knoten-Rampe: 2,07 statt 3,0 (0,93 m unter den eigenen Ufern — „Wasser fast weg", Carve gräbt bis 1,07) und 1,47 statt 0,0 (1,47 m über dem Boden — „Wasserhügel"), Gefälle 0,03 ⇒ kein Fall. Zwillinge: `client3d/scripts/smoke_water_plane.mjs` **[4e]**, `client3d/scripts/smoke_waterfall.mjs` **[9]** |
| `scripts/smoke_height_bake.py` **[9]** | die Löschung der fünften Stufe **namentlich**: 17 Symbole, die Bake-Signaturen, der `waters`-freie Index, die drei Raum-Wasserfelder und die gestrippte Wasser-Boden-Art |
| `scripts/smoke_terrain_layers.py` **[13]** | Bett-Art als Layer (Oberfläche + eigene Übergangsbreite, zwei Betten = zwei Layer), die rote Probe „nichts malt die Wasser-Textur aufs Gelände", das EINE Prädikat Zeile für Zeile, und das **Kantengesetz**: dieselben zwei Rechtecke in zwei Malreihenfolgen geben die zwei Breiten |
| `scripts/smoke_scene_recipe.py` **[4w]** | `map_water` von Hand (100 % / 75 % → Verweis; 50 % / 25 % / 0 % → keiner), Letzter-gewinnt, und dass der Eintrag sonst nichts über Wasser sagt |
| `scripts/smoke_terrain_types.py`, `scripts/smoke_nav_grid.py` | Sanitizer der Art-Vorgaben bzw. der Bett-Carve unter der Laufregel |

## Nachtrag 2026-08-21 (§ A16.3 / § A16.7 / § A19 Nr. 5 / § G4): Ein Wasser-Gesetz — W2 (Client)

> **Der MESH-Teil dieses Nachtrags ist mit Wasser v2 K-A E5 tot**
> (`liftToWaterProfile`, die Regelfläche, der Ufer-Shader `vWaterPlane`): das
> Terrain hebt und schattiert seine eigenen Wasserpixel (Nachtrag „Das
> Wasser-Raster", 7a/9/10). Was bleibt, ist die LESUNG — `waterProfileOf`,
> `waterLevelAt` und das Verbot, `water_level_effective` zu lesen —, und die
> gilt unverändert für Spielmechanik, Wasserfall-Erkennung und die
> Raster-Quelle des Servers.

*Etappe W2 aus `development_instructions/plan-fliessgewaesser.md`, die
Lese-Seite des W1-Nachtrags oben. Er **ersetzt** dessen Satz „bis W2 zeichnet
der Client weiter EINE flache Platte", **streicht** die Zonen-Wasser-Aussagen
von § A19 Nr. 5 ersatzlos und **präzisiert** § G4 (der Spiegel ist keine
Platte mehr). Was der Server liefert, ändert W2 nicht um eine Zahl: die neun
Zahlen von W1 werden jetzt ausgewertet statt gemittelt. W3 (Admin-UI) folgt.*

**DAS GESETZ, in vier Sätzen.** Der Spiegel ist eine **REGELFLÄCHE**: jeder
Vertex des Earcuts trägt `water_level_at` seines eigenen Ortes, ein See kommt
dabei bitgleich flach heraus wie bisher. Die **Fließrichtung treibt die
Ripple**, und zwar als **Vertex-Attribut**, weil das Material der ART gehört
und die Strömung der FLÄCHE. Es gibt **EINE Wasserquelle**: die gemalten
Flächen — der Zonen-Lookup ist gelöscht, und Schwimmen rechnet gegen das
LOKALE Niveau. Und der Client **malt kein Bett mehr selbst**: er rendert die
Oberfläche, die die Layer-Tabelle nennt.

### 1. Der Spiegel ist eine Regelfläche, keine Platte

`scene/waterPlaneMath.ts` trägt den reinen TS-Zwilling der Server-Funktion:

* `waterProfileOf(meta)` liest `meta.water_profile` — und **das ist der ganze
  Wasser-Test**. Nur eine Fläche, die das eine Server-Prädikat
  (`terrain_types.is_water_kind`) als Wasser gezählt hat, trägt ein Profil.
  Die Material-KLASSE (`isWaterClass`) wird dafür **nicht mehr befragt**: sie
  sagt, wie Wasser AUSSIEHT, und war das zweite Buch darüber, was Wasser IST.
* `waterLevelAt(profile, x, z)` ist `heightfield.water_level_at`, Zeile für
  Zeile, samt der beiden Klemmen — an den Enden liefert sie `level_up` bzw.
  `level_down` **exakt**, nicht das Ergebnis einer Interpolation mit t = 0/1.
* `liftToWaterProfile(positions, profile)` schreibt dieses Niveau in das `y`
  jedes `(x, y, z)`-Tripels. Die Masche steht danach im Ursprung; ihre Höhe
  ist absolut und darf nicht noch einmal verschoben werden.

**KEINE UNTERTEILUNG, und das ist Arithmetik, kein Geschmack.** Das Profil ist
in der Ebene linear, solange die Klemme nicht greift — und die greift nur
AUSSERHALB von `[s_min, s_max]`, das sind die Extreme des Polygons selbst.
Kein innerer Punkt erreicht den Knick, also gibt eine Regelfläche durch den
Umriss die Funktion exakt wieder. Ein 60 m langer Fluss ist eine Handvoll
Dreiecke.

**DER UFER-SHADER BLIEB UNVERÄNDERT** — das ist der Befund von W2, nicht ein
Versäumnis. `wsDepth = vWaterPlane.y − tlodHeight(vWaterPlane.xz)` liest die
Höhe seit E4 aus der GEOMETRIE, nie aus einer Uniform; die Interpolation einer
linearen Funktion über ein Dreieck IST diese Funktion, also misst er ohne eine
Zeile Änderung gegen das lokale Niveau. Genau dieselbe Eigenschaft trug schon
zwei Seen auf zwei Höhen auf EINEM Material.

### 2. Die Fließrichtung als Vertex-Attribut

`aWaterFlow` (vec2) trägt die stromabwärtige Einheitsrichtung
(`dir_x`/`dir_z`, für stehendes Wasser `(0, 0)`) und liegt auf der Spiegel-
Geometrie, nicht in einer Uniform. **Der Grund ist die Materialbindung:**
`ground.rebuildAreas` hält genau EIN Material je Wasser-ART für die ganze
Welt; eine Uniform hätte also ein Material je FLÄCHE erzwungen, um zwei Floats
zu sagen. Auf einer Masche von einem Dutzend Vertices sind zwei Floats nichts.

Der Ripple-Patch (`@anima/scene-render` `materials.ts`) baut daraus einen
Rahmen — `wAx` stromabwärts, `wAy` quer — und legt die beiden Scroll-Vektoren
hinein. **Ohne Strömung ist der Rahmen der der Welt**, und die beiden Vektoren
sind buchstäblich die Konstanten von vorher: `A = (1, 0.6)`,
`B = −(0.8, 1.3)`. Mit Strömung laufen **beide Lagen stromabwärts**
(`A = wAx + wAy·0.6`, `B = wAx·0.8 − wAy·1.3`) und nur ihre Querkomponenten
sind gegenläufig — eine zweite Lage, die stromauf liefe, läse sich als zwei
Flüsse. Die Beträge (`√1.36`, `√2.33`) sind rotationsinvariant, `uSpeed` bleibt
also dieselben Meter pro Sekunde.

**Eine Geometrie ohne das Attribut liest `(0, 0)`** — WebGL lässt ein
ungebundenes Attribut auf seinem generischen Wert `(0, 0, 0, 1)`, den three nie
schreibt. Jede Wasserfläche, die keine client3d-Spiegelmasche ist (allen voran
die Böden der Admin-Vorschau), behält damit exakt ihr Aussehen.

### 3. Eine Wasserquelle — der Zonen-Lookup ist gelöscht

**Gelöscht** (keine Alias-Felder, keine Fallback-Leser):
`waterPlaneMath.zoneWaterAt` · `zoneWaterMirrors` · `ZoneMirror` ·
`waterLevelOf` · der Zustand `ground.zoneWaters` · das Lesen von
`index.waters` · die Zonen-Schleife in `rebuildAreas` · das **Borgen** eines
beliebigen wasser-geflaggten Katalog-Eintrags für einen Raum-Bodenart-Namen ·
`@anima/scene-render` `TerrainLayerWater` und das Feld `waters` von
`TerrainLayerIndex`.

`typeAt` liest den Spiegel damit aus genau einer Schleife: die letzte
enthaltende gemalte Fläche gewinnt Art UND Niveau, und das Niveau ist
`waterLevelAt(profile, x, z)` — **das lokale**, nicht `water_level_effective`.
`floatRootY(groundY, levelAt, sink)` ist in seinem Gesetz unverändert; was sich
geändert hat, ist was hineingereicht wird. Das ist der Unterschied zwischen
einer Figur, die überall 0,6 m unter ihrer eigenen Wasserlinie hängt, und
einer, die stromab 1,92 m ÜBER dem sichtbaren Wasser schwimmt und stromauf in
1 m tiefem Wasser watet (die rote Gegenprobe im Smoke, von Hand gerechnet).

`water_level_effective` fährt weiter mit und wird vom Client **nicht mehr
gelesen**: es ist die eine Ebene für einen FLACHEN Konsumenten, und diesen
Konsumenten gibt es hier nicht mehr.

### 4. Der Bett-Hack ist tot

`layerGround.setLayerTable` ersetzte für jede Wasser-Zeile das Bild von Layer 0
(`layer.water ? bare : layer`). Das war ein Renderer, der Boden erfindet: eine
autorierte Kies-Sohle wurde auf die Default-Art der Welt zurückgeflacht. Seit
W1 IST `surface` einer Wasser-Zeile schon die des Bettes und `bed_kind` nennt
die Art dazu, also entfällt die Ersetzung ersatzlos. Wo der Client die ART
statt der Oberfläche braucht (Farb-Fallback, Meter je Kachel), fragt er
`layer.bed_kind || layer.kind`. `bed_kind` ist zusätzlich Teil des `layerKey`,
denn zwei Teiche einer Art auf zwei Betten sind zwei Zeilen mit zwei Bildern —
ohne das im Schlüssel bliebe das Slice-Array der alten Welt stehen.

### 5. Der Lageplan sagt nur noch Bescheid

Ein `floor_plan`-Eintrag kann `map_water {area_id, kind}` tragen (W1 § 6). Der
3D-Client liest es **absichtlich für nichts**: Raum-Semantik (Zugehörigkeit,
Mitte, Stände, Pulk) kommt weiter aus `polygon_world`, Boden und Spiegel malt
die KARTE. Eine Fläche zu unterdrücken gibt es nicht, weil Stockwerk 0 seit E5a
ohnehin keine eigene malt. Das Feld `water_level_effective` von `SceneFloor`
ist **ersatzlos gestrichen** — der Server sendet es seit W1 nicht mehr, W3 hat
den letzten Leser (die Admin-Lageplan-Vorschau) entfernt, und der Typ nennt es
seitdem nicht mehr.

### 6. Die Beweise (§ B5a)

| Skript | was es herleitet |
|---|---|
| `client3d/scripts/smoke_water_plane.mjs` **[1]** | dass das PROFIL die einzige Wasserfrage ist: Mittelniveau allein ist keines, autoriertes Niveau keines, eine Zahl kaputt = kein Profil |
| **[4]** | der Fixture-Fluss von Hand: Achse durch den Schwerpunkt (50, −30), `dir = (−1, 0)` aus 270°, `s_min/s_max = ∓30`, `level(x) = 0,08·x + 1,0` an sechs Stellen, beide Klemmen **exakt**, der See als entartete Spanne, der Flow-Vektor |
| **[5]** | die geneigte Masche: vier Ecken auf 2,6 / 7,4 / 7,4 / 2,6 (4,8 m Gefälle auf 60 m), die Linearität an Hälfte, Viertel und ⅞ der Kante, und der See **bitgleich** flach (`Object.is`) samt `level + 0 == 0 + level` |
| **[6]** | Schwimmen am lokalen Niveau: Bett `0,08·x`, Tiefe überall 1,0 m, Wurzel/Körper bei x = 26/50/74 — und die **roten** Gegenproben des flachen Mittelniveaus (1,92 m über dem sichtbaren Wasser stromab, Waten stromauf, ein Watet/Schwimmt-Umschlag bei genau x = 55, den es in Wahrheit nirgends gibt) |
| **[7]** | der Ufer-Shader auf der Schräge: Alpha 20/27 an jedem x — und **rot**, dass die flache Platte oberhalb x = 62,5 negative Tiefe hätte und ganz weggeworfen würde |
| **[8]** | die Löschung **namentlich**: acht Symbole dürfen in `client3d/src` und `packages/scene-render/src` in keiner Nicht-Kommentar-Zeile mehr stehen, `SceneFloor.water_level_effective` eingeschlossen — und `map_water` steht an seiner Stelle |
| **[9]** | die Ripple-Richtung: der stehende Fall ergibt exakt die alten Konstanten, 0°/90°/270° geben beide Lagen stromabwärts mit gegenläufiger Querkomponente, und die Beträge bleiben rotationsinvariant |
| `client3d/scripts/smoke_layer_cut.mjs` **[7b]** | der Bett-Fall: die Ersetzung ist weg, das Slice kommt aus `layer.surface`, Farbe und Kachelmaß fragen `bed_kind`, und `bed_kind` steht im `layerKey` |
| `client3d/scripts/smoke_surface_patch.mjs` | **rot**: keine Bibliotheksfrage entscheidet mehr über Wasser |

## Nachtrag 2026-08-23 (§ B2): Ein Prop steht auf einem Prop, und ein Prop darf halb sein

Zwei Eingriffe am Lageplan, beide an DERSELBEN Platzierung und beide ohne ein
zweites Prop in der Bibliothek: den Teekessel auf den Tisch stellen, und den
Tisch zur Hälfte an die Wand stellen.

### 1. Obenauf — die Stapelregel

**Es gibt KEIN neues Höhenfeld.** Die Platzierung trägt seit je `offset_y`
(Meter, additiv zum Raumboden, ±5 m, Abwesenheit = 0) — das ist das Feld, in
dem eine Stapelung landet. Neu ist nur, wer die Zahl AUSRECHNET.

**Die Regel, ein Satz:** die Unterkante des gestellten Props landet exakt auf
der Oberfläche des OBERSTEN Props, dessen gedrehter Fußabdruck seinen Punkt
überdeckt. Ausgeschrieben über die Basisleiter des Nachtrags 2026-08-20
(automatische Basis + `ground_offset_m` des PROPS + `offset_y` der
PLATZIERUNG):

```
top(Träger)      = ground_offset_m(Träger) + offset_y(Träger) + height_m(Träger)
offset_y(Ziel)   = top(Träger) − ground_offset_m(Ziel)
```

Die automatische Basis kürzt sich weg — Träger und Ziel stehen im selben Raum
auf derselben Platte, gespeichert wird nur die Differenz. Beide Bodenversätze
stehen drin, weil beide echt sind: ein 10 cm eingesunkener Tisch hat seine
Platte 10 cm tiefer, und ein Prop, das selbst einsinkt, soll auf der Platte
stehen und nicht in ihr.

„Darunter" ist ein FUSSABDRUCK-Test, keine Entfernung: jede andere Platzierung,
deren gedrehte Box (`width_m × depth_m`, um `+rad(yaw)` gedreht, § A1.1) den
Punkt der Platzierung enthält, ist Kandidat; von denen gewinnt die mit der
höchsten Oberfläche (Becher auf Tablett auf Tisch). Streu-Kopien zählen nie —
sie entstehen erst zur Compose-Zeit, ein Autor kann auf keine zeigen.

`width_m` / `depth_m` / `height_m` sind dabei die Maße der **gezeigten
Variante** (Nachtrag 2026-08-24), für Ziel wie Träger einzeln aufgelöst: eine
Teekanne auf der HOHEN Variante eines Tisches landet höher als auf der
niedrigen. Der `variant` einer Platzierung ist eine POSITION in der
veröffentlichten Liste, also geht er durch `props.placement_variant`, bevor die
Maße gelesen werden.

**Wo die Regel lebt:** `app/core/props.stack_offset_y` (rein, ohne Bibliothek)
plus `placement_stack_offset_y` (mit ihr davor), erreichbar über
`POST /world/props/stack-y` mit `{props: [...], index: n}` →
`{"offset_y": 0.75}` bzw. `{"offset_y": null}`. Der Rumpf trägt die
Platzierungsliste, wie `POST /play/scene-preview` den Location-Entwurf trägt —
der Lageplan fragt also auch für ungespeicherte Arbeit. **Kein Renderer rechnet
hier etwas**: das Ergebnis steht in `offset_y`, und beide Renderer lesen
weiterhin nur `bottom_y`.

**Bedienung:** Lageplan → Prop-Leiste → „Place on top" (angeboten, sobald
wirklich etwas darunter liegt) und „Place on floor" als Umkehrung.

**Handrechnung (§ B5a)** — `scripts/smoke_scene_recipe.py` **[7f]**, Tisch
1,2 × 0,8 × 0,75 m bei (2, 3), Teekessel 0,2 × 0,2 × 0,25 m:

| Fall | Ergebnis |
|---|---|
| Kessel über der Tischmitte | `0 + 0 + 0.75 − 0 = 0.75` |
| 0,55 m aus der Mitte (Halbmaße 0,6 × 0,4) | weiterhin `0.75` |
| derselbe Punkt, Tisch auf Yaw 90° | `lz = 0.55 > 0.4` → **nichts darunter** |
| Tablett (0,05 m) liegt schon auf dem Tisch | `0.75 + 0.05 = 0.80` (das OBERSTE gewinnt) |
| Tisch 5 cm eingesunken | `−0.05 + 0.75 = 0.70` |
| Kessel selbst 5 cm einsinkend | `0.75 + 0.05 = 0.80`, Unterkante wieder `0.75` |
| Payload, Etage 0 | Tisch `bottom_y = 0.01`, Kessel `0.01 + 0.75 = 0.76` |

### 2. Der Tiefenschnitt — `cut_plane`

Ein halber Tisch an der Wand ist DIESER Tisch mit einer Ebene hindurch, kein
zweiter Bibliothekseintrag. Die Platzierung trägt dafür zwei Felder:

```
cut_keep   # Bruchteil der TIEFE, der stehen bleibt: 0.05 … 1.0
cut_side   # welche Hälfte BLEIBT: "front" | "back"
```

Sanitizer wie bei `ground_offset_m` — **Abwesenheit ist die Aussage**: `1.0`
(ganzes Prop), alles über 1 (geklemmt auf 1.0) und jeder Unsinn schreiben
KEINEN Schlüssel; unter 0,05 wird geklemmt, nie abgelehnt; ohne `cut_side`
steht „back". Streu-Kopien erben keinen Schnitt.

**Geschnitten wird immer quer zur TIEFE** — der lokalen z-Achse des Props — und
die Ebene dreht mit dem Platzierungs-Yaw. `cut_side` benennt die Hälfte, die
STEHEN BLEIBT: `"front"` ist auf dem Plan die obere Kante des ungedrehten
Fußabdrucks (lokal −z), `"back"` die untere (lokal +z). Das Prop hängt an seiner
eigenen Mitte (§ B2 Schritt 3), lokal z läuft also −d/2 … +d/2:

```
back:   z_cut = +d/2 − keep·d,   n_lokal = (0, 0, +1)
front:  z_cut = −d/2 + keep·d,   n_lokal = (0, 0, −1)
n = σ·(sin θ, 0, cos θ)        P = Anker + z_cut·(sin θ, 0, cos θ)      c = −n·P
```

**Payload — `cut_plane` am Platzierungs-Spec (`models[]`, Rolle `prop`):**

```
cut_plane?: { normal: [nx, 0, nz], constant: c }
```

in den Weltmetern des Payloads, mit three.js' eigener Konvention: **behalten
wird, wo `n·p + c >= 0`**. Fehlt = ungeschnitten. Der Server liefert damit ein
FERTIGES PRIMITIV wie Platten und Wände; der Konsument baut genau eine
`THREE.Plane` daraus und rechnet nichts nach.

**Was der Renderer tut** (`applyDepthCut`, `@anima/scene-render/depthCut.ts` —
EINE Implementierung für Admin-Vorschau und 3D-Client): die Ebene NACH dem
Einhängen bauen und mit der Elternmatrix in den Weltraum heben
(`Material.clippingPlanes` ist Weltraum, der Szenen-Payload spricht die Meter
der Location — im Client hebt sie erst die Kachelgruppe mit Pin und Yaw), die
Materialien KLONEN (der Modell-Cache teilt sie), `clippingPlanes` setzen,
`clipShadows` an und `DoubleSide`. Beide Renderer schalten dafür einmalig
`renderer.localClippingEnabled = true`. Ein späteres Nachheben (§ A16.9) ist
harmlos: es verschiebt nur in y, und diese Normale hat keine y-Komponente.

**Die Schnittfläche bleibt OFFEN** — das ist eine Clipping-Ebene, kein CSG.
Bewusst akzeptiert, dieselbe Abmachung wie beim Hüllen-Clip (§ B1); deshalb
DoubleSide und deshalb der Hinweis in der Bedienung, die Schnittkante an eine
Wand zu stellen.

**Bedienung:** Lageplan → Prop-Leiste → „Depth cut (%)" (100 = ungeschnitten)
plus ein Umschalter Vorderteil/Hinterteil.

**Handrechnung (§ B5a)** — `scripts/smoke_scene_recipe.py` **[7g]**, Prop der
Tiefe 2 m bei (2, 3), `keep` 0,5:

| Fall | Ebene |
|---|---|
| back, Yaw 90° | `z_cut = 0`, `n = (1, 0, 0)`, `c = −2` → behalten wo x ≥ 2 |
| front, Yaw 90° | `n = (−1, 0, 0)`, `c = +2` → die komplementäre Hälfte |
| back, Yaw 0°, keep 0,25 | `z_cut = 0.5`, `n = (0, 0, 1)`, `c = −3.5` |
| keep 1,0 | **keine Ebene** |
| Payload: Tisch (Tiefe 0,8) bei Welt (−2,0, −2,5), back, keep 0,5 | `n = (0, 0, 1)`, `c = 2.5` |

## Nachtrag 2026-08-24 (§ A16.3 / § G4): Kein Relief am Wasserrand, und der Spiegel folgt seiner Achse überall — W5d

> **ÜBERHOLT — beide Hälften.** Der Client-Teil (Abschnitt 2,
> `subdivideRibbonByAxis`) ist mit Wasser v2 K-A E5 gelöscht: es gibt kein
> Spiegel-Mesh mehr, das man in Streifen schneiden könnte; das Terrain tastet
> den Pegel pro Vertex aus dem Raster ab. Der SERVER-Teil (Abschnitt 1, das
> reliefreie Band am Wasserrand) ist mit **K-A E6** zurückgebaut
> (`HEIGHT_BAKE_VERSION` 8, Nachtrag „Der Rückbau der Ufer-Wächter" am Ende
> dieses Dokuments): das Relief läuft wieder bis an die Wasserlinie, und die
> Rand-Hälfte von § G4 ist dort neu geschrieben. Was hier steht, ist der
> BEFUND, der zum Kragen führte — er gilt als Beschreibung des alten Defekts
> weiter, die Regel nicht mehr.

*Befund des Users nach Bake v4 + W5c: „Es sind noch immer Löcher zwischen
Wasser und Land." Zwei getrennte Ursachen, beide numerisch überführt, beide an
ihrer eigenen Stelle behoben. Screenshot-frei gemessen (§ B5a).*

### 1. Server: das Mikro-Relief endet am Wasser (`HEIGHT_BAKE_VERSION` 4 → 5)

Der Spiegel einer Fläche ohne autorierten Pegel ist der **Median der
Naturhöhen am eigenen Umriss**. Ein Umriss, der um ±1 m Mikro-Relief
schwankt, hat damit die HÄLFTE seines Umfangs ÜBER dem eigenen Wasser — und
die Bankklemme (v4) kann das nicht reparieren, weil sie nur hebt. Gemessen auf
der Fixture von `scripts/smoke_height_bake.py` **[11]**: 1,344 m Spannweite
über einen einzigen See, der höchste Randpunkt **0,466 m über seinem eigenen
Spiegel**, und das gezeichnete Gelände stand schon auf dem **feinsten** Gitter
(2 m) 0,389 m über dem Spiegel INNERHALB des Polygons.

Neu (`HeightModel._relief_weight`): das Mikro-Relief wird mit einem Gewicht
multipliziert, das **0 innerhalb des Polygons und auf dem Umriss** ist und über
das `shore_ramp_m`-Band nach außen per `smoothstep` auf 1 zurückkommt — dieselbe
Kurve und dieselbe Breite, die das Bett INNEN benutzt. Bei überlappenden Bändern
gewinnt das kleinste Gewicht; `shore_ramp_m = 0` (das Becken) verblasst außerhalb
nichts.

> **DIE RAND-SCHRANKE, konstruktiv.** Eine Probe im Polygon wird aus den vier
> Ecken IHRER Gitterzelle gezeichnet, die höchstens `step` Meter entfernt
> liegen. Für `step ≤ shore_ramp_m` liegt jede dieser Ecken damit entweder im
> Polygon (Carve: `h ≤` Spiegel) oder im reliefreien Band, wo der Boden die
> Flächenhöhe plus Klemme ist — das gezeichnete Bild ist eine Konvexkombination
> davon und steht also höchstens um `WATER_BANK_LIP_M` (0,1 m) über dem
> Spiegel. Das ist die Rand-Hälfte von § G4; Invariante 2 oben bleibt die
> Tiefen-Hälfte.

**Die Bankklemme bleibt** — sie fängt jetzt genau das, was das Relief nicht
mehr macht: HÖHENFLÄCHEN, die den Spiegel unterlaufen (Fixture [10]: Ufer bei
−0,4 unter einem Spiegel bei 1,0, Hub 1,5 m). Ohne Relief am Rand ist sie kein
zweites Buch mehr, sondern der einzige.

### 2. Client: die Streifen des Spiegel-Meshes sind eine ARRANGEMENT, kein Rest

W5c teilte die Maske mit einem laufenden REST: der stromaufwärtige Teil jeder
Querlinie war ein fertiger Streifen, nur der stromabwärtige wurde weiter
geschnitten. Eine Halbebene ist UNENDLICH — bei jeder Maske, die sich zurück
biegt (jeder Fluss mit einer Kurve), enthält der „stromauf"-Teil einer frühen
Querlinie deshalb auch die Scheibe des fernen Arms, die zufällig auf dieser
Seite liegt, und die Regelfläche darüber trägt ein Niveau vom falschen Ende des
Flusses hinein. Dieselbe Asymmetrie erzeugte **T-Vertices**: eine spätere
Querlinie teilt nur noch die Reste, während der schon fertige Streifen dieselbe
Sehne ganz behält — eine Seite zeichnet die Sehne, die andere den Teilungspunkt.

Neu (`waterPlaneMath.subdivideRibbonByAxis`): jede Querlinie wird JEDEM Stück
angeboten; ein Stück, das sie sauber schneidet, wird durch seine beiden Hälften
ersetzt, ein Stück, das sie verfehlt oder nur streift, bleibt ganz. Die Stücke
kacheln die Maske weiterhin exakt, es geht keines verloren, und es gibt keinen
T-Vertex mehr, weil jede Linie beide Seiten jeder Sehne teilt.

Gemessen (`client3d/scripts/smoke_water_plane.mjs` **[5d]**, 8-m-Fluss mit
90°-Knick, 61 Knoten, 15 360 Proben; Metrik ist triangulierungs-UNABHÄNGIG: die
Ebene durch drei gehobene Ecken eines Stücks gegen `waterLevelAt`):

| Regel | Ecke von der eigenen Ebene | Fläche gegen `waterLevelAt` |
|---|---|---|
| laufender Rest (W5c) | 0,1168 m | **0,3229 m** bei (56, 20) |
| Arrangement (W5d) | 0,0322 m | **0,0322 m** bei (54, 2) |

Der Rest von 0,0322 m ist nicht das Mesh: (54, 2) ist die INNENSEITE der Kurve,
wo `waterLevelAt` selbst springt (eine Haaresbreite links projiziert auf den
Ost-Schenkel, rechts auf den Nord-Schenkel, und deren Bogenkoordinaten liegen
zwei halbe Bandbreiten auseinander). Der Schnitt landet AUF dem Sprung — mehr
kann eine Fläche nicht, und es ist derselbe Sprung, mit dem die Bake das Bett
gegraben hat. Kosten: ein Stück je Knoten (255 Stücke für einen 256-Knoten-
Mäander, 15 ms), Deckel `WATER_STRIP_MAX` = 1024.

## Nachtrag 2026-08-24 (§ A16.3 / § G4): Das reliefreie Band bekommt sein eigenes Maß — W5e (Server)

> **ÜBERHOLT durch Wasser v2 K-A E6** (`HEIGHT_BAKE_VERSION` 8, Nachtrag „Der
> Rückbau der Ufer-Wächter" am Ende dieses Dokuments): das reliefreie Band UND
> die Bankklemme sind gelöscht, weil der Terrain-Vertex auf `max(h, w_level)`
> gehoben wird und beide Defekte damit im Renderer beantwortet sind. Die Zahlen
> unten bleiben als Beleg dafür lesbar, warum ein 1-m-Band nichts ausrichtete;
> die Regel und die Konstante gibt es nicht mehr.

*Befund des Users nach Bake v5: „die Wellen des angrenzenden Geländes am Rand
des Wassers" sind KOMPLETT unverändert. Der Nachtrag **ersetzt** die Breiten-
Aussage von W5d Nr. 1 (die Regel selbst bleibt); der Client ändert sich nicht.
`HEIGHT_BAKE_VERSION` **5 → 6**.*

### Die Zahl, die es überführt

W5d hat das Mikro-Relief am Wasser ausgeblendet und dafür das **`shore_ramp_m`**
der Fläche als Bandbreite genommen — mit der Begründung, die zwei Hälften eines
Ufers sollten eine Zahl teilen. Genau das war der Fehler: die beiden Zahlen
beschreiben verschiedene DINGE. Der Rampenwert sagt, wie schnell das BETT fällt;
das Band muss sagen, wie weit eine WELLE des Nachbargeländes niedergehalten
wird. Die Saat-Art `river` deklariert 1,0 m Rampe (`shared/terrain/types.json`),
`water` nimmt die 3,0 m Vorgabe — die autorierte Welle einer Wiese ist typisch
**16 m** lang. Ein 1–4-m-Band liegt damit INNERHALB einer einzigen Flanke.

Gemessen auf der Fixture von `scripts/smoke_height_bake.py` **[11h]** (See
(0,0)–(40,40), Wiese Amplitude 1,0 / Welle 16, Probe 8 m östlich des Umrisses):

| Bandbreite | Gewicht 1 m vom Umriss | Kamm 8 m draußen | Schlimmstes im 4-m-Kragen |
|---|---|---|---|
| 1 m (Saat `river`) | **1,0** | **0,968 m** | 0,772 m |
| 3 m (Vorgabe `water`) | 1,0 | **0,968 m** | — |
| 4 m (Fixture W5d) | 1,0 | **0,968 m** | — |
| **16 m (v6)** | **0,0112** | **0,484 m** | **0,121 m** |

Dreimal dieselbe Zahl: das Band hat den Kamm nie berührt, es hat nur den letzten
Meter der Flanke umgeformt. Vom Wasser aus ist das exakt „nichts hat sich
geändert".

### Die Regel (eine, `HeightModel._relief_weight`)

    Band = max(shore_ramp_m, RELIEF_SHORE_FADE_M)      RELIEF_SHORE_FADE_M = 16 m

`RELIEF_SHORE_FADE_M` ist **eine Flanke der Standardwelle**
(`models.terrain.DEFAULT_RELIEF_WAVE_M` 32 / 2, im Smoke gegen diese Konstante
geprüft, damit die beiden nicht auseinanderlaufen). Eine Welle steigt über eine
Flanke und fällt über die nächste; ein Band, das kürzer als eine Flanke ist,
kann eine Flanke nur eindellen. Das `max` sorgt dafür, dass das relieffreie Band
nie INNERHALB des Bankklemmen-Bandes endet.

**Bewusst NICHT die Welle der Nachbarfläche selbst.** Erstens spränge die
Bandbreite an jeder Grenze zwischen zwei Reliefflächen, und ein Sprung im
Gewicht ist eine Stufe im Boden — ein Uferdefekt gegen einen Naht-Riss getauscht.
Zweitens geht `relief_wave_m` bis 200 m: ein Fluss durch eine hügelige Welt
planierte dann einen 100-m-Korridor an beiden Ufern. Drittens braucht eine lange
Welle gar kein breites Band — über 16 m einer 200-m-Welle steigt der Boden nur um
etwa `Amplitude · 16/100`, das Band entlässt sie also von selbst sanft.

**Kein Ausschalter mehr.** `shore_ramp_m = 0` heißt weiterhin „Becken mit einer
Stufe als Ufer" und betrifft nur das BETT (Carve unverändert geprüft, [11e]);
für das Relief der Nachbarfläche sagt diese Null nichts. Die Regel des Users ist
ohne Ausnahme formuliert.

**Wer das Relief autoriert, ist egal** ([11i]): das Gewicht ist Geometrie gegen
den WASSER-Umriss und wird in `natural()` auf das fertige Rauschen angewandt —
die Wiese nebenan, der Wald jenseits des Flusses und eine zweite Fläche über dem
Wasser selbst werden vom selben Band verblasst.

### § G4, Rand-Hälfte: die Schranke wird nur besser

Eine Probe im Polygon wird aus den vier Ecken ihrer Gitterzelle gezeichnet; eine
Ecke AUSSERHALB liegt höchstens `step·√2` vom Umriss. Damit gilt (Fixture ohne
Höhenfläche):

    gezeichnet − Spiegel ≤ max(WATER_BANK_LIP_M, Amplitude · smoothstep(step·√2 / Band))

Der zweite Term fällt monoton in `Band` — ein breiteres Band kann die Schranke
nur senken. Auf dem 2-m-Gitter: `1,0 · smoothstep(2,83/16) = 0,083 m`, unter der
Lippe (0,1 m) und damit **konstruktiv**, wo das 4-m-Band von v5 rechnerisch
0,786 m zuließ und nur die Messung es rettete. Gemessen (**[11g]**):

| Gitter | v6 gezeichnet über dem Spiegel | ohne Verblassen (rot) |
|---|---|---|
| 2 m | 0,0828 m (≤ Lippe, konstruktiv) | 0,3892 m |
| 4 m | 0,0918 m (≤ Lippe) | 0,4260 m |
| 8 m | 0,0979 m (≤ Lippe) | 0,4463 m |
| 16 m | 0,2069 m (jenseits der Konstruktion) | 0,3571 m |

### Erreicht die Änderung eine laufende Welt?

Ja, und das ist geprüft statt angenommen (**[11j]**): `height_sig()` hasht
`code_version` = `HEIGHT_BAKE_VERSION`, die Signatur bewegt sich also allein
durch den Versionssprung; `get_field()` nimmt die gespeicherte Rasterzeile aus
`world_heightfield` NUR bei `stored.sig == sig`; die Kacheln, die der Client
zeichnet, werden per Konstruktion nie persistiert (`get_tile`), und der Client
holt Übersicht wie Kacheln neu, sobald `height_sig` im Worldmap-Payload springt.
Es gibt kein zwischengespeichertes Artefakt, das den Neustart überlebt.

---

## Nachtrag 2026-08-24 (§ A16.5 / § G2 / § G4): Das Wasser-Raster — Wasser v2, K-A E1/E2

**Entschieden (User 2026-08-24):** `recherche-wasser-v2.md` § 4 **K-A** —
„Wasser wird eine Bodenart". Der Umbau läuft in sechs Etappen
(`plan-wasser-v2-ka.md`); **hier stehen E1 (Server) und E2 (Client)**. Der
Wasserspiegel wird damit vom **gebauten Mesh** zum **abgetasteten Feld**. Was in
diesem Nachtrag steht, ist additiv: die Polygon-Meshes von § A16.8 zeichnen
unverändert weiter, der Terrain-Shader ist nicht angefasst, und `h_final`
bewegt sich um keinen Millimeter.

`HEIGHT_BAKE_VERSION` **6 → 7**. Nicht weil die Höhen anders herauskämen — der
Spiegel war immer schon Eingabe des Carve und wird jetzt zusätzlich
ausgeliefert — sondern weil die Kachel-NUTZLAST eine Funktion des Codes ist und
eine v6-Kachel gar kein Wasserfeld hat. Der Sprung ist das Einzige, was eine
laufende Welt zum Nachladen bringt (§ „Erreicht die Änderung eine laufende
Welt?").

### 1. Die Auslieferung — zweites Feld derselben Kachel

Kachelindex, Signatur, Cache, Stapelgröße und die Statistik-Persistenz sind
**unverändert wiederverwendet**. Eine Kachel trägt zusätzlich:

```jsonc
"water": {
  "level":  [[float|null, …], …],   // 129 × 129, Weltmeter; null = trocken
  "flow_x": [[float, …], …],        // optional, siehe unten
  "flow_z": [[float, …], …]
}
```

- **Der Schlüssel FEHLT**, wenn die Kachel keinen Tropfen Wasser trägt — was
  die meisten Kacheln der meisten Welten sind. Kein leeres Raster, keine Zeile
  Nullen: dieselbe Aussage, die eine nicht indizierte Kachel über die Höhe
  macht.
- **`null` ist die einzige Maske.** `level[j][i]` ist der lokale Spiegel am
  selben Stützpunkt, den `heights[j][i]` beschreibt — oder `null`, wenn dort
  kein Wasser steht. Es ist NICHT der Umriss (siehe Dilatation).
- **`flow_x`/`flow_z` fehlen GEMEINSAM**, wenn die ganze Kachel keinen Fluss
  hat. Ein stehendes Gewässer hat eine Ein-Knoten-Achse und damit exakt (0, 0)
  überall; zwei Gitter Nullen würden die Kachel verdoppeln, um nichts zu sagen.
  Abwesenheit liest sich als „(0, 0) überall".
- Rundung: `level` auf 3 Nachkommastellen wie `heights`, die Fließkomponenten
  auf 6 wie `dir_x`/`dir_z` des Profils.

### 2. Die drei Regeln des Rasters (`HeightModel.water_at`)

```
level(p) = water_level_at(profile, p)     des OBERSTEN Wassers über p
flow(p)  = water_flow_at(profile, p) · Faktor            desselben Wassers
bedeckt  = INNERHALB des Umrisses ODER innerhalb WATER_RASTER_DILATION_M
```

**„Oberstes" ist die Regel des Bodens** — die zuletzt gemalte Fläche gewinnt,
dieselbe, mit der `_kind_at` die Bodenart auflöst. **Innen schlägt dilatiert**,
in zwei Durchgängen: der Ring außerhalb eines Flusses ist eine Filter-Reparatur
und keine Autorenschaft, also muss ein Punkt, der wirklich in einem See liegt,
den See lesen, auch wenn ein später gemalter Fluss dorthin reicht.

**Der Wert im Ring ist die FORTGESETZTE Funktion**, nicht der nach außen
getragene Randwert. `water_level_at` ist überall definiert (Projektion auf eine
Polylinie plus Klemme), also bekommt ein Ringpunkt den Spiegel, den das Profil
dort hätte — und genau das macht die bilineare Mischung INNERHALB des Umrisses
exakt. Bewusst NICHT die Regel der Bankklemme (die liest den Pegel am NÄCHSTEN
UMRISSPUNKT): die Klemme ist eine Aussage über den BODEN neben dem Wasser und
darf kein Endniveau seitwärts über die Landschaft tragen, dies ist die
analytische Fortsetzung eines Feldes.

### 3. Die Dilatationsregel — zwei Gitterschritte, und die Zahl ist eine Diagonale

`WATER_RASTER_DILATION_STEPS = 2`, also **4 m** bei `TILE_STEP_M` = 2 m.

Sei `P` ein Punkt INNERHALB eines Umrisses. Ein bilinearer Lookup bei `P` mischt
die vier Ecken der Gitterzelle, in der `P` liegt. Liegt eine Ecke `C` außerhalb
des Umrisses, dann schneidet die Strecke `P→C` den Umriss in einem `Q`, also

```
d(C, Umriss) ≤ |CQ| ≤ |CP| ≤ eine Zelldiagonale = √2 Schritte = 2,8284 m
```

**Ein Schritt deckt das nicht** (eine diagonale Ecke kann 2,83 m draußen
liegen), **zwei decken es strikt**. Damit gilt konstruktiv: *jeder Punkt
innerhalb jeder Wasserfläche liest vier definierte Ecken auf dem Basisgitter.*
Ein `NaN`/`null` bedeutet **trockener Boden**, nie eine Lücke in den Daten.

**Die Garantie gilt dem Basisgitter allein**, und das ist bewusst so. Die
Mip-Pyramide des Clients dezimiert das Raster, der Ring ist also 2 Texel breit
auf Stufe 0, eines auf Stufe 1 und darüber keines mehr — während dasselbe
Diagonalargument auf jeder Stufe √2 **Texel** verlangt, d. h. 46 Basisschritte
(92 m) auf der 64-m-Stufe. Einen Spiegel 92 m ins Land zu malen würde „das
oberste Wasser über diesem Punkt" zu einer Aussage über Boden machen, den
niemand Ufer nennt — für eine Stufe, auf der ein 6-m-Fluss ohnehin keine eigene
Stützstelle mehr hat. Was eine grobe Stufe am Ufer falsch macht, deckt die
Fragment-MASKE (E4), nie ein Loch im Boden.

### 4. Die Fließregel — der Server ist jetzt die Quelle

`water_flow_at(profile, x, z, faktor)` ist die Zeile-für-Zeile-Übernahme von
`client3d/src/scene/waterPlaneMath.waterFlowAt`: Achsentangente, an jedem Knoten
über ein Fenster `min(halbe Vorstrecke, halbe Folgestrecke, 4 m)` kosinus-
geblendet, am Knoten selbst exakt die normierte Winkelhalbierende. Die Regel
wandert mit dem Mesh, das sie pro Vertex auswertete; die Zahlen bleiben
identisch (Zwillingsprüfung: `scripts/smoke_height_bake.py` [12c] — der Client
hat mit K-A E5 keinen zweiten Leser mehr, die Handrechnung steht seither
vollständig in dessen Docstring).

**Die LÄNGE ist der Fließ-Faktor** — die eigene Geschwindigkeit der Fläche geteilt
durch den `flow_speed`-Regler ihrer ART (`heightfield.water_flow_factor`, der
Zwilling von `@anima/scene-render waterFlowFactor`). Eine Fläche ohne eigenen
Wert antwortet exakt 1, das Raster trägt dann die reine Einheitstangente.
Warum ein Verhältnis und nicht die absolute Geschwindigkeit: der Regler der ART
ist eine MATERIAL-Zahl, und eine Fläche darf nur skalieren, was das Material
schon trägt.

### 5. Signatur und Statistik

- **`height_sig` deckte die Wasser-Eingaben bereits** (`water_basis`: Polygon,
  Pegel, Endniveaus, Bearing, `flow_along`, Linie, Breite, Tiefe, Uferrampe) —
  **mit zwei Lücken, die dieser Umbau geschlossen hat**: `meta.flow_speed_m_s`
  der Fläche und der `flow_speed`-Regler ihrer Art waren bis hierher reine
  Optik, von niemandem gehasht. Jetzt SCHIFFT die Kachel den Fließvektor, also
  sind beide Bake-Eingaben und stehen in `water_basis`. Sie sind die einzigen
  Einträge dieser Signatur, die `h_final` um keinen Millimeter bewegen.
- **`world_height_tile_stats` bleibt gültig.** `min`/`max`/`err` werden
  ausschließlich von `heights` abgelesen (`tile_stats_from`), und der Pegel
  ändert `h` nicht — die Zeilen bleiben also wahre Aussagen über ihr Raster.
  Sie werden trotzdem neu berechnet, weil die Signatur (ihr Schlüssel) sich mit
  `HEIGHT_BAKE_VERSION` bewegt; das ist der normale Weg und keine Migration.

### 6. Die gemessene Zahl: muss das Wasser-Raster feiner als 2 m sein?

**Nein.** Gemessen auf der Haarnadel-Fixture (`smoke_height_bake.py` [8k]/[12d];
drei Klicks A(150,300) → B(249,280) → C(201,260), 6 m breit, Maske
(140,250)-(300,315)), bilinear gelesen gegen `water_level_at` an 321 × 321
Proben innerhalb der Maske:

| Gitter | größte Abweichung | davon auf „glatten" Zellen |
|---|---|---|
| **2 m** | **3,4347 m** | **0,0177 m** |
| 1 m | 3,3638 m | 0,0088 m |
| 0,5 m | 3,5273 m | 0,0015 m |

„Glatt" heißt: alle vier Zellecken UND die Probe projizieren auf dasselbe
Achsensegment, es läuft also keine Mittelachse durch die Zelle.

**Die Lesart, und sie ist eindeutig:**

1. Auf ihrem eigenen Gitter ist das Raster nicht „nah an" der Funktion, es IST
   sie — Abweichung exakt 0 an jedem Stützpunkt.
2. Die 3,4 m sind ein **Sprung von `water_level_at` selbst**. An der Innenseite
   einer Haarnadel projiziert ein Punkt eine Haaresbreite links auf Schenkel 1
   und rechts auf Schenkel 2; die Bogenkoordinaten unterscheiden sich um fast
   die ganze Kehre. Gemessen fällt der Pegel bei z = 277,727 zwischen
   x = 225,80 und x = 225,90 von 8,4414 auf 7,1463 — **1,2951 m über zehn
   Zentimeter**. Halbieren und Vierteln des Gitters ändert die Zahl nicht
   (3,36 / 3,53): *keine Auflösung löst einen Sprung auf.*
3. Fern der Mittelachse ist das 2-m-Raster **auf 1,8 cm genau** und verhält
   sich wie eine bilineare Lesung muss — zweiter Ordnung im Schritt
   (0,0177 → 0,0088 → 0,0015).

Ein feineres Wasser-Raster kauft also nichts. Der Rest ist eine Unstetigkeit
des autorierten Spiegels und Sache der Fragment-Maske (E4), nicht der
Payload-Auflösung. (Der W5d-Wert 0,0322 m stammt von der Bogen-Fixture von
`smoke_water_plane.mjs` [5d] und beschreibt dieselbe Klasse: die Kante landet
AUF dem Sprung, was das Beste ist, was eine Fläche kann.)

### 7. Client (E2) — Pyramide, Zwilling, Dezimierung

- `client3d/src/scene/waterRaster.ts` hält das Feld je Kachel
  (`WaterRaster`), wandelt `null` an der Wire-Grenze EINMAL in `NaN` und liefert
  `rasterLevelAt` / `rasterFlowAt`. Die Leiter hat **keine Übersichts-Sprosse**:
  das Übersichtsgitter trägt kein Wasser, also ist ein Punkt außerhalb der
  geladenen Kacheln „hier ist kein Wasser bekannt".
- **Die maskierte Mischung** (`waterBilinear`): eine Ecke mit Gewicht 0 wird
  NICHT gelesen. Reines Fließkomma würde ihr `NaN` über `NaN · 0 = NaN`
  weitertragen — und das ist kein Rundungsdetail: die Pyramide wird AN den
  Gitterpunkten gefüllt (`tx = 0`), der Ring verlöre also sein äußerstes Texel,
  die Dilatation fiele von 2 auf 1 Schritt und damit unter das √2, das die
  Garantie oben braucht. Ergebnis: Löcher im Wasser entlang eines Gitters von
  Linien.
- **Die Wasser-Pyramide ist `buildPyramid`**, ohne eigene Regel:
  - **Dezimierung = TEILMENGE, kein Mittelwert.** Der Spiegel ist stückweise
    LINEAR, also IST jeder zweite Stützpunkt der Spiegel auf dem groben Gitter
    — dasselbe Argument, das § G2 für die Höhen führt. Ein Boxfilter erzeugte
    eine Fläche, die kein Profil beschreibt, und verschmierte das Ufer (er
    mischte am Randtexel den Pegel mit seinem dilatierten Nachbarn). `min` wäre
    ebenso eine andere Fläche und ist unnötig: unter K-A wird der Boden auf
    `max(h, level)` gehoben, der Spiegel muss nicht pessimistisch sein.
  - **Ein grobes Texel ist genau dann Wasser, wenn sein eigenes Basistexel es
    ist.** Die Maske dezimiert MIT dem Pegel, weil sie der Pegel IST (`NaN`).
    Jede andere Regel („Wasser, wenn EINES der vier", „…wenn ALLE vier") wäre
    ein zweites Buch darüber, wo das Wasser steht.
- `wlevelAt(pyr, x, z, k)` ist der CPU-Zwilling des GLSL, das E3 neben
  `tlodHeight` gestellt hat (`tlodWaterAt`); die Uniformen `uTlodWater`,
  `uTlodWaterGeom`, `uTlodWaterLevel` sind gebunden und aktuell und werden seit
  E3 **von der Wasser-Variante des Terrain-Programms gelesen** (Punkt 7a). Es
  gibt **keinen FERN-Zwilling** (Punkt 7 oben).

### 7a. Client (E3) — der Vertex-Hub, als ZWEITE Materialvariante

Der Terrain-Vertex landet auf `y = max(h, w_level)`, wo das Raster einen Pegel
hat. Vier Entscheidungen, alle in `client3d/src/scene/terrainLod.ts`:

- **Zwei Programme, nicht eines.** Die Risiko-Regel aus `recherche-wasser-v2.md`
  § 4 K-A ist bindend: trockener Boden darf für das Wasser nichts zahlen. Der
  Besitzer baut deshalb ZWEI Materialien durch dieselbe Kette
  (`ground.rebuildBase`), `patchTerrainLod(mat, water)` hängt den Hub nur an
  eines davon, und der `customProgramCacheKey` des trockenen bleibt Zeichen für
  Zeichen `…+terrain-lod` — three gibt ihm damit dasselbe `WebGLProgram` wie
  vorher. Gezeichnet wird als zweiter Draw-Call aus einem zweiten
  Instanz-Puffer, dessen Mesh KIND des trockenen ist (Sichtbarkeit und Lebens-
  dauer bleiben „das Terrain", ganz).
- **Das Tor ist die Kachelliste des Wasser-Rasters** (`nodeHasWater`): ein Stück
  bekommt die Hub-Variante, wenn sein GESCHLOSSENES Rechteck eine Kachel mit
  `water`-Feld berührt — `floor((x + size) / tile_m)`, ohne das `− 1e-6` von
  `nodeBounds`. Damit gehört ein von zwei Stücken geteilter Vertex zu BEIDEN
  Kachelspannen, beide laufen durch dasselbe Programm, und ein Riss an der Naht
  ist konstruktiv unmöglich. (Der Server garantiert die andere Hälfte: eine
  Kachel ohne `water`-Schlüssel hat in ihrem ganzen Fenster inklusive Rändern
  keinen nassen Stützpunkt — `water_raster` antwortet sonst nicht None.)
- **Der max wird PRO STUFE genommen, der Morph über das Paar**:
  `y = mix( max(h₁,w₁), max(h₂,w₂), f )`, jede Lesung an ihrem eigenen
  `nodeStep · 2^k`. Die andere Reihenfolge (erst die Spiegel mischen, dann ein
  max) springt am Ufer um `level − h`, sobald `f` die 0 verlässt, weil die
  maskierte Mischung eines nassen mit einem trockenen Texel für jedes Gewicht
  > 0 trocken ist — gemessen 0,25 m auf der Ufer-Fixture.
- **λ wird NIE gehoben.** `tlodMorphAt` misst weiter gegen `tlodHeight(p, 0.0)`,
  also lesen beide Varianten dieselbe Morph-Koordinate und setzen einen
  geteilten Vertex auf denselben Punkt.
- **Trockentest ist `( w > h ) ? w : h`, nie `max()`**: das Sentinel ist das
  `NaN` aus der Textur, und GLSL legt nicht fest, welchen Operanden `max` bei
  einem NaN liefert.
- **Statistik unangetastet.** `min`/`max`/`err` bleiben höhenrein (Punkt 5). Der
  gehobene Spiegel kann über die Box eines Knotens ragen (höchstens um die
  Wassertiefe dort) — das kostet nur LOD-DISTANZ, seit der Frustum-Cull weg ist,
  und `|max(a,b) − max(c,d)| ≤ max(|a−c|,|b−d|)` hält den Stufenfehler unter
  `max(err_h, err_w)`; der Carve schreibt die Spiegel-Variation ohnehin in das
  Bett, ein gehobener Spiegel ist also FLACHER als das Bett, das er deckt.
- **Die Wasser-Schattierung kam in E4** (siehe Abschnitt 9): in E3 wurde ein
  gehobenes Pixel noch als der Boden gemalt, den es ersetzt. Die Polygon-Spiegel
  zeichnen bis E5 weiter. Isolationsschalter **22** (`uTlodNoWater`, Uniform
  statt Define) nimmt den Hub live heraus — und seit E4 die Schattierung mit
  ihm, über dasselbe Uniform.

### 8. Die Beweise (§ B5a)

| Was | Wo |
|---|---|
| Raster = `water_level_at` auf dem Gitter, Dilatation, Diagonale | `scripts/smoke_height_bake.py` [12a]/[12b] |
| Fließvektor = die Zahlen, die der Client vor K-A trug, Faktor | [12c] (Handrechnung dort; der Client-Zwilling ist mit E5 gelöscht) |
| Kurveninnenseite: 2 m gegen 1 m gegen 0,5 m | [12d] |
| Payload additiv, Flussfelder optional | [12e] |
| Statistik ist höhenrein | [12f] |
| Client liest die Server-Tabellen zurück, maskierte Mischung | `client3d/scripts/smoke_world_height.mjs` [W1]–[W4] |
| Pyramide: Teilmenge, Sentinel, Ringverlust je Stufe, Uniformen | `client3d/scripts/smoke_terrain_lod.mjs` [15] |
| Hub `max(h, w)`, Ring-Sonden, Reihenfolge des Morphs, Tor | `client3d/scripts/smoke_terrain_lod.mjs` [16] |
| Zweite Variante: GLSL-Pins, Cache-Key, `uTlodNoWater` | `client3d/scripts/smoke_terrain_lod.mjs` [17] |

### 9. Die Wasser-Schattierung im Terrain-Fragment (K-A E4)

**Kein Payload ändert sich.** E4 ist reine Client-Darstellung: derselbe Bake,
dieselben Kacheln, dieselbe zweite Materialvariante. Was dazukommt, ist die
Antwort auf „wie sieht ein gehobenes Pixel aus" — bisher: wie der Boden, den es
ersetzt.

**Single-Layer-Water (Recherche § 3.3).** Ein Wasserpixel wird nicht mehr
gemischt, sondern **im selben opaken Durchgang** schattiert: der Shader, der das
Bett gerade texturiert hat, mischt das Wasser selbst dazu. Die Reihenfolge im
Fragment, in Shader-Reihenfolge:

1. nach `#include <metalnessmap_fragment>` — `tlodWaterSurface()`: Absorption
   über die Tiefe auf die **Albedo** (nicht auf das fertige Licht: sonst wäre
   tiefes Wasser ein flacher, unbeleuchteter Fleck, der nachts hell bliebe),
   dazu Rauheit und Metallizität des Wassers, alles über **einen** Faktor `twA`;
2. in `#include <normal_fragment_begin>` — `tlodWaterNormal()`: die
   Ripple-Normale statt der Bodennormale, über denselben Faktor geblendet;
3. vor `#include <opaque_fragment>` — `tlodWaterOut()`: Fresnel-Himmelsanteil
   und Schaumband, die beiden Dinge, die keine Albedo sind.

**Die Tiefe ist ein Varying, keine Textur-Lesung.** Der Vertex kennt Bett und
Spiegel bereits (`h1/h2` gegen `l1/l2`), also fährt
`vTlodWet = mix(l1 − h1, l2 − h2, f)` mit. Das ist exakt die Differenz der
beiden linearen Interpolanten, die das Dreieck wirklich zeichnet — die
Uferlinie liegt also genau dort, wo der gezeichnete Spiegel das gezeichnete
Bett verlässt, und die 4 `texelFetch`, die der Mesh-Shader je Pixel für
`tlodHeight` ausgab, entfallen ersatzlos.

**Die Kurven sind die des Spiegels**, Konstante für Konstante:
`waterShoreAlpha` (¾ der eigenen Bettiefe, W4b) ist jetzt die Absorption,
`waterFoam`/`WATER_FOAM_BAND_M`/`_STRENGTH` das Schaumband,
`waterEdgeFade` die Randrampe (ohne sie stünde der weiße Schaum als Stufe an
der Wasserlinie, weil `waterFoam(0) = 1` ist). Ripple, Anisotropie, die zwei
Geschwindigkeiten und die Wellen-Normalmap kommen unverändert aus
`@anima/scene-render materials.ts` — die Textur wird **geteilt**, nicht
nachgebaut.

**Welche Wasserart ein Pixel ist**, beantwortet die **id-Maske des
Layer-Compositors**: sie nennt je Texel das Paar (oben, darunter) und sagt
nichts darüber, auf welcher Seite man steht — was hier reicht, weil ein Pixel,
das gehoben wurde, definitionsgemäß im Wasser steht: die **Wasserhälfte** des
Paars ist seine Art. Je Layer-Index liegt eine Zeile in einer kleinen
`3 × n`-RGBA32F-Tabelle (Tint/`sky_mix`, `wave_m`/`speed`/`flow_speed`/
Deckkraft-Tiefe, Rauheit/Metallizität/`is_water`). Zeilen, die kein Wasser sind,
tragen den Look des **ersten** Wassers der Welt, damit ein Randpixel Wasser
zeichnet und nicht den Ton einer Wiese.

**Die Deckkraft-Tiefe ist damit pro ART und nicht mehr pro FLÄCHE** — eine echte
Verengung gegenüber W4b, weil die Maske Arten kennt und keine Flächen. Die
zuletzt gemalte Fläche einer Art gewinnt (die Regel, die der Server bei
überlappenden Gewässern selbst benutzt). **E6 hat entschieden, dass das so
bleibt** (Begründung im Nachtrag „Der Rückbau der Ufer-Wächter": der Look ist
ein Art-Datensatz, ein billiger Rasterkanal mischte am Ufer gegen 0 und deckte
die Wasserlinie zu, und der Gewinn wäre eine Art, die zweimal mit
verschiedenen Tiefen gemalt wurde) — wer eine andere Deckkraft braucht, malt
eine eigene ART.

**Der Fließvektor** fährt als zweites Datenfeld neben dem Pegel mit
(`uTlodFlow`, RG32F, **nur Stufe 0** derselben Lattice) und wird **im Fragment**
gelesen (`waterShade.twFlowAt`, am eigenen XZ des Pixels, 4 `texelFetch`
bilinear auf Stufe 0). Seine LÄNGE ist der Geschwindigkeitsfaktor der Fläche,
`(0,0)` ist stilles Wasser.

**Warum nicht im Vertex** (Nachtrag 2026-08-27, vorher stand hier genau das):
Die Richtung ist glatt, ein Varying lag also nahe — nur ist das Feld es nicht.
Der Server schreibt den Fluss ausschließlich ins Gewässer plus die 4 m
Dilatation des Bakes, und die Vertices eines Terrain-Stücks stehen
`baseStep · 2^level` Meter auseinander: 2 m auf Stufe 0, 16 m auf Stufe 3,
64 m auf Stufe 5. Ein 6 m breiter Fluss ist mit Dilatation ein 14 m schmales
Band — aus 16 m Abstand können **alle vier** Ecken einer Zelle daneben liegen,
das Varying ist dann exakt `(0,0)`, und `twRipple` nimmt seinen STILL-Zweig:
gezeichnetes stehendes Wasser, während die Punkt-Messung der Debug-Zeile am
selben Ort 2 m/s meldet. Das ist kein Randfall, sondern die Mehrheit der
Ausrichtungen ab Stufe 4. Der Fragment-Tap kennt die Stufe gar nicht und kann
deshalb nicht kollabieren. `tlodFlowAt` und `vTlodFlow` sind ersatzlos
gelöscht; der TS-Zwilling der GPU-Lesung heißt `terrainLod.gpuWaterFlowAt`.

**Der Admin-Grundriss ist davon nicht betroffen.** Die Vorschau rendert das
Wasser weiter als Spiegel-Mesh aus `packages/scene-render/materials.ts`, mit
einem konstanten `aWaterFlow` je Fläche und ohne LOD — es gibt dort weder
Lattice noch Stufen, an denen etwas ausfallen könnte.

**Was das trockene Programm kostet: nichts.** Die dry-Variante bekommt weder
Chunk noch Uniform noch Anker dazu; ihr Fragment ist Zeichen für Zeichen das
von vorher (Beweis: `smoke_terrain_lod.mjs` [18]). **Was das nasse Programm
kostet:** ein trockenes Pixel innerhalb der nassen Variante zahlt zwei
Ableitungen und einen Vergleich; ein Wasserpixel zahlt seit dem Umzug **+4
`texelFetch` im Fragment**, dafür fallen im Vertex **−4** weg (das wet-Vertex-
Programm sinkt von 20 auf 16 Fetches, das dry bleibt unberührt).

**Zurückgegebene Arbeit:** wo `twA == 1` (ab der Deckkraft-Tiefe) ist die
Bodennormale unsichtbar und wird **nicht berechnet** — `tlodNormalAt` sind 16
`texelFetch`, die dort entfallen. Die zweite Hälfte der Recherche-Erwartung
(ein Slice statt vier in `lcSurface`) ist **nicht** umgesetzt: sie säße in
`@anima/scene-render layerCut.ts`, also im geteilten Compositor, und würde das
trockene Programm mitverändern.

| Was | Wo |
|---|---|
| Absorption, Schaumband, Randrampe, Tint-Mix (Handtabellen) | `client3d/scripts/smoke_water_shade.mjs` [1]–[3] |
| Look-Tabelle = die Defaults des Spiegels, Packung | ebenda [4] |
| Flow-Frame: Identität bei Stille, 3:1 stromauf | ebenda [5] |
| GLSL-Pins: Reihenfolge, Konstanten, `textureGrad`, Maskenpaar | ebenda [6] |
| Fließvektor im Fragment: `twFlowAt` = Punktmessung auf jeder Stufe, das zurückgebaute Vertex-Blend geht ab Stufe 3 still | `client3d/scripts/smoke_flow_lod.mjs` |
| Trockenes Programm unverändert, drei Einfügepunkte, Uniformen | `client3d/scripts/smoke_terrain_lod.mjs` [18] |
| Tiefen-Varying, `liftedDepth`, und dass es KEIN Flow-Varying mehr gibt | ebenda [17] |

### 10. Der Rückbau des Spiegels (K-A E5)

**Es gibt kein Wasser-Mesh mehr.** E3 hebt den Terrain-Vertex auf
`max(h, w_level)`, E4 schattiert dasselbe Pixel als Wasser — die zweite,
transparente Fläche darüber war seither ein Doppel, und E5 löscht sie samt
allem, was nur sie gebraucht hat:

| Was | Wo es stand |
|---|---|
| `buildWaterPlane`, `earcutStrips`, `patchWaterShore`, `WATER_SHORE_CACHE_KEY` | `client3d/src/scene/waterPlane.ts` (Datei gelöscht) |
| `addMirror`, die Material-Karte je Wasser-Art, die Wasser-Mesh-Liste, der Textur-Preload der Flächen-Stufe, `materialFor` | `client3d/src/scene/ground.ts` |
| `liftToWaterProfile`, `subdivideRibbonByAxis` (+ `crossNormalAt`, `clipHalfPlane`, `ringSignedArea`, `WATER_STRIP_MAX`, `WaterPoint2`), `waterFlowAt` (+ Blend-Fenster), `waterShoreGlsl`, `waterShoreBody`, `waterAlpha`, `WATER_SHORE_BAND_M`, `WATER_FOAM_ALPHA` | `client3d/src/scene/waterPlaneMath.ts` |
| `isWaterClass` — die Ausnahme, mit der Natur-Boden und Schleier dem Wasser-Material auswichen | `client3d/src/scene/naturalGroundMath.ts` |
| Attribute `aWaterFlow` / `aWaterOpaque`, der Ufer-`discard`, `depthWrite: false` und die Transparenz-Sortierung des Wassers | ebenda, mit den Meshes |

**Was bleibt und WARUM:** `waterProfileOf` / `waterLevelAt` (Spielmechanik:
`floatRootY`, `typeAt`, Waten/Schwimmen — dort muss der Pegel exakt sein, nicht
gerastert; dazu die Wasserfall-Erkennung und die Look-Tabelle), die Uferkurven
`waterOpaqueDepthM` / `waterShoreAlpha` / `waterFoam` / `waterEdgeFade` samt
ihren Konstanten (das Terrain-Fragment schattiert mit genau diesen Zahlen), und
der Fließ-FAKTOR `waterFlowFactor` im geteilten Paket — er ist jetzt die
Kodierung, die der Server in das Raster bäckt und die der Terrain-Shader als
Länge zurückliest.

**Der Wasserfall bleibt, und hängt jetzt am Raster-Material statt am Spiegel.**
`waterfallsFrom(profile, strokeWidthM(meta))` liest weiter die Achse aus der
Nutzlast — die Erkennung ist unberührt. Neu ist nur die Herkunft der
Wellennormalen des Vorhangs: `buildWaterfall(fall, sink)` holt sie mit
`surfaceWaveNormal(THREE)` direkt aus `@anima/scene-render materials.ts`, also
genau die Textur, die auch das Terrain-Fragment scrollt (Punkt 9), statt sie vom
Material des Spiegels abzulesen. Die Vorhänge und Schaumscheiben sind damit die
EINZIGEN Meshes, die eine gemalte Wasserfläche noch erzeugt — ein Blatt in der
Luft ist das eine, was ein Höhenfeld nicht sein kann. Sie leben und sterben mit
den Flächen (`ground.clearAreas`).

**Isolationsschalter 11** heißt darum nicht mehr „Water planes hidden", sondern
„Waterfalls hidden": die Wasser-OBERFLÄCHE ist Teil des Terrains und wird mit
Schalter 22 (`noWater`) abgeschaltet.

**Die Beweise (§ B5a):** `smoke_water_plane.mjs` behält die Abschnitte mit
Lesern — Profil [1], Uferkurven [2]/[2a]/[2b]/[2d], Carve-Invariante [3], die
Fixtures [4]/[4b]/[4d]/[4e], Waten/Schwimmen [6], Uferneigung [7] — und zählt
in [8] die gelöschten Namen als ROTE Proben mit. Gestrichen sind die
Mesh-Abschnitte [2c] (Ufer-GLSL), [4c]/[4d-flow]/[4e-flow]/[4f] (der
Per-Vertex-Fließvektor; der Server prüft die Regel jetzt in
`scripts/smoke_height_bake.py` [12c]), [5]/[5b] (der Lift) und [5c]/[5d] (die
Streifen). `smoke_waterfall.mjs` prüft die neue Herkunft der Wellennormalen,
`smoke_layer_cut.mjs`, `smoke_natural_ground.mjs`, `smoke_surface_patch.mjs` und
`smoke_fog_veil.mjs` prüfen die eine verbliebene Material-Kette.

---

## Nachtrag 2026-08-24 (§ A16.3 / § G4): Der Rückbau der Ufer-Wächter — Wasser v2, K-A E6 (Server)

*Letzte Etappe des K-A-Umbaus. `HEIGHT_BAKE_VERSION` **7 → 8**: die Höhen
kommen für unveränderte Daten anders heraus, jede laufende Welt bäckt neu.*

### Was gelöscht ist

Zwei Bake-Stempel haben zwischen v4 und v7 den Rand jedes Gewässers geformt.
Beide waren gegen **ein** Symptom der Mesh-Ära geschrieben — der Spiegel war
eine eigene, durchsichtige FLÄCHE, und der Boden daneben wusste nichts von ihr:

| Weg | Was er tat | Warum er sterben kann |
|---|---|---|
| **Bankklemme** (v4): `_bank_clamp`, `WATER_BANK_LIP_M`, `water_bank_box`, `_ring_nearest_point` | hielt den Boden im `shore_ramp_m`-Band AUSSERHALB des Umrisses auf mindestens `water_level_at(nächster Umrisspunkt) + 0,1 m`, mit linear ausblendendem Minimum | Boden unter dem Spiegel ist kein Loch mehr, sondern **Bett**: der Terrain-Vertex wird auf `max(h, w_level)` gehoben (E3), der Spiegel steht also nirgends mehr in der Luft |
| **Relief-Fade** (v5/v6): `_relief_weight`, `_relief_fade_width`, `RELIEF_SHORE_FADE_M` | nahm das Mikro-Relief über einen Kragen von `max(shore_ramp_m, 16 m)` auf 0 zurück, innerhalb des Polygons ganz | Boden ÜBER dem Spiegel am Rand ist kein Loch mehr, sondern ein **Fels im See** — es gibt keine Platte, in die er ein Loch schneiden könnte |

`h_final` hat damit wieder **drei** Stufen (`natural → carve → plateaus`), und
ein Gewässer schreibt nur noch INNERHALB seines eigenen Umrisses. Kein
Rückfall-Leser, kein Alias, keine Konfiguration: die Namen sind weg und werden
namentlich als ROTE Proben geführt (`scripts/smoke_height_bake.py` **[10a]**).

**Die Box, die eine Wasserfläche noch beansprucht** (`shaped_boxes`, Kachel-
Index, Gitterwachstum), ist der Umriss **plus `WATER_RASTER_DILATION_M` = 4 m**
statt plus `shore_ramp_m`. Das ist keine Kosmetik: was ein Gewässer außerhalb
seines Umrisses noch schreibt, ist der **Dilatationsring** des Rasters, und eine
Kachel, in die der Ring hineinreicht, muss indiziert sein — sonst endet der Ring
an einer Kachelgrenze, also genau der bilineare Defekt, gegen den die Dilatation
existiert. Die alte, mit `shore_ramp_m` gewachsene Box deckte ihn nie (ein
legales `shore_ramp_m = 0` wuchs gar nicht).

### § G4, Rand-Hälfte — neu, und konstruktiv statt gemessen

> **Die Rand-Hälfte von § G4 ist keine Schranke mehr, sondern eine Aussage über
> den Vertexshader.** Was ein Renderer über Wasser zeichnet, ist
> `y = max(h, w_level)` pro Morph-Abgriff (K-A E3) — **auf jeder gezeichneten
> Stufe ist die Oberfläche eines Wasser-Texels also der Spiegel**, und der
> existiert überall dort, wo die Basismaske Wasser sagt: die Wasser-Pyramide
> DEZIMIERT als **Teilmenge** eines stückweise linearen Feldes und ein grobes
> Texel ist genau dann Wasser, wenn sein eigenes Basis-Texel es ist (K-A E2,
> `buildWaterPyramid`) — kein Mittelwert, kein `min`, keine zweite Maske. Daraus
> folgt beides ohne Messung: Boden UNTER dem Spiegel kann nicht gezeichnet
> werden (der `max` gibt den Spiegel zurück, es entsteht keine Lücke zwischen
> Wasser und Land), und Boden ÜBER dem Spiegel wird als das gezeichnet, was er
> ist — Fels im Wasser, kein Loch in einer Platte. Der Preis dieser Aussage ist
> benannt: der Ring ist auf Stufe 0 zwei Texel breit, auf Stufe 1 eines und
> darüber keines, die Garantie gilt also auf dem BASIS-Gitter; was eine grobe
> Stufe am Ufer verfehlt, deckt die Fragment-MASKE (K-A E4), nie das Gelände.
>
> **Die Tiefen-Hälfte (Invariante 2) bleibt wörtlich stehen:** jenseits der
> Ufer-Rampe liegt der Boden punktweise mindestens `ε` unter
> `water_level_at(x, z)`, in JEDEM Raster. Sie ist die Aussage über den CARVE
> und der Carve ist unverändert.
>
> **Die Dilatationsregel** (unverändert seit E1, hier als Teil von § G4
> festgeschrieben): Pegel- und Fließraster müssen mindestens
> `WATER_RASTER_DILATION_STEPS` = 2 Gitterschritte über jeden Umriss hinaus
> fortgeschrieben sein, weil eine Zellecke eines nassen Punktes höchstens eine
> Zell-DIAGONALE (√2 Schritte) außerhalb liegt; ein Schritt deckt das nicht,
> zwei decken es strikt.

Geprüft in `scripts/smoke_height_bake.py` **[10e]**: das 4-/8-/16-m-Gitter des
Wasserrasters ist Texel für Texel jedes 2./4./8. Basis-Texel (Pegel wie
Trocken-Sentinel), und über 7 857 nasse Proben ist `min(max(h, w) − w)` exakt
**0,0** — nichts wird unter seinem eigenen Spiegel gezeichnet, obwohl 7 497
dieser Proben im BAKE darunter liegen.

### Was zurückkommt — und was es kostet

**Das Relief läuft wieder bis an die Wasserlinie** ([11a]–[11d], Fixture See
(0,0)–(40,40) + Wiese Amplitude 1,0 / Welle 16):

| | v6 (Kragen) | v8 (Rückbau) |
|---|---|---|
| Boden 1 m außerhalb des Umrisses | 1,1 % der Welle | **100 %** |
| Schlimmste Welle im 4-m-Kragen | 0,1206 m | **0,772 m** |
| Abgeleiteter Spiegel (Rand-Median) | exakt 0,0 (relieffreier Rand) | **0,1504 m**, Spannweite des Randes **1,344 m** |
| Höchster Randpunkt über seinem Spiegel | 0,0 m | **0,466 m** — und das ist jetzt ein Fels, kein Loch |

**Der Preis, als Zahl statt als Überraschung** ([10g]): ein Ufer, das unter dem
Spiegel liegt, wird als Wasser gezeichnet, solange das Raster dort einen Pegel
hat — also **bis zu 4 m über den autorierten Umriss hinaus**, und dort hört die
Wasserfläche mit einer Stufe in Höhe der getragenen Tiefe auf (Fixture: 1,4 m).
Die Bankklemme hat das nie verhindert (ihr Band ist `shore_ramp_m`, in der
Vorgabe 3 m < 4 m, und darf 0 sein); sie hat nur den Boden, den sie deckte, hoch
genug gemacht, dass er nicht hob. Wer die Wasserlinie exakt am gezeichneten
Umriss haben will, malt das Ufer nicht unter den Spiegel — das ist eine
Autoren-Aussage und keine Bake-Regel mehr.

**Der Unterwasser-Geist stellt dieselbe Frage wie das Wasser** (Befund
2026-08-27, Nachtrag zu diesem Preis): Ein Ding steht genau dann im Wasser, wenn
Pegel UND `waterInside(sd)` es sagen — dasselbe Paar, aus dem `liftedHeight` den
Wasser-Lift bildet (`ground.waterGhostAt` → `walk.ghostWaterLevel` +
`walk.ghostCutY`, geprüft in `smoke_walk_math.mjs`). Ein für sich gelesener
Pegel ist NIE eine Maske: er ist 4 m über jeden Umriss hinaus dilatiert, und der
Boden in diesem Kragen liegt seit dem Rückbau bis zu 0,772 m darunter — also
weit über den 0,05 m des Geist-Gates, weshalb ein Diorama auf dem trockenen Ufer
halbtransparent geisterte, während die Figur daneben (sie liest den
Polygon-Test `ground.typeAt`) fest blieb.

### Begehung und Navigation

`world_height` liefert am Ufer jetzt Boden, der unter dem Spiegel liegen darf.
Das ist für die Gates folgenlos und geprüft: **Waten/Schwimmen** liest das
PROFIL (`water_level_at`, exakt, nicht das Raster) und nicht `h`, **Steigung
und Stufe** lesen `h` — und `h` ist am Ufer jetzt glatter als vorher, weil die
0,1-m-Lippe entlang jeder Uferlinie weg ist. Gemessen in
`scripts/smoke_nav_grid.py`: der 30-m-Weg ins Seedorf kostet wieder
**53,0 s** = 20 s Gras + 25 s Waten + 4 s/m · 2,0 m Abstieg ins Bett (v4–v7:
53,664 s, weil die Lippe 0,166 m Auf und Ab dazugab). `smoke_slope_gate.py`
ist unberührt — es misst Plateau-Rampen.

### Die Deckkraft-Tiefe bleibt PRO ART — Entscheidung, nicht Vertagung

E4 hatte vorgemerkt, `water_depth_effective` pro FLÄCHE im Wasserraster
mitzuliefern, weil die id-Maske nur Arten kennt. **Entschieden: sie bleibt pro
Art**, und das ist ab hier die stehende Regel, kein offener Punkt.

Gründe, in dieser Reihenfolge:

1. **Der Wasser-Look IST ein Art-Datensatz.** Tint, `sky_mix`, `wave_m`,
   `speed`, `flow_speed`, Rauheit und Metallizität kommen alle aus der
   Surface-Bibliothek und können gar nicht pro Fläche sein. Ein Texel-Kanal für
   das achte Feld machte EINEN Wert flächenscharf, während der Farbton, in den
   er hineinblendet, artscharf bleibt.
2. **Der billige Kanal wäre falsch.** Der Fließvektor fährt plain-bilinear
   (der Server schreibt (0, 0) auf trockenen Punkten); eine Tiefe, die an
   trockenen Ecken gegen 0 mischt, ergäbe `opaque_depth → 0` und damit
   Absorption **1** genau an der Wasserlinie — ein deckender Saum am Ufer, also
   die Defektklasse, gegen die die Stufe angetreten ist. Korrekt getragen
   bräuchte sie die MASKIERTE Mischung des Pegels: entweder einen vierten Kanal
   auf der R32F-Pegelpyramide (4× Texturspeicher auf JEDER Stufe) oder vier
   zusätzliche `texelFetch` je Vertex. Beides ist nicht „billig".
3. **Nutzlast.** Ein viertes Feld je nassem Texel ist rund +33 % auf jede nasse
   Kachel, dauerhaft, für eine Zahl, die je Fläche konstant ist.
4. **Der Gewinn ist eine Art, die ZWEIMAL mit verschiedenen Tiefen gemalt
   wurde.** Dann gewinnt die zuletzt gemalte Fläche (die Regel, die der Server
   bei überlappenden Gewässern selbst benutzt), und der Unterschied ist, wie
   schnell das Bett verschwindet — nicht, wo Wasser ist und wie tief man watet
   (beides liest das exakte Profil).

Wer eine erkennbar andere Deckkraft braucht, malt eine eigene ART — das ist im
Autorenmodell der vorgesehene Weg und kostet nichts.

### Die Beweise (§ B5a)

| Was | Wo |
|---|---|
| Namen weg, `final` dreistufig, Version 8 | `scripts/smoke_height_bake.py` **[10a]**, **[10c]** |
| Band außerhalb des Umrisses = autorierter Boden, Bett unverändert | ebenda **[10b]**, **[10d]** |
| § G4-Rand-Hälfte: Teilmengen-Dezimierung + `min(max(h,w) − w) = 0` | ebenda **[10e]** |
| Ring-Box, Dilatationsbreite, der 4-m-Preis mit seiner Stufe | ebenda **[10f]**, **[10g]** |
| Relief bis an die Wasserlinie, wobbelnder Rand-Median, Kragen zurück | ebenda **[11a]**–**[11d]** |
| 0-Rampen-Becken unverändert, Signatur erreicht die laufende Welt | ebenda **[11e]**, **[11f]** |
| Wegkosten am See: 53,0 s statt 53,664 s, von Hand hergeleitet | `scripts/smoke_nav_grid.py` |

---

## Nachtrag 2026-08-24 (§ B5a): Zwei Sichtbefunde am K-A-Wasser — Schaum-Deckung und Vorhang-Verdeckung (Client)

*Reine Renderer-Korrekturen. Keine Nutzlast, kein Bake, keine Signatur ändert
sich; `HEIGHT_BAKE_VERSION` bleibt **8**.*

### 1. „Weiße Ränder und Ecken am Wasserrand" — der Schaum hat seine Deckung verloren

Der Spiegel war eine DURCHSICHTIGE Fläche: er weißte sein eigenes Licht mit
`foam · WATER_FOAM_STRENGTH` und wurde danach mit
`alpha = clamp(shoreAlpha + foam · 0,15, 0, 1) · rim` über den Grund geblendet.
Auf den Schirm kam also das **Produkt aller drei** Faktoren — am Rand drei
kleine Zahlen, also eine Spitze. K-A E4 hat die ersten beiden übernommen und
den dritten fallen gelassen, weil der Boden, den es schattiert, undurchsichtig
ist und es kein Alpha mehr gibt, in das er fallen könnte.

Gemessen auf der Seefixture (Deckungstiefe 1,5 m, Randrampe gesättigt):

| Tiefe | Schaumband | Deckung | weiß VORHER | weiß NACHHER | Faktor |
|---|---|---|---|---|---|
| 0,15 m | 0,84375 | 0,1545625 | 0,50625 | 0,0782473 | 6,47× |
| 0,30 m | 0,5 | 0,179 | 0,30 | 0,0537 | 5,59× |
| 0,45 m | 0,15625 | 0,2394375 | 0,09375 | 0,0224473 | 4,18× |

Am lautesten ist das genau dort, wo am wenigsten Wasser steht: auf der
überfluteten Bank im Dilatationsring (E6 hat die Bankklemme absichtlich
zurückgebaut, „der Lift deckt es ab") und an der Gitter-Treppe, auf der dieser
Ring endet — die gemeldeten weißen Ränder UND Ecken. Auf einer gemäanderten
6-m-Fixture mit 1,2-m-Mikrorelief ist das Schaumband quer gemessen **11,5 m**
breit statt der ~3 m, die ein 3-m-Uferrampen-Fluss vorsieht, und **696 von 1968**
Ringpunkten 3,5–7 m ausserhalb des Umrisses werden gehoben.

**Regel jetzt** (`client3d/src/scene/waterShade.ts`, `waterFoamAt` und ihr
GLSL-Zwilling): `foam · min(shoreAlpha + foam · WATER_FOAM_MIN_COVER, 1) · rim`.
`WATER_FOAM_MIN_COVER` = 0,15 ist die Randzahl des Spiegels, wörtlich; die
Deckung benutzt dieselbe Uferkurve, die die Absorption schon reitet — keine
zweite Kurve. Nachweis: `smoke_water_shade.mjs` [2] (Handtabelle + die drei
ROTEN Proben mit den kaputten Zahlen) und [6] (GLSL-Zeile, plus ROTE Probe,
dass das nackte Band nicht mehr vorkommt).

### 2. „Der Wasserfall hat nur oben die Wasserfall-Textur" — der Vorhang stand in seiner eigenen Wand

Unter K-A ist der Spiegel zwischen Lippe und Gumpen der BODEN: das Terrain wird
auf `max(h, w_level)` gehoben, der Fall steht also als steile, **undurchsichtige,
nasse Wand** über die Sehne des Laufs. Der Vorhang hing aber am Bogen-MITTELPUNKT
über einen Lauf von `WATERFALL_LEAN · h` — steiler als diese Wand, sobald die
Sehne länger als `0,3 h` ist, also bei jedem Fall flacher als 73°.

Auf der Plan-Fixture (Fallhöhe 5,8 m, Sehne 3 m) mit `r` = Laufkoordinate ab dem
Fallpunkt und `u` = Höhenanteil (0 = Gumpen, 1 = Lippe):

```
r_Wand(u) = 1,5 · (1 − 2u)        r_alt(u) = 0,87 · (1 − 2u)
r_alt − r_Wand = −0,63 · (1 − 2u)   ->  −0,63 m am Fuß, < 0 für jedes u < 0,5
```

Genau die untere **Hälfte** stand hinter dem eigenen Wasser — deshalb war der
Vorhang mit Isolationsschalter 22 („Water lift off") vollständig sichtbar. Die
Wrap-Mode-Verdächtigung war falsch: `materials.makeWaveNormal` setzt
`wrapS = wrapT = RepeatWrapping`, bevor sie irgendjemand sieht (im Smoke
angenagelt).

**Regel jetzt:** `Waterfall` trägt zusätzlich `chordM` (die Sehne des Laufs,
in `runToFall` ohnehin berechnet). Der Vorhang hängt an der **Lippe** und
bekommt den Lauf der Wand plus den Lean am Fuß:

```
top = (x, z) − dir · chordM/2                bot = (x, z) + dir · (chordM/2 + 0,3 h)
r_neu(u) − r_Wand(u) = 0,3 h · (1 − u)   ->  1,74 / 0,87 / 0 m bei u = 0 / 0,5 / 1
```

Der obere Rand fällt damit exakt auf die Lippe (auf der Fixture Knoten B
(20, 0)), der Fuß 1,74 m hinter den Wandfuß (Knoten C), und die Naht an der
Lippe deckt der Vorhang-Shader mit seiner eigenen 6-%-Ausblendung ab. Nachweis:
`smoke_waterfall.mjs` [9] — vier Ecken, drei Abstände, 101 Höhen ohne
Verdeckung, plus die ROTEN Proben des alten Zustands.

### 3. Offen und NICHT gefixt: der Fluss zerfällt ab Mip 2

Der dritte Befund („nur jeder zweite Abschnitt fließendes Wasser") ist gemessen,
aber nicht behoben — er ist keine Panne in einer der drei verdächtigten Stellen,
sondern die Auflösungsgrenze von K-A selbst. Auf derselben Mäander-Fixture:

| Gitter | gehobene Flusspunkte | kleinstes interpoliertes \|flow\| |
|---|---|---|
| 2 m (Level 0) | 123 / 123 | 1,0000 |
| 4 m (Level 1) | 123 / 123 | 0,9997 |
| 8 m (Level 2) | **44 / 123** | 0,9996 |
| 16 m (Level 3) | **0 / 123** | — |

Der Fließvektor ist also überall in Ordnung (Server: 150 von 150 Gitterpunkten
eines 700-m-Flusses über drei Kacheln tragen `|flow| = 1`, alle drei Kacheln
liefern die Arrays; Client: der Varying fällt nirgends unter 0,9996, wo Wasser
gehoben wird). Was verschwindet, ist der GEHOBENE Punkt: ein 6 m breites Bett
mit ±3 m Carve hat auf einem 8-m-Gitter meist keinen Stützpunkt mehr im Bett,
also ist `h_k ≥ w_k` und der Lift greift nicht. Das Mesh-Mirror hatte dieses
Problem nicht — er war ein Polygon in voller Auflösung. Die drei ehrlichen
Optionen (Level-Deckel für wasserführende Knoten, feineres Wasserraster, oder
akzeptieren) sind eine Entscheidung, keine Fehlerbehebung.

---

## Nachtrag 2026-08-25 (§ A16.5 / § B5a): Die vier Befunde am K-A-Wasser — der `sd`-Kanal, das gehobene Ringband und der Fließ-Rahmen

*Ein Server-Umbau (`HEIGHT_BAKE_VERSION` **8 → 9**, additive Kachel-Nutzlast)
und drei Client-Korrekturen, die alle vier auf dieselbe Wurzel zurückgehen:
**der Renderer hatte kein Feld, das sagt, wo der Autor das Wasser gemalt hat.**
Der Pegel ist DILATIERT (4 m über jeden Umriss hinaus), also ist er keine Maske;
die Material-Maske des Boden-Kompositors nennt die OBERSTE GEMALTE ART, also ist
sie es auch nicht. Der Bake liefert die Antwort jetzt selbst.*

### 1. Die Befunde und ihre Zahlen

| Befund | Ursache, gemessen |
|---|---|
| **F-A** „der See ist nur noch eine Sandfläche" | Das Tor von `95ea0ca0` las das ID-Paar der Material-Maske. Fixture (lake + gemalter Sand-Bett-Fläche, `app/core/terrain_layers.py`): das Paar in der Seemitte ist **(1, 1) = (sand, sand)** — keine Hälfte ist Wasser, also gab `twInside` **0** über die ganze Seefläche zurück und der gehobene Spiegel wurde als sein eigenes Bett gemalt. (Ein `bed_kind` OHNE gemalte Fläche allein tut das nicht: die Wasser-Ebene trägt weiter `water: true` und nur die SURFACE des Betts — auch gemessen.) |
| **F-B** graue Randflecken, Treppen-Silhouette, „Avatar steht im Boden" | Das Dilatationsband wurde GEOMETRISCH gehoben. Fixture (flacher Boden 0, Spiegel 1,0, Umriss bei x = 10): jeder Vertex des 4-m-Bandes stieg **1,00 m** auf den Spiegel, gezeichnet als Boden, mit dem echten Boden 1 m darunter — dort steht die Figur (`waterPlaneMath.waterLevelAt` kennt die Dilatation nicht). Der äußere Rand des Bandes ist eine Gitter-Treppe. |
| **F-C** „fließt nicht, alle paar Meter anders strukturiert" | Der Ripple-Rahmen ist die Achsentangente pro Vertex, und die springt an der MITTELACHSE — dieselbe Unstetigkeit, die § A16.5 Punkt 6 am Pegel mit 1,2951 m auf 10 cm gemessen hat. Hairpin-Fixture: **145,96°** zwischen zwei Gitterpunkten 2 m auseinander. |
| **F1-Deckel** | Der Deckel maß die UNGETORTE Hebung, also die Breite von Körper **plus Ring**. Fixture (6-m-Fluss, Bank unter dem Spiegel): Deckel **2** statt **1** — für einen Fluss, dessen eigener Körper auf Stufe 2 schon zerfallen ist. |

### 2. Server (Bake v9): der vierte Kanal und der geglättete Fluss

```jsonc
"water": {
  "level":  [[float|null, …], …],   // unverändert
  "sd":     [[float|null, …], …],   // NEU: Meter, + innen, − im Ring, gleiche Maske
  "flow_x": [[float, …], …],        // jetzt GEGLÄTTET
  "flow_z": [[float, …], …]
}
```

- **`sd` ist die vorzeichenbehaftete Distanz zum Umriss DESSELBEN Wassers**, aus
  dem `level` stammt — die Nullmenge IST der gemalte Umriss. Ein Punkt innerhalb
  zweier überlappender Seen liest die Distanz des OBERSTEN zu SEINEM Umriss;
  „zuletzt gemalt gewinnt" ist EINE Entscheidung für alle vier Kanäle. Maske und
  Rundung wie `level` (Millimeter, `null` auf genau denselben Texeln).
  Kosten: ein zusätzlicher Ring-Durchlauf auf dem Innen-Zweig (der Ring-Zweig
  misst die Distanz ohnehin, um sich zu entscheiden).
- **`flow` läuft durch eine separable Box vom Radius
  `WATER_FLOW_BLUR_M`** — und das ist `WATER_RASTER_DILATION_M`, nicht aus
  Geschmack: das Raster ist genau so weit über jeden Umriss hinaus geschrieben,
  also liegt die Box um jeden Punkt INNERHALB eines Umrisses noch ganz im
  geschriebenen Bereich. Die Glättung mischt damit nie einen autorierten
  Fließvektor mit dem (0, 0) echten Trockenbodens. Bei `TILE_STEP_M` = 2 m sind
  das 2 Texel Radius, also eine 5 × 5-Box über 8 m.
- **NICHT re-normalisiert.** Wo zwei Richtungen wirklich uneins sind, ist der
  Mittelwert KÜRZER, und die Länge ist der Geschwindigkeits-Faktor: eine
  anmutige Verlangsamung genau dort, wo das Feld mehrdeutig ist. Der
  Stillwasser-Boden (1e-4) wird nie erreicht (kürzester gemessener Vektor
  0,2952).
- **Das Fenster wird mit RAND abgetastet und danach beschnitten** (`(129 + 2r)²`
  statt `129²`, +6,3 %). Eine an der eigenen Kante geklemmte Box hinge davon ab,
  aus welcher Kachel man einen Punkt liest — § G1 sagt, dass sie das nicht darf.
  Geprüft: derselbe Punkt aus zwei Fenstern gibt bitgleich denselben Vektor.
- **Pegel und `sd` werden NICHT geglättet.** Beide werden gegen eine SCHWELLE
  gelesen; eine Glättung verschöbe die Wasserlinie vom autorierten Umriss weg.

### 3. Client: EIN Feld, ZWEI Stufen, dasselbe Sampler-Textstück

`waterShade.waterSdGlsl()` ist ein einziger GLSL-Text, den beide Stufen der
Wasser-Variante einbinden — Vertex und Fragment können keine Funktion teilen,
also teilen sie diesen String. Das Gitter ist `uTlodWaterLevel[0]` über
`uTlodWaterGeom.xy`, die Ausdehnung ist per `textureSize` das Nahfenster; außen
antwortet er `TW_SD_DRY` (−10 000 m) statt ein Randtexel nach außen zu klemmen.
Das Trocken-Sentinel ist eine ZAHL und nicht das `NaN` des Pegels: `sd` wird auf
ein VORZEICHEN gelesen, also zieht eine trockene Ecke die einfache bilineare
Mischung ins Negative — die richtige Richtung — und kann keine Mischung
vergiften. Innerhalb eines Umrisses kann sie das nie tun (Dilatationsargument,
§ A16.5 Punkt 3; nachgemessen an 6561 bzw. 1681 Proben).

- **Der LIFT tort auf `sd ≥ 0`** (`tlodLift(h, p, nodeStep, sd)`). Die Distanz
  wird EINMAL pro Vertex genommen, vor beiden Taps des Morph-Paares: sie ist
  eine Funktion der Position allein, also tragen beide Terme dieselbe Zahl und
  das Paar bleibt in `f` stetig — und zwei Stücke verschiedener Stufen, die sich
  einen Vertex teilen, heben ihn beide oder keines.
- **Der Ring behält seine Werte** und muss es: sie sind es, die die bilineare
  Mischung INNERHALB des Umrisses das Profil reproduzieren lassen. Er ist
  bilineare STÜTZE, nie eine Fläche.
- **Das Fragment-Tor liest dasselbe `sd`**, mit einem weichen Band von
  `max(ein Bildschirmpixel, 0,5 m)`. Die ID-Maske behält genau eine Aufgabe:
  zu sagen, WELCHE Wasserart hier steht (`layer = twIsWater(a) ? a : b`). Die
  `sd`-Hälfte von `bindLayerIdUniforms` ist wieder gelöscht — kein totes
  Mechanismus-Paar.
  **ÜBERHOLT am 2026-08-25 (Bake v10, siehe letzter Nachtrag):** auch diese
  letzte Aufgabe war falsch besetzt — die Maske nennt die oberste GEMALTE Art,
  nicht die Wasserart. Das Raster nennt seine Art seit v10 selbst
  (`kinds` + `kind_idx`), und `bindLayerIdUniforms` ist ganz gelöscht.
- **Der F1-Deckel misst die GETORTE Hebung**: `waterTileCaps` nimmt das
  `sd`-Feld und zählt ein Texel nur, wenn es wirklich steigt. Sonst beschriebe
  die Zahl nichts.

### 4. Der Fließ-Rahmen (F-C) — was die Glättung kauft, und was NICHT

Gemessen als größter Winkel zwischen den Fließvektoren zweier BENACHBARTER
Gitterpunkte innerhalb des Umrisses (`smoke_height_bake.py` [12h]):

| Fixture | roh | ausgeliefert (Box r = 2) |
|---|---|---|
| **Mäander** — Fluss als Band um seine eigene Linie, 8 m breit | **1,80°** (p99 1,71, Mittel 0,52) | **1,49°** |
| **Haarnadel** — Achse kehrt INNERHALB eines 160 × 65 m-Polygons um | **145,96°** | **66,32°** |

**Die Lesart, und sie entscheidet gegen ein zusätzliches gröberes Abtasten:**
ein autorierter Fluss hat den Sprung gar nicht — die Mittelachse seiner Linie
liegt für jede Biegung sanfter als die halbe Breite AUSSERHALB des Bandes. Die
146° gehören der Fixture, in der ein 6-m-Strich in einer seeförmigen Fläche
umkehrt. Ein gröberes Rahmen-Sampling brächte dort 66° → 41° und kostete jedem
schmalen Fluss die Fließrichtung an seinen Ufern; die Box ist die richtige,
billige Versicherung, und mehr ist an dieser Stelle nicht zu holen.

**Was danach übrig bleibt und NICHT behoben ist** (Messung, keine Vermutung):
`twFrame` staucht die WELTKOORDINATE um die Fließachse, also verstärkt sich
jede Rahmen-Änderung mit dem Abstand vom Weltursprung. Für eine Rahmen-Drehung
`dθ` ist die zusätzliche uv-Verzerrung ≈ `(1 − 1/aniso) · |p| · dθ / λ`
Wellenlängen. Auf der Mäander-Fixture (|p| ≈ 150 m, λ = 1,6 m, aniso = 3):
Mittel 0,52°/2 m → Faktor 0,45, schlimmster Punkt 1,49°/2 m → 1,30 — also eine
lokale Stauchung von 1,5× bis 2,3×, die `textureGrad` nicht kennt. Dazu kommt
der DRIFT-Term: er wächst mit `uTlodTime` (Wrap bei 3600 s), und bei
`sp` = 0,15 m/s sind das am Ende der Stunde 337 Wellenlängen Versatz — zwei
Nachbarvertizes 0,52° auseinander liegen dann **3,06 Wellenlängen** auseinander,
d. h. das Muster dekorreliert im Lauf von Minuten. Das ist die verbleibende
Hälfte von „alle paar Meter anders strukturiert", und es ist ein
Entwurfs-Thema (Flow-Map-Advektion mit periodischem Reset, oder die Anisotropie
fallen lassen), keine Panne — deshalb steht es hier und nicht im Code.

### 5. Die Beweise (§ B5a)

| Was | Wo |
|---|---|
| `sd` innen/auf dem Umriss/im Ring, bed_kind unberührt, 6561 Innen-Proben ≥ 0 | `scripts/smoke_height_bake.py` **[12g]** |
| Nutzlast: gleiche Maske wie `level`, Rundung, Lattice | ebenda **[12g]** |
| Blur-Radius = Dilatation, Winkel-Tabelle roh/ausgeliefert, keine Re-Normierung, Stillwasser bleibt still, Fenster-Naht | ebenda **[12h]** |
| Client-Zwilling `rasterSdAt`: bilinear, Sentinel, 1681 Innen-Proben ≥ 0 | `client3d/scripts/smoke_world_height.mjs` **[W4a]** |
| Lift-Tor: Ring hebt nicht mehr, „Figur neben dem Wasser", GLSL-Pins | `client3d/scripts/smoke_terrain_lod.mjs` **[16]**, **[17]** |
| Deckel misst die getorte Hebung (2 → 1) | ebenda **[18] (e)** |
| Fragment-Tor: eine Smoothstep, Band, ID-Maske nur noch für den Look | `client3d/scripts/smoke_water_shade.mjs` **[7]** |

---

## Nachtrag 2026-08-25 (§ A16.5): Das Wasser-Raster nennt seine ART pro Texel — die zweite Hälfte von F-A

*Ein Server-Umbau (`HEIGHT_BAKE_VERSION` **9 → 10**, additive Kachel-Nutzlast)
und ein Client-Schnitt. v9 gab dem Renderer ein Feld, das sagt, **OB** ein Pixel
in gemaltem Wasser steht (`sd`). **WELCHES** Wasser es ist, blieb bei der
ID-Maske des Boden-Kompositors — und die beantwortet eine andere Frage.*

### 1. Der Befund

Nutzer-Beleg vom 2026-08-25: „See UND Fluss zeigen Flecken, die wie
**Waldboden** aussehen, teils durchscheinend, teils nicht; beim Fluss stimmt die
**Fließrichtung** nicht; die gewünschte Rand-Transparenz funktioniert an
**manchen** Seestellen."

Alles davon steht in EINER Zeile des Fragments, die es bis v9 gab:

```glsl
layer = twIsWater( a ) ? a : b;     // (a, b) = das ID-Paar der Material-Maske
```

Das Paar nennt die **oberste GEMALTE Art** und die darunter. Das ist eine
Aussage über den BODEN. Überall dort, wo das Wasser nicht die oberste gemalte
Art ist — ein Fluss unter einer darüber gemalten Waldfläche, ein See mit
`bed_kind`, jede Z-Order-Änderung — nennt das Paar **gar kein Wasser**, beide
Hälften fallen durch `twIsWater`, und die Wahl landet auf einer
Platzhalter-Zeile: dem **primären Wasser der Welt**.

Gemessen auf der Fixture „Fluss durch darüber gemalten Wald"
(`scripts/smoke_height_bake.py` **[12j]**, `terrain_layers.LayerModel`):

| Größe | gemessen |
|---|---|
| ID-Paar in der Flussmitte (60, 40) | **(1, 1) = (g, g)** — der Wald |
| dessen Ebene `water` | **false** — beide Hälften fallen durch |
| eigene Ebene des Flusses | **2**, `water: true` — die Maske nennt sie hier nie |
| Anteil der nassen Texel des Fensters mit falschem Paar | **alle** (Menge der Ebenen über alle nassen Texel = `{1}`) |

Und was die falsche Zeile kostet, in Zahlen
(`client3d/scripts/smoke_water_shade.mjs` **[11]**; tiefer See 4 m Bett →
`opaque` 3,0 m, `flow_speed` 0; Fluss 1,2 m Bett → `opaque` 0,9 m,
`flow_speed` 1,0 m/s):

| bei 0,60 m Wassertiefe | richtige Zeile (Fluss) | gewählte Zeile (See) |
|---|---|---|
| Absorption `3t²−2t³` | `t = 2/3` → **20/27 = 0,740741** | `t = 0,2` → **0,104** |
| Rest des BETTS im Bild | **7/27 = 0,259259** | **0,896** |
| — Faktor | | **3,456× so viel Waldboden** |
| Drift der Kämme (`flow_speed · |flow|`) | **1,0 m/s** | **0 m/s — nichts bewegt sich** |
| Ripple-Wellenlänge | **1,2 m** | **2,0 m** |

Das ist die ganze Beobachtung: „wie Waldboden" ist `1 − Absorption` mit der
falschen `opaque`-Tiefe, „teils durchscheinend, teils nicht" ist derselbe Pixel
bei anderer Tiefe, „Fließrichtung stimmt nicht" ist ein Muster, das gar nicht
wandert (der RAHMEN kam immer aus dem Raster und war nie falsch), und „an
manchen Seestellen richtig" sind genau die Stellen, an denen das Wasser zufällig
doch die oberste gemalte Art ist.

### 2. Server (Bake v10): Palette + Index-Gitter

```jsonc
"water": {
  "level":    [[float|null, …], …],   // unverändert
  "sd":       [[float|null, …], …],   // unverändert (v9)
  "kinds":    ["water", "river"],      // NEU: die Palette DIESES Fensters
  "kind_idx": [[int, …], …],           // NEU: Index hinein, pro Texel
  "flow_x":   [[float, …], …],         // unverändert, weiterhin optional
  "flow_z":   [[float, …], …]
}
```

- **`kind_idx[j][i]` nennt die Art des OBERSTEN Wassers** an diesem Texel —
  dieselbe Entscheidung, die schon `level` und `sd` wählt. „Zuletzt gemaltes
  Wasser gewinnt" ist EINE Entscheidung, und alle fünf Kanäle eines Texels
  stammen aus demselben Wasser. `HeightModel.water_at` gibt die Art als fünften
  Rückgabewert.
- **Eine PALETTE statt eines Namens pro Texel.** Eine Kachel trägt ein oder zwei
  Wasser; 129 × 129 Wiederholungen derselben Handvoll Wörter wären hunderte
  Kilobyte. Und ein INDEX ist ohnehin genau das, was eine Look-Tabelle
  indiziert. Die Reihenfolge ist „zuerst angetroffen" beim zeilenweisen Lauf
  über das BESCHNITTENE Fenster; die Palette ist nie leer, solange die Kachel
  existiert.
- **`kind_idx` ist 0, wo `level` `null` ist, und bedeutet dort NICHTS.** Kein
  zweites Sentinel: `level` IST die Maske dieses Rasters, und ein zweites würde
  nur wiederholen, was das erste sagt — und jeden Leser zwingen, eine nullable
  Ganzzahl durch eine Textur zu tragen, die keinen Platz dafür hat.
- **Nichts wird geglättet oder gemischt.** Eine Art ist ein NAME; der Mittelwert
  zweier Namen ist keiner. Das Gitter wird beschnitten wie `level` und `sd`.
- `h_final` bewegt sich um keinen Millimeter. Der Zähler dreht sich, weil eine
  v9-Kachel keine Palette trägt und der Renderer dann nichts hat, womit er seine
  Look-Tabelle indizieren könnte.

### 3. Client: die Look-Tabelle ist nach ART geschlüsselt, die ID-Maske ist raus

- **`WaterLook`-Tabelle: eine Zeile pro WASSERART** statt einer pro Ebene. Damit
  fallen die Platzhalter-Zeilen weg (jede Bodenebene trug das primäre Wasser als
  Attrappe) und mit ihnen das `is_water`-Flag im dritten Slot von Texel 2 — es
  war nur dazu da, diese Attrappen wieder auszusortieren. Der Slot ist jetzt
  Reserve. **Zeile 0 ist das primäre Wasser** und das, was eine unbekannte Art
  liest (und jede v9-Kachel): schlimmster Fall „das falsche Wasser", nie ein
  bodenfarbener See.
- **`uTlodWaterKind`** — R32F auf dem BASIS-Gitter der Wasser-Pyramide, neben
  `uTlodFlow` und `uTlodWaterSd` und ohne eigene Geometrie (das Gitter IST
  `uTlodWaterLevel[0]` über `uTlodWaterGeom.xy`). Der Client löst den NAMEN aus
  dem Raster über die aktuelle `rowOfKind`-Abbildung in eine ZEILE auf
  (`terrainLod.buildKindRows`), damit die Tabelle jederzeit neu geordnet werden
  darf, ohne dass der Bake je eine Zeilennummer eines Renderers kennt.
- **NEAREST, nie bilinear** (`waterRaster.nearestIndex` / `rasterKindAt`, GLSL
  `twKindRow`): eine Look-Zeile ist ein Name. Wo zwei Wasserarten INNERHALB
  einer zusammenhängenden Fläche aneinanderstoßen, wechselt die Zeile an der
  Texelkante statt zu blenden — **angenommen und hier notiert**: es ist ein
  Meter-Sprung im Farbton zwischen zwei Wassern, die der Autor als zwei Wasser
  gezeichnet hat.
- **Was gestorben ist:** `bindLayerIdUniforms` (ganz, samt der zweiten
  Sampler-Bindung), `uTlodWaterMask` / `uTlodWaterMaskGeom` im Wasser-Programm,
  `twIsWater`, `WaterLook.isWater` und die Attrappen-Zeilen. Der Boden-Kompositor
  behält seine Maske unverändert für den BODEN; geborgt wird nichts mehr.
- **Die H2-Oberflächenterme reiten dieselbe Zeile**: Rauheit, Metalness,
  Himmelsanteil und Ripple lesen `look1`/`look2` derselben Zeile — sie werden
  mit demselben Schnitt richtig, ohne eigene Änderung.

### 4. Die Beweise (§ B5a)

| Was | Wo |
|---|---|
| Palette + `kind_idx` von Hand auf einer Zwei-Arten-Fixture (Überlappung, Ring, trockene Texel, Ein-Eintrag-Fenster) | `scripts/smoke_height_bake.py` **[12i]** |
| Verurteilung „Fluss durch Wald": ID-Paar `(g, g)`, Ebene nicht Wasser, alle nassen Texel betroffen; Raster nennt `river` | ebenda **[12j]** |
| Client-Zwilling: Draht → Palette/Gitter, `nearestIndex`-Regel, Wechsel an der Texelkante, v9-Kachel, Index außerhalb der Palette | `client3d/scripts/smoke_world_height.mjs` **[W4b]** |
| Die Zahlen der falschen Zeile (3,456× Bett, 0 statt 1 m/s, 2,0 statt 1,2 m) | `client3d/scripts/smoke_water_shade.mjs` **[11]** |
| GLSL: Zeile aus `twKindRow`, kein `twIsWater`, kein `uTlodWaterMask` | ebenda **[6]**, **[7]** |
| Uniform-Bindung: `uTlodWaterKind` am Wasser-Programm, Maske an keinem | `client3d/scripts/smoke_terrain_lod.mjs` **[18]** ("the water shading lives in the water program only") |

---

## Nachtrag 2026-08-25 (§ B2/§ A9/§ A9a): Maß, Motiv, Einsinken und Marker gehören der VARIANTE — die Nutzlast bleibt Zeichen für Zeichen gleich

**Für die Renderer ändert sich nichts.** Dieser Nachtrag steht hier, weil die
Sätze weiter oben („`ground_offset_m` je Prop", „die Maße des Props") die
Quelle falsch benennen, nicht weil ein Feld gewandert wäre.

Ein Prop trug bis heute EIN Maß, EIN Bildmotiv, EIN `ground_offset_m` und EINE
Markerliste; eine Modellvariante durfte die ersten beiden überschreiben. Eine
Variante ist aber eine ganze VERSION des Objekts — der Setzling neben der
gewachsenen Kiefer, der zerbrochene Stuhl neben dem heilen —, und genau diese
vier Angaben unterscheiden sich je Version. Sie liegen deshalb seit heute auf
dem Varianteneintrag und nirgendwo sonst (`app/core/props.py`, Feldtabelle im
Modulkopf); der Master-Datensatz hat die Schlüssel verloren, ohne Fallback-Leser.

| Payload-Feld | vorher gelesen aus | jetzt gelesen aus | Form |
|---|---|---|---|
| `max_m` / `placeholder_dims` / `dims` | Prop, Variante überschreibt | die gezeichnete VARIANTE (`props.variant_dims`) | unverändert |
| `ground_offset_m` (Szene, Welt-Props, Streu) | Prop | die gezeichnete VARIANTE (`props.variant_ground_offset`) | unverändert, Abwesenheit = 0.0 |
| `prop_markers[]` | Prop | die gezeichnete VARIANTE (`props.variant_markers`) | unverändert |
| `prop_height_m` der Streu | Prop | PRIMÄRvariante (die Instanzen werden clientseitig gesampelt) | unverändert |

Wo kein Variantenkontext existiert — die schlanke Prop-Bibliothek
`GET /assets/props`, die Zeile der Bibliotheksliste, der schematische Grundriss —
antwortet die **PRIMÄRvariante**, also dieselbe wie bei jeder anderen
unqualifizierten Frage (`/model` ohne Parameter, `variants` als Element 0 von
`model_variants`).

Der interne Rezept-Zwischenschritt `variant_tiers` trägt die Angaben jetzt pro
Eintrag mit: `{variant, tiers, dims, ground_offset_m?, markers?}` — `markers`
nur auf dem VOLLEN Datensatz, die schlanke Client-Bibliothek bekommt weiterhin
nur `marker_count`. Das ist die eine Liste, in der eine Platzierung ihre
POSITION auflöst, damit eine Zeile nie die Größe der einen und das Einsinken
einer anderen Version bekommt.

**Einmal-Migration** beim Start (`app/core/prop_field_migration.py`, `world_kv`-
gesichert): jedes Prop reicht seine Werte an jede Variante durch, die keinen
eigenen hat; ein selbst gesetzter Variantenwert bleibt stehen; danach fallen die
Schlüssel vom Master-Datensatz. Content-Pakete aus der Zeit davor werden beim
Import durch dieselbe Transformation geschickt.

### Die Beweise (§ B5a)

| Was | Wo |
|---|---|
| Maß je Variante: Sanitizer, Auflösung, `max_m`, Stapelregel, ROTE PROBE „`height_m` auf dem Master-Datensatz wird ignoriert" | `scripts/smoke_prop_variants.py` **[18]** |
| Motiv je Variante: Kopie-beim-Anlegen, Rückfall auf den PROP-NAMEN, Aufrufstelle des Renderns, 400 auf den Prop-Route-Feldern | ebenda **[19]** |
| Einsinken + Marker je Variante, die Stapelregel in beide Richtungen (0,75 / 1,05 statt 0,9 / 0,9) und die Migration auf einem handgebauten Vor-Umzug-Sidecar | ebenda **[20]** |
| Zeile eines Welt-Props liest das Einsinken der Variante, die sie zeichnet (−0.4 statt −0.2) | `scripts/smoke_world_props.py` **[3]** |
| Streu-Eintrag: Sanitizer über die echte Schreibroute, ROTE PROBE auf dem Master-Datensatz | `scripts/smoke_terrain_areas.py` **[15]** |

## Nachtrag 2026-08-25 (§ B1): Eine Tür ist ein LOCH, kein Schlitz — der Sturz

Zwei Befunde aus der Vorschau und aus dem Blender-Außenbild, ein und dieselbe
Ursache: **die Öffnungen wurden nicht gleich behandelt.** Ein Fenster bekam
Brüstung, Sturz und Glasband, eine Tür bekam eine Lücke — und zwar über die
GANZE Wandhöhe, obwohl ihre `height_m` seit jeher autoriert ist (`world_ops.
_sanitize_opening` verlangt 0,4…10 m). Von innen reichte jede Türöffnung bis
an die Decke; von außen las sich das gleiche Loch in der Kontur wie ein
fehlendes Wandstück, weshalb im Blender-Außenbild „gar keine Türen" zu sehen
waren: ein Schlitz vom Boden bis zur Traufe ist keine Tür.

**Die Regel, ab jetzt eine einzige für alle Öffnungen** (`scene_recipe.
_room_walls` und `_contour_walls`):

| Stück | Fenster | Tür / Durchgang |
|---|---|---|
| unter der Öffnung | Brüstung 0 … `sill_m` | entfällt (man geht hindurch) |
| die Öffnung selbst | Glasband, eigener Eintrag mit `glass` | Lücke |
| über der Öffnung | Sturz `sill_m + height_m` … Wandkopf | **Sturz** `height_m` … Wandkopf, Eintrag mit `lintel` |

Handrechnung an der 3,00-m-Etage (Wandhöhe `max(0,6; 3,00−0,15)` = 2,85) für
eine 1,00 × 2,10 m Tür in der Südwand eines Raums, der 4 m breit ist und
mittig auf der Kontur eines 10 × 8-m-Hauses steht:

| Wand | Stücke | `base_y` | `height` |
|---|---|---|---|
| Raumkante | x 6,0 … 4,5 und x 3,5 … 2,0 | −0,14 | 2,99 |
| Raumkante | x 4,5 … 3,5 (Sturz) | 2,10 | 0,75 |
| Konturkante | x 10,0 … 4,5 und x 3,5 … 0,0 | −0,14 | 2,99 |
| Konturkante | x 4,5 … 3,5 (Sturz) | 2,10 | 0,75 |

Also: **das Loch wird in JEDE Wand geschnitten, die die Tür durchstößt** —
die Kontur eingeschlossen, wie bisher über die Projektion der Außenschwelle
(§ A6/§ 4.2) — und es endet in JEDER dieser Wände auf der Türhöhe. Wo die
Kontur ohnehin einer Raumhülle weicht („eine Wand, ein Besitzer"), weicht auch
der Sturz mit: kein Wandstück dort, kein Sturz dort, die Raumwand trägt beides.
Eine Tür so hoch wie die Wand bekommt keinen Sturz (0 m ist kein Primitiv).

**Die Drahtform ändert sich nicht** — ein `walls`-Eintrag beschrieb schon
immer mit `base_y` + `height` ein beliebiges Band in der Wand, genau wie der
Fenstersturz. Additiv sind nur zwei Felder:

- `walls[].lintel` (bool, fehlt = normal): dieses Stück hängt über einer
  BEGEHBAREN Öffnung. Gezeichnet wird es wie jede Wand — beide Renderer
  brauchten dafür keine Zeile —, aber es sperrt nichts im Grundriss. Wer aus
  `walls` 2D-Kollider ableitet (`client3d/src/game/collide.ts`), überspringt
  es; ohne das Feld wäre jede Tür zugemauert. Der Fenstersturz trägt das Flag
  NICHT: unter ihm liegt die eigene Brüstung, die dort ohnehin sperrt.
- `doorways[].height_m`: die lichte Höhe, geklemmt wie `width_m` geklemmt ist.
  `base_y + height_m` ist die Unterkante des Sturzes — dieselbe Zahl, aus der
  die Kontur ihren Sturz stellt, nie eine zweite Ableitung.

`SCENE_RECIPE_VERSION` 1 → **2**: dieselben Daten liefern andere Wände, also
muss jede Szenensignatur sich bewegen, sonst behalten Client und Cache die
alte Geometrie bis jemand die Location zufällig speichert.

### Die Beweise (§ B5a)

| Was | Wo |
|---|---|
| Raumwand: 2 Stücke + Sturz, Sturz auf 2,10 / 0,75, ROTE PROBE „keine Türlücke reicht mehr an die Wandkrone" | `scripts/smoke_scene_recipe.py` **[3]** |
| Kontur: Sturz über dem projizierten Loch, gleiche x-Spanne, Tür so hoch wie die Wand → gar kein Sturz; weichende Kontur überlässt auch den Sturz der Raumwand | ebenda **[4]** |
| `doorways[].height_m`: geklemmt gegen die Wand (9,0 → 2,85), fehlende Autorierung → Wandhöhe, also kein Sturz | ebenda **[3d]** |
| Sturz bekommt keinen Schürzen-Anteil (§ A16.9) | ebenda **[4a]** |
| Blender-Volumen: 10 × 8-Haus, ein Raum, eine 1 × 2,1-m-Tür → 14 Wandprismen (12 Wand + 2 Türblatt), 126 Vertices, 95 Faces (ohne Tür 8 / 78 / 59), Bounding-Box unverändert | `scripts/smoke_exterior_render.py` **[4b]** |
| Kollision: das geflaggte Stück wird kein Segment, ROTE PROBE „ohne Flag wäre die Tür zugemauert" | `client3d/scripts/smoke_walk_math.mjs` |

## Nachtrag 2026-08-25 (§ B1): Das TÜRBLATT — eine Tür ist von außen SICHTBAR

Der Sturz (Nachtrag oben) hat die Tür zum Loch gemacht, aber ein Loch ist noch
keine Tür: von außen blieb eine Außentür ein dunkles Rechteck Innenraum, im
Blender-Außenbild ein Schatten in der Fassade. **User-Entscheidung (a) vom
2026-08-25: die Öffnung bekommt ein TÜRBLATT** — dieselbe Mechanik, die das
Fenster seit jeher hat, nur opak statt durchsichtig.

**Eine Öffnung, drei Stücke — und das dritte ist die SCHEIBE IM LOCH:**

| Stück | Fenster | Tür | Durchgang |
|---|---|---|---|
| unter der Öffnung | Brüstung 0 … `sill_m` | entfällt | entfällt |
| **in der Öffnung** | **Glasband**, Eintrag mit `glass` | **Türblatt**, Eintrag mit `leaf` | Lücke |
| über der Öffnung | Sturz | Sturz, Eintrag mit `lintel` | Sturz, Eintrag mit `lintel` |

Ein `passage` ist eine autorierte Öffnung OHNE Tür — ein Blatt darin behauptete
eine Tür, die niemand gezeichnet hat —, also bleibt sein Loch leer.

**Die Drahtform ändert sich wieder nicht.** Additiv sind zwei Felder:

- `walls[].leaf` (bool, fehlt = normal): dieses Stück IST die Tür. Es füllt die
  LICHTE Öffnung — vom Wandfuß (`base_y` der Wand ohne Schürze, § A16.9: das
  Blatt steht nicht im Gelände, die Schwelle liegt an seinem Fuß) bis zur
  Türhöhe — und ist so dünn wie ein Glasband: `WALL_THICKNESS ×
  PANE_THICKNESS_FACTOR` = 0,07 × 0,6 = **0,042 m**. Es trägt KEIN
  `texture_kind`; seine Farbe ist `style.door_color`, opak.
  Beide Renderer behandeln es wie eine Scheibe: gezeichnet, aber **aus dem
  Fassaden-Culling ausgenommen** (`wallCullRef` / `tile.outlineWalls`) — die
  Culling-Liste ist die Fassade, und eine Scheibe füllt ein Loch, statt einen
  Raum zu schließen. Und es SPERRT NICHTS: wer 2D-Kollider aus `walls`
  ableitet, überspringt `leaf` wie `lintel`, sonst wäre jede Tür der Welt
  zugemauert.
- `doorways[].type` (`"door"` | `"passage"`): welche begehbare Öffnung das ist.
  Daraus — und nicht aus einer zweiten Öffnungssuche — entscheidet die Kontur,
  ob ihr projiziertes Loch ein Blatt bekommt.
- `style.door_color` (`#4a3a2e`): die eine Farbe, die beide Renderer für ein
  `leaf`-Stück nehmen.

**Wer trägt das Blatt bei Kontur/Raum-Überlappung?** Dieselbe Regel wie beim
Sturz, keine zweite: das Blatt der Kontur wird gegen die Strecken geklemmt, die
einer Raumhülle gewichen sind („eine Wand, ein Besitzer"). Steht die Raumwand
auf der Konturlinie, trägt sie Wand, Sturz UND Blatt allein; steht der Raum
zurückgesetzt im Haus, sind es zwei verschiedene Löcher in zwei verschiedenen
Wänden — beide bekommen ihr eigenes Blatt, genau wie beide ihren eigenen Sturz
bekommen.

Handrechnung, dieselbe 1,00 × 2,10-m-Tür an der 3,00-m-Etage wie oben:

| Wand | Stück | `base_y` | `height` | `thickness` |
|---|---|---|---|---|
| Raumkante | Blatt x 4,5 … 3,5 | 0,00 | 2,10 | 0,042 |
| Konturkante | Blatt x 4,5 … 3,5 | 0,00 | 2,10 | 0,042 |

Also **kein Schürzen-Anteil** (der Sturz hat auch keinen) und keine
Wandstärke: `base_y` ist der Fuß der Wand OHNE die 0,14 m, die deren
volle Stücke ins Gelände reichen.

`SCENE_RECIPE_VERSION` 2 → **3**: gleiche Daten, andere Wände.

### Die Beweise (§ B5a)

| Was | Wo |
|---|---|
| Raumwand: Blatt 0,00 / 2,10 / 0,042, ohne `texture_kind`, ROTE PROBE „das Blatt trägt keine Schürze"; ein `passage` bekommt keines | `scripts/smoke_scene_recipe.py` **[3]** |
| Kontur: Blatt über dem projizierten Loch, gleiche x-Spanne wie der Sturz; weichende Kontur überlässt auch das Blatt der Raumwand | ebenda **[4]** |
| `style.door_color` liegt im Stil-Vokabular | ebenda **[9]** |
| Blender-Volumen: 14 Wandprismen (2 davon Türblatt), 126 Vertices, 95 Faces, vier Materialien, Bounding-Box unverändert | `scripts/smoke_exterior_render.py` **[4b]/[5]** |
| Kollision: das Blatt wird kein Segment, ROTE PROBE „ein sperrendes Blatt mauert die Tür zu" | `client3d/scripts/smoke_walk_math.mjs` |

## Nachtrag 2026-08-25 (§ A6/B1): TREPPEN — man geht in den ersten Stock

Bis hierher gab es genau EINE senkrechte Verbindung: den Fahrstuhl. Der Satz
„Treppen gibt es nicht" ist gestrichen. **Eine Treppe ist kein neuer
Subsystem-Zweig, sondern dieselbe Mechanik wie der Fahrstuhl** — der Server
rechnet sie in `extras`-Kästen aus, die Renderer stellen sie hin.

### Die Drahtform (Autorenformat)

```json
"stairs": [ { "at": [2.0, -2.0], "from_level": 0, "dir_deg": 90 } ]
```

- `at` = der FUSSPUNKT, wo die erste Stufe beginnt, in lokalen Metern wie
  `map3d.elevator` und jede andere Plankoordinate.
- `from_level` = die untere Etage (ein Kellerlauf ist `-1`). **Ein Lauf endet
  IMMER auf `from_level + 1`.** Wer vom Erdgeschoss in den zweiten Stock will,
  autoriert ZWEI Läufe — das ist die Kette, und fehlt ihr ein Glied, bleibt für
  diesen Sprung der Fahrstuhl.
- `dir_deg` ∈ {0, 90, 180, 270} = Aufstiegsrichtung. Die Vektoren stehen fest,
  niemand rechnet sie zurück: `{0: (0,+1), 90: (+1,0), 180: (0,−1),
  270: (−1,0)}` in (x, z).
- Maximal **8** Läufe je Location; der Sanitizer kappt die Liste und wirft
  jeden Eintrag weg, dem `at`, `from_level` oder ein gültiges `dir_deg` fehlt
  (nicht repariert — eine Treppe, deren Richtung niemand aufgeschrieben hat,
  zeigt sonst irgendwohin).

### Das Rezept (Server-Konstanten, echte Meter)

| Konstante | Wert | Was |
|---|---|---|
| `STAIR_WIDTH_M` | 1,20 | Stufenbreite QUER zur Steigrichtung |
| `STAIR_TREAD_M` | 0,26 | Auftritt je Stufe ENTLANG der Steigrichtung |
| `STAIR_RISE_M` | 0,20 | NOMINELLE Steigung — nur der Teiler |
| `STAIR_PAD_M` | 0,90 | Kante des Trigger-Pads (Marker, wie `ELEVATOR_PAD_M`) |
| `STAIR_PAD_THICKNESS` | 0,05 | Dicke des Pads |
| `STAIR_PAD_GAP_M` | 0,05 | Luft zwischen Pad-Kante und erster/letzter Stufe |

```
base   = storey_floor_y(from_level, storey)
target = storey_floor_y(from_level + 1, storey)
climb  = target − base
steps  = max(2, round(climb / STAIR_RISE_M))
rise   = climb / steps          # teilt den Etagenabstand GLEICHMÄSSIG
run    = steps · STAIR_TREAD_M
```

Die nominelle Steigung ist nur der Teiler: gerechnet wird mit `rise`, damit die
letzte Stufe EXAKT auf dem oberen Boden landet statt eine Handbreit darunter.
**Stufe *i* ist ein MASSIVER Kasten** vom unteren Boden bis zu ihrem eigenen
Auftritt — eine Treppe, auf der man überall steht, kein Satz schwebender
Platten:

```
center = at + dir·(i+0.5)·TREAD ,  y = base + (i+1)·rise/2
size   = TREAD entlang der Richtung, (i+1)·rise hoch, WIDTH quer
```

Die **Pad-OBERKANTE ist der Etagenboden** — dasselbe Gesetz wie beim
`elevator_pad`, also `center_y = Boden − THICKNESS/2`:

```
foot = at − dir·(STAIR_PAD_M/2 + STAIR_PAD_GAP_M) , level = from_level
head = at + dir·(run + STAIR_PAD_M/2 + STAIR_PAD_GAP_M) , level = from_level+1
```

### Handrechnung EG → OG (storey 3,00, `at` = (2, −2), `dir_deg` 90 → +X)

| Größe | Rechnung | Wert |
|---|---|---|
| `base` | `storey_floor_y(0, 3)` — Etage 0 IST das Terrain | 0,00 |
| `target` | `storey_floor_y(1, 3)` = 1·3 + 0,08 | **3,08** |
| `climb` | 3,08 − 0,00 | 3,08 |
| `steps` | `round(3,08 / 0,20)` = `round(15,4)` | **15** |
| `rise` | 3,08 / 15 | **0,205333…** |
| `run` | 15 · 0,26 | **3,90** |

| Primitiv | `center` | `size` | `level` |
|---|---|---|---|
| `stair_step` i = 0 | [2,13 / 0,102667 / −2] | [0,26 / 0,205333 / 1,20] | 0 |
| `stair_step` i = 14 | [5,77 / 1,54 / −2] | [0,26 / 3,08 / 1,20] | 0 |
| `stair_pad` `foot` | [1,50 / −0,025 / −2] | [0,90 / 0,05 / 0,90] | 0 |
| `stair_pad` `head` | [6,40 / 3,055 / −2] | [0,90 / 0,05 / 0,90] | 1 |

Bei `dir_deg` 0/180 läuft der Auftritt in z: `size` tauscht x ↔ z und das
Zentrum wandert entlang z — sonst ändert sich keine Zahl.

### Handrechnung Keller → EG (`from_level` −1)

| Größe | Rechnung | Wert |
|---|---|---|
| `base` | `storey_floor_y(−1, 3)` = −3 + 0,08 | **−2,92** |
| `target` | `storey_floor_y(0, 3)` | 0,00 |
| `climb` / `steps` / `rise` / `run` | 2,92 · `round(14,6)` = 15 | 2,92 / 15 / **0,194667** / 3,90 |

Stufe 0 sitzt bei y = −2,822667, Stufe 14 ist 2,92 hoch (Mitte −1,46); das
Fuß-Pad liegt bei −2,945 auf `level` −1, das Kopf-Pad bei −0,025 auf `level` 0.
Der Keller ist damit KEIN Sonderfall, sondern dieselbe Formel.

### Payload — additiv, zwei neue `extras`-Kinds

- `{kind:"stair_step", center, size, level: from_level, stair: idx}`
- `{kind:"stair_pad", center, size, level, stair: idx, end:"foot"|"head"}`

`stair` ist der Index des Laufs in `map3d.stairs` — zwei Läufe einer Kette
bleiben unterscheidbar. Dazu `style.stair_color` = **`#8a7a66`**: eine Treppe
ist Mauerwerk, kein Maschinenteil, und muss sich vom Grau des Fahrstuhls
unterscheiden.

**Routing-Regel:** Verbindet eine Treppenkette zwei Etagen, gewinnt sie; der
Fahrstuhl bleibt Fallback.

`SCENE_RECIPE_VERSION` 3 → **4**: dieselben Daten liefern andere `extras`,
also muss jede Szenensignatur sich bewegen.

### Die Beweise (§ B5a)

| Was | Wo |
|---|---|
| EG → OG: 15 Stufen + 2 Pads, Stufe 0 und Stufe 14 nach center/size, beide Pads nach center/size/level/end | `scripts/smoke_scene_recipe.py` **[5s]** |
| `dir_deg` 0: `size` x ↔ z getauscht, Zentrum und Pads wandern in z | ebenda **[5s]** |
| Keller → EG: 15 Stufen, erste bei −2,822667, letzte 2,92 hoch, Pads −2,945 / −0,025 auf `level` −1 / 0 | ebenda **[5s]** |
| Kette aus zwei Läufen behält ihre `stair`-Indizes | ebenda **[5s]** |
| ROTE PROBE: ohne `map3d.stairs` entsteht kein einziges `stair_*`-Primitiv (die Fahrstuhl-Zählung misst also keine Treppe) | ebenda **[5s]** |

## Nachtrag 2026-08-27 (§ B1/B2): Tür-Props + Slots (v5)

Bis hierher war eine Tür ein **Blatt**: eine dünne dunkle Platte im Loch
(Nachtrag 2026-08-25). Sie bleibt der Normalfall. Neu ist, dass eine Öffnung
statt der Platte ein **Prop** bekommen kann — ein modelliertes Türblatt samt
Zarge aus der Prop-Bibliothek. Das Prop ist ein ganz normaler `models[]`-
Eintrag; neu sind nur sein Mess-Modus (`fit`) und sein Anker (die Angel).

**Es sperrt weiterhin NICHTS.** Ein Tür-Prop ist ein Modell, kein Kollider —
die Kollision liest `models[]` nicht und tut es auch weiter nicht.

### Auflösung: welches Prop steht in der Öffnung (dreiwertig)

`scene_recipe.door_prop_id(opening, default)` ist die EINE Regel, und alle drei
Verbraucher (Wand-Splitter, Schwellenliste, Modell-Spec) fragen sie:

1. `openings[].prop_id` gesetzt → **dieses** Prop,
2. sonst `openings[].door_prop == "none"` → **kein** Prop (das ist das
   ausdrückliche „hier keine Tür", das den Location-Default aussperrt),
3. sonst `location.default_door_prop_id` (neues Feld, leer = keiner),
4. sonst offener Durchgang mit Blatt wie bisher.

Nur `type: "door"` bekommt eins. Ein Fenster hat Glas, ein `passage` ist ein
Loch OHNE Tür — beide nehmen auch den Default nicht an.

### Felder

| Feld | Wo | Bedeutung |
|---|---|---|
| `prop_id` | `rooms[].openings[]` (gespeichert) | das Prop dieser Öffnung |
| `door_prop: "none"` | ebenda | ausdrücklich kein Prop; sperrt den Default aus |
| `hinge: "left"\|"right"` | ebenda (fehlt = `left`) | an welchem Ende die Angel sitzt, gelesen gegen `along` der Schwelle — für den Autor: links oder rechts, von innen aus diesem Raum auf die Tür blickend |
| `default_door_prop_id` | Location | Standard-Tür des Ortes |
| `door_prop: true` | `walls[]` (nur zusammen mit `leaf`) | dieses Blatt füllt ein Prop → **Renderer zeichnen das Stück NICHT** |
| `measure: "fit"` | `models[]` | in die Öffnung eingepasst statt real-size skaliert |
| `size_m: [w, h]` | `models[]` (nur `fit`) | lichte Breite/Höhe der Öffnung in Weltmetern |
| `door: {opening, hinge, swing}` | `models[]` | `opening` = Index in `doorways[]`, `swing` = ±1 |

`walls[]` behält den Blatt-Eintrag mit Absicht: der Blender-Außenrender
(`exterior_render.py`) baut seine Fassade aus `walls` und verlöre sonst das
Prisma der Tür. Nur die beiden Renderer überspringen ihn. Ein `fit`-Spec trägt
kein `max_m` — die Öffnung ist das Maß.

### `place()` mit `measure: "fit"` (§ B2, die EINE Ausnahme)

Nicht-uniform, und der einzige Spec, der nicht auf seiner Mitte hängt:

- x → `size_m[0]`, y → `size_m[1]`, **z mit demselben Faktor wie x** (das Blatt
  behält sein Tiefenverhältnis zur Breite),
- die lokale **−x-Kante** und die Unterseite gehen in den Gruppenursprung, z
  bleibt mittig (die Dicke sitzt auf der Wandebene),
- die Skalierung liegt INNERHALB der Yaw-Gruppe — außerhalb würde sie das
  Blatt bei jedem Yaw scheren, der kein Vielfaches von 90° ist.

Der Ursprung der zurückgegebenen Gruppe IST damit die Angel: „Tür öffnen" ist
eine Drehung dieser Gruppe um sich selbst und bleibt reiner Sicht-Zustand je
App (Öffnungswinkel, Nähe, wann überhaupt).

### Handrechnung Anker + Yaw

Die Schwelle liefert `at_world`, `along = (ux, uz)`, `width_m`, `height_m`,
`base_y` — nichts davon wird nachgerechnet. Dann gilt

```
anchor = at_world ∓ along · width_m/2     (− bei hinge left, + bei right)
yaw    = (atan2(−uz, ux)·180/π + (hinge == "right" ? 180 : 0)) mod 360
bottom_y = base_y,   size_m = [width_m, height_m]
```

`yaw` dreht das lokale +x auf die Richtung, in die das Blatt VON der Angel weg
läuft: three's `Ry(+θ)` bildet lokal +x auf `(cos θ, −sin θ)` ab (§ A1.1), also
löst `θ = atan2(−uz, ux)` genau `+x → along`; bei rechter Angel läuft es gegen
`along`, daher +180°.

Für eine Öffnung bei `at_world` = (x₀, z₀), `width_m` = 1,0:

| `along` | `hinge` | `anchor` | `yaw` | `swing` |
|---|---|---|---|---|
| (1, 0) | left | (x₀ − 0,5 / z₀) | atan2(0, 1) = **0°** | +1 |
| (1, 0) | right | (x₀ + 0,5 / z₀) | **180°** | −1 |
| (0, 1) | left | (x₀ / z₀ − 0,5) | atan2(−1, 0) = −90° → **270°** | +1 |
| (0, 1) | right | (x₀ / z₀ + 0,5) | 270 + 180 = **90°** | −1 |
| (−1, 0) | left | (x₀ + 0,5 / z₀) | atan2(0, −1) = **180°** | +1 |

Die letzte Zeile ist der Fall der Smoke-Fixtur (Südtür von Raum „a": `at_world`
(−2, −1), `along` (−1, 0), Breite 1,0 → `anchor` (−1,5 / −1), `yaw` 180).

### Woher `swing` kommt

`swing` ist das Vorzeichen, mit dem eine POSITIVE Drehung um y das Blatt nach
AUSSEN öffnet — „außen" ist `_door_outward` = `(uz, −ux)`, die Normale weg von
dem Raum, aus dessen Wand das Loch geschnitten wurde (`rooms[0]`).

Dreht man die gesetzte Gruppe um φ, wandert ein Weltversatz (vx, vz) mit

```
d/dφ (vx·cos φ + vz·sin φ, −vx·sin φ + vz·cos φ) |φ=0 = (vz, −vx)
```

Das freie Ende des Blattes liegt bei `v = +along` (linke Angel) bzw.
`v = −along` (rechte). Also ist die Ableitung genau `(uz, −ux)` = außen für
links → **+1**, und ihr Gegenteil für rechts → **−1**.

`SCENE_RECIPE_VERSION` 4 → **5**: dieselben Daten liefern andere `models`/
`walls`, also muss jede Szenensignatur sich bewegen. In der Signatur stehen
zusätzlich `default_door_prop_id` (ein Feld der LOCATION, das keine
Raumsignatur abdeckt) und die Mesh-Signatur jedes aufgelösten Tür-Props (die
URL bleibt beim Neu-Erzeugen gleich).

### Slots: welche Fläche eines Props sich füllen lässt

Ein **Slot** ist ein **Material des Modells**. Wer ein Prop modelliert (oder
prompten lässt), benennt die füllbare Fläche — den Bilderrahmen, die
Fensterscheibe, das Schild — und genau dieser Materialname ist der Slot. Es
gibt keine zweite Auszeichnung, keine Zusatzdatei.

Die Regel steht in **einer** Funktion, `props.detect_slots(material_names)`,
und nirgends sonst. Für jeden Materialnamen `m`, klein geschrieben und
getrimmt:

| `m` | Slot |
|---|---|
| beginnt mit `slot_` | Name = `m[5:]`; Art `material`, wenn der Name in {`glass`, `mirror`, `matte`} steht, sonst `image` |
| ∈ {`picture`, `screen`, `sign`} (ganzer Name) | `{name: m, kind: "image"}` |
| == `glass` | `{name: "glass", kind: "material"}` |
| sonst | kein Slot |

Groß/Kleinschreibung ist egal, Namen werden **klein** gespeichert, **doppelte
fallen weg** (das erste Auftreten gewinnt), die **Reihenfolge ist die des
Modells**. Beispiel von Hand: `["slot_glass", "Slot_Poster", "glass", "SIGN"]`
→ `[{glass, material}, {poster, image}, {sign, image}]` — das zweite `glass`
ist dasselbe wie das erste und fällt weg.

Nur **Raum-Props** (`app/core/props.py`) haben Slots. Map-Props
(`world_props`) bekommen keine.

Ein Prop aus einem **Content-Pack** bringt seine `slots` im mitkopierten
`sidecar.json` mit (`content_io.export_prop_to_zip` / der Prop-Import kopieren
das Verzeichnis unverändert). Erkannt wird nur, wenn ein **Mesh landet**
(Upload oder Generierung), nie beim Import — wer ein Prop zum Teilen baut,
benennt die füllbaren
Materialien also schon im Mesh nach dieser Konvention oder pflegt die Liste vor
dem Export im Prop-Editor.

**Materialnamen müssen die Blender-Veredelung überleben**, sonst zeigt die
Liste auf Flächen, die die gespeicherte Datei nicht mehr hat. Stand heute tut
sie das: Neukodierung (`retexture.py`), Reduktion (`lod.py`) und
Normalisierung (`normalize.py`) fassen `bpy.data.materials` nicht an, der
glTF-Import/Export von Blender reicht den Namen durch. Die **eine** Ausnahme
ist der Vertex-Farben-Bake (`bake_vc.py`): er leert die Materialliste des
Objekts und legt `baked_vc_mat_<i>` an. Deshalb liest die Erkennung erst
**nach** den Veredelungsschritten desselben Ingests. Betroffen sind ohnehin nur
Vertex-Farben-Meshes, die gar keine benannten Flächen mitbringen.

Gelesen wird auf **beiden** Landewegen eines Meshes — es gibt keinen
gemeinsamen Trichter:

| Weg | Auslöser | Reihenfolge |
|---|---|---|
| `props._store_bbox` | Upload, Galerie-Auswahl, gelöschtes Mesh, gelöschte Variante | bake → retexture → LOD → **Slots** → Messung |
| `props._generate` | die img2mesh-Kette (der Normalfall) | `select` → Sidecar-Schreibung mit `bbox` → **Slots** |

`_generate` wählt und misst inline und kommt **nicht** durch `_store_bbox` —
ein Nachbearbeitungsschritt muss in beide Blöcke (Befund 2026-08-27: die
Erkennung stand nur in `_store_bbox` und feuerte für ein GENERIERTES Prop nie).
Die Verkleinerungswege (`_shrink`, `_reduce_to_low`, `_store_lod_stages`)
brauchen keinen eigenen Aufruf: sie wählen ausschließlich in die Stufe `low`,
gelesen werden die Slots aber am `full`-Mesh (`model_path(prop_id)`).

Im Datensatz (`props._prop_record`, immer vorhanden):

| Feld | Bedeutung |
|---|---|
| `slots: [{name, kind}]` | die füllbaren Flächen; `[]` = keine. Auch auf dem schlanken Record — die Szene gleicht dagegen ab |
| `slots_auto: true\|false` | nur im vollen Record: `true` = aus den Materialnamen gelesen (der Editor zeigt „detected"), `false` = von Hand gepflegt |

Solange `slots_auto` **nicht** `false` ist, wird die Liste bei **jedem**
landenden Mesh **neu erkannt** — ein neu generiertes Modell bringt seine
eigenen Flächen mit, statt die des Vorgängers hinter dem Abzeichen „detected"
stehen zu lassen; ein **leeres** Ergebnis zählt genauso (das neue Modell nennt
dann wirklich keine füllbare Fläche). Ein Ergebnis, das dem Gespeicherten
gleicht, schreibt nichts, und ein unlesbares Mesh ändert nichts — nur ein
POSITIVER Befund.

Sobald jemand sie **von Hand setzt**, ist Schluss: ein `POST /world/props/{id}`
mit `slots` (oder der Batch-Save) speichert die Liste und setzt `slots_auto`
auf `false` — ab da fasst kein weiteres Modell sie an, auch eine **geleerte**
Liste nicht (alle Slots löschen ist auch eine Entscheidung). Eine kaputte Liste
ist ein 400, kein stilles Verwerfen.

### Slot-WERTE: was in der Fläche steht

Was in einer füllbaren Fläche steht, gehört zum **Prop**, nicht zur
Platzierung: die Werte kommen aus den Prop-Defaults (`area_defaults`) und aus
den `slot_values` der Bild-Variante — die Regel steht im Nachtrag
[„Bild-Props (v5)"](#nachtrag-2026-08-27--b2-bild-props-v5--das-bild-reitet-auf-der-variante)
am Ende dieses Dokuments. Im Payload steht das Ergebnis unverändert am
Spec als `slots` (`models[]`, Raum-Prop wie Tür-Prop); fehlt der Schlüssel,
rendert das Prop, wie es modelliert wurde.

### Der Tausch im Renderer (`applySlotMaterials`)

`packages/scene-render/src/slotMaterials.ts` ist die EINE Routine, die einen
Slot auf ein Mesh schreibt; beide Renderer rufen sie (3D-Client
`sceneRecipe.ts`, Admin-Vorschau `FloorPlanPreview.tsx`). Sie durchläuft die
gesetzte Gruppe und vergleicht den SLOT-NAMEN jedes Materials mit den
Schlüsseln aus `slots`.

**Der Schlüssel ist der Slot-Name, nicht der Materialname** (Ruling R11): der
Slot-Name ist der Materialname ohne sein `slot_`-Präfix — genau so, wie
`props.detect_slots` ihn beim Lesen des Modells abgestreift hat. Das Material
`slot_picture_1` ist also der Slot `picture_1`; die Routine streift beim
Vergleich **ein** führendes `slot_` ab (getrimmt und klein auf beiden Seiten,
und hinter dem Präfix noch einmal getrimmt, wie auf dem Server). Ein Material
ohne Präfix (`picture`, `glass`) heißt weiterhin wie sein Slot. Der rohe Name
`slot_picture_1` als Schlüssel trifft nichts — den schickt der Server nie.

**Die Regel, die sie korrekt macht: das Material wird JE PLATZIERUNG geklont,
bevor es angefasst wird.** Der GLB-Lader hält eine `THREE.Group` je URL und
gibt sie allen Platzierungen; `Object3D.clone()` kopiert die Knoten, TEILT aber
die Material-Instanzen — ohne Klon hinge das Poster der Diele auch in der
Küche. (Dieselbe Regel wie bei `applyDepthCut`.) Der Aufruf steht deshalb VOR
Schnitt/Clip/Ghost: die klonen ihrerseits, was sie durchlaufen, und übernehmen
das Bild damit von selbst.

- `image` → `loadTexture(url)` (der Lader ist Parameter — Ladepolitik ist
  App-Sache), dann `colorSpace = SRGBColorSpace`, `flipY = false` (glTF-UVs)
  auf `map`, und `color = 0xffffff`, damit ein grauer Grundton das Bild nicht
  herunter multipliziert.
- `preset "glass"` → `GLASS_PRESET` (`opacity` 0,3 · `roughness` 0,06 ·
  `metalness` 0 · `transmission` 0,85 nur, wenn das Material das Feld hat) plus
  `transparent` und `DoubleSide` — eine einseitige Scheibe verschwindet, sobald
  man um die Tür herumgeht.

Zurück kommt die Liste der Klone. Sie gehört dem Aufrufer: jeder Klon besitzt
die Textur, die für ihn geladen wurde, und `disposeSlotMaterials` gibt beides
frei (Client: beim Stufenwechsel und im `unmountScene`; Vorschau: vor jedem
Neuaufbau).

`three` ist Parameter, kein Import — Paketregel.

### Grenzen (bewusst)

- Ein Prop-Ausweis, der ins Leere zeigt (oder ein Prop ohne Mesh), behält
  seinen Spec mit leerem `variants` — dieselbe Regel wie bei hängenden
  Raum-Platzierungen. Er bekommt KEINE `placeholder_dims`: eine Ersatzkiste
  wird auf ihren Anker zentriert, und dieser Anker ist eine Kante.
- Modell-Varianten (E2.3) hat ein Tür-Prop nicht — es liefert die primäre
  Stufenkarte.

### Die Beweise (§ B5a)

| Was | Wo |
|---|---|
| Öffnung mit `prop_id` → ein `models[]`-Eintrag `role:"prop"`, `measure:"fit"`, `size_m [1,0 / 2,1]`, Anker (−1,5 / −1), `yaw` 180, `bottom_y` 0, `door {0, left, +1}` | `scripts/smoke_scene_recipe.py` **[3p]** |
| `hinge: "right"` → Anker (−2,5 / −1), `yaw` 0, `swing` −1 | ebenda **[3p]** |
| zweite Achse: `along` (0, 1) → Anker (0 / −3,3), `yaw` 270, `size_m [1,6 / 2,1]` | ebenda **[3p]** |
| Blatt bleibt in `walls[]` (Außenrender) und trägt `door_prop` — Raumwand UND Kontur | ebenda **[3p]** |
| Default greift, `prop_id` gewinnt, `door_prop:"none"` unterdrückt (Blatt zurück, kein Flag) | ebenda **[3p]** |
| ROTE PROBE: Fenster und `passage` bekommen nie ein Tür-Prop, auch nicht per Default | ebenda **[3p]** |
| Prop-Ausweis ins Leere: Spec bleibt, `variants` leer, keine `placeholder_dims` | ebenda **[3p]** |
| Signatur bewegt sich für Location-Default UND neue Mesh-Signatur | ebenda **[3p]** |
| `place()` mit `fit`: 0,5×2×0,1-Kiste auf `size_m [1,0 / 2,1]` → 1,0 × 2,1 × 0,2, Angelkante AUF dem Anker, bei `yaw` 270 läuft die Breite in +z | `client3d/scripts/smoke_place_rotation.mjs` **[7]** |
| Materialnamen aus dem GLB (`materials[].name`, Header + JSON-Chunk) | `scripts/smoke_props_slots.py` **[1]** |
| `detect_slots`: Präfix, feste Liste, Groß/Klein, Dedup, Reihenfolge — plus rote Probe („glasses", „slots_x", „picture_frame") | ebenda **[2]** |
| Erkennung läuft beim Modell-Eintreffen NACH bake/retexture/LOD; Record trägt `slots` + `slots_auto true` | ebenda **[3]** |
| …und auf der GENERATIONS-Kette, die `_store_bbox` überspringt (img2mesh-Dienst gefälscht) | ebenda **[3b]** |
| Ein neues Mesh ERSETZT eine Auto-Liste — auch mit leerem Ergebnis | ebenda **[3c]** |
| Patch-Pfad weist kaputte Listen ab und schreibt dabei nichts; gespeicherte Liste ist klein und dedupliziert | ebenda **[4]** |
| Von Hand gepflegte (auch geleerte) Liste überlebt das nächste Modell | ebenda **[5]** |
| Eine Platzierung/Öffnung mit `slot_values` verliert das Feld beim Speichern, und am Spec entsteht kein `slots` daraus | `scripts/smoke_scene_recipe.py` **[3p]** |
| `applySlotMaterials`: das benannte Material bekommt eine `map`, das andere bleibt DASSELBE Objekt, und zwei Platzierungen derselben Cache-Gruppe haben VERSCHIEDENE Material-Instanzen | `scripts/smoke_slot_materials.mjs` **[1]/[2]** |
| `applySlotMaterials` streift das Präfix ab: Materialien `slot_picture_1`/`slot_glass_1` werden von den Schlüsseln `picture_1`/`glass_1` gefüllt — plus rote Proben (roher Name als Schlüssel trifft nichts, `slotpicture_1` ohne Unterstrich ist kein Treffer, nur EIN Präfix fällt) | ebenda **[8]** |
| Glas-Preset setzt `transparent` + die Konstanten, `transmission` nur wo das Feld existiert | ebenda **[3]** |

## Nachtrag 2026-08-27 (§ B2): Bild-Props (v5) — das Bild reitet auf der VARIANTE

Ein Rahmen-Prop (Bilderrahmen, Tür mit Scheibe, Bildschirm, Schild) trägt seit
`spec-picture-props.md` **Flächen** im Mesh: die Faces einer erkannten Fläche `k`
liegen auf dem Material `slot_picture_<k>` bzw. `slot_glass_<k>` mit planaren
UVs 0…1. **Welches Bild** darin hängt, ist eine **Variante** des Props (D2) —
keine Eigenschaft der Platzierung (D3: der Platzierungs-Picker ist entfernt) und
kein eigenes Prop.

### Woher `slots` am Spec kommt

```
spec["slots"] = { **prop.area_defaults, **variante.slot_values }
```

Zwei Quellen, eine Vereinigung, in dieser Reihenfolge. Der Schlüssel ist in
beiden Quellen die **Flächen-ID** — und die ist zugleich der Slot-Name, also der
Materialname ohne `slot_`-Präfix (`slot_picture_1` → `picture_1`). Genau diesen
Schlüssel schlagen die Renderer nach, siehe
[„Der Tausch im Renderer"](#der-tausch-im-renderer-applyslotmaterials).

| Quelle | Wo gespeichert | Wofür |
|---|---|---|
| `area_defaults` | Prop-Sidecar, `{"<area id>": {"preset": "glass"}}` | prop-weite Aussage, gilt **ohne** Variante — die Scheibe einer Tür |
| `slot_values` | **Varianten**-Eintrag in `model_variants`, `{"<area id>": {"image": "<url>"}}` oder `{"preset": …}` | das Bild, das jemand auf DIESE Version des Rahmens gehängt hat |

Die Variante wird mit der EINEN Regel aufgelöst (`_variant_index` → Position in
der veröffentlichten Varianten-Liste → dieser Eintrag), also aus demselben
Eintrag wie das Mesh, das die Kopie zeigt. Eine Platzierung ohne Variante — und
jede Platzierung jedes gewöhnlichen Props — bekommt damit nur die Defaults; ein
**Tür-Prop** (`_door_prop_models`) hat keine Varianten und bekommt ausschließlich
die Defaults. Ist das Ergebnis **leer**, fehlt der Schlüssel `slots` ganz:
„keine Slots" heißt für beide Renderer „render das Mesh, wie es modelliert
wurde", und ein leeres Objekt sagte in jedem Payload jeder Welt dasselbe.

**Kein zweites Tor im Rezept.** Geprüft wird beim SPEICHERN der Variante
(`props.set_variant_slot_values`): die Fläche muss im Prop-Sidecar `areas`
stehen, eine `picture`-Fläche nimmt eine Bild-URL dieser Welt
(`/world/locations/<loc>/gallery/<file>` oder `/characters/<name>/images/<file>`),
eine `glass`-Fläche ein Preset aus `SLOT_PRESETS`. Alles andere ist ein 400, und
gespeichert wird nichts. Das Rezept liest die abgelegten Werte wörtlich.

**Der `label` ist dreiwertig (R10)** — „der Körper hat nichts gesagt" und „der
Admin hat das Feld geleert" sind verschiedene Aussagen:

| `label` im Körper | Wirkung |
|---|---|
| fehlt / `null` | der gespeicherte Name **bleibt** — ein neues Bild benennt die Variante nicht hinter dem Rücken des Admins um |
| `""` | wird aus den neuen Bild-Dateinamen **neu hergeleitet** (auch der Fall einer frisch angelegten Variante) |
| Text | wird wörtlich gespeichert (getrimmt, gekappt) |

**Verschwindet eine Fläche, verschwinden BEIDE Hälften.** Ein erneuter Split
oder ein Mesh, das ein Material nicht mehr nennt, zieht die Fläche aus dem
Sidecar (`_reconcile_areas` bzw. der Split-Landung) — und mit ihr den Eintrag
aus `area_defaults` **und** aus den `slot_values` **jeder** Variante
(`_prune_to_areas`). Der `label` bleibt: er ist der Name der Version, keine
Beschreibung ihrer Werte. Am Spec steht danach kein toter Schlüssel mehr.

### Felder am Varianten-Eintrag (`GET /world/props/{id}/variants`)

| Feld | Bedeutung |
|---|---|
| `slot_values` | `{}` = diese Variante zeigt nichts Eigenes |
| `label` | Anzeigename; hergeleitet aus den Bild-Dateinamen (Basisname ohne Endung, `", "`-verbunden), bei reinem Glas aus dem Preset |
| `stale` | die **kopierte** Rahmen-Geometrie ist älter als das Mesh, das das Prop jetzt zeigt |

### Die Kopie und `stale` (R4)

Eine Bild-Variante **kopiert** die primäre GLB unter ihren eigenen Stem
(`ModelGallery.new_path` + `write_sidecar` + `select`), samt `<model>.glb.areas.json`
und Quellbild; die LOD-Stufe entsteht wie bei jeder Variante (`request_low_tier`).
Das spart jede Referenz-Mechanik — Auswahl, Stufen, Signatur und Rezept bleiben
unangetastet — und kostet eine GLB je Bild.

Der Sidecar der Kopie trägt dafür

```json
"copied_from": {"file": "model_1787866010.glb", "signature": "a3fc8b8b6aa0"}
```

und daraus folgt die Antwort auf „veraltet?" ohne Raten:

```
stale  ⟺  copied_from.file ≠ der AKTIVE full-Datei­name der primären Variante
```

Ein Mesh ohne `copied_from` (die primäre Variante selbst, eine hochgeladene
Variante) ist nie veraltet — es ist niemandes Kopie; und solange die primäre
Variante gar kein aktives full-Mesh hat, ist nichts veraltet, weil es nichts
zu vergleichen gibt. `POST …/variants/{i}/recopy`
kopiert erneut (neue Galerie-Datei, die alte bleibt als Historie stehen) und
**behält die `slot_values`**.

### Signatur

`props._prop_record.model_signature` nimmt `area_defaults` und die
`slot_values` **aller** Varianten mit auf. Ein Bildwechsel ändert weder Mesh
noch Stufe noch URL — ohne das im Schlüssel behielte ein laufender Client das
alte Poster an der Wand. Über `model_sig` an der Platzierung wandert das in die
Raum- und damit in die Szenen-Signatur. Props, die nichts über Bilder sagen,
behalten ihren Schlüssel Zeichen für Zeichen.

### Handbeispiel

Rahmen-Prop mit den Flächen `picture_1` (Art `picture`) und `glass_1` (Art
`glass`), `area_defaults = {"glass_1": {"preset": "glass"}}`, vier aktive
Varianten, davon Variante 1 mit
`slot_values = {"picture_1": {"image": "/world/locations/demo/gallery/x.png"}}`:

| Platzierung | `slots` am Spec |
|---|---|
| `{"prop_id": "frame", "variant": 1}` | `{"glass_1": {"preset": "glass"}, "picture_1": {"image": "/world/locations/demo/gallery/x.png"}}` |
| `{"prop_id": "frame"}` (ohne Variante → Position 0) | `{"glass_1": {"preset": "glass"}}` |
| `{"prop_id": "frame", "variant": 5}` (5 mod 4 = 1) | wie Variante 1 — ein Index außerhalb wickelt, er 404t nie |
| Tür-Prop ohne `area_defaults` | kein `slots`-Schlüssel |

### API (admin-only, `app/routes/prop_variants.py`)

| Route | Körper | Antwort |
|---|---|---|
| `POST /world/props/{id}/variants/picture` | `{slot_values, label?}` | `{status, index, variant}` — neue Variante mit Mesh-Kopie |
| `POST /world/props/{id}/variants/{i}/slot-values` | `{slot_values, label?}` | `{status, index, slot_values, label}` |
| `POST /world/props/{id}/variants/{i}/recopy` | — | `{status, index, variant}` |

`label` folgt an beiden Routen der Dreiwertigkeit oben: **weggelassen** heißt
„nicht erwähnt" (Name bleibt bzw. wird bei einer neuen Variante hergeleitet),
`""` heißt „neu herleiten", Text wird gespeichert.

400 mit dem Text des Stores für unbekannte Fläche, LEERE Zuordnung (das ist
eine gewöhnliche Modell-Variante, keine Bild-Variante), falsche URL-Form,
Preset an einer Bild-Fläche (und umgekehrt), erreichten Varianten-Cap (R5) und
die primäre Variante bei `recopy`; 409, solange die Variante generiert — der
Store weist das ein zweites Mal ab, ein Rennen kommt also nicht daran vorbei.

### Die Beweise (§ B5a)

| Was | Wo |
|---|---|
| Bild-Variante anlegen: neue Stem-Datei, Mesh Byte für Byte, `.areas.json` + Quellbild wandern mit, `copied_from` zeigt auf die Primär-Datei | `scripts/smoke_props_areas.py` **[5]** |
| `label` aus den Bild-Dateinamen bzw. aus dem Preset | ebenda **[5]** |
| Prüfung: unbekannte Fläche, fremde URL, Preset an Bild-Fläche, Bild an Scheibe, Preset außerhalb `SLOT_PRESETS` — und der Sidecar bleibt Byte-identisch | ebenda **[6]** |
| Der Varianten-Cap gilt auch für Bild-Varianten (R5) | ebenda **[7]** |
| Rezept: `variant: 1` → `slots`, ohne Variante nur Defaults, Tür-Prop nur Defaults, leer → kein Schlüssel, Index außerhalb wickelt | ebenda **[8]** |
| Prop- UND Szenen-Signatur bewegen sich bei geändertem Bild und geänderten Defaults | ebenda **[9]** |
| `stale` nach neuem Primär-Mesh, `recopy` macht frisch und behält die Werte; die alte Kopie bleibt Historie | ebenda **[10]** |
| `label`-Dreiwertigkeit (R10), leere Zuordnung abgewiesen, `recopy` während einer Generierung abgewiesen | ebenda **[11]** |
| Verschwundene Fläche: `area_defaults` UND `slot_values` jeder Variante gehen mit, `label` bleibt, am Spec kein toter Schlüssel | ebenda **[11]** |
| Primäre Variante ohne aktives full-Mesh → nichts ist `stale` | ebenda **[11]** |

### Das Türblatt als KNOTEN — `door.leaf_bbox` (spec-picture-props.md § 6, D7)

Ein generiertes Türbild zeigt immer Zarge **und** Blatt; bis hierher schwenkte
der Client die ganze Gruppe. Jetzt schneidet Blender das Blatt geometrisch aus
(größte ebene Face-Gruppe im Zargen-Inneren plus ihre Kantenfaces, oder das
Polygon des Admins mit Art `leaf`) und macht es zum eigenen glTF-Knoten
**`leaf`**; der Rest ist der Knoten **`frame`**. Materialien und UVs bleiben,
also bleibt eine Glasfläche im Blatt ein Slot-Material des Blatt-Knotens und
schwenkt mit. Beide Knoten haben Identitäts-Transform (die Welt-Matrix ist in
die Vertices gebacken). Art `leaf` ist eine Fläche ohne Farbe (Ruling R9):
kein Prompt-Fragment, nie ein Slot, nie ein Default, nicht umbenennbar —
nur `key_areas`, die Flächenliste und der Polygon-Pick kennen sie. (Das ist
NICHT das Wandstück `leaf` in `walls[]` — das ist die flache Platte im
Türloch, ein Wandteil; hier geht es um einen Knoten im Prop-Modell.)

Am Tür-Spec (`_door_prop_models`) steht dann

| Feld | Quelle | Bedeutung |
|---|---|---|
| `door.leaf_bbox: {min: [x,y,z], max: [x,y,z]}` | Prop-Sidecar `leaf_bbox` (vom Split-Lauf) | die Box des `leaf`-Knotens in **rohen** y-up-Modell-Metern, VOR der `fit`-Skalierung von `place()`; fehlt, solange das Mesh keinen `leaf`-Knoten hat — dann schwenkt wie bisher die ganze Gruppe |

Der Client (`registerDoorProp`) sucht im platzierten Klon das Kind `leaf`,
hängt es in eine Pivot-Gruppe — Ursprung und Achse liefert die EINE geteilte
Routine **`leafPivot(bbox, fix_euler)`** in `packages/scene-render/src/leafPivot.ts`
(beide Renderer rufen sie: `hangLeafPivot` im 3D-Client, der „Test swing" des
Admin-Viewers) — innerhalb der skalierten Modellwurzel und UNTER dem
Orientierungs-Fix, darum sind die rohen Koordinaten die richtigen — und dreht
(`swingDoorProps`) **nur diese**, per `setRotationFromAxisAngle(axis, winkel)`;
`retargetDoorProp` hängt sie nach dem Stufenwechsel neu. Winkel, Ease und Gate
sind unverändert.

**Ruling R12 (2026-08-28): die Angel ist für BEIDE Angeln die −x-Seite.**
`place()` setzt jedes `fit`-Modell mit seiner −x-Kante in den Ursprung
(§ B2 v5), und `_door_prop_models` dreht eine rechts angeschlagene Tür um
zusätzliche 180° um genau diese Kante (`yaw = atan2(−uz, ux) + 180`). Eine
rechte Tür ist also dasselbe Modell umgedreht, nie gespiegelt. `max.x` bei
rechter Angel setzte die Achse auf die FREIE Kante und schwenkte das Blatt
durch die Zarge. `hinge` liefert weiterhin nur das Vorzeichen (`swing`).

**Ruling R13 (2026-08-28): die −x-Kante ist die des FIX-Rahmens, nicht des
rohen.** `place()` misst die Kiste NACH dem Orientierungs-Fix (`bFix`,
`fix.position.x = −bFix.min.x`), der Pivot hängt aber unter dem Fix in rohen
Koordinaten. Die Regel wird deshalb im Fix-Rahmen ausgesprochen und
zurückgerechnet: die 8 Ecken von `leaf_bbox` mit der Fix-Rotation R drehen
(three-Euler **'YXZ'** = Ry·Rx·Rz, dieselbe Reihenfolge wie `place()`, feine
Winkel), dort **x = min, y = min, z = Mitte** wählen, den Punkt mit Rᵀ
zurückdrehen; die Achse ist Rᵀ·(0, 1, 0). Fix 0 ergibt genau R12
(min.x, min.y, Mitte z; Achse +y). Ein y-Fix von 180° legte sonst die Angel
auf das rohe `max.x` (die freie Kante), ein y-Fix von 90° auf eine z-Kante,
und jeder x/z-Fix kippte die Achse.

Handbeispiel (`scripts/smoke_scene_recipe.py` **[3p]**, `scripts/smoke_leaf_pivot.mjs`):
Sidecar `leaf_bbox = {min: [0.1, 0.1, −0.02], max: [0.9, 2.1, 0]}` (ein
0,8 × 2,0-m-Blatt, 2 cm dick, 2 cm zurückgesetzt in einer 1,0 × 2,2-m-Zarge)
→ `door = {opening: 0, hinge: "right", swing: −1, leaf_bbox: {…}}` wörtlich,
Anker/Yaw/`fit` unverändert; ohne Sidecar-Wert **kein** Schlüssel (nicht
`null`). Pivot `leafPivot(bbox, fix)`: Fix 0 → Punkt (0.1, 0.1, −0.01), Achse
(0, 1, 0); Fix y = 180° → (0.9, 0.1, −0.01) (das rohe `max.x` IST die
Fix-−x-Kante), Achse (0, 1, 0); Fix y = 90° → (0.5, 0.1, −0.02) (die rohe
min.z-Kante), Achse (0, 1, 0); Fix x = 90° → (0.1, 1.1, 0), Achse (0, 0, −1)
(die Achse kippt); Fix z = 90° → (0.1, 2.1, −0.01), Achse (1, 0, 0). Jede
Zahl von Hand, dazu der Gegenbeweis, dass R three's Euler(YXZ) ist. Der Split selbst:
`scripts/smoke_door_leaf_blender.py` (Ring aus vier Quadern um eine
zurückgesetzte Platte → Knoten `frame` 48 / `leaf` 12 Dreiecke, `leaf_bbox`
wie oben, `delete` fügt zu einem Knoten zurück); die Heuristik ohne Blender:
`scripts/smoke_picture_areas.py` Fixture F.

## Nachtrag 2026-08-28 (§ B2): Bild-Props v2 — Flächen, Türblatt und Orientierung gehören zur MODELLDATEI

**Anlass** (`development_instructions/befunde-bild-props-2026-08-28.md`, Wurzel 1,
gemessen an einem echten Tür-Prop): jede Variante ist eine **eigene**
img2mesh-Generierung — Variante `model-v3` hatte andere Achsen und keinen
`leaf`-Knoten —, aber `areas`, `leaf_bbox`, `rotation` und `area_defaults`
lagen **prop-weit** im Sidecar, der Areas-Tab und der Landing-Hook kannten nur
die Primärvariante, und das Rezept las `leaf_bbox`/`area_defaults` vom Prop-Record.
Entscheid **E1** (`spec-bild-props-v2.md`): **Flächen gehören zur Modelldatei.**

### Datenmodell

| Wo | Felder | Bemerkung |
|---|---|---|
| Sidecar der **Full-Datei** (`model_<ts>.json`, `props.file_areas` / `props.set_file_areas`) | `areas[]`, `leaf_bbox`, `rotation {x,y,z}`, `areas_run_at`, `areas_error`, `areas_warning`, `key_areas_run[]` | das Gemessene DIESER Datei; `areas_warning` (heute nur die No-Leaf-Notiz) ist seit v2 ein **eigener** Schlüssel neben `areas_error`; `key_areas_run` = welche Arten der letzte automatische Lauf wirklich gesucht hat |
| Sidecar der **Low-Datei** | `inherits_from: <Full-Dateiname>` + Kopien von `areas`/`leaf_bbox`/`rotation` | `file_areas(low)` antwortet über `inherits_from` mit den Werten der Full-Datei (Decimate behält Knoten und Materialien — gemessen); die Kopien sind für einen Leser, dessen Full-Datei verschwunden ist |
| **Varianten-Eintrag** (`model_variants[i]`) | `area_defaults {"<area id>": {"preset": "glass"}}` | neben `slot_values`/`label`; geprüft gegen die Flächen der **eigenen** Datei; eine neue Variante KOPIERT die Defaults ihrer Quellvariante (`_COPIED_ON_ADD`), das Landen ihres Meshes stutzt sie auf das, was die Datei nennt |
| Prop-Sidecar | `key_areas[]` **bleibt** (Ruling V2: der Wunsch für die nächste Generierung) | `areas`, `leaf_bbox`, `rotation`, `area_defaults`, `areas_error`, `areas_run_at` sind **weg** — einmalige Boot-Migration `app/core/prop_areas_migrate.py` (Ruling V0): Werte auf die aktive Full-Datei der Primärvariante (+ Low), der alte `rotation`-Wert auf die aktive Full-Datei **jeder** Variante (Ruling V4 — er galt vor dem Boot für alle; nur eine Varianten-KOPIE bekommt dazu ihre `areas`/`leaf_bbox` aus dem `.areas.json`-Begleiter zurück), `area_defaults` an den Primär-Eintrag; danach **kein** Fallback-Leser |
| **Prop-Record** | `variant_tiers[i]` += `areas`, `rotation`, `area_defaults`, `areas_warning` (immer) und `leaf_bbox` (nur solange das Mesh einen `leaf`-Knoten hat) | die prop-weiten Felder `areas`/`area_defaults`/`leaf_bbox`/`rotation` **entfallen ohne Alias**; `model_signature` nimmt jetzt **jeder** Variante `area_defaults`+`slot_values` und den Fix jeder aktiven Datei mit (eine gedrehte Variante 1 invalidiert die Szenen, die sie zeigen) |

Regel für neue Dateien: die **Orientierung wird je Datei gesetzt**
(`POST /world/props/{id}/rotation?variant=i[&filename=…]`, Muster
`location_model3d.set_rotation`); eine neue Datei derselben Variante (Upload,
Generierung) **startet mit dem Fix der Datei, die sie ersetzt**, ein Split
(`_land_split`) übernimmt den Fix seiner Eingabedatei — die Dial-Vorbelegung
der Befunde. Ein Fix auf der aktiven Full-Datei wird auf die aktive Low-Datei
kopiert; ein Fix, der auf eine erbende Low-Datei zielt, landet auf ihrer
Full-Datei.

### Rezept

```
entry = variant_tiers[_variant_index(placement, len(model_variants))]   # die aufgelöste Variante
spec["fix_euler"]  = fix_euler(entry.rotation)
spec["slots"]      = { **entry.area_defaults, **entry.slot_values }       # leer → Schlüssel fehlt
spec["leaf_bbox"]  = entry.leaf_bbox                                       # nur wenn vorhanden
```

`_prop_models` liest **je aufgelöster Variante** (`_placement_entry`), nie
einen prop-weiten Wert; `_door_prop_models` liest die **Primärvariante**
(`variant_tiers[0]` — Öffnungen tragen keine Variante, Ruling V1): `fix_euler`,
`door.leaf_bbox` und `slots` aus deren Datei bzw. Eintrag. Neu am
Raum-Platzierungs-Spec: `leaf_bbox` (rohe y-up-Modell-Meter der aufgelösten
Variante), wenn deren Mesh einen `leaf`-Knoten hat — dieselbe Bedeutung wie
`door.leaf_bbox`, ohne Schwenk-Auftrag.

Handbeispiel (`scripts/smoke_scene_recipe.py` **[3p]**, „the PLACED VARIANT
decides"): Prop `frame`, Variante 1 mit `rotation {y: 90}`, `areas [glass_1]`,
`area_defaults {glass_1: glass}`, `leaf_bbox`; Variante 0 ohne alles. Zwei
Kopien in Raum a (x −4…0, z −4…−1), `at [1, 1]` auf Variante 1 → Anker
(−3, −3), `at [2, 1]` auf Variante 0 → (−2, −3): Variante 1 → `fix_euler
{0, 90, 0}`, `slots {glass_1: {preset glass}}`, `leaf_bbox` = ihre Box;
Variante 0 → `fix_euler 0`, **kein** `slots`, **kein** `leaf_bbox`. Tür-Spec
mit `variant_tiers[0].rotation {y: 270}` → `fix_euler {0, 270, 0}`.

### Routen

`GET/POST/PATCH/DELETE /world/props/{id}/areas[/{area_id}]?variant=<i>`
(Query; ohne = Primärvariante; unbekannter Index 404). `GET` antwortet
`{variant, model_file, areas(+edges), mesh_layout, key_areas, key_areas_run,
area_defaults, leaf_bbox, rotation, blender, last_run, error, warning}` — alles
außer `key_areas` von der aktiven Datei dieser Variante. `POST` mit `mode:
"auto"` nimmt optional `kinds: ["picture","glass","leaf"]` (das „Jetzt
erkennen" des Tabs, E3: **genau** diese Arten). Neu: `POST
/world/props/{id}/variants/{i}/area-defaults {area_defaults}`; ein Prop-PATCH
mit `area_defaults` ist ein 400, das diese Route nennt (`MOVED_TO_VARIANT`).
`POST /world/props/{id}/rotation?variant=i&filename=` antwortet `{status,
variant, filename, rotation, prop}`; ein unbekanntes Prop, eine unbekannte
Variante oder ein fremder Dateiname ist ein 404. Eine Variante **ohne** Mesh
hat keine Datei und damit keine Flächen: `slot_values`/`area_defaults` werden
gegen die Flächen ihrer aktiven Full-Datei geprüft und sind bis zum ersten
gelandeten Mesh nicht setzbar (E1 — es gibt nichts, worauf ein Bild hängen
könnte). Der Landing-Hook (`_areas_after_landing`)
läuft für **jede** Variante (Tor: `key_areas` nicht leer oder Tür-Prop);
`_reconcile_areas(pid, variant)` gibt einer Datei ohne Lesung ihre Liste (aus
dem `.areas.json`-Begleiter, sonst „keine Flächen") und lässt die Defaults
**dieser** Variante ihrer aktiven Datei folgen; `slot_values` bleiben bei
einem Galerie-Klick unberührt (R15, jetzt je Variante), ein Split/Rename/
Delete/Re-Copy auf Variante i stutzt beide Hälften **von i**. Beweise:
`scripts/smoke_props_areas.py` Teil 3 [15]–[17], `scripts/smoke_prop_areas_migrate.py`.

### Türblatt = Durchstich-Prisma (E2), Restzahl, `adopt` (E6) — 2026-08-28

**Anlass** (Befunde Wurzel 2, gemessen an `door-wood-f4b1d4`): der v1-Schnitt nahm
nur die sichtbare **Haut** — 432 von 614 Blatt-Dreiecken in einer 1,8-cm-Schicht,
979 Rahmen-Dreiecke als zweite Haut 6 cm dahinter; die Tür war „zu und offen
zugleich". Seit E2 ist das Blatt ein **Prisma**: `picture_areas.prism_faces` nimmt
**jedes** Face, dessen Zentrum in die Blatt-Grundfläche projiziert — über die
**gesamte Tiefe**, ohne Sichtbarkeits- und Normalentest (Vorderhaut, Rückhaut,
Kanten, Klinken **und** der Teil der Rahmen-Rückhaut hinter dem Blatt). Auto:
Grundfläche = `inner` der Blattebene — den Rand messen **nur seitwärts stehende**
Faces (Normale > 18° von der Blattebenen-Normale: Zargen, Riegel, Blattkanten), nie
Faces, die bloß in der Tiefe abweichen (eine fein triangulierte Vorderhaut oder die
Rückhaut würde das Blatt sonst auf die Türmitte beschneiden); kein messbarer Rand →
0, die Silhouette ist die Grundfläche; ein Face, das mehr als ein Viertel der Achse
hineinreicht, ist eine Haut und misst keinen Rand. Manuell: der Client sendet für Art `leaf` `through:
true` (Polygon = alle Faces mit Zentrum im Ring, `Model3DViewer.selectFaces`), der
Server bildet aus den **Zentren** der gelisteten Faces die Grundfläche in deren
Ausgleichsebene und schneidet dasselbe Prisma (`leaf_prism`) — die Client-Liste ist
eine Auswahl, nie die Geometrie-Wahrheit. Ein Face **auf** der Grundflächenkante
(sub-mikron, nur modellierte Meshes) gehört zum Blatt, wenn seine Normale aus der
Grundfläche hinauszeigt (Blattkante), nicht hinein (Zarge). Bild/Glas behalten die
Sichtauswahl. Jeder Lauf mit Blatt meldet `leaf_residual` = Rahmen-Faces, deren
Zentrum mehr als 2 cm innerhalb der Grundfläche liegt, **durch die geschnitten
wurde** (auto: `inner`; manuell: Umriss der Zentren der gelisteten Faces — ein
v1-artiger Hautschnitt der Blattmitte meldet so die Rückhaut dahinter); `leaf_bbox`
wird in der Ebene auf diese Grundfläche geklemmt (`clamp_bbox` — die Angel liegt auf
der Blattkante, nicht auf einem überstehenden Rückhaut-Vertex); > 0 wird
`areas_warning` = `LEAF_RESIDUAL_NOTE` („{n} frame faces remain inside the leaf
footprint — draw the leaf again or check the door"). E6: benannte Materialien
(`slot_<name>`, `picture|screen|sign|glass`) werden beim Landen zu Areas (`mode:
"adopt"`, vor dem Schlüsselfarben-Lauf): Fläche aus den Faces des Materials, **keine**
UV-Umschreibung, keine Backup-Lage, Knotenbaum unverändert; das Material wird auf
den kanonischen Namen `slot_<kind>_<k>` **umbenannt**, wenn es den nicht schon
trägt (`glass*` → glass, sonst picture) — nur unter diesem Namen können Renderer
(`applySlotMaterials`), Delete und Rename die Fläche adressieren; Quelle `adopt`,
von `auto`-Läufen nicht aufgelöst (R14). R16: der Umriss (`edges`) wird auf den
**gewelded** Faces gerechnet — 16 Kanten für ein 4 × 4-Feld nach dem Round-Trip,
nicht 96. Beweise: `scripts/smoke_picture_areas.py` Fixture G (332 Prisma-Faces =
12 Blatt + 320 Rückhaut; v1 hätte 12 genommen; G' mit 16 × 16-Vorderhaut: Rand 0,1,
842 Faces, Hautschnitt der Mitte → Restzahl 8), `scripts/smoke_door_leaf_blender.py`
[H] (Landing 332/168, `through` 10 → 332, Restzahl 2, G' 842 + Restzahl 8),
`scripts/smoke_picture_areas_blender.py` [I] (adopt, Namenskollision) + [H] (R16).

## Nachtrag 2026-08-27 (§ B2): Oberflächen-Raster (v6)

**Anlass** (User am Ort „Klippen"): „Die Laufhöhe des Avatars ist die Höhe des
Landes darunter und nicht die Oberfläche des Dioramas (also mit Steinen, Höhen
und Tiefen) … Das gleiche gilt für Props." Das stimmte: seit E5b liefert **kein
Mesh eine Höhe**. Die Raycast-Sprosse ist gelöscht (`client3d/src/game/ground.ts`),
`tileWalkY` kannte drei Sprossen, alle aus Daten, Props gar keine — und der
Server prüfte Schritte allein gegen `relief.ground_at`.

Die Antwort ist **kein Client-Raycast**, sondern ein **serverseitig gebackenes
Höhenraster je Modell**: Blender misst einmal, was begehbar ist, das Rezept
schickt das Raster **inline am Platzierungs-Spec**, und **eine** Sample-Formel
macht daraus eine Standhöhe — in beiden Renderern UND im Schritt-Tor des
Servers. Der Renderer misst weiterhin nichts, er liest.

### Die Entscheide (Kurzfassung)

| Nr. | Frage | Entscheid |
|---|---|---|
| 0 | Mechanik | Server-gebackenes Höhenraster je Modell; kein Client-Raycast |
| 1 | Modell-Kreis | Dioramen (`role:"room"`) + Raum-Props (`role:"prop"`); Gebäude und Karten-Props (`world_props`) bleiben wie heute |
| 2 | Raster | 0,25 m; je Zelle die niedrigste nach oben weisende Fläche, über der ≥ 1,2 m frei ist; keine Fläche = `null` → Terrain |
| 3 | Backzeitpunkt | beim Landen + Improvements-Typ für den Bestand + Neubacken bei Fix-Drehung |
| 4 | Gültigkeit | die Datei trägt `version`, Quell-Identität und Fix; abweichend = fehlend = heutiges Verhalten |
| 5 | Mulden | Terrain bleibt Untergrenze (`standY = max` unverändert) |
| 6 | Server-Prüfung | der Server liest DASSELBE Raster mit derselben Formel |
| 7 | Props | alle Props werden gebacken, Wirkung nur mit Tag `walkable` (Standard: aus) |
| A | Ansatz | Raster im Modell-Rahmen (nach exaktem Fix), eigene Datei neben dem Modell, inline im Rezept, EINE Sample-Funktion in `packages/scene-render` + Python-Zwilling |
| R1 | Ruling | das Raster **schlägt** die `walk_y`-Deklaration (Sprosse 0); `null`-Zellen fallen weiter auf sie zurück |
| R2 | Ruling | Kopffreiheit 1,2 m statt Figurhöhe 1,7 m — eine niedrige Höhle bleibt begehbar, statt die Figur aufs Höhlendach zu heben |
| R3 | Ruling | das höchste antwortende Raster gewinnt (Kiste auf Fels); keine `plateCeiling`-Kappung auf Rastern |

### Das Backen — was im Raster steht

`app/blender/scripts/heightgrid.py`, gerufen über `runner.run("heightgrid", …)`
und wie jede Blender-Stufe über einen LOD-Slot gegattet.

* **Modell-Rahmen nach exaktem Fix.** Das Skript wendet den Sidecar-Fix
  (`rotation`, Euler `'YXZ'`) an und rechnet in glTF-Achsen zurück — `box_min`,
  `box_max`, `origin` und `values` stehen damit in derselben Achsenlage wie in
  three.js.
* **Zwei Boxen** nach der three-Methode (`Box3.setFromObject`, die 8 Ecken jeder
  Objekt-BBox transformiert): `box` unter dem **exakten** Fix (davon Ursprung,
  Mitte, Unterkante) und `extent_snapped` als Größe unter dem auf 90°
  **gerundeten** Fix — genau der Maßstabsnenner, den `place()` benutzt.
* **Der Schritt sind 0,25 WELT-Meter** (Korrektur 2026-08-28, Datei-`version` 2).
  Das Raster wird im **Modell-Rahmen** ausgelegt, ein generiertes Mesh ist aber
  auf ~1 Einheit normiert und wird erst beim Platzieren mit
  `s = target_m / extent(measure)` skaliert (`placeModelSpec`, dieselbe Formel
  wie `surface_scale`). Der Schritt in der Datei ist deshalb
  **`step = 0,25 / s`** in Modell-Einheiten; `step_world = step · s` steht
  informativ daneben. `target_m` ist die Zahl, mit der der Renderer skaliert —
  beim Raum `width_m`, sonst die längere Seite des Raum-Rechtecks
  (`scene_recipe.diorama_max_m`, `measure: "xz"`), beim Prop `max(width_m,
  depth_m, height_m)` der Variante (`measure: "xyz"`). Ohne `target_m` (0)
  weiß das Skript nichts über die Weltgröße und nimmt den Schritt wie
  übergeben. *(Vorher wurde 0,25 als Modell-Einheit gelesen: ein 10-m-Diorama
  bekam 5 statt 41 Knoten je Seite, Felsen wurden weggemittelt und die Figur
  stand im Stein.)*
* **Knoten** bei `origin + i·step`, `cols = ceil(Breite/step) + 1`, `rows`
  analog in z. Ist `cols·rows > max_cells` (40 000), verdoppelt sich `step` und
  es wird neu gerechnet; das Raster nennt seinen Schritt selbst. Der äußerste
  Ring wird `EDGE_NUDGE` = 1 mm nach innen geschossen, aber am nominellen
  Knoten gelesen.
* **Die Zellenregel:** ein Strahl von oben sammelt ALLE Treffer samt
  Orientierung; genommen wird der **niedrigste nach oben weisende** Treffer,
  über dem bis zum nächsten Treffer (beliebiger Orientierung) mindestens
  `clearance` = 1,2 m frei sind — der oberste hat unendlich Luft und
  qualifiziert immer. Kein nach oben weisender Treffer → `null`, dort antwortet
  das Raster nie. **Die Kopffreiheit sind WELT-Meter wie der Schritt** und
  werden im Bake genauso durch `s` geteilt (`clearance_model = 1,2 / s`),
  bevor das Raster gelaufen wird (Korrektur 2026-08-28, Datei-`version` 3).
  *(Vorher wurden die 1,2 gegen Modell-Koordinaten verglichen: ein auf ~1
  Einheit normiertes Mesh ist nirgends 1,2 Einheiten hoch, also qualifizierte
  nur der oberste Treffer — jedes Raster war die Silhouetten-Oberkante, das
  Hüttendach statt des Hüttenbodens.)*
* **`values`** sind Zentimeter-Ints über `box_min.y`, zeilenweise
  `values[j*cols + i]`, `null` = keine Fläche.

### Die Datei — `<modell>.surface.json`

`app/core/model_surface.py`. Sie liegt neben ihrem Modell
(`raum_1.glb` → `raum_1.glb.surface.json`), matcht das Modell-Muster der
Galerie absichtlich NICHT und wird beim Löschen des Modells
(`ModelGallery.delete`) mit gelöscht — das Raster stirbt mit seinem Mesh.

```jsonc
{
  "version": 3, "step": 0.025,
  // Buchhaltung, keine Nutzlast: bei welcher Weltgröße die Auflösung gewählt
  // wurde. step_world = step · s = 0,25 m.
  "target_m": 20.0, "measure": "xz", "step_world": 0.25,
  "source": {"name": "raum_1.glb", "size": 812344, "mtime": 1787869178},
  "rotation": {"x": 0.0, "y": 90.0, "z": 0.0},
  "box_min": [-1, 0, -1], "box_max": [1, 1.6, 1],
  "extent_snapped": [2, 1.6, 2],
  "origin": [-1, -1], "cols": 81, "rows": 81,
  "values": [20, 20, null, /* … cols·rows Einträge, zeilenweise … */],
  "hits": 6561,
  "baked_at": "2026-08-27T22:19:36Z", "blender": "4.2.5 LTS"
}
```

**Gültigkeit ist eine Eigenschaft der DATEI** (`read_surface`): sie nennt ihr
Format (`SURFACE_VERSION` = **3** seit 2026-08-28 — eine v1-Datei wurde in der
falschen Auflösung gemessen, eine v2-Datei verglich die Kopffreiheit in
Modell-Einheiten; beide lesen sich damit als `stale` und werden neu gebacken,
umzurechnen gibt es nichts), das Modell, aus dem sie gebacken wurde (Name +
Größe + mtime), und den Fix, unter dem das geschah (je Achse `% 360`, auf 0,1°
verglichen) — und sie muss alle acht Nutzlast-Felder tragen. Weicht eines ab,
liest sie sich als „kein Raster": heutiges Verhalten, nie ein veralteter Boden.
Für die Admin-Zeile unterscheidet `surface_status` `baked` / `missing` /
`stale` — und nennt dort `step` in **Welt-Metern** (`step_world`), denn die
Zeile „baked 81×81 @ 0,25 m" verspricht eine Länge auf dem Boden, nicht in
Modell-Einheiten. Ein Modell ohne jede nach oben weisende Fläche bekommt eine Datei
voller `null` — sonst würde ewig neu gebacken.

### Am Spec (§ B2)

| Feld | Wo | Bedeutung |
|---|---|---|
| `surface` | `models[]` mit `role: "room"`, und `role: "prop"` **mit** `walkable` | der Nutzlast-Block `step, origin, cols, rows, values, box_min, box_max, extent_snapped` — die Zahlen der Datei unverändert, im Modell-Rahmen |
| `walkable` | nur Prop-Spec | das Prop trägt das Tag `walkable`; ohne das Feld schickt es kein Raster (das Raster einer Tischplatte wäre totes Gewicht in jeder Nutzlast) |

Gebäude-Specs bekommen keins (Entscheid 1). `code_version` steht auf **8** —
die Konstante gehört dem ganzen Payload, nicht diesem Abschnitt, und bewegt
sich mit jeder Änderung an dem, was der Composer bei unveränderten Daten
antwortet (6 = diese Raster, 7 = Platz-Typen an den Markern, 8 = der
`anchor` am Prop-Marker).

**Die Signatur.** `_signature` nimmt je Raster einen Kurz-Hash des Blocks auf
(`model_surface.block_sig`, 8 Zeichen), unter dem Schlüssel
`role:id:room:variant`. Die **Variante gehört in den Schlüssel**: zwei Kisten
desselben Props im selben Raum können verschiedene Meshes und damit
verschiedene Raster zeigen, und `role:id:room` allein ließe die zweite die erste
überschreiben. So bringt ein frisch gebackenes oder ungültig gewordenes Raster
die Clients zum Neuladen. Die Raum-Metas gehen dafür OHNE ihre Raster in den
Hash — die Zahlen stecken schon in den Kurz-Hashes.

### Die eine Formel — `surfaceHeightAt` / `surface_height_at`

`packages/scene-render/src/surface.ts` und der zeilengleiche Python-Zwilling in
`app/core/model_surface.py`. Sie ist die exakte **Umkehr von `place()`** (§ B2)
und rechnet in kachel-lokalen Metern, wie jede Spec-Zahl:

```
extent = measure == 'xyz' ? max(ex, ey, ez) : max(ex, ez)   (ex,ey,ez = extent_snapped)
s  = max_m / (extent || 1)
c  = (box_min + box_max) / 2
qx = x − anchor[0];  qz = z − anchor[1]
θ  = yaw_deg · π/180
lx = qx·cos θ − qz·sin θ            (Umkehr von three's Ry(+θ))
lz = qx·sin θ + qz·cos θ
u  = (lx / s + c.x − origin[0]) / step
v  = (lz / s + c.z − origin[1]) / step
außerhalb [0, cols−1] × [0, rows−1]  → null
bilinear über die vier Knoten; EIN null-Knoten → null
y  = bottom_y + lift + s · value / 100
```

Begründung der letzten Zeile: `place()` setzt
`outer.position.y = bottom_y − s·(box_min.y − c.y)` und hängt das Modell mit
`−c`; ein Punkt p landet also auf `bottom_y + s·(p.y − box_min.y)` — und genau
das sind `values`, in Zentimetern.

**`lift`.** Eine Etage-0-Platzierung (Raum-Diorama, Prop — nicht Gebäude, nicht
`level ≠ 0`) wird nach § A16.9 um `lift = groundAt(Anker_welt) − datum` auf das
Gelände unter ihrem EIGENEN Anker gehoben (`storeyGroundLift`, geteiltes Paket).
Das Raster steht, wo sein Modell steht: der Sampler nimmt `lift` als Parameter
(`surfaceHeightAt(surface, spec, x, z, lift = 0)`,
`surface_height_at(surface, spec, x, z, lift=0.0)`), der Client hält ihn am
Eintrag (`PlacedSurface.lift`) und schreibt ihn in demselben Trichter, der auch
das Modell bewegt (`reliftPlacement` — Montage, Höhen-Revision, Stufen-Tausch),
und der Server rechnet ihn selbst aus `ground_at(Anker_welt) − datum`.

`highestSurfaceAt(list, x, z)` bzw. `highest_surface_at(specs, x, z, lift_of)`
gibt die **höchste antwortende** Fläche (R3: Kiste auf Fels), jeder Eintrag mit
SEINEM `lift`. Die beiden Signaturen sind bewusst verschieden: der Client
sammelt eine Liste `PlacedSurface`, der Server bekommt die Rezept-Specs direkt
und reicht den Lift als Callable nach, weil er ihn je Spec selbst rechnet.
`PlacedSurface` trägt außerdem `level` und `roomId` — wer fragen darf, steht
unten.

Ein Wort zur Kante: der äußerste Knotenring wird 1 mm innen geschossen, aber am
nominellen Knoten gelesen. Ist die Box kein ganzes Vielfaches von `step`,
extrapoliert der letzte Ring damit nach außen über bis zu einen Schritt Boden,
den das Modell nicht bedeckt.

### Vier Sprossen

`tileWalkY` (`client3d/src/scene/tiles.ts`) hat seit v6 eine Sprosse mehr, und
sie steht ganz oben:

| Sprosse | Quelle | Geltung |
|---|---|---|
| **0** | **das gebackene Raster** (`bakedFloorAt` → `highestSurfaceAt`) | höchstes antwortendes Raster + `WALK_CLEARANCE_M`; **keine `plateCeiling`-Kappung** — die Kopffreiheit steckt im Backen |
| 1 | die Deklaration `walk_y_world` (`declaredFloorAt`) | wo kein Raster antwortet |
| 2 | die Stockwerks-Platten (`recipeFloorAt`) | nur deklarierte Etagen, gekappt durch `plateCeiling` |
| 3 | das Terrain | `tile.center.y`, darüber der Welt-Term von `tileGroundY` |

`standY = max(Kachel-Antwort, Weltboden)` ist **unverändert** (Entscheid 5):
eine Mulde im Diorama zieht die Figur nie unter das Gelände, auf dem sie steht.

**Wer welche Raster fragen darf**, ist keine Feinheit:

* die **Boden-Leiter** (`tileWalkY` — draußen, auf passierbarer Kachel, in einer
  always-visible-Zone) nimmt nur Einträge mit `level === 0`; sonst zöge ein
  Diorama im Erdgeschoss die Figur im ersten Stock zu sich herunter;
* die **Stände eines Raums** (`deriveRoomSpots` über `roomFloorWorldY`) und der
  **Avatar im Gebäude-Raum** (`main.roomFloorY`) nehmen nur die Raster IHRES
  Raums, auf jeder Etage — ein Boden je Raum (Gesetz 2026-08-20). Der Avatar
  wird dabei an (x, z) gefragt statt an der Raummitte, sonst liefe er durch den
  Hügel, auf dem die NPCs stehen.

`bakedFloorAt(tile, lx, lz, keep)` ist die EINE Stelle, an der `tile.surfaces`
gelesen wird; `keep` ist genau dieser Filter. Die Liste wird synchron aus der
Nutzlast gefüllt, bevor ein Mesh geladen ist — die Figur steht richtig, sobald
die Szene da ist; ein Eintrag, dessen Mesh nie lädt, behält `lift: 0`, also die
komponierte Höhe, die die Nutzlast selbst nennt.

Der Mesh-Strahl von E5b ist damit **nicht zurück**: Sprosse 0 sind DATEN, die
der Server gebacken hat, keine Messung, die der Renderer nimmt.

**Ruling R1 im Klartext:** das Raster schlägt die Deklaration. `walk_y` war der
Platzhalter für die Messung, die es nicht gab; eine Kiste über dem deklarierten
Boden erzwingt die Reihenfolge ohnehin. `walk_y` bleibt das nominelle Bodenmaß
für Schwellen (`threshold_base_y`), `plateCeiling` und die Raum-Deklaration.

### Der Server steht auf demselben Raster

`model_surface.stand_height_at(location, x, z)` =
`max(relief.ground_at(x, z), was die Szene am Punkt darüber legt)` —
dieselbe `standY`-Formel wie im Client, mit demselben Sampler.

**Drei Sprossen**, die Boden-Leiter des Clients minus der einen, die hier nicht
greifen kann:

0. **Das gebackene Raster** — `highest_surface_at` über die Etage-0-Specs mit
   `surface`; das höchste antwortende gewinnt (Ruling R3).
1. **Die Deklaration** — wo kein Raster antwortet (`null`-Zelle, Loch im Bake,
   Punkt neben jedem Modell): das `walk_y_world` eines Etage-0-Raums, geprüft
   in seinem `floor_plan`-Hull, bei Überlappung gewinnt der KLEINSTE Hull
   (`model_surface.declared_floor_of`, Python-Zwilling von `declaredFloorAt`).
   `walk_y_world` ist kachel-lokal wie `bottom_y` und bekommt denselben
   Etage-0-Lift wie seine Platzierung.
2. **Das Gelände** — `ground_at`, und zugleich Untergrenze der beiden Sprossen
   darüber (Entscheid 5).

**Die Platten (Client-Sprosse 2) fehlen mit Absicht:** seit E5a zeichnet das
Rezept nur für DEKLARIERTE Stockwerke Platten, Etage 0 hat keine, und dieses
Tor ist Etage-0-only. Es gäbe nichts zu fragen — wohl aber die Platte des
Geschosses über dem Läufer, gegen die niemand gemessen werden darf.

* Die Raster einer Location sind die Specs mit `surface` aus `compose_scene`
  (über `scene_inputs`, das dafür aus `routes/play.py` nach `scene_recipe`
  gezogen ist — eine Route darf nicht der einzige Weg zur Szene sein), **je
  Location mit 5 s TTL gecacht**: `/play/pos` läuft bis zu viermal je Sekunde
  und Läufer und fragt zwei Punkte je Meldung. Auch die leere Antwort einer
  Location ohne Szene wird gecacht.
* **Nur Etage 0**, genau wie die Boden-Leiter des Clients: eine Lauf-Meldung ist
  ein Punkt auf der Bodenebene. Wer im Obergeschoss steht, kam über einen Raum
  dorthin.
* Der **Lift** kommt aus `ground_at(Anker_welt) − datum`; `datum` ist die
  Bodenhöhe am **Pin** der Location — dieselbe Null, von der jede Szenenzahl
  misst (`tile.center.y` im Client). Ohne endliches Datum kein Raster, nur
  Boden: `storeyGroundLift` hebt dann auch im Client nicht, und das Datum als
  0 zu lesen hübe jedes Raster um die absolute Höhe seines eigenen Ankers.
* Keine Szene, keine Sprosse am Punkt, ein defekter Sidecar: **nacktes Gelände**,
  ein Log je Location. Das Schritt-Tor ist eine Plausibilitätsprüfung und darf
  nie der Grund sein, warum jemand nicht laufen kann.
* In `POST /play/pos` (§ A15 Nr. 8) misst Δh damit zwischen zwei **Standhöhen**
  statt zwischen zwei Geländehöhen — jeder der beiden Punkte mit SEINER
  Location (`location_at_point` für den Vorpunkt, denselben Fund benutzt die
  Öffnungs-Ausnahme weiter). Toleranz, `slope_blocks`, die beiden Absage-Texte
  und das Log sind unverändert.

`forget_surfaces` hängt an jedem Backen: ein Raum vergisst seine Location, ein
Prop steht in vielen und vergisst deshalb alles.

### Wann gebacken wird, und wer es auslöst

1. **Beim Landen.** Beim Prop beide Mess-Pfade (`_store_bbox` und der
   Inline-Pfad der Generierung), beim Raum `select_model` — der Trichter, durch
   den Auswahl, Upload und Generierung/Shrink alle gehen; gebacken wird das
   aktive Voll-Modell. **Nie im Request-Thread**, aber nicht überall auf
   dieselbe Weise: `_store_bbox` startet einen eigenen Hintergrund-Thread, weil
   seine Aufrufer (Upload, Auswahl, Löschen) auf dem Request-Pfad sitzen und
   ein Raster minutenlang auf einen Blender-Slot warten darf; `_generate` läuft
   ohnehin schon in seinem Job und backt dort **synchron**. Ein bereits
   gültiges Raster wird übersprungen.
2. **Bei der Fix-Drehung** (`location_model3d.request_surface`,
   `props.bake_surfaces`) sofort im Hintergrund. Bis das neue landet, ist das
   alte ungültig (`rotation` ≠) und es gilt Terrain. Ein Auftrag, der WÄHREND
   eines Backens kommt, wird nicht verworfen, sondern gemerkt — der Job hängt
   eine Runde an, damit der zuletzt gedrehte Fix der ist, der auf Platte liegt.
   Ein Backen je Galerie bzw. je Prop.
3. **Improvements-Typ `surface_bake`** („Bake walkable surfaces", Subjects
   „Room models" / „Prop models") für den Bestand. Kandidat = Modell da,
   `read_surface` antwortet `None` (fehlend, fremde Quelle und fremder Fix sind
   für ihn dasselbe). Ein belegter Blender-Slot ist **Last, kein Defekt**: der
   Schritt wartet bis zu 300 s und meldet sonst `CandidateBusy`, verbraucht also
   keinen der zwei Versuche, nach denen die Engine einen Kandidaten für immer
   überspringt. Kein Blender, unlesbares Modell, gescheitertes Skript sind
   echte Fehlschläge und sollen zählen.
4. **Der Admin-Knopf „Bake surface"** am Raum-Modell-Panel (Lageplan-Editor) und
   am Prop-Panel:

| Route | Körper | Antwort |
|---|---|---|
| `POST /world/locations/{lid}/rooms/{rid}/model3d/surface` | — | `{queued: true}` |
| `POST /world/props/{pid}/surface` | `{variant?}` — der STORE-Index EINER Variante; fehlt/leer = jede aktive; alles andere (negativ, nicht ganzzahlig, kein Zahlwort) ist ein Fehler | `{queued: true}`, sonst 400 |

Beide erzwingen (`force`) — der Admin hat gedrückt, also wird auch ein gültiges
Raster neu gebacken —, beide antworten sofort und **kennen keinen
`busy`-Zustand**: das Backen wartet im Hintergrund auf seinen eigenen Slot.
Daneben zeigen die Panels die Statuszeile aus `surface_status`
(„baked 33×33 @ 0.25 m", „missing", „stale (model or fix changed)"), am Prop je
gezeigter Variante — und der Bake-Knopf lädt den Datensatz gleich neu, weil er
den Status ungültig macht. Der Raum-Status liefert sie als
**`meta.surface_status`**, nicht als `meta.surface`: `surface` ist im
Szenen-Rezept das RASTER selbst, und zwei Felder gleichen Namens mit
verschiedenem Inhalt sind der Weg, auf dem ein Consumer ein Status-Dict
abtastet. Am Prop hängt der Block an der GEZEIGTEN Variante (`shownHasMesh`),
nicht am Prop-Flag: Status, Knopf und Route sprechen alle über die Variante,
die offen ist.

Das Tag `walkable` steht im Prop-Admin als **Hinweistext unter dem Tag-Feld**
(„Tag \"walkable\" lets figures stand on this prop; its surface is baked from
the mesh.") — die Tags sind ein freies Komma-Feld ohne Vorschlagsliste, anders
als die Kategorie mit ihrer Datalist.

**Die Admin-Vorschau (`POST /play/scene-preview`) bekommt keine Raster**:
`scene_inputs(..., with_surface=False)`. Sie zeichnet und läuft nie, und ein
Raster kostet je Raum ein paar hundert Kilobyte plus JSON-Parse — bei jedem
Tastendruck im Lageplan-Editor.

### Fehlerfälle

| Fall | Verhalten |
|---|---|
| Blender fehlt, Skript scheitert, Modell unlesbar | `bake_surface` `None`, ein Info-Log, keine Datei — kein Raster ist heutiges Verhalten, kein Fehler |
| Kein Slot frei | dito, aber als `busy` unterscheidbar (`bake_surface_result`): die Engine lässt den Schritt offen, der Admin-Knopf wartet im Hintergrund |
| Modell ohne nach oben weisende Fläche | Datei voller `null` → kein Endlos-Neubacken, keine Wirkung |
| Quelle / Fix / Version geändert, Datei unvollständig | `read_surface` `None` → „stale" → Terrain, bis ein Auslöser neu backt |
| Riesiges Modell | `step` verdoppelt bis `max_cells` = 40 000; das Raster nennt seinen Schritt selbst |
| Client vor dem Server-Neustart (v5) | kein `surface`-Feld → die Sprosse antwortet nie |
| Raster unter Terrain | `standY = max` → Terrain (Entscheid 5) |

### Bewusst NICHT v1

* **Gebäude-Modelle und Karten-Props** (`world_props`) bekommen kein Raster
  (Entscheid 1) — Dioramen und Raum-Props.
* **Mulden** unter dem Gelände wirken nicht; `standY = max` bleibt.
* **Kein Client-Raycast** — die E5b-Löschung bleibt gelöscht.
* **Tür-Props sind nicht begehbar**: begehbar ist, was das Tag trägt.
* **Ein NPC in einem Diorama im Obergeschoss** wird von der Boden-Leiter nicht
  getragen (sie fragt nur Etage 0).
* **Ohne endliches Datum** rechnet der Server nur mit Gelände.

### Die Beweise (§ B5a)

| Was | Wo |
|---|---|
| Die Gründe eines Backens (`ok` / `unreadable` / `no_blender` / `busy` / `failed` / `unstorable`) | `scripts/smoke_model_surface.py` **part 0** (3 Checks) |
| Die Zellenregel Knoten für Knoten an einer rein in Python geschriebenen Mini-GLB (Sockel + Block + hoher Überhang + niedriger Sims): 80 / 20 / **20** / **90** cm und `null` neben dem Modell — 20, weil unter dem hohen Überhang 1,3 m ≥ 1,2 m Luft ist, 90, weil unter dem Sims nur 0,6 m bleiben; dazu beide Boxen, `extent_snapped` unter Fix 0 und Fix x = 90, und die Gültigkeit (Version, Quelle, Fix, unvollständige Datei) | ebenda **part 1** (36 Checks, echtes Blender; ohne Blender SKIP statt Fehler) |
| Die Sampler-Handtabelle: Knotenwert, Bilinear-Mitte, `null`-Nachbar, Punkt außerhalb, Yaw, `measure xyz`, `lift`, höchstes gewinnt | ebenda **part 2** (15 Checks) |
| **Dieselbe Handtabelle in TypeScript** — `surfaceHeightAt`/`highestSurfaceAt` Zahl für Zahl wie der Python-Zwilling | `client3d/scripts/smoke_surface_math.mjs` (15 Checks) |
| Rezept: `code_version` **8** (die Konstante bewegt sich mit JEDER Änderung an dem, was der Composer bei unveränderten Daten antwortet: 6 = diese Oberflächen-Raster, 7 = Marker sprechen Platz-Typen, 8 = der Prop-Marker nennt seinen `anchor`), das Raum-Spec trägt den Block unverändert, ein Raum ohne Raster kein Feld, das ungetaggte Prop weder `walkable` noch Block, das getaggte beides (und `walkable` ohne Bake: die Flagge ohne Block) — und die Signatur bewegt sich, sobald ein Raster erscheint | `scripts/smoke_scene_recipe.py` **[7i]** (9 Checks) |
| Zwei Varianten desselben Props in einem Raum: jede Kopie bekommt das Raster IHRER Store-Variante, und ein Neubacken der „verschluckten" Variante bewegt die Signatur | ebenda **[7h]** (8 Checks) |
| Die Höhensperre: neben der Kiste blanker Boden, auf der 0,3-m-Kiste 0,3 (Schritt erlaubt), am 0,8-m-Block `too_steep` als STUFE, wieder herunter erlaubt; Etage-0-Filter, Anker-Lift, TTL-Cache, `forget_surfaces` und der defekte Sidecar, der auf Boden zurückfällt statt zu 500 | `scripts/smoke_play_pos.py` **[23]** (21 Checks) |
| Sprosse 1 auf der Server-Seite: ein Loch im Raster (`null`-Knoten) fällt auf das `walk_y_world` des Raums in seinem `floor_plan`-Hull, außerhalb jedes Hulls antwortet das Gelände, bei Überlappung gewinnt der kleinste Hull — und das Schritt-Tor misst gegen 0,9 statt gegen 0,0 | ebenda **[23h]** (11 Checks) |
| Improvements: nur der ausgelegte Raum ist Subject, `apply` backt unter dem bei APPLY neu gelesenen Fix, `is_done` liest frisch zurück, der gedrehte Regler macht den Kandidaten wieder zum Kandidaten, `busy` = `CandidateBusy` (kein Versuch verbraucht), ein Defekt = `RuntimeError`, und das Cache-Vergessen je Subject | `scripts/smoke_improvement_types.py` **[14]** Raum-Modelle (12 Checks), **[15]** Prop-Varianten (5 Checks) |
| Dass ein Landen den Bake auslöst — mit Attrappe statt Blender, damit die LOD-Kette ohne ihn läuft | `scripts/smoke_model_lod.py` |
| Verify-Zeile `surface_scale` je Spec mit Raster: die gemessene Skala des platzierten Objekts gegen `max_m / extent_snapped` — die einzige Stelle, an der eine Loader-Abweichung Blender ↔ three sichtbar würde („Prüfe am Verbraucher") | `client3d/src/scene/sceneRecipe.ts`, `?debug3d=1` |
| Verify-Zeile `surface_box` daneben: die EXAKTE Box der Fix-Gruppe (outer → yawG → fitG → fix, in Modell-Einheiten vor Yaw und Skala) gegen `box_max − box_min` und `box_min[1]` der Datei, als größte Abweichung der vier Zahlen. `surface_scale` vergleicht nur die größte Seite — ein Mesh, dessen Box in den anderen Achsen oder in der Unterkante abweicht, kommt dort grün durch, während jede Raster-Lesung um genau diese Differenz danebenliegt | ebenda |

## Nachtrag 2026-08-28 (§ B): Marker sprechen PLATZ-TYPEN (v7)

**Was sich ändert.** Ein Marker sagte bisher „hier spielt Clip `sit`"; jetzt
sagt er „hier ist ein Sitzplatz". Das Vokabular ist die endliche Liste der
**Platz-Typen** des Posen-Katalogs (`pose_catalog.get_groups()` — Start-Satz
`seat` 0,314 / `bed` 0,631 / `floor` 0,051 / `counter` 0 / `stand` 0 als
`root_drop`); welche Pose dort gespielt wird, entscheidet der Charakter, nicht
der Marker (plan-posen-plaetze.md § 3). Jeder Marker und jede Platzierung
trägt eine **stabile ID** (8 Zeichen Base32 `a-z2-7`, vom Sanitizer
vergeben, gespeicherte IDs bleiben), damit ein gelöschter Nachbar keinen
Platz umnummeriert und ein Charakter einen Platz beim Namen halten kann.
`SCENE_RECIPE_VERSION` ist 7 — die Signatur kippt, kein Client behält Marker
mit `animation`.

**Gespeichert** (Sanitizer `world_ops._sanitize_markers` /
`props.sanitize_markers`; ein Marker ohne `group` fällt weg):

```
Raum-Marker   { id, group, at: [x, y], capacity?, spacing_m?, rotation?, offset_y?, tilt?, roll? }
Prop-Marker   { id, group, at: [u, v, w], capacity?, spacing_m?, facing? }
Platzierung   { prop_id, id, label?, at, yaw?, … }           # id neu, label optional
```

`capacity` 1..8 (nur > 1 wird geschrieben, dann mit `spacing_m` 0,2..3,0,
Vorgabe 0,6 m).

**Szenen-Payload** `markers[]` (§ B, Block „Figuren & Marker"): `{room_id,
id, group, label, capacity, at_world, slots, y_world, root_offset, facing?,
tilt?, roll?, anchor?, source}`. Platz-ID = Raum-Marker-ID bzw.
`"<placement.id>/<marker.id>"`; `label` = Platzierungs-Label, sonst Prop-Name,
sonst Gruppen-Label. `root_offset = groups[group].root_drop × 1,70` auf
Millimeter gerundet — die Tabelle `FIGURE_ROOT_DROP` im Szenen-Rezept ist
gelöscht (ebenso ihre Schattenkopie in `@anima/scene-render`, 2026-08-28:
`figureRootY(surfaceY, rootOffset)` kennt nur noch den Payload-Wert), der
Katalog ist die EINE Quelle. Ein Marker, dessen Gruppe der
Katalog nicht kennt, ist kein Platz und fehlt im Payload.

**`anchor` — EIN Prop, EIN Boden** (Befund 2026-08-28, der Sitzende ~40 cm zu
tief auf der „Stone bench" über der Klippe). Ein Prop-Marker trägt zusätzlich
den Anker SEINER Platzierung, exakt die Zahl, die auch `models[].anchor`
führt; ein Raum-Marker hat keine Platzierung und kein Feld. Zwei Aufgaben, ein
Wert: (1) die Gelände-Hebung von § A16.9 wird DORT abgetastet — das Mesh steht
auf dem Boden unter seinem Anker, ein an seinem eigenen Punkt gehobener Sitz
weicht am Hang um genau das Relief zwischen beiden Punkten ab; (2) es ist die
EINZIGE Verbindung Marker → Mesh, denn `models[].id` ist die Prop-ID und
gehört jeder Kopie der Bank. `SCENE_RECIPE_VERSION` steht deshalb auf **8** —
der Payload ändert sich bei unveränderten Daten, also muss die Signatur sich
bewegen, sonst behielte jeder Client seine alte Szene bis zum nächsten
Speichern des Ortes. Ein Prop-Marker OHNE `anchor` (eine noch zwischen-
gespeicherte Szene von vor der Änderung) bekommt im 3D-Client den alten Ring
zurück, statt gar kein Klickziel zu haben. Handrechnung:
`client3d/scripts/smoke_place_lift.mjs` [1] (Anker 1,0 / Marker 1,4 / Datum
0,25 → Hebung 0,75 statt 1,15), Payload-Seite
`scripts/smoke_scene_recipe.py` [9a]/[7i], Ziel-Aufteilung
`client3d/scripts/smoke_places_client.mjs` [7]/[8].

**Slots — Geometrie nur im Rezept** (`scene_recipe.marker_slots`, rein):
die `capacity` Plätze liegen mittig um den Marker auf der Achse QUER zur
Blickrichtung (eine Bank läuft seitwärts). Blickrichtung 0 = Süd (+z),
90 = Ost (+x); die Querachse ist die um +90° gedrehte Blickrichtung
`(cos f, −sin f)`; Slot i sitzt bei `(i − (n−1)/2) × spacing_m` darauf.
Kapazität 1 ⇒ `slots == [at_world]`. Handrechnung (Smoke
`scripts/smoke_scene_recipe.py` Block [M]): Marker Welt (−2, −3), Blick Ost,
Kapazität 3, Abstand 0,6 → Querachse (0, −1) → Slots
`[[-2, -2.4], [-2, -3], [-2, -3.6]]` (Slot 0 rechts vom Sitzenden). Kein
Renderer rechnet einen Slot nach (§ B5a).

**Einmal-Migration beim Boot** (`app/core/places_migration.py`,
`world_kv`-Flag `migration.places_v1`, direkt nach der Marker-Oberflächen-
Reparatur und VOR der Prop-Feld-Migration): `animation` → `group` nach der
Regel der alten Absenk-Tabelle (`sit*` → seat, `sleep*` → bed, `lie*`/`lay*`
und `sit-ground*` → floor, alles andere → stand), IDs für jeden Marker und
jede Platzierung; betrifft `layout.markers[]`, `layout.props[]` und die
Prop-Sidecars (Datensatz-`markers` UND jede Variante). Kein Fallback-Leser
für `animation` — nirgends.

**Raum-Rezept** (§ B1): `placements[]` zusätzlich `id`, `label`, `prop_name`;
`prop_markers[]` = `{placement, id, group, capacity, spacing_m, offset_m,
height_m, facing}`. Das LLM-Einrichten (`furnish_new`) schlägt je Möbel einen
Marker mit `group` aus dieser Liste vor, keinen Clip-Kind mehr.
