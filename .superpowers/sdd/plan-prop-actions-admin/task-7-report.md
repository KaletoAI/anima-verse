# Task 7 — Workspace und Asset-Umzug

## Stand und Nachweisgrenze

Produktcode im isolierten Worktree `props-actions-admin`, nicht im ursprünglichen Checkout. `PropDetail` ist die Layout-Komposition; `usePropWorkspace` besitzt den bisherigen gemeinsamen Feldentwurf, Basisrevision, ausgewählte Geometrie und alle Werkzeuge des einen Viewers. Aufgabenbereiche sind eigene Komponenten. Die HTML-Studie wurde nicht als Produktnachweis verwendet.

**Vom Worker nicht ausgeführt:** TypeScript, Build, Tests, Lint, Formatter, Server, Browser, Modell-/Bild-/LLM-Jobs. Der Controller meldete für Basis `a007cad4` erfolgreiche TypeScript-/Buffer-/Bulk-/Build-Prüfungen (Artefakt 185) und reale UI-Nachweise u. a. für einen gültigen texturierten Upload, eine Canvas, bereichsübergreifenden Entwurf und History-Sperren. Das ist Controller-Evidenz, kein eigener Lauf. Die nachfolgend dokumentierte Fixrunde 1 wurde vom Worker wiederum nicht geprüft; Controller-Rebuild, Review und Browser-Nachabnahme bleiben erforderlich. Der Übergabe-Commit-Hash steht in der Worker-Abschlussnachricht.

Task 7 bietet im Bereich Aktionen ausschließlich eine Liste/Summary der wirklichen gespeicherten bzw. gepufferten Aktionsdefinitionen und der Bindung der ausgewählten Variante. Es gibt keine behaupteten Aktions-, Effekt-, Zugangs- oder Laufzeittest-Editoren. Diese gehören zu Task 8. Der vom Nutzer verlangte tatsächliche LLM-Prompt-Nachweis nach Client-Cutover bleibt ein eigener späterer Abnahmepunkt; hier wurde kein kostenpflichtiger Aufruf getätigt.

## Komponenten und genaue Task-8-Schnittstelle

