# Task 8 — Aktions-, Wirkungs- und Zugangseditor

## Übergabe und Nachweisgrenze

Produktänderungen ausschließlich im Worktree `props-actions-admin`, Branch `feat/props-actions-admin`, auf Task-7-Basis `71f1982b`. Die Übergabe-Nachricht enthält den expliziten Commit-Hash. Originalcheckout, Shared-Produktassets und die private Parent-Acceptance-Fixture wurden nicht verändert.

**Kein Worker/Child hat Tests, TypeScript, Build, Lint, Formatter, Server, Browser oder Modell-/Medienjobs ausgeführt.** Vorbereitete Regressionen sind kein beobachteter RED/GREEN-Nachweis. Tatsächliche API-/Store-/Browserabnahme bei 1440/900/390 px bleibt vollständig Controller-Arbeit. Insbesondere ist die Standardlücke eines fehlenden Eintrittsübergangs kein Erfolg: die Raumprüfung zeigt den echten Sperrgrund, ohne Defaultanimation/Teleport zu erfinden.

## Bedienung und Datenvertrag

`PropDetail` ersetzt die bisherige Summary durch `PropActionsPanel({workspace,onIssue})`. Die obsolete Summary und deren Styles sind entfernt. Alle Bereiche benutzen unverändert einen `usePropWorkspace`-Owner, einen Feldbuffer, UUID-gekeyte Varianten und einen gemounteten Viewer. Die gemeinsame Variante bleibt oberhalb von Editor/Vorschau auch mobil sichtbar. Ein Save umfasst die Top-Level-Aktionsliste und alle Variantenpatches; kein zweites Formular- oder Effekt-/Ausführungsmodell wurde eingeführt.

- `workspace.selectedActionId / setSelectedActionId` ist die gemeinsame Aktionsauswahl für Inspector, räumliche Bindung, Vorschau und Prüfung. Bei entfernter Auswahl wird die erste verbleibende Aktion gewählt.
- `workspace.catalog / reloadActionCatalog / authoringIssues` benutzen die bestehenden realen Quellen `/world/stat-keys`, `/world/conditions/list`, `/poses?axis=pose`. Der vorhandene Marker-Posenkatalog wird aus derselben Antwort abgeleitet. Stimmungen bleiben die Vorschläge aus `useMoods`; freier Mood-Text ist weiterhin gültig.
- `queueGeneral({actions: completeArray})` ist der einzige Aktionsschreibpfad. Name, Beschreibung, Regeln, Voraussetzung, Wirkung und Phase puffern direkt auf Change, nicht erst Blur. `queueVariant(currentIndex,patch)` übersetzt wie bisher in die stabile UUID. Kein neues Revision-Rebase und kein automatischer Retry bei 409.
- `saveIssues` erhält strukturierte Serverfehler bzw. Editorblocker. Fehlerlinks wählen Bereich, Aktion und Variante und fokussieren das Feld. `data-author-path="actions.N.effects.M.stat"` usw. verbindet die Aktionsfelder mit dem kanonischen Serverpfad. Variantengebundene Bindungsfelder haben `prop-binding-*`-IDs. Unbekannte Referenzen bleiben erhalten und explizit reparierbar.
- Der gemeinsame Save verweigert unlesbare Kataloge, unbekannte/nicht ausführbare Darstellungen, echte Paarfähigkeitslücken, unpassende Personenzahl, unbekannte Stat-/Zustandsreferenzen und unzulässige Wirkungszeitpunkte. Servervalidierung und Runtime bleiben zusätzlich autoritativ; der Editor ist kein zweiter Executor.

## Aktionen, Voraussetzungen und Wirkungen

Ausdrückliche Vorlagen: Sitzen/Entspannen, wach Hinlegen, echtes Einschlafen, Kaffee und echte Paarhandlung. Sitzen/Hinlegen benötigen eine passende vorhandene Sitz-/Liegedarstellung; Paar benötigt einen echten `solo:false`-Katalogeintrag und eine vollständige Paarclipfähigkeit aus `pair_kinds`. Unbekannte/verlorene Fähigkeiten werden nicht als dekorative No-op angeboten.

