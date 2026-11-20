"""A223 — the clothing slot ``hands`` (gloves) is wired end to end.

No server, no world DB. Usage: ./.venv/bin/python scripts/smoke_hands_slot.py

Expected (by hand from the A223 brief): ``hands`` is a core slot (inventory, labels — its paint regions left with the
painted mode, A224), it is in the human species' topology with an
anchor, the outfit-LLM prompt and the slot keyword fallback name gloves, a glove lies under a coat (layer stack
hands -> outer), the item kind guess of a piece on ``hands`` is ``gloves``, and every client slot list has it.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILED = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"   [{detail}]" if not ok and detail else ""))
    if not ok:
        FAILED.append(name)


from app.models.inventory import VALID_PIECE_SLOTS  # noqa: E402
from app.core import body_slots, garment_set, garment_template as gt  # noqa: E402

check("inventory slot", "hands" in VALID_PIECE_SLOTS)
check("core label 'Hands'", body_slots.DEFAULT_PIECE_SLOT_LABELS.get("hands") == "Hands")
check("glove under the coat", garment_set._stacked_over({"outer"}, {"hands"})
      and not garment_set._stacked_over({"hands"}, {"outer"}))
check("kind guess on hands = gloves", gt.default_kind({"name": "Plain", "outfit_piece": {"slots": ["hands"]}}) == "gloves")
yml = (ROOT / "plugins/human/plugin.yaml").read_text()
check("human topology slot", "{id: hands, label: Hands}" in yml)
check("human anchor", re.search(r"^\s+hands: \[10, 54\]", yml, re.M) is not None)
check("outfit prompt names gloves",
      "- hands: gloves" in (ROOT / "shared/templates/llm/tasks/outfit_generation.md").read_text())
check("slot keyword fallback", '"hands": ["gloves"' in (ROOT / "app/skills/outfit_creation_skill.py").read_text())
check("play route order", '"feet", "hands"]' in (ROOT / "app/routes/play.py").read_text())
for f, pat in (("frontend/src/components/Silhouette.tsx", "  hands: 'M "),
               ("frontend/src/components/Silhouette.tsx", "  'hands',\n]"),
               ("frontend/src/tabs/characters/WardrobeTab.tsx", "hands: [10, 54]"),
               ("packages/player-ui/src/BelongingsPanel.tsx", "hands: [10, 54]"),
               ("frontend/src/tabs/items/itemsModel.ts", "  'hands',\n]")):
    check(f"client {f}", pat in (ROOT / f).read_text())

print()
print("all checks passed" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
