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
> 6. **Marker tragen zwei Neigungsachsen.** `markers[].tilt` (Kopf hoch/tief)
>    und `markers[].roll` (seitlich kippen), Grad ±90, Default 0, angewandt
>    NACH dem Facing im Figuren-System ('YXZ'). Vorher konnte eine Figur nur
>    senkrecht stehen — schräg auf dem Sand liegen war nicht ausdrückbar.
> 8. **Ein Raum hat einen eigenen Höhen-Offset.** `layout.floor_offset_y`
>    (Meter, ±, Default 0) hebt den ganzen Raum gegenüber seiner
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
>     (Straße quert die Zelle): `[{edge: N|E|S|W, at_world: [x, z],
>     width_m, type: "passage", room_id?, inward: [±1|0, ±1|0]}]`, Punkt
>     über den Rahmen des Bezugsquadrats (`at` wie Raum-Openings:
>     links→rechts auf N/S, oben→unten auf E/W), `inward` = einwärtige
>     Normale in Weltachsen. **`at`-Degradierung (eine Regel für beide
>     Verbraucher, seit E4):** fehlendes, nicht-numerisches oder nicht-endliches
>     `at` ist die KANTENMITTE 0,5, Werte außerhalb werden auf [0, 1] geklemmt —
>     `scene_recipe._boundary_openings` und `boundary_entry` liefern damit
>     denselben Punkt (vorher stand hier 0, also die Ecke, und der Renderer bot
>     einen Eingang an, den das Eintritts-Gate ablehnte).
>     **Konsum (Etappe 3, 2026-08-03, plan-3d-lod-und-betreten.md):**
>     client3d liest die Openings für die Eintritts-Nähe des
>     „Betreten"-Angebots — Weltposition = Kachelzentrum + `at_world`, mehr
>     rechnet kein Renderer (der Server hat auch die
>     `tile_rotation` nach Nr. 15 bereits eingerechnet). Dabei zählen
>     **nur die Öffnungen der Kante, die der Schritt kreuzt**: eine Öffnung
>     an der Nordkante ist kein Eingang für den, der von Westen her tritt,
>     so nah er an der Ecke auch stehen mag (`entryOfferNear` filtert auf
>     dieselbe Kante, die der Server prüft — sonst verspricht das Angebot
>     einen Schritt, den `opening_on_edge` ablehnt). Und der SERVER
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
>     `h(i,j) = (XorShift32((seed_eff + i·73856093 + j·19349663) & 0xFFFFFFFF)
>     .next01() · 2 − 1) · amplitude_m · k` — Welt-Meter, auf 4 Stellen
>     gerundet. Die beiden Konstanten sind Teil des Vertrags. `seed_eff` ist
>     der wirksame Seed nach Nr. 12: `variant_mix(relief.seed, variant_seed)`
>     bei einem Klon, sonst `relief.seed` unverändert.
>     **Zwischen den Stützpunkten bilinear:** mit n = `grid.length − 1` ist
>     `fx = clamp01(u) · n`, Zelle `i = min(int(fx), n − 1)` und `tx = fx − i`
>     (analog v/j/fy) — kein festes Raster, sondern immer das GELIEFERTE.
>     Ein Sample genau auf der Ostkante (u = 1) fällt damit in die letzte
>     Zelle mit tx = 1 und liest den Randstützpunkt. Dieselbe Formel in
>     `scatter_curves.terrain_height` und in `@anima/scene-render`
>     (`sampleTerrain`), § B5a-prüfbar von Hand.
>     **Payload:** `scene.terrain = {step, grid, amplitude_m}`, nur wenn
>     `relief` gesetzt ist; `amplitude_m` steht dort in Welt-Metern.
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
  `rotation.y = +rad(yaw_deg)` — **derselbe Drehsinn wie in der
  Szenen-Yaw-Kette** (`map3d.rotation`, § A1.8: `rotation.y = +rad(yaw)`,
  angeglichen mit E4). Die beiden Felder bleiben trotzdem verschiedene
  Dinge — das eine dreht die Location in der Welt, das andere das Modell in
  der Szene; wer sie verwechselt, spiegelt die Location.
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
> Die Szenenhöhe einer Location ist ein ZWEITES Feld **auf** diesem
> (`relief.ground_lift_at` addiert beide) — der Rand eines Szenen-Reliefs ist
> auf 0 gepinnt, ein Ort auf einem Hügel fährt also mit dem Hügel hoch,
> statt ein flaches Regal hineinzuschneiden.

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
| `plan_width_m` | `float \| null` | Kantenlänge des Fußabdrucks, aus `map3d` hochgezogen. Der Wert stammt aus demselben Fußabdruck, den auch `world_bounds` benutzt — Eintrag und Fußabdruck-Regel können also nicht auseinanderlaufen. `null` bedeutet deshalb **zweierlei**: der Ort ist **unplatziert** (dann hat er keinen Fußabdruck, egal wie gut sein Anker ist) ODER seine Geometrie hat keinen brauchbaren Anker (`map3d.plan_width_m` fehlt, ist ≤ 0 oder unlesbar). Ein Client, der die Kantenlänge eines unplatzierten Ortes braucht, findet sie bis dahin nur in `map3d`; E2 (Drag-Ghost) darf den rohen Anker unplatzierter Orte später zusätzlich als eigenes Feld liefern |
| `map3d` | `object` | **optionaler Schlüssel** — nur wenn nicht leer (inkl. der abgeleiteten `floors`-Ersatzangabe aus den Raum-Layouts) |
| `layout_sig` | `str` (10) | **optionaler Schlüssel** — nur wenn mindestens ein Raum ein Layout hat ODER `map3d` nicht leer ist (AV3D-2⁺). Die Signatur deckt **beides** ab: die Raum-Layouts **und** die szenenformenden `map3d`-Metadaten des Ortes (Grenz-Durchgänge, `rotation`, `size`, `tile_rotation`, `plan_width_m`, `storey_height_m`, `floors` …). Ändert sich eines von beiden, holt der Client die Szene neu — ein gezeichnetes Tor erreicht so auch einen laufenden Client (E5 B11) |

Wurzelfelder des Payloads: `avatar` · `current_location_id` ·
`locations` · `characters` · `events_by_location` · `world_bounds` ·
`terrain_sig` · `height_sig` · `fogged` · `max_step_height_m` ·
`max_slope_deg` · `backdrop` (**optionaler Schlüssel** — nur wenn die
Fernkulisse eingeschaltet ist, § A17).

| Wurzelfeld | Typ | Bedeutung |
|---|---|---|
| `world_bounds` | `{"min_x","min_z","max_x","max_z"} \| null` | Ausdehnung der Welt in Metern, auf 2 Stellen gerundet; **vor** dem Fog-Filter berechnet (A1.6) |
| `terrain_sig` | `str` (10) | Signatur über gemalte Flächen + Welt-Typenzeilen. Ändert sie sich, holt der Client `GET /play/terrain` neu — sonst nie |
| `height_sig` | `str` (10) | Signatur über die autorierten **Höhenflächen** UND die **Platzierungen der planierenden Orte** (E8 Task 2/4 — ein verschobener Ort verschiebt sein Plateau, § A16.1; seit 2026-08-13 zählen nur Orte mit `level_ground`, und das Setzen/Löschen des Flags ändert die Signatur für sich allein) UND über das **Mikro-Relief der gemalten Terrain-Arten** (§ A16.2: relief-tragende Flächen samt der flachen Flächen darüber und den beiden Katalog-Zahlen; relief-freies Malen zählt nicht mit). Ändert sie sich, holt der Client `GET /play/heightfield` neu **und verwirft Kachel-Index samt aller geladenen Kacheln** (§ A16.3) — sonst nie. Wie `terrain_sig` **nie gefoggt**: ein Bergrücken ist von weit außerhalb sichtbar, und ein verstecktes Relief ließe Bild und Laufregel auseinanderlaufen |
| `fogged` | `bool` | `true` = gefilterte Sicht (§ A12) |
| `max_step_height_m` | `float` | Welt-Einstellung `game.max_step_height_m` (Default 0,4; validiert und geklemmt auf [0,05; 5]). Höchste Stufe, die eine Figur nimmt — Teil des Höhen-Gates von `POST /play/pos` (§ A15 Nr. 8) |
| `max_slope_deg` | `float` | Welt-Einstellung `game.max_slope_deg` (Default 40; geklemmt auf [10; 89]). Steilste Steigung, die eine Figur erklimmt — dasselbe Gate |
| `backdrop` | `{"height_m","seed","arcs"} \| fehlt` | Die **Fernkulisse** (§ A17) — reine Optik. Fehlt der Schlüssel, ist sie aus (oder der Server ist älter); beides ist für den Client derselbe Zustand |

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
`travel`, `avatar_url`.

| Feld | Typ | Bedeutung |
|---|---|---|
| `pos` | `{"x": float, "z": float} \| null` | Freier Meterpunkt. **Die Wahrheit**; `location_id` wird daraus abgeleitet (Punkt im Fußabdruck). `null` = der Charakter hat keinen Punkt (nie gesetzt, oder seine Location ist selbst unplatziert) — erst dann fällt ein Client auf den Location-Mittelpunkt zurück |
| `travel` | `{…} \| null` | Laufende Reise als **Meter-Polyline** (`target_id`, `waypoints`, `progress_m`, `total_m`, `eta_game`, `speed_m_s_real`, `pace_m_s_real`) — Felder und Formeln in **§ A11**. `null` = keine Reise. Solange der Block MIT `waypoints` da ist, kommt die Render-Position aus ihm, nicht aus `pos` (das nur im Ticker-Takt nachgeführt wird); ohne `waypoints` (Fog, § A11 — dort sind auch alle Zahlen des Blocks `null`) bleibt `pos` die Position |

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
  sig:    str }               # identisch mit worldmap.terrain_sig