- `PropDetail.tsx`: fünf direkte Bereiche `overview | actions | places | assets | appearance` (Typ `PropWorkspaceArea` aus `propTypes.ts`), Kopf mit globalem Save/Discard, Objektmenü, **ein** Geometrie-Select über Editor und Vorschau, mobile Editor-/Vorschau-Umschaltung. Tastatur: Pfeile/Home/End im Tablist, sichtbarer Fokus. Der Viewer bleibt beim Bereichswechsel und beim mobilen Umschalten gemountet.
- `usePropWorkspace.ts`: `usePropWorkspace(props: PropDetailProps)` liefert `PropWorkspace`. Dieser Typ ist `ReturnType<typeof usePropWorkspace>`, damit die Ansichten den tatsächlichen Vertrag konsumieren. Es gibt keine zweite Formularbibliothek und keinen zweiten Draft-Store.
- Alle Bereichskomponenten bekommen genau `{ workspace: PropWorkspace }`. Task 8 ersetzt `PropActionsSummary` durch seinen Editor und erweitert `PropPlaces`; kein zweiter Owner und kein zusätzlicher Viewer nötig.
- `workspace.actions: ActionDefinition[]` ist `draftValue(buf, GENERAL_TARGET, 'actions', prop.actions || [])`. Änderungen ausschließlich über `workspace.queueGeneral({ actions: completeActionList })`. `toBulkFieldBody` serialisiert dies an die kanonische **Top-Level**-Position `actions`, nicht nach `general.actions`.
- `workspace.variants: PropVariant[]` ist die Serverliste mit dem bestehenden UUID-gekeyten Buffer darüber; `workspace.shownVariant`, `workspace.variant` (numerischer Datei-API-Index), `workspace.setVariant(index)` sind der einzige Geometriekontext. Dauerhafte Bindungen verwenden `shownVariant.uid`, niemals einen Index als Identität.
- `workspace.queueVariant(index, patch)` löst den aktuellen Store-Index in die stabile UUID auf und puffert z. B. `{ markers, action_bindings }` auf `v:<uid>`. `shownVariant.action_bindings` ist die editierbare Sicht. `serverVariants` ist nur die gespeicherte Datei-/Statussicht; dort nicht unmittelbar Feldentwürfe hineinmutieren.
- `workspace.buf`, `dirtyCount`, `saving`, `save(): Promise<boolean>`, `discard()`, `conflicts`, `saveError`, `resolveConflict(conflict, keepLocal)` werden gemeinsam verwendet. `baseRevision` nicht durch einen Editor verändern. Während Save sind Editorfelder und Viewer-Picking gesperrt bzw. laufende Platzierwerkzeuge beendet.
- Navigation über `workspace.navigate(area)`; beendet aktuelle Platzierwerkzeuge, setzt mobil auf Editor und fokussiert den zugehörigen Tab. `setMobilePane('preview')` zeigt den existierenden Viewer, ohne ihn neu zu erzeugen.
- Vorhandene Marker-/Preview-Schnittstellen: `markers`, `selMarker`, `selIdx`, `setSelectedMarker`, `patchMarker`, `saveMarkers` indirekt über `queueVariant`, `armPlacing`, `placing`, `setPlacing`, `previewPose`, `setPreview`. Task 8 kann die Auswahl-/Zugangswerkzeuge hier erweitern. Zugangspunkte-/Rollen-Overlays sind mit Task 7 nicht vorgetäuscht implementiert.
- Viewer-/Flächenvertrag: `viewerRef`, `areaTools`, `setAreaView`, `drawKind`, `areasOnView`, `previewFile`, `showStoredFile`. Es gibt nur `PropPreview` mit einem `Model3DViewer`. Historische Galerie-Dateien sind explizit Vorschau; Flächen, Wasser, Orientierung und Walkable-Werkzeuge bleiben dann gesperrt. `showStoredFile('')` kehrt zum veröffentlichten Modell zurück. Semantische Werkzeuge müssen dieselbe Ausschlussregel mit Polygon-/Wasser-/Marker-Modus beachten.
- `beforeImmediate(label): Promise<boolean>` bleibt die gemeinsame Prop-/Entwurfsentscheidung. Variantenbezogene Sofortoperationen verwenden zwingend `prepareVariantOperation(uid, label): Promise<PropVariant | null>`: vor dem Dialog die UUID festhalten, nach erfolgreicher Entscheidung neu lesen, die UUID auf den aktuellen Datei-API-Index auflösen; bei Abbruch/fehlender UUID kein Schreibrequest. Task 8 darf keinen numerischen Index über ein Await hinweg als Identität verwenden.

## Alt → Neu: erhaltene Funktionen einzeln

