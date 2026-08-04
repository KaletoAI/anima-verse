# Schnittstellen 3D — Gesamtvertrag v5 (2026-07-28)

> **v5 — EIN Rahmen, EIN Maßstabsfaktor, EIN Anker (2026-07-28).**
> Drei Änderungen, die alles Folgende überschreiben, wo es widerspricht:
>
> 1. **Das Bezugsquadrat ist `map3d.extent_m`** (Welt-Meter, Default 10 =
>    genau eine Kachel), nicht mehr feste 8 m. Es ist zugleich die Box, die
>    das Location-Modell füllt: `max_m = extent_m × map3d.size` mit
>    `size ∈ ]0, 1]`, Default 1. Die 0,92-Kachelmarge entfällt ersatzlos.
>    Damit gilt **Grundriss-Rand = Modell-Rand**; vorher standen Kachel (10),
>    Modell (10 × 0,92 × size) und Grundriss (8) unverbunden nebeneinander und
>    die äußeren 0,6 m eines size-1-Modells waren von keiner Fraktion
>    erreichbar. `k = extent_m / plan_width_m`; `extent_m` reist im Payload
>    mit (`scene.extent_m`) — Konsumenten dürfen KEINE Konstante annehmen.
> 2. **Ein Modell wird mit EINEM Faktor auf allen drei Achsen skaliert.**
>    `scale_mode`/`box`/`scale_axes`/`fit_box` sind weg; jede Spec trägt
>    `max_m` + `measure` (`yawed_xz` | `xz` | `xyz`), `place()` rechnet
>    `s = max_m / gemessene Ausdehnung`. Nichts wird mehr in einer Dimension
>    gestaucht — mit `height_m`/`floors` (Sidecar) und `level_height` (map3d)
>    verschwinden auch die Regler, die das taten. Etagenhöhe ist
>    `map3d.storey_height_m` in REALEN Metern (× k). Der Y-Morph des Clients
>    (Kachelsicht uniform ↔ Detailsicht `height_m × k`) ist gelöscht: er ließ
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
>    `walk_y`-Regler** (REALE Meter über der Unterkante, × k; fehlt/0 = die
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
> `level_height` auftaucht, gilt die Liste oben.
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
>    einstellte. Geprüft in `scripts/smoke_place_rotation.mjs` — und zwar am
>    SKALIERUNGSFAKTOR, nicht an der achsparallelen Hülle: die Hülle eines
>    gekippten 4-m-Würfels ist bis zu 4·√3 groß, und das ist richtig.
> 5. **Eine `ground`-Location bringt ihren Boden mit.** Kein Renderer legt
>    dort seine eigene Kachel-/Bühnenplatte darunter. Der 3D-Client zeichnete
>    eine undurchsichtige 10 × 10-Platte bei y 0,04 in ein Modell hinein, das
>    von −0,80 bis +2,69 reicht — Seebecken und Strand lagen dahinter.
> 6. **Marker tragen zwei Neigungsachsen.** `markers[].tilt` (Kopf hoch/tief)
>    und `markers[].roll` (seitlich kippen), Grad ±90, Default 0, angewandt
>    NACH dem Facing im Figuren-System ('YXZ'). Vorher konnte eine Figur nur
>    senkrecht stehen — schräg auf dem Sand liegen war nicht ausdrückbar.
> 8. **Ein Raum hat einen eigenen Höhen-Offset.** `layout.floor_offset_y`
>    (REALE Meter, ±, Default 0, × k) hebt den ganzen Raum gegenüber seiner
>    Etage: Platte, Wände, Props, Marker, Ausgang und das Diorama. Innerhalb
>    eines Gebäudes bleibt er 0 — er ist für Räume, die ein Loch in ein
>    Location-Modell schneiden: dort liegt das Gelände nicht auf Etagenhöhe,
>    und ohne den Offset schwebt der Raum über seinem eigenen Loch. NICHT
>    mitbewegt werden Etagenplatte, Konturwände und Fahrstuhl — die gehören
>    dem Gebäude. `model_offset_y` bleibt daneben, was es ist: die Lage des
>    MODELLS relativ zum Raumboden.
> 9. **Eine Overlay-Zone mit erklärter Boden-Art bekommt ihre Fläche**
>    (2026-07-29). Outdoor-Räume außerhalb des Grundrisses liegen auf dem
>    Modell und bekommen normalerweise keine Platte — eine Fläche auf
>    ETAGENHÖHE schnitte durch das Gelände. Setzt der Raum aber
>    `surfaces.floor`, wird die Fläche auf der Höhe der ZONE ausgegeben
>    (`overlay.y` + 0,01 gegen Z-Fighting), `thickness` 0, mit der Art als
>    `texture_kind`. Damit wird ein gezeichneter Bereich zum See: Raum über
>    das Wasser legen, Boden-Art `water`, `floor_offset_y` auf die
>    Wasserlinie — den Rest macht die Materialklasse. Ohne erklärte Art
>    ändert sich nichts, das Modell zeigt weiter seine eingebackene Textur.
> 7a. **Der Diorama-Bodenabstand ist 0,02 über dem Boden, auf dem der Raum
>    steht** — der Raumplatte drinnen (0,10 + 0,02 = die vertraute 0,12),
>    dem blanken Etagenboden draußen. Ein Outdoor-Raum hat keine Platte
>    (§ A5); die 0,12 dort zu zitieren hob das Diorama 10 cm über den Boden,
>    während die PROPS desselben Raums schon richtig darauf standen.
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
>     `size` fix 1, `offset_y` gilt nicht — Nr. 7). Die Rezept-Innenwelt
>     komponiert wie ein Gebäude-Interieur: keine `cutouts`, keine
>     Overlay-Zonen; Outdoor-Räume behalten ihre Textur-Platten (§ A5).
>     Der Kachelboden des Renderers folgt dort dem Fade (fern unsichtbar
>     wegen Nr. 5, nah als Backstop unter der Detailszene).
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
>     0,6 m), Exit/Marker ±0,5 m) und mit Mittelpunktsabstand ≥
>     `scatter_spacing_m` zu den Kopien DERSELBEN Platzierung.
>     `scatter_spacing_m` ist die GANZE Dichteregel: 0 = Kopien dürfen
>     überlappen (Baumkronen tun das) — die frühere Footprint-Untergrenze
>     hielt jeden Baum eine Kronenbreite auf Abstand (User-Befund
>     2026-08-02). Versuchsbudget `count × 30`, Unterbelegung erlaubt.
>     Identischer Seed ⇒ identische Szene in Admin-Vorschau und Client;
>     § B5a prüft exakte Positionen gegen die von Hand gerechnete Folge.
> 13. **`scene.boundary_openings`** — Durchgänge an der LOCATION-Grenze
>     (Straße quert die Zelle): `[{edge: N|E|S|W, at_world: [x, z],
>     width_m, type: "passage", room_id?, inward: [±1|0, ±1|0]}]`, Punkt
>     über den Rahmen des Bezugsquadrats (`at` wie Raum-Openings:
>     links→rechts auf N/S, oben→unten auf E/W), `inward` = einwärtige
>     Normale in Weltachsen. **Konsum (Etappe 3, 2026-08-03,
>     plan-3d-lod-und-betreten.md):** client3d liest die Openings für die
>     Eintritts-Nähe des „Betreten"-Angebots — Weltposition = Kachelzentrum
>     + `at_world`, mehr rechnet kein Renderer (der Server hat auch die
>     `tile_rotation` nach Nr. 15 bereits eingerechnet). Und der SERVER
>     erlaubt den Avatar-Schritt nur über eine Kante mit autorisiertem
>     Opening (`app/core/boundary_entry.py`, verdrahtet in
>     `world_ops.move_avatar_step`) — eine Kante ohne Opening ist kein
>     Übergang mehr, und eine Location ohne jede Opening ist überhaupt nicht
>     betretbar (403 `no_entrance`, Entscheidung 2026-08-04: sonst wäre ein
>     Ort ohne Autoren-Öffnung heimlich über jede Kante begehbar). Der
>     Eintritt routet in den verknüpften Raum (`room`); eine Opening OHNE
>     `room` ist trotzdem gültig — sie ist der Eingang zu einer Location,
>     deren Boden kein Raum ist, und der Avatar steht danach in keinem Raum.
>     Das Verlassen ist aus dem verknüpften Raum heraus oder aus keinem Raum
>     ohne Entry-Room erlaubt (der Rundweg derselben Opening); für jede
>     andere Kante bleibt das `entry_room`-Gate beim Verlassen unverändert
>     die Gameplay-Instanz. Der Journey-Durchlauf ist weiterhin eine
>     spätere Etappe.
> 14. **`scene.terrain` — deterministisches Geländerelief.** Ohne Diorama ist
>     eine Detailszene bretteben; `map3d.relief = {amplitude_m, seed, wave_m?}`
>     (nur zusammen mit `area_model` + `area_detail`, `amplitude_m` 0,05..5
>     REALE Meter, `seed` Pflicht) legt ein Höhenfeld über das Bezugsquadrat.
>     **Gitter:** n × n Zellen → **(n+1) × (n+1) Stützpunkte**, `grid[j][i]`,
>     Stützpunkt (i, j) auf Plan-Fraktion (i/n, j/n) — i West→Ost, j
>     Nord→Süd; `step` = `extent_m / n` Welt-Meter. **n ist keine Konstante:**
>     `wave_m` ist die Breite EINER Bodenwelle in REALEN Metern (1..200),
>     daraus `n = int(plan_width_m / wave_m + 0,5)` (halb-auf, wie
>     `Math.round`), geklemmt auf [2, 22] — die Obergrenze ist das, was
>     `drapeGeometry` mit `MAX_SPLITS = 5` noch auflöst (e·√2 / 2⁵ = e/22,63);
>     ohne `wave_m` gilt der Default n = 16. Clients lesen n aus dem
>     gelieferten Gitter (`grid.length − 1`) bzw. rechnen mit `step`, nie mit
>     einer eigenen 16. **Rand = 0** (i oder j ∈ {0, n}), damit Nachbarkacheln
>     nahtlos aneinanderstoßen. **Flach = 0**
>     für jeden Stützpunkt, der in der TESSELLIERTEN Hülle eines flachen Raums
>     liegt (Point-in-Poly wie beim Scatter, Nr. 12): flach ist jeder
>     Innenraum (nicht `always_visible` — Wände brauchen ebenen Boden) plus
>     jeder Außenraum mit `layout.relief_flat` (Straße, Platz, Lichtung).
>     Nichts wird geglättet; die Nachbarzelle interpoliert den Übergang.
>     Sonst genau EIN xorshift32-Zug (Nr. 12, Seed 0 → 1) auf dem
>     Raum-Hash der Position:
>     `h(i,j) = (XorShift32((seed + i·73856093 + j·19349663) & 0xFFFFFFFF)
>     .next01() · 2 − 1) · amplitude_m · k` — Welt-Meter, auf 4 Stellen
>     gerundet. Die beiden Konstanten sind Teil des Vertrags.
>     **Zwischen den Stützpunkten bilinear:** Zelle `x = min(int(u·16), 15)`,
>     `fx = u·16 − x` (analog v/j), u/v auf [0, 1] geklemmt — dieselbe Formel
>     in `scatter_curves.terrain_height` und in `@anima/scene-render`
>     (`sampleTerrain`), § B5a-prüfbar von Hand.
>     **Payload:** `scene.terrain = {step, grid, amplitude_m}`, nur wenn
>     `relief` gesetzt ist; `amplitude_m` ist hier bereits × k.
>     **Arbeitsteilung:** *der Server hebt alles, was in nicht-flachen Räumen
>     steht* — Prop-`bottom_y` (manuell wie gestreut), Dioramen-`bottom_y`,
>     Marker-`y_world`, jeweils um `terrain_height` am EIGENEN Plan-Anker der
>     Platzierung (Prop-Marker am Anker ihrer Platzierung, damit Möbel und
>     Sitzpunkt gemeinsam steigen). *Die Renderer drapieren nur Boden +
>     `relief`-Platten und sampeln Figuren-Höhen* — Raumplatten
>     nicht-flacher Außenräume tragen dafür `"relief": true` (unterteilen +
>     Vertices über `sampleTerrain` heben); Etagenplatten, Wände und alle
>     übrigen Platten bleiben unverändert. Objekthöhen werden NIE zusätzlich
>     im Renderer gesampelt, sonst zählt die Hebung doppelt.
>     **Flache Räume ändern sich numerisch nicht:** in einem Innenraum oder
>     einem Raum mit `relief_flat` ist jede Zahl bitgleich zu einer Szene ohne
>     Relief. `relief` liegt im gehashten `map3d`, `relief_flat` im
>     Raum-Rezept — Regler, Würfel und Checkbox bewegen also die Signatur.
> 15. **`map3d.tile_rotation` — EINE Vorlage, mehrere Ausrichtungen.** Eine
>     Straße, die ost–west durch die Zelle läuft, wird EINMAL als Vorlage
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
>       `clip_outline` / `cutouts`, `markers[].at_world`, `exits[].at_world`,
>       `rooms[].overlay.centre|rect` → Welt-Regel; `rooms[].outline` →
>       Fraktions-Regel. `rooms[].exit` wird **nur bei `exit_derived`**
>       gedreht (absolute Plan-Fraktion); ein EXPLIZITER Exit ist eine
>       Fraktion des RAUM-RECHTECKS und gehört dem 2D-Editor, der die
>       unrotierte Vorlage zeigt — er bleibt stehen.
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
Verweis-Stubs liegen. `backend-wishlist.md` bleibt unverändert der Rückkanal
des Clients.

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

