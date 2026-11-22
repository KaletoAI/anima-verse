# Schnitttexturen Gruppe B — Rock, Kleid, Jacke, Knopfleiste/Kragen, trägerloses Oberteil

> **Für ausführende Agenten:** PFLICHT-Skill superpowers:executing-plans (die Session setzt selbst um, keine
> Subagenten). Schritte als Checkboxen (`- [ ]`).
>
> **Stand 2026-11-21, Basis `main` @ `58550c2b6`.** Nichts ist umgesetzt. Jede offene Frage ist unten als
> **Entscheidung mit Begründung** getroffen (wie zuletzt: „nimm die Empfehlungen“). Skizzen mit ECHTEN Inseln:
> `~/claude-out/schnitt-texturen/gruppe-b-skizzen/` (5 PNG, eine je Art).

**Ziel.** Jede Vorlagen-Art bekommt Schnittteile (Pattern-UV, eine px/cm) und damit die „Textur aus Schnitt“:
`skirt`, `dress`, `jacket` und das trägerlose Oberteil (`top` mit `shoulders` = `strapless`). Dazu Knopfleiste,
Reißverschluss, Schnürung, Knöpfe und Stehkragen als Vorlagen-Parameter für `top`, `dress`, `jacket`, und Schlitze
vorn links/rechts (Kiras Schlitzrock, Ylvas Wickelrock). Danach gibt es keine Gitter-UV (`uv_mode` "grid") mehr.
Die Korsett-Taille (Rosi) ist ein eigener, kleiner, abtrennbarer Teil am Ende.

**Architektur in einem Satz je Weg.**
- Kleid mit Oberteil und Jacke laufen schon durch `build_bodice`, das jede Fläche beim Bauen beschriftet
  (`face_part`): sie brauchen nur neue Beschriftungsregeln (Taillennaht, Vorderkanten, kein Halsbündchen bei V/offen,
  Kragen als Streifen) und `uv_mode` "pattern".
- Rock, trägerloses Kleid und trägerloses Oberteil laufen durch `wrap()` (zwei pygarment-Paneele, Spalten im
  Winkel): sie bekommen die Beschriftung aus dem Paneel-Index, der Reihe (Bund) und der Taillenhöhe, beim Bauen,
  als dieselben bmesh-Int-Layer `uv_part` / `uv_seam` wie ein Oberteil.
- Knopfleiste, Reißverschluss, Schnürung und Knöpfe sind **keine Insel**, sondern eine **Marke** im Schnitt
  (die Mittellinie bzw. die Vorderkanten als Pixel-Polylinie). Der Code malt sie nach dem Farbabgleich in den Atlas.
  Das Modell malt nur Stoff.

---

## 0. Was du jetzt umstellen kannst (und wer es hat)

Ohne neuen Code, in Game-Admin → Characters → Figure → Vorlagen-Dialog:

| Wer | Teil | Umstellen | Kosten | Warum |
|---|---|---|---|---|
| Dario | Worn Linen Shirt | Textur → **From cut** | 0 Jobs, CPU-Zusammenbau | Ein fertiger Atlas liegt seit 21:45 da (MiniMax, Vorder- + Rückjob `ready`). In der Welt steht die Textur auf `projection`. |
| Ylva Nordwind | Laced Linen Blouse | Textur → **From cut** | 0 Jobs | Atlas seit 21:46 `ready` (MiniMax; Rücken schlicht, ohne Job). Zuschnitt geprüft: 4 Inseln, 18,37 px/cm, p95 1,13. |
| Kai | Black Lederjacket (copy) | Front → **closed**, Kragen → **stand** | 1 Neu-Drapierung (CPU, 0 Hub-Jobs) | Das Bild zeigt Reißverschluss und Stehkragen, die Parameter sagen „offen, ohne Kragen“. Mit Phase C wird es sonst falsch geschnitten (zwei Vorderteile statt einem mit Reißverschluss-Linie). |
| Kira | Black Blazer (shared) | Kragen → **lapel** | 1 Neu-Drapierung (CPU) | Das Bild zeigt Revers. Gemessen: Revers-Kragen 28,3 × 5,9 cm, Fläche 1,000. |
| Rosi | Red Corset Top | **nichts** | — | `lift` steht schon auf 1,0 (Push-up). Bild hat Träger, Parameter trägerlos: trägerlos bleiben, der trägerlose Zuschnitt ist sauber (Skizze rechts zeigt den Träger-Zuschnitt mit Sägezahnkante). |
| Tilda Haase | Grey Knit Cardigan | **nichts** | — | `front` open passt (Cardigan offen getragen); die Knopfleiste kommt mit Phase C. |

Nach jeder Phase steht im Abschnitt „Lieferung“ der Phase, was du danach umstellen kannst.

---

## 1. Messbasis (2026-11-21, nur Kopien, 0 Hub-Jobs, kein Server)

Zwei Demos in `/home/dev/.claude/jobs/c956220f/tmp/cutbplan/scr/` (nicht im Repo):
- `run_cut.py`: der echte Blender-Zuschnitt (`garment_template_build`, `cut_only`) auf KOPIEN der Basiskörper, mit
  `uv_mode` = "pattern" im Prozess erzwungen. Kontrolle: Tildas Bluse und Darios Hemd ergeben **byte-gleich** dieselben
  Werte wie die echten Zuschnitte der Welt (18,59 / 13,81 px/cm, dieselben Inseln) — die Demo ist also treu.
- `panels_demo.py`: die `wrap()`-Konstruktion (80 Spalten, Reihen aus `panel_spec`, Radius = Umfang der Reihe / 2π,
  ohne Körper-Abstand) mit den geplanten Teilen, flachgelegt mit dem Repo-`uv_pattern` (numpy).

### 1.1 Was heute schon passt und was bricht (echter Zuschnitt, Oberteil-Regeln)

| Teil (Person) | Inseln heute | px/cm | Fläche | p95 Paneele | Befund |
|---|---|---|---|---|---|
| Shy Red Dress (Vallerie) | front, back, sleeve_l/r, band | 13,59 | 0,997–0,998 | 1,10 | Paneele gut; Halsbündchen p95 1,57 |
| Sheer Moon Ritual Dress (Ylva) | dto. | 11,48 | 0,994–0,998 | 1,14 | Vorderteil 75 × 129 cm (Kleid in einem Stück); **Halsbündchen V: Fläche 1,33, p95 2,94** |
| Emerald Green Dress (Lirien) | — | — | — | — | **Absturz**: `KeyError uv_seam` (Träger + Schlitz: kein einziger markierter Schnitt, die leere Kanten-Ebene geht im `split_slit`-bmesh-Umlauf verloren) |
| Grey Knit Cardigan (Tilda) | front, **front_2**, back, sleeves, **band…band_5** | 14,86 | 0,973–0,997 | 1,22 | offenes V: Halsbündchen in 5 Splitter, p95 bis 1e12 |
| Black Lederjacket (Kai, wie gespeichert: offen) | front, front_2, back, sleeves, band | 14,02 | 0,996–0,999 | 1,12 | Band p95 1,48 |
| Lederjacke mit Stehkragen (Kai, Vorschlag) | front, back, sleeves, band, **collar** | 12,57 | 0,996–0,998 | 1,12 | **Kragen als Ring-Panel flachgelegt: 15,1 × 29,8 cm, p95 1,28** (Kragen 6 hat keine Streifen-Daten) |
| Black Blazer (Kira, wie gespeichert) | front, back, sleeves, band, band_2 | 16,82 | 0,995–0,998 | 1,13 | V 26 cm: Band Fläche 1,52, **p95 4,06** |
| Blazer mit Revers (Vorschlag) | front, front_2, back, sleeves, band, collar | 14,49 | 0,995–0,998 | 1,13 | Revers-Kragen 28,3 × 5,9, p95 1,00; Band 108 cm, p95 4,0 |
| Corset-Top mit Trägern (Rosi, Variante) | front, back | 15,93 | 0,977–0,994 | 1,24 | geht heute; Oberkante zwischen den Trägern sägezahnig |
| (Oberteile, live) Bluse Tilda / Hemd Dario / T-Shirt Kai | … band(_2) | 18,6 / 13,8 / 14,1 | — | ≤ 1,30 | **Halsbündchen schon heute kaputt**: Tilda 2 Teile p95 2,6/3,8, Dario (V) p95 3,2–3,4, Kai 1,53 |