| Bisherige Funktion | Neuer erreichbarer Ort / bestehender Verbraucher |
| --- | --- |
| Bibliothek einklappen | vorhandenes `ListPane`, auf breiten Bildschirmen als einklappbare Bibliothek; unter 1100 px Drawer |
| Text-/Tag-Suche, Kategorie, Befestigung, geschätzte Maße | Bibliothek, bisherige Zustände/Filter erhalten |
| Modell fehlt, Aktionen vorhanden, unvollständige Bindung | zusätzliche Bibliotheksfilter; dekorative Props ohne Aktionen erhalten keinen Aktionsmangel-Fehler |
| Thumbnail, Kategorie, Maße, Mount-Vorschlag, fehlende Bilder/Meshes, Varianten, Generierungsstatus | Bibliothekszeilen mit den vorhandenen Daten plus textlichem Aktionsstatus |
| Mehrfachauswahl, alle sichtbaren wählen, Auswahl leeren, Sammelveröffentlichung | Bibliotheksleiste; laufende Bulk-Veröffentlichung hält den tatsächlichen Button/Poller gemountet und verhindert Einklappen |
| Import | bisheriger `ImportButton` in der Bibliotheksleiste |
| Neuanlage mit Upload/Generierungsoptionen | bisheriges `PropCreateForm`, über Neu in der Bibliothek; Create-Pane bleibt scrollbar |
| LLM-Sammelklassifizierung | Bibliothekswerkzeug, bestätigter sofortiger Spend-Dialog mit bis zu einem Aufruf je 40 unklassifizierte Props und anschließendem Ergebnisbericht inkl. ungeklärter Namen |
| Name, Kategorie, Tags | Übersicht, im gemeinsamen Buffer direkt kontrolliert |
| Befestigung unbekannt / vorgeschlagen / bestätigt | Übersicht; unbekannter Wert explizit sichtbar, Vorschlag bestätigen/ändern ist ein Entwurfsfeld |
| Windverhalten | Übersicht, gemeinsames Prop-Feld `sway_factor` |
| Generierungsbeschreibung | Übersicht ausdrücklich für ausgewählte Geometrie sowie Modell & Varianten; dasselbe Variantenfeld, kein zweiter Speicherpfad |
| zentrale Variantenwahl | beständiges Select über Editor und Vorschau, in allen Bereichen und mobil sichtbar |
| Variante hinzufügen, aktivieren/deaktivieren, löschen, Saison-Tags, aktive Obergrenze | Modell & Varianten → Aktivität & Jahreszeiten, bestehender `PropVariantStrip` als Verwaltung (kein zweiter Selektor) |
| Breite/Tiefe/Höhe, proportionale Skalierung, geschätzte Maße | Modell & Varianten → Variant settings, bestehende `variantFields`-Regeln |
| Bodenausgleich | Modell & Varianten → Sink, bestehender `SliderInput` als Zahleneingabe; gleiche Live-Vorschau |
| Frontbild samt Backend-/Prompt-/Negativ-/Zeit-Provenienz, Vergrößern | Modell & Varianten → Source image, bestehendes `useEnlarge` |
| Frontbild neu rendern, hochladen, Metadaten/Bild neu laden | Modell & Varianten → Source image, bisherige Container-Dialogs/Uploadrouten |
| Rück-/Links-/Rechtsansicht, vorhandene Vorschau, Vergrößern, Rendern, Upload, Zwei-Klick-Löschen | Modell & Varianten → Extra views, bisherige variantengebundene Routen |
| andere Varianten als Bildreferenz | vorhandener `PropImageDialog`, unveränderte `refVariants`-Übergabe |
| Quellbild erneut meshen, Multi-View-Auswahl | Modell & Varianten → 3D from this image, vorhandener `MeshBackendDialog` |
| weitere Variante generieren | Modell & Varianten → Regenerate, bestehender Container-Dialog samt Obergrenze und Generierungs-Poller |
| Generierungsstatus je Variante und für weitere laufende Varianten | Bibliothek und Modell & Varianten, bisherige Poll-/Statusdaten |
| Mesh-Galerie, historische Vorschau, aktiven Tier wählen, kein Modell wählen, einzelne Datei löschen | Modell & Varianten → bestehender `PropModelPanel` / `ModelGalleryRow` |
| GLB-Upload und Tier-Auswahl | Modell & Varianten → bestehender `PropModelPanel`, bisheriger Datei-Input / `TierPicker` |
| Detailstufen und Budgets für Full/Low, Backend-Placeholder | Modell & Varianten → Resolution tiers, gemeinsamer Varianten-Draft |
| CPU-Distance-Mesh und Mesh→Mesh-Reduktion | Modell & Varianten → bisherige `BuildDistanceMeshButton` und Reduktionsdialog; gemeinsame Sofortoperations-Schranke ergänzt |
| freie Orientierung je Achse / +90° | Modell & Varianten → Orientation fix, sofortig; bei historischer Vorschau gesperrt |
| begehbare Oberfläche: Status, backen, entfernen, Zwei-Klick-Bestätigung | Modell & Varianten → Walkable surface, bisherige Dateioperationen; bei historischer Vorschau gesperrt |
| Marker hinzufügen/platzieren/auswählen/löschen; Kataloggruppe; XYZ; Blickrichtung; Kapazität; Abstand; Slot-Achse; Vorschaupose | Plätze & Zugänge → extrahiertes vollständiges bisheriges Markerformular (`PropPlaces`), inklusive numerischer Alternativen |
| Flächenerkennung, angeforderte Arten, Polygonzeichnen/Abbrechen, Flächenart ändern, Flächen auflösen | Darstellung → bestehender `PropAreasPanel`, derselbe Viewer-/R1-Vertrag |
| Bilder, Bildvarianten, Bildzuordnung, Name, veralteten Rahmen neu kopieren, Assemblierungsvorschau | Darstellung → bestehender `PropAreasPanel` / `PictureVariantDialog` |
| Materialien, Spiegel-/Glas-Presets | Darstellung → bestehende Pane defaults, dieselben Scene-Presets |
| Türblatt-/Türschwenktest | Darstellung / derselbe Viewer mit bestehendem `leafBbox`, keine zweite Canvas |
| Licht-Presets, Farbe, Stärke, Reichweite, Halo, Flackern, Tageszeit, XYZ, Viewer-Picking, auf alle Varianten | Darstellung → vollständiges bisheriges Lichtformular; weiterhin Varianten-Entwurfsfeld |
| Wasser: erkennen/pollen, gültig/veraltet, Regionen/Status, aktivieren, Aussehen/Farbe/Klarheit, Wasserstand/Tiefe, manuell Rechteck/Ellipse, Größe, platzieren, entfernen | Darstellung → bestehender `WaterPanel` / `useModelWater`; sofortig. Zahlenalternativen für Slider und manuelle Größen ergänzt |
| Export | beschriftetes Objektmenü; gespeicherter Stand, bisheriger ZIP-Endpunkt |
| Veröffentlichen | beschriftetes Objektmenü; vorhandener `PublishButton`, bei Entwurf erst speichern |
| Prop löschen | beschriftetes Objektmenü; bisheriger Zwei-Klick-Mechanismus und Container-Löschpfad |
| Referenzfigur, Meterraster, Maße, Markervorschau, Flächenumrisse, Frontansicht | dauerhafte gemeinsame Vorschau (`PropPreview`); vorhandene Viewer-Funktionen |