## 0. Warum v4 — Analysebefund 2026-07-24

Die Geometrie-Regeln dieses Vertrags sind heute **dreifach implementiert**:

1. Backend: `app/core/room_recipe.py` (Spiegelung, Exit-Ableitung,
   Marker-Komposition), `app/core/location_model3d.py` (Anker-Meta).
2. Game-Admin-Vorschau: `frontend/src/tabs/world/FloorPlanPreview.tsx`
   (1841 Zeilen raw three.js) + `planGeometry.ts` — reimplementiert
   Öffnungs-Normalisierung, Spiegelung und Exit-Ableitung als gepflegtes
   „Spiegelbild" des Backend-Codes und **ruft `/play/rooms/{id}/recipe`
   nirgends auf**.
3. 3D-Client: `src/scene/tiles.ts`, `roomShell.ts`, `propPlace.ts`,
   `figures.ts` — implementiert dieselben Ketten ein drittes Mal (nutzt
   immerhin das Rezept).

Jeder dokumentierte Drift-Bug der letzten Wochen ist genau daraus
entstanden: ×k-Vergesser (Commit 237ccd7), uniforme statt achsengetrennter
Skalierung (Mondscheinsee), Pivot- statt BBox-Verankerung (Hörsaal),
Panel-Viewer-Einheitenfehler (de0b151), 0,12 m vs. 0,12×k, 1,70 m vs.
1,75 m Figurenhöhe. Über ein Dutzend Geometrie-Konstanten leben als
Kopien in beiden Frontends.

