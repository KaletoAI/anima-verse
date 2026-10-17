"""Plain location fixtures shared by hull smoke scripts; no storage imports."""


def stepped_house():
    """A two-storey rectangle with a setback and four contour openings."""
    return {
        "id": "hull-demo",
        "map3d": {
            "outline": [[0, 0], [10, 0], [10, 8], [0, 8]],
            "level_outlines": {"1": [[0, 0], [6, 0], [6, 8], [0, 8]]},
            "storey_height_m": 3.0,
            "boundary": [[0, 0], [10, 0], [10, 8], [0, 8]],
        },
        "rooms": [
            {"id": "a", "layout": {"x": 0, "y": 0, "w": 10, "d": 8,
                "level": 0, "openings": [
                    {"edge": 0, "at": 0.5, "width_m": 1.2,
                     "height_m": 1.2, "sill_m": 0.9, "type": "window"},
                    {"edge": 2, "at": 0.3, "width_m": 1.0,
                     "height_m": 2.1, "type": "door", "to": "outside"}]}},
            {"id": "b", "layout": {"x": 0, "y": 0, "w": 6, "d": 8,
                "level": 1, "openings": [
                    {"edge": 1, "at": 0.5, "width_m": 1.2,
                     "height_m": 1.2, "sill_m": 0.9, "type": "window"},
                    {"edge": 3, "at": 0.5, "width_m": 1.0,
                     "height_m": 2.4, "type": "passage", "to": "outside"}]}},
        ],
    }


def without_outline():
    """Rooms alone must never synthesize a building contour."""
    loc = stepped_house()
    loc["map3d"].pop("outline")
    loc["map3d"].pop("level_outlines")
    return loc


def opening_edge_cases(facts):
    """Independent fact copies exercising clipping and adjacent apertures."""
    from copy import deepcopy
    cases = []
    for holes in (
        [dict(s0=-0.3, s1=1, y0=0.9, y1=2.1, kind='window')],
        [dict(s0=s, s1=s+1, y0=0.9, y1=2.1, kind='window') for s in (2, 3)],
        [dict(s0=-2, s1=20, y0=0, y1=2.1, kind='door')],
    ):
        case = deepcopy(facts)
        case['levels'][0]['edges'][0]['openings'] = holes
        cases.append(case)
    return cases


def count(parts, *, tag):
    return sum(p['tag'] == tag for p in parts)


def total_openings(facts):
    return sum(len(e['openings']) for l in facts['levels'] for e in l['edges'])


def windows(facts):
    return sum(h['kind'] == 'window' for l in facts['levels'] for e in l['edges'] for h in e['openings'])


def doors(facts):
    return sum(h['kind'] == 'door' for l in facts['levels'] for e in l['edges'] for h in e['openings'])


def face_normal(points):
    return [sum((a[(i+1)%3]-b[(i+1)%3])*(a[(i+2)%3]+b[(i+2)%3])
                for a, b in zip(points, points[1:]+points[:1])) for i in range(3)]


def no_degenerate_faces(parts):
    import math
    for part in parts:
        for face in part['faces']:
            pts = [part['vertices'][i] for i in face]
            if not all(math.isfinite(v) for p in pts for v in p):
                return False
            normal = face_normal(pts)
            length = math.sqrt(sum(v*v for v in normal))
            if length < 2e-6:
                return False
            if any(abs(sum(normal[k]*(p[k]-pts[0][k]) for k in range(3))) > length*2e-4 for p in pts):
                return False
    return True


def no_face_overlaps_openings(parts, facts):
    """Check positive-area overlap on wall, plinth and interior facade planes."""
    import math
    for level in facts['levels']:
        for edge in level['edges']:
            a, b, n = edge['a'], edge['b'], edge['normal']
            length = math.dist(a, b)
            u = [(b[i]-a[i])/length for i in range(2)]
            for part in parts:
                if part['tag'] not in ('wall', 'plinth', 'interior'):
                    continue
                for face in part['faces']:
                    pts = [part['vertices'][i] for i in face]
                    normal = face_normal(pts)
                    if abs(normal[1]) > 1e-5 or abs(normal[0]*u[0]+normal[2]*u[1]) > 1e-4:
                        continue
                    distances = [(p[0]-a[0])*n[0]+(p[2]-a[1])*n[1] for p in pts]
                    if min(distances) < 0 or max(distances) > 1.3:
                        continue
                    ss = [(p[0]-a[0])*u[0]+(p[2]-a[1])*u[1] for p in pts]
                    ys = [p[1] for p in pts]
                    if min(ys) < level['floor_y']-0.141 or max(ys) > level['top_y']+1e-4:
                        continue
                    for hole in edge['openings']:
                        if min(max(ss), hole['s1'], length)-max(min(ss), hole['s0'], 0) > 1e-4 and min(max(ys), hole['y1'])-max(min(ys), hole['y0']) > 1e-4:
                            return False
    return True