### 1.2 Geplante Teile, gemessen (Demo `panels_demo.py` + `sketch.py`)

| Teil (Person) | Inseln (cm) | Fläche | p95 | px/cm (Layout) |
|---|---|---|---|---|
| Black Slit Skirt (Kira) | Rock vorn 49,2 × 34,0 (Schlitz), hinten 48,8 × 33,9, Bund 63,3 × 3,0 | 0,999 / Bund 0,984 | 1,05 / Bund 1,03 | **26,62** (untereinander; eine Reihe 19,99) |
| Black pencil skirt (Rosi) | 50,4 × 20,4 ×2, Bund 95,5 × 3,1 | 1,000 | 1,02 | 20,78 |
| Moon Silk Skirt (Gelina) | 95,1 × 78,8 ×2, Bund 85,5 × 3,0 | 1,000 | 1,01 | **12,29** (eine Reihe nur 10,51) |
| Leather Wrap Skirt (Ylva) | 49,8 × 66,5 (Schlitz vorn links 46 cm), 51,2 × 66,4, Bund 96,1 × 3,0 | 1,000 | 1,02 | 19,40 |
| Long Brown Wool Skirt (Tilda) | 65,4 × 80,5 ×2, Bund 59,4 × 3,0 | 0,999 | 1,05 | 15,13 |
| Ritual Dress (Ylva), mit Taillennaht | Oberteil vorn ≈ 52,8 × 43,4, hinten ≈ 51,5 × 49,9; Rock vorn 72,9 × 87,6, hinten 73,8 × 87,8; Ärmel | Rock 0,999 | Rock 1,05 | 11,69 (ohne Naht 11,48) |
| Shy Red Dress (Vallerie), mit Naht + Stehkragen | Oberteil ≈ 47,4 × 38,7 / 45,3 × 40,6; Rock 64,3 × 52,4 ×2; Kragen 53,9 × 3,7 | Rock 1,000 | 1,04 | 13,75 |
| Cardigan (Tilda), ohne Band | Vorderteil r 29,4 × 72,4, l 29,2 × 71,7, Rücken 55,4 × 77,6, Ärmel | 0,973–0,997 | 1,22 | 15,69 |
| Lederjacke (Kai) geschlossen + Stehkragen-Streifen | Vorderteil 72,4 × 59,6, Rücken, Ärmel, Kragen 64,2 × 3,7 | 0,996–0,998 | 1,12 | 14,08 |
| Blazer (Kira) Revers, ohne Band | Vorderteile 24,8 / 25,7 × 57, Rücken, Ärmel, Kragen 28,3 × 5,9 | 0,995–0,998 | 1,13 | 16,70 |
| Red Corset Top (Rosi) trägerlos | Vorderteil 51,4 × 31,6 (Herz-Ausschnitt 10 cm), Rücken 50,5 × 31,6 | 0,994–0,995 | 1,16 | 19,24 |

„≈“: das Kleid-Oberteil ist in der Skizze der echte Zuschnitt, an der Taille (Höhe = ganzes Paneel − Rock-Paneel)
abgeschnitten; die Zahlen kommen nach Phase D aus dem echten Lauf. Der Rock ohne Körper-Abstand (Demo) ist eher
etwas zu schmal; die px/cm-Ziele unten haben 5 % Luft.

Zwei Befunde aus der Demo, die der Plan einbaut:
1. **Ein Bund mit mehr als einer Flächenreihe darf nicht durch `strip_island_uv`**: die mittlere Reihe liegt auf keiner
   der zwei Streifen-Zeilen, alle Ecken fallen auf einen Punkt (gemessen Fläche 1,49, p95 1e12). Mit
   `ring_strip_uv` (wie die Bünde der Gruppe A): Fläche 0,984–0,990, p95 1,02–1,03. Dasselbe gilt für den Stehkragen
   (3 Ringe).
2. **Breite Röcke brauchen ein zweites Layout.** Gelina eine Reihe 10,51, untereinander 12,29 px/cm. Kira umgekehrt
   nicht nötig, aber untereinander 26,62 statt 19,99.

---

## 2. Entscheidungen (jede mit Grund)