Der Inspector bearbeitet Name, NPC-/Spielerbeschreibung, aktiviert/deaktiviert, Fähigkeit, eine/zwei Personen, vier Raumanwesenheitspolitiken und laufende Unterbrechung. Harte Voraussetzungen sind AND-Zeilen auf existierende Werte mit Vergleich/Schwelle oder vorhandene Zustände mit vorhanden/nicht vorhanden sowie semantisches Ziel. Nicht lesbare Charakterwerte werden nicht erfunden; die reale Raumprüfung meldet den Runtimegrund.

Kaffee hat ausschließlich Zubereiten und Trinken mit positiven Spielzeitdauern und vorhandenen Darstellungen. Ein abweichender vorhandener Phasenablauf bleibt sichtbar fehlerhaft, bis ausdrücklich durch den festen Ablauf ersetzt. Kein frei verdrahtbarer Workflow und kein Item. Erfolg wird erst nach vollständigem Trinken vergeben. Wachpose/Paar laufen bis beendet und bieten keinen ausnutzbaren Abschlussbonus; echter Schlaf nutzt Wach-zu-Schlaf-Erfolg und die bestehende Schlaf-/Erholungsmechanik, ohne zusätzliche aktive Bettregeneration.

`PropActionEffects` und `PropActionRequirements` sind strukturierte wiederholbare Zeilen. Wirkungstypen: Wertbetrag oder Rate pro aktiver Spielminute, Stimmung, Zustand hinzufügen/entfernen. Zustand: Dauer in Spielsekunden/-minuten/-stunden, Wiederholung ignorieren oder Dauer auffrischen, kein Stapeln. Zeitpunkte werden abhängig von Fähigkeit und Typ begrenzt; ein bereits ungültiger Zeitpunkt wird nicht still korrigiert. Ziele sind semantisch ausführende Person, Partnerperson oder beide. Zustandspflege bleibt im vorhandenen Zustandsbereich verlinkt, kein zweiter Zustandseditor.

Kopieren von anderem Prop liest dessen wirkliche gespeicherte Definition, mintet neue Aktions-/Phasen-/Voraussetzungs-/Wirkungs-IDs und übernimmt keine fremde Geometriebindung. Lokale unabhängige Kopien ebenso. Aktionsentfernung verlangt die bewusste gemeinsame Entfernung aller Variantenbindungen; Körpermarker bleiben erhalten.

## Räumlicher und Viewer-Vertrag

`PropPlaces` erweitert das bestehende vollständige Körpermarkerformular mit `PropSpatialBindings`. Markerpositionen bleiben Bruchteile der RAW-Bounding-Box; XYZ, Facing, Kapazität, Slotabstand und Achse bleiben vorhanden. Bindungen sind varianteneigen und beziehen sich dauerhaft auf die UUID; ausdrückliches Nichtunterstützen ist kein verlorener Zugang.

Zugänge sind `{x,z,yaw}` am Boden im orientierten lokalen Meterrahmen ab Grundflächenmitte; Punkte außerhalb der Modellbox sind erlaubt. Numerische Felder und Ground-Plane-Picking bearbeiten denselben Variantenentwurf. Körperanker-/Zugangs-/Heading-/Rollenoverlays behaupten keinen tatsächlichen Raumweg. Bei Paaren sind physische A/B-Clip-/Zugangsrollen von den semantischen Wirkungszielen getrennt: die vorhandene Runtime weist die Personen nach den echten Paarregeln zu.

Der Workspace besitzt `patchBinding(actionId,patch)`, `armAccess(actionId,role)`, `accessPlacing` und `onPickAccess`; die bestehenden Marker-/Flächen-/Wasser-/Lichtwerkzeuge bleiben exklusiv. Historische Dateivorschau und Save sperren schreibende Picking-Modi. Escape beendet nur das aktuelle Werkzeug. Kamera/Canvas bleiben beim Bereichs- und mobilen Editor-/Previewwechsel gemountet; die bestehende Hidden-RAF-Pause wurde nicht durch einen zweiten Viewer ersetzt.

