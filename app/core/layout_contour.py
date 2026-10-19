"""Derive building shells without a database or a geometry dependency.

Inputs are normalized ``{room_id, layout}`` entries. Room outline vertices
are metres RELATIVE to layout.x/y, whereas returned contours are absolute
plot metres (x east, y south). Rings are open, start at the smallest (x,y),
and have positive shoelace area: counter-clockwise in mathematical x/y,
clockwise on the editor's y-down map. This matches ``_hull_fixtures`` and
``world_ops``; ``RoomLayoutEditor.writeLevelOutline`` preserves click order
and ``scene_recipe._outline_world`` parses that same frame without a turn.

Integer 0.05 m ticks avoid floating-point decisions at the strict 0.3 m
alignment threshold. Rectilinear rooms use compressed coordinate cells;
only diagonal polygons need every tick in their bounding box. Connectivity
and exterior flood fills reject islands and holes before tracing a ring.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from typing import Any

Point = tuple[int, int]
Cell = tuple[int, int]


def _tick(value: float) -> int:
    return round(value * 20)


def _metres(value: int) -> float:
    return round(value / 20, 2)


def _vertices(layout: dict) -> list[Point]:
    """Lift relative vertices before snapping, so translated rooms vote together."""
    x, y = layout['x'], layout['y']
    polygon = layout.get('outline') or [[0, 0], [layout['w'], 0],
                                      [layout['w'], layout['d']], [0, layout['d']]]
    return [(_tick(x + p[0]), _tick(y + p[1])) for p in polygon]


def _clusters(polygons: list[list[Point]], axis: int) -> dict[int, int]:
    """Count distinct rooms, so a detailed polygon has no extra voting power."""
    votes: Counter = Counter()
    for polygon in polygons:
        votes.update({p[axis] for p in polygon})
    runs: list[list[int]] = []
    for value in sorted(votes):
        if not runs or value - runs[-1][-1] >= 6:
            runs.append([])
        runs[-1].append(value)
    result = {}
    for run in runs:
        winner = min(run, key=lambda value: (-votes[value], value))
        result.update({value: winner for value in run})
    return result


def _finding(out: list[dict], code: str, ref: str, message: str) -> None:
    out.append({'code': code, 'ref': ref, 'message': message})


def align_rooms(rooms: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return independent room copies with globally aligned above-ground edges.

    Cellars neither vote nor move. The minimum-size guard keeps the original
    room unchanged, including its unsnapped coordinates, rather than damaging
    a narrow room to improve the facade. Openings retain their edge fractions.
    """
    aligned = deepcopy(rooms)
    eligible = [(i, _vertices(r['layout'])) for i, r in enumerate(rooms)
                if r.get('layout') and r['layout'].get('level', 0) >= 0]
    polygons = [p for _, p in eligible]
    xs, ys = _clusters(polygons, 0), _clusters(polygons, 1)
    warnings: list[dict] = []
    for index, polygon in eligible:
        moved = [(xs[x], ys[y]) for x, y in polygon]
        left, right = min(x for x, _ in moved), max(x for x, _ in moved)
        top, bottom = min(y for _, y in moved), max(y for _, y in moved)
        if right - left < 20 or bottom - top < 20:
            _finding(warnings, 'room_too_small',
                     str(rooms[index].get('room_id') or f'rooms[{index}]'),
                     'Edge alignment would make this room smaller than 1 m; '
                     'its original layout was kept.')
            continue
        layout = aligned[index]['layout']
        layout.update(x=_metres(left), y=_metres(top),
                      w=_metres(right-left), d=_metres(bottom-top))
        if layout.get('outline'):
            layout['outline'] = [[_metres(x-left), _metres(y-top)] for x, y in moved]
    return aligned, warnings


