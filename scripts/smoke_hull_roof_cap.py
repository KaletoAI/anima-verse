"""Hand-derived roof-cap rows (single storey, eaves y=3).

Stone 12x12: outer=.04+.5=.54, half_span=6.54; 40° rise=5.49,
atan(4.5/6.54)=34.53° ±.01, rise=4.50 ±.005, no flat top.
Timber 20x16: outer=.34, half_span=8.34; auto 50° lowers to 40°;
rise=7.00>6, cap width=2*(8.34-6/tan40)=2.38 ±.01.
Explicit stone 50° stays 50°, truncates at 4.5. Timber cap override 8
makes atan(8/8.34)=43.81° ±.01 without truncation. Square hip at the
lowered pitch has one apex, no zero-width slab. Chimney top <= top+.9;
rise <1.6 suppresses dormers. Slabs retain .15 thickness.
"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _hull_fixtures import polygon_case_facts, no_degenerate_faces
from smoke_hull_roofs import closed
from app.core.hull_roofs import build_roofs

ROOT = Path(__file__).resolve().parents[1]
def case(name, length, depth, form, overrides=None):
    style = json.loads((ROOT / "shared/building_styles" / f"{name}.json").read_text())
    style["roof"]["pitch_deg"] = [40,40] if name == "steinhaus" else [50,50]
    style.update(chimneys=[1,1], dormers=1)
    facts = polygon_case_facts([[0,0],[length,0],[length,depth],[0,depth]])
    parts, info = build_roofs(facts, style, {"seed":7, "overrides":{"roof_form":form, "ornament_density":1, **(overrides or {})}}, tier="full")
    wing = info["wings"][0]
    for part in parts:
        no_degenerate_faces([part])
        if part["tag"] == "roof": closed(part)
    return parts, wing

def check():
    parts, wing = case("steinhaus",12,12,"hip")
    assert abs(wing["pitch_deg"]-34.53)<.01, wing
    assert abs(wing["ridge_y"]-wing["eaves_y"]-4.50)<.005
    assert wing["flat_top"] is False
    peaks = {tuple(v) for p in parts if p["tag"]=="roof" for v in p["vertices"] if abs(v[1]-wing["ridge_y"])<.0001}
    assert len(peaks)==1
    parts, wing = case("fachwerk",20,16,"gable")
    assert wing["pitch_deg"]==40 and wing["flat_top"]
    assert abs(wing["ridge_y"]-wing["eaves_y"]-6)<.0001
    caps = [p for p in parts if p["tag"]=="roof" and len({v[1] for v in p["vertices"]})==2]
    assert len(caps)==1
    assert abs(max(v[1] for v in caps[0]["vertices"])-min(v[1] for v in caps[0]["vertices"])-.15)<.0001
    assert abs(max(v[2] for v in caps[0]["vertices"])-min(v[2] for v in caps[0]["vertices"])-2.38)<.01
    for p in parts:
        if p["tag"]=="gable":
            assert len(p["vertices"])==4
            assert abs(max(v[1] for v in p["vertices"])-wing["ridge_y"])<.0001
        if p["tag"]=="chimney": assert max(v[1] for v in p["vertices"])<=wing["ridge_y"]+.9001
    _, wing = case("steinhaus",12,12,"hip",{"pitch_deg":50})
    assert wing["pitch_deg"]==50 and wing["flat_top"]
    assert abs(wing["ridge_y"]-wing["eaves_y"]-4.5)<.0001
    _, wing = case("fachwerk",20,16,"gable",{"max_rise_m":8})
    assert abs(wing["pitch_deg"]-43.81)<.01 and not wing["flat_top"]
    parts, _ = case("fachwerk",20,16,"gable",{"max_rise_m":1.5})
    assert not any(p["tag"]=="dormer" for p in parts)
    print("PASS roof rise cap")
def check_extra():
    """Triangle centroid (26/3,16/3); explicit 50° is capped at rise 1.5.
    Shed 20x16 has full wall-span rise 16.68*tan50, capped at 1.5.
    Sampling at the center must report the flat cap, not the old apex.
    """
    from app.core.hull_roofs import roof_top_y
    from app.core.hull_styles import validate_style, validate_description
    style = json.loads((ROOT/"shared/building_styles/fachwerk.json").read_text())
    for outline, form in (([[0,0],[20,0],[6,16]], "hip"),
                          ([[0,0],[20,0],[20,16],[0,16]], "shed")):
        parts, info = build_roofs(polygon_case_facts(outline), style,
            {"overrides":{"roof_form":form,"pitch_deg":50,"max_rise_m":1.5}}, tier="full")
        wing = info["wings"][0]
        assert wing["flat_top"] and wing["pitch_deg"] == 50
        assert abs(wing["ridge_y"]-4.5)<.0001
        for part in parts:
            no_degenerate_faces([part])
            if part["tag"] == "roof": closed(part)
        if wing["form"] == "tent":
            x,z = wing["rect"]["center"]
            assert abs(roof_top_y(wing,x,z,style)-4.5)<.0001
    assert validate_style({}, "x")["roof"]["max_rise_m"] == 6
    assert validate_style({}, "x")["roof"]["min_pitch_deg"] == 20
    for value, expected in ((0,1.5),(99,12)):
        assert validate_style({"roof":{"max_rise_m":value}}, "x")["roof"]["max_rise_m"] == expected
        assert validate_description({"overrides":{"max_rise_m":value}}, {})["overrides"]["max_rise_m"] == expected
    for value, expected in ((0,5),(99,60)):
        assert validate_style({"roof":{"min_pitch_deg":value}}, "x")["roof"]["min_pitch_deg"] == expected
    print("PASS tent, shed and validation")
if __name__ == "__main__":
    check()
    check_extra()