**Leitprinzip v4:** Jede Geometrie-Entscheidung existiert genau EINMAL —
im Backend. Beide Renderer konsumieren dieselben server-gerechneten Daten;
die Admin-Vorschau ist nicht länger „Referenz per Reimplementation",
sondern erster Konsument derselben Vertragsfläche (§ B5).

---

# Teil A — Ist-Vertrag (konsolidiert)

## A1. Vokabular, Koordinaten, Maßstab

- **Kachel** = 10 × 10 Welt-Meter, eine Location. **Referenzquadrat** =
  festes **8 × 8 m**, kachelzentriert — die Bezugsfläche ALLER Fraktionen
  (`layout.x/y/w/d`, `map3d.outline`, `map3d.elevator`, Rezept-`outline`,
  `placements.at`, `exit`, Marker-`at`). +x = Ost; +Fraktion-y → +z = Süd.
- **Anker-Kette (v3):** `k = 8 / plan_width_m(effektiv)` — Welt-Meter pro
  Real-Meter der Location. Effektiv = explizites `map3d.plan_width_m`,
  sonst Auto-Ableitung `height_m × (größte XZ-Seite / Y des Meshes, nach
  Rotations-Fix)`, sonst Legacy (kein k; `level_height`-Formeln).
- **Etagenhöhe** `storey = height_m / floors × k` (wenn Gebäude-Meta beides
  deklariert), sonst `map3d.level_height`, sonst 3. Etagenboden von
  Level n = `n × storey`.
- **Yaw-Kette:** `yaw = map3d.rotation` (explizite 0 zählt) →
  `map_rotation_2d` → 0. Yaw dreht im Uhrzeigersinn in der Draufsicht;
  three.js `rotation.y = −rad(yaw)`.
- **Rotations-Fixe** (Modell-Meta, Prop-Bibliothek): Euler **'YXZ'**
  (2026-07-28), in Grad, VOR jeder Messung anwenden. Yaw (y) liegt außen,
  Tilt (x) und Roll (z) wirken im schon gedrehten Rahmen — „nach vorn
  kippen" heißt damit unabhängig von der Blickrichtung dasselbe, und die
  Marker-Neigung benutzt dieselbe Reihenfolge. Bei nur EINER belegten Achse
  ist das identisch zum früheren 'XYZ'.
- **Kompass für Blickrichtungen** (`facing`, Marker-`rotation`): 0 = Süd,
  90 = Ost, 180 = Nord, 270 = West; Figur `rotation.y = +rad(facing)`.
- Alle Felder mit Suffix `_m` sind REALE Meter → im Anchored-Mode ×k.
  `offset_x/y/z` sind dagegen immer WELT-Meter (kein ×k).

## A2. Die Platzierungsketten (heute drei — v4 vereinheitlicht sie, § B2)

**Gebäudemodell** (`/play/locations/{id}/model` + Meta):
1. Meta-Rotations-Fix (innere Gruppe).
2. Karten-Yaw als eigene ELTERN-Rotation (nie in einem Euler kombinieren).
3. BBox des rotierten Ganzen messen → `k_xz = (10 × 0,92 × map3d.size) /
   max(B_x, B_z)`; `k_y = height_m × k / B_y` (ohne height_m: `k_y = k_xz`).
   `map3d.size` ∈ ]0, 2] — über 1 ragt bewusst über die Kachel, nicht
   clampen, nicht clippen.