```

- `types` ist der **wirksame** Katalog, nach `kind` sortiert.
- `areas` kommen **von unten nach oben**: `z_order` aufsteigend, bei
  Gleichstand die Malreihenfolge. Der LETZTE Eintrag liegt oben.
- `polygon` = `[[x, z], …]` in Welt-Metern, auf 2 Stellen gerundet, 3–256
  Punkte, automatisch geschlossen.
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

Eine **Liste** je Fläche, höchstens 8 Einträge, jeder Eintrag genau drei
Felder (Server-Whitelist `app/models/terrain._sanitize_scatter_list`):

```
scatter: [ {density_per_100m2: float,   # Instanzen je 100 m² der Fläche, 0 = keine
            model?: str,                # /assets/props/<id>/model; fehlt = eingebautes Büschel
            height_m?: float}, … ]      # ZIELHÖHE: das Prop wird uniform darauf skaliert
```

- **Fehlende oder leere Liste = es wächst nichts.** Es gibt keine Vorgabe.
- **Der Server hängt an einen Eintrag mit Prop-`model` zusätzlich
  `variants: {tier: "/assets/props/<id>/model?tier=<tier>"}`** — nur die
  Stufen, die das Prop WIRKLICH hat, aufgelöst mit derselben einen Regel
  `pickVariant` wie die Szenen-Props (§ B1); fremde/absolute URLs und Props
  ohne Mesh bekommen den Schlüssel nicht, und ohne `variants` lädt ein Client
  weiter `model`. Welche Stufe er wann nimmt, ist **Anzeige-Politik des
  Clients** (Distanz-Hysterese, Sichtweite, Instanz-Budget — in
  `development_instructions/plan-scatter-lod.md` festgehalten), kein
  Payload-Vertrag: gespeichert bleiben die drei Felder oben.
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
  Fog-Modus.

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
| `GET /world/height-areas` | `{areas, sig, step_m, default_step_m, tile_step_m, max_slope_deg, max_step_height_m}` — die autorierten **Höhenflächen** (§ A16) in stabiler Anlege-Reihenfolge, dazu der aktuelle Übersichts-Schritt und der feinste (Befund 14: die Vergröberung ist sonst unsichtbar) sowie der **Kachel-Schritt**, aus dem der Editor die Plateau-Rampe `tan(max_slope_deg) · tile_step_m` rechnet (§ A16.1). Die beiden **Lauf-Grenzen** fahren seit 2026-08-16 mit (dieselben Werte wie in der Weltkarte, aus denselben `core.relief`-Gettern): jeder Editor, der eine Relief-Zahl zeigt, muss auch sagen können, ab wann sie unbegehbar wird — dafür soll niemand die ganze Weltkarte ziehen |
| `POST /world/height-areas` | Neue Höhenfläche, **die Id vergibt der Server** → `{status, area, step_m}`; `step_m` ist der Schritt DANACH (der Schreibvorgang rastert synchron neu), also eine Tatsache und keine Prognose |
| `PUT /world/height-areas/{id}` | Ersetzt `polygon`/`height_m`/`falloff_m`/`meta` einer **bestehenden** Fläche → `{status, area, step_m}`; **404**, wenn es die Id nicht gibt |
| `DELETE /world/height-areas/{id}` | Löscht eine Höhenfläche (der Boden dort fällt auf die flache Welt zurück); **404**, wenn es sie nicht gab |

Geprüft wird **beim Schreiben**, nicht beim Lesen (die Leser scheitern
still): Art muss im Katalog stehen · Polygon 3–256 endliche
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
- **Yaw-Kette der Szene:** `yaw = map3d.rotation` (explizite 0 zählt) →
  `map_rotation_2d` → 0; three.js **`rotation.y = +rad(yaw)`**.
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
  drehen seitdem gespiegelt — bewusst, ohne Migration.
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
  der Yaw in der Szenen-Kette (§ A1.8), der im Rezept und in der
  Draft-Vorschau mitreist.

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
- Figuren stehen indoor auf der ABGETASTETEN Bodenfläche (Diorama-Boden
  bzw. Rezept-Platte); die Konstante verankert nur Modelle/Platten.
  Outdoor-Räume haben keine Platte — Figuren stehen auf Level-/
  Terrain-Höhe.
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
  markers?,
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
- **Raum-Ebene (Klarstellung v4):** Raum-Bodenplatte Oberkante
  `level × storey + 0,10` (liegt damit AUF der Etagen-Platte; Dicke
  0,02), Raumhüllen-Wände Basis 0,10; Props auf Platte + 0,01 (§ A2);
  Diorama-Unterkante bleibt bei + 0,12 (§ A3). Der Legacy-Fahrstuhl (ohne
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
  Meter. Figuren-Routing: Türschwelle → Fahrstuhl → vertikal → weiter.
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
- **`undergrowth` — wie viel auf einem Boden VON SELBST wächst** (2026-08-15,
  Erzeugung umgebaut 2026-08-16). Ein whitelisteter `meta`-Schlüssel, eine
  Zahl 0…1 (zwei Dezimalen, 0/leer/Junk = Schlüssel weg) = Anteil der vollen
  Unterwuchs-Dichte des Clients. Der Server liefert NUR diese Zahl; Position,
  Höhe, Distanzen und Geometrie gehören dem Renderer, es gibt dafür keine
  weiteren Katalog-Schlüssel und kein Authoring pro Fläche.

  **Vertrag für die Renderer — KAMERA-LOKAL, nicht pro Fläche.** Der Unterwuchs
  wird NICHT mehr über die ganze gemalte Form vorgebaut, sondern pro ZELLE
  eines ursprungsverankerten 64-m-Rasters im Umkreis von 128 m um denselben
  Anker, den die feinen Höhen-Kacheln nutzen (§ A16.3: der Avatar, solange der
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
| `eta_game` | ISO-Zeit `\| null` | nominelle Ankunft auf der **Spieluhr**; trägt den Offset der **Weltzeitzone** (`server.timezone`) — ein HH:MM-Slice ergibt direkt Spiel-Wanduhrzeit. **Gefoggt `null`** wie `progress_m` |
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
- **Der Payload liefert bewusst keine Spiel-Jetzt-Referenz.** Ein laufender
  Restzeit-Countdown rechnet daher näherungsweise
  `(total_m − progress_m) / speed_m_s_real` in ECHTEN Sekunden — NICHT
  `eta_game` gegen eine lokale Uhr (die Spieluhr läuft mit Faktor und kann
  springen). Der ANGEZEIGTE Ankunftszeitpunkt kommt immer aus `eta_game`
  (siehe Nominal-Absatz oben).
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
  einkreisen. Gefoggt sind für jeden außer dem Avatar deshalb ALLE sechs
  Felder `null` — `waypoints`, `progress_m`, `total_m`, `eta_game`,
  `speed_m_s_real`, `pace_m_s_real`. Die Schlüssel bleiben stehen, damit
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
`progress_m` und `total_m` bedeuten dort dasselbe (`eta_game` ebenfalls mit
Weltzeitzonen-Offset). Zusätzlich nur `target_name`, `eta_hhmm` (fertiges
Label, weil der Browser die Spielzeitzone nicht kennt) und `arrived`; die
`waypoints` fehlen — das Panel zeichnet keine Karte. `POST /play/travel`
antwortet mit genau diesem Block unter `journey`.

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
| `characters[]` | ja | der Avatar selbst immer; jeder andere nur, wenn seine `location_id` sichtbar ist. Unsichtbarer Ort ⇒ Figur fehlt komplett. **Wildnis** (`location_id: ""` mit `pos`): seit **E6** die Sichtweiten-Regel unten — nur wer nah genug am Avatar steht, ist da; Reisende bleiben (§ A11), solange ein Avatar aktiv ist |
| `characters[].movement_target_id` | nein | das Reiseziel bleibt — der Client zeichnet die Richtung |
| `characters[].movement_target_name` | ja | `""`, wenn das Ziel nicht sichtbar ist. Ohne diese Regel leckten Ortsnamen über die Figurenliste |
| `characters[].travel` | teilweise | der Block bleibt (die Figur ist ja sichtbar), aber bei **jedem außer dem Avatar** sind ALLE sechs Zahlen/Listen `null`: `waypoints`, `progress_m`, `total_m`, `eta_game`, `speed_m_s_real`, `pace_m_s_real`. Es bleibt `target_id` — opak, wie `movement_target_id`. Begründung und Feldliste: § A11 („Die ROUTE ist Avatar-Wissen — und ihre ZAHLEN auch") |
| `events_by_location` | ja | nur Schlüssel sichtbarer Orte |
| `world_bounds` | **nein** | siehe unten |
| `terrain_sig` | **nein** | Gelände wird nie gefoggt (§ A1.5) |
| `max_step_height_m`, `max_slope_deg` | **nein** | die zwei Lauf-Grenzwerte (§ A1.3, § A15 Nr. 8). Regeln sind keine Ortskenntnis — ein Grenzwert verrät nichts über die Welt |
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
  als das, was ohnehin unter den Räumen liegt: die Etagenplatte der Etage 0
  mit dem aus `terrain` aufgelösten Kind (§ A9, Reihenfolge in § A6).
  **Achtung:** diese Platte entsteht nur, wenn die Location einen Grundriss
  hat (`map3d.outline`) — ohne ihn gibt es in der Detailszene keine
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

**Request** `{"x": <Meter>, "z": <Meter>}` · **Antwort**
`{ok: true, pos: {x, z}, location_id, room_id}`.

**Meldefrequenz:** ~3/s während der Bewegung plus einmal beim Anhalten.
Server-Drossel ~4/s.

**Die Gate-Kette, in genau dieser Reihenfolge** (jede Absage trägt
`{reason, message, pos, location_id}`, wobei `pos` der LETZTE GÜLTIGE Punkt
ist — der Client snappt die Figur darauf zurück, damit die beiden Sichten nie
auseinanderstehen):

| # | Prüfung | Absage |
|---|---|---|
| 1 | Party-**Follower** besitzt keine eigene Bewegung | 403 `party_follower` |
| 2 | `x`/`z` sind endliche Zahlen | 400 |
| 3 | **Drossel** ~4 Meldungen/s — Überschuss wird STILL verworfen, kein Fehler-Toast | 200 `{ok: false, throttled: true}` |
| 4 | **Schrittweite** gegen die ECHTE Zeit seit der letzten AKZEPTIERTEN Meldung | 409 `too_far` |
| 5 | **Location des Punktes** ableiten (`location_at_point`) — entscheidet Nr. 6 | — |
| 6 | Gelände `passability_at` am Punkt (§ A1.5) — **nur in der WILDNIS** (`location_id == ""`); NUR die Passierbarkeit, das Tempo wird hier nie geprüft | 409 `impassable` |
| 7 | **Location-Übergang** — EXIT vor ENTRY | 403 (siehe unten) |
| 8 | **Höhe** des Punktes gegen den letzten gültigen (Steigung immer, Stufe zusätzlich unter 1 m — siehe unten) | 409 `too_steep` |

**Die Erlaubnis in Nr. 4 hat DREI Terme**, und der dritte ist keine
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

**FOOTPRINT GEWINNT — FÜR DIE PASSIERBARKEIT (Nr. 5 vor Nr. 6, Entscheidung
2026-08-13, präzisiert durch Befund 3).** Gemaltes Gelände beurteilt, wo man
STEHEN darf, zwischen den Orten. Liegt der gemeldete Punkt in
IRGENDEINEM platzierten Fußabdruck (eigener wie fremder), entfällt der
Gelände-Check ganz — eine Location wird AUF die Welt gesetzt und erbt nicht
den Boden, den jemand darunter gemalt hat. Sonst wäre eine Halle auf einem
Felsplateau oder ein Dorf auf einer Insel im See ein Ort, in dem man keinen
Schritt tun kann und jede Meldung eine Absage bekommt (Abnahme-Befund B1);
das Tor eines Ortes sind seine Öffnungen und Regeln (Nr. 7), nie der Fels
darunter. Das ist zugleich die **Voraussetzung für das E8-Plateau**: dort
wird die Heightmap unter dem Fußabdruck planiert (sofern der Ort es
verlangt, § A16.1), und der Fels unter dieser Planierung darf die geebnete
Fläche nicht weiter sperren. Diese Passierbarkeits-Regel hängt NICHT am
`level_ground`-Flag — sie gilt für jeden Fußabdruck.

Dieselbe Regel gilt im **NPC-Routing** (`nav_grid`): eine Zelle stirbt am
fremden Fußabdruck (SAT) oder am Gelände in ihrer Mitte — Letzteres nur
außerhalb jedes Fußabdrucks. Ohne das wäre ein Ort auf Fels für die Reise
unerreichbar, während sein Avatar darin frei umherläuft. Am GELÄNDE stirbt
sie drinnen also nie; an der STEILHEIT dagegen schon, wenn der Ort nicht
planiert (§ A16.1) — die beiden Ausnahmen sind zwei Regeln, und nur die
zweite fragt `level_ground`.

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

**Der Übergang (Nr. 7).** Gleiche Location oder Wildnis → Wildnis ist frei.
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

**DAS HÖHEN-GATE (Nr. 8) — neu 2026-08-13 (E8 Task 1).** Bis hierher hat in
dieser Welt keine einzige REGEL nach einer Höhe gefragt: das Szenen-Payload hob
Props, die Renderer drapierten den Boden, und eine Felswand ließ sich so leicht
hochlaufen wie eine Wiese. Jetzt vergleicht der Server den Boden unter dem
letzten gültigen Punkt mit dem Boden unter dem gemeldeten:

```
Δh = lift(neuer Punkt) − lift(letzter Punkt)
IMMER       ->  STEIGUNG:  atan(|Δh| / dist) > game.max_slope_deg  (Default 40°)
dist < 1 m  ->  UND STUFE: |Δh| > game.max_step_height_m           (Default 0,4 m)
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

