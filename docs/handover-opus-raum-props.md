# Arbeitsauftrag: Raum-Props — Vorarbeiten (API, Hülle, Prop-Assets)

Du arbeitest im three.js-Client `anima-verse-3d` (Vite + TypeScript). Das
anima-verse-Backend hat eine neue Säule ausgerollt: Räume werden aus
Einzel-Props eingerichtet (Rezept) statt nur als Diorama-Mesh gerendert.

**Pflichtlektüre zuerst, komplett:**
`/home/dev/projekte/shared/backend-note-room-recipe.md` — der Vertrag.
Zum Verständnis des Bestands hilfreich: `docs/schnittstellen-3d.md`
(nur lesen) und die unten genannten Vorbild-Stellen im Code.

Eine zweite Session (Fable) baut parallel/danach die Integration
(Szenengraph-Weiche, Platzierungskette 2b, Figuren-Anbindung, Marker).
Deine Aufgabe sind die drei sauber abgegrenzten Pakete unten.

## Spielregeln

- **Nur diese Dateien anfassen:** `src/api.ts`, `src/types.ts` (erweitern),
  `src/scene/roomShell.ts`, `src/scene/propAssets.ts` (neu anlegen).
- **Tabu:** `tiles.ts`, `main.ts`, alle übrigen Dateien, alles unter
  `/home/dev/projekte/shared/` und `docs/schnittstellen-3d.md` /
  `docs/backend-wishlist.md` (macht die andere Session).
- Die unten definierten Schnittstellen sind **fix** (die Integration baut
  dagegen). Wo dir etwas fehlt oder unklar ist: umsetzen so gut es geht,
  Annahme als Kommentar markieren und unten im Abschnitt „Rückmeldung von
  Opus“ notieren — nicht die Signaturen ändern.
- Stil: deutsche Kommentare, Dichte/Idiome wie im Bestand (siehe
  `src/api.ts`, `src/scene/tiles.ts`). Kein Blender, keine externen Tools.
- Verifikation: `npm run build` (macht `tsc --noEmit` + vite build) muss
  durchlaufen. Committe pro Paket, deutsche Commit-Messages im Stil von
  `git log --oneline -8`, und stage NUR deine vier Dateien.

## Paket A — API-Schicht (`src/api.ts`, ggf. `src/types.ts`)

Neue Endpunkte aus Abschnitt 1 + 2 der Note, exakt im Muster der
bestehenden Funktionen (`getSurfaceTextures` für „Fehler → leer“,
`getRoomModel` für „404 → null, andere Fehler werfen“):

```ts
export interface ApiProp {
  id: string; name: string; category?: string;
  width_m: number; depth_m: number; height_m: number;   // reale Meter, NACH Fix
  rotation?: { x?: number; y?: number; z?: number };    // Orientierungs-Fix in Grad
  tags?: string[]; marker_count?: number; has_model: boolean;
}
/** Prop-Bibliothek; BARE ARRAY vom Server, leer = Normalzustand.
 *  Fehler/nicht verfügbar → []. */
export async function getProps(): Promise<ApiProp[]>
export function propModelUrl(id: string): string   // /assets/props/{id}/model

export interface ApiOpening {
  edge: number;            // Kanten-INDEX in outline (Kante i = Punkt i -> i+1)
  at: number;              // 0..1 ENTLANG der gerichteten Kante (Öffnungs-Mitte)
  width_m: number; height_m: number; sill_m: number;   // reale Meter
  type: string;            // "window" | "door" | "passage" (offen)
  to?: string; prop_id?: string;
}
export interface ApiPlacement {
  prop_id: string;
  at: [number, number];    // Fraktionen des 8x8-Referenzquadrats
  yaw: number;             // Grad, im Uhrzeigersinn (Draufsicht)
  offset_y: number;        // reale Meter
  dims: { width_m: number; depth_m: number; height_m: number };
  has_model: boolean; model_url?: string; missing?: boolean;
}
export interface ApiPropMarker {
  placement: number;       // Index in placements
  animation: string;
  offset_m: [number, number]; // Meter relativ zum Platzierungspunkt (dx, dz)
  height_m: number;        // Meter ÜBER dem Etagenboden
  facing?: number;         // Grad, Welt-Kompass (0=S/90=E/180=N/270=W)
}
export interface ApiRoomRecipe {
  room_id: string; level: number; rotation?: number;
  outline: [number, number][];   // absolute Fraktionen 8x8, im Uhrzeigersinn
  surfaces?: { floor?: string; wall?: string };   // Surface-Texture-Kinds
  openings?: ApiOpening[];
  exit?: [number, number];
  markers?: RoomMarker[];        // bestehendes Vokabular aus types.ts
  placements?: ApiPlacement[];
  prop_markers?: ApiPropMarker[];
  signature: string;             // md5, ändert sich bei Layout- UND Prop-Änderungen
}
/** Raum-Rezept; 404 = Raum ohne Layout (null), andere Fehler werfen. */
export async function getRoomRecipe(roomId: string): Promise<ApiRoomRecipe | null>
```