4. `scale.set(k_xz, k_y, k_xz)` auf WELT-Achsen (achsengetrennt, v2.1).
5. BBox neu messen → Unterkante = 0,06 m + `offset_y`; XZ-Zentrum =
   Kachelmitte + `offset_x`/`offset_z` (Welt-Achsen, Yaw dreht sie NICHT
   mit). Ausnahme Terrain-/Template-Kacheln: X und Z getrennt füllen,
   ohne 0,92-Rand, damit size = 1 nahtlos kachelt.
6. Meta-`walk_y` (optional, Meter über der Modell-Unterkante, Regler in
   der Modell-Galerie): begehbare Fläche des LOCATION-Modells. Das
   Rezept liefert daraus `walk_y_world` am Building-Spec — die
   Standhöhe der Overlay-Zonen einer Flächen-Location; ohne das Feld
   stehen Figuren auf der Modell-Unterkante (`bottom_y`).

**Raum-Diorama** (`/play/rooms/{id}/model` + Meta):
1. Normalisieren: rohe BBox messen (NIE dem Pivot trauen), größte XZ-Seite
   = 1, XZ zentriert, Unterkante y = 0.
2. Fit: uniform `min(w/fp_x, d/fp_z) × 0,96`, an der UNROTIERTEN Box.
   ⚠ Diese Rechteck-Einpassung ist ab v4 nur noch der FALLBACK — der
   Größenabgleich mit Props/Figuren läuft über die Real-Size-Regel in
   § B2a (Diorama skaliert wie ein Prop über `width_m × k`).
3. Meta-Fix (innere Gruppe) → Layout-Yaw (Eltern-Gruppe).
4. Rotierte Box NEU messen und NEU erden: Unterkante =
   `Etagenboden + 0,12 + layout.model_offset_y`; XZ-Anker =
   `layout.model_at` (Fraktionen des Raum-Rechtecks; fehlt = zentriert).
   **Raum-Sidecar-`offset_y` ist stillgelegt** — für Räume nicht mehr aus
   dem Meta lesen (Gebäude unverändert).

**Props — REAL-SIZE-Regel** (`/assets/props`, Rezept-`placements`):
1. GLB laden, Orientierungs-Fix aus der Bibliothek anwenden.
2. BBox des GEFIXTEN Meshes messen → maxExtent = max(x, y, z).
3. `s = max(width_m, depth_m, height_m) × k / maxExtent` (UNIFORM — eine
   Platzierung skaliert nie).
4. `rotation.y = −rad(yaw)`.
5. Ergebnis-BBox messen → Unterkante auf **Raumplatten-Oberkante + 0,01**
   (outdoor: Etagenboden + 0,01) + `offset_y × k`, XZ-Zentrum auf
   `placements.at`. (Klarstellung v4 — vorher nannten Vorschau/Client/
   Rezept drei verschiedene Werte: 0,05 / 0,11 / 0. Möbel stehen auf dem
   Raumboden; die `prop_markers`-Höhen reiten denselben Hub mit.)
- `missing: true` → Platzhalter rendern, Platzierung nie verwerfen;
  `has_model: false` → Platzhalter in `dims`-Größe.
- Zahlenbeispiel zum Diffen: rohe Box [1,0/0,5/2,0], Fix y = 90°, Dims
  W 1,2/D 0,6/H 0,3 → gefixte Ausdehnung [2,0/0,5/1,0], s = 0,6k; Marker
  `at [0,5/1,0/0,25]`, facing 90, yaw 90 → `offset_m [0, −0,3]`,
  `height_m 0,3`, `facing 0`.

**Verankerung IMMER:** BBox-Unterkante des fertig transformierten Modells,
gemessen NACH Fix → Yaw → Skalierung; Offsets als letzter Schritt.

## A3. Standhöhen & Figuren-Maßstab — Klärung der 0,12-Frage

- **Verbindlich: 0,12 ist eine KONSTANTE in Welt-Metern, ohne ×k.** Die
  Admin-Vorschau rechnet `Etagenboden + 0,12 + offset` (FloorPlanPreview,
  Grounding-Zeile) — die §2e-Formulierung „0,12 × k" der Rezept-Note war
  falsch und ist hiermit zurückgezogen. Euer Client rechnet bereits
  richtig.
- Figuren stehen indoor auf der ABGETASTETEN Bodenfläche (Diorama-Boden
  bzw. Rezept-Platte); die Konstante verankert nur Modelle/Platten.
  Outdoor-Räume haben keine Platte — Figuren stehen auf Level-/
  Terrain-Höhe.
- **Figuren-Basishöhe: 1,70 m × k** (anchored; Legacy `1,7 × storey/3`).
  Der Client-Default 1,75 m ist eine bekannte Divergenz → auf 1,70
  angleichen (§ B6). `height_cm` der Charaktere skaliert relativ dazu.

## A4. Raum-Rezept `GET /play/rooms/{room_id}/recipe`

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
  exit?, exit_derived?, markers?,
  placements: [{ prop_id, at: [x, y], yaw, offset_y,
                 dims: {width_m, depth_m, height_m}, has_model, missing? }],
  prop_markers: [{ placement, animation, offset_m: [dx, dz],
                   height_m, facing? }],
  always_visible?,                    # Outdoor-Flag (§ A5)
  clip_model?,                        # Diorama-Clip-Opt-in (§ B1)
  no_walls?,                          # Raum emittiert KEINE walls-Einträge
                                      # (offene Zone, Pavillon, Bereich in
                                      # einem Area-Modell): keine Segmente,
                                      # keine Fenster-Brüstung/-Sturz, kein
                                      # Glas. Öffnungen bleiben Editor-Daten,
                                      # Platte/Exit/Marker unberührt; die
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
  `model_at`, Maßstab `width_m × k` § B2a, Standhöhe `walk_y`), egal ob
  der Raum `placements` trägt. Ein Raum ohne Diorama hat schlicht kein
  Modell. Die alte Weiche „placements verdrängen das Diorama" ist
  aufgehoben; `/scene` emittiert die Diorama-Spec entsprechend immer.