**Die Richtung zählt nicht**: einen Abhang hinunterzufallen ist so unmöglich
wie ihn hinaufzuklettern, sonst könnte man einen Läufer irgendwo aussetzen, wo
er nicht mehr hochkommt.

**Woher die Höhe kommt: ZWEI Quellen, EINE Antwort**
(`app/core/relief.ground_lift_at`).

1. Das WELTRELIEF unter allem — `world_geometry.ground_y`, das gerasterte
   Höhenfeld (§ A16), bilinear gelesen. Es gilt drinnen wie draußen; unter
   einem Fußabdruck MIT `level_ground` ist es durch die Planierung eben
   (§ A16.1), unter jedem anderen läuft die Landschaft einfach durch.
2. Das SZENEN-Relief obendrauf: für eine `area_detail`-Location mit
   `map3d.relief` wird genau das Feld gesampelt, das
   `GET /play/locations/{id}/scene` als `terrain.grid` ausliefert (§ B1 Nr. 14)
   — dieselbe eine Gitter-Konstruktion (`scene_recipe.compose_terrain`),
   inklusive `tile_rotation`. Sein Rand ist auf 0 gepinnt, es ist also ein
   Aufschlag, kein Ersatz: ein Ort auf einem Hügel fährt mit dem Hügel hoch.

In einer Welt, in der niemand etwas modelliert hat, sind beide 0 und das Gate
ist vollständig inert.

Der Client spiegelt beides mit denselben Quellen (`main.ts reliefLiftAt` →
`game/ground.groundLift`): das Weltfeld über `sampleWorldHeight` — die
BILINEARE Lesung, nicht die gezeichnete Dreiecksfläche `sampleGroundHeight`,
denn dieser Spiegel sagt die Server-Antwort voraus und der Server liest das
Feld — und das Szenen-Relief über `scene/tiles.terrainLiftAt`, **nicht** über
den Modell-Raycast `tileGroundY`: der kennt eine Modell-Oberfläche, die der
Server nicht kennt, und die beiden Sichten müssen sich einig bleiben. (Bis E8
Task 4 fehlte dem Spiegel der Welt-Term — das war das Gummiband auf jedem
Welt-Hügel: der Client lief die Figur hoch, der Server holte sie 3×/s zurück.)

