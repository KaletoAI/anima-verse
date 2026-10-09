# Admin UI Guide

Neue Admin-UI folgt den bestehenden Layouts. Referenzen sind die Server-Einstellungen in `static/admin/settings.css`, die Game-Admin-Komponenten `Field`, `DetailToolbar` und `ListPane`, sowie die Character-, Location- und Room-Editoren. Das Setup ergänzt diese Muster.

## Farben und Typografie

| Rolle | Dunkler Standard | Game-Admin-Token |
| --- | --- | --- |
| Eingaben / Seitenfläche | `#0d1117` | `--bg` |
| Formulargruppen | `#161b22` | `--bg-container` |
| Sekundäre Aktionen | `#21262d` | `--bg-secondary` |
| Rahmen | `#30363d` | `--border` |
| Text | `#c9d1d9` | `--text` |
| Hilfstext | `#8b949e` | `--text-muted` |

Systemschrift wie im bestehenden Admin verwenden. Eingaben und Buttons haben 12–13 px, Feldbeschriftungen 11 px, Hilfstexte 10–11 px. Gruppenüberschriften im Game-Admin bleiben bei 13 px. Server-Seitentitel verwenden die vorhandene `.section-title`. Blau markiert Auswahl/Herkunft, Grün primäre Aktionen, Rot destruktive Aktionen. Game-Admin verwendet Theme-Variablen mit den bestehenden Fallbacks.

## Layout und Bausteine

- Speichern und Zurücksetzen stehen in `DetailToolbar`; Unterbereiche verwenden `.ga-subtabs` wie die Character- und Location-Editoren.
- Eine fachliche Gruppe bekommt eine `.ga-form`-Fläche mit 12 px Innenabstand und 6 px Radius. Rekursive Schema-Knoten sind reine Layout-Container, keine zusätzlichen Formularflächen. Untergruppen verwenden `.ga-fieldset`.
- Beschriftung, Eingabe und Hilfstext werden mit `Field` gebaut. `.ga-field-control` ist eine horizontale Flex-Zeile: zusätzliche Elemente teilen sonst die Breite der Eingabe. Herkunftshinweise bekommen deshalb eine eigene Zeile; Textfelder und Textareas behalten die volle Breite. Reset-/Default-Aktionen stehen separat.
- Auswahl links, Editor rechts: `.ga-list` und `.ga-list-row.is-active` nutzen, wie in den bestehenden Listen/Detail-Tabs. Auswahl ist kein grüner Speichern-Button. Abstand zwischen Spalten: 14 px; Liste etwa 18 %, mindestens 180–200 px. Auf schmalen Ansichten stapeln sich die Setup-Spalten.
- Lange Beschriftungen und Herkunftshinweise dürfen umbrechen. `min-width: 0` an flexiblen Spalten verhindert horizontalen Überlauf. Textareas behalten ihre durch `rows` definierte Höhe.

## Formularstile und Zustände

Server-Admin-Felder müssen auch außerhalb von `.field` dunkel sein, etwa im Routing-Editor und in Dialogen. Die allgemeinen Regeln für Eingaben, Selects und Textareas in `settings.css` sind die Basis; `color-scheme: dark` deckt native Browser-Controls ab. Checkboxen, Radios, Slider und Farbauswahl nicht mit Textfeld-Padding gestalten.

Game-Admin-Eingaben nutzen `.ga-input` beziehungsweise `.ga-textarea`, Buttons `.ga-btn`, Statushinweise `.ga-tag`. Neue Klassen nur für benötigte Anordnung, keine ungestylten Namen wie `.ga-badge`. CSS auf den betroffenen Bereich begrenzen; bestehende Editoren nicht global umgestalten.

Tastaturfokus muss sichtbar bleiben. Auswahlbuttons kennzeichnen ihren Zustand mit `aria-pressed`; eine echte ARIA-Tablist benötigt zusätzlich Tabpanels und passende Tastaturnavigation. Aktionen bleiben während des Speicherns deaktiviert.

## Prüfung vor Abschluss

1. Mit Character-/Location-/Room-Editor und Server-Einstellungen vergleichen: Schriftgröße, Rahmen, Abstände, Auswahl und Aktionen.
2. Standard- und Override-Felder, Reset-Aktion, lange Labels, Listen, Textareas und Dialogfelder ansehen.
3. Bei breiter und schmaler Ansicht prüfen: volle Feldbreite, keine weißen Browser-Controls, kein horizontaler Seitenüberlauf, sichtbarer Tastaturfokus.
4. `npm run build:admin` ausführen und die gebauten Assets mitliefern, da FastAPI `static/game_admin` ausliefert. Betroffene TSX-Dateien linten.

## Ursachen der korrigierten Einstellungs-UI

Die Server-Stile waren auf `.field` und `.lora-row` begrenzt; etwa `.rt-newform` hatte dadurch native helle Felder. Im Setup lag der Herkunftsblock direkt neben der Eingabe in `.ga-field-control`. Rekursive `.ga-form`-Container erzeugten mehrfach verschachtelte Rahmen, Browser-Standardüberschriften störten die kompakte Hierarchie und Bildstil-Auswahlbuttons verwendeten die grüne Aktionsoptik. Diese Fälle dienen als Referenz für künftige Erweiterungen.