def _inside(x: float, y: float, polygon: list[Point]) -> bool:
    """Include boundary centres to make diagonal rasterisation deterministic."""
    inside = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        ax, ay = a
        bx, by = b
        cross = (x-ax)*(by-ay) - (y-ay)*(bx-ax)
        if abs(cross) < 1e-9 and min(ax,bx) <= x <= max(ax,bx) \
                and min(ay,by) <= y <= max(ay,by):
            return True
        if (ay > y) != (by > y) and x < ax + (y-ay)*(bx-ax)/(by-ay):
            inside = not inside
    return inside


def _axes(polygons: list[list[Point]]) -> tuple[list[int], list[int]]:
    """Compress straight walls, retaining unit ticks where rasterisation needs them."""
    xs, ys = set(), set()
    for polygon in polygons:
        xs.update(x for x, _ in polygon)
        ys.update(y for _, y in polygon)
        if any(a[0] != b[0] and a[1] != b[1]
               for a, b in zip(polygon, polygon[1:]+polygon[:1])):
            xs.update(range(min(x for x, _ in polygon), max(x for x, _ in polygon)+1))
            ys.update(range(min(y for _, y in polygon), max(y for _, y in polygon)+1))
    # A padding tick permits a genuine exterior flood fill on every side.
    return (sorted(xs | {min(xs)-1, max(xs)+1}),
            sorted(ys | {min(ys)-1, max(ys)+1}))


def _fill(polygons: list[list[Point]], xs: list[int], ys: list[int]) -> set[Cell]:
    """Use cell centres: rectilinear cells are exact, diagonal cells are 5 cm."""
    xi, yi = {x:i for i,x in enumerate(xs)}, {y:i for i,y in enumerate(ys)}
    filled: set[Cell] = set()
    for polygon in polygons:
        x0,x1 = min(x for x,_ in polygon), max(x for x,_ in polygon)
        y0,y1 = min(y for _,y in polygon), max(y for _,y in polygon)
        for i in range(xi[x0],xi[x1]):
            for j in range(yi[y0],yi[y1]):
                if _inside((xs[i]+xs[i+1])/2, (ys[j]+ys[j+1])/2, polygon):
                    filled.add((i,j))
    return filled


def _neighbours(cell: Cell) -> tuple[Cell, Cell, Cell, Cell]:
    x,y = cell
    return (x-1,y), (x+1,y), (x,y-1), (x,y+1)


def _flood(start: Cell, allowed: set[Cell]) -> set[Cell]:
    """Four-way connectivity rejects buildings touching only at one corner."""
    seen = {start}
    todo = [start]
    while todo:
        for neighbour in _neighbours(todo.pop()):
            if neighbour in allowed and neighbour not in seen:
                seen.add(neighbour)
                todo.append(neighbour)
    return seen


def _ring(cells: set[Cell], xs: list[int], ys: list[int]) -> tuple[list | None, list[str]]:
    """Reject topology before tracing, so a hole cannot silently become floor."""
    if not cells:
        return None, ['contour_split']
    errors = []
    if _flood(min(cells), cells) != cells:
        errors.append('contour_split')
    empty = {(i,j) for i in range(len(xs)-1) for j in range(len(ys)-1)} - cells
    if _flood((0,0), empty) != empty:
        errors.append('contour_hole')
    if errors:
        return None, errors
    edges: dict[Point, list[Point]] = defaultdict(list)
    for i,j in cells:
        a,b,c,d = (xs[i],ys[j]),(xs[i+1],ys[j]),(xs[i+1],ys[j+1]),(xs[i],ys[j+1])
        for neighbour, start, end in (((i,j-1),a,b), ((i+1,j),b,c),
                                      ((i,j+1),c,d), ((i-1,j),d,a)):
            if neighbour not in cells:
                edges[start].append(end)
    # A pinched boundary is not a simple polygon, even if its floor is connected.
    if any(len(ends) != 1 for ends in edges.values()):
        return None, ['contour_split']
    start = min(edges)
    points = [start]
    current = edges[start][0]
    while current != start:
        points.append(current)
        current = edges[current][0]
    if len(points) != len(edges):
        return None, ['contour_hole']
    corners = []
    for i,b in enumerate(points):
        a,c = points[i-1],points[(i+1)%len(points)]
        if (b[0]-a[0])*(c[1]-b[1]) != (b[1]-a[1])*(c[0]-b[0]):
            corners.append(b)
    first = corners.index(min(corners))
    corners = corners[first:]+corners[:first]
    return [[_metres(x),_metres(y)] for x,y in corners], []