## Speicher-, Sofort- und Konfliktregeln

1. `pendingFields` bleibt der einzige Feldbuffer. Eine globale Speicherung sendet `base_revision`, `general`, Top-Level-`actions` und Variantenpatches nach UUID. Verwerfen betrifft nur diesen Buffer und die kurzlebigen Zahlen-/Textarea-Eingabezustände, nicht schon veränderte Dateien.
2. Name/Kategorie/Tags/Wind/Mount, Variantenbeschreibung, Maße, Bodenausgleich, Jahreszeiten, Budgets, Marker, Bindungen und Licht bleiben Felder des gemeinsamen Entwurfs. Keine heimlichen Feldrequests auf Blur.
3. Upload, Generierung, Galerie-/Tieränderungen, Variantenverwaltung, Orientierung, Flächen und Wasser behalten die existierenden sofortigen API-Operationen. Diese Speicherart ist im jeweiligen Bereich beschriftet. Die gemeinsame Schranke fragt konservativ bei **jedem** offenen Feldentwurf nach Speichern/Fortfahren oder Abbruch, damit auch bereichsübergreifende Abhängigkeiten nicht mit alten Daten weiterlaufen. Schon laufende unabhängige Jobs werden nicht angehalten.
4. Wasserzahlen basieren auf der gespeicherten Modellskalierung. Bei offenem Draft werden diese Editoren gesperrt und ein ausdrücklich benannter Save-and-continue-Einstieg angeboten; danach werden die Wasserdaten erneut gelesen. Dadurch wird eine vor dem Speichern errechnete Wasserhöhe nicht still mit veralteter Skalierung geschrieben. Wasser wird außerdem bei geänderter Prop-Revision neu gelesen.
5. `fieldConflicts` vergleicht ausschließlich lokal bearbeitete Author-Felder gegen die bisher akzeptierte und die neue Serversicht. Allgemeine und Varianten-Sicht müssen dieselbe Revision nennen, bevor die Basis vorgerückt wird. Nur tatsächlich nicht überlappende Felder werden kontrolliert auf die neue Basis übernommen; Datei-/Jobstatus ist kein Author-Feld.
6. Ein LLM-Mount-Vorschlag berücksichtigt auch `mount_suggested` beim Vergleich. Ein lokaler Mount-Entwurf wird niemals mit dem Klassifizierungsergebnis überschrieben. Überlappungen erscheinen mit Server-/lokalem Wert und expliziter Entscheidung pro Feld. Ein bewusst nicht unterstütztes Binding und ein dekoratives Prop sind keine fehlende Aktion.
7. Aktionen, Markerlisten und Bindungen werden als ganze Felder behandelt, nicht nach Position oder Label automatisch vermischt. Bei 409 wird der lokale Buffer nicht gelöscht und der Schreibrequest nicht automatisch wiederholt. Die aktualisierte Serversicht ermöglicht gezielte Übernahme; verschwundene Varianten zeigen ihre erhaltenen lokalen Felder als Konflikt.
8. Fehler beim Variantenlesen lassen den letzten guten Zustand stehen und zeigen eine Wiederladen-Aktion; Speichern ist bis zur kohärenten Sicht gesperrt. Späte ältere Variantenantworten werden über eine Request-Generation verworfen.
9. Eine historische Galerie-Datei sperrt Flächen-/Wasserwerkzeuge sowie Orientierung/Walkable-Schreibwerkzeuge, bis ausdrücklich zum veröffentlichten Modell zurückgekehrt wurde. Bereiche wechseln die Kamera nicht. Mobile Umschaltung blendet denselben Viewer aus/ein; `ResizeObserver` passt dessen Viewport bei Container-/Draweränderungen an, ohne Kameraneustart.
10. Die bestehenden Import-/Mesh-/Bild-/Bildvarianten-/Marketplace-Dialogs bleiben Verbraucher. Neue Entscheidungs-/Berichtsmodals verwenden die bestehende Admin-Modaloberfläche mit Fokusbindung, Rückfokus und Escape. Escape verwirft keinen gesamten Prop-Entwurf.