**Dieselbe Regel im NPC-Routing** (`nav_grid`, E8 Task 4). Eine Zelle ist
blockiert, wenn der Boden AN IHRER MITTE steiler steht als `max_slope_deg` —
gemessen als ZENTRALE Differenz über die je zwei Gegennachbarn
(`rise = hypot(h(x+c,z)−h(x−c,z), h(x,z+c)−h(x,z−c))`, `run = 2 · NAV_CELL_M`).
Zentral und nicht einseitig: der flache Boden am FUSS einer Klippe erbte sonst
deren Steilheit, und das Ufer jedes Sees wäre unbegehbar. Ausgenommen sind
Zellen INNERHALB eines Fußabdrucks **mit `level_ground`** (Footprint gewinnt;
nur DORT ist das Feld planiert — seit 2026-08-13 ist die Planierung opt-in,
§ A16.1, und unter einem ungeflaggten Ort läuft die autorierte Landschaft
durch, die dann genauso beurteilt wird wie der Boden draußen) und Zellen an
einer Öffnung (`OPENING_EXEMPT_M` = 1,5 m Toleranz + eine Zelle) — dieselbe
Rampenenden-Ausnahme wie unten. Die PASSIERBARKEITS-Ausnahme („Footprint
gewinnt" bei gemaltem Untergrund) fragt das Flag NICHT: sie gilt für jeden
Fußabdruck, geflaggt oder nicht. Dazu kostet
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

**Verschachtelung: der INNERSTE UMSCHLIESSENDE Ort MIT Relief gewinnt.** Nicht
„der Ort, in den der Punkt fällt": ein Ort ohne eigenes Relief planiert den
Boden nicht, auf dem er steht — er steht DARAUF. Sonst säße eine Hütte auf
einem Dorfplatz, dessen Relief 2 m ansteigt, in einer selbstgemachten Grube:
der Platz antwortet 2 m, die Hütte 0, und dazwischen stünde eine 63°-Klippe,
die eine öffnungslose Hütte von allen Seiten versiegelt. Die Auflösung ist
dieselbe Kleinster-gewinnt-Regel wie bei `location_at_point`, nur beschränkt
auf Orte, die ein Feld HABEN; wer keines hat, ist für die Frage durchsichtig.
Der Client spiegelt das in `reliefLiftAt`.

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

An einem PLANIERENDEN Ort (§ A16.1) ist am Weltrelief ohnehin nichts zu
überqueren: der gepinnte Ring reicht eine Zelle ÜBER den Fußabdruck hinaus,
die Öffnung liegt also auf ebenem Grund. Die Ausnahme trägt weiterhin den
Fall, den sie immer trug — eine Klippe im SZENEN-Relief an der Öffnung — und
seit die Planierung opt-in ist auch den Weltrelief-Fall wieder: an einem Ort
OHNE `level_ground` steigt der autorierte Hang durch die Türschwelle, und
genau dafür ist die Rampenenden-Ausnahme da. Bis zur Plateau-Rampe eine Zelle
weiter draußen reicht sie bewusst nicht: das ist die Autorierungs-Grenze aus
§ A16.1, kein Loch in der Regel.

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

## A16. Das Weltrelief — `GET /play/heightfield` — neu 2026-08-13 (E8 Task 2)

**Der Boden der offenen Welt ist ab hier eine Landschaft.** Bis E8 war jede
Höhe eine Sache der Innenszene; draußen war die Welt die flache v1-Platte.
Autoriert wird sie im Karten-Editor als **Höhenflächen**, ausgeliefert wird
sie als **Gitter**, und `ground_y(x, z)` (§ A1.2) ist die eine Funktion, die
beides verbindet.

**Seit 2026-08-13 hat das Feld eine zweite Quelle:** das **Mikro-Relief der
Terrain-Arten** (§ A16.2) — gemalter Boden bringt seine eigenen kleinen Hügel
mit. Alles Folgende gilt unverändert; das Relief kommt als ADDITIVER Durchgang
zwischen Flächen und Planierung hinzu, und `height_sig` deckt es mit ab.

**Zwei Formen, nur eine wird bearbeitet.** Eine **Höhenfläche** ist ein
Polygon in Weltmetern plus `height_m` (wie hoch der Boden darin steht) und
`falloff_m` (über wie viele Meter er dorthin ansteigt). Das **Gitter** ist
daraus gerechnet — ein Cache, keine Autorierungsfläche. Niemand bearbeitet
Zellen.

```
h_flaeche(p) = height_m · min(1, Abstand(p, Kontur) / falloff_m)
               für p INNERHALB der Kontur, sonst sagt die Fläche nichts
```

Die Fläche trifft die Welt also **auf ihrer eigenen Kontur** bei 0 und
braucht keinen passenden Nachbarn, um stetig auszusehen. `falloff_m` 0 heißt
„kein Übergang“ — eine Wand an der Kante.

**Überlappung: die STÄRKSTE Auslenkung gewinnt** (größter `|Wert|`, bei
Gleichstand der höhere). Für zwei Hügel ist das wörtlich „der höhere
gewinnt“; als Auslenkung formuliert, damit eine **Senke** (negatives
`height_m`) nicht von der 0 der flachen Welt drumherum geschlagen wird.
Deterministisch: dieselben Flächen ergeben dasselbe Gitter, auf jeder
Maschine.

**Bekannte Autorierungsgrenze dieser Regel** (Entscheid 2026-08-13, bewusst
so): eine schwächere Fläche kann sich nicht RELATIV in eine stärkere
einschneiden — ein 2-m-Graben quer über ein 9-m-Plateau bleibt Plateau, weil
9 stärker auslenkt als 2. Wer eine Mulde im Hochland will, autoriert sie als
eigene Fläche mit der ABSOLUTEN Höhe (7 m), nicht als Differenz. Die
Planierung unter Fußabdrücken (T4) braucht das nicht: sie ist ein eigener
Durchgang NACH der Rasterung und gewinnt ohnehin.

**Das Gitter hängt am WELT-URSPRUNG, nie an `world_bounds`.** Jeder
Stützpunkt sitzt auf einem Vielfachen von `step_m`, gezählt ab (0, 0):

```
origin = floor(min / step) · step − step          # ein Ring AUSSERHALB der Daten
punkte = ceil((max + step − origin) / step) + 1   # und einer dahinter
```

Damit verschiebt eine neu gemalte Fläche am Weltrand **keinen einzigen
bestehenden Stützpunkt** — ein aus der aktuellen Ausdehnung abgeleitetes
Gitter würde bei jedem Anbau alle Höhen der Welt verrücken (Inventar-Befund
5). Und weil der komplette Rand außerhalb aller Flächen liegt, ist er 0:
**außerhalb des Gitters gilt der Randwert**, und das bedeutet exakt „die
flache Welt“.

`step_m` ist standardmäßig **4 m** und reist MIT dem Datensatz. Reicht die
bemalte Ausdehnung über das Punktbudget (120 000 Stützpunkte), wird der
Schritt **verdoppelt**, bis es passt — ein doppelt so weites Land bekommt ein
gröberes Relief, kein abgeschnittenes. Verdoppeln hält das Gitter am
Ursprung verankert. `height_m` ist auf **±50 m** geklemmt (§ A1.7), auch weil
der 3D-Client seine Kacheln aus fester Höhe anrayct.

**Diese Vergröberung ist SICHTBAR zu machen** (Befund 14, 2026-08-13). Sie
hängt an der Vereinigungs-Box von allem, was den Boden formt: eine einzige
Fläche weit draußen vergröbert das Relief der GANZEN Welt — live gemessen hob
eine 16 160 × 5 876 m große Box den Schritt von 4 m auf 32 m, und das
Mikro-Relief einer 22-m-Fläche (Welle 8…12 m) hatte danach keinen Stützpunkt
mehr und verschwand, ohne dass irgendetwas den Zusammenhang gezeigt hätte.
Darum liefern `GET /world/height-areas` und die Schreib-Antworten von
`POST`/`PUT /world/height-areas` den aktuellen `step_m` (die GET zusätzlich
`default_step_m` und `tile_step_m`), und der Editor zeigt ihn dauerhaft an,
sobald er über dem feinsten liegt, samt Konsequenz: **unter 2 × Schritt trägt
das Raster nichts mehr** (Nyquist, dieselbe Grenze, die `relief_wave_m` klemmt
— dort am KACHEL-Schritt, siehe § A16.2). Der Server rechnet, der Editor zeigt
— eine zweite Verdopplungs-Logik im Client wäre genau die Zwillings-Regel, die
auseinanderläuft. Aus demselben Grund reist `tile_step_m` mit: die
Rampen-Zahl der Planierung hängt daran und hat sich am 2026-08-14 halbiert.

**Payload** (Auth wie `/play/terrain`: eingeloggter User, **kein** Admin-Gate,
**nie gefoggt**). Eigener Endpoint aus demselben Grund wie das Gelände — und
doppelt so triftig, weil ein Gitter größer ist als eine Flächenliste:
**gemessen 0,94 MB unkomprimiert bei vollem Punktbudget** (346 × 346 Punkte,
1 370 m Kante) und 190 KB für eine Welt aus 40 autorierten Hügeln. Das ist
nichts für einen 3-Sekunden-Poll und alles für einen Abruf bei
Signaturwechsel. Geholt wird er einmal und neu, wenn `height_sig` in der
Weltkarte wechselt.

```
{ origin_x, origin_z,   # Weltmeter des Stützpunkts heights[0][0]
  step_m,               # Abstand zweier Stützpunkte in Metern
  rows, cols,           # Gitterform; 0/0 + heights [] = flache Welt
  heights: [[float, …], …],   # heights[j][i] = Höhe bei
                              # (origin_x + i·step_m, origin_z + j·step_m)
  sig,                  # identisch mit worldmap.height_sig
  tile_m,               # Kantenlänge einer Kachel in Metern (256,0; § A16.3)
  tile_step_m,          # Schritt der Kacheln — IMMER 2,0, nie vergröbert
  tiles: ["tx,tz", …] } # der KACHEL-INDEX: jede Kachel, in der die Welt
                        # einen Boden hat, sortiert nach tx, dann tz
```

**Dieses Gitter ist seit v2 die FERN-Übersicht** (§ A16.3): es ist das eine
Raster, das vergröbert werden darf, und keine Regel liest es mehr. Die
mitgelieferten drei Felder sind die Brücke zur feinen Auflösung —
`tiles` sagt, wo überhaupt Boden ist, und `GET /play/heightfield/tiles` liefert
ihn in 2 m. **Vermischt werden die beiden nie**, siehe § A16.3.

**Zwischen den Stützpunkten ist das Feld BILINEAR**, und zwar in beiden
Sprachen gleich:

```
fx = clamp((x − origin_x)/step, 0, cols−1);  i = min(floor(fx), cols−2);  tx = fx − i
fz = clamp((z − origin_z)/step, 0, rows−1);  j = min(floor(fz), rows−2);  tz = fz − j
nord = h[j][i]·(1−tx) + h[j][i+1]·tx
sued = h[j+1][i]·(1−tx) + h[j+1][i+1]·tx
h    = nord·(1−tz) + sued·tz
```

Ein Feld mit weniger als 2 × 2 Punkten trägt kein Relief und antwortet 0.

**Zwillings-Disziplin (verbindlich).** `app/core/heightfield.sample_height`
und `packages/scene-render/src/worldHeight.ts` (`sampleWorldHeight`) sind
dieselbe Formel zweimal, und sie müssen es bleiben: der Server lehnt eine
Laufmeldung nach SEINER Lesung des Feldes ab (§ A15 Nr. 8), der Renderer
drapiert den Boden nach seiner. Beide werden gegen **eine** von Hand
hergeleitete Tabelle geprüft — `scripts/smoke_heightfield.py` Abschnitt [8]
und `client3d/scripts/smoke_world_height.mjs`, dasselbe Feld, dieselben
Erwartungen (§ B5a: Zahlen, keine Screenshots).

**Was der RENDERER damit macht** (E8 Task 3, gilt für beide Renderer): der
Boden wird auf DEM Gitter geschnitten, das das Feld mitbringt — die Basisplatte
als Zellgitter (`gridPlate`), jede gemalte Fläche entlang derselben Linien
zerteilt (`subdivideOnGrid`, `@anima/scene-render/gridMesh`). Jede Zelle wird
dabei von der Minimum- zur Maximum-Ecke geteilt, auf beiden Seiten.

**Gehoben wird mit `sampleGroundHeight`, nicht mit `sampleWorldHeight`.** Ein
Netz ist nicht bilinear, es ist dreieckig: über einer Zelle ist die gezeichnete
Fläche eine von zwei EBENEN

```
tz <= tx:  h00 + tx·(h10−h00) + tz·(h11−h10)
tz >  tx:  h00 + tz·(h01−h00) + tx·(h11−h01)
```

und sie weicht im Zellinneren um bis zu ein Viertel der Zell-Verwindung
`|h00+h11−h01−h10|` vom Feld ab. Gemessen an einer 5-m-Fläche mit 10 m Falloff
auf 8-m-Gitter: **ein voller Meter** — genau so weit sackt ein Flächen-Vertex
unter die Platte, wenn er bilinear gehoben wird, und genau so weit sticht die
Platte durch die Wiese. Der Fehler hängt an der Verwindung, NICHT am Verhältnis
`falloff_m` zur Zellweite; eine Autorierungs-Grenze gibt es dafür nicht. Also
liest ALLES, was den Boden berührt, denselben Sampler: Platte, Flächen, Streu,
Figuren, Marker. `sampleWorldHeight` bleibt, was es war — der Zwilling der
Server-Lesung des Feldes.

**Und wo die FIGUR steht:** auf `max(Weltboden, Kachel-Laufhöhe)` — der
Fußabdruck bringt seine eigene Laufhöhe mit (Platte, Modellhaut, Szenen-Relief,
alles um das Kachelzentrum gerechnet), das Weltrelief läuft unter einem nicht
planierenden Ort einfach weiter, und das Höhere gewinnt; die Fußabdruck-Platte
wird mit demselben Sampler drapiert, damit das Gelände nicht durch sie
hindurchschneidet. Unter einer Planierung (§ A16.1) sind beide Zahlen dieselbe,
die Regel ist dort ein No-op. Der Preis ist Autorierungs-Sache: ein
`display: ground`/`shell_area`-Modell, das unter den Weltboden taucht (Seegrund,
versenkter Hof), wird von der Landschaft unterlaufen.

**Zellweite:** `gridStepFor` verdoppelt den Feld-Schritt, bis das Netz unter
40 000 Zellen bleibt, und misst das über die **Feld-Box**, nie über die ganze
Platte — außerhalb des Feldes ist der Boden eben und wird von vier Quads
getragen. Ein 100-m-Hügel in einer 1500-m-Welt bleibt damit auf 4 m (29² = 841
Zellen), statt auf 8 m vergröbert zu werden, um 35 000 leere Zellen zu bezahlen.
Platte und Flächen teilen sich die eine Zahl (eine gröbere Fläche würde in den
Hügel einsinken).

Zwei Folgen, die keine Geometrie sind: **Nebel-Quads** werden auf ~64 m
gekachelt (`FOG_TILE_M`) und hängen je Kachel auf `max(Höhe darin) + 5 cm` —
ohne Kachelung hebt EIN Hügel ein weltbreites Band fünfzig Meter in die Luft;
verraten wird dadurch nichts, weil das Gelände ohnehin nie gefoggt ist und die
Topographie schon zeigt. **Gekachelt wird nur, wo das Gelände sich bewegt**
(E8 Task 5): ein Schleier-Rechteck, unter dem die Spannweite des Bodens unter
`FOG_FLAT_EPS_M` = 0,25 m bleibt, bleibt EIN Quad. Eine Welt ohne Relief kostet
damit exakt so viele Draw Calls wie vor E8 (gemessen: 744 bei 100 bekannten
Orten; alles kacheln wären 3 659, mit drei Hügeln sind es 1 899). Und
**Boden-Raycasts** starten bei
`max(Feldhöhe) + 5 m` statt bei fixen 20 m — die ±50-m-Klemme oben ist genau
deshalb notiert.

### A16.1 Die Planierung unter Fußabdrücken (Plateau) — E8 Task 4, **opt-in seit 2026-08-13**

**Die Planierung ist eine Option pro Ort, Default AUS.** Das Feld
`level_ground` (Top-Level am Ort, fehlend = `false`, im Karten-Editor die
Checkbox „Flatten terrain") entscheidet, ob ein Ort den Boden unter sich
ebnet. Ohne das Flag ändert ein Ort das Höhenfeld überhaupt nicht: die
autorierte Landschaft läuft durch ihn hindurch, Figuren folgen ihr auch IM
Ort. Der Entscheid des Users im Wortlaut: „Orte werden bewusst gebaut. Die
Landschaft sollte den Ort nicht beachten. Vielleicht will man sogar einen
Anstieg im Ort."

**Die AUTORIERUNGS-FOLGE, offen benannt und akzeptiert:** ein Ort OHNE Flag
auf starkem Hang steckt sichtbar teils im Berg und schwebt teils, und er kann
am Steilheits-Gate (§ A15 Nr. 8) unbetretbar werden — für den Router genauso
wie für einen Avatar, denn beide beurteilen jetzt denselben durchlaufenden
Boden. Das ist keine Panne, sondern die Kehrseite der Wahl: wer die ebene
Baufläche will, setzt das Flag. Es gibt **keine Migration** — bestehende Welten
verlieren beim nächsten Rastern ihre automatischen Plateaus.

**Das Flag gehört der PLATZIERUNG, nie dem Template.** Ein Klon erbt es
deshalb nicht (`_resolve_clones` setzt es aus dem Klon selbst): dieselbe
Vorlage kann einmal auf ebener Wiese und einmal am Hang stehen.

**Wo geflaggt ist, gilt unverändert alles Folgende.** Ein Ort wird AUF die
Welt gesetzt, und der Boden darunter wird dafür geebnet: nach der reinen
Flächen-Rasterung läuft ein zweiter Durchgang, in dem jeder GEFLAGGTE
platzierte Fußabdruck auf die autorierte Höhe an seinem EIGENEN
MITTELPUNKT gepinnt wird — `ground_y(pos_x, pos_z)`, gelesen VOR jeder Planierung,
damit zwei benachbarte Orte nicht davon abhängen, wen die DB zuerst
zurückgab. Ohne das schneidet der Boden eines Ortes am Hang auf der einen
Seite durch den Hügel und schwebt auf der anderen, und die Geh-Regel (§ A15
Nr. 8) lehnt jeden Schritt über diese Naht ab.

**Gepinnt wird der Fußabdruck DILATIERT UM EINE ZELLE** — dasselbe Muster,
mit dem das Szenen-Relief seine flachen Räume pinnt
(`scatter_curves.terrain_grid`, `flat_hulls`), und aus demselben Grund: ohne
den Ring interpolieren die Randzellen die Außenhöhen wieder HINEIN, und der
Boden steigt am eigenen Rand durch den Ort. Mit dem Ring hat jede Zelle, die
den Fußabdruck berührt, vier gepinnte Ecken — das Plateau ist über den ganzen
Ort exakt eben —, und **die Rampe ist die eine Zelle** zwischen Ring und
unangetasteter Landschaft.

**Überlappung: der KLEINSTE Fußabdruck gewinnt**, dieselbe Auflösung, die
`location_at_point` und `relief.ground_lift_at` für Verschachtelung
benutzen (die Hütte auf dem Dorfplatz ist die speziellere Antwort). Umgesetzt
als „der breiteste zuerst", damit der schmalste zuletzt schreibt.

**Das Gitter WÄCHST dafür.** Ein GEFLAGGTER Fußabdruck, der über die bemalte
Box hinausragt, zieht seine Box plus einen Schritt in die Gitter-Grenzen — sonst
würde das Plateau am Rand abgeschnitten und träfe draußen (wo der Randwert
gilt) als Klippe auf die flache Welt. Fußabdrücke, die keine autorierte Höhe
berühren können, bleiben draußen: dort ist alles 0, und eine ferne Hütte darf
das Gitter nicht über die halbe Welt spannen. Eine Welt ohne eine einzige
Höhenfläche behält deshalb ihr leeres Gitter, egal wie viele Orte darauf
stehen. Ein ungeflaggter Ort braucht keine Gitter-Deckung, weil er nichts
hineinschreibt.

**`height_sig` deckt seit Task 4 auch die PLATZIERUNGEN** — seit 2026-08-13
genau die der planierenden Orte. Verschieben,
Drehen, Größe ändern, Setzen und Löschen einer solchen Location bewegen ihr
Plateau und damit das Relief — ohne dass eine Höhenfläche angefasst wurde, und
das SETZEN oder LÖSCHEN des Flags tut es ebenfalls, ohne dass sich der Ort
einen Zentimeter bewegt (er tritt in die gehashte Liste ein oder aus). Clients
holen das Feld also auch dann neu, wenn nur ein Ort umgezogen ist; der
Schreibpfad (`world._save_world_data`) vergleicht die Signatur und rastert
neu, wenn sie sich geändert hat.

**Die AUTORIERUNGS-GRENZE, klar benannt** (sie betrifft nur geflaggte Orte —
ohne Planierung gibt es keine Rampe, sondern nur den durchlaufenden Hang):
die Rampe ist EINE Zelle breit — und eine Zelle ist der Schritt des Rasters,
auf dem planiert wird, auf einer Kachel also `TILE_STEP_M` = 2 m —,
also trägt sie `tan(max_slope_deg) · tile_step_m` = **1,68 m** bei den
Vorgaben (bis 2026-08-14, als die Kacheln noch bei 4 m standen: 3,36 m).
Steht ein Ort mehr als das über oder unter dem Boden an seinem Rand, bleibt
ein Rand, den niemand überschreitet — eine Zelle AUSSERHALB des Fußabdrucks
und damit außer Reichweite der 1,5-m-Öffnungs-Ausnahme. Am Ort selbst ist das
kein Problem: der gepinnte Ring reicht eine Zelle über den Fußabdruck hinaus,
die Öffnung liegt also auf ebenem Grund und das Betreten ist frei. Wer den
Ort auf einem echten Steilhang platziert, baut sich eine Mauer — der
Höhen-Editor nennt dieselbe Zahl, und zwar **gerechnet aus `tile_step_m`**
(`GET /world/height-areas` trägt es mit): eine im Client hartkodierte 3,36
hätte nach der Halbierung weiter den doppelten Anstieg versprochen.

**Der Client hängt seine ganze Kachel daran** (`scene/tiles.footprintCentre`):
die Kachel steht auf `y = ground_y(pos_x, pos_z)` — unverändert und ohne
Client-Änderung auch bei ungeflaggten Orten, nur ist der Boden dort eben nicht
mehr eben, die Kachel steckt also sichtbar im Hang. Und weil die
Kachel-Gruppe Position UND Drehung trägt, klettert alles darin — Platte,
Hülle, Räume, das kachel-lokale Szenen-Payload — gemeinsam den Hügel hinauf.
Kein Payload-Feld ändert sich dafür (§ A1.2 gilt: kein y im Payload). Zwei
Folgen im Client, beide Pflicht: die Dach-Grenze `walk_y_world` misst
RELATIV zur Kachel (sie ist ein Szenen-Meter, der Strahl-Treffer ein
Welt-Meter), und eine Kachel wird neu gebaut, wenn sich ihre Plateauhöhe
ändert — die Szene verankert Türschwellen und Raummitten als Weltpunkte.

**Das NPC-Routing zieht mit** (`nav_grid`, siehe § A15): eine Zelle, deren
Boden steiler steht als `max_slope_deg`, ist blockiert — ausgenommen Zellen
in einem PLANIERENDEN Fußabdruck (dort ist das Feld eben) und an einer
Öffnung; in einem ungeflaggten Ort misst der Router den durchlaufenden Hang
wie draußen. Jeder Höhenmeter
kostet zusätzlich `SLOPE_COST_S_PER_M` = 4 Spielsekunden — eine STRAFE, nie
ein Bonus, sonst überschätzt die A*-Heuristik und die Route ist nicht mehr
optimal. Die Strafe steckt auch in `segment_costs`, also erbt die Reisezeit
den Berg, und die Linien-Glättung kann den Umweg um einen Hang nicht mehr
wegziehen.

### A16.2 Das Mikro-Relief der Terrain-Arten — neu 2026-08-13

**Eine Terrain-ART kann Hügel tragen.** Zwei whitelistete Katalog-Felder je
Art (`meta.relief_amplitude_m`, `meta.relief_wave_m`, Editor: „Relief
amplitude/wavelength") erzeugen zufällige kleine Hügel überall dort, wo diese
Art gemalt ist — der Wunsch des Users im Wortlaut: „nur um zufällige kleine
Hügel zu erzeugen, damit die Welt nicht flach wirkt".

**Eingebacken, nicht gerendert.** Das Relief landet im Welt-Höhenfeld (§ A16)
und damit im EINEN `heights`-Array, das Server-Gate, Client-Spiegel und beide
Renderer lesen. Es gibt bewusst **keinen TS-Zwilling**: der Client bleibt
Sampler, sonst hätten Laufregel und Bild zwei verschiedene Böden.

**Die Formel** — Wert-Rauschen auf einem Gitter der Kantenlänge `wave_m`, das
wie das Höhengitter selbst am **Welt-Ursprung** verankert ist:

```
seed(art)  = FNV-1a 32 über den ART-NAMEN (es gibt KEIN Seed-Feld):
             h = 2166136261; je UTF-8-Byte b:  h = ((h XOR b)·16777619) mod 2^32
rnd(u, v)  = XorShift32((seed + u·73856093 + v·19349663) mod 2^32).next01()·2 − 1
u, v       = floor(x/wave), floor(z/wave);   tx, tz = die Nachkommateile
h_relief   = bilinear(rnd über die vier Ecken) · relief_amplitude_m
```

Es sind exakt die Konstanten des alten Szenen-Reliefs
(`scatter_curves.terrain_grid`) — **eine Formelfamilie im Repo**. Der Seed ist
ein Hash des NAMENS, weil ein gespeicherter Seed durch jede Katalog-Änderung,
jeden Export und jeden Klon mitgeschleppt werden müsste, nur um den Boden
stillzuhalten. Negative Ecken sind sauber definiert (`& 0xFFFFFFFF` = die
vorzeichenlose 32-Bit-Lesung), zwei Flächen derselben Art setzen sich also
nahtlos fort.

**Klemmen.** `relief_amplitude_m` 0,05..2,0 m (2 Dezimalen; fehlend oder 0 =
kein Relief, der Schlüssel verschwindet). Die Obergrenze ist eine
**Begehbarkeits**-Grenze: zwei Nachbar-Stützpunkte können sich um höchstens
2·Amplitude über einen Gitterschritt unterscheiden, auf dem Kachel-Raster, das
die Regeln lesen, also `atan(2·2,0/2,0)` = **63°** im Maximum (45°, solange
dieser Schritt 4 m war) — die Zahl, die der Editor-Hinweis nennt. Es ist ein
theoretischer Worst Case: er verlangt zwei benachbarte Rausch-Ecken auf ±1.
Die Obergrenze bleibt bei 2,0 m (Entscheid 2026-08-14), aber der Editor
**warnt** ab `tile_step_m · tan(max_slope_deg) / 2` (0,84 m bei den Vorgaben),
also sobald dieser Worst Case die Laufsperre überschreitet — beide Zahlen
kommen vom Server (`heightMath.reliefWarnAmpM`), geklemmt wird nichts.
`relief_wave_m` **4**..200 m, fehlend = **32 m**; die Untergrenze ist
2 × `TILE_STEP_M` (**Nyquist**: eine kürzere Welle kann das Gitter nicht
tragen, sie würde nur je nach Schrittweite anders aliasen) — sie halbierte
sich am 2026-08-14 mit dem Kachel-Schritt, und **genau dafür** wurde er
halbiert: eine 4-m-Welle ist seither autorierbar, vorher machte der Server
stillschweigend 8 m daraus. Es gibt **keinen Kontur-Fade**: den Übergang trägt
die bilineare Interpolation des Feldes selbst.

**Die Randregel (Abnahme 2026-08-13): am Rand hebt das Relief nur noch.** An
einem Stützpunkt, von dessen vier Gitter-Nachbarn einer KEIN Relief trägt
(flache oberste Art oder unbemalter Grund), wird der Rausch-Beitrag auf
`max(0, Rauschen)` geklemmt — Positives läuft über die Interpolation sanft in
den Nachbarboden aus (das Ufer hebt sich), Negatives endet auf dem autorierten
Niveau. Sonst zog eine Senke im Gras die Naht des Sees mit sich nach unten;
innere Stützpunkte (alle vier Nachbarn relief-tragend) bleiben unverändert
voll.

**Welche Art an einem Punkt gilt**, ist die Regel von `terrain_query.kind_at`
— die OBERSTE gemalte Fläche, die ihn enthält (letzter Treffer gewinnt). Eine
flache Art über einer hügeligen nimmt das Relief also wieder weg. Ein Punkt,
den KEINE Fläche bedeckt, bekommt kein Relief: die unbemalte Welt bleibt eben,
und nur deshalb ist das Gitter überhaupt begrenzbar.

**Durchgangs-Reihenfolge der Rasterung** (jeder Schritt wegen des vorigen):

```
Flächen (stärkste Auslenkung) → Mikro-Relief (ADDITIV) → Planierung (gewinnt)
```

Additiv und NACH den Flächen, weil das Relief eine Variation der autorierten
Landschaft ist und kein Konkurrent — vor dem `|max|`-Vergleich würde es von
jeder Höhenfläche überschrieben. Vor der Planierung, weil ein planierter Ort
auf ebenem Grund steht und nicht auf ebenem Grund plus Rauschen. Der **Null-Ring**
am Gitterrand bleibt unangetastet, ohne Sonderfall: das Gitter reicht immer
einen vollen Schritt über jede bemalte Box hinaus.

**Gitter-Grenzen und Signatur wachsen mit.** Die Basisbox ist ab jetzt
„Höhenflächen ∪ Flächen, deren ART Amplitude > 0 hat" — eine Welt ohne eine
einzige Höhenfläche, aber mit Relief-Gras, bekommt damit ihr erstes Gitter
(Punktbudget und Verdopplung unverändert). `height_sig` hasht zusätzlich genau
das, was der Raster-Pass liest (`heightfield.relief_inputs`): die Polygone der
relief-tragenden Flächen, die flachen Flächen DARÜBER und die beiden
Katalog-Zahlen. **Terrain-Malen ohne relief-tragende Art ändert die Signatur
nicht** — sonst kostete jeder Pinselstrich eine Neu-Rasterung. Die Schreibpfade
`terrain.save_area/delete_area` und `terrain_types.save_world_type/delete_world_type`
rufen dafür `note_world_write()`, das erst vergleicht und nur bei echter
Änderung neu rastert.

**Kosten** (gemessen 2026-08-13, ganze Welt mit einer Relief-Art bemalt, also
der Worst Case): volles Punktbudget 346 × 346 = 119 716 Stützpunkte — 393 ms
ohne, **534 ms mit** Relief-Pass; eine 800-m-Welt (203²) 129 ms → 185 ms. Der
Aufschlag von rund einem Drittel entsteht je zur Hälfte aus „welche Art liegt
oben" und der Rausch-Auswertung; er fällt auf dem SCHREIB-Pfad an, nie beim
Laufen.

**Die 2D-Karten schattieren das Relief** (seit 2026-08-15). Spielerkarte
(`frontend/src/player/MapPanel.tsx`) und Minimap des 3D-Clients
(`client3d/src/hud/Minimap.tsx`) legen dieselbe Schattierung über ihre
Terrain-Farben: `hillshadeImage()` aus `@anima/scene-render` — Normale aus dem
Höhen-Gradienten, Licht aus Nordwest (Azimut 315°, Höhe 45°), neutrales Grau
moduliert, Alpha proportional zur Hangneigung (maximal 0,35; **ebener Grund
schreibt Alpha 0**, eine flache Welt sieht also exakt aus wie zuvor). Beide
rufen mit `MAP_RELIEF_Z_FACTOR` = 3, der kartografischen Überhöhung: die Quelle
ist die **Übersicht** (`GET /play/heightfield`, § A16.3 — ein Leser fragt
entweder Kacheln oder Übersicht, und eine Karte ist die Fernsicht), die bis auf
32 m pro Zelle vergröbert; ohne Überhöhung bleibt ein 5-m-Hügel dort rund eine
von 255 Stufen und damit unsichtbar. Nachgeladen wird **nur bei Wechsel von
`height_sig`**, über den jeweils schon vorhandenen Worldmap-Poll — kein
eigener Poll, kein Regler, kein Server-Code. Die Mathe liegt einmal im
geteilten Paket, die Verbraucher entscheiden nur, wo das fertige Rechteck
landet (ihre eigene Karten-Projektion, `drawImage`/`<image>` mit Glättung);
Zeile 0 des Bildes ist die nördlichste Gitterlinie und landet in beiden
Projektionen oben, ohne Achsen-Spiegelung.

**Was hier NICHT passiert:** der Karten-EDITOR bleibt bewusst ohne Hillshade —
er zeigt Höhenflächen als eigene Ebene mit Zahl-Label
(`frontend/src/tabs/map/HeightLayer.tsx`), weil ein schattiertes Bild eine
zweite, hübschere Antwort auf „wie hoch ist es hier" wäre, die niemand mit der
Zahl vergleichen kann, die die Regeln benutzen.

**Verifikation:** `scripts/smoke_heightfield.py` (Rasterung, Rampe,
Überlappung inkl. Senke, Sanitizer-Klemmen, Signatur/Store/`ground_y`, die
Ursprungs-Verankerung, das Vergröbern, die Routen und Abschnitt [11] die
Planierung: das Opt-in-Flag in BEIDEN Zuständen samt roter Gegenprobe mit dem
ungefilterten `placed_footprints`, Plateauhöhe, Dilatationsring,
Rampen-Handrechnung, wanderndes Plateau samt Signaturwechsel; Abschnitt [13]
das Mikro-Relief: Seed und ein Stützpunkt von Hand — xorshift32 Schritt für
Schritt —, negative Lattice-Indizes samt Wrap, Determinismus, Null-Ring,
oberste Art gegen `kind_at`, Signatur-Verhalten in allen vier Fällen,
Reader-Klemmen und die rote Gegenprobe mit vertauschten Durchgängen), der
Sanitizer der beiden Katalog-Felder in `scripts/smoke_terrain_types.py` [9],
plus die `.mjs`-Tabelle des geteilten Samplers
(`client3d/scripts/smoke_world_height.mjs`, Abschnitt [4] die kombinierte
Höhenquelle des Client-Spiegels), die handgerechnete Schattierungs-Tabelle
(`client3d/scripts/smoke_hillshade.mjs` — Lampe, Rampen, Gipfel, Überhöhung
[dreifach überhöht gezeichnet: aus dieser Ebene liest NIEMAND eine Neigung ab]
und die roten Gegenproben gegen vertauschte Achse und gespiegelten
Gradienten) und die Gitter-/Drape-Mathe in
`client3d/scripts/smoke_relief_math.mjs` (Zellweite, Platte, Flächenschnitt
inkl. Naht-Gegenprobe, Kontur-Zelle gegen die gemessene Plattenfläche,
Nebelhöhe, Reisenden-Höhe, Linien-Verdichtung). Regel und Routing:
`scripts/smoke_slope_gate.py` [6] und `scripts/smoke_nav_grid.py` [13]/[14].

### A16.3 Das Kachel-Höhenfeld — `GET /play/heightfield/tiles` — neu 2026-08-14

**Ein Gitter kann nicht beides sein.** Die Übersicht (§ A16) deckt die ganze
Welt ab und wird deshalb vergröbert, sobald jemand weit draußen malt — live
gemessen 4 m → 32 m. Auf 32 m ist der Boden, gegen den ein Läufer beurteilt
wird, nicht mehr der Boden, den jemand autoriert hat. Also gibt es ab v2 **zwei
Raster derselben Landschaft**:

- die **Übersicht** — ein Gitter über alles, vergröberbar. Ein BILD für die
  Ferne, sonst nichts.
- die **Kacheln** — 256-m-Quadrate im immer feinen **2-m-Schritt** (bis
  2026-08-14: 4 m), auf Anfrage gerechnet. Alles, was der Boden ENTSCHEIDET
  (Laufregel, Routing, jede Serverregel) liest diese, und der Nahbereich der
  Renderer auch.

**Warum 2 m und nicht 4** (User-Entscheidung 2026-08-14): die autorierbare
Wellenlänge des Mikro-Reliefs ist auf 2 × den Kachel-Schritt geklemmt
(§ A16.2, Nyquist), bei 4 m also auf 8 m. Wer 4 m tippte, bekam 8 m — ohne
dass es irgendwo stand. Der halbierte Schritt macht 4-m-Wellen autorierbar;
er kostet die vierfache Punktzahl je Kachel und halbiert die Rampe eines
planierenden Ortes (§ A16.1, 3,36 m → 1,68 m). Die **Übersicht bleibt bei
4 m**: sie ist ein Fernbild, und niemand liest sie als Regel.

**Kachelmaß 256 m, Anker ist der Welt-Ursprung.** Kachel `(tx, tz)` deckt
`[tx·256, (tx+1)·256] × [tz·256, (tz+1)·256]` ab, ihre Stützpunkte SIND globale
Gitterpunkte (`tile_key(x, z) = (floor(x/256), floor(z/256))`; ein Punkt auf
einer Naht gehört zur Kachel im Osten/Süden — beide tragen ihn mit demselben
Wert). 256 ist ein Vielfaches von 2, das ist die ganze Anforderung: eine Kachel
ist ein FENSTER des einen Weltgitters, kein eigenes Gitter. Auch die Übersicht
bleibt gitter-kongruent, weil 4 ein Vielfaches von 2 ist: jeder
Übersichts-Stützpunkt IST ein Kachel-Stützpunkt.

**129 × 129 Punkte — die Ränder gehören dazu, in BEIDEN Nachbarn.** Die
Duplizierung der Randpunkte ist Absicht und kostet 1,57 % Daten (129²/128²
Punkte; die 0,78 % je Achse fallen auf beiden an): bilineares Sampling
INNERHALB einer Kachel braucht damit nie einen Punkt der Nachbarkachel (ein
Client darf jede beliebige Teilmenge halten), und weil beide Seiten denselben
Punkt tragen, ist der Boden über die Naht **stetig** statt nur beinahe.

**Payload von `GET /play/heightfield`** — der Index reist mit der Übersicht
(Felder `tile_m`, `tile_step_m`, `tiles`, siehe § A16). Ein Client hat damit
ohne Zusatz-Runde die Aussage „hier KANN Boden sein, überall sonst ist die Welt
flach".

**Payload von `GET /play/heightfield/tiles?keys=tx:tz,tx:tz`** (Auth wie
`/play/terrain`: eingeloggter User, **nie gefoggt**):

```jsonc
{ "sig": "4400406961",      // DIE eine height_sig, global
  "tile_m": 256.0,
  "step_m": 2.0,
  "tiles": {
    "1,0": { "origin_x": 256.0, "origin_z": 0.0,
             "rows": 129, "cols": 129, "heights": [[…], …] }
  } }
```

| Feld | Typ | Bedeutung |
|---|---|---|
| `sig` | `str` (10) | Identisch mit `worldmap.height_sig` und mit dem `sig` der Übersicht — es gibt **eine** Signatur. Ändert sie sich, verwirft der Client Index UND alle geladenen Kacheln |
| `tile_m` | `float` | Kantenlänge einer Kachel in Metern (256,0). Der Client **hartkodiert sie nicht**, er rechnet seine Schlüssel damit |
| `step_m` | `float` | Abstand zweier Stützpunkte, **immer** 2,0 — Kacheln werden nie vergröbert |
| `tiles` | `{ "tx,tz": Kachel }` | Nur die Kacheln, die es gibt (siehe unten). Ein leeres Objekt ist eine gültige Antwort |
| `tiles[k].origin_x/_z` | `float` | Weltmeter von `heights[0][0]` — exakt `tx·256` / `tz·256` |
| `tiles[k].rows/cols` | `int` | 129 × 129, Ränder inklusive |
| `tiles[k].heights` | `[[float, …], …]` | `heights[j][i]` = Höhe bei `(origin_x + i·2, origin_z + j·2)`, dieselbe bilineare Leseregel wie die Übersicht (§ A16). Eine Kachel trägt **kein eigenes** `step_m`: alle im Batch haben dasselbe, und es steht oben |

**Zwei Schreibweisen desselben Schlüssels, absichtlich verschieden.** In der
QUERY trennt `:` innerhalb eines Schlüssels und `,` zwischen den Schlüsseln
(`keys=0:0,1:0,-1:2`); im PAYLOAD heißt die Kachel `"tx,tz"` (`"1,0"`), weil
dort kein Trennzeichen zweiter Ordnung gebraucht wird. Negative Indizes sind
gewöhnliche Kacheln.

**Der Batch ist auf 64 Schlüssel gekappt** (`TILE_BATCH_MAX`) — 4 km² feiner
Boden, mehr als der Laderadius je auf einmal will (der Client fragt sein
Want-Set, rund 28 Kacheln). Bei 129² Punkten sind das rund 100 KB je Kachel
und damit 6…8 MB für einen vollen 64er-Batch; das Kap bleibt trotzdem, weil
der Client ohnehin nie so viel auf einmal will. Duplikate fallen auf ihre
ERSTE Position zusammen, und **die Kappung greift NACH dem Entdoppeln**, ein
wiederholter Schlüssel verdrängt also keinen anderen. Unlesbare Tokens
(fehlender Doppelpunkt, keine ganze Zahl) werden **übersprungen**, nicht als
Fehler beantwortet — die genannten Kacheln sind ja trotzdem der fehlende Boden.
Beides, Junk-Tokens UND die über dem Kap abgeschnittenen Schlüssel, wird
**je einmal** im Log gesagt (Muster `backdrop.py`, ein Kanal pro Fall): eine
verworfene Kachel sieht auf der Client-Seite aus wie flacher Boden, das Log ist
also die einzige Stelle, an der sie noch auffallen kann.

**Nicht indizierte Kacheln fehlen einfach in der Antwort** — kein Fehler, kein
Null-Gitter. Der Index hat dem Client schon gesagt, dass dort die flache Welt
ist, und eine fehlende Kachel ist genau diese Aussage; sie kostet damit weder
Rasterung noch Kilobytes. Deshalb ist der Endpunkt auch mit veraltetem Index
gefahrlos: die Antwort ist kleiner als die Frage.

**Der Sampler-Vorrang (bindend, für JEDEN Leser): fein > Übersicht > 0.**

```
h(x, z) = Kachel, die (x,z) enthält, sofern geladen   → bilinear aus ihr
          sonst die Übersicht, sofern sie den Punkt trägt → bilinear aus ihr
          sonst 0                                       (die flache Welt)
```

Serverseitig ist das `heightfield.world_height` (Kachel oder 0 — der Server
liest die Übersicht überhaupt nicht mehr), clientseitig
`@anima/scene-render` (`sampleCompositeHeight`), damit beide Renderer dieselbe
Reihenfolge anwenden.

**Die Gleichheitsgarantie.** Kachel und Übersicht kommen aus DEMSELBEN
Auswertungskern über DASSELBE ursprungsverankerte Gitter. Rastert man die
Übersicht **auf dem Kachel-Schritt**, trägt sie an jedem gemeinsamen
Stützpunkt exakt die Zahl der Kachel — Punkt für Punkt gemessen in
`scripts/smoke_heightfield.py`, Abschnitt [14], der den Schritt dafür auf 2 m
zwingt („alle Stützpunkte der Übersicht tragen die Zahl der Kacheln", dazu die
Naht-Prüfungen und Zwischenpunkte auf beiden Nähten).

**Bei ihrem eigenen Schritt laufen die beiden auseinander — aus ZWEI
Gründen**, und der zweite ist der unauffällige. Seit dem 2026-08-14 gilt das
schon bei der UNVERGRÖBERTEN Übersicht (4 m gegen 2 m), vorher erst ab der
ersten Verdopplung:

1. **Die Auflösung selbst.** Schon bei 4 m fehlt jeder zweite Stützpunkt je
   Achse — eine 4-m-Welle hat dort nur noch einen je Wellenzelle —, und bei
   32 m fehlen 15 von 16; ein 22-m-Hügel hat gar keinen mehr (Nyquist,
   § A16.2) und existiert in der Übersicht nicht.
2. **Die Planierung planiert mit IHREM Schritt.** Der Rampenring um einen
   Fußabdruck (§ A16.1) ist „eine Zelle breit" — in der Übersicht bei 32 m also
   **32 m breit**, bei 4 m eben 4 m, in der Kachel immer 2 m. Ein planierter Ort
   hat in den beiden Rastern damit unterschiedlich weit ausgreifende Plateaus
   UND unterschiedliche Plateauhöhen (die Höhe wird auf dem eigenen Gitter am
   Mittelpunkt gelesen), auch dort, wo die Auflösung allein noch nichts
   erklären würde. Das ist der Preis der Entscheidung und kein Fehler: die
   Naht zwischen beiden liegt konstruktionsbedingt hinter dem Nebelband
   (siehe unten), und keine REGEL liest die Übersicht.

**Regel daraus: die beiden nie mischen.** Ein Leser fragt ENTWEDER die Kacheln
ODER die Übersicht — nie den einen Wert hier und den anderen einen Meter
weiter. Wer aus Kachel-Boden auf Übersichts-Boden umschaltet, tut das an einer
Kante, nicht in einer Mischzone.

**Und wo diese Kante liegt: im Nebel.** Der Client hält die indizierten Kacheln
im Radius **560 m** um seinen Anker (Avatar-Position, unverkörpert das
Kamera-Bodenziel), der Szenennebel endet bei **520 m** (`THREE.Fog(220, 520)`,
`engine.ts`). Die Naht zwischen feinem und grobem Boden liegt damit
konstruktionsbedingt hinter dem Nebelband. Sie wird **nicht extra kaschiert** —
das ist eine dokumentierte Annahme, keine Auslassung: ein Übergangs-Blend wäre
genau die Mischzone, die die Regel oben verbietet.

**Kosten und Caches.** Eine Kachel rastert in **Millisekunden** (gemessen
**78 ms** für den Worst Case: 8-km-Fläche mit Relief, 129² Punkte,
`smoke_heightfield.py` [14d] — knapp das Vierfache der 20 ms bei 65², also
genau die vierfache Punktzahl) und wird **nicht in der DB gespeichert** — es
gibt einen Prozess-LRU über 512 Kacheln, Schlüssel `(Generation, tx, tz)`, und
der Index ist je Generation gecacht. ACHTUNG bei der Obergrenze: 512 volle
Kacheln sind bei 129² Punkten mehrere hundert MB Python-Floats (bei 65² waren
es rund 70). Persistiert wird weiterhin nur die Übersicht, weil nur sie eine
Drittelsekunde kostet.

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
                             # Metas + Prop-Sidecars der Location ab
  k, storey_m,               # abgeleitete Skalare (Welt-Einheiten)
  levels: [ { level, floor_y } ],
  style: { wall_color, floor_color, glass_color, glass_opacity,
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
               yaw_deg,                    # Eltern-Rotation, +rad im Client
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
  markers: [ { room_id, at_world: [x,z], y_world, animation, facing?,
               source: "room"|"prop" } ],  # ALLE fertig in Welt-Koordinaten

  # --- Türschwellen & Befunde (2026-08-05) ---
  doorways: [ { level, at_world: [x,z], along: [ux,uz], width_m,
                base_y, rooms: [room_id, …], outside } ],
                                           # IMMER da, leer = keine Tür
                                           # base_y = STEH-Höhe der Raumseite
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
  der GROUND-Raum zählt nie mit, er trägt vertraglich kein Layout.
- **`openings_without_walls`** (Diagnose 2026-08-15) — mindestens ein Raum hat
  Öffnungen im Layout, bekommt aber wegen `no_walls` (bzw. Outdoor
  `always_visible`) gar keine Wände: Tür, Fenster, Glas und Schwelle
  entstehen nirgends, während die 2D-Planzeichnung sie weiter zeigt. Ein
  wandloser Raum OHNE Öffnungen ist erlaubt (offene Zone, Pavillon) und
  bleibt still — nur die Kombination meldet sich, einmal pro Location mit
  `room_count` der betroffenen Räume.

**Damit wandern in den Server:** Wand-Splitting um Öffnungen inkl.
Fenster-Brüstung/-Sturz/Glas als eigene `walls`-Einträge, Türlücken der
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
  3. rotation.y = +rad(yaw_deg) als Eltern-Rotation
     ✔ Seit **E4** (2026-08-09, Task 3): verbindlicher Drehsinn ist die
     Weltkarten-Konvention (§ A1.1), das frühere Minus ist in allen
     Renderstellen gekippt (§ A1.8). Der Server liefert `yaw_deg`
     unverändert. `markers[].facing` bleibt unberührt (Kompass, § A1.8),
     ebenso der hergeleitete Wand-Yaw in `primitives.ts`.
  4. Ergebnis-BBox messen → Unterkante = bottom_y, XZ-Zentrum = anchor
```

Ersetzt die früheren drei Spezialketten vollständig (§ A2 führt nur noch
Diorama und Props als Legacy) — Gebäude, Diorama
und Props unterscheiden sich nur noch in den vom SERVER gelieferten
Spec-Werten, nicht im Code. `measure_axes: "xz"` beschränkt die
maxExtent-Messung in Schritt 2 auf die XZ-Achsen.

## B2a. Größenabgleich Diorama ↔ Props ↔ Figuren — EIN Maßstabsgesetz

Befund (2026-07-24): Dioramen skalieren per Rechteck-Einpassung, Props
und Figuren per reale Meter (× k; k = 1 seit E4). Konsistent ist das nur,
solange der Editor das Raum-Rechteck auf `width_m / plan_width_m` hält — zur
Renderzeit erzwingt das niemand; frei gezogene/alte Räume driften, und
seit Dioramen, Props und NPCs im SELBEN Raum stehen, fällt das sofort
auf (Diorama-Sofa ≠ Prop-Stuhl ≠ Figur).

**Neue Regel (v4): Das Diorama skaliert wie ein Prop.**

- `width_m` deklariert → `scale_mode "real_size"`, `max_m = width_m`,
  `measure_axes: "xz"` (width_m ist die größte XZ-Seite; die Höhe folgt
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
  Fahrstuhl. Die Gebäude-Hülle füllt weiterhin das Bezugsquadrat
  (`extent_m × size`) statt eine eigene Realgröße zu tragen.
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
acht sind zu; offen bleibt allein #3.

| # | Befund | Stand |
|---|---|---|
| 1 | Figuren-Basishöhe Client 1,75 m vs. Vertrag 1,70 m | **Historisch, erledigt (E1/E4):** 1,70 m in Welt-Metern gilt überall (§ A1.1/§ A3), das `× k` ist mit E4 weg — und der Client steht auf 1,70 (`client3d/src/scene/figures.ts BASE_FIGURE_HEIGHT_M`, Payload-Default `1.7`) |
| 2 | „0,12 × k" in §2e der Rezept-Note | **Historisch, erledigt:** zurückgezogen — 0,12 Welt-Meter konstant (§ A3) |
| 3 | `activityToClipKind`-Keyword-Heuristik im Client | **OFFEN (E7 nachgeprüft):** die Heuristik lebt (`client3d/src/scene/figures.ts:415`, gerufen in `main.ts` und `npcs.ts`) und greift genau dann, wenn `activity_animation` leer kommt. Fix unverändert: entfernen, sobald jede Aktivität ein Preset trägt |
| 4 | README des Clients nennt `map-icon-2d` als Bodenquelle; `mapIconUrl()` tot | **Erledigt — aber die Diagnose war FALSCH (E7-Korrektur):** `mapIconUrl()` lebt und liefert das Footprint-Icon der Karte (`frontend/src/tabs/map/PlacementLayer.tsx:78`, Konsumenten `MapTab`, `KnownLocationsEditor`, `LocationEditor`). Nichts daran ist Dead Code, `map_image_2d`/`map_rotation_2d` bleiben ausdrücklich (§ A1.9). Weg ist nur die README-Zeile des Clients |
| 5 | `implementierung-3d-pipeline.md` nennt `/characters/{name}/model[/meta]` | **Erledigt:** `client3d/docs/implementierung-3d-pipeline.md:80` sagt heute selbst, dass es diese Routen NICHT gibt, und nennt `GET /characters/{name}/model3d` (JSON) |
| 6 | `placements[].model_url` | **Erledigt:** im Szenen-Payload existiert das Feld nicht mehr (`model_tiers`/`variants` statt dessen, v5-Kopf). `model_url` gibt es nur noch als Feld der Prop-BIBLIOTHEK (`app/core/props.py`) — anderer Namensraum, kein Rest |
| 7 | Diorama-Böden mit Löchern — begehbare Höhe nicht messbar | **Erledigt:** `walk_y` (Meter über Modell-Unterkante) ist Sidecar-Anker mit Admin-Regler; das Rezept rechnet ihn zu `walk_y_world` aus (`app/core/scene_recipe.py`) |
| 8 | Diorama-Maßstab (Rechteck-Fit) ≠ Prop-/Figuren-Maßstab (×k) im selben Raum | **Historisch, erledigt (E4):** § B2a — Diorama skaliert real-size über `width_m` (measure xz), Rechteck-Breite nur noch Fallback; bei `k = 1` sind „real-size" und „Welt-Maßstab" dasselbe |

## Nachtrag 2026-07-27: Eine Wand, ein Besitzer (Kontur vs. Raumhülle)

Wo eine INDOOR-Raumhülle kolinear auf der Gebäudekontur liegt (Toleranz
0,09 m ≈ Wanddicke + Spiel), liefert `/scene` dort KEIN Konturwand-Stück
mehr — die Raumwand besitzt die Strecke (sie trägt Textur und
Öffnungen). Outdoor-Räume lassen die Kontur unberührt. Befund-Anlass:
deckungsgleiche Wände z-fighteten, sobald eine Wand-Textur gesetzt war
(Haus von Kai, 27 Paare / 16,47 m doppelt — jetzt 0/0).