Felder defensiv normalisieren wie im Bestand üblich (fehlende Arrays → `[]`
ist NICHT nötig, optionale Felder einfach durchreichen; nur `outline` auf
gültige `[x, y]`-Paare filtern schadet nicht).

## Paket B — Hüllen-Renderer (`src/scene/roomShell.ts`, neu)

Abschnitt 2a der Note: Bodenplatte + Wandsegmente aus dem `outline`-Polygon,
pro Raum. **Direktes Vorbild im Code:** der Gebäude-Grundriss-Block in
`src/scene/tiles.ts` ab Zeile ~626 (`AV3D-12`): gleiche Punkt-Abbildung,
gleiche Materialwahl, gleiche `wallSeg`-Technik, gleiche Umlaufrichtungs-
Erkennung für Wand-Normalen. Kein CSG.

```ts
export interface ShellCtx {
  k: number;        // Welt-Meter pro Real-Meter (8 / plan_width_m)
  storey: number;   // Etagenhöhe in Welt-Metern
  floorY: number;   // Etagen-Basis (level * storey) — Konvention wie Vorbild:
                    // Platten-OBERKANTE bei floorY + 0.08, Wände ab dort
  /** Aktive Surface-Textur eines Kinds; null = prozeduraler Fallback
   *  (dann schlichte Farben wie im Vorbild: Boden 0xd8d0c2, Wand 0xcfc4b2).
   *  Wird von der Integration geliefert — hier nur aufrufen. */
  surface: (kind: string | undefined, use: 'floor' | 'wall')
    => { texture: THREE.Texture; sizeM: number } | null;
}

export interface RoomShell {
  group: THREE.Group;   // Kachel-LOKAL: Ursprung = Kachelzentrum, XZ-Ebene
  /** fürs Wall-Culling der Integration; mid/normal kachel-lokal (XZ) */
  walls: { mesh: THREE.Mesh; mid: THREE.Vector2; normal: THREE.Vector2 }[];
}

export function buildRoomShell(recipe: ApiRoomRecipe, ctx: ShellCtx): RoomShell
```

Regeln (alles Wichtige steht in der Note, hier die Übersetzung in unsere
Konventionen):

- **Koordinaten:** `outline`-Fraktion `[fx, fz]` → lokal
  `x = fx * 8 − 4`, `z = fz * 8 − 4` (exakt wie das Vorbild mit `LW = 8`).
  Polygon ist auto-schließend und laut Vertrag im Uhrzeigersinn — die
  Umlaufrichtung trotzdem per Flächenvorzeichen bestimmen (wie Vorbild),
  damit die Wand-Normalen robust sind.