| # | Frage | Entscheidung | Grund |
|---|---|---|---|
| B1 | Teile des Rocks | `skirt_front`, `skirt_back`, `waistband` (wenn `waistband` ≠ none) | Die zwei pygarment-Paneele SIND Vorder- und Rückenteil; die Seitennähte sind ihre Grenze (heute `remove_doubles`). Gemessen p95 ≤ 1,05. |
| B2 | Rock-Bund | Der Parameter `waistband` (none/thin/wide = 0/1,2/3 cm, besteht schon für Slip/Strumpfhose) kommt in `KIND_FIELDS["skirt"]`, **Standard für Röcke `wide`** (`kind_defaults`). Der Bund ist die oberste(n) Reihe(n) als Ring-Streifen, offen hinten Mitte. | Alle fünf Rock-Bilder zeigen einen Bund. Nur Beschriftung, keine neue Geometrie (die oberste Reihe ist schon gepinnt). |
| B3 | Schlitz vorn links/rechts | `SLIT_SIDES` += `front_left`, `front_right` = 1,5π ± 6 Spalten (6 · π/40 = **0,47124 rad**). Kira (Schlitz 6 cm) und Ylvas Wickelrock (46 cm) bekommen ihn vom Parameter-LLM bzw. von dir. | Beide Bilder zeigen den Schlitz vorn seitlich. Auf einer Spalte, damit `split_slit` (Toleranz eine halbe Spalte) ihn findet. |
| B4 | Wickelrock | Kein eigenes Doppellagen-Teil. Wickelrock = Schlitz `front_left`/`front_right`; die schräge Überlappkante malt das Modell aus dem Bild aufs Vorderteil. | Eine zweite Stofflage auf einer einlagigen Drapierung kollidiert mit sich selbst; das Bild zeigt die Kante, das Modell setzt sie an dieselbe Stelle (Vorder-Job). |
| B5 | Rock-Layout | `pack` probiert die Zeilen der Art UND die Alternative `ROWS_ALT[kind]` (Paneele untereinander) und nimmt die größere px/cm (bei Gleichstand die erste). Für `skirt` und den Rockteil des Kleids. | Gemessen Gelina 10,51 → 12,29, Kira 19,99 → 26,62. Deterministisch, eine Zahl. |
| B6 | Kleid-Taillennaht | Immer: Flächen unter der Reihe, die `outline.waist_y` am nächsten liegt, werden `skirt_front`/`skirt_back`, darüber `front`/`back`. Gilt für Kleid mit Oberteil (`build_bodice`) und trägerloses Kleid (`wrap`). | Ritual Dress und Emerald zeigen die Naht (Ylva bestickt), Vallerie einen Gürtel. Ein Rock-Paneel bekommt eine eigene Insel für Saum-Drucke; px/cm sogar besser (11,48 → 11,69). Abstand Naht ↔ Taille ≤ halbe Reihe (`GRID_M`/2 = 0,75 cm). |
| B7 | Vorderteile offener Jacken | Neue Teile `left_front` (+X, Spalten c < N/4) und `right_front` (c ≥ 3N/4) beim Bauen; kein `front`/`front_2` mehr bei `front_open`. | „front_2“ ist eine Nummer, kein Name. `front_l`/`front_r` sind schon Hosenbeine („left front leg panel“); eindeutige Namen halten `BACK_PARTS`/Prompt-Namen artunabhängig. |
| B8 | Halsbündchen | Für `dress` und `jacket` (und das trägerlose Oberteil) nur bei geschlossener Front, Ausschnitt crew/boat oder scoop ≤ 8 cm, **ohne** Kragen. Sonst gehört der innerste Ring zu Vorder-/Rückenteil. Die Oberteile bleiben vorerst bei ihrer Regel (Phase F). | Gemessen: V/offen/Kragen geben Fläche 1,3–1,5, p95 3–4 bis 1e12. Ein Kragen ist selbst die Einfassung. Die Oberteile byte-gleich halten, bis sie ohnehin neu geschnitten werden (sonst veralten alle ihre Atlanten auf einmal). |
| B9 | Kragen | `collar` (none/stand) gilt künftig auch für `top` und `dress`; `lapel` bleibt Jacke. Stehkragen = Ring-Streifen (`ring_strip_uv`, Achse senkrecht durch den Hals, Schnitt hinten Mitte). Revers-Kragen bleibt flachgelegtes Paneel. | Tilda (Bluse), Vallerie (Kleid), Kai (Jacke) haben Stehkragen. Gemessen: Ring-Panel 15,1 × 29,8 / p95 1,28 → Streifen 64,2 × 3,7, p95 ≈ 1,0. Revers ist offen und kurz: als Panel schon 1,00. Hemdkragen (umgelegt) = Stehkragen in v1; der Umschlag ist Geometrie, kommt später. |
| B10 | Knopfleiste & Co. | Neuer Parameter `placket` (none / buttons / zip / lacing) für `top`, `dress`, `jacket`, und `buttons` (0–12, 0 = automatisch). **Keine Insel** (Teil-ID 7 `placket` bleibt reserviert): der Schnitt liefert eine Marke, der Code malt Leiste, Reißverschluss, Schnürung und Knöpfe nach dem Farbabgleich. `placket` und `buttons` sind `TEXTURE_ONLY`. | Eine Leisten-Insel teilt das Vorderteil in zwei (Prompt-, Gate- und Platzlogik ändern sich, jeder Oberteil-Atlas veraltet). Die Modelle malen Knöpfe unzuverlässig, unsere Prompts verbieten sie sogar („without buttons“). Gemalt sitzen sie genau, 0 Hub-Jobs beim Umschalten (nur `recompose`). |
| B11 | Wo die Marke liegt | Datei neben den Inseln: `templates/cut/{item}_{cut_sig}.marks.json` (und beim Drape `{item}_{tsig}.marks.json`), geschrieben vom selben Blender-Lauf. Nicht in `islands.json`. | Die Inseln eines Oberteils bleiben byte-gleich (kein Oberteil-Atlas veraltet). Ein vorhandener Oberteil-Zuschnitt ohne Marken-Datei wird bei gesetzter Knopfleiste **einmal** mit derselben `cut_sig` neu geschnitten (CPU, Sekunden); `islands.json` muss dabei byte-gleich bleiben, sonst Fehler. |
| B12 | Knopf-Regel | Geschlossen: auf der Mittellinie; offen: auf der Vorderkante von `right_front`, Knopflöcher (Schlitze) auf `left_front`. Kleid: vom Ausschnitt bis zur Taillennaht, sonst bis zum Saum. Automatische Anzahl `n = max(1, round(L / BUTTON_PITCH_CM[kind]))`, Pitch top/dress 7 cm, jacket 10 cm; Durchmesser 1,1 cm (top, dress) / 1,8 cm (jacket); Leistenbreite 3,0 cm (top, dress, Cardigan) / keine Leiste beim Revers. | Bilder: Tilda 7 Knöpfe, Vallerie ~5 am Oberteil, Cardigan 5, Blazer 2. Feste Regel, die Zahl ist überschreibbar. Knopfseite fest: kein Geschlechts-Parameter. |
| B13 | Knopf-Aussehen | Scheibe in Stofffarbe, L* ± 25 (heller Stoff dunkler, dunkler Stoff heller), Rand L* ± 40, zwei Löcher; Reißverschluss 0,8 cm Metallgrau L* 60 mit Zähnchen alle 0,25 cm und Zipper oben; Schnürung: Ösenpaare ± 1,2 cm, Kreuzschnur L* ± 30. Alles nur innerhalb der Insel-Maske, vor dem Anschnitt-Rand. | Deterministisch, kein zweiter Bild-Job. Kontrast-Richtung folgt dem Stoff (Blazer schwarz → hellere Knöpfe sichtbar). |
| B14 | Trägerloses Oberteil (Rosi) | Über `wrap()`: `front`, `back` (die zwei Paneele), keine weiteren Teile; Herz-Ausschnitt bleibt im Vorderteil. `NO_PATTERN_STRAPLESS` entfällt. | Gemessen sauber: 51,4 × 31,6, p95 1,16, 19,24 px/cm. |
| B15 | Korsett-Form (Rosi, Push-up) | Push-up gibt es schon (`outfit_piece.lift`, Rosi steht auf 1,0). Neu und **abtrennbar**: die Korsett-Taille (`cinch`, Phase G), messen zuerst. Der Schnitt hängt nicht davon ab. | Der Wunsch war Korsett/Push-up: Push-up existiert; nur die geschnürte Taille fehlt. Der Zuschnitt (Phase A) braucht sie nicht. |
| B16 | Versionen | Ein art-gebundener Schlüssel `PANEL_VERSION = 1` im `tsig` und im `cut_sig` von `skirt`, `dress`, `jacket` und trägerlosem `top` (wie `FITTED_VERSION`). `TEMPLATE_VERSION` bleibt 10. Flachlegungs-Schlüssel dieser Arten: `UV_PATTERN_SHA` (live). | Nur diese Teile werden einmal neu drapiert (CPU). Kein Oberteil, keine Gruppe-A-Art. |
| B17 | Gitter-UV | Wird gelöscht (`UV_TORSO`/`UV_CAP`/`UV_COLLAR`/`UV_SLEEVE`, `u_of`/`v_rows`, die UV in `wrap()`, `uv_mode` "grid", die 1024-Bake-Größe). | Keine Kompat-Pfade (CLAUDE.md). Nach Phase D ist jede Art Pattern. |
| B18 | Prompts | Eine zweite Prompt-Familie `garment` (drei Dateien, gleiche vier Abschnitte) für alle Arten außer `top`; neue Variablen `hint` (je Art) und `front_count`. `prompt_sha(kind)` = md5 der Familie. Die Oberteil-Dateien bleiben byte-gleich. | Oberteil-Atlanten bleiben gültig. Ein Kleid hat zwei Vorderteil-Inseln (Oberteil + Rock), eine offene Jacke zwei Vorderteile — die kurzen P-H3-Texte sagen sonst „die übrigen Formen schlicht“ und löschen die Rock-Stickerei. Gruppe A (Branch `cuta`) braucht dieselbe Familie: wer zuerst landet, legt sie an, der andere ergänzt nur `hint`-Zeilen. |
| B19 | Hauptteile je Art | Eine Tabelle `CUT_KINDS[kind]` in `garment_cut_texture`: `main = {"front": (...), "back": (...)}` (Vereinigung der Teile, auf der die Gates messen und aus der der Stoff-Patch kommt), `model_parts`, `back_parts`, `hint`, `rows`, `rows_alt`. Rock: main front `skirt_front`; Kleid: `front`+`skirt_front`; offene Jacke: `left_front`+`right_front`. | Ersetzt `MAIN_PART`/`MODEL_PARTS` (heute nur `front`/`back`). Gruppe A trägt ihre Zeilen in dieselbe Tabelle ein. |
| B20 | Rücken-Job | `BACK_PARTS` += `skirt_back`. Ein schlichter Rücken (`PLAIN_BACK_DETAIL` 0,20) bekommt keinen Job, wie bisher. | Schlichte Röcke/Kleider sparen den Rücken-Job (Tilda, Rosi, Kira vermutlich). |
| B21 | Vorder-Platz im Prompt | `front_place` wird `front_places(islands)` über alle Hauptteile; Text „the top left and middle left shapes“, `front_count` steuert Einzahl/Mehrzahl im Template. | Kleid und offene Jacke haben zwei Vorder-Inseln. |
| B22 | Dekoriertes Kleid | `model_parts` des Kleid-Vorderjobs = `front`, `skirt_front`, `collar` (+ Ärmel mit `sleeve_print` picture). | Ylvas Stickerei sitzt auf Oberteil UND Rock; sonst füllt `fill_fabric` den Rock schlicht. |
| B23 | Strap-Kleid-Absturz | `pattern_uv_of` liest `uv_seam` nur, wenn die Ebene existiert; fehlt sie, gibt es keinen markierten Schnitt. `split_slit` überträgt die Ebene trotzdem. | Gemessen: Lirien stürzt heute ab (Träger + Schlitz, kein markierter Schnitt). Beide Stellen, weil Blender eine leere Int-Ebene beim Umlauf fallen lässt. |
| B24 | Mindestwerte (Abnahme) | Paneele: Fläche 0,97–1,03; p95 ≤ 1,25 Rock-/Rockteil-Paneele, ≤ 1,30 Oberteil-/Jacken-Paneele; Streifen (Bund, Kragen) p95 ≤ 1,10 (neu geprüft, weil jetzt Ring-Streifen); kein Splitter; px/cm ≥ 0,95 × Skizzenwert und ≥ 11,0. | Gemessene Werte mit 5 % Luft; 1,30 weil die echte Bluse Tildas schon 1,28–1,30 hat. |

