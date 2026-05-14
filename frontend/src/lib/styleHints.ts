// Style-Hint-Vokabular (Schritt 7, May 2026, plan-outfit-system-rethink.md §1).
//
// Ersetzt die alten "outfit_types" aus outfit_rules.json. Items, Raeume und
// Locations koennen einen Style-Hint als Tag fuhren — Compliance ignoriert
// ihn (keine harte Regel), aber LLM und ChangeOutfit-Skill nutzen ihn als
// Stil-Hinweis.
//
// Wenn der User andere Tags will: einfach hier erweitern. Backend speichert
// den String wie eingegeben — keine harte Validation.
export const STYLE_HINT_OPTIONS: readonly string[] = [
  'casual',
  'business',
  'elegant',
  'sporty',
  'beach',
  'club',
]
