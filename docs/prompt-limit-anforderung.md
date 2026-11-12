# Anforderung: Prompt-Limit vom AI-Hub übernehmen und vor dem Senden kürzen

Stand 2026-11-12, Anforderung von Kai (übergeben aus der quartermaster-Session).

## Anlass

Figur **Ylva Nordwind**, Seite **Pose** (Render-Art `tpose`), Bild-Backend testweise
**Venice Qwen Uncensored** (`venice.ai/qwen-edit-uncensored`). Vier Klicks zwischen 22:38 und 22:43 CET
endeten alle so (`logs/main.log`):

```
Venice Qwen Uncensored: request error (HTTP 400): {"detail":"Venice prompt is outside the model's text length bounds"}
```

- `final_prompt` der T-Pose: **1551 Zeichen** (`logs/image_prompts.jsonl`). Er setzt sich zusammen aus
  dem Stil-Präfix für `tpose`, dem A-Pose-Text, dem Aussehen und dem Outfit.
- Venice-Limit für `qwen-edit-uncensored`: **1500 Zeichen** (`promptCharacterLimit`). Die anderen
  Venice-Qwen-Edit-Modelle erlauben 10000.
- Die Default-Pose mit 748 Zeichen lief über dasselbe Backend durch.
- anima-verse kennt kein Prompt-Limit pro Backend und kürzt nicht (`app/imagegen/backends/openai_diffusion.py`).

## Gewünscht

1. **Limit vom AI-Hub holen.** Der Hub liest das Limit pro Modell und stellt es bereit (Auftrag liegt bei
   der ai-hub-Session: Alias-Schema `/v1/generations/<alias>/schema` bzw. Modellkatalog). anima-verse
   übernimmt es pro Bild-Backend. Ein unbekanntes Limit heißt: nicht kürzen.
2. **Selbst kürzen, bevor gesendet wird**, z. B. über einen LLM-Helper. Er verdichtet den Prompt auf das
   Limit und behält dabei die Bedeutung. Priorität: Identität/Aussehen und Outfit bleiben erhalten,
   Stil-Präfix und Füllformulierungen werden zuerst verdichtet. Ergebnis hart gegen das Limit prüfen
   (zur Not abschneiden), damit kein 400 mehr entsteht.
3. Gekürzten und Original-Prompt in `image_prompts.jsonl` protokollieren.

Ausdrücklich **nicht** Teil dieses Auftrags (Kai): Anzeige von Hintergrund-Renderfehlern in der UI.