- **Hülle:** Bodenplatte = `outline`-Fläche; Wände = Kanten × Etagenhöhe,
  in Segmente um die Öffnungen geteilt (kein CSG). Öffnungen referenzieren
  die Kante per INDEX (Kante i = Punkt i → i+1); `at` = MITTE der Öffnung,
  0..1 entlang der gerichteten Kante; Spanne `at ± width_m × k / 2`, an
  den Kantenenden geklemmt. Fenster = Brüstung (0..`sill_m×k`) + Glas
  (`sill_m×k`..`(sill_m+height_m)×k`) + Sturz; Tür/Passage = Lücke.
  ⚠ `sill_m`/`height_m` real → ×k.
- **Gespiegelte Öffnungen:** eine physische Öffnung, im Besitzer-Raum
  definiert, erscheint in BEIDEN Wänden — der Nachbar bekommt sie mit
  eigenem Kanten-Index und gespiegeltem `at` fertig geliefert; exakt wie
  eigene behandeln, nichts umrechnen. `mirrored: true` ist rein
  informativ. Gilt für Türen, Passagen und Fenster.
- **Abgeleiteter Exit:** fehlt `layout.exit`, liefert das Rezept bei
  vorhandenen Türen/Passagen trotzdem `exit` (+ `exit_derived: true`) —
  Öffnung mit `to == "outside"` gewinnt, sonst erste Tür/Passage (stabile
  Ordnung Kanten-Index, dann `at`); Punkt = Öffnungsmitte 0,3 m nach innen.
- **Marker:** `prop_markers` sind FERTIG komponiert (Fix → Real-Size →
  Yaw durchgerechnet) — eine Zeile beim Konsumenten:
  `marker = platzierungspunkt + [dx,dz] × k`, Höhe = Etagenboden +
  `height_m × k`, `facing` = Welt-Kompass. Objektlokale Fraktionen dürfen
  −0,5..1,5 (Y: −1..1,5) — nur die Wertebereiche werden größer.
  **Facing-Default (2026-07-25):** `prop_markers` tragen IMMER ein
  `facing` — fehlt es am Objekt-Marker, gilt Prop-Front = Süd im
  Objektraum und der Sitzende erbt die Platzierungs-Drehung
  (`facing = (0 − yaw) mod 360`); zeigt die Front eines Props nicht nach
  Süden, einmal am Objekt-Marker korrigieren. (Befund Café-Terrasse:
  gedrehte Stühle, alle Sitzenden schauten in dieselbe Richtung.)
  Raum-Marker (`markers`) = unverändert `layout.markers` (raumlokal,
  `at`/`animation`/`rotation`/`offset_y` additiv zur abgetasteten
  Auflagehöhe; Marker schlagen die Client-Heuristik).
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
  0,07; Türen nur EG an Raum-Exits mit Kantenabstand < 0,45 (Lücke ±0,4;
  Reststücke < 0,06 entfallen), sonst mittige Tür im südlichsten
  Wandstück; Obergeschosse halbtransparent. **Klarstellung 2026-07-26:**
  opak (`opacity_role: "ground"`) ist die UNTERSTE genutzte Etage, alles
  darüber ist `"upper"` — bei einem Keller (`level -1`) ghostet also auch
  die Terrain-Etage 0, sonst läge der Keller unsichtbar unter opakem
  Boden. Türen bleiben eine Level-0-Sache (realer Gebäudeeingang), auch
  wenn ein Keller existiert. Enum unverändert, Clients unverändert.
- **Raum-Ebene (Klarstellung v4):** Raum-Bodenplatte Oberkante
  `level × storey + 0,10` (liegt damit AUF der Etagen-Platte; Dicke
  0,02), Raumhüllen-Wände Basis 0,10; Props auf Platte + 0,01 (§ A2);
  Diorama-Unterkante bleibt bei + 0,12 (§ A3). Fahrstuhl im Legacy-Mode
  (ohne Anker): reale Meter × `storey / 3` statt × k — wie der
  Figuren-Maßstab.
- `map3d.level_floors?: {"<level>": "<kind>"}`: Etagenplatte mit der
  aktiven Textur des Kinds kacheln (`size_m × k`); Raum-Böden liegen
  darüber. Ohne Eintrag: globales `floor`-Kind, sonst Default-Material.
- `map3d.elevator`: `[x, y]`-Fraktion, gilt für alle Etagen. Rezept:
  Schacht 1,8 m², Ecksäulen 0,14, Glas 3 Seiten (offene Seite Richtung
  Gebäudemitte), Pads 1,6 m², Kabine 1,4 m² × 0,6 storey — alles reale
  Meter × k. Figuren-Routing: Raum-Exit → Fahrstuhl → vertikal → weiter.
  Treppen gibt es nicht.
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
  den Clip. Die Keyword-Heuristik `activityToClipKind` im Client ist ein
  Workaround und fällt mit v4 (§ B6).

## A9. Terrain & Oberflächen (AV3D-13 v2)

- Location sagt per `terrain` WELCHE Art; `/assets/surface-textures`
  sagt WIE: Flächen (`url` kachelbar, `size_m`, Kachelung im
  Welt-Maßstab) oder Zusammenstellungen (`blend` mit `toward`/`zones`/
  `noise`, Zonen von der toward-Kante, `kind:"neighbor"` = häufigste
  Nicht-toward-Nachbar-Art). 404/leer/unbekannt → eingebaute prozedurale
  Fallbacks. 2D-Map-Icons werden NICHT als Boden verwendet
  (`map-icon-2d` ist für den 3D-Pfad tot — README-Verweis streichen).
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
  Tagwert. Die Textur der Art bleibt die Basisfarbe.
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

## A10. Kamera & Steuerung (Referenz, unverändert)

FOV 45°, near 0,5, far 800; Orbit um Bodenpunkt, dist 2,5..150,
zoomgekoppelter Pitch `lerp(18°, 62°, sqrt(norm(dist)))` + Offset ±35°
(gesamt 8..85°); exponentielle Glättung ~8/s. Links ziehen = bodenver-
ankertes Pan, Mitte/Shift = Drehen/Neigen (0,005 rad bzw. 0,25°/px),
Rad = Zoom auf Cursor (`dist *= exp(ΔY·0,0012)`), Klick = Auswahl bei
< 0,15 Einheiten Bewegung. Q/E ±45°, +/− Zoom-Stufen, WASD Pan.
Raum-Vorschau-Start: dist 22, Pitch-Offset +28°, Target Kachelmitte.