- **Bodenplatte:** `THREE.Shape` aus den Punkten, `ExtrudeGeometry`
  (depth 0.14, kein Bevel), `rotation.x = Math.PI / 2`, Oberkante bei
  `ctx.floorY + 0.08` — identisch zum Vorbild (Raum-Inhalte rechnen ab
  +0.12 über der Etagen-Basis, die Platte darf nicht höher liegen).
- **Wände:** pro Kante i (Punkt i → i+1) Segmente als flache Boxen
  (Dicke 0.07), Höhe `Math.max(0.6, ctx.storey − 0.15)`, Basis
  `ctx.floorY + 0.08`. Jedes Segment in `walls` eintragen (mid/normal wie
  im Vorbild berechnet).
- **Öffnungen** (`openings`): referenzieren die Kante per Index; `at` ist
  die Fraktion 0..1 entlang der gerichteten Kante und wird als
  **Öffnungs-Mitte** interpretiert (Annahme! — als solche im Code
  kommentieren). Öffnungsbreite = `width_m × k`. Pro Kante die Öffnungen
  nach `at` sortieren, Wandstücke dazwischen bauen. Vertikal, EIN
  generischer Codepfad für alle Typen:
  - Brüstungsband von 0 bis `sill_m × k` (nur wenn > 0),
  - der Öffnungsbereich von `sill_m × k` bis `(sill_m + height_m) × k`:
    bei `type === "window"` eine dünne Glasfläche (transparentes
    Standard-Material, opacity ≈ 0.3, kein Schattenwurf), bei Tür/Passage
    Lücke,
  - Sturzband von dort bis zur Wandhöhe (nur wenn Platz bleibt).
  ⚠ `sill_m`/`height_m` sind reale Meter → **immer × k** (die
  Backend-Vorschau hatte hier selbst einen ×k-Vergesser).
  Brüstung/Sturz kommen NICHT in `walls` (kein Culling-Eintrag nötig),
  die Voll-Segmente zwischen Öffnungen schon.
- **Texturen:** `ctx.surface(recipe.surfaces?.floor, 'floor')` bzw.
  `…wall…` abfragen. Kachelmaß = `sizeM × k` Welt-Meter: Textur klonen
  (`needsUpdate`!), `wrapS/wrapT = RepeatWrapping`, Boden
  `repeat = 1 / (sizeM × k)` in beiden Achsen (ExtrudeGeometry-UVs sind
  Shape-Koordinaten, also Welt-Einheiten), Wand-Segmente
  `repeat.set(segLänge / (sizeM × k), wandHöhe / (sizeM × k))`
  (Box-UVs sind 0..1 pro Fläche). `null` → Farb-Fallback wie oben.
- Materialhelfer: `std()`/`box()` aus tiles.ts sind privat — kleine lokale
  Pendants schreiben (siehe tiles.ts Z. ~338, drei Zeilen), nichts
  exportieren, was nicht in der Schnittstelle steht.

`exit`, `markers`, `placements`, `prop_markers`, `rotation` in diesem Paket
**ignorieren** — macht die Integration.

## Paket C — Prop-Assets (`src/scene/propAssets.ts`, neu)

Bibliotheks-Cache, GLB-Loading, Platzhalter. KEIN Orientierungs-Fix
anwenden, NICHT skalieren, NICHT positionieren — die Platzierungskette
(Abschnitt 2b der Note) baut die andere Session; sie erwartet hier rohe
Meshes.

