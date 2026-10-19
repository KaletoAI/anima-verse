#!/usr/bin/env python3
"""Hand-derived rows, with positive shoelace winding in plot metres.

A=[0,6]x[0,4], B=[6,10]x[0,8]: area 24+32=56; outline
(0,0),(10,0),(10,8),(6,8),(6,4),(0,4). B starting at 6.2
clusters to 6 (tie -> smallest), but 6.3/6.4 remain separate.
B ending at 4.2 clusters to 4 -> 10x4 rectangle. Four strips in
[0,6]^2 leave [2,4]^2 empty -> 2x2 hole. Upper A has area 24;
upper A+B is identical, no override; upper x=11 overhangs by 1.
Small [0,1.2]: run 0,.25,.3,.5,.75 wins at .3 (two rooms),
run 1.2,1.4 wins at 1.2 -> width .9<1, preserve original.
Relative L translated to (-3,2): area 6*2+2*4=20. Padding the
first contour by 2 -> [-2,12]x[-2,10]. Triangle x+y<=4 has cell
centres i+j<=79: 80*81/2=3240 cells, area 3240*.05^2=8.1.
"""
from copy import deepcopy
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.layout_contour import align_rooms, derive_contour, seed_boundary


def room(key, x, y, w, d, level=0, **extra):
    return {"room_id":key, "layout":dict(x=x,y=y,w=w,d=d,level=level,**extra)}


def codes(rows):
    return {e["code"] for e in derive_contour(rows)["errors"]}


def main():
    a,b = room("a",0,0,6,4),room("b",6,0,4,8)
    expected = [[0,0],[10,0],[10,8],[6,8],[6,4],[0,4]]
    before = deepcopy([a,b])
    assert derive_contour([a,b])["outline"] == expected
    assert [a,b] == before
    print("PASS L union, winding, purity")
    assert derive_contour([a,room("b",6.2,0,3.8,8)])["outline"] == expected
    for x in (6.3,6.4):
        assert "contour_split" in codes([a,room("b",x,0,10-x,8)])
    assert derive_contour([a,room("b",6,0,4,4.2)])["outline"] == [[0,0],[10,0],[10,4],[0,4]]
    print("PASS alignment, strict threshold, split, facade jog")
    ring = [room("n",0,0,6,2),room("s",0,4,6,2),room("w",0,2,2,2),room("e",4,2,2,2)]
    assert "contour_hole" in codes(ring)
    assert "contour_split" in codes([room("a",0,0,2,2),room("b",2,2,2,2)])
    assert derive_contour([a,b,room("u",0,0,6,4,1)])["level_outlines"] == {"1":[[0,0],[6,0],[6,4],[0,4]]}
    assert not derive_contour([a,b,room("u",0,0,6,4,1),room("v",6,0,4,8,1)])["level_outlines"]
    assert "storey_overhang" in codes([a,b,room("u",0,0,11,8,1)])
    assert "storey_overhang" in codes([room("g",0,0,10,10),room("u",4,4,6,6,1),room("v",0,0,10,10,2)])
    print("PASS hole, point contact, storeys, cascade, overhang")
    small = room("small",0,0,1.2,4,openings=[{"at":.4}])
    rows = [small,room("p",.3,0,3,4),room("q",.3,0,3,4),room("bridge",.25,0,3,4),room("r",.5,0,3,4),room("s",.75,0,3,4),room("t",1.4,0,3,4)]
    aligned,warnings = align_rooms(rows)
    assert aligned[0] == small
    assert any(w["code"]=="room_too_small" and w["ref"]=="small" for w in warnings)
    assert derive_contour([a,b,room("cellar",-100,-100,200,200,-1)])["outline"] == expected
    assert derive_contour([room("cellar",0,0,4,4,-1)])["outline"] is None
    assert aligned[1]["layout"]["x"] == .3
    # Width .9 triggers the guard: endpoint 10.05 survives alignment,
    # exactly one grid tick beyond the ground; endpoint 10.10 must fail.
    ground = room("ground",0,0,10,10)
    assert "storey_overhang" not in codes([ground,room("u",9.15,0,.9,10,1)])
    assert "storey_overhang" in codes([ground,room("u",9.2,0,.9,10,1)])
    moving = room("moving",6.2,0,3.8,8,openings=[{"at":.37}])
    aligned,_ = align_rooms([a,moving])
    assert aligned[1]["layout"]["x"] == 6
    assert aligned[1]["layout"]["openings"] == [{"at":.37}]
    print("PASS small-room guard, opening preservation, cellars, 5 cm tolerance")
    poly = [[0,0],[6,0],[6,2],[2,2],[2,6],[0,6]]
    assert derive_contour([room("L",-3,2,6,6,outline=poly)])["outline"] == [[x-3,y+2] for x,y in poly]
    assert derive_contour([room("L",-3,2,6,6,outline=poly),room("fill",-1,4,4,4)])["outline"] == [[-3,2],[3,2],[3,8],[-3,8]]
    assert seed_boundary(expected) == [[-2,-2],[12,-2],[12,10],[-2,10]]
    assert derive_contour([room("snap",.021,.021,3.98,3.98)])["outline"] == [[0,0],[4,0],[4,4],[0,4]]
    print("PASS relative polygon, boundary padding, snapping")
    result = derive_contour([room("triangle",0,0,4,4,outline=[[0,0],[4,0],[0,4]])])
    assert not result["errors"], result
    p = result["outline"]
    area = sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(p,p[1:]+p[:1]))/2
    assert abs(area-8.1)<1e-8, area
    poly = room("poly",0,0,4,4,outline=[[0,0],[4,0],[4,4],[.2,4],[.2,2],[0,2]])
    aligned,_ = align_rooms([poly,room("one",.2,0,4,4),room("two",.2,0,4,4)])
    assert aligned[0]["layout"]["x"] == .2
    print("PASS diagonal raster, distinct room votes")
    print("smoke_layout_contour: all rows passed")


if __name__ == "__main__":
    main()
