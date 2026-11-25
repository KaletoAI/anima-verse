# Client-Ausführung E2 (Navmesh im Client) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der native Client backt pro gemounteter Location ein Navmesh aus dem Szenen-Payload (Godot-freie Quelle in `native/Core/Nav`), mit Türschwellen als eigenen Regionen, Treppen-/Aufzug-Links, Prüfung (`--check nav`), Debug-Overlay (F9), gemessenem Vergleich Voxel-Bake gegen 2D-Polygon-Bake, Klick-Laufen über `QueryPath` und einer Navmesh-Klemme, die den Avatar an Möbeln stoppt.

**Architecture:** `NavSource.Build` (Core, rein) macht aus `ScenePayload` + `TileFrame` + `PlaceInventory` + gemessenen Prop-Boxen pro Stockwerk Laufflächen und Hindernis-Umrisse in Welt-Metern, dazu Türschwellen-Rechtecke und Links. `NavBake` (Godot) backt daraus je Stockwerk ein `NavigationMesh` — Modus `Polygon` über `NavigationServer2D.BakeFromSourceGeometryDataAsync` + `NavigationPolygon.GetNavigationMesh()`, Modus `Voxel` über `NavigationServer3D.BakeFromSourceGeometryDataAsync`; Task 5 misst beide und löscht den Verlierer. `LocationNav` (Godot) hält eine eigene Navigation-Map pro Location mit einer Region pro Stockwerk, einer Region pro Türschwelle (abschaltbar bei Sperre) und den Links; ein Rebake baut eine **neue** Map und tauscht erst, wenn sie vollständig synchronisiert ist (synchrone Map-/Region-Iterationen, Signal `NavigationServer3D.MapChanged`, Entscheidung 4). Pfadsuche und Klemme liegen hinter `IPathProvider` (Core), Planung und Verfolgung (`NavRoutePlanner`, `NavRoute`, `NavClamp`) sind rein und mit einer Fake-Implementierung getestet.

**Tech Stack:** C# / .NET 8, Godot 4.7.2 mono (`NavigationServer3D`, `NavigationServer2D`, `NavigationMesh`, `NavigationPolygon`, `NavigationMeshSourceGeometryData2D/3D`), xUnit (`native/tests`), Headless-Check (`native/Check`), `native/test.sh`, `native/package.sh`.

**Spec:** `docs/superpowers/specs/2026-11-25-client-ausfuehrung-design.md` — Abschnitte 3, 5d (vollständig), 6 (Zeilen „Ziel unerreichbar“, „Figur steckt fest“, „Raumwechsel“, „Szene ändert sich“), 7 Punkt 9, 8 Zeile E2 und „Festgelegt, mit Messregel“, 9. Baseline: `docs/superpowers/measurements/2026-11-25-client-ausfuehrung-e0-baseline.md`.

## Global Constraints