def _contained(upper: set[Cell], lower: set[Cell], xs: list[int], ys: list[int]) -> bool:
    """Test the entire upper floor against a 5 cm expanded lower floor.

    Expansion is along each plot axis (one grid tick). Splitting expanded
    rectangles at their coordinates tests whole cells, including reentrant
    corners, rather than accepting a concavity because its vertices fit.
    """
    excess = upper - lower
    if not excess:
        return True
    rectangles = [(xs[i]-1, ys[j]-1, xs[i+1]+1, ys[j+1]+1) for i,j in lower]
    for i,j in excess:
        x0,x1,y0,y1 = xs[i],xs[i+1],ys[j],ys[j+1]
        candidates = [(a,b,c,d) for a,b,c,d in rectangles
                      if a < x1 and c > x0 and b < y1 and d > y0]
        cuts_x = sorted({x0,x1} | {v for a,_,c,_ in candidates for v in (a,c) if x0<v<x1})
        cuts_y = sorted({y0,y1} | {v for _,b,_,d in candidates for v in (b,d) if y0<v<y1})
        for a,b in zip(cuts_x,cuts_x[1:]):
            for c,d in zip(cuts_y,cuts_y[1:]):
                x,y = (a+b)/2,(c+d)/2
                if not any(left<=x<=right and top<=y<=bottom
                           for left,top,right,bottom in candidates):
                    return False
    return True


def derive_contour(rooms: list[dict]) -> dict:
    """Align copies and derive each occupied non-cellar storey's simple shell.

    The lowest occupied nonnegative level supplies ``outline``. Later levels
    compare with the preceding occupied storey, including levels whose equal
    contour was omitted from the cascade. Invalid storeys return findings and
    no polygon for that storey; callers must refuse Apply whenever errors exist.
    """
    aligned,warnings = align_rooms(rooms)
    result: dict[str, Any] = dict(outline=None,level_outlines={},errors=[],warnings=warnings)
    levels: dict[int, list[list[Point]]] = defaultdict(list)
    for room in aligned:
        layout = room.get('layout')
        if layout and layout.get('level',0) >= 0:
            levels[layout.get('level',0)].append(_vertices(layout))
    if not levels:
        return result
    xs,ys = _axes([p for polygons in levels.values() for p in polygons])
    previous_cells: set[Cell] | None = None
    previous_ring = None
    for index,level in enumerate(sorted(levels)):
        cells = _fill(levels[level],xs,ys)
        ring,errors = _ring(cells,xs,ys)
        for code in errors:
            _finding(result['errors'],code,str(level),
                     f'Storey {level} must form one connected contour without holes ({code}).')
        if previous_cells is not None and not _contained(cells,previous_cells,xs,ys):
            _finding(result['errors'],'storey_overhang',str(level),
                     f'Storey {level} extends beyond the storey below by more than 0.05 m.')
        if ring is not None:
            if index == 0:
                result['outline'] = ring
            elif ring != previous_ring:
                result['level_outlines'][str(level)] = ring
        previous_cells,previous_ring = cells,ring
    return result


def seed_boundary(outline: list) -> list:
    """Pad the contour box by 2 m to leave a walkable margin around the hull."""
    if not outline:
        return []
    left,right = min(p[0] for p in outline)-2,max(p[0] for p in outline)+2
    top,bottom = min(p[1] for p in outline)-2,max(p[1] for p in outline)+2
    return [[round(left,2),round(top,2)], [round(right,2),round(top,2)],
            [round(right,2),round(bottom,2)], [round(left,2),round(bottom,2)]]