Referenzierte Marker können nur mit ausdrücklich gewähltem Ersatz oder gemeinsamer Entfernung aller abhängigen Bindungen aus demselben Entwurf entfernt werden. Variantenverwaltung bleibt sofortig und benutzt die vorhandene Save-/Cancel-Schranke sowie erneute UUID-Auflösung nach dem Await; referenzierte Variantengeometrie wird nicht still entfernt.

## Konfiguration, echte Platzierung und getrennte Ausführung

`PropActionChecks({workspace,onIssue})` trennt drei Einstiege:

1. `POST /world/props/{id}/validate` mit `{document}`: `propActionCheckDocument(prop,workspace.variants,buf)` projiziert den **vollen aktuellen ungespeicherten** Autorentwurf. Top-Level-`actions`, alle `model_variants`, stabile UUIDs, Marker und Bindungen; `...variant.dims` wird in skalare `width_m/depth_m/height_m` übertragen, keine verschachtelten HTTP-`dims` und kein UUID-Bulk-Patchobjekt. Allgemeine Felder einschließlich Tags-/Mount-Draft werden kanonisch projiziert. Aktion-/Variantenreihenfolge bleibt exakt die Workspace-Reihenfolge für Fehlernavigation. Raumweg/Eintritt/Anwesenheit bleiben ohne Platzierung nicht geprüft.
2. `POST .../check-placement` mit `{target,action_id,revision,actor,partner}` prüft ausschließlich die **gespeicherte** aktuelle Definition. Dirty Draft, laufender Save und verschiedene gespeicherte Revisionen sperren den Request. Ort, tatsächlicher Raum, vorhandene Platzierung und reale wache Personen müssen ausdrücklich ausgewählt sein. Schlafende zählen sichtbar zur Anwesenheit, sind keine Partner. Der erste tatsächliche Sperrgrund ist kein Beweis, dass nachfolgende Prüfungen bestanden wurden.
3. Separates `Handlung in der Welt ausführen…` öffnet Warnung/Bestätigungsmodal und sendet erst danach `POST .../execute-test` mit zusätzlich strikt `confirmed:true` und neuer `request_id`. Gleicher Executor, Regeln und ausdrückliche Paarzustimmung, kein Admin-Bypass. Die Antwort ist als Startmomentaufnahme bezeichnet; keine versteckte Ausführung durch Vorschau/Prüfung.

Minimale neue Admin-Lesequelle: `GET /world/props/{id}/check-targets?location_id=…` → `{revision,rooms:[{id,name,placements:[{target:{location_id,room_id,placement_id,variant_uid}}],persons:[{name,sleeping}]}]}`. Sie verwendet tatsächliches `places._compose` und `_present` samt bestehender Read-only-Szenenkette, keine Testpersonen/Platzierungen und keine Medienerzeugung. Ortsauswahl verwendet das vorhandene `/world/locations`. Diese Route ersetzt keinen Verfügbarkeits-/Wegchecker.

## Vorbereitete Regressionen und Controller-Kommandos

`scripts/smoke_prop_action_authoring.mjs` transpiliert reale Helper mit dem vorhandenen TypeScript, ohne neue Abhängigkeit. Fälle: echte Solo-/Paarkatalogauswahl, feste Kaffeephasen, unabhängige Kopier-IDs/verschachtelte Zeilen, unbekannte Referenzen unverändert als Fehler, verbotener Relax-Abschlussbonus, keine aktive Schlafregeneration und kanonische volle Draft-Projektion inklusive UUID-Reihenfolge, Dimensionen und Issue-Auflösung. `scripts/smoke_prop_action_api.py` ergänzt die echte Admin-Zielliste mit schlafendem Raumzensus, tatsächlichem Target, Revision, verweigertem normalen Benutzer und unveränderten DB-/Dateisnapshots unter bestehenden Medien-Tripwires.