- Geteilter Arbeitsbaum auf `main`, kein Worktree, kein `--amend`, kein `stash`, kein `rebase`. Andere Sessions committen parallel.
- **Pfadgenaue Commits:** `git add <genau die Pfade>` und `git commit -m "<msg>" -- <dieselben Pfade>`. Vor dem ersten Edit einer Datei `git diff --quiet -- <datei>`; hat sie fremde, nicht committete Hunks: nicht anfassen, dem Orchestrator melden. Neue `*.cs` bekommen beim ersten Godot-Import ein `*.cs.uid` — das gehört in denselben Commit.
- Jede Commit-Nachricht endet mit der Zeile `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **`docs/superpowers/` ist gitignoriert:** Plan, Spec und Messdokument nur mit `git add -f <pfad>`.
- **Kein Zugriff auf `worlds/`**, keine Live-`world.db`, kein Start/Stopp/Abfragen des laufenden Servers.
- **E2 ändert kein Server-Verhalten:** keine Datei unter `app/`, `shared/`, `static/`, `client3d/`, `hud/`, `frontend/`, `scripts/` wird angefasst. Aufträge kommen erst in E3. Bestehende Endpunkte (z. B. die Raum-Eintrittsmeldung beim Treppenritt) werden nur so benutzt, wie der Client sie heute schon benutzt.
- `native/Core` bleibt Godot-frei (`native/tests/CoreIsGodotFreeTests.cs`); jeder öffentliche Core-Typ liegt unter `AnimaNative.*` (hier `AnimaNative.Nav`).
- Erwartungswerte werden **von Hand hergeleitet** (in `native/fixtures/README.md`, Abschnitt „Nav world“, und in den Test-Docstrings), nie als Schnappschuss der aktuellen Ausgabe. Navmesh-Ergebnisse werden mit Toleranz geprüft, nie bitgleich.
- Jeder Task endet mit lauffähigem nativen Client: `GODOT=/home/dev/tools/godot/Godot_v4.7.2-stable_mono_linux_x86_64/Godot_v4.7.2-stable_mono_linux.x86_64 native/test.sh` grün (bei reinen Core-Tasks genügt `dotnet test native/tests` + `dotnet build native/`).
- Godot-API-Namen nur aus der installierten `GodotSharp.xml` (`/home/dev/tools/godot/Godot_v4.7.2-stable_mono_linux_x86_64/GodotSharp/Api/Release/GodotSharp.xml`); alle unten genannten Methoden sind dort verifiziert.
- `grep` ist ein ugrep-Wrapper: `command grep -rna` oder `git grep -a` benutzen.
- Code-Kommentare/Docstrings Englisch; deutsche Kommentare in angefassten Dateien ins Englische übersetzen. Keine Rückwärtskompatibilitäts-Aliase, kein Übergangsschalter (Spec 8: kein Doppelbetrieb).
- Kein `CharacterBody3D`, kein Physik-Backend-Eintrag, keine Avoidance, keine NPC-Änderung (alles E3+). Draußen kein Navmesh (Spec 5d „Außenwelt“).

## Entscheidungen dieses Plans (Claude, ohne Rückfrage getroffen)

1. **Eine Quelle, zwei Bake-Modi.** `NavSource` liefert 2D-Umrisse pro Stockwerk (Laufflächen mit Löchern, Hindernis-Rechtecke mit Höhenband). `Polygon`-Modus: `NavigationMeshSourceGeometryData2D.AddTraversableOutline` / `AddObstructionOutline`, `NavigationPolygon { AgentRadius = 0.25, CellSize = 0.05 }`, Ergebnis über `GetNavigationMesh()` (Vertices (x, 0, z)) auf die Stockwerkshöhe gehoben. `Voxel`-Modus: Bodenflächen per `Earcut.Triangulate` als `AddFaces`, Hindernisse per `AddProjectedObstruction(outline, elevation, height, carve: false)`, Parameter aus Spec 5d. Beide Modi leben bis Task 5; Task 5 entscheidet per Messregel (Entscheidung 9) und löscht den Verlierer samt seiner Parameter.
2. **Türen werden versiegelt, die Schwelle ist eine eigene Region.** Für jeden Durchgang (`SceneDoorway`, `Usable`) mit **angrenzender Wand** derselben Ebene (eine Wand, deren Mittellinie höchstens 0,05 m von `at_world` entfernt und parallel zu `along` liegt und deren Endpunkt höchstens `width/2 + 0.05` m von `at_world` entfernt ist) baut `NavSource` ein **Siegel** (Hindernis-Rechteck: Mitte `at_world`, halbe Länge `width/2` längs `along`, halbe Tiefe `t/2` quer, `t` = größte Dicke der angrenzenden Wände) und eine **Schwelle** (Rechteck: halbe Länge `width/2 − r`, halbe Tiefe `t/2 + r`, `r` = 0,25). Die Schwellenkanten quer zur Wand liegen damit genau auf der erodierten Raumkante (Wandfläche + r) und werden per Edge-Connection verschweißt. Ein Durchgang ohne angrenzende Wand bekommt weder Siegel noch Schwelle (offener Boden). Ist `width/2 − r ≤ 0`, gibt es das Siegel, aber keine Schwelle (Tür unpassierbar), und `NavSource` meldet ein `NavProblem("door_too_narrow", doorwayIndex)`.
3. **Sperre = Region aus, über den vorhandenen Sperrenweg.** `LocationNav.ApplyLocks(locks, avatarRoom)` setzt je Schwelle den Sollwert `on = Locks.DoorwayLock(rooms, locks, avatarRoom) is null`, vergleicht ihn mit `RegionGetEnabled(rid)` und ruft `RegionSetEnabled` **nur bei echter Abweichung** (Review N-B1); Rückgabe `bool` = mindestens eine Schwelle hat sich geändert — dieselbe Regel, mit der heute Türblätter (`WorldBuilder.Props.cs:121`) und Türmarken gefärbt werden. Kein Rebake. Aufgerufen wird es **nur** aus `WorldBuilder.SetLocks(LockState)` (`WorldBuilder.cs:1044`, hält `_locks` samt `AvatarRoom`; heute schon von `LocationStoreys.cs:160` / `Residency.cs:186` benutzt) für jeden Slot mit Navigation, und beim Scharfschalten **jeder** neuen Map (Entscheidung 4) mit dem aktuellen `_locks` — sonst wäre nach einem Rebake jede verschlossene Tür offen. Es gibt keinen zweiten Sperrenweg (kein `ApplyNavLocks`, keine Änderung in `MainRooms`).
4. **Eine Map pro Location, Tausch statt Umbau.** Jeder Bake erzeugt eine neue Map (`MapCreate`, `MapSetActive`, `MapSetCellSize`, `MapSetCellHeight`, `MapSetEdgeConnectionMargin`, `MapSetLinkConnectionRadius`, `MapSetUseEdgeConnections(true)`, **`MapSetUseAsyncIterations(map, false)`**) und setzt je Region **`RegionSetUseAsyncIterations(region, false)`**. Grund (Review B4, gemessen mit 4.7.2): mit dem Standard `map_use_async_iterations = true` ist `iter = 1` eine **leere** Map (`QueryPath` → `[]`, `MapGetClosestPoint` → (0,0,0), keine Edge-Connections), erst `iter = 2` ist vollständig; ebenso zeigt nach `RegionSetEnabled` der nächste Iterationswechsel noch den alten Zustand. Mit synchronen Iterationen ist `iter = 1` vollständig und eine Sperre wirkt im nächsten Physik-Frame. **Bereitschaft** = `MapGetIterationId(map)` ist seit der letzten **wirksamen** Änderung an dieser Map (Erzeugen, ein `RegionSetEnabled`/`LinkSetEnabled`, das den Zustand wirklich umschaltet) gestiegen; `LocationNav` merkt sich dazu `ChangedAtIteration`. **Nur eine echte Änderung setzt `ChangedAtIteration`** (Review N-B1): `ApplyLocks`/`SetLinkEnabled` vergleichen den Sollwert mit `RegionGetEnabled`/`LinkGetEnabled` und lassen gleiche Werte unberührt — ein `RegionSetEnabled` mit dem schon gesetzten Wert löst in 4.7.2 keinen Map-Wechsel aus, `Ready` bliebe sonst für immer `false`. Scharf geschaltet wird über das Signal `NavigationServer3D.MapChanged(Rid map)` (in der XML vorhanden) — es gibt keinen Frame-Tick-Aufrufer (Review W3). **Abo nur solange eine ausstehende Map existiert** (Review N-W1): der Builder meldet `OnNavMapChanged` an, wenn die erste ausstehende Map entsteht, und ab, wenn keine mehr aussteht (nach Tausch oder Verwerfen) sowie in `StopResidency` (`WorldBuilder.Residency.cs:118`, hängt an `TreeExiting`, `WorldBuilder.cs:439`) — ein Signal-Handler auf einem freigegebenen Builder wäre ein Absturz im Server-Sync. Beim Scharfschalten (erstes `MapChanged` der ausstehenden Map): `ApplyLocks` mit dem aktuellen `_locks` (Entscheidung 3); **ändert es nichts** (keine Sperre trifft eine Schwelle), ist die Map jetzt schon bereit → **sofort** Tausch; ändert es etwas, erst beim nächsten `MapChanged` dieser Map mit `Ready` tauschen. Tausch = `slot.Nav` setzen, `NavChanged` melden, alte Map samt Regionen und Links freigeben (`FreeRid`). So gibt es nie einen Frame ohne Pfad (Spec 5d). **Abfragen während `SetLocks`** (Review N-W4): `NavFor` liefert die aktive Map auch dann, wenn ein `ApplyLocks` sie gerade auf `Ready == false` gesetzt hat; Pfadsuche und Klemme laufen bis zur nächsten Iteration auf dem alten Sperrzustand weiter (ein Physik-Frame). Nur Checks warten per `AwaitReady` auf „Änderung wirksam“.
5. **Wann gebacken:** an **zwei** Stellen. (a) Direkt nach `slot.Ring = Ring.Near` in `MountDetailAsync` (`WorldBuilder.Residency.cs:190`) — das ist der erste Zeitpunkt, an dem der Slot `Near` ist: `DeriveStands` läuft beim Bau mit `const Ring ring = Ring.Far` (`WorldBuilder.cs:576/818`), in `MountDetailAsync` bei `Residency.cs:250` und über `SwapTierAsync` (`Models.cs:139`) jeweils **vor** `:190` (Review B1). (b) Am Ende von `WorldBuilder.DeriveStands(slot)` für Tier-Swap, Redatum und Modell-Nachladen (`Models.cs:325`); bei `UnmountDetail` (`Residency.cs:338`) ist der Ring dort schon `Far` → Freigabe. Gebacken wird nur für `slot.Ring == Ring.Near` mit mindestens einer Lauffläche; bei `Ring.Far` und in `FreeSlot` wird die Navigation freigegeben. Ergebnisse eines veralteten Bakes (`slot.Generation` geändert oder neuerer Fingerabdruck angefordert) werden verworfen.
6. **Cache-Schlüssel = `NavSourceData.Fingerprint`** (SHA-256 über die kanonische Zahlentextform der ganzen Quelle + `NavBakeParams.Version`) statt nur `scene_etag`: so lösen auch Möbel-Boxen nach dem Modell-Laden einen Rebake aus, ein unveränderter Remount nicht. Speicher-Cache für 16 Fingerabdrücke (LRU); Plattencache nein (Spec: erst ab gemessenen 300 ms).
7. **Laufflächen.** **Ebene 0** jeder Location (Gebäude wie Nicht-Gebäude) = der `boundary`-Ring, um `r + 0,05` = 0,30 m **nach außen** versetzt (Versatz-Regel `NavSource.OffsetRing`, Review N-klein: Wicklung zuerst per Shoelace auf gegen den Uhrzeigersinn in (x, z) normiert, damit „außen“ unabhängig von der gelieferten Reihenfolge ist; jede Kante wird um d längs ihrer Außennormale verschoben, neue Ecke = Schnitt der beiden verschobenen Nachbarkanten (Gehrung, auch an konkaven Ecken — dort liegt der Schnittpunkt nach innen versetzt); fast parallele Nachbarkanten (|Kreuzprodukt| < 1e-9) → Ecke entfällt; spitze konvexe Ecken mit Gehrungslänge > 4·d → Fase (zwei Punkte im Abstand d); ergibt das einen sich selbst schneidenden Ring (O(n²)-Kantentest, z. B. Kerbe schmaler als 2·d), gilt der unversetzte Ring und `NavProblem("boundary_offset", -1)` wird gemeldet. Review B3: der Hof `is_ground` steht nicht in `floor_plan`, `scene_recipe.py:4219`; der 2D-Bake erodiert jede Außenkante um r, auch ohne Wand — mit dem Versatz liegt die erodierte Kante 0,05 m außerhalb des Grundrisses, der Avatar kommt also über die Grundstückskante, wo die Klemme nicht mehr gilt), dazu die `floor_plan`-Polygone, die Platten der Ebene 0 und die Umrisse aller `scene.Corridors` der Ebene 0 (`SceneCorridor.Outline`, über `TileToWorld`). Sperren sind nur Wände, Siegel und Möbel. Höhe: `FollowGround = true` und `Hulls` = die `floor_plan`-Polygone der Ebene 0 (Welt-xz) — `NavBake` hebt einen Vertex innerhalb einer Hülle auf `datum + FloorY(0)`, außerhalb auf `groundAt(x, z)` (Kanten ohne Wand, an denen sich beide mischen, werden linear interpoliert; das Gefälle dort ist der Unterschied Datum ↔ Gelände am Rand und bleibt unter `agent_max_climb`). **Andere Ebenen:** jede Platte als **eigener** `NavFloor` (der Bake vereinigt sie; Core hat keine Polygon-Union, Review W6), dazu die Korridore dieser Ebene; ein Plattenloch wird nur dann als Hindernis eingetragen, wenn **keine andere** Platte derselben Ebene es überdeckt (Mittelpunkt-in-Polygon-Test gegen die übrigen Umrisse — reale Fixtures haben deckungsgleiche bzw. überlappende Platten je Ebene: `walk/scene_loc-hall.json` Ebene 1, `storeys/scene_loc-tower.json`). Höhe = größtes `TopY` der Ebene + Datum, `FollowGround = false`.
8. **Hindernisse:** Wände wie `Collide.WallSegments` (ohne `Lintel`, ohne `Leaf`, Glas sperrt), als Rechteck um die Mittellinie mit halber Dicke `max(t, 0.02)/2`, ohne Endkappen; ausgelassen werden Wände, deren Oberkante höchstens `agent_max_climb` 0,25 m über dem Boden liegt oder deren Unterkante mindestens `agent_height` 1,8 m darüber. Möbel: gemessene Welt-Boxen aller Placements mit `Role == "prop"`, `Door == null`, `!Walkable`, als achsparalleles xz-Rechteck; ausgelassen nach derselben Höhenregel (Teppich, Hängelampe). Treppen- und Aufzugsboxen (`extras`) sind nie Hindernisse.
9. **Messregel Voxel gegen Polygon (Task 5):** Gewinner ist der Modus, der (a) alle Pfad-Abschnitte N4–N7 von `--check nav` besteht und (b) den kleineren größten Kantenfehler hat (gemessen an den Sonden N2: Abstand gefundener Rand ↔ exakte erodierte Kante). Bei Gleichstand innerhalb 0,01 m entscheidet die kleinere Summe der Backzeiten über die vier Vergleichs-Locations. Der Verlierer wird im selben Task gelöscht.
10. **Overlay** ist ein eigenes `MeshInstance3D` (`NavOverlay`), gebaut aus den Polygonen der Regionen der offenen Location (Stockwerke blau, Schwellen grün bzw. rot wenn gesperrt, Links als gelbe Linien), +0,03 m angehoben, unshaded, halbtransparent; **F9** schaltet es. Nicht `NavigationServer3D.SetDebugEnabled` — das zeichnet in Release-Exporten nicht.
11. **Klick-Laufen.** Heute gibt es im nativen Client **keinen Boden-Klick** (einziger `WalkTo`-Aufrufer ist der Anlauf zum Treppenfuß, `AvatarRoomsController.cs:241`; `MainHud.PickAt` kennt nur Figur, Angebot, Vertikalziel — Review B2). E2 baut ihn: im `pickAction` von `MainHud.PickAt` **nach** Angeboten und Vertikalzielen, nur `Embodied`, schneidet der Klickstrahl die Ebene `y = datum + FloorY(LevelFilter ?? 0)` der Location, in deren Grundriss der Avatar steht; liegt der Treffer außerhalb dieses Grundrisses, wird einmal mit der Ebene `y = FigureGroundY(x, z)` des ersten Treffers nachgeschnitten. **Steht der Avatar draußen** (kein Grundriss): erste Ebene `y = Avatarhöhe`, dann einmal mit `y = FigureGroundY(ersterTreffer)` nachschneiden (Review N-W5 — am Hang liegt ein Treffer auf einer festen Ebene sonst neben dem Klickpunkt). Beides ist die reine Funktion `NavClick.GroundHit` über `NavClick.FloorHit` (Core). Dann `WalkTo(hit, level)`; dessen Ergebnis ist das Ergebnis des `pickAction`. `PlayerSteering.WalkTo` prüft zuerst wie heute `Blocked(mine, hit)` (Ablehnungs-Scheiben, `PlayerBlocked` samt Eintritts-/Schlossweg, `WorldBuilder.Embody.cs:80`) und plant erst danach über `NavRoutePlanner`, sobald der Start in einer Location mit fertiger Navigation liegt; sonst bleibt der heutige gerade Weg (`ClickMove.PlanClickWalk`) — das ist kein Doppelbetrieb, denn draußen gibt es kein Navmesh (Spec 5d). `Route` bleibt in beiden Modi das **Endziel** (bestehende Checks lesen es: `EmbodyRoomsCheck.cs:110`, `EmbodyOffersCheck.cs:166`, `EmbodyWalkCheck.cs:106`), `NavRoute` kommt dazu. Überquert der Pfad einen Link, ruft die Steuerung `RideLink(ownerId)` (`Func<ulong, Task<bool>>`); `AvatarRoomsController.RideLinkAsync` startet denselben Ritt wie heute ein Treppen-/Aufzugsangebot (`RideAsync`, mit Parameter `keepNavRoute`), `false` = Ritt nicht gestartet → Route abgebrochen. Unerreichbares Ziel → `WalkTo` gibt `false` zurück. `NavRoute` (Verfolgung, Feststecken, Neuplanung) ist ein kleiner Abspieler, den E3 durch den Auftragsweg ersetzt — bewusst Wegwerf-Code, so im Spec-Eintrag (Task 8) benannt.
12. **Klemme:** `NavClamp.Step` (Core) nach `Collide.ClampAgainstWalls` in `PlayerSteering.Step`, nur wenn der Avatar in einer Location mit fertiger Navigation steht, kein Stair-Ride läuft und das Ziel im Grundriss liegt (der Hof gehört dank Entscheidung 7 zum Netz, über die Grundstückskante hinaus gilt sie nicht). Der alte `OwnPropMotion`-Weg ist automatisch ausgenommen, weil `Step` bei `PropActionDriven`/`WalkIn` vorher zurückkehrt (`PlayerSteering.cs:130/146`) — das wird im Check belegt, nicht nur behauptet.
13. **Owner-Ids der Links:** Treppe `(1UL << 16) | flightIndex` (Index in `PlaceInventory.Stairs`), Aufzug `(2UL << 16) | (ulong)(lowerLevel + 128)`. Kosten: Treppe enter 0 / travel 1; Aufzug **`LinkSetEnterCost` 20 und `LinkSetTravelCost` 10** (Review W2: `enter_cost` allein hält die Pfadsuche in 4.7.2 nicht vom Aufzug fern — gemessen nahm P2 vorwärts den Aufzug). **Pfad-Metadaten:** Godot markiert genau **einen** Punkt, den Einstieg (`PathTypes` = Link, `PathOwnerIds` = Owner); der Ausstieg ist der nächste Punkt, schon wieder Typ Region (gemessen `types = [0,0,0,0,0,1,0,0,0]`). Vertrag: `Owners[i] ≠ 0` ⇒ Link-Abschnitt `(owner, Points[i], Points[i+1])`. Pfadpunkte liegen auf dem Netz, nicht auf der Link-Position (Aufzug unten (105.2, **0.0**, 3.2)). Navigation-Layer: Stockwerk `1u << Math.Clamp(level + 8, 0, 30)`, Schwellen wie ihr Stockwerk, Links `1u << 31`; Abfragemaske immer `uint.MaxValue` (Spec 5d).

## Review Focus

1. **Tür schmaler als 2 · 0,25 m** (z. B. 0,45 m): kein Absturz, keine Schwelle, Siegel bleibt, `NavProblem` gemeldet — Test `NarrowDoorHasSealNoThreshold` in Task 1.
2. **Avatar startet neben dem Navmesh** (sitzt im Sessel, steht auf dem `access`-Punkt 0,15 m am Möbel): er muss weggehen können, die Klemme darf ihn nicht festhalten oder zurückreißen — Tests `OffMeshStartMayApproachMesh` / `OffMeshStartMayNotGoDeeper` in Task 2, Check-Abschnitt A2b in Task 6.
3. **Location wird während eines asynchronen Bakes abgebaut oder neu gemountet:** Ergebnis verworfen, keine verwaiste Map (`ProcessInfo.ActiveMaps` zurück auf den Ausgangswert) — Check-Abschnitt N9 in Task 4.
4. **Klick nach draußen aus dem Gebäude** (Ziel außerhalb des Grundrisses): Weg über die nächste Außentür-Schwelle, dann gerade weiter; ohne Außentür der heutige gerade Weg — Tests `OutsideTargetRoutesViaOutsideDoor` / `OutsideTargetWithoutDoorFallsBack` in Task 2. Der umgekehrte Fall (Klick von draußen in einen fremden Grundriss) bleibt wie heute abgelehnt (`EmbodyWalkCheck.cs:136`, `PlayerBlocked`).
6. **Tastengang bei echter Bildrate** (dt 1/60, Schritt 0,15 m < Erosion 0,25 m): Raum → Hof → über die Grundstückskante, die Klemme sperrt nicht ein — Check A7 in Task 6.
7. **Sperre überlebt einen Rebake** — Check N12 in Task 4.
5. **Flache und hängende Möbel** (Teppich 0,02 m hoch, Lampe ab 1,9 m): keine Hindernisse; **gedrehte Location** (yaw 90°): Schwellen-Rechteck richtig in Welt-Metern — Tests `FlatAndOverheadPropsAreNoObstacles`, `YawTurnsThresholdIntoWorld` in Task 1.

---

## Dateiübersicht

| Pfad | Verantwortung | Task |
|---|---|---|
| `native/Core/Nav/NavTypes.cs` | `NavFloor`, `NavObstacle`, `NavThreshold`, `NavLinkSpec`, `NavStoreySource`, `NavSourceData`, `NavPropBox`, `NavProblem`, `NavLayers`, `NavLinkOwner` | 1 |
| `native/Core/Nav/NavBakeParams.cs` | Bake-Parameter je Modus, `Version`, Zellgrößen-Untergrenze | 1 |
| `native/Core/Nav/NavSource.cs` | `NavSource.Build(...)` | 1 |
| `native/Core/Nav/NavPaths.cs` | `IPathProvider`, `NavPath` | 2 |
| `native/Core/Nav/NavClamp.cs` | Klemme | 2 |
| `native/Core/Nav/NavRoute.cs` | `NavRoutePlanner`, `NavRoute` (Verfolgung, Feststecken, Neuplanung) | 2 |
| `native/tests/NavSourceTests.cs`, `native/tests/NavRouteTests.cs`, `native/tests/FakePathProvider.cs` | xUnit | 1, 2 |
| `native/fixtures/nav/*` | Nav-Welt (Szene, Worldmap, Locations, Urls, Höhenfeld, Terrain, model3d) | 1 (Szene), 3 (Rest) |
| `native/fixtures/README.md` | Abschnitt „Nav world“ mit allen Herleitungen | 1, 3, 4, 6 |
| `native/World/NavBake.cs` | Godot-Bake beider Modi, Schwellen-Mesh | 3 |
| `native/World/NavMaps.cs` | `LocationNav` (Map/Regionen/Links/Tausch/Sperren), `GodotPathProvider` | 3 |
| `native/World/WorldBuilder.Nav.cs` | `RequestNavBake`, `ReleaseNav`, Prop-Boxen, Cache, `NavFor` | 4 |
| `native/World/WorldBuilder.Stands.cs`, `native/World/WorldBuilder.Residency.cs`, `native/World/WorldBuilder.cs` | Aufruf am Ende von `DeriveStands` und nach `slot.Ring = Ring.Near` (`Residency.cs:190`), Freigabe in `FreeSlot`, `LocationSlot.Nav`, Sperren in `SetLocks` | 4 |
| `native/Check/NavCheck.cs`, `native/Check/CheckRunner.cs`, `native/Cli.cs` | `--check nav`, `--check navcompare` | 3, 4, 5, 6, 7 |
| `docs/superpowers/measurements/2026-11-25-client-ausfuehrung-e2-navmesh.md` | Messvergleich + Entscheidung | 5 |
| `native/Core/Nav/NavClick.cs`, `native/tests/NavClickTests.cs` | Klickstrahl → Bodentreffer (rein) | 6 |
| `native/Figures/PlayerSteering.cs`, `native/Figures/AvatarRoomsController.cs`, `native/App/MainEmbody.cs`, `native/App/MainHud.cs`, `native/fixtures/nav/pos_answers.json` | Boden-Klick, Klick-Laufen, Link-Ritt, Klemme | 6 |
| `native/World/NavOverlay.cs`, `native/Main.cs`, `native/Hud/HudOverlay.cs` | Overlay + F9 | 7 |
| `docs/superpowers/specs/2026-11-25-client-ausfuehrung-design.md` | Abschnitt 9 „E2 umgesetzt“ | 8 |

---

## Die Nav-Welt (`native/fixtures/nav/`) — Herleitung, gilt für alle Tasks

Location `loc-nav` „Navhaus“ bei Welt (100, 0), yaw 0, flaches Höhenfeld 0 → Datum 0, `TileToWorld(lx, lz, ly) = (100 + lx, ly, lz)`. `storey_m` 3, `levels` 0 / 1 bei `floor_y` 0 / 3, `boundary` x −6…6, z −7…4 (südlich von W1 ein 3 m tiefer Hof). Avatar „Nia Nav“ in `r-a` bei Welt (97, −1).

| Teil | Tile-Daten | Welt |
|---|---|---|
| Räume | `r-a` (0, x −6…0), `r-b` (0, x 0…6), `r-up` (1, x 0…6); `floor_plan` für `r-a`, `r-b` | |
| Wände Ebene 0 (t 0,2, h 3) | W1a (−6,−4)→(−3.45,−4), W1b (−2.55,−4)→(6,−4), W2 (−6,4)→(6,4), W3 (−6,−4)→(−6,4), W4 (6,−4)→(6,4), W5 (0,−4)→(0,1.55), W6 (0,2.45)→(0,4) | |
| Tür D0 (Index 0) | `at_world` (0, 2), `along` (0, 1), Breite 0,9, Räume [r-a, r-b], innen | |
| Tür D1 (Index 1) | `at_world` (−3, −4), `along` (1, 0), Breite 0,9, Räume [r-a], außen (`OutwardNormal` (0, −1)) | Mitte (97, −4) |
| Raum-Eintritt | `pos_answers.json` Szenarien `nav-up` (`POST /play/enter-room` `{room_id: r-up}` → 200, Antwortkörper nach dem Muster von `fixtures/embody/pos_answers.json` „enter-room“) und `nav-up-rejected` (dieselbe Anfrage → 409) | |
| Platte Ebene 1 | `r-up`, Umriss x 0…6, z −4…4, `top_y` 3,0, Loch x 1.5…4.0, z −3.8…−2.8 | |
| Wände Ebene 1 (t 0,2, `base_y` 3, h 2,8) | (0,−4)→(6,−4), (6,−4)→(6,4), (0,4)→(6,4), (0,−4)→(0,4) | |
| Treppe id 1 | `at` (1.5, −3.3), `dir_deg` 90, run 2,5, rise 3, 10 Stufen, Breite 1, `foot` (1.0, 0.0, −3.3), `head` (4.5, 3.0, −3.3), Footprint x 1.5…4.0, z −3.8…−2.8; `stair_tread`-Extra mit `stair: 1` | Fuß (101, 0, −3.3), Kopf (104.5, 3, −3.3) |
| Aufzug | `elevator_pad` Ebene 0 Mitte (5.2, 0.0, 3.2) Größe (1, 0.1, 1); Ebene 1 Mitte (5.2, 3.0, 3.2); `elevator_shaft` | Halte (105.2, 0.05, 3.2), (105.2, 3.05, 3.2) |
| Sessel (Platzhalter) | `r-a`, Anker (−3, −2), w 0,8 d 0,8 h 0,9, `bottom_y` 0 | Box x 96.6…97.4, y 0…0.9, z −2.4…−1.6 |
| Bett (Platzhalter) | `r-b`, Anker (4, 1.5), w 1,4 d 2,0 h 0,5 | Box x 103.3…104.7, y 0…0.5, z 0.5…2.5 |
| Teppich (Platzhalter) | `r-a`, Anker (−3, 2), w 2 d 1,5 h 0,02 | Box x 96…98, y 0…0.02, z 1.25…2.75 |

Modell-Specs nach dem Muster der Platzhalter in `fixtures/storeys/scene_loc-tower.json` (`role "prop"`, `placeholder_dims`, `fix_euler` 0, `yaw_deg` 0, `measure "xyz"`, `max_m` = größte Seite, `anchor`, `bottom_y`, `level`, `room_id`).

**Hergeleitete Werte (r = 0,25; Polygon-Modus exakt, Zellraster 0,05 trifft alle Zahlen):**

- Erodierte Räume: `r-a` x 94.35…99.65 (W3-Fläche −5.9 + r → −5.65; W5-Fläche −0.1 − r → −0.35), z −3.65…3.65; `r-b` x 100.35…105.65; Loft x 100.35…105.65, z −3.65…3.65 ohne Loch-Zone x 101.25…104.25, z ≤ −2.55.
- Lauffläche Ebene 0 (Entscheidung 7): `boundary` + 0,30 nach außen = Welt x 93.7…106.3, z −7.3…4.3. Hof erodiert: x 93.95…106.05 (−6.3 + r = −6.05, 6.3 − r = 6.05; Review-Messung 93.953…106.047), z −7.05 (−7.3 + r) … −4.35 (W1-Außenfläche −4.1 − r). Die Streifen außerhalb von W2/W3/W4 (0,2 m zwischen Wandfläche und versetztem Rand) verschwinden in der Erosion. Hof-Höhe: Gelände 0 (`FollowGround`, flach).
- Siegel D1: x 96.55…97.45, z −4.1…−3.9. Schwelle T1: x 96.8…97.2 (± (0.45 − 0.25)), z −4.35…−3.65 (± (0.1 + 0.25)), Outside, `OuterPoint` (97, −4.35) = Mitte + (0, −1)·0.35; verschweißt mit `r-a` (Kante z −3.65) und Hof (Kante z −4.35).
- Siegel D0: x 99.9…100.1, z 1.55…2.45. Schwelle T0: x 99.65…100.35 (± (0.1 + 0.25)), z 1.8…2.2 (± (0.45 − 0.25)), y 0.
- Sessel erodiert: x 96.35…97.65, z −2.65…−1.35 (Ecken je nach Join gerundet — keine Pfadannahme berührt sie). Bett erodiert: x 103.05…104.95, z 0.25…2.75. Teppich: kein Hindernis (0,02 ≤ 0,25).
- Links: Treppe Owner 65536 = `(1 << 16) | 0`, Start (101, 0, −3.3), Ende (104.5, 3, −3.3), beide auf dem Netz (Abstand 0), Kosten enter 0 / travel 1. Aufzug Owner 131200 = `(2 << 16) | 128`, Start (105.2, 0.05, 3.2), Ende (105.2, 3.05, 3.2), `enter_cost` 20, `travel_cost` 10. Im Pfad trägt nur der **Einstiegspunkt** den Owner; Pfadpunkte liegen auf dem Netz (Aufzug unten (105.2, 0.0, 3.2), oben (105.2, 3.0, 3.2)).
- **P1** (97, 0, −1) → (103, 0, −1): durch T0 über die unteren Ecken (99.65, 0, 1.8) und (100.35, 0, 1.8); Länge 2·√(2.65² + 2.8²) + 0.7 = 2·3.855191 + 0.7 = **8.410382**.
- **P2** (97, 0, −1) → Loft (104, 3, 2): (99.65, 1.8) → (100.35, 1.8) → Treppenfuß (101, −3.3) [√(0.65² + 5.1²) = 5.141255] → Link [√(3.5² + 3²) = 4.609772] → (104, 2) [√(0.5² + 5.3²) = 5.323533; kreuzt die Loch-Zone nicht: bei z −2.55 ist x = 104.5 − 0.5·0.75/5.3 = 104.4292 > 104.25]; Länge 3.855191 + 0.7 + 5.141255 + 4.609772 + 5.323533 = **19.629751** (Review gemessen 19,6307), genau ein Punkt mit Owner ≠ 0, Owner 65536. Rückweg (104, 3, 2) → (97, 0, −1) dieselbe Länge über die Treppe.
- **P3** = P2 mit abgeschalteter Treppe, über den Aufzug: (97, −1) → (99.65, 1.8) [3.855191] → Bettecke (103.05, 2.75) [√(3.4² + 0.95²) = 3.530227; bei x 100.35 ist z = 1.8 + 0.7·0.95/3.4 = 1.9956 ∈ T0 1.8…2.2, die Ecke (100.35, 1.8) entfällt] → Aufzug unten (105.2, 0, 3.2) [√(2.15² + 0.45²) = 2.196588; bei x 104.95 ist z = 3.148 > 2.75, frei vom Bett] → Link [3] → (104, 3, 2) [√(1.2² + 1.2²) = 1.697056]; Länge **14.279062** (Review gemessen 14,279). **Warum P2 trotzdem die Treppe nimmt:** Kosten über den Aufzug ≥ (14.279062 − 3) + 3·10 = 41.28 (ohne `enter_cost`, das 4.7.2 bei der Wahl nicht zuverlässig anrechnet) > 19.63 über die Treppe (travel 1). Mit nur `enter_cost` 20 nahm P2 vorwärts gemessen den Aufzug (14,279).
- **Sonden `MapGetClosestPoint`**: (100.05, 0, 0) in W5 → (100.35, 0, 0) (0,30 zu `r-b` gegen 0,40 zu `r-a`); (97, 0, −1.5) im Sessel-Rand → (97, 0, −1.35); (97, 0, 2) auf dem Teppich → unverändert; (100, 0, 2) in der Tür → unverändert; (97, 0, −5.5) im Hof → unverändert; (97, 0, −7.2) jenseits des Hofs → (97, 0, −7.05).
- **Zugang Sessel** (Server-Regel: Boxkante + `ACCESS_BODY_R_M` 0,15): (97, 0, −1.45) → Lücke zum Netz 0,10 ≤ 0,4; das gerade Schlussstück (97, −1.35)→(97, −1.45) schneidet keine Wand.

---

### Task 1: Core-Quelle `NavSource` + Nav-Szene

**Files:**
- Create: `native/Core/Nav/NavTypes.cs`, `native/Core/Nav/NavBakeParams.cs`, `native/Core/Nav/NavSource.cs`, `native/tests/NavSourceTests.cs`, `native/fixtures/nav/scene_loc-nav.json`
- Modify: `native/fixtures/README.md` (neuer Abschnitt „Nav world (`nav/`, E2, `Check/NavCheck.cs`, `--check nav`)“ mit der Tabelle und den Herleitungen oben)
- Commit mit: dieser Plan `docs/superpowers/plans/2026-11-25-client-ausfuehrung-e2.md` (`git add -f`)

**Interfaces:**
- Consumes: `ScenePayload`, `SceneWall`, `SceneDoorway`, `ScenePlate`, `SceneFloor` (`Core/World/Payloads.cs`, `Core/World/SceneParts.cs`), `TileFrame` + `SceneView.TileToWorld` (`Core/Scene/SceneView.cs:22/161`), `PlaceInventory.Stairs` / `.ElevatorStops` (`Core/Scene/ScenePlaces.cs:115`), `Vec3` (`AnimaNative.Overview`), `P2` (`AnimaNative.Scatter`).
- Produces (Namespace `AnimaNative.Nav`):
  - `public sealed record NavFloor(P2[] Outline, P2[][] Holes)` — Welt-xz.
  - `public sealed record NavObstacle(P2[] Outline, double BottomY, double TopY, string Kind)` — `Kind` ∈ `"wall" | "seal" | "prop"`.
  - `public sealed record NavThreshold(int Doorway, int Level, P2[] Quad, double Y, string[] Rooms, bool Outside, P2? OuterPoint)` — `Quad` immer in der Reihenfolge (x0, z0) → (x1, z0) → (x1, z1) → (x0, z1) im Welt-xz mit x0 < x1, z0 < z1 (nach jedem Yaw neu sortiert; Shoelace-Fläche in (x, z) = +(x1 − x0)(z1 − z0) > 0 — umgekehrt verschweißt Godot nicht, gemessen `connections = 0`); `Outside` = `SceneDoorway.Outside` (Review N-W2: Außentüren kommen **nur** aus diesem Flag, nicht aus Raumzahl oder Lage); `OuterPoint` nur bei `Outside`: Schwellenmitte + Außennormale · (t/2 + r); Normale = `SceneDoorway.OutwardNormal`, fehlt sie (null oder (0, 0)), dann `(along.z, −along.x)` — dieselbe Regel wie `_door_outward` (`app/core/scene_recipe.py:1235`, Raumhülle im Uhrzeigersinn) —, beides gedreht wie `SceneView.TileDirToWorld`.
  - `public sealed record NavLinkSpec(ulong Owner, string Kind, Vec3 Start, Vec3 End, int FromLevel, int ToLevel, double EnterCost)` — `Kind` ∈ `"stairs" | "elevator"`.
  - `public sealed record NavStoreySource(int Level, double FloorY, bool FollowGround, IReadOnlyList<P2[]> Hulls, IReadOnlyList<NavFloor> Floors, IReadOnlyList<NavObstacle> Obstacles)` — `FollowGround`: Vertices außerhalb aller `Hulls` auf `groundAt(x, z)`, innerhalb auf `FloorY` (Entscheidung 7). `NavFloor.Holes` enthält nur Löcher, die keine andere Platte der Ebene überdeckt.
  - `public sealed record NavProblem(string Kind, int Doorway)`
  - `public sealed record NavSourceData(IReadOnlyList<NavStoreySource> Storeys, IReadOnlyList<NavThreshold> Thresholds, IReadOnlyList<NavLinkSpec> Links, IReadOnlyList<NavProblem> Problems, string Fingerprint)` + `bool IsEmpty` (keine Lauffläche).
  - `public readonly record struct NavPropBox(int Level, Vec3 Min, Vec3 Max)`
  - `public static class NavLayers { uint ForLevel(int level); const uint Links = 1u << 31; const uint All = uint.MaxValue; }`
  - `public static class NavLinkOwner { ulong Stairs(int flight); ulong Elevator(int lowerLevel); bool TryStairs(ulong owner, out int flight); bool TryElevator(ulong owner, out int lowerLevel); }`
  - `public enum NavBakeMode { Polygon, Voxel }`; `public sealed record NavBakeParams(NavBakeMode Mode, double AgentRadius, double AgentHeight, double AgentMaxClimb, double AgentMaxSlopeDeg, double CellSize, double CellHeight, double EdgeConnectionMargin, double LinkConnectionRadius)` mit `static NavBakeParams For(NavBakeMode mode)` (= `Create(mode, <Modus-Zelle>, <Modus-Zellhöhe>)`), `public static NavBakeParams Create(NavBakeMode mode, double cellSize, double cellHeight)` (die einzige Stelle, die klemmt), `const int Version = 1`, `const double MinCellSize = 0.05`, `const double ElevatorEnterCost = 20`, `const double ElevatorTravelCost = 10`. Werte: beide Modi Radius 0,25, Höhe 1,8, Climb 0,25, Slope 40° (`max_slope_deg`-Default, `WorldBuilder.Embody.cs:90`), Link-Radius 0,6; Polygon Zelle 0,05 / 0,05, Margin 0,1; Voxel Zelle 0,1 / 0,1, Margin 0,25. `For` klemmt `CellSize`/`CellHeight` auf `≥ MinCellSize`.
  - `public static NavSourceData NavSource.Build(ScenePayload scene, TileFrame frame, PlaceInventory places, IReadOnlyList<NavPropBox> props, bool building, NavBakeParams p)`

- [ ] **Step 1: Szene-Fixture schreiben** — `native/fixtures/nav/scene_loc-nav.json` exakt nach der Tabelle „Die Nav-Welt“ (Felder wie `fixtures/walk/scene_loc-hall.json`, Signatur `"nav-house"`, `style` von dort kopiert, `doorways` mit `usable`-fähigen Feldern `at_world`/`along`/`width_m`).

- [ ] **Step 2: Failing tests schreiben** (`native/tests/NavSourceTests.cs`; Fixture-Pfad über denselben Repo-Wurzel-Helfer, den `tests/PropWaterVectorTests.cs` für `shared/test-vectors` nutzt; `frame = new TileFrame(new Vec3(100, 0, 0), 0)`; `places = PlaceInventory.Compose(scene, frame, null, null)`; Props = die drei Boxen der Tabelle). Docstring zitiert die Herleitung aus „Die Nav-Welt“.

```csharp
[Fact] public void StoreysFloorsAndHeights()      // 2 Stockwerke; Ebene 0: 3 Böden (boundary-Ring versetzt: Bounds x 93.7…106.3, z −7.3…4.3; 2× floor_plan) bei y 0, FollowGround true, 2 Hulls; Ebene 1: 1 Boden mit 1 Loch bei y 3.0, FollowGround false
[Fact] public void ObstacleCountsPerStorey()      // Ebene 0: 7 wall (W1a, W1b, W2–W6) + 2 seal + 2 prop = 11; Ebene 1: 4 wall
[Fact] public void PartyWallRectangle()           // W5 → Outline-Bounds x 99.9…100.1, z −4…1.55 (±1e-9), BottomY 0, TopY 3
[Fact] public void DoorSealAndThreshold()         // Siegel x 99.9…100.1, z 1.55…2.45; T0 Quad-Bounds x 99.65…100.35, z 1.8…2.2, Y 0, Rooms {r-a,r-b}, Outside false, OuterPoint null
[Fact] public void OutsideDoorThreshold()         // Siegel D1 x 96.55…97.45, z −4.1…−3.9; T1 x 96.8…97.2, z −4.35…−3.65, Rooms {r-a}, Outside true, OuterPoint (97, −4.35)
[Fact] public void OutsideDoorWithoutNormalUsesAlong() // Szene-Kopie: D1 ohne outward_normal → OuterPoint (97, −4.35) (along (1,0) → (0, −1)); D0 (Outside false) bleibt ohne OuterPoint
[Fact] public void BoundaryOffsetLShape()         // reine OffsetRing-Probe: L (0,0)(6,0)(6,3)(3,3)(3,6)(0,6), d 0,3 → (−0.3,−0.3)(6.3,−0.3)(6.3,3.3)(3.3,3.3)(3.3,6.3)(−0.3,6.3) ±1e-9 (konkave Ecke (3,3) → (3.3,3.3): Schnitt von z = 3.3 und x = 3.3); dieselbe Eingabe rückwärts gewickelt → dieselben Punkte; Kerbe 0,4 breit → unversetzter Ring + Problem boundary_offset
[Fact] public void ThresholdQuadOrder()           // T0 und T1: Quad[0] = (x0,z0), Quad[1] = (x1,z0), Quad[2] = (x1,z1), Quad[3] = (x0,z1); Shoelace-Fläche > 0
[Fact] public void NarrowDoorHasSealNoThreshold() // Szene-Kopie mit width_m 0.45 und Wänden bis 1.775/2.225 → D0 hat ein Siegel und keine Schwelle (gesamt 2 seals, 1 threshold = T1), Problems == [("door_too_narrow", 0)]
[Fact] public void DoorWithoutWallIsOpenFloor()   // Szene-Kopie ohne W5/W6 → für D0 weder Siegel noch Schwelle (übrig: Siegel + Schwelle von D1), keine Problems
[Fact] public void OverlappingPlatesKeepCoveredHoleOpen() // Szene-Kopie mit zweiter, deckungsgleicher Ebene-1-Platte ohne Loch → Ebene 1: 2 Böden, beide Holes leer (das Loch ist überdeckt)
[Fact] public void CorridorIsFloor()              // Szene-Kopie mit einem Korridor (Ebene 1, Umriss x 0…6, z 3…4) → Ebene 1: 2 Böden, der Korridor in Welt-Metern x 100…106, z 3…4
[Fact] public void StairAndElevatorLinks()        // 2 Links: (65536, stairs, (101,0,−3.3)→(104.5,3,−3.3), 0→1, cost 0); (131200, elevator, (105.2,0.05,3.2)→(105.2,3.05,3.2), 0→1, cost 20)
[Fact] public void FlatAndOverheadPropsAreNoObstacles() // Teppich (h 0.02) fehlt; zusätzliche Box Lampe y 1.9…2.2 fehlt; Bett-Rechteck x 103.3…104.7, z 0.5…2.5 vorhanden
[Fact] public void YawTurnsThresholdIntoWorld()   // frame yaw π/2 → T0-Bounds x 101.8…102.2, z −0.35…0.35 (x = 100 + lz, z = −lx); Eckenreihenfolge wie ThresholdQuadOrder, Shoelace-Fläche > 0
[Fact] public void FingerprintStableAndSensitive()// zweimal Build → gleich; Sessel-Box 0.01 m verschoben → anders; Modus Voxel → anders
[Fact] public void LayerAndOwnerEncoding()        // NavLayers.ForLevel(0) == 1u<<8, ForLevel(1) == 1u<<9, ForLevel(-30) == 1u; Stairs(0)==65536; Elevator(0)==131200; TryStairs round-trip
[Fact] public void CellSizeFloor()                // NavBakeParams.Create(NavBakeMode.Voxel, 0.01, 0.01) → CellSize 0.05, CellHeight 0.05; For(Voxel) == Create(Voxel, 0.1, 0.1)
```

- [ ] **Step 3: Tests laufen lassen, Fehlschlag sehen**
Run: `dotnet test native/tests --filter FullyQualifiedName~NavSourceTests`
Expected: FAIL (Typen fehlen, Build-Fehler).

- [ ] **Step 4: Typen und `NavSource.Build` implementieren** nach Entscheidungen 2, 7, 8, 13 (Korridore aus `scene.Corridors`, `SceneParts.cs:60`). Wände über `Collide.WallSegments`-Filterregel (nicht die Funktion selbst — die liefert keine Dicke), Platten-/Raumhöhen über `scene.FloorY(level)` und `ScenePlate.TopY`, Treppen/Aufzug aus `places` (schon Welt-Meter). Fingerabdruck: Zahlen mit `ToString("R", CultureInfo.InvariantCulture)` in fester Reihenfolge in einen Text, dazu `p.Mode` und `NavBakeParams.Version`, dann `SHA256.HashData` → Hex.

- [ ] **Step 5: Tests grün**
Run: `dotnet test native/tests --filter "FullyQualifiedName~NavSourceTests|FullyQualifiedName~CoreIsGodotFree"` → PASS; danach `dotnet test native/tests` → PASS.

- [ ] **Step 6: README-Abschnitt „Nav world“** mit Tabelle + Herleitungen (Abschnitt „Die Nav-Welt“ dieses Plans, wortgleich in Englisch).

- [ ] **Step 7: Commit**
```bash
git add native/Core/Nav/NavTypes.cs native/Core/Nav/NavBakeParams.cs native/Core/Nav/NavSource.cs native/tests/NavSourceTests.cs native/fixtures/nav/scene_loc-nav.json native/fixtures/README.md
git add -f docs/superpowers/plans/2026-11-25-client-ausfuehrung-e2.md
git commit -m "feat(native-nav): Godot-free navmesh source with door seals, thresholds and links" -- native/Core/Nav/NavTypes.cs native/Core/Nav/NavBakeParams.cs native/Core/Nav/NavSource.cs native/tests/NavSourceTests.cs native/fixtures/nav/scene_loc-nav.json native/fixtures/README.md docs/superpowers/plans/2026-11-25-client-ausfuehrung-e2.md
```

---

### Task 2: Core-Pfadschicht — `IPathProvider`, `NavClamp`, `NavRoutePlanner`, `NavRoute`

**Files:**
- Create: `native/Core/Nav/NavPaths.cs`, `native/Core/Nav/NavClamp.cs`, `native/Core/Nav/NavRoute.cs`, `native/tests/FakePathProvider.cs`, `native/tests/NavRouteTests.cs`

**Interfaces:**
- Consumes: `Vec3`, `P2`, `ClickMove.GoalArriveM` (0,2), `Stairs.RideArriveM` (0,4).
- Produces:
  - `public sealed record NavPath(IReadOnlyList<Vec3> Points, IReadOnlyList<ulong> Owners, double Length)` — `Owners[i]` = Link-Owner des Punkts `i`, 0 = Region (aus `PathTypes`/`PathOwnerIds`). Vertrag (Entscheidung 13): `Owners[i] ≠ 0` ⇒ Link-Abschnitt `(Owners[i], Points[i], Points[i + 1])`; nur der Einstiegspunkt trägt den Owner.
  - `public interface IPathProvider { bool Ready { get; } NavPath Query(Vec3 from, Vec3 to); Vec3 Closest(Vec3 p); }`
  - `public static class NavClamp { const double OnMeshTolM = 0.02, DeeperEpsM = 1e-4; P2 Step(P2 from, P2 to, double y, double storeyHeight, IPathProvider nav); }` — Regel: `dTo = |to − Closest(to)|`; `dTo ≤ tol` → `to`; `dFrom = |from − Closest(from)|`; `dTo ≤ dFrom + DeeperEpsM` → `to` (zurück zum Netz oder nicht tiefer hinein; das Epsilon macht den Parallelgang im Möbel unabhängig vom Float-Rauschen); sonst `dFrom ≤ tol` → `Closest(to)` (gleitet an der Kante), sonst `from`. Alle Abstände horizontal; `Closest` (3D, über alle Stockwerke) gilt nur, wenn `|Closest.Y − y| < storeyHeight / 2`, sonst zählt der Punkt als unendlich weit vom Netz (ein Netzpunkt direkt über/unter dem Avatar ist kein „auf dem Netz“).
  - `public abstract record NavStep; public sealed record NavWalk(IReadOnlyList<Vec3> Points) : NavStep; public sealed record NavLink(ulong Owner, Vec3 Start, Vec3 End) : NavStep;`
  - `public sealed record NavPlan(IReadOnlyList<NavStep> Steps, Vec3 Goal, double Length)`
  - `public static class NavRoutePlanner { const double OnMeshM = 0.3, UnreachableM = 0.5; NavPlan? Plan(IPathProvider nav, Vec3 from, Vec3 to, Func<double, double, bool> insideFootprint, IReadOnlyList<P2> outsideDoors, double outsideY); }` — Fälle: (1) beide auf dem Netz → `Query`; endet der Pfad weiter als `UnreachableM` vom Ziel → `null`. (2) Start auf dem Netz, Ziel außerhalb des Grundrisses → je Außentür `Query(from, door)` + gerade zum Ziel, kürzeste Summe; ohne Außentür → `null` (Aufrufer nimmt den alten geraden Weg). (3) Start auf dem Netz, Ziel im Grundriss aber neben dem Netz (Möbel) → `Query(from, Closest(to))`, Ziel = `Closest(to)` (Klick ins Möbel hält an seiner Kante). (4) Start außerhalb des Grundrisses → `null` (der Aufrufer nimmt den heutigen geraden Weg samt `Blocked`/`PlayerBlocked`; ein Klick von draußen in einen fremden Grundriss bleibt abgelehnt wie `EmbodyWalkCheck.cs:136`, Eintritt und Schloss laufen weiter über ihren heutigen Weg — Review W5). (5) beide neben dem Netz → `null`. Ein Pfad wird an Link-Punkten in `NavWalk`/`NavLink`-Abschnitte zerlegt.
  - `public sealed class NavRoute { NavRoute(NavPlan plan); NavStep Current { get; } Vec3? Next { get; } Vec3 Final { get; } bool Done { get; } bool RideRequested { get; } NavRouteEvent Tick(Vec3 pos, double dt); void LinkResult(bool started); void LinkFinished(); }` — `Next` = die nächste anzulaufende Ecke (null während eines Link-Abschnitts), `Final` = Endziel (`NavPlan.Goal`). Nach `AtLink` steht `RideRequested`; `LinkResult(false)` → der nächste `Tick` liefert `Abort`; `LinkResult(true)` → die Route wartet auf `LinkFinished()`. Mit `public enum NavRouteEvent { None, AtLink, Replan, Abort, Arrived }`; Konstanten `StuckSpeedMS = 0.05`, `StuckSeconds = 2`, `DeviationM = 1`, `CornerArriveM = ClickMove.GoalArriveM`, `LinkArriveM = Stairs.RideArriveM`. Feststecken: horizontale Geschwindigkeit < 0,05 m/s für 2 s → `Replan`, beim zweiten Mal → `Abort` (Spec 6); Abstand zum aktuellen Segment > 1 m → `Replan`.

- [ ] **Step 1: Failing tests** (`NavRouteTests.cs`; `FakePathProvider` = Polygon-Welt aus achsparallelen Rechtecken mit Rechteck-Löchern: `Closest` = nächster Punkt, `Query` = vorgegebene Antwort je (from, to) oder Gerade, `Ready` true):

```csharp
[Fact] public void OnMeshStepPassesThrough()            // Netz x 0…10, z 0…10: (5,5)→(5.2,5) → (5.2,5)
[Fact] public void StepIntoObstacleSlidesToEdge()       // Loch x 4…6, z 4…6 (= erodierter Sessel): (5,3.9)→(5,4.1) → (5,4.0)
[Fact] public void OffMeshStartMayApproachMesh()        // from (5,4.5) im Loch, to (5,4.3) → to (dTo 0.3 ≤ dFrom 0.5)
[Fact] public void OffMeshStartMayNotGoDeeper()         // from (5,4.3), to (5,4.6) → from
[Fact] public void ParallelInsideObstacleIsStable()     // from (5,4.3), to (5.1,4.3) (gleich tief, dTo == dFrom bis auf 1e-12) → to
[Fact] public void OtherStoreyIsNotOnMesh()             // Fake liefert Closest mit Y + 3 (Stockwerk darüber), storeyHeight 3 → wie neben dem Netz: from bleibt
[Fact] public void PlanSplitsAtLink()                   // Query liefert Punkte A,B,L1,L2,C mit Owners 0,0,65536,0,0 (nur der Einstieg markiert, wie 4.7.2 liefert) → Steps Walk[A,B,L1], Link(65536,L1,L2), Walk[L2,C]
[Fact] public void UnreachableReturnsNull()             // Query endet 0.6 vor dem Ziel → null
[Fact] public void ClickIntoFurnitureStopsAtEdge()      // Loch x 4…8, z 4…5.5; Ziel (6,4.6) → Goal (6,4) (0.6 zur Kante z 4 gegen 0.9 zu z 5.5), Route endet dort
[Fact] public void OutsideTargetRoutesViaOutsideDoor()  // Türen (0,5) und (10,5), Ziel (−3,5) außerhalb → Pfad über (0,5), Goal (−3,5), Länge = Query-Länge + 3
[Fact] public void OutsideTargetWithoutDoorFallsBack()  // keine Außentür → null
[Fact] public void StuckTwiceAborts()                   // Tick mit gleicher Position, dt 0.5: nach 2 s Replan, nach weiteren 2 s Abort
[Fact] public void DeviationReplans()                   // Position 1.2 m neben dem Segment → Replan
[Fact] public void LinkWaitsForFinish()                 // an L1 (≤ 0.4) → AtLink, RideRequested; LinkResult(true); weitere Ticks None ohne Fortschritt; LinkFinished() → nächster Walk, Next = C, Final = C
[Fact] public void LinkRejectedAborts()                 // an L1 → AtLink; LinkResult(false) → nächster Tick Abort
```

- [ ] **Step 2: Fehlschlag sehen** — `dotnet test native/tests --filter FullyQualifiedName~NavRouteTests` → FAIL (Build).
- [ ] **Step 3: Implementieren** nach den Signaturen oben; während eines `NavLink`-Abschnitts zählt `Tick` weder Feststecken noch Abweichung.
- [ ] **Step 4: Grün** — `dotnet test native/tests` → PASS.
- [ ] **Step 5: Commit**
```bash
git add native/Core/Nav/NavPaths.cs native/Core/Nav/NavClamp.cs native/Core/Nav/NavRoute.cs native/tests/FakePathProvider.cs native/tests/NavRouteTests.cs
git commit -m "feat(native-nav): path provider seam, navmesh clamp and route planner/follower" -- native/Core/Nav/NavPaths.cs native/Core/Nav/NavClamp.cs native/Core/Nav/NavRoute.cs native/tests/FakePathProvider.cs native/tests/NavRouteTests.cs
```

---

### Task 3: Godot-Bake und Maps — `NavBake`, `LocationNav`, `--check nav` (direkt aus der Quelle)

**Files:**
- Create: `native/World/NavBake.cs`, `native/World/NavMaps.cs`, `native/Check/NavCheck.cs`, `native/fixtures/nav/{locations.json,worldmap.json,urls.json,heightfield.json,terrain.json,model3d.json}` (Höhenfeld/Terrain/Urls als Kopie von `fixtures/walk/`; Worldmap: nur `loc-nav` bei (100, 0) yaw 0 und Avatar „Nia Nav“ in `r-a` bei (97, −1); `model3d.json` `{"Nia Nav": null}`)
- Modify: `native/Check/CheckRunner.cs` (`only == "nav"` + Aufruf im Gesamtlauf + Feld in der `CHECK ok`-Zeile), `native/Cli.cs` (Hilfezeile `--check nav | --check=nav` **und** `nav` in `IsSection` sowie in die Liste der `ArgumentException`-Meldung von `CheckSection`, `Cli.cs:251–257` — sonst wird `--check=nav` abgewiesen), `native/fixtures/README.md` (Abschnitte N0–N8)

**Interfaces:**
- Consumes: Task 1 (`NavSourceData`, `NavBakeParams`, `NavLayers`, `NavLinkOwner`), Task 2 (`IPathProvider`, `NavPath`), `Locks.DoorwayLock` (`Core/Embody/Locks.cs`), `Earcut.Triangulate` (`Core/Scene/Earcut.cs:30`).
- Produces:
  - `public static class NavBake { Task<NavigationMesh[]> BakeStoreysAsync(NavSourceData src, NavBakeParams p, Func<double, double, double>? groundAt); NavigationMesh ThresholdMesh(NavThreshold t, NavBakeParams p); }` — Rückgabe parallel zu `src.Storeys`. Polygon: je Stockwerk `NavigationMeshSourceGeometryData2D` (`AddTraversableOutline` je Boden, `AddObstructionOutline` je Loch und je Hindernis, dessen Höhenband den Gehraum schneidet), `NavigationPolygon { AgentRadius, CellSize }`, `NavigationServer2D.BakeFromSourceGeometryDataAsync(poly, data, callback)`, dann `poly.GetNavigationMesh()`, Vertices auf `FloorY` bzw. `groundAt` gehoben, `CellSize`/`CellHeight` = Map-Werte. Voxel: `NavigationMeshSourceGeometryData3D.AddFaces` (Earcut je Boden mit Löchern), `AddProjectedObstruction(outline at BottomY, BottomY, TopY − BottomY, carve: false)`, `NavigationMesh` mit `AgentRadius/Height/MaxClimb/MaxSlope/CellSize/CellHeight`, `NavigationServer3D.BakeFromSourceGeometryDataAsync`. Der Callback (kommt auf dem Main-Thread im Server-Sync an) setzt nur ein `new TaskCompletionSource<…>(TaskCreationOptions.RunContinuationsAsynchronously)`, damit die Fortsetzung nicht innerhalb des Server-Syncs Regionen anlegt; der Aufrufer awaitet auf dem Main-Thread (Godot-SynchronizationContext). Schwelle: Rechteck als `NavigationPolygon` (`SetVertices` + `AddPolygon`) → `GetNavigationMesh()` → gehoben — dieselbe Umwandlung wie der Polygon-Modus, damit die Wicklung stimmt.
  - `public sealed class LocationNav : IPathProvider` — Felder `Rid Map`, `IReadOnlyList<Rid> Storeys`, `IReadOnlyDictionary<int, Rid> Thresholds` (Schlüssel Doorway-Index), `IReadOnlyDictionary<ulong, Rid> Links`, `string Fingerprint`, `NavSourceData Source`, `NavBakeMode Mode`; `static LocationNav Create(NavSourceData src, NavigationMesh[] storeys, NavBakeParams p)` (Entscheidungen 4, 13; Regionen `RegionSetMap`, `RegionSetNavigationMesh`, `RegionSetNavigationLayers`, `RegionSetOwnerId`; `MapSetUseAsyncIterations(Map, false)`, je Region `RegionSetUseAsyncIterations(rid, false)`; Links `LinkCreate`, `LinkSetMap`, `LinkSetStartPosition`, `LinkSetEndPosition`, `LinkSetBidirectional(true)`, `LinkSetEnterCost`, `LinkSetTravelCost` (Aufzug 10, Treppe 1), `LinkSetNavigationLayers(NavLayers.Links)`, `LinkSetOwnerId`); `ulong ChangedAtIteration` (beim Erzeugen 0; = aktuelle `MapGetIterationId` **nur** wenn `ApplyLocks`/`SetLinkEnabled` wirklich einen Region-/Link-Zustand umschalten, Vergleich über `RegionGetEnabled`/`LinkGetEnabled`, Review N-B1); `bool Ready => NavigationServer3D.MapGetIterationId(Map) > ChangedAtIteration` (Entscheidung 4 — **nicht** `> 0`, Review B4); `bool ApplyLocks(IReadOnlyDictionary<string, string>? locks, string avatarRoom)`; `bool SetLinkEnabled(ulong owner, bool on)` (beide: `true` = etwas hat sich geändert); `void Free()`; `IPathProvider`: `Query` über `NavigationServer3D.QueryPath(NavigationPathQueryParameters3D { Map, StartPosition, TargetPosition, NavigationLayers = NavLayers.All, MetadataFlags = All }, result)` → `NavPath(result.Path, owners, result.PathLength)` mit `owners[i] = PathTypes[i] == Link ? PathOwnerIds[i] : 0` (nur der Einstiegspunkt ist Link, Vertrag `NavPath`); `Closest` = `MapGetClosestPoint`.
  - `public static class NavCheck { Task<string> RunAsync(Node3D host, string fixtures); }`

- [ ] **Step 1: Check zuerst schreiben** (`NavCheck.RunAsync`; Quelle direkt aus `fixtures/nav/scene_loc-nav.json` + den drei Hand-Boxen, Modus `NavBakeParams.For(NavBakeMode.Polygon)`; Bereitschaft: `await host.ToSignal(host.GetTree(), SceneTree.SignalName.PhysicsFrame)` bis `Ready`, höchstens 120 Frames, sonst Fehler; dieselbe Wartefunktion `AwaitReady(nav)` nach jeder Änderung in N6/N7). Abschnitte, alle Zahlen aus „Die Nav-Welt“, Toleranz 0,05 m (Polygon) und Länge ±0,05:
  - **N0** 2 Stockwerks-Regionen, 2 Schwellen, 2 Links; `MapGetLinkConnectionRadius` 0,6; gleich nach dem ersten `Ready`: `Closest((97, 0, −1))` = (97, 0, −1) ± 0,05 (keine leere Map, Review B4).
  - **N1** `RegionGetConnectionsCount(T0) == 2` (an `r-a` und `r-b` verschweißt), `RegionGetConnectionsCount(T1) == 2` (an `r-a` und den Hof).
  - **N2** die sechs Sonden `Closest` (inkl. Hof und jenseits des Hofs); zusätzlich je Wand eine Sonde 0,05 m innerhalb der Wandfläche → Ergebnis-Abstand zur Wandfläche = 0,25 (Kantenfehler protokollieren: `[check-nav] edge_error max=<m>`).
  - **N3** jeder Link: `|End − Closest(End)| ≤ 0,6` und `|Start − Closest(Start)| ≤ 0,6` (sonst still deaktiviert, Spec 5d); Zugang Sessel: Lücke 0,10 ± 0,05 ≤ 0,4, Schlussstück schneidet kein `Collide.WallSegments`-Segment.
  - **N4** P1: Länge 8.410 ± 0,05, Punkte enthalten (99.65, 0, 1.8) und (100.35, 0, 1.8) ± 0,05, kein Link.
  - **N5** P2: Länge 19.630 ± 0,05, genau ein Punkt mit Owner ≠ 0, Owner 65536, letzter Punkt (104, 3, 2) ± 0,05; **Rückweg** (104, 3, 2) → (97, 0, −1): ebenfalls 19.630 ± 0,05 über Owner 65536 (Linkwahl in beiden Richtungen, Review W2).
  - **N6** `SetLinkEnabled(65536, false)` → `AwaitReady` → P3 über Owner 131200, Länge 14.279 ± 0,05 (Weglänge, nicht Kosten; P3 in „Die Nav-Welt“), Einstiegspunkt (105.2, 0.0, 3.2) ± 0,05; wieder an.
  - **N7** `ApplyLocks({r-b: ""}, "r-a")` → `AwaitReady` → P1 endet ≥ 0,5 m vor dem Ziel; `ApplyLocks(null, "r-a")` → P1 wieder 8.410; `ApplyLocks({r-b: ""}, "r-b")` → offen (eigener Raum ausgenommen, `Locks.DoorwayLock`). **N7b** (Review N-B1): `ApplyLocks(null, "r-a")` zweimal hintereinander → der zweite Aufruf gibt `false` zurück, `ChangedAtIteration` unverändert, `Ready` bleibt `true` (kein Warten); ebenso `SetLinkEnabled(65536, true)` auf eingeschaltetem Link → `false`.
  - **N8** `Free()` → nach zwei Physik-Frames (gemessen: im selben Frame noch der alte Wert) `NavigationServer3D.GetProcessInfo(ProcessInfo.ActiveMaps)` wieder auf dem Ausgangswert.
- [ ] **Step 2: Fehlschlag sehen** — `cd native && dotnet build -nologo -v quiet` → Build-Fehler (Typen fehlen).
- [ ] **Step 3: `NavBake`, `LocationNav` implementieren**, `CheckRunner`/`Cli` verdrahten, README N0–N8 ergänzen.
- [ ] **Step 4: Check grün** — `$GODOT --headless --path native -- --check nav` → `CHECK ok …`; dann `GODOT=… native/test.sh` → `== all native checks passed`.
- [ ] **Step 5: Commit** (alle neuen `.cs` mit ihren `.cs.uid`)
```bash
git add native/World/NavBake.cs native/World/NavBake.cs.uid native/World/NavMaps.cs native/World/NavMaps.cs.uid native/Check/NavCheck.cs native/Check/NavCheck.cs.uid native/Check/CheckRunner.cs native/Cli.cs native/fixtures/nav native/fixtures/README.md
git commit -m "feat(native-nav): bake storeys, door thresholds and links into a per-location navigation map" -- native/World/NavBake.cs native/World/NavBake.cs.uid native/World/NavMaps.cs native/World/NavMaps.cs.uid native/Check/NavCheck.cs native/Check/NavCheck.cs.uid native/Check/CheckRunner.cs native/Cli.cs native/fixtures/nav native/fixtures/README.md
```

---

### Task 4: Backen beim Mounten — `WorldBuilder.Nav`

**Files:**
- Create: `native/World/WorldBuilder.Nav.cs`
- Modify: `native/World/WorldBuilder.cs` (`LocationSlot.Nav`: `public LocationNav? Nav { get; internal set; }`; `SetLocks` ruft zusätzlich `slot.Nav?.ApplyLocks(...)` je Slot, Entscheidung 3; kein festes `MapChanged`-Abo — An-/Abmeldung in `WorldBuilder.Nav.cs`, Entscheidung 4 / Review N-W1), `native/World/WorldBuilder.Stands.cs` (letzte Zeile von `DeriveStands`: `RequestNavBake(slot)`; die Prop-Boxen werden **einmal** pro `DeriveStands` gemessen — `MeasurePropBoxes(slot)` liefert die Liste, aus der `RoomPropBoxes` und `NavPropBoxes` lesen, statt zweimal alle Props zu vermessen), `native/World/WorldBuilder.Residency.cs` (direkt nach `slot.Ring = Ring.Near` bei `:190`: `RequestNavBake(slot)`, Entscheidung 5 / Review B1; `FreeSlot`: `ReleaseNav(slot)`; `StopResidency` (`:118`): alle ausstehenden Maps freigeben und `MapChanged` abmelden, Review N-W1), `native/Check/NavCheck.cs` (Abschnitte N9–N12), `native/fixtures/README.md`

**Interfaces:**
- Consumes: Task 1–3; `slot.Scene`, `slot.Stands.Frame`, `slot.Places`, `slot.Placements`, `slot.IsBuilding`, `slot.Ring`, `slot.Generation`, `Height.GroundAt`.
- Produces (in `WorldBuilder`):
  - `public NavBakeMode NavMode { get; set; } = NavBakeMode.Polygon;` (Task 5 entfernt die Eigenschaft wieder)
  - `internal void RequestNavBake(LocationSlot slot)` — Ring ≠ Near oder leere Quelle → `ReleaseNav`; gleicher Fingerabdruck wie `slot.Nav` → nichts; Bake läuft schon → nur „neuester Fingerabdruck“ merken; sonst Cache-Treffer (16er-LRU `fingerprint → NavigationMesh[]`) oder `NavBake.BakeStoreysAsync`; nach Abschluss verwerfen, wenn `slot.Generation` sich geändert hat, der Slot nicht mehr in `_slots` steht oder ein neuerer Fingerabdruck wartet (dann neu anfordern); sonst `LocationNav.Create` als **ausstehende** Navigation (erste ausstehende → `MapChanged` anmelden), die der `MapChanged`-Handler scharf schaltet (Entscheidung 4: `ApplyLocks(_locks)`; `false` → sofort Tausch, `true` → beim nächsten `MapChanged` dieser Map mit `Ready` tauschen; danach alte frei; keine ausstehende mehr → abmelden). Logzeile je Bake: `[nav] bake loc=<id> mode=<m> storeys=<n> thresholds=<t> links=<l> ms=<x> cache=<hit|miss>`.
  - `internal void ReleaseNav(LocationSlot slot)` (gibt aktive **und** ausstehende Map frei), `private void OnNavMapChanged(Rid map)` (kein Frame-Tick: `TickProps` läuft aus `App/MainLights.cs:74`, die Checks rufen ihn nicht — Review W3), `public LocationNav? NavFor(LocationSlot? slot)` (nur getauschte; bleibt nach `SetLocks` dieselbe, auch wenn sie bis zur nächsten Iteration `Ready == false` meldet — Review N-W4), `internal bool NavMapChangedSubscribed` (für N11/N13), `public event Action<LocationSlot>? NavChanged`.
  - `IReadOnlyList<NavPropBox> NavPropBoxes(LocationSlot slot)` — Entscheidung 8, `Level = rec.Spec.Level`, aus der einmaligen Messung von `DeriveStands`.

- [ ] **Step 1: Check-Abschnitte zuerst** (Welt über `WorldBuilder` wie `WalkCheck`: `new FixtureSource(dir, fixtures)`, `BuildAsync(world, "Navhaus")`, `slot.Fade.Snap(1)`; der Slot muss über den echten Residency-Weg `Ring.Near` werden — wie `ResidencyCheck` es auslöst —, denn erst dort wird gebacken; Frames laufen lassen, bis `NavFor(slot)` nicht null, höchstens 240; **kein** direkter `RequestNavBake`-Aufruf im Check, sonst bliebe B1 unentdeckt):
  - **N9** `NavFor(slot)` fertig; `NavPropBoxes(slot)` = genau 3 Boxen (Sessel, Bett, Teppich — den Teppich filtert erst `NavSource`) mit den Welt-Boxen der Tabelle ± 0,01; Fingerabdruck = der aus Task 1 mit denselben Boxen gebaute; N4 erneut über `NavFor(slot)` → 8.410 ± 0,05.
  - **N10** zweiter `DeriveStands(slot)` ohne Änderung → keine neue Map (gleiche `Map`-Rid); Sessel-Node um 0,5 m verschieben + `DeriveStands` → neue Map nach Synchronisierung, alte frei (`ActiveMaps` unverändert gegenüber vorher).
  - **N11** Bake anstoßen und im selben Frame `UnmountDetail` (über den vorhandenen Residency-Weg, wie `ResidencyCheck` ihn auslöst) → nach 60 Frames `slot.Nav == null`, `ActiveMaps` = Ausgangswert (zwei Physik-Frames nach dem letzten `FreeRid` gemessen; Review Focus 3), `NavMapChangedSubscribed == false`.
  - **N13** (Review N-B1/N-W1): vor dem ersten Bake `NavMapChangedSubscribed == false`; erster Bake ohne Sperre → `NavFor(slot)` ist nach dem **ersten** `MapChanged` der neuen Map gesetzt (gezählt über einen Test-Zähler im Handler, kein zweites `MapChanged` nötig), danach `NavMapChangedSubscribed == false`; `StopResidency` bei laufendem Bake → abgemeldet, `ActiveMaps` zurück auf Ausgangswert.
  - **N12** `SetLocks` mit `r-b` gesperrt, Avatarraum `r-a` → T0 `RegionGetEnabled == false`, im selben Frame liefert `NavFor(slot)` weiter dieselbe Map (Review N-W4); Rebake erzwingen (Sessel-Node verschieben + `DeriveStands`) → nach dem Tausch ist T0 der **neuen** Map weiterhin aus und P1 endet ≥ 0,5 m vor dem Ziel; `SetLocks` ohne Sperre → T0 an (Review W4).
- [ ] **Step 2: Fehlschlag sehen** — `$GODOT --headless --path native -- --check nav` → `CHECK FAILED … N9`.
- [ ] **Step 3: Implementieren** nach den Signaturen; `groundAt` = `Height.GroundAt` (nur bei `FollowGround` benutzt).
- [ ] **Step 4: Grün** — `--check nav` ok; `GODOT=… native/test.sh` grün (alle anderen Checks unverändert: der Bake ändert keine Figur).
- [ ] **Step 5: Commit**
```bash
git add native/World/WorldBuilder.Nav.cs native/World/WorldBuilder.Nav.cs.uid native/World/WorldBuilder.cs native/World/WorldBuilder.Stands.cs native/World/WorldBuilder.Residency.cs native/Check/NavCheck.cs native/fixtures/README.md
git commit -m "feat(native-nav): bake each near location when it turns near and after its stands, swap maps when synced" -- native/World/WorldBuilder.Nav.cs native/World/WorldBuilder.Nav.cs.uid native/World/WorldBuilder.cs native/World/WorldBuilder.Stands.cs native/World/WorldBuilder.Residency.cs native/Check/NavCheck.cs native/fixtures/README.md
```

---

### Task 5: Messvergleich Voxel gegen Polygon, Verlierer löschen

**Files:**
- Modify: `native/Check/NavCheck.cs` (`RunCompareAsync`), `native/Check/CheckRunner.cs` (`only == "navcompare"`, **nicht** im Gesamtlauf), `native/Cli.cs` (`navcompare` in `IsSection` und in die `CheckSection`-Meldung, Hilfezeile), danach Löschung in `native/World/NavBake.cs`, `native/Core/Nav/NavBakeParams.cs`, `native/World/WorldBuilder.Nav.cs` (`NavMode` weg), `native/tests/NavSourceTests.cs` (Modus-Fälle anpassen), `native/fixtures/README.md`
- Create: `docs/superpowers/measurements/2026-11-25-client-ausfuehrung-e2-navmesh.md`

**Interfaces:**
- Consumes: Task 3/4.
- Produces: nach dem Task gibt es genau einen Bake-Weg; `NavBakeParams.Current` (statt `For(mode)`), `NavBakeMode` entfällt, `NavBakeParams.Version = 2` (Fingerabdruck ändert sich mit).

- [ ] **Step 1: `navcompare` schreiben** — für `fixtures/nav` (Hand-Boxen), `fixtures/walk` (`loc-hall`), `fixtures/embody` (`loc-hall`), `fixtures/storeys` (`loc-tower`) je Modus: Backzeit (Stopwatch um den **synchronen** Bake — `NavigationServer2D.BakeFromSourceGeometryData` bzw. `NavigationServer3D.BakeFromSourceGeometryData` (beide in der XML) —, Median aus 5 Läufen; nicht „Aufruf bis Callback“ des Async-Bakes, denn der Callback kommt erst im Server-Sync auf dem Main-Thread an und misst den Frame-Takt, Review W7), Polygonzahl (`NavigationMesh.GetPolygonCount` summiert), Kantenfehler (N2-Sonden, nur `nav`), N4–N7 bestanden ja/nein (nur `nav`), `RegionGetConnectionsCount(T0)`. Ausgabe eine Zeile je (Fixture, Modus): `[navcompare] fixture=… mode=… ms=… polys=… edge_err=… paths=ok|fail thresholds_welded=…`.
- [ ] **Step 2: Laufen lassen** — `$GODOT --headless --path native -- --check navcompare` → `CHECK ok navcompare …`; Zeilen in das Messdokument übernehmen (Tabelle: Fixture × Modus × Metrik, dazu Godot-Version, Maschine `nproc`, Datum).
- [ ] **Step 3: Entscheidung nach Messregel 9** im Messdokument begründen (Zahlen, nicht Eindruck). Im Messdokument vermerken: `storeys/scene_loc-tower.json` hat Türen in durchgehenden Wänden ohne Lücke — Entscheidung 2 findet dort keine angrenzende Lücke, es entsteht keine Schwelle; die Fixture taugt als Zeit-/Polygonprobe, nicht als Pfadbeleg (`thresholds_welded` dort erwartungsgemäß 0). Zum Vergleich: der Review maß den synchronen 2D-Bake der Nav-Welt mit 0,1–0,8 ms. Hält eine Fixture beim Gewinner die 300-ms-Schwelle nicht (Spec 8: Plattencache), dort vermerken — keine Umsetzung in E2.
- [ ] **Step 4: Verlierer löschen** (Code, Parameter, Testfälle, `navcompare`-Modusschleife — `navcompare` bleibt als Messung des Gewinners für E7), `NavBakeParams.Version = 2`; README-Werte für den Gewinner prüfen (Voxel-Gewinner: Toleranzen in N2/N4/N5/N9 auf die gemessene Kantenabweichung + 0,05 setzen und im README begründen).
- [ ] **Step 5: Grün** — `dotnet test native/tests`, `--check nav`, `GODOT=… native/test.sh`.
- [ ] **Step 6: Commit**
```bash
git add native/Check/NavCheck.cs native/Check/CheckRunner.cs native/Cli.cs native/World/NavBake.cs native/Core/Nav/NavBakeParams.cs native/World/WorldBuilder.Nav.cs native/tests/NavSourceTests.cs native/fixtures/README.md
git add -f docs/superpowers/measurements/2026-11-25-client-ausfuehrung-e2-navmesh.md
git commit -m "perf(native-nav): measure voxel against polygon bake, keep the winner" -- native/Check/NavCheck.cs native/Check/CheckRunner.cs native/Cli.cs native/World/NavBake.cs native/Core/Nav/NavBakeParams.cs native/World/WorldBuilder.Nav.cs native/tests/NavSourceTests.cs native/fixtures/README.md docs/superpowers/measurements/2026-11-25-client-ausfuehrung-e2-navmesh.md
```

---

### Task 6: Avatar — Boden-Klick, Klick-Laufen über das Navmesh, Link-Ritt, Möbel-Klemme

**Files:**
- Create: `native/Core/Nav/NavClick.cs`, `native/tests/NavClickTests.cs`, `native/fixtures/nav/pos_answers.json` (Szenarien `nav-up`, `nav-up-rejected`, siehe „Die Nav-Welt“)
- Modify: `native/Figures/PlayerSteering.cs`, `native/Figures/AvatarRoomsController.cs`, `native/App/MainEmbody.cs` (Verdrahtung `RideLink`, `TryGroundWalk`), `native/App/MainHud.cs` (`PickAt`: Boden-Klick im `pickAction`), `native/World/WorldBuilder.Nav.cs` (`NavOutsideDoors(slot)`), `native/Check/NavCheck.cs` (Abschnitte A0–A7), `native/fixtures/README.md`
- **Nicht** angefasst: `native/App/MainRooms.cs` — Sperren laufen über `WorldBuilder.SetLocks` (Entscheidung 3, Task 4).

**Interfaces:**
- Consumes: Task 2 (`NavRoutePlanner`, `NavRoute`, `NavClamp`, `NavRouteEvent`), Task 4 (`NavFor`, `NavChanged`, `SetLocks`), `AvatarRoomsController.RideAsync` (`AvatarRoomsController.cs:197`, privat), `Stairs.LegTo`, `Elevator.TargetRoom`, `WorldBuilder.FigureGroundY` (`WorldBuilder.Water.cs:182`).
- Produces:
  - `public static class NavClick { static P2? FloorHit(Vec3 origin, Vec3 dir, double planeY); static P2? GroundHit(Vec3 origin, Vec3 dir, double firstY, Func<double, double, double> groundAt); }` (Core) — `FloorHit`: Schnitt des Strahls mit `y = planeY`; `null` bei `dir.Y ≥ −1e-6` oder `t ≤ 0`. `GroundHit`: `h1 = FloorHit(firstY)`, dann `FloorHit(groundAt(h1))`; `null`, wenn einer der beiden `null` ist (Review N-W5).
  - `TryGroundWalk` (`MainEmbody.cs`, statisch mit Builder/Steuerung/Avatarposition/Strahl als Parameter, `Main` reicht seine Felder durch): nur `Embodied`; Slot = `world.FootprintAt(avatar)`; `level = slot.LevelFilter ?? 0`; erster Treffer mit `planeY = datum + scene.FloorY(level)`; liegt er nicht im Grundriss dieses Slots, zweiter Schnitt mit `planeY = FigureGroundY(ersterTreffer)`; dann `_playerSteering.WalkTo(hit, level)`. Ohne Slot (Avatar draußen): erste Ebene `y = avatar.Y`, dann `planeY = FigureGroundY(ersterTreffer)` (Review N-W5), `level = null`. Beide Fälle über `NavClick.GroundHit`.
  - `MainHud.PickAt`: im `pickAction`-Lambda **nach** Angeboten und Vertikalzielen `if (Embodied && TryGroundWalk(o, d)) return true;` (Figur-Klick und Info-Panel bleiben vorrangig wie heute).
  - `PlayerSteering.WalkTo(P2 hit, int? level = null)` — Ziel-y = Stockwerkshöhe aus `NavFor(slot).Source`. Reihenfolge: heutige Sperren (`PropActionDriven`, `MovementLocked`, …) → **`Blocked(mine, hit)`** wie heute (Ablehnungs-Scheiben, `PlayerBlocked`; `EmbodyPositionCheck.cs:89`, `EmbodyWalkCheck.cs:140` bleiben grün) → mit fertiger Navigation am Start: `NavRoutePlanner.Plan(...)` (`insideFootprint` = `world.FootprintAt(x, z) == slot`, `outsideDoors` = `NavOutsideDoors(slot)`, `outsideY` = `FigureGroundY`); `null` und **beide** (Start und Ziel) im Grundriss → `false`; sonst der heutige gerade Weg. `Route` = Endziel in beiden Modi (`NavPlan.Goal` bzw. das gerade Ziel). `FirstStep.Arm("click_walk", …)` bleibt.
  - `public NavRoute? NavRoute { get; }` neben `Route`; `CancelRoute()` löscht beide; `CancelStraightRoute()` löscht nur `Route`-Zustand und Walk-Target, nicht `NavRoute` (für den Ritt).
  - `public Func<ulong, Task<bool>>? RideLink { get; set; }`
  - `AvatarRoomsController.RideAsync(..., bool keepNavRoute = false)` gibt jetzt `Task<bool>` zurück: `false` bei jedem der heutigen stummen Rücksprünge (`target is null`, `Channel.InFlight`, `Channel.Rejected`, Eintritt abgelehnt, Generation/Slot gewechselt, `!CanUse`), `true` nachdem `VerticalRide` gesetzt ist; mit `keepNavRoute` ruft es `CancelStraightRoute()` statt `CancelRoute()` (heute `:201`). `RideStairsAsync`/`RideElevatorAsync` reichen das Ergebnis durch, ihre Aufrufer ignorieren es wie heute.
  - `AvatarRoomsController.RideLinkAsync(ulong owner) : Task<bool>` — Treppe: Ziel-Landung = das Ende des Fluges, das nicht auf dem aktuellen Stockwerk liegt, Ritt wie `RideStairsAsync` (`StairRide { Legs = [leg], Leg = 0, Armed = true }`); Aufzug: Ziel-Stockwerk = das andere Ende, Ritt wie `RideElevatorAsync` ohne Picker. Beide über `RideAsync(..., keepNavRoute: true)` (unveränderte Raum-Eintrittsmeldung). Unbekannter Owner → `false`.
- In `PlayerSteering.Step`: (a) Folgt eine `NavRoute`: `dir` zu `NavRoute.Next`; Ereignis `AtLink` → `_rideTask = RideLink(owner)` einmal (fehlt `RideLink` → `LinkResult(false)`); ist `_rideTask` fertig: `LinkResult(result)`; nach `LinkResult(true)` wartet die Route, bis `VerticalRide` **gesetzt und wieder `null`** ist → `LinkFinished()` (während des Server-Roundtrips ist `VerticalRide` noch `null` — das zählt nicht als fertig, Review B5); `Replan` → neu planen zum selben `Final`; `Abort`/`Arrived` → `CancelRoute()`. Der 20-Frame-Stillstand gilt nur noch für den geraden Weg. (b) Nach `Collide.ClampAgainstWalls`: wenn `world.NavFor(here)` fertig, `f.Ride is null` und `world.FootprintAt(target) == here` → `target = NavClamp.Step(from, target, f.Position.Y, <storey_m der Szene>, nav)`.

- [ ] **Step 1: Tests und Check-Abschnitte zuerst.**
  - `NavClickTests` (Herleitung im Docstring): Strahl o = (98, 10, 5), d = (0, −10, −6) (unnormiert, das Ergebnis ist skalierungsfrei): `planeY` 0 → t = 1 → (98, 5 − 6) = (98, −1); `planeY` 3 → t = 0,7 → (98, 5 − 4,2) = (98, 0.8); d = (0, 0, −1) → null; o unter der Ebene (o.Y = −1, d nach unten) → null. `GroundHit` am Hang `groundAt(x, z) = −0,5·z`, `firstY` 0: h1 = (98, −1) → Gelände 0,5 → t = 0,95 → (98, 5 − 5,7) = (98, −0.7); auf flacher Ebene (`groundAt` ≡ 0) = `FloorHit(0)`.
  - `NavCheck`, Aufbau wie `Check/EmbodyRoomsCheck.cs:40–51`: `FigureManager` mit `GroundYAt = builder.FigureGroundY`, `new PlayerSteering(manager, builder) { RoomId = "r-a" }`, `SetActive(true)`, **echter** `AvatarRoomsController` (`new(manager, builder, steering, source, hud, () => now)`, `SetActive(true)`, `hud.SetState("mode","embodied")`), `steering.RideLink = rooms.RideLinkAsync`; Frames `steering.Step(dt, keys, yaw)` + `manager.Tick(dt)` + `rooms.Tick()`, dt 0,25 außer A7:
  - **A0** Boden-Klick über die Verdrahtung (`TryGroundWalk` nimmt o/d als Parameter, keine Kamera nötig; dafür wird die Funktion als `internal static TryGroundWalk(WorldBuilder, PlayerSteering, Vec3 avatar, Vec3 o, Vec3 d)` ausgelegt und von `Main` wie vom Check gerufen), Strahl aus `NavClickTests`, Avatar auf (97, −1): `LevelFilter` 0 → true, `steering.Route` = (98, −1) ± 0,01; `LevelFilter` 1 → Treffer (98, 0.8) liegt im Grundriss → `WalkTo(…, 1)` → `NavRoute.Final` = (100.35, 3, 0.8) ± 0,05 (nächster Loft-Punkt: Loft erodiert ab x 100.35, Abstand 2,35 < 3 zum Boden darunter; Planer-Fall 3); danach `CancelRoute()`.
  - **A1** `WalkTo((103, −1))` → true; `NavRoute` enthält (99.65, 1.8) und (100.35, 1.8); `Route` = (103, −1) (Endziel, Review W5); höchstens 40 Frames bis Ankunft innerhalb 0,2 von (103, 0, −1); beim Überqueren von x = 100 liegt z in [1.75, 2.25] (durch die Tür, nicht durch die Wand).
  - **A2** Klemme: Avatar auf (97, −1) gesetzt, Tastengang nach −z (Tastenname und Kamerawinkel wie in `Check/EmbodyWalkCheck.cs`) 8 Frames → z nie < −1.36, Endpunkt z −1.35 ± 0,02. **A2b** Avatar auf (97, −1.8) (im erodierten Sessel) gesetzt, Gang nach +z → er erreicht z > −1.35 (kommt frei).
  - **A3** `WalkTo((97, −2))` (ins Möbel) → Ziel (97, −1.35) ± 0,02, Ankunft dort.
  - **A4** `builder.SetLocks` mit `r-b` gesperrt, Avatarraum `r-a` → nach `Ready` `WalkTo((103, −1)) == false`, Avatar steht still; Sperre weg → true.
  - **A5** `source.SelectRoomScenario("nav-up")`; `WalkTo((104, 2), level: 1)` → genau eine Eintrittsanfrage `r-up` (`source.RoomRequests`), Ritt über Owner 65536 (`NavRoute` hatte genau einen Link-Abschnitt), `NavRoute` bleibt über den Ritt erhalten (nicht von `RideAsync` gelöscht); nach dem Ritt geht der Avatar weiter und steht innerhalb 0,25 von (104, 3.0x, 2) (y = Loft-Boden aus `PlayerFloorY`), `steering.RoomId == "r-up"`.
  - **A5b** `SelectRoomScenario("nav-up-rejected")`; Avatar zurück auf (97, −1), Ebene 0; `WalkTo((104, 2), level: 1)` → Avatar läuft bis zum Treppenfuß, Eintritt abgelehnt → `NavRoute == null` und `Route == null` (Route abgebrochen), Avatar bleibt auf Ebene 0 (y < 0,1) innerhalb 0,5 von (101, 0, −3.3), `VerticalRide == null`.
  - **A6** `steering.PropActionDriven = true` + Ziel im Sessel → `Step` ändert keine Position (alter `OwnPropMotion`-Weg unberührt, Entscheidung 12).
  - **A7** Tastengang bei **dt 1/60** (Schritt `max(3,4·dt, MinLead 0,15)` = 0,15 m < Erosion 0,25 m, `PlayerSteering.cs:200`): Avatar auf (97, −3), Gang nach −z bis zu 240 Frames → er passiert T1 (bei z = −4 ist x ∈ [96.8, 97.2]), erreicht den Hof (z < −4.4) und danach z < −7.1 (über die Grundstückskante, `FootprintAt == null`); in keinem Frame bleibt er stehen, solange die Taste gedrückt ist (Review B3).
- [ ] **Step 2: Fehlschlag sehen** — `dotnet test native/tests --filter FullyQualifiedName~NavClickTests` → FAIL (Build); `--check nav` → `CHECK FAILED … A0`.
- [ ] **Step 3: Implementieren** (Interfaces oben); in `MainEmbody` `RideLink = owner => _avatarRooms.RideLinkAsync(owner)` und `TryGroundWalk`; in `MainHud.PickAt` der Boden-Klick im `pickAction`.
- [ ] **Step 4: Grün** — `dotnet test native/tests`; `--check nav`; `GODOT=… native/test.sh` (insbesondere `EmbodyPositionCheck` P2 „disc blocks“, `EmbodyWalkCheck` (`:106/136/140`), `EmbodyOffersCheck` (`:166`) und `EmbodyRoomsCheck` (`:110`) unverändert grün — `Route` bleibt das Endziel, `Blocked` läuft vor der Nav-Planung; ihre Welten haben Navigation, ihre Erwartungen dürfen sich nur ändern, wenn ein Klick vorher durch eine Wand ging — dann neu herleiten und im README begründen). **Review N-W3:** diese Checks warten vor ihrem ersten `WalkTo`/`UseVertical` (über dieselbe Frame-Schleife wie N9, höchstens 240 Frames), bis `builder.NavFor(slot) != null` — sonst prüfen sie je nach Bake-Timing mal den geraden Weg, mal den Nav-Weg. Die Erwartungen werden danach **neu hergeleitet**, nicht übernommen: insbesondere `EmbodyRoomsCheck` R5 (`Route is { X:0, Z:-2 }`, `:110`) — `Route` ist jetzt `NavPlan.Goal`, also der nächste Netzpunkt zum Treppenfuß; liegt der Fuß weniger als r = 0,25 von einer Wandfläche oder Hindernis-Kante in `walk/scene_loc-hall.json` entfernt, verschiebt er sich um die Erosion. Herleitung (Fuß, nächste Wandflächen, erwartetes Ziel) im README-Abschnitt der jeweiligen Fixture; dasselbe für `EmbodyWalkCheck` `:106/152`, `EmbodyOffersCheck` `:163/166` und `EmbodyPositionCheck` P2.
- [ ] **Step 5: Commit**
```bash
git add native/Core/Nav/NavClick.cs native/tests/NavClickTests.cs native/fixtures/nav/pos_answers.json native/Figures/PlayerSteering.cs native/Figures/AvatarRoomsController.cs native/App/MainEmbody.cs native/App/MainHud.cs native/World/WorldBuilder.Nav.cs native/Check/NavCheck.cs native/fixtures/README.md
git commit -m "feat(native-nav): ground click, click-walk on the navmesh with stair/lift links and furniture clamp" -- native/Core/Nav/NavClick.cs native/tests/NavClickTests.cs native/fixtures/nav/pos_answers.json native/Figures/PlayerSteering.cs native/Figures/AvatarRoomsController.cs native/App/MainEmbody.cs native/App/MainHud.cs native/World/WorldBuilder.Nav.cs native/Check/NavCheck.cs native/fixtures/README.md
```

---

### Task 7: Debug-Overlay (F9)

**Files:**
- Create: `native/World/NavOverlay.cs`
- Modify: `native/World/WorldBuilder.Nav.cs` (Overlay-Knoten besitzen, bei `NavChanged` und aus `SetLocks` neu bauen), `native/World/WorldBuilder.cs` (`SetLocks` stößt den Overlay-Neubau an), `native/Main.cs` (`_Input`: `Key.F9` toggelt, wie F11 vor HUD/Login behandelt), `native/Hud/HudOverlay.cs:640` (`Key.F9` wie F11/F2 nie an die Seite), `native/Check/NavCheck.cs` (Abschnitt O1), `native/Check/HudInputProbe.cs` nur falls dort die durchgelassenen Tasten gezählt werden (Zahl neu herleiten)

**Interfaces:**
- Consumes: `LocationNav` (Regionen-Meshes, Schwellen-Zustand, Links).
- Produces: `public sealed partial class NavOverlay : MeshInstance3D { void Rebuild(LocationNav nav); }`, `WorldBuilder.NavOverlayVisible { get; set; }`. Eine `ArrayMesh` mit drei Oberflächen: Stockwerke (Fächer-Dreiecke je Polygon, Farbe #3a7bd5, Alpha 0,35), Schwellen (#3ad57b bzw. #d53a3a wenn `RegionGetEnabled == false`), Links (`PrimitiveType.Lines`, #e0c040); +0,03 m; `StandardMaterial3D { ShadingMode = Unshaded, Transparency = Alpha, NoDepthTest = false }`. Nur die offene Location wird gezeigt.

- [ ] **Step 1: Check O1 zuerst** — Nav-Welt: `NavOverlayVisible = true` → Overlay-Mesh hat 3 Oberflächen; Dreieckszahl Oberfläche 0 = Σ(Polygon-Ecken − 2) über alle Stockwerks-Polygone (aus den Region-Meshes gezählt), Oberfläche 1 = 4 (zwei Rechtecke, T0 und T1), Oberfläche 2 = 2 Linien (4 Vertices); `SetLocks` mit `r-b` gesperrt, Avatarraum `r-a` → T0 rot, T1 grün; `false` → Knoten unsichtbar.
- [ ] **Step 2: Fehlschlag sehen** — `--check nav` → `CHECK FAILED … O1`.
- [ ] **Step 3: Implementieren.**
- [ ] **Step 4: Grün** — `--check nav`, `GODOT=… native/test.sh`.
- [ ] **Step 5: Commit**
```bash
git add native/World/NavOverlay.cs native/World/NavOverlay.cs.uid native/World/WorldBuilder.Nav.cs native/World/WorldBuilder.cs native/Main.cs native/Hud/HudOverlay.cs native/Check/NavCheck.cs
git commit -m "feat(native-nav): F9 navmesh overlay with door and link state" -- native/World/NavOverlay.cs native/World/NavOverlay.cs.uid native/World/WorldBuilder.Nav.cs native/World/WorldBuilder.cs native/Main.cs native/Hud/HudOverlay.cs native/Check/NavCheck.cs
```
(`HudInputProbe.cs` nur in beide Listen, wenn geändert.)

---

### Task 8: Abschluss — Spec-Eintrag, Paket, AppImage

**Files:**
- Modify: `docs/superpowers/specs/2026-11-25-client-ausfuehrung-design.md` (Abschnitt 9: Eintrag „**E2 umgesetzt (Datum, Plan `docs/superpowers/plans/2026-11-25-client-ausfuehrung-e2.md`)**“ mit: gewählter Bake-Modus + Kernzahlen aus dem Messdokument, Türschwellen-Konstruktion (Siegel + Schwelle, Entscheidung 2), Fingerabdruck statt `scene_etag` als Cache-Schlüssel (Entscheidung 6), Map-Tausch statt Region-Tausch (Entscheidung 4) mit synchronen Iterationen und Bereitschaft „Iteration seit der letzten Änderung gestiegen“ — **dazu den Satz in Spec 5d nachtragen** (bisher „`MapGetIterationId > 0` vor der ersten Abfrage“; mit asynchronen Iterationen ist `iter = 1` in 4.7.2 eine leere Map), Owner-Kodierung und Kosten der Links (Aufzug `travel_cost` 10), Hof-/Korridor-Laufflächen (Entscheidung 7), Boden-Klick (Entscheidung 11), `NavRoute` als Wegwerf-Abspieler, den E3 ersetzt, offene Übergabepunkte an E3: Avoidance, `OrderPlayer`, NPC-Pfade, Welt-Map draußen, `access`-Prüfung gegen echte Aufträge in `OrderCheck`)

- [ ] **Step 1: Gesamtlauf** — `GODOT=/home/dev/tools/godot/Godot_v4.7.2-stable_mono_linux_x86_64/Godot_v4.7.2-stable_mono_linux.x86_64 native/test.sh` → `== all native checks passed`.
- [ ] **Step 2: Spec-Eintrag schreiben und committen**
```bash
git add -f docs/superpowers/specs/2026-11-25-client-ausfuehrung-design.md
git commit -m "docs(spec): E2 navmesh in the native client implemented" -- docs/superpowers/specs/2026-11-25-client-ausfuehrung-design.md
```
(Hat die Spec fremde, nicht committete Hunks: nur den eigenen Abschnitt über einen handgebauten Index committen — `git diff` prüfen, sonst Orchestrator melden.)
- [ ] **Step 3: Paket bauen** — `GODOT=… native/package.sh` → letzte Zeile `== AppImage: <pfad> (<bytes> bytes)`.
- [ ] **Step 4: Ausliefern** — `cp <pfad> ~/claude-out/` und `ln -sfn ~/claude-out/<dateiname> ~/claude-out/AnimaNative-latest.AppImage`; prüfen: `readlink ~/claude-out/AnimaNative-latest.AppImage` zeigt auf die neue Datei, `test -x` ok. Nichts anderes in `~/claude-out` löschen.
- [ ] **Step 5: Abnahme-Hinweis an den Orchestrator** (Spec 8, E2): Avatar läuft per Klick um Sessel/Bett herum, durch Türen, über Treppen (Stockwerk umschalten, oben klicken); F9 zeigt das Navmesh; gesperrte Tür → Schwelle rot, Klick dahinter läuft nicht. Kein Server-Neustart nötig (E2 ändert nur den Client).

---

## Review-Entscheidungen (Review 2026-11-25, eingearbeitet)

- **Übernommen, blockierend:** B1 (Bake zusätzlich nach `Residency.cs:190`, Check ohne direkten `RequestNavBake`), B2 (Boden-Klick in `MainHud.PickAt` + `NavClick`, Check A0), B3 (Ebene 0 = versetztes `boundary` + Korridore, Hof in der Nav-Welt über Außentür D1, Check A7 mit dt 1/60), B4 (synchrone Iterationen, Bereitschaft = Iteration seit letzter Änderung gestiegen, Spec-5d-Nachtrag in Task 8), B5 (`RideLink` als `Task<bool>`, `RideAsync(keepNavRoute)`, `LinkResult`, A5/A5b über den echten `AvatarRoomsController`).
- **Übernommen, wichtig:** W1 (nur Einstiegspunkt markiert, Test und Vertrag), W2 (Aufzug `travel_cost` 10, N5 in beide Richtungen, N6 = P3 14,279), W3 (Scharfschalten über `MapChanged` statt `TickNav`), W4 (Sperren nur über `SetLocks`, beim Scharfschalten neu angewandt, N12), W5 (Planer-Fall 4 gestrichen, `Blocked` vor der Nav-Planung, `Route` = Endziel, „beide im Grundriss“), W6 (Eckenreihenfolge der Schwelle festgelegt und getestet, Platten einzeln, Loch nur ohne Überdeckung), W7 (synchroner Bake für die Zeitmessung, Tower nur Zeitprobe).
- **Übernommen, klein:** Cli `IsSection`/`CheckSection`, N8/N11 zwei Physik-Frames, `NavRoute.Goal` → `Next`/`Final`, `NavClamp`-Epsilon und |Δy|-Regel, `NavBakeParams.Create`-Signatur, `RunContinuationsAsynchronously`, Prop-Boxen einmal pro `DeriveStands` gemessen, `NavRoute` als Wegwerf-Code im Spec-Eintrag. `GetNavigationMesh()`-Zellhöhe war schon vorgesehen (keine Änderung).
- **Eigene Ausgestaltung (Review ließ die Wahl):** W3 per Signal `MapChanged` statt benannter Frame-Aufrufstelle — wirkt auch in Checks ohne `TickProps`. B3: Höhe im gemischten Ebene-0-Netz pro Vertex (innerhalb der `floor_plan`-Hüllen Boden, außerhalb Gelände) statt einer eigenen Hof-Region — getrennte Regionen hätten an wandlosen Kanten eine 0,5-m-Erosionslücke ohne Verbindung.
- **Abgelehnt:** keiner.

## Review-Entscheidungen (zweites Fable-Review 2026-11-25, eingearbeitet)

- **Übernommen, blockierend:** N-B1 (`ApplyLocks`/`SetLinkEnabled` vergleichen mit `RegionGetEnabled`/`LinkGetEnabled`, `ChangedAtIteration` nur bei echter Änderung, Rückgabe `bool`; Scharfschalten ohne Änderung tauscht sofort — Entscheidung 4, Task 3 N7b, Task 4 N13).
- **Übernommen, wichtig:** N-W1 (`MapChanged` nur abonniert, solange eine ausstehende Map existiert; Abmeldung auch in `StopResidency`; N11/N13 prüfen `NavMapChangedSubscribed`), N-W2 (Außentüren nur über `SceneDoorway.Outside`, Normale `OutwardNormal` mit Rückfall `(along.z, −along.x)` wie `_door_outward`; Test `OutsideDoorWithoutNormalUsesAlong`), N-W3 (bestehende Embody-Checks warten auf `NavFor != null`, R5 und die übrigen `WalkTo`-Erwartungen werden neu hergeleitet, nicht übernommen), N-W4 (während `SetLocks` laufen Abfragen auf dem alten Map-Stand weiter, `NavFor` bleibt gesetzt; nur Checks warten per `AwaitReady`), N-W5 (Boden-Klick draußen: Ebene auf Avatarhöhe, dann einmal mit `FigureGroundY(Treffer)` nachschneiden; `NavClick.GroundHit` + Hangtest).
- **Übernommen, klein:** Hof-Herleitung korrigiert auf x 93.95…106.05; Versatz-Regel `NavSource.OffsetRing` (Wicklung normiert, Gehrung, Fase, Rückfall bei Selbstschnitt mit `NavProblem("boundary_offset")`) samt Test `BoundaryOffsetLShape`.
- **Eigene Ausgestaltung:** N-B1 — sofortiger Tausch statt eines künstlichen Umschaltens, weil ohne Änderung kein Iterationswechsel garantiert ist. N-W1 — Abo an „ausstehende Map existiert“ gebunden statt an Lebensdauer des Builders; `StopResidency` statt `_ExitTree`, weil es schon an `TreeExiting` hängt und Residency-Abbrüche abdeckt. N-W5 — reine Core-Funktion `GroundHit` statt Logik in `MainEmbody`, damit der Hangfall per xUnit belegt ist.
- **Abgelehnt:** keiner.

## Self-Review (vom Planautor durchgeführt)

- **Spec-Abdeckung E2:** `NavSource` (T1), `NavBake` (T3), Maps/Regionen/Links (T3), Türschwellen-Regionen + Sperre ohne Rebake (T1/T3/T6), `NavCheck` inkl. Link-Radius, Zugangslücke ≤ 0,4, Schlussstück ohne Wand (T3), Overlay mit Taste (T7), Messvergleich Voxel/Polygon (T5), Klick-Laufen über `QueryPath` (T6), Avatar-Klemme sperrt Möbel, `OwnPropMotion` ausgenommen (T6), Cache + Rebake + Freigabe erst nach Sync (T4), Bereitschaft = Iteration seit der letzten Änderung gestiegen bei synchronen Iterationen (T3/T4, Spec-Nachtrag 5d in T8), Zellgrößen-Untergrenze (T1), Feststecken/Neuplanung (T2/T6). Nicht in E2 (Spec 8): Avoidance, `OrderPlayer`, NPC-Wege, Welt-Map draußen, Chunk-Navmeshes, `CharacterBody3D`.
- **Typkonsistenz:** `NavSourceData`/`NavThreshold.Doorway`/`NavLinkSpec.Owner` (T1) = Schlüssel in `LocationNav.Thresholds`/`Links` (T3); `IPathProvider` (T2) von `LocationNav` (T3) implementiert; `NavFor`/`NavOutsideDoors` (T4/T6) im selben Partial `WorldBuilder.Nav.cs`, Sperren nur über `SetLocks` (T4); `RideLink` `Func<ulong, Task<bool>>` (T6) = `RideLinkAsync` (T6); `ApplyLocks`/`SetLinkEnabled` geben `bool` zurück (T3), der Scharfschalt-Weg in T4 nutzt es; `NavClick.GroundHit` (T6) ist der einzige Klick-Schnitt, `TryGroundWalk` ruft nur ihn; `NavBakeParams.For` → nach T5 `NavBakeParams.Current` (T5 passt alle Aufrufer an).