## A11. Reise-Payload (server-autoritative Bewegung) — neu 2026-07-27

Ein Charakter wechselt die Location nicht mehr schlagartig, sondern reist
über die Kachel-Kette. `GET /play/worldmap` liefert dafür pro Charakter das
Feld **`travel`** — `null`, solange keine Reise läuft:

| Feld | Typ | Bedeutung |
|---|---|---|
| `path` | `[locationId, …]` | Zellenkette der Reise, **inkl. Start- und Zielkachel** |
| `target_id` | `str` | Zielkachel (= `path[-1]`, identisch mit `movement_target_id`) |
| `seg` | `int` | Index des zuletzt passierten Knotens, 0-basiert, max `len(path)−2` |
| `frac` | `float` | Fortschritt 0..1 von `path[seg]` nach `path[seg+1]` |
| `progress_cells` | `float` | `seg + frac` — Gesamtfortschritt in Zellen |
| `eta_game` | ISO-Zeit | nominelle Ankunft auf der **Spieluhr**; trägt den Offset der **Weltzeitzone** (`server.timezone`) — ein HH:MM-Slice ergibt direkt Spiel-Wanduhrzeit |
| `cell_seconds_real` | `float \| null` | wie viele ECHTE Sekunden eine Zelle dauert (`seconds_per_cell / Zeitfaktor`); `null` bei eingefrorener Welt bzw. Faktor 0 |

**Semantik**

- **Die Position ist eine reine Funktion der Spieluhr.** Server und alle
  Clients rechnen aus demselben Payload dieselbe Position:
  `pos = lerp(Kachelmitte(path[seg]), Kachelmitte(path[seg+1]), frac)`
  (Kachelmitten aus `grid_x`/`grid_y`, Kachel = 10 m, § A1). Es gibt kein
  client-eigenes Pathfinding und keine eigene Reisezeit.
- **`location_id` = nächstgelegene Zelle**, Rundung „halb abwärts": genau
  zwischen zwei Kacheln zählt die bereits verlassene. Der Spielzustand
  (Regeln, Wahrnehmung, Raum) springt also bei `frac 0,5`, während `frac`
  stetig läuft — beide Felder widersprechen sich nicht, sie beschreiben
  verschiedene Dinge (Spielzustand vs. Darstellung). **`location_id` wird
  nur im Ticker-Takt (5 s) nachgeführt** — bei hohem Zeitfaktor kann es dem
  `frac` um mehrere Zellen nachlaufen. Die Render-Position kommt IMMER aus
  `path`/`seg`/`frac`, nie aus `location_id`.
- **Ankunft wird eine halbe Zelle früher verbucht.** Sobald die nächst-
  gelegene Zelle das Ziel ist, setzt der Ticker die Ankunft und löscht die
  Reise. Folge: `frac` erreicht in der Praxis nie 1,0, und `travel` kann
  bis zu `0,5 × cell_seconds_real` VOR `eta_game` zwischen zwei Polls
  verschwinden. Clients verzweigen auf „Feld weg" (Ankunft), niemals auf
  `frac == 1,0` oder auf das Erreichen von `eta_game`.
- **Freeze:** steht die Spieluhr, stehen alle Reisen. `frac`/`progress_cells`
  bleiben konstant, `cell_seconds_real` ist `null` — genau dann darf nicht
  extrapoliert werden.
- `seconds_per_cell` ist die Welt-Einstellung `game.travel_seconds_per_cell`
  (Admin → Game, Default 60 SPIEL-Sekunden pro Zelle, geklemmt auf 1…3600).
  Sie wird beim START einer Reise auf die Reise geschrieben — laufende Reisen
  behalten ihr Tempo. Kein Client-Wissen; der Client rechnet ausschließlich mit
  `cell_seconds_real`.
- **Der Payload liefert bewusst keine Spiel-Jetzt-Referenz.** Restzeit-
  Anzeigen rechnen daher `(len(path)−1 − progress_cells) × cell_seconds_real`
  — NICHT `eta_game` gegen eine lokale Uhr (die Spieluhr läuft mit Faktor und
  kann springen; `eta_game` ist eine Spielzeit-Marke für Texte/Logs).

**Client-Erwartung**

1. Figur auf der Server-Position rendern (Formel oben), nicht auf der
   Kachelmitte von `location_id`.
2. Zwischen zwei Polls darf mit `cell_seconds_real` extrapoliert werden:
   `progress_cells += Δt_real / cell_seconds_real` (bei `null`: einfrieren).
   **Extrapoliert wird `progress_cells`, nicht `frac`** — `seg` und `frac`
   leitet der Client daraus neu ab:
   `seg = clamp(floor(progress_cells), 0, len(path)−2)`,
   `frac = progress_cells − seg`. Wer nur `frac` im aktuellen Segment
   hochzählt, bleibt an jedem Knoten stehen, bis der nächste Poll kommt.
3. Beim nächsten Poll: Abweichung `|progress_cells_client −
   progress_cells_server| > 0,5` Zellen ⇒ hart auf den Server-Wert
   schnappen. Darunter weich nachziehen.
4. Blickrichtung/Clip bleiben Client-Sache (Laufrichtung aus dem aktuellen
   Segment); `activity_animation` wird bewusst NICHT auf „walk" gezwungen
   (§ A8).

**Verifikation** — numerisch nach dem Prinzip § B5a: der Verify-Modus difft
die Welt-Position der Figur gegen den aus `path`/`seg`/`frac` interpolierten
Pfadpunkt (Toleranz ε = 0,01 Welt-Meter) und meldet Objekt/Feld/Ist/Soll als
Zahlen — keine Screenshot-Beurteilung.

---

# Teil B — Ziel-Vertrag v4: das Szenen-Rezept

Kern des Umbaus: EIN Endpoint liefert die komplette darstellbare Szene
einer Location als **fertige Primitive und Platzierungs-Specs**. Der
Client (und die Admin-Vorschau) besitzen danach genau ZWEI generische
Geometrie-Routinen — „Primitiv bauen" und „Modell platzieren" — und
keine einzige eigene Geometrie-Entscheidung mehr.

## B1. `GET /play/locations/{location_id}/scene`