```ts
/** Bibliothek setzen (einmalig beim Start aus getProps()). */
export function setPropLibrary(list: ApiProp[]): void
export function propInfo(id: string): ApiProp | undefined

/** GLB laden (Promise-Cache pro id; parallele Aufrufe teilen den Load).
 *  Rückgabe: die ROHE Szene des glTF, unverändert. 404/Fehler → null,
 *  fehlgeschlagene Loads nicht dauerhaft als null cachen (Retry möglich).
 *  Browser-HTTP-Cache + ETag erledigen die Revalidierung — keine eigene
 *  ETag-Verwaltung bauen. */
export async function loadPropModel(id: string): Promise<THREE.Group | null>

/** Platzhalter für missing / has_model:false — Box in Realgröße dims × k,
 *  halbtransparent neutral-grau, Ursprung = ZENTRUM DER UNTERKANTE
 *  (die Integration setzt ihn direkt auf den Platzierungspunkt). */
export function buildPropPlaceholder(
  dims: { width_m: number; depth_m: number; height_m: number }, k: number
): THREE.Object3D
```

GLTFLoader wie in `src/scene/figures.ts`
(`three/addons/loaders/GLTFLoader.js`); pro `loadPropModel`-Aufrufer wird
dasselbe gecachte Original zurückgegeben — Klonen übernimmt die
Integration (so steht es auch dem Platzhalter-Pfad frei). Ein
Modul-weiter `GLTFLoader` reicht.

## Was du NICHT baust (nur zur Orientierung)

Szenengraph-Weiche placements↔Diorama, Platzierungskette (Fix → BBox →
uniform s → Yaw → Erdung), prop_markers-Komposition, Signature-Polling,
Begehbarkeit/Spots, Wishlist-Status — alles Integration (Fable-Session).

## Rückmeldung von Opus

- `src/api.ts` `getProps`: Vertrag sagt BARE ARRAY; ich akzeptiere defensiv
  auch `{ props: [...] }` (wie `getSurfaceTextures` mit `{ textures }`) und
  filtere auf Einträge mit `id`. Optionale Felder werden 1:1 durchgereicht.
- `src/api.ts` `getRoomRecipe`: nur `outline` auf gültige `[x,y]`-Paare
  gefiltert, `level` fällt auf 0 zurück, `signature` auf `''`. Alle übrigen
  optionalen Felder unverändert durchgereicht (kein `[]`-Default, wie gewünscht).
- `src/scene/roomShell.ts`: `opening.at` als Öffnungs-MITTE interpretiert
  (im Code kommentiert). `at` und Öffnungsspanne werden auf `[0, len]` der
  Kante geklemmt; überlappende Öffnungen fange ich mit `cursor = max(cursor,
  end)` ab, damit keine negativen Wandstücke entstehen.
- `src/scene/roomShell.ts`: Glas-Material-Farbe `0xbcd4e0` gewählt (im
  Vertrag nur „transparent, opacity ≈ 0.3" spezifiziert), Reuse der
  Elevator-Glas-Anmutung. `castShadow=false` fürs Glas, Brüstung/Sturz
  ebenfalls schattenlos wie die Wand-Segmente im Vorbild.
- `src/scene/roomShell.ts`: `sill*k` und `(sill+height)*k` werden nach oben
  auf `WALL_H` geklemmt, falls eine Öffnung höher als die (etagenbegrenzte)
  Wand angegeben ist — dann entfällt Sturz bzw. Öffnung wächst nicht über
  die Wand hinaus. Wand-Textur wird pro Segment geklont (Box-UVs 0..1 pro
  Fläche → repeat muss je Länge/Höhe stimmen).
- `src/scene/propAssets.ts`: Fehlgeschlagene Loads werden aus dem
  Promise-Cache gelöscht (kein dauerhaftes null-Caching), sodass ein
  späterer Aufruf erneut lädt. Rohe glTF-Szene wird unverändert und
  ungeklont zurückgegeben (Klonen ist Integrations-Sache).
- Offen: `ApiPlacement.model_url` liegt vor, `loadPropModel` lädt aber über
  `propModelUrl(id)` (Endpunkt aus Abschnitt 1). Die Integration entscheidet,
  ob sie `model_url` direkt nutzt oder über die id lädt — falls `model_url`
  bevorzugt werden soll, bräuchte `loadPropModel` einen optionalen URL-Param.