---

## 3. Teile (`uv_pattern.PARTS`)

1–36 unverändert (Oberteil + Gruppe A). Neu:

| id | Name | UV | Arten | Job | Prompt-Name | Label |
|---|---|---|---|---|---|---|
| 37 | `skirt_front` | Paneel | skirt, dress | front | "front skirt panel" | "Skirt front" |
| 38 | `skirt_back` | Paneel | skirt, dress | **back** | "back skirt panel" | "Skirt back" |
| 39 | `left_front` | Paneel | jacket (offen/Revers) | front | "left front panel" | "Front left" |
| 40 | `right_front` | Paneel | jacket (offen/Revers) | front | "right front panel" | "Front right" |
| 14 | `waistband` | Ring-Streifen | skirt (neu) | front | "waistband" | "Waistband" |
| 6 | `collar` | Stehkragen: Ring-Streifen; Revers: Paneel | top, dress (neu), jacket | front | "collar" | "Collar" |

`STRIP_PARTS` bleibt die Menge; neu ist nur, dass `collar` (6) beim Stehkragen über `rings` statt `strips` läuft.

Zeilen (`uv_pattern.ROWS` / neu `ROWS_ALT`):
- `skirt`: (`skirt_front`, `skirt_back`), (`waistband`); alt: (`skirt_front`), (`skirt_back`), (`waistband`).
- `dress`: (`front`, `back`), (`skirt_front`, `skirt_back`), (`sleeve_r`, `sleeve_l`, `collar`, `band`);
  alt: (`front`, `back`, `sleeve_r`, `sleeve_l`), (`skirt_front`, `skirt_back`), (`collar`, `band`).
- `jacket`: (`right_front`, `front`, `left_front`, `back`), (`sleeve_r`, `sleeve_l`), (`collar`, `band`).
- `strapless`: (`front`, `back`) — Schlüssel `"strapless"` für ein trägerloses `top`/`dress` ohne Rockteil.

Marken-Datei (`marks.json`, Pixel im Atlas-Rahmen wie `islands.json`):
`{"version": 1, "atlas_px", "px_per_cm", "lines": {"centre_front": {"island": "front", "px": [[x, y], …]},
"edge_left": {"island": "left_front", "px": …}, "edge_right": {"island": "right_front", "px": …}}}` — die Mittellinie
(Spalte 0) vom Ausschnitt bis zum Saum (Kleid: bis zur Taillennaht), die Vorderkanten (Spalte 0 / N) einer offenen
Front. Oben zuerst.

---

## 4. Koordination mit Gruppe A (Branch `cuta`)

Gruppe A schaltet ihre fünf Arten frei (`texture` in `KIND_FIELDS`, `FITTED_VERSION` 1, Hauptteile, Prompts). Beide
Gruppen brauchen dieselbe Infrastruktur. Regel: **Phase 0 landet einmal**. Liegt sie schon auf `main` (von `cuta`),
prüft Phase 0 nur und trägt die Gruppe-B-Zeilen ein. Gemeinsam sind: `CUT_KINDS`, die Prompt-Familie `garment`,
`prompt_sha(kind)`, `texture` in `KIND_FIELDS` für jede `PATTERN_KINDS`-Art, `e2e_cut_texture.py` für jede Art.

---

## 5. Reihenfolge

Meistgenutzte Art zuerst (Welt: 5 Röcke, 3 Jacken, 3 Kleider, 3 Oberteile mit Leiste/Kragen, 1 trägerloses Top):

| Phase | Inhalt | Lieferung (was du danach umstellen kannst) |
|---|---|---|
| 0 | Gemeinsame Infrastruktur (`CUT_KINDS`, Prompt-Familie, `prompt_sha(kind)`, e2e für jede Art, Strap-Absturz B23) | nichts Sichtbares |
| A | Rock (+ trägerloses Oberteil, gleicher `wrap`-Weg) | Tilda, Kira, Rosi, Gelina, Ylva: Rock → From cut; Kira + Ylva: Schlitz → `front_left`; Rosi: Korsett → From cut |
| B | — (in A enthalten: trägerloses Oberteil A6) | |
| C | Jacke: Vorderkanten, Band-Regel, Stehkragen-Streifen, Marken + gemalte Leiste/Reißverschluss/Knöpfe | Tilda Cardigan, Kai Lederjacke, Kira Blazer → From cut; `placket`/`buttons` |
| D | Kleid: Taillennaht, Kragen für Kleid, Leiste bis Taille, dekoriertes Kleid | Vallerie, Ylva, Lirien → From cut; Vallerie: Kragen stand + Leiste buttons |
| E | Oberteil: Kragen + Leiste (Marken-Datei für vorhandene Zuschnitte) | Tilda Bluse: Kragen stand + 7 Knöpfe; Dario Worn Shirt: Leiste lacing; Dario Embroidered: Leiste buttons |
| F | Oberteil-Halsbündchen nach Regel B8 (bricht Oberteil-Inseln: zusammen mit E einmal) | — |
| G | Korsett-Taille `cinch` (abtrennbar, messen zuerst) | Rosi: cinch |

E und F gehen in EINEM Release, damit jedes Oberteil höchstens einmal neu texturiert werden muss.

---

## Phase 0 — Gemeinsame Infrastruktur

### Task 0.1: Ledger und Ausgangslage
- [ ] Ledger `.superpowers/sdd/2026-11-22-schnitt-gruppe-b/progress.md`: BASE-Hash, die Entscheidungen B1–B24, ob
  Phase 0 schon von `cuta` gelandet ist.
- [ ] Ausgangs-Smokes, rote vorher notieren: `smoke_uv_pattern.py`, `smoke_garment_template.py`,
  `smoke_garment_cut_texture.py`, `smoke_cut_texture_post.py`, `smoke_cut_texture_dialects.py`,
  `smoke_cut_texture_plain_back.py`, `smoke_template_cut_first.py`, `smoke_docs_garment_templates.py`,
  `smoke_i18n_orphans.py`, `smoke_imports_resolve.py`.

