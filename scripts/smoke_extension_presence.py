"""Usage: .venv/bin/python scripts/smoke_extension_presence.py

Ruling A64: the Figure tab's and the 3D tab's viewers say which extension groups the SHOWN model carries, and why a
group is missing (``model3d.extension_presence``) — a covered slot is correct (no part, no bones), an exposed slot
without bones is not.

Synthetic fixture (no pack, no world, no server): package ``fixture`` with two slots.
- ``slot``, covered by the clothing slot ``bottom``, with a separate mesh part (switch ``switch``) mapping the rig
  ``chain`` (op ``appendage_chain``) and a companion ``companion`` (op ``attached_part_bone``, only with
  ``attributes.switch: on``) — the shape of A49's fixture; token ``|mesh:fixture.slot=on``.
- ``upper``, covered by ``top``, with ``pair`` (applies only to gender female) and ``tip`` (``exposed_only``, gender
  female).
Profile M: gender male, switch on. Profile F: gender female, switch on.
Items: item_pants "Jeans" (no covers) · item_shirt "Shirt" · item_shirt_see "Mesh shirt" (exposed_detail true) ·
item_dress "Dress" (covers [bottom]) · item_skirt "Skirt".

Hand-derived (``rig_groups_for`` with part off → chain; with part on → chain + companion; so the declared set of M is
{chain, companion}; pair/tip apply to female only → M's ``not_declared`` = [pair, tip]):

[1] Kai's case — outfit model, mesh_variant "", worn pieces {bottom: item_pants, top: item_shirt}, record
    {groups [chain], ops {chain: appendage_chain}, status not_found, metric chain reason "no core vertices"}:
    built [] · chain: grey "Covered", pieces [Jeans] · companion: grey "Covered", pieces [Jeans] ·
    not_declared [pair, tip].
[2] base model (``base``, mesh_variant = token), record applied with both metrics applied: built [chain, companion],
    missing [].
[3] an exposed slot that lost its bones (the bug case): pieces {top: item_shirt}, mesh_variant = token, record ops
    {chain: attached_part, companion: attached_part_bone}, metrics chain {status not_found, reason "r"}, companion
    applied → built [companion]; chain yellow "Not built" with ``EXT_REASON_NOT_FOUND`` (an attached part found
    nothing), detail "r".
[4] the bottom piece worn OPEN (``figure.open``) covers nothing: pieces {bottom: item_skirt} open, record with no
    groups (status none_applicable) → chain and companion yellow "Not built" with ``EXT_PRESENCE_NOT_ON_MODEL``.
[5] ``covers`` counts: pieces {top: item_dress} (covers [bottom]) → chain covered, pieces [Dress].
[6] profile F, pieces {top: item_shirt}: pair and tip declared; tip (exposed_only) covered by [Shirt]; pair is a
    motion group clothing does not remove (no exposed_only, no mesh part) → NOT "Covered" even under the shirt:
    yellow, not on this model (its record names no group); with item_shirt_see (exposed_detail true) tip is not
    covered either (→ yellow, not on this model).
[7] wiring (source greps): ``get_model3d_info`` sets ``extension_presence``; the Figure payload carries
    ``served_extension``; Model3DViewer renders ``extensionNote``; FieldFigure and FieldModel3D pass
    ExtensionPresenceNote; every English string of the note has a de.json key.
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import paths  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


with tempfile.TemporaryDirectory() as tmp:
    paths.init(tmp)
    from app.core.db import init_schema
    init_schema()
    from app.core import body_slots as bs, model3d
    from app.plugins.registry import BodySlotSpec, MeshPartSpec, Package, RigSpec

    attrs = {'switch': {'type': 'select', 'options': ['off', 'on']}}
    chain = RigSpec.parse(dict(id='chain', op='appendage_chain', chains=[[
        {'bone': 'mixamorig:G1', 'parent': 'Hips'}, {'bone': 'mixamorig:G2', 'parent': 'mixamorig:G1'}]]))
    companion = RigSpec.parse(dict(id='companion', op='attached_part_bone', applies_to={'attributes.switch': ['on']},
                                   chains=[[{'bone': 'mixamorig:C', 'parent': 'Hips'}]]))
    part = dict(switch='switch', tpose_prompt='flat slot', rigs={'chain': {'params': {}, 'attribute_params': {}}})
    slot = BodySlotSpec('slot', 'fixture', covered_by=['bottom'], attributes=attrs, rigs=[chain, companion],
                        mesh_part=MeshPartSpec.parse(part, attrs, [chain, companion]))
    pair = RigSpec.parse(dict(id='pair', op='pair_protrusion', applies_to={'gender': ['female']},
                              chains=[[{'bone': 'mixamorig:P', 'parent': 'Spine2'}]]))
    tip = RigSpec.parse(dict(id='tip', op='pair_tip', exposed_only=True, applies_to={'gender': ['female']},
                             chains=[[{'bone': 'mixamorig:PT', 'parent': 'mixamorig:P'}]]))
    upper = BodySlotSpec('upper', 'fixture', covered_by=['top'], attributes={}, rigs=[pair, tip])
    pkg = Package('fixture', Path(tmp), {}, body_slots=[slot, upper])
    TOKEN = bs.mesh_variant_token(slot)
    M = {'gender': 'male', 'body_slots': {'slot': {'switch': 'on'}}}
    F = {'gender': 'female', 'body_slots': {'slot': {'switch': 'on'}}}
    ITEMS = {
        'item_pants': {'name': 'Jeans', 'outfit_piece': {}},
        'item_shirt': {'name': 'Shirt', 'outfit_piece': {}},
        'item_shirt_see': {'name': 'Mesh shirt', 'outfit_piece': {'exposed_detail': True}},
        'item_dress': {'name': 'Dress', 'outfit_piece': {'covers': ['bottom']}},
        'item_skirt': {'name': 'Skirt', 'outfit_piece': {}},
    }

    def outfit(pieces, record, variant='', opened=()):
        return {'source': 'base_body', 'base_signature': 'basefix', 'mesh_variant': variant,
                'figure': {'pieces': pieces, 'open': list(opened)}, 'extension_rig': record}

    def missing_of(presence):
        return {m['id']: m for m in presence.get('missing', [])}

    with patch.object(bs, '_species_packages_for', return_value=[pkg]), \
            patch('app.plugins.registry.packages', return_value=[pkg]), \
            patch('app.core.motion_item_cache.item_snapshot', return_value=ITEMS):
        # [1] Kai's case.
        kai = outfit({'bottom': 'item_pants', 'top': 'item_shirt'},
                     {'groups': ['chain'], 'group_ops': {'chain': 'appendage_chain'}, 'status': 'not_found',
                      'attempted': True, 'metrics': {'chain': {'reason': 'chain link has no core vertices'}}})
        p = model3d.extension_presence('Fixture', kai, profile=M)
        miss = missing_of(p)
        check(p.get('built') == [], f"[1] built [] (got {p.get('built')})")
        check(set(miss) == {'chain', 'companion'}, f"[1] missing chain + companion (got {sorted(miss)})")
        check(all(miss[g]['light'] == 'grey' and miss[g]['state'] == model3d.EXT_PRESENCE_COVERED
                  and miss[g]['pieces'] == ['Jeans'] for g in miss), f"[1] both grey Covered by [Jeans] ({miss})")
        check(p.get('not_declared') == ['pair', 'tip'], f"[1] not_declared [pair, tip] (got {p.get('not_declared')})")

        # [2] the base.
        base = {'base': True, 'mesh_variant': TOKEN,
                'extension_rig': {'groups': ['chain', 'companion'], 'status': 'applied', 'attempted': True,
                                  'group_ops': {'chain': 'attached_part', 'companion': 'attached_part_bone'},
                                  'metrics': {'chain': {'status': 'applied'}, 'companion': {'status': 'applied'}}}}
        p = model3d.extension_presence('Fixture', base, profile=M)
        check(p.get('built') == ['chain', 'companion'] and p.get('missing') == [],
              f"[2] base: built [chain, companion], missing [] (got {p.get('built')}, {p.get('missing')})")

        # [3] exposed slot that lost its bones.
        lost = outfit({'top': 'item_shirt'},
                      {'groups': ['chain', 'companion'], 'status': 'applied', 'attempted': True,
                       'group_ops': {'chain': 'attached_part', 'companion': 'attached_part_bone'},
                       'metrics': {'chain': {'status': 'not_found', 'reason': 'r'}, 'companion': {'status': 'applied'}}},
                      variant=TOKEN)
        p = model3d.extension_presence('Fixture', lost, profile=M)
        miss = missing_of(p)
        check(p.get('built') == ['companion'], f"[3] built [companion] (got {p.get('built')})")
        c = miss.get('chain') or {}
        check(c.get('light') == 'yellow' and c.get('state') == model3d.EXT_STATE_NOT_BUILT
              and c.get('reason') == model3d.EXT_REASON_NOT_FOUND and c.get('detail') == 'r' and c.get('pieces') == [],
              f"[3] chain yellow Not built, EXT_REASON_NOT_FOUND, detail r (got {c})")

        # [4] an open piece covers nothing.
        opened = outfit({'bottom': 'item_skirt'}, {'groups': [], 'status': 'none_applicable'}, opened=['item_skirt'])
        miss = missing_of(model3d.extension_presence('Fixture', opened, profile=M))
        check(all(miss.get(g, {}).get('reason') == model3d.EXT_PRESENCE_NOT_ON_MODEL
                  and miss[g]['light'] == 'yellow' for g in ('chain', 'companion')),
              f"[4] open skirt: chain + companion yellow, not on this model (got {miss})")

        # [5] covers counts.
        dress = outfit({'top': 'item_dress'}, {'groups': [], 'status': 'none_applicable'})
        miss = missing_of(model3d.extension_presence('Fixture', dress, profile=M))
        check(miss.get('chain', {}).get('pieces') == ['Dress'], f"[5] chain covered by [Dress] (got {miss.get('chain')})")

        # [6] female profile, exposed_only tip.
        shirt = outfit({'top': 'item_shirt'}, {'groups': [], 'status': 'none_applicable'})
        p = model3d.extension_presence('Fixture', shirt, profile=F)
        miss = missing_of(p)
        check(p.get('not_declared') == [], f"[6] F: nothing undeclared (got {p.get('not_declared')})")
        check(miss.get('tip', {}).get('pieces') == ['Shirt'] and miss['tip']['state'] == model3d.EXT_PRESENCE_COVERED,
              f"[6] tip covered by [Shirt] (got {miss.get('tip')})")
        check(miss.get('pair', {}).get('pieces') == [] and miss['pair']['light'] == 'yellow'
              and miss['pair']['reason'] == model3d.EXT_PRESENCE_NOT_ON_MODEL,
              f"[6] pair is not removed by clothing: yellow, not on this model (got {miss.get('pair')})")
        see = outfit({'top': 'item_shirt_see'}, {'groups': [], 'status': 'none_applicable'})
        miss = missing_of(model3d.extension_presence('Fixture', see, profile=F))
        check(miss.get('tip', {}).get('pieces') == [] and miss['tip']['reason'] == model3d.EXT_PRESENCE_NOT_ON_MODEL,
              f"[6] exposed_detail shirt: tip not covered, not on this model (got {miss.get('tip')})")

    # [7] wiring.
    m3d = (ROOT / 'app/core/model3d.py').read_text()
    fb = (ROOT / 'app/core/figure_build.py').read_text()
    viewer = (ROOT / 'frontend/src/tabs/characters/Model3DViewer.tsx').read_text()
    fig = (ROOT / 'frontend/src/tabs/characters/FieldFigure.tsx').read_text()
    tab3d = (ROOT / 'frontend/src/tabs/characters/FieldModel3D.tsx').read_text()
    helper = (ROOT / 'frontend/src/tabs/characters/extensionPresence.ts').read_text()
    check('info["extension_presence"] = extension_presence(' in m3d, "[7] get_model3d_info sets extension_presence")
    check('"served_extension": _served_extension(character_name, profile)' in fb, "[7] Figure payload served_extension")
    check('{extensionNote}' in viewer and 'extensionNote = null' in viewer, "[7] Model3DViewer renders extensionNote")
    check('extensionNote={<ExtensionPresenceNote presence={data.served_extension} />}' in fig,
          "[7] FieldFigure passes the note")
    check('extensionNote={<ExtensionPresenceNote presence={model.extension_presence} />}' in tab3d,
          "[7] FieldModel3D passes the note")
    de = json.loads((ROOT / 'shared/languages/de.json').read_text(encoding='utf-8'))['translations']
    keys = ['Extension bones on this model: {ids}', 'Extension bones: none on this model',
            'Not declared for this character: {ids}', model3d.EXT_PRESENCE_COVERED,
            model3d.EXT_PRESENCE_COVERED_REASON, model3d.EXT_PRESENCE_NOT_ON_MODEL]
    check(all(k in de for k in keys), f"[7] de.json keys: missing {[k for k in keys if k not in de]}")
    check(all(k in helper for k in keys[:3]), "[7] the client strings are the helper's")

print("ALL OK" if not FAILS else f"{len(FAILS)} FAILED")
sys.exit(1 if FAILS else 0)