## Kleine gemeinsame Komponentenänderungen

- `ListPane`: optionale kontrollierte Expansion und Sperre des Einklappens; unverändertes Verhalten ohne diese Props. Benötigt für Drawer und laufende Bulk-Veröffentlichung.
- `BuildDistanceMeshButton`: optionales `prepareBuild(): Promise<string | null>`; liefert nach der Save-Schranke die neu aufgelöste Ziel-URL oder bricht mit `null` ab. Bestehende Verbraucher ohne Callback behalten ihren bisherigen URL-Pfad.
- `Model3DViewer`: Container-`ResizeObserver` statt ausschließlich Window-Resize; nötig für Bibliothekseinklappen/mobile Preview bei gemountetem Viewer.

## Vorbereitete Regressionen, nicht ausgeführt

`scripts/smoke_prop_fields_buffer.mjs` ergänzt verhaltensbezogene Fälle für disjunkte Änderungen, Mount-Klassifizierung gegen lokalen Mount, Variantendescription-Überlappung, UUID-unabhängige Reihenfolge, verschwundene Varianten, feldweise Serverübernahme sowie ungemischte konkurrierende Aktionslisten. Keine Tests auf Texte/Überschriften/Komponentenverdrahtung. Bestehender Bulk-Test wurde nicht verändert.

## Controller-Prüfungen

Aus dem isolierten Worktree, nach Integration und ohne parallele Worker-Checks:

```sh
./frontend/node_modules/.bin/tsc -b frontend/tsconfig.json
node scripts/smoke_prop_fields_buffer.mjs
node scripts/smoke_prop_operation_targets.mjs
./.venv/bin/python scripts/smoke_prop_bulk_save.py
npm --prefix frontend run build
```

Den vom Controller bisher verwendeten Python-Interpreter einsetzen, falls `.venv` nicht im Worktree eingebunden ist. Kein Server oder Test wurde hier gestartet.

Anschließend echte Admin-Browserprüfung bei **1440, 900 und 390 px**, nicht die HTML-Studie:

- Bibliothek ein-/ausklappen, Drawer öffnen/schließen und Fokus, Such-/Filterkombinationen, Mehrfachauswahl, Import/Neu und laufende Bulk-Anzeige.
- Prop-/Bereichs-/Variantenauswahl, mehrere Felder über Bereiche/Varianten, Speichern, Verwerfen, Verlassen-Warnung und unveränderte Kameraposition.
- Mount-Vorschlag im Draft bestätigen und verwerfen; sofortige LLM-Kostenbestätigung abbrechen; einen genehmigten Klassifizierungslauf samt Ergebnisbericht und überlappendem lokalen Mount mit expliziter Konfliktentscheidung prüfen.
- Upload mit unabhängigem Draft, Save-and-continue/Cancel, Generierungsstatus ohne lokale Feldverluste, Discard nach sofortigem Upload (Datei muss bleiben).
- Revisionskonflikt/gelöschte Variante, lokale Werte stehenlassen, gezielte Serverübernahme/Behalten und erst danach bewusster neuer Save.
- Galerie-Vorschau historischer Datei, gesperrte Flächen-/Wasser-/Orientierungs-/Walkable-Werkzeuge, explizite Rückkehr; genau eine Canvas/Viewer-Instanz.
- Sämtliche in der Zuordnungstabelle genannten Assetwerkzeuge; Wasser-Editor nach einem dirty Maßentwurf erst nach benanntem Speichern und erneutem Lesen bedienen.
- Tastaturpfad, Pfeiltasten/Home/End, sichtbarer Fokus, Modal-Tabbindung/Rückfokus, Escape für aktuelles Werkzeug, mobile Editor-/Preview-Umschaltung, numerische Marker-/Wassergrößen-/Wasserstand-Eingaben und erreichbare Speicheraktionen ohne horizontales Dokumentoverflow.