```
{
  signature,                 # deckt map3d + alle Raum-Layouts + Modell-
                             # Metas + Prop-Sidecars der Location ab
  k, storey_m,               # abgeleitete Skalare (Welt-Einheiten)
  levels: [ { level, floor_y } ],
  style: { wall_color, floor_color, glass_color, glass_opacity,
           upper_wall_opacity, upper_floor_opacity, room_palette: [...],
           elevator_frame_color, elevator_pad_color, elevator_cabin_color,
           elevator_cabin_opacity, elevator_glass_opacity },
           # Editor-Overlays (Marker/Exit/Lineal) bleiben bewusst lokal —
           # Vorschau-AIDs, keine Vertragsgeometrie

  # --- fertige Primitive (Reihenfolge egal, alles Welt-Koordinaten) ---
  plates:  [ { level, outline: [[x,z],…], top_y, thickness,
               texture_kind?, opacity_role: "ground"|"upper",
               room_id? } ],
  walls:   [ { level, from: [x,z], to: [x,z], base_y, height, thickness,
               texture_kind?, glass?, opacity_role, room_id?,
               outward_normal: [nx,nz] } ],
  extras:  [ { kind: "elevator_shaft"|"elevator_pad"|"elevator_cabin"|…,
               … je Kind eine feste Primitiv-Form … } ],

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
               yaw_deg,                    # Eltern-Rotation, −rad im Client
               scale_mode: "fit_box" | "real_size" | "tile_fit",
               box: {w,d,h} | max_m | {xz, y?},
                                           # fit_box: Zielbox (Welt) & 0,96
                                           # real_size: max_m (Welt)
                                           # tile_fit (Gebäude): XZ-Ziel &
                                           #   optionales Y-Ziel (Welt)
               measure_axes?: "xyz"|"xz",  # real_size: BBox-Achsen für
                                           # maxExtent (Default xyz; Dioramen
                                           # messen nur XZ — § B2a)
               scale_axes?: {xz, y},       # Gebäude: achsengetrennt fertig
                                           #   vorgerechnet, wenn Server die
                                           #   Mesh-BBox kennt (§ B4)
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
               placeholder_dims? } ],      # dims×k-Box bei missing/has_model=false

  # --- Rezept-Vokabular pro Raum (PLAN-Fraktionen, für den 2D-Editor) ---
  rooms:   [ { room_id, level, always_visible,
               outline,                    # absolute 8×8-Fraktionen (wie Rezept)
               openings,                   # normalisiert INKL. gespiegelter —
                                           # Ghost-Öffnungen kommen von HIER,
                                           # nie aus lokaler Spiegel-Logik
               exit, exit_derived,         # Rezept-Rahmen: explizit = Raum-
                                           # Rechteck-Fraktion, abgeleitet =
                                           # absolute Platten-Fraktion
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
  figures: { base_height_m_world,          # = 1,70 × k (bzw. Legacy-Wert)
             stand_clearance: 0.12 },      # Welt-Meter, Konstante
  markers: [ { room_id, at_world: [x,z], y_world, animation, facing?,
               source: "room"|"prop" } ],  # ALLE fertig in Welt-Koordinaten
  exits:   [ { room_id, at_world: [x,z], derived? } ],
  outdoor_rooms: [ room_id, … ]
}
```

**Damit wandern in den Server:** Wand-Splitting um Öffnungen inkl.
Fenster-Brüstung/-Sturz/Glas als eigene `walls`-Einträge, Türlücken der
Außenkontur, südlichste-Wand-Fallback-Tür, Spiegelungen, Exit-Ableitung,
Fahrstuhl-Primitive, Etagenplatten, Raum-Platten, alle Konstanten
(0,07 / 0,14 / 0,96 / 0,92 / 0,12 / ±0,4 / < 0,45 / < 0,06 /
max(0,6; storey−0,15)), Farben und Opacities (`style`), Marker- und
Exit-Kompositionen in Weltkoordinaten, Figuren-Maßstab.

**Was der Client noch tut:** GLB/FBX laden, BBox messen, die EINE
place()-Routine (§ B2) ausführen, Primitive als Box/ExtrudeGeometry
bauen, Texturen kacheln. Dazu weiterhin alles Sicht-/Interaktions-
Zustandliche: Kamera, LOD/Fades, Etagen-Umschalter (per `opacity_role`
und `level` gesteuert), Kamera-Culling (`outward_normal` liegt bei),
Labels, Pathfinding, Tag/Nacht, Terrain-Blends, Animations-Retargeting.

## B2. Die EINE Platzierungs-Routine

```
place(mesh, spec):
  1. fix_euler anwenden ('YXZ'), BBox messen
  2. scale_mode "real_size": s = max_m / maxExtent (uniform)
     scale_mode "fit_box":   s = min(box.w/fp_x, box.d/fp_z) × 0,96 —
                             fp = Footprint der GEFIXTEN, noch
                             un-geyawten Box aus Schritt 1. (Präzisierung
                             2026-07-25: die Teil-A-Altkette maß VOR dem
                             Fix und driftete, sobald ein x/z- oder
                             90°-Fix die Achsen tauschte; § A2 beschreibt
                             nur noch das Legacy-Verhalten.)
     scale_mode "tile_fit":  erst Schritt 3, dann an der ROTIERTEN BBox
                             k_xz = box.xz / max(B_x, B_z);
                             k_y = box.y / B_y (ohne box.y: k_xz);
                             scale.set(k_xz, k_y, k_xz) auf Welt-Achsen
     scale_axes gesetzt:     scale.set(xz, y, xz) direkt (Welt-Achsen)
  3. rotation.y = −rad(yaw_deg) als Eltern-Rotation
  4. Ergebnis-BBox messen → Unterkante = bottom_y, XZ-Zentrum = anchor
```

Ersetzt die drei Spezialketten aus § A2 vollständig — Gebäude, Diorama
und Props unterscheiden sich nur noch in den vom SERVER gelieferten
Spec-Werten, nicht im Code. `measure_axes: "xz"` beschränkt die
maxExtent-Messung in Schritt 2 auf die XZ-Achsen.

## B2a. Größenabgleich Diorama ↔ Props ↔ Figuren — EIN Maßstabsgesetz