### Task 0.2: `CUT_KINDS` — Hauptteile, Modellteile, Rückenteile je Art
**Dateien:** `app/core/garment_cut_texture.py`, `scripts/smoke_garment_cut_texture.py`.
```python
@dataclass(frozen=True)
class CutKind:
    main: dict[str, tuple[str, ...]]     # job -> parts whose union the gates measure and the fabric patch comes from
    model: dict[str, tuple[str, ...]]    # job -> parts taken from the model's answer (the rest: fabric fill)
    hint: str = ""                       # the kind's sentence for picture_subject / image_tag
CUT_KINDS: dict[str, CutKind]           # "top", "skirt", "dress", "jacket", "strapless" (+ Gruppe A)
def cut_kind(islands: dict, params: dict) -> CutKind  # "strapless" for a strapless top/dress
BACK_PARTS = ("back", "back_l", "back_r", "palm_l", "palm_r", "skirt_back")
```
- `MAIN_PART`/`MODEL_PARTS` werden gelöscht; `panel_fabric`, `fill_fabric`, `_post_job`, `model_parts` lesen
  `cut_kind(...)`. `top` = heutiges Verhalten byte-gleich (main front `front`, back `back`; model front `front`,
  `collar`, `placket`).
- [ ] [1] `top`-Payload der Smoke: gleiche Masken, gleiche Füllung wie BASE (Pixel-gleich, BASE-Hash festgehalten).
- [ ] [2] Kleid-Payload (Inseln `front`, `skirt_front`, `back`, `skirt_back`, Ärmel): Vorder-Hauptmaske = Vereinigung
  von `front` + `skirt_front` (Pixelzahl = Summe beider), Rückjob-Inseln = {`back`, `skirt_back`}.
- [ ] [3] Offene Jacke: Vorder-Hauptmaske = `left_front` ∪ `right_front`.
- [ ] Commit `feat(cut-texture): per-kind main / model parts (CUT_KINDS) for every pattern kind`.

### Task 0.3: Prompt-Familie `garment`, `prompt_sha(kind)`, `front_places`
**Dateien:** neu `shared/templates/image/garment_cut_texture_garment_front_plain.md`,
`…_garment_front_decorated.md`, `…_garment_back.md`; `garment_cut_texture.py`; `scripts/smoke_cut_texture_dialects.py`.
- Gleiche vier Abschnitte (`picture_edit`, `picture_subject`, `image_tag`, `ordinal`) wie die Oberteil-Dateien;
  Variablen zusätzlich `hint`, `front_count`. `picture_edit`/`ordinal` bleiben KURZ (Prompt-Test: lange Texte
  erfanden Embleme); nur der dekorierte Text bekommt die Mehrzahl:
  `The {{ front_place }} of {{ ref(1) }} {{ "is" if front_count == 1 else "are" }} the front of the {{ piece }} in
  {{ ref(2) }}, laid flat. Paint {{ "it" if front_count == 1 else "them" }} as that front: same fabric, same print or
  embroidery at the same place. The other shapes get plain fabric only. Outlines, colour and white background stay
  unchanged.`
  `picture_subject`/`image_tag`: Satz `{{ hint }}` hinter der Stückliste (leer = nichts).
- `PROMPT_FAMILIES = {"top": {...3 Dateien...}, "garment": {...}}`, `prompt_family(kind) = "top" if kind == "top"
  and not strapless else "garment"`, `prompt_sha(kind)`; `csig(..., prompt_sha)`.
- `front_places(islands, main_parts) -> (str, int)`: die `_place_words` jeder Hauptteil-Insel in Muster-Reihenfolge,
  ohne Präposition, mit „and“ verbunden, + „shape“/„shapes“: z. B. `("top left and middle left shapes", 2)`.
- Hinweise (`CUT_KINDS[...].hint`):
  - skirt: "The skirt pieces lie waist up: the front skirt panel as seen from the front, the back skirt panel as seen from behind; the long thin strip is the waistband."
  - dress: "The upper pieces are the bodice, the pieces under them the skirt; front pieces as seen from the front, back pieces as seen from behind."
  - jacket: "Left and right are the wearer's: the right front panel lies at image left, as seen from the front."
  - strapless: "".
- [ ] [1] `prompt_sha("top")` == BASE-`PROMPT_SHA` (kein Oberteil-Atlas veraltet).
- [ ] [2] Kleid, dekoriert, P-H3: Text beginnt `Edit <Picture 1>.`, enthält „top left and middle left shapes“ und
  „are the front of the dress“; `compose(..., keep_negations=True)` gibt ihn byte-gleich zurück.
- [ ] [3] Rock, MiniMax: enthält „front skirt panel, back skirt panel, waistband“ NICHT (der Rückjob ist getrennt) —
  der Vorderjob listet genau „front skirt panel, waistband“ und den Rock-Hinweis.
- [ ] [4] StrictUndefined: fehlendes `hint` → Fehler.
- [ ] Commit.

### Task 0.4: Strap-Kleid-Absturz (B23)
**Dateien:** `app/blender/scripts/garment_template_build.py`, `scripts/smoke_template_cut_first.py` (Blender-Teil).
- [ ] `pattern_uv_of`: `uv_seam` lesen nur wenn vorhanden. `split_slit` schreibt die Ebene zurück (bm-Layer holen
  bzw. anlegen, dann `to_mesh`).
- [ ] Beweis: Liriens Emerald Dress (Kopie, `cut_only`) läuft durch; vorher `KeyError` am BASE-Hash `58550c2b6`.
- [ ] Commit `fix(template build): a bodice without marked cuts keeps going through a slit`.

### Task 0.5: `e2e_cut_texture.py` für jede Art
- [ ] `--item` akzeptiert jedes `PATTERN_KINDS`-Teil; „worn top“ → „worn template piece“; der Zustand `texture`
  wird für das gewählte Teil in der Kopie auf `cut` gesetzt.
- [ ] Neue Prüfung: `marks.json` vorhanden, wenn `placket` ≠ none, und die gemalte Leiste liegt im Atlas (Pixel der
  Knopf-Mittelpunkte weichen um ≥ 15 ΔE76 vom Stoff ab).
- [ ] Neue Prüfung für Röcke/Kleider: der Bund bzw. die Rockteile sind im Atlas gefüllt (`island_coverage` ≥ 0,97).
- [ ] Commit.

---

## Phase A — Rock und trägerloses Oberteil (`wrap`-Weg)

### Task A1: Parameter
**Dateien:** `app/core/garment_template.py`, `scripts/smoke_garment_template.py`.
- `SLIT_SIDES` += `front_left`, `front_right` (B3); `SLIT_ANGLE` in `garment_template_build.py` +=
  `front_left: 1.5π + 6π/40`, `front_right: 1.5π − 6π/40`.
- `KIND_FIELDS["skirt"]` += `waistband`, `texture`; `kind_defaults("skirt")["waistband"] = "wide"`;
  `KIND_FIELDS["top"]` behält `texture` (das trägerlose Top bekommt es damit automatisch).
- `PANEL_KINDS = ("skirt", "dress", "jacket")`, `panel_piece(params) = kind in PANEL_KINDS or strapless_top(params)`;
  `PANEL_VERSION = 1` (Kommentar-Historie „1: pattern-piece UVs for skirt, dress, jacket, strapless top“) im `tsig`
  als `"panels": PANEL_VERSION` nur für `panel_piece` (B16), dasselbe in `cut_sig`;
  `PATTERN_KINDS` += `skirt`, `dress`, `jacket`; `build_args`: `uv_mode` entfällt (immer Pattern, B17).
- `keyed_params`: `waistband` keyt nur `skirt`, `briefs`, `tights` (sonst weg).
- `uv_pattern_key(kind)`: `UV_PATTERN_SHA` auch für `PANEL_KINDS` und das trägerlose Top.
- [ ] [1] `tsig` eines Oberteils mit Ärmeln = BASE (Fixture-Schlüssel); `tsig` eines Rocks ≠ BASE; eines trägerlosen
  Tops ≠ BASE.