def outer_face_distance(parts, facts):
    edge = facts['levels'][0]['edges'][0]
    a, n = edge['a'], edge['normal']
    distances = []
    for part in parts:
        if part['tag'] != 'wall':
            continue
        for face in part['faces']:
            pts = [part['vertices'][i] for i in face]
            normal = face_normal(pts)
            if normal[0]*n[0]+normal[2]*n[1] <= 1e-6:
                continue
            ds = [(p[0]-a[0])*n[0]+(p[2]-a[1])*n[1] for p in pts]
            if max(ds)-min(ds) < 1e-4 and min(ds) > 0:
                distances.append(ds[0])
    return min(distances)


def polygon_case_facts(outline):
    """Synthetic supplied facts for generic mesh/offset stress checks."""
    import math
    area = sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(outline,outline[1:]+outline[:1]))
    ccw = area > 0
    edges = []
    for i,a in enumerate(outline):
        b = outline[(i+1)%len(outline)]
        length = math.dist(a,b)
        ux,uz = (b[0]-a[0])/length,(b[1]-a[1])/length
        edges.append(dict(index=i,a=a,b=b,length=length,
                          normal=[uz,-ux] if ccw else [-uz,ux],openings=[]))
    return dict(ok=True,eaves_y=3,levels=[dict(level=0,floor_y=0,top_y=3,
                outline=outline,ccw=ccw,edges=edges)])


def roof_shapes() -> dict:
    """Return direct facts for roof polygons; room/location data is unnecessary.

    The existing stepped_house location still exercises hull_facts composition.
    These polygons supply only geometry already represented by hull facts.
    """
    import math
    outlines = {
        "rectangle": [[0, 0], [10, 0], [10, 8], [0, 8]],
        "L": [[0, 0], [10, 0], [10, 4], [4, 4], [4, 8], [0, 8]],
        "T": [[0, 0], [10, 0], [10, 3], [7, 3], [7, 8], [3, 8], [3, 3], [0, 3]],
        "U": [[0, 0], [10, 0], [10, 8], [7, 8], [7, 3], [3, 3], [3, 8], [0, 8]],
        "triangle": [[0, 0], [10, 0], [3, 8]],
        "concave": [[0, 0], [10, 0], [7, 3], [4, 2], [3, 8], [0, 8]],
    }
    angle = math.radians(30)
    outlines["rotated_L"] = [
        [x * math.cos(angle) - z * math.sin(angle),
         x * math.sin(angle) + z * math.cos(angle)] for x, z in outlines["L"]
    ]
    return {name: polygon_case_facts(outline) for name, outline in outlines.items()}


def rect_facts() -> dict:
    """A supplied 10 by 8 metre storey with one door and one window."""
    facts = polygon_case_facts([[0, 0], [10, 0], [10, 8], [0, 8]])
    facts["levels"][0]["edges"][0]["openings"] = [
        {"s0": 2.0, "s1": 3.2, "y0": 0.0, "y1": 2.1, "kind": "door"},
        {"s0": 6.0, "s1": 7.2, "y0": 0.9, "y1": 2.1, "kind": "window"},
    ]
    return facts


def l_shaped_house(*, rotated: bool = False) -> dict:
    """Return a three-storey 20 by 14 L with 24 windows and two doors."""
    import math

    outline = [[0, 0], [20, 0], [20, 6], [8, 6], [8, 14], [0, 14]]
    if rotated:
        angle = math.radians(30)
        outline = [[x * math.cos(angle) - z * math.sin(angle),
                    x * math.sin(angle) + z * math.cos(angle)] for x, z in outline]
    minimum_x = min(point[0] for point in outline)
    minimum_z = min(point[1] for point in outline)
    rooms = []
    for level in range(3):
        openings = [
            {"edge": edge, "at": at, "width_m": 1.2, "height_m": 1.2,
             "sill_m": 0.9, "type": "window"}
            for edge, positions in ((0, (.2, .5, .8)), (2, (.25, .75)),
                                    (4, (.5,)), (5, (.25, .75)))
            for at in positions
        ]
        if level == 0:
            openings.extend({"edge": edge, "at": .5, "width_m": 1.0,
                             "height_m": 2.1, "type": "door", "to": "outside"}
                            for edge in (1, 3))
        rooms.append({"id": f"l-floor-{level}", "layout": {
            "x": minimum_x, "y": minimum_z,
            "w": max(point[0] for point in outline) - minimum_x,
            "d": max(point[1] for point in outline) - minimum_z,
            "outline": [[x - minimum_x, z - minimum_z] for x, z in outline],
            "level": level, "openings": openings}})
    return {"id": "hull-large-L", "map3d": {
        "outline": outline, "boundary": outline, "storey_height_m": 3.0},
        "rooms": rooms}