Befund (2026-07-24): Dioramen skalieren per Rechteck-Einpassung, Props
und Figuren per `reale Meter × k`. Konsistent ist das nur, solange der
Editor das Raum-Rechteck auf `width_m / plan_width_m` hält — zur
Renderzeit erzwingt das niemand; frei gezogene/alte Räume driften, und
seit Dioramen, Props und NPCs im SELBEN Raum stehen, fällt das sofort
auf (Diorama-Sofa ≠ Prop-Stuhl ≠ Figur).

**Neue Regel (v4): Das Diorama skaliert wie ein Prop.**

- Anchored-Mode (k vorhanden) UND `width_m` deklariert →
  `scale_mode "real_size"`, `max_m = width_m × k`,
  `measure_axes: "xz"` (width_m ist die größte XZ-Seite; die Höhe folgt
  uniform). Das Raum-RECHTECK hat damit KEINEN Einfluss mehr auf den
  Diorama-Maßstab — es bleibt Grundriss-Fläche für Platte/Wände/
  Begehbarkeit. Anker/Erdung unverändert (`model_at`,
  Etagenboden + 0,12 + `model_offset_y`).
- Ohne `width_m` oder ohne k → Fallback `fit_box` (Rechteck-Einpassung
  × 0,96 wie bisher, § A2) — mit dokumentiert inkonsistentem Maßstab.
- Der Editor hält weiterhin (v3) die lange Rechteck-Seite auf
  `width_m / plan_width_m` — jetzt nur noch als AID, damit Platte/Hülle
  optisch mit der Diorama-Kante abschließen; ein Überstehen des
  real-size-Dioramas über sein Rechteck ist legitim und wird über
  `width_m`/`model_at` justiert, nicht über das Rechteck.
- Damit gilt raumübergreifend EIN Gesetz: **alles reale Meter × k** —
  Dioramen (`width_m`), Props (`dims`), Figuren (1,70 m + `height_cm`),
  Öffnungen (`width_m`/`sill_m`/`height_m`), Fahrstuhl. Der einzige
  Nicht-k-Maßstab bleibt die Gebäude-Hülle (`tile_fit`, Kachel-Optik).
- **Kalibrierung im Game-Admin:** eine Vergleichsfigur (fix 1,70 × k,
  skaliert NIE mit) wird IN das Diorama gestellt; der Admin stellt
  `width_m` ein, bis die Möbel zur Figur passen, und `walk_y`, bis sie
  auf dem sichtbaren Boden steht. `width_m` ist damit nicht mehr „am
  Quellbild geschätzt", sondern an der Figur geeicht — die Genauigkeit
  von Props/Markern in diesem Raum hängt direkt daran.

## B3. Draft-Vorschau für den Admin

```
POST /play/scene-preview        # Body: location-Draft (map3d + rooms
                                # inkl. ungespeicherter layouts)
                                # → identischer Payload wie /scene
```

Gleicher Composer, keine Persistenz. Damit konsumiert die
Game-Admin-Vorschau (`FloorPlanPreview`) dieselbe Vertragsfläche wie der
Client; `planGeometry.ts`-Duplikate (Spiegelung, Edge-Normalisierung,
Exit-Ableitung) und die Konstanten-Kopien entfallen ersatzlos.
`floorplan.html` des Clients bleibt Debug-Werkzeug und rendert dann
automatisch identisch.

## B4. Server-vermessene Meshes (Ausbaustufe)

Der Server vermisst jedes GLB einmal beim Ingest (Generierung/Upload)
und legt `bbox_raw` + `bbox_fixed` im Sidecar ab. Dann kann `/scene`
`scale_axes`/absolute Transformen fertig liefern und `place()` schrumpft
auf „Matrix anwenden". Assets ohne Vermessung (Bestand) laufen über die
Spec-Parameter aus § B2 — Koexistenz per Datenlage. (Erst nach B1–B3.)

## B5. Rollen ab v4

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

## B6. Divergenz-Fixliste (aus der Analyse, unabhängig von B1 startbar)

| # | Befund | Fix |
|---|---|---|
| 1 | Figuren-Basishöhe Client 1,75 m vs. Vertrag 1,70 m | Client auf 1,70 × k (bzw. `figures.base_height_m_world`) |
| 2 | „0,12 × k" in §2e der Rezept-Note | Zurückgezogen — 0,12 Welt-Meter konstant (§ A3) |
| 3 | `activityToClipKind`-Keyword-Heuristik im Client | `activity_animation` server-authoritativ; Heuristik entfernen, sobald alle Aktivitäten gemappt liefern |
| 4 | README des Clients nennt `map-icon-2d` als Bodenquelle; `mapIconUrl()` tot | Doku/Dead-Code entfernen |
| 5 | `implementierung-3d-pipeline.md` nennt `/characters/{name}/model[/meta]` | Realität ist `GET /characters/{name}/model3d` (JSON) — Doku angleichen |
| 6 | `placements[].model_url` | Deprecated, fällt mit `/scene` weg |
| 7 | Diorama-Böden mit Löchern — begehbare Höhe nicht messbar (Wishlist 2026-07-24) | Angenommen: `walk_y` (Meter über Modell-Unterkante) als Raum-Sidecar-Anker, ausgeliefert in `/scene` `plates[].top_y` bzw. Raum-Meta; Admin-Regler wie übrige Anker |
| 8 | Diorama-Maßstab (Rechteck-Fit) ≠ Prop-/Figuren-Maßstab (×k) im selben Raum | Behoben durch § B2a: Diorama skaliert real-size über `width_m × k` (measure_axes xz); Rechteck-Fit nur noch Fallback |

Rückfragen wie immer über die Wishlist.

## Nachtrag 2026-07-27: Eine Wand, ein Besitzer (Kontur vs. Raumhülle)

Wo eine INDOOR-Raumhülle kolinear auf der Gebäudekontur liegt (Toleranz
0,09 m ≈ Wanddicke + Spiel), liefert `/scene` dort KEIN Konturwand-Stück
mehr — die Raumwand besitzt die Strecke (sie trägt Textur und
Öffnungen). Outdoor-Räume lassen die Kontur unberührt. Befund-Anlass:
deckungsgleiche Wände z-fighteten, sobald eine Wand-Textur gesetzt war
(Haus von Kai, 27 Paare / 16,47 m doppelt — jetzt 0/0).