- [ ] [2] `validate_params({"kind":"skirt"})["waistband"] == "wide"`, `slit "front_left"` gültig.
- [ ] [3] Winkel: `SLIT_ANGLE["front_left"] − 1.5π = 0.471239` (± 1e-6) = genau 6 Spalten zu π/40.
- [ ] Commit.

### Task A2: `wrap()` beschriftet; Gitter-UV raus
**Dateien:** `garment_template_build.py`, `uv_pattern.py`, `scripts/smoke_uv_pattern.py`.
```python
def wrap(spec, btree, centre) -> (verts, faces, face_part, angles, top_ids, info)
    # face_part: 37/38 (skirt), 1/2 (strapless top), skirt part under the waist row (strapless dress),
    # 14 for the top ``nb`` rows when spec["waistband_m"] > 0 (nb = max(1, round(waistband_m / row_step)));
    # info["seam_edges"] = the waistband's back-centre column edges (back panel column (cols-1)//2, rows 0..nb)
    # info["centre_front"] = front panel column (cols-1)//2, rows 0..rows-1 (for marks)
def pattern_uv_of_wrap(obj, centre, pattern, islands_json, marks_json, rows, rows_alt)
```
- Die Int-Layer `uv_part`/`uv_seam`/`uv_cid` werden VOR `remove_doubles` gesetzt (bmesh-Daten überleben den Merge).
- Bund-Ring über `rings = {14: (centre_xy + z0, +Z, +Y)}`; Paneele über `axes` (+Z hoch, senkrechte Achse durch
  `centre`).
- `uv_pattern.pack(..., rows=, rows_alt=)`: beide Layouts, das mit größerem `s` gewinnt, Gleichstand → `rows` (B5).
- Gitter-UV-Konstanten und -Code gelöscht (B17); Bake immer `atlas_px`.
- Smoke `smoke_uv_pattern.py`, von Hand:
  - [ ] [22] Layout-Wahl Gelina: Kästen 95,1 × 78,8 (×2), Bund 85,5 × 3,0, Rand 1,5. Eine Reihe: W = 1,5 + 95,1 +
    1,5 + 95,1 + 1,5 = 194,7 → floor₀.₀₁(2048/194,7 = 10,519) = **10,51**. Untereinander: H = 1,5 + 78,8 + 1,5 + 78,8 +
    1,5 + 3,0 + 1,5 = 166,6 (W = 98,1) → floor₀.₀₁(12,293) = **12,29** → gewählt.
  - [ ] [23] Kira: eine Reihe W = 1,5 + 49,2 + 1,5 + 48,8 + 1,5 = 102,5 → **19,98**; untereinander H = 1,5 + 34,0 +
    1,5 + 33,9 + 1,5 + 3,0 + 1,5 = 76,9, W = 1,5 + 63,3 + 1,5 = 66,3 → 2048/76,9 = 26,632 → **26,63** → gewählt.
  - [ ] [24] Bund-Ring, Zylinder r 0,10, 2 Flächenreihen à 1,5 cm, 80 Segmente, offen bei θ = 0: u-Länge =
    80 · 2 · 0,10 · sin(π/80) = 16 · 0,0392598 = **0,628157 m** (± 1e-4), v = 0,030 (± 1e-6), p95 ≤ 1,001. Dieselbe
    Insel über `strip_island_uv` ergibt NaN-freie, aber entartete Dreiecke (p95 > 1e6) — der Beweis für B9/B2.
  - [ ] [25] Oberteil-Payload byte-gleich zu BASE (Smoke [21] bleibt grün, `TOP_UV_PATTERN_SHA` unverändert).
- [ ] Commit `feat(template build): skirts and strapless tops cut into pattern pieces (PANEL_VERSION 1)`.

### Task A3: Schlitz vorn links/rechts in Vorschau und Dialog
**Dateien:** `app/core/garment_preview*.py` (die Linie im Vorlagen-Overlay), `frontend/src/tabs/characters/figureModel.ts`,
`TemplateParamsDialog.tsx`, `shared/languages/de.json`, `shared/templates/llm/tasks/garment_template_params.md`.
- [ ] Choice-Labels „Front left“ / „Front right“ (t()), Overlay zeichnet den Schlitz an der richtigen Stelle.
- [ ] Parameter-LLM-Template: Schlitz vorn seitlich + Wickelrock → `front_left`/`front_right`; Rock-Bund.
- [ ] `npm run lint`, Build in sauberem Worktree, `smoke_i18n_orphans.py`, `smoke_no_native_dialogs.py`.
- [ ] Commit (Code, dann Bundle).

### Task A4: Stücknamen
- `piece_name_of`: skirt — `flare` ≥ 0,6 → "circle skirt", `flare` ≤ 0,1 und `length_m` ≤ 0,45 → "pencil skirt",
  `length_m` ≥ 0,75 → "long " + (…), sonst "A-line skirt"/"straight skirt" (`flare` ≤ 0,1 → straight); Schlitz
  ändert den Namen nicht. Trägerloses Top: Ausschnitt `straight`/`sweetheart` und `fit` ≤ 0,2 → "corset top", sonst
  "strapless top".
- [ ] [1] Kira (0,34 / 0,0) → "pencil skirt"; Gelina (0,76 / 0,68) → "long circle skirt"; Tilda (0,8 / 0,3) →
  "long A-line skirt"; Ylva (0,69 / 0,0) → "straight skirt"; Rosi Korsett → "corset top".

### Task A5: CPU-Prüfung auf Kopien (0 Hub-Jobs)
- [ ] Alle fünf Röcke + Rosis Korsett: `cut_only` auf Kopien. Abnahme (B24): Paneele Fläche 0,97–1,03, p95 ≤ 1,25;
  Bund p95 ≤ 1,10; kein Splitter; px/cm ≥ Kira 25,3 · Rosi 19,7 · Gelina 11,7 · Ylva 18,4 · Tilda 14,4 · Rosi-Korsett
  15,0 (Korsett mit Körperabstand und Lift-Körper: echter Wert kleiner als die Demo 19,24). Musterbögen nach
  `~/claude-out/schnitt-texturen/phase-a/`.
- [ ] Neu-Drapierung eines Rocks (Kopie): Bake-Abdeckung ≥ 0,85, Stretch-Gate wie bisher.

### Task A6: Live-E2E Rock + trägerloses Top (lokale Hub-Aliase, Kette im Prozess)
`--chain MiniMax-H3-Image,P-H3-Image`, Kopien, ein Build-Klick, Plan danach leer. Harte Grenze 12 Bild-Jobs in Phase A.
- [ ] Tilda Wool Skirt (schlicht, Rücken vermutlich schlicht → 1 Job + Upscale).
- [ ] Kira Slit Skirt mit `front_left` (Schlitz an der Bildstelle).
- [ ] Gelina Moon Silk Skirt (sheer, Schillern; Layout untereinander).
- [ ] Rosi Red Corset Top (trägerlos; Bild zeigt Abnäher/Stäbe → dekoriert?, die Entscheidung trifft der Code).
- [ ] Jedes Atlas- und Figur-Bild (`figure_front.png`, `figure_back.png`) SELBST ansehen, Protokoll je Teil:
  schlicht bleibt schlicht · Druck/Naht sitzt wo im Bild · kein Farbsprung an Seitennaht/Bund · keine grauen
  Umrisse · kein gedehnter Stoff. Ergebnis nach `~/claude-out/schnitt-texturen/e2e-phase-a.md`.
- [ ] Lieferung an dich: die Umstell-Liste (Abschnitt 5, Zeile A).

---

## Phase C — Jacke