## Fixrunde 1 / unabhängiges Workspace-Review

Basis `a007cad4`, alle sieben Reviewbefunde sowie die vom Controller genehmigte 390-px-Hostkorrektur adressiert. Keine Worker-Checks, Jobs, Server oder Fixture-Änderungen.

1. **Async-Zielidentität:** Die neue Consumer-Hilfe `resolveVariantAfterBarrier` liest erst nach der Entscheidung und löst die ursprünglich festgehaltene UUID neu auf. Source-/View-Uploads, Galerieauswahl/-löschung/-upload, Reduktion, CPU-LOD, Variantenanlage/-aktivität/-löschung, Orientierung, Walkable, Flächen, Pane-Defaults, Bildvarianten, Rahmenkopie und Wasser verwenden die aufgelöste Variante bzw. URL. Orientierung liest auch die übrigen Achsen frisch. Flächen lehnen eine inzwischen gewechselte Modelldatei ab. Wasser bindet UI-Antworten an die ursprüngliche UUID; ein Indexwechsel ist keine neue Identität. Auch die spätere bezahlte Bestätigung in Bild-/Meshdialogs löst Target- und Referenz-UUIDs erneut auf. Eine entfernte UUID schreibt weder in den Nachfolger noch in einen anderen Slot.
2. **Tippen vor Blur:** Dimensionen, Generierungsbeschreibung und Face-Budgets schreiben ihre kanonischen Feldwerte bereits beim ersten `onChange` in denselben `pendingFields`-Buffer. Eine unvollständige Dimensionszahl pinnt den bisherigen Dimensionswert als bearbeitetes Feld. `dimDraft`, `descDraft` und `faceDraft` halten nur die Eingabezeichenfolge, nicht unerkannte Author-Änderungen. Ein Hintergrundresultat kann deshalb weder die betreffende Konfliktbasis vorziehen noch lokale Eingabezeichenfolgen einer überlebenden UUID durch bloßes Reindexieren zurücksetzen. Kein zweiter State-/Form-Store.
3. **Bildvariantenmodal:** Die Save-/Cancel-Entscheidung ist jetzt ein Body-Portal mit expliziter höherer Ebene (1200 statt bestehender Bildmodalebene 1000), Fokusbindung und Rückfokus. Der geöffnete `PictureVariantDialog` bleibt samt Bild-/Namensentwurf gemountet; Zielidentität ist die UUID. Escape in der oberen Entscheidung erreicht den unteren Dokument-Listener nicht. Bei einer neuen Bildvariante wird zusätzlich geprüft, dass die ursprüngliche Rahmen-UUID noch primär ist.
4. **Drawer / Sammelveröffentlichung:** Der vorhandene portaled `AnchoredPopover` bietet eine optionale Fokus-Scope für Bulk-Publish. Nach sichtbarer Positionierung wird Fokus in die Veröffentlichung übertragen; Tab bleibt dort, Escape schließt nur diese Oberfläche und Schließen fokussiert den Auslöser zurück. Die native Drawer-Fokusbindung läuft nur für tatsächliche DOM-Nachfahren und fängt die Portal-Tastatur nicht ab. Keine Bibliotheks-/Popover-Kopie.
5. **Bildsubject nach Save:** `openImageGeneration(view)` liest nach der Save-Schranke die gespeicherte Prop-Definition und die UID-aufgelöste Variante. `propGenerationSubject` verwendet deren Beschreibung bzw. den tatsächlich gespeicherten neuen Namen. Front- und Zusatzansichten benutzen denselben Pfad; Bildprovenienz und Referenz-UUIDs bleiben erhalten. `openMeshGeneration()` verwendet ebenfalls die frisch gelesene Variante.
6. **Regenerierungsziel / Kosten:** `propGenerationTarget` spiegelt die bestehende Serverregel (erst aktiver leerer Slot, sonst neuer Slot unter Cap, sonst letzter aktiver Slot). Der Dialog benennt ein bestehendes Ziel und bei Cap ausdrücklich den Austausch von Quellbild/aktivem Mesh sowie den Erhalt der Mesh-Galerie. Der Auslöser verspricht nicht mehr bedingungslos eine zusätzliche Variante. Vor dem kostenpflichtigen Request wird der Plan erneut gelesen; ein verändertes Ziel/Cap/Reindexieren öffnet den aktualisierten Hinweis ohne Jobstart und verlangt erneute bewusste Bestätigung. Bestehende Ziele werden explizit über die UUID-aufgelöste Variantenroute angesprochen.
7. **Zugängliche Übersicht:** Name, Kategorie, Tags, neue Beschreibung, Befestigung und Wind haben explizite zugängliche Namen entsprechend ihren sichtbaren Beschriftungen. Keine Änderung des gemeinsamen `Field`-Bausteins.
8. **390-px-Host:** Der identifizierte globale Header-Control-Container erhält nur eine Klasse. Unter 800 px darf der Header umbrechen und seine Controls dürfen innerhalb der verfügbaren Breite wrappen; Desktopregeln bleiben unverändert. Kein Abschneiden/Verstecken der Controls, keine Änderung parent-eigener Acceptance-Fixtures oder Templates.