`scripts/smoke_prop_spatial_bindings.mjs` deckt die wirkliche atomare Marker-/Referenzreparatur, Paar-Kapazität, fehlende/ungültige Zugänge, lokale Grundflächenfreiheit sowie Vorwärts-/Rücktransformation des Ground-Pickings außerhalb der Modellbox ab. Keine Source-/Verdrahtungs-/Wortlautpins.

Controller nach Integration, ohne gleichzeitig schreibende Worker:

```sh
./frontend/node_modules/.bin/tsc -b frontend/tsconfig.json
node scripts/smoke_prop_action_authoring.mjs
node scripts/smoke_prop_spatial_bindings.mjs
node scripts/smoke_prop_fields_buffer.mjs
node scripts/smoke_prop_operation_targets.mjs
node scripts/smoke_prop_dimension_gesture.mjs
./.venv/bin/python scripts/smoke_prop_bulk_save.py
./.venv/bin/python scripts/smoke_prop_action_api.py
npm --prefix frontend run build
```

Danach tatsächlicher Admin-Browser bei **1440/900/390 px**, reale API und Storewerte, nicht HTML-Studie: Kaffee mit zwei Phasen und existierender Energie/Stimmung/Zustandwirkung speichern/reloaden; Entspannung mit Rate; Variante ohne Zugang reparieren, ausdrücklich unsupported setzen; unbekannter Stat blockiert und ist reparierbar; Marker-/Variantendeletion bewusst; bereichs-/variantenübergreifender Draft, 409, Keyboard/Fokus und numerische Alternativen; genau eine Canvas und erhaltene Kamera; Konfigurationscheck ohne DB-Mutation; tatsächlicher Platzierungscheck mit ehrlichem fehlendem Eintrittsgrund; getrennte Bestätigung echter Ausführung und normale Paarzustimmung.

## Task-9-Grenze

Keine Spieler-/Together-/Browser-/Native-Client-Cutoverarbeit in Task 8. Die neuen Adminfunktionen konsumieren die bereits vorhandenen echten Task-6-Verträge. Beide Clients müssen in Task 9 dieselben autoritativen Angebote, Zustimmung, Ausführungszustände und lokalen Wege vollständig konsumieren; das ist keine behauptete Task-8-Browser-/Spielabnahme. Der Nutzerwunsch nach tatsächlichem LLM-Template-/Toolnachweis **nach** Client-Cutover bleibt ausdrücklich als eigene spätere Abnahme bestehen.

## Fixrunde 1/5 — echte Phasen, kanonischer Maßstab und ehrliches Prüfergebnis

Fixbasis `7629ae16` (Task-8-Commit `da86b684` plus explizite Parent-Typkorrektur). Die vier Important-Befunde aus `history://ActionEditorReview:168-207` wurden als Scope übernommen. Parent meldete für diese Basis TypeScript, Authoring-/Spatial-/Buffer-/Target-/Gesture-Smokes, Bulk, API **17** und Build erfolgreich (`artifact://258`). Die tatsächliche UI zeigte trotzdem beide Kaffeephasen als Driving; diese Beobachtung wurde nicht erneut zur Bestätigung ausgeführt. Parent hatte die realen Phasen anschließend manuell auf Cooking/Drinking korrigiert. Das war keine Akzeptanz der falschen Vorlage.

Produktkorrekturen:

1. Kaffee wählt Phasendarstellungen unabhängig aus wirklich verfügbaren Katalogfähigkeiten: Zubereiten bevorzugt `making-coffee`, danach `cooking`; Trinken verwendet `drinking`. Weder erste Sitzpose noch erste beliebige Soloaktion sind Ersatz. Fehlt eine passende Fähigkeit, bleibt die Phase ausdrücklich leer/reparierbar und Save blockiert. Die Kaffeevorlage bleibt erreichbar, damit fehlende Phasendarstellungen gezielt zugeordnet werden können.
2. `propMetresPerUnit(bbox,dims,rotation)` in `spatialBindings.ts` delegiert an das echte React-freie `placeTransform(...).outerScale`. Dadurch gilt dieselbe 90°-gerundete Messung wie im Renderer, während die tatsächliche Orientierung unverändert exakt bleibt. `PropPreview` verwendet den Kehrwert für Referenzfigur, Zugänge/Inverse-Picking und Slotgeometrie; `PropPlaces` verwendet denselben Faktor für RAW-Marker-Meterreadbacks. Keine Änderung an `dimensionGesture` oder der Authoring-Ratioarithmetik.
3. `actionPreviewPose(action,phaseId?)` liefert bei kombinierten Aktionen die wirkliche ausgewählte Phase beziehungsweise die erste Eintrittsphase. Der dauerhaft gemountete Viewer bietet eine ausdrücklich beschriftete Vorschauphasenauswahl ohne Weltänderung. Änderungen an `phases[].pose_key` aktualisieren den Overlay-Consumer; das unbenutzte Top-Level-`pose_key` ist nicht länger die kombinierte Vorschauquelle. Fehlende Darstellung wird nicht heimlich durch die Markergruppen-Defaultpose ersetzt.
4. Die Konfigurationsprüfung verbindet die Editorblocker des tatsächlich geprüften Entwurfs mit den Serverissues. Ein positiver Server-Stringtypcheck für eine leere Pose kann keine grüne Konfiguration mehr erzeugen, während Save wegen dieser Pose blockiert ist. Antworten und Fehler bleiben an den geprüften Prop-/Dokument-/Katalogsnapshot gebunden; spätere Antworten für veraltete Entwürfe werden nicht als aktuelles Ergebnis verwendet.

Regressionen sind vorbereitet, **nicht von Worker/Children ausgeführt**: Kaffee mit vorne liegender fremder Driving-Fähigkeit wählt echte getrennte Phasen; fehlende passende Fähigkeiten bleiben leer; Vorschau folgt erster/ausgewählter und bearbeiteter Phase statt dem veralteten Top-Level-Posewert. Die Spatial-Regression vergleicht 45°-Quadrat, asymmetrische/multiaxiale und negative Fixes mit der echten kanonischen Platzierung; der 45°-Fall prüft ausdrücklich den handableitbaren Maßstab ohne √2-Abweichung. Konfigurationsregressionen prüfen echte leere-Pose-Editorblocker trotz positivem Serverresultat, Serverfehler/Warnungen und veraltete asynchrone Snapshots. Keine Verdrahtungs-, Source- oder Wortlautpins.

Controller: die oben aufgeführten Kommandos erneut ausführen, zusätzlich `node scripts/smoke_prop_action_checks.mjs`. Danach die **tatsächliche** Kaffeevorlage ohne manuelle Ersatzreparatur öffnen: unterschiedliche passende Zubereitungs-/Trinkdarstellungen; fehlende Darstellung leer und reparierbar; Vorschauphase wechseln und Darstellung ändern. An einem Prop mit 45°-Orientierungsfix numerischen Zugang mit Ground-Pick und Meterreferenz vergleichen. Leere Phasendarstellung prüfen: Save gesperrt und Konfigurationscheck ebenfalls fehlerhaft; während wartender Prüfung Entwurf ändern, ohne ein veraltetes grünes Ergebnis zu übernehmen.

Keine Worker-/Child-Checks, Server, Browser oder Modell-/Medienjobs in dieser Fixrunde. Private Parent-Fixtures/-Skripte/-Templates wurden nicht verändert. Task9 und der tatsächliche spätere LLM-Template-Nachweis bleiben unverändert außerhalb dieser Übergabe.

Neue reine Prüfhilfen in `propActionChecks.ts`: `composePropConfigurationResult(document,catalog,server): PropConfigurationResult`, `samePropConfigurationSnapshot(checked,current): boolean`, `isCurrentPropConfigurationRequest(checked,current): boolean`. `PropConfigurationSnapshot` hält `{propId,revision,document,catalog,revisionReady}`; `PropConfigurationRequest` ergänzt `{snapshot,sequence}`. Diese Hilfen ändern weder das HTTP-Payload noch die serverseitige Ausführung.