### Task C1: `build_bodice` — Vorderkanten, Band-Regel, Kragen-Ring
**Dateien:** `garment_template_build.py`, `scripts/smoke_garment_template.py`.
- `col_part(c)`: `open_front` → `39` (`left_front`) für c < N/4, `40` (`right_front`) für c ≥ 3N/4, sonst wie
  heute (B7). Gilt nur für `jacket` (ein Oberteil hat keine offene Front).
- `neck_band` = heutige Regel **und** für `dress`/`jacket`: `not open_front and collar == "none" and neckline in
  ("crew", "boat") or (neckline == "scoop" and depth ≤ 0.08)` (B8). Der Ring geht sonst an `col_part`.
- Kragen: `info["collar_ring"] = {"axis_p": (ncx, ncy, z_ring), "axis_d": +Z, "cut": +Y}` für `collar` stand →
  `rings[6]`; Revers bleibt Paneel.
- `info["marks"]`: Konstruktions-Ids der Spalte 0 (geschlossen) bzw. Spalten 0 und `nc−1` (offen), von der
  Ausschnitt-Kante bis zur Saumreihe (Kleid: bis zur Taillenreihe).
- [ ] [1] Synthetische Bodice-Spec (N = 80, offen): Fläche in Spalte 5 → 39, Spalte 75 → 40, Spalte 40 → 2.
- [ ] [2] V-Jacke ohne Kragen: kein `band` im Ergebnis (`faces_per_part` ohne 5).
- [ ] [3] Kragen-Streifen Kai (aus 1.2): Länge ≈ 0,97^1,5 × Bandlänge = 0,95534 × 66,5 = **63,5 cm**; Höhe: 3 Ringe à
  √(1,2² + (0,03 · 10,58)²) cm = √(1,44 + 0,1007) = 1,2412 cm → **3,72 cm** (Radius 66,5/2π = 10,58 cm); Abnahme
  ± 3 % (die Schrumpfung 0,97 je Ring ist `build_bodice`s eigene).

### Task C2: Marken-Datei
**Dateien:** `uv_pattern.py` (`mark_px(islands, payload, ids) -> list[[x, y]]`: jede Id auf ihre Insel-Kopie, bei
zwei Kopien die der genannten Insel), `garment_template_build.py` (schreibt `marks.json`), `garment_template.py`
(`marks_path`), `garment_template_cut.py` (kopiert sie unter `templates/cut/`), `scripts/smoke_uv_pattern.py`.
- [ ] [26] Ein flaches 40 × 60 cm Rechteck, Spalte x = 20 cm als Marke, 18,00 px/cm, Rand 1,5 cm: Pixel-x =
  (1,5 + 20,0) · 18 = **387,0** für jede Ecke der Linie (± 0,5).
- [ ] [27] `marks.json` ist nicht Teil des `islands_sha` (zwei Läufe mit/ohne Marke: gleiche `islands.json`-Bytes).

### Task C3: Leiste, Reißverschluss, Schnürung, Knöpfe malen
**Dateien:** `app/core/cut_texture_post.py`, `app/core/garment_cut_texture.py`, `app/core/garment_template.py`,
`scripts/smoke_cut_texture_post.py`.
```python
PLACKETS = ("none", "buttons", "zip", "lacing")
BUTTON_PITCH_CM = {"top": 7.0, "dress": 7.0, "jacket": 10.0}
BUTTON_D_CM = {"top": 1.1, "dress": 1.1, "jacket": 1.8}
PLACKET_W_CM = {"top": 3.0, "dress": 3.0, "jacket": 3.0}   # lapel: 0 (no band, buttons only)
def draw_placket(atlas, labels, marks, *, kind, style, buttons, px_per_cm, base_lab) -> (np.ndarray, dict)
```
- Nach `compose`, vor dem Schreiben; nur innerhalb der Insel-Maske der Marken-Insel. `POST_VERSION` 8.
- `csig` = md5(Basis-csig, `marks_sha`) nur bei `placket` ≠ none; `reused_jobs` sucht Antworten unter der Basis-csig
  (eine Leistenänderung = `recompose`, 0 Hub-Jobs).
- `buttons` 0 → automatisch (B12).
- [ ] [1] Linie von y = 100 bis 100 + 44,0 · 18,59 = 917,96 px, 0 Knöpfe (auto), top: n = round(44,0 / 7,0 = 6,286) =
  **6**; Mittelpunkte y_j = 100 + (j + 0,5) · 817,96 / 6 → erster **168,16**, Abstand **136,33 px**; Durchmesser
  1,1 · 18,59 = **20,45 px**.
- [ ] [2] Knopf-Kontrast: Stoff L* 85 (creme) → Knopf L* 60, Rand 45; Stoff L* 15 (schwarz) → Knopf L* 40, Rand 55.
- [ ] [3] Nichts außerhalb der Insel-Maske ändert sich (Pixel-gleich).
- [ ] [4] `zip`: Streifen 0,8 cm = 0,8 · 14,08 = 11,26 px breit (± 1), L* 60 ± 3.

### Task C4: Parameter + Dialog
- `KIND_FIELDS["jacket"]` += `placket`, `buttons`, `texture`, `sleeve_print`; `placket`/`buttons` in `TEXTURE_ONLY`.
- Dialog: Choice „Placket“ (None / Buttons / Zip / Lacing), Zahl „Buttons (0 = automatic)“; die Textur-Box zeigt
  „Placket drawn by code — no image job“. Parameter-LLM-Template ergänzt.
- `piece_name_of(jacket)`: Revers → "blazer"; Leder (`fabric` leather_*) → "leather jacket"; offen + kein Kragen →
  "cardigan"; sonst "jacket".
- [ ] Lint, Build, i18n-Smoke, Render-Prüfung des Dialogs (Charakter-Reiter-Checkliste).

### Task C5: CPU-Prüfung + Live-E2E Jacke
- [ ] CPU (Kopien): Tilda Cardigan (offen), Kai (closed + stand + zip), Kira (Revers, 2 Knöpfe). Abnahme: Paneele
  0,97–1,03 / p95 ≤ 1,30; Kragen p95 ≤ 1,10; px/cm ≥ Tilda 14,9 · Kai 13,4 · Kira 15,9; kein `band` bei offen/V.
- [ ] Live, Grenze 12 Bild-Jobs: Kai Lederjacke (Ziernähte → dekoriert), Tilda Cardigan (Strick, Rücken mit Rippen →
  Rückjob), Kira Blazer. Jedes Bild selbst ansehen: Knöpfe auf der richtigen Kante, Reißverschluss in der Mitte,
  kein Farbsprung an Kragen/Vorderkante. Protokoll `e2e-phase-c.md`.

---

## Phase D — Kleid

### Task D1: Taillennaht + Kleid-Kragen
- `build_bodice`: Torso-Fläche mit Mittelpunkt-z < `waist_row_z` → 37/38 (nur `dress`), `waist_row_z` = die
  `row_y` am nächsten an `outline.waist_y`. `wrap()` für das trägerlose Kleid gleich.
- `bodice_spec`: `collar` auch für `dress` und `top` (`stand` erlaubt, `lapel` nur Jacke; `validate_params` setzt
  `lapel` bei top/dress auf `stand`). `keyed_params`: `collar` keyt top/dress nur ≠ none.
- Marken: Kleid-Leiste endet an der Taillenreihe.
- [ ] [1] Synthetische Reihen 0,015 m, `waist_y` 1,126, Reihe bei 1,1205 und 1,1355 → Naht bei **1,1205**
  (|Δ| 0,0055 < 0,0075).
- [ ] [2] Ylva (Kopie): Inseln `front, back, skirt_front, skirt_back, sleeve_l, sleeve_r` (kein `band`, V 17 cm);
  Rock-Paneele 72,9 × 87,6 / 73,8 × 87,8 cm ± 5 %; px/cm ≥ 11,1.