### Aktualisierte Task-8-Verbraucher

- `workspace.prepareVariantOperation(uid, label)` ist die Schranke für varianteigene Schreiboperationen. `null` bedeutet abbrechen. Kein alter Index und keine vor der Schranke zusammengebaute URL nach dem Await.
- `workspace.openImageGeneration(view)`, `openMeshGeneration()` und `openRegeneration()` sind die Asset-Einstiege statt direkter Aufrufe mit alten Render-Closures. Interne Container-Callbacks tragen `PropVariant` bzw. `PropGenerationTarget`, Bildreferenzen als UID-haltige Variantenrecords und die frisch gespeicherte Prop-Definition.
- `areaTools.run(what, call)` übergibt `call(currentIndex)` den neu aufgelösten Index; nicht mehr eine parameterlose Closure mit altem Query-Index.
- `editDim(key, raw)` pinnt den Feldentwurf beim Tippen; `commitDim` normalisiert beim Blur. Beschreibungs-/Face-Budget-Consumer puffern ebenfalls auf Change und normalisieren weiter beim Blur.

### Zusätzliche Regressionen und erneute Controller-Abnahme

`scripts/smoke_prop_operation_targets.mjs` übt die tatsächliche UID-Continuation-Hilfe mit einer wartenden Entscheidung, nachfolgender Reindexierung, entferntem Ziel und Abbruch ohne nachfolgenden Read/Write aus. Zusätzlich werden die drei realen Generationstargetfälle und der gespeicherte Namensfallback geprüft. `smoke_prop_fields_buffer.mjs` ergänzt gleichzeitig aktive Dimension-/Beschreibungs-/Budgetfelder gegen spätere Hintergrundänderungen. Beide Erweiterungen sind **nicht vom Worker ausgeführt**; keine Überschrift-/Source-Pin-/Komponentenverdrahtungsasserts.

Controller bitte Kommandos erneut ausführen und Async-Target-Smoke ergänzen. Im tatsächlichen Admin besonders: B/1 mit dirty Draft wählen, Schranke öffnen, A/0 extern entfernen, Konflikt gezielt auflösen und fortfahren; B muss am neuen Index angesprochen werden und C unverändert bleiben. Entferntes B darf keinen Folgeslot bearbeiten. Aktiver Zahlen-/Beschreibung-/Budgetinput während eines Hintergrund-Authorupdates muss einen Feldkonflikt auslösen. Bildvarianten-Save mit dirty Prop muss pointer- und keyboard-bedienbar über dem Bildmodal bleiben; Cancel muss den Bildentwurf erhalten. Im 900-/390-Drawer Bulk-Publish per Tastatur öffnen und Catalog/Tags/Publish/Close erreichen. Rename bei leerer Variantenbeschreibung vor New image/Extra view speichern; Prompt muss den gespeicherten neuen Namen enthalten. Regenerate am Cap muss das tatsächliche Austauschziel vor dem Jobstart benennen. 390 px: Dokument-Scrollbreite am echten Header erneut messen und alle Header-/Speichercontrols bedienen. Kein Produktnachweis dieser Fixrunde wird hier behauptet.