- [ ] [3] Vallerie mit `collar` stand + `placket` buttons: Inseln inkl. `collar`, kein `band`; px/cm ≥ 13,0;
  `marks.json` mit `centre_front` bis zur Taille.
- [ ] [4] Lirien (Träger + Schlitz links): läuft (Task 0.4), Schlitz links = Seitennaht (keine Kerbe im Paneel).

### Task D2: Kleid in der Textur
- `CUT_KINDS["dress"]`: main front (`front`, `skirt_front`), back (`back`, `skirt_back`); model front (`front`,
  `skirt_front`, `collar`) (B22). `piece_name_of(dress)`: Länge ab Taille < 0,40 "mini dress", < 0,65 "knee-length
  dress", < 0,85 "midi dress", sonst "long dress"; mit Ärmeln "long-sleeve …"/"short-sleeve …".
- [ ] [1] Dekoriertes Kleid: `fill_fabric` füllt nur Ärmel/Band, NICHT `skirt_front` (Pixel des Rocks = Antwort).
- [ ] [2] Ylvas Text (P-H3): „The top left and middle left shapes of <Picture 1> are the front of the long-sleeve
  long dress …“ (die Ortswörter aus dem echten Layout, im Smoke aus einer Fixture).

### Task D3: Live-E2E Kleid
- [ ] Grenze 12 Jobs: Vallerie (Punkte-Muster, Knopfleiste + Kragen gemalt), Ylva (sheer, Stickerei Oberteil + Rock,
  Schlitz vorn), Lirien (Smaragd, schlicht). Selbst ansehen: Punkte durchgehend über die Taillennaht, Stickerei an der
  Bildstelle, Schlitz offen. Protokoll `e2e-phase-d.md`.

---

## Phase E + F — Oberteil: Kragen, Leiste, Halsbündchen (ein Release)

### Task E1: Oberteil-Parameter
- `KIND_FIELDS["top"]` += `collar`, `placket`, `buttons`. `keyed_params`: `collar` keyt nur ≠ none; `placket`,
  `buttons` sind `TEXTURE_ONLY`.
- Vorhandener Oberteil-Zuschnitt ohne `marks.json` und `placket` ≠ none → Zustand `marks_missing`, der Zuschnitt
  läuft einmal mit derselben `cut_sig` (CPU); `islands.json` muss byte-gleich sein, sonst `CUT_FAILED` mit Grund
  „islands changed while writing marks“ (B11).
- [ ] [1] `tsig` eines Oberteils ohne Kragen = BASE; mit `placket` buttons = BASE (TEXTURE_ONLY).
- [ ] [2] Tilda-Bluse (Kopie): Leiste setzen → `marks_missing` → Lauf → `islands.json`-sha unverändert
  (`62a3179120d7`-Zuschnitt: sha aus der Kopie festhalten), `recompose` 0 Hub-Jobs, 7 Knöpfe gemalt.

### Task F1: Halsbündchen-Regel auch für Oberteile + Kragen-Ring
- Die Regel B8 gilt jetzt für `top`; Stehkragen-Ring (C1) für `top`. Das ändert die Inseln von V- und Kragen-
  Oberteilen: `TOP_UV_PATTERN_SHA` neu festhalten (Smoke [21] mit neuem Basis-Commit).
- Betroffen in der Welt (gemessen, Band heute kaputt): Dario Worn Linen Shirt (V), Tilda Bluse (2 Band-Teile, mit
  Kragen). Kai T-Shirt (crew, Band 1,53) und Dario Embroidered (crew) behalten ihr Band → ihre Inseln bleiben gleich?
  Prüfen: nur Pieces mit V/Kragen ändern sich; jedes andere Oberteil byte-gleich (Smoke vergleicht drei Fixtures).
- [ ] Live-E2E: Tilda Bluse (Kragen + 7 Knöpfe), Dario Worn Shirt (Schnürung). Grenze 6 Jobs.

---

## Phase G — Korsett-Taille (abtrennbar)

**Messen zuerst, dann bauen** (die Werte entscheiden, ob es den Parameter braucht):
- [ ] Rosis Korsett (Kopie, nach Phase A): Abstand Stoff–Haut an der Taille je 2 cm Höhe, Taillenumfang Stoff vs.
  Körper, Brust-Vorsprung mit `lift` 1,0 vorher/nachher (`bust_shaping.landmarks`).
- Entscheidung schon getroffen, falls der Stoff an der Taille > 1,5 cm absteht: `cinch` (0–1, Standard 0, nur
  `corset_top`): der Körper wird wie beim Lift im Kratz-Körper geformt — Taillenumfang × (1 − 0,08 · cinch) mit
  Glättung über ± 8 cm (`bust_shaping`-Muster: nur Positionen, Jacobi-Determinante > 0,15), die Vorlage mit `fit`
  0 darüber. Schlüssel wie `lift` (`key_tokens`).
- [ ] [1] Smoke: Ring r 0,12 m, cinch 1 → r' = 0,12 · 0,92 = **0,1104 m** auf Taillenhöhe, 0,12 bei ± 8 cm.
- [ ] Live-Render Rosi vorher/nachher (Figur, kein Bild-Job außer ggf. neuer Textur), Protokoll.

---

## Abschluss

- [ ] `docs/garment-templates.md`: Abschnitt „1b. Step 3b: skirt, dress, jacket, strapless top“ (Teile, Nähte, Layout-
  Wahl, Marken, Knöpfe, `PANEL_VERSION`), Gitter-UV-Sätze gelöscht; `smoke_docs_garment_templates.py`-Fakten.
- [ ] `docs/edit-prompts.md`: Prompt-Familie `garment`, `hint`, `front_count`.
- [ ] Alle berührten Smokes grün oder unveränderte rote; `smoke_imports_resolve.py`, `smoke_plugin_private_imports.py`.
- [ ] Übersicht `~/claude-out/edit-prompts/schnittmuster-uebersicht.md` nachziehen.
- Danach (eigener Plan, Nutzer-Reihenfolge Punkt 4): Chat-Bilder und andere Edit-Bilder über `edit_prompt`.

## Regeln für jede Phase

- Nie eine Live-`world.db` öffnen; Kopie per `cp` in `/home/dev/.claude/jobs/c956220f/tmp/`, danach löschen.
- Kein Server, kein `:8000`. Instanz nur über `config.load` mit `INSTANCE_DIR`.
- Hub nur MiniMax-H3-Image, P-H3-Image, Qwen2.1 (`192.168.8.10:4000`) + lokaler Iris-Upscaler.
- Commits pfadgenau (`git commit -- <pfade>`), Trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`;
  nie `static/` außer dem eigenen Bundle-Commit, nie `plugins/*`, `shared/items/*`, `model_capabilities.json`.
- Kein Feature ohne eigenen Live-Lauf; der Nutzer testet erst danach.

## Quellen

- Demos + Rohdaten: `/home/dev/.claude/jobs/c956220f/tmp/cutbplan/` (`runs/*/data.json`, `runs_np/*.islands.json`).
- Skizzen: `gruppe-b-skizzen/skirt_schnitt.png`, `dress_schnitt.png`, `jacket_schnitt.png`,
  `top_knopfleiste_schnitt.png`, `strapless_schnitt.png` (rot = gemalte Leiste/Knöpfe/Reißverschluss).
- Code: `garment_template.py` (`KIND_FIELDS`, `PATTERN_KINDS`, `keyed_params`, `tsig`), `garment_template_build.py`
  (`wrap`, `build_bodice`, `split_slit`, `pattern_uv_of`), `uv_pattern.py`, `garment_cut_texture.py`,
  `cut_texture_post.py`, `garment_template_cut.py`, `bust_shaping.py`.
- Gruppe A: `~/claude-out/schnitt-gruppe-a/plan-schnitt-gruppe-a.md`; Übersicht `~/claude-out/edit-prompts/schnittmuster-uebersicht.md`.
