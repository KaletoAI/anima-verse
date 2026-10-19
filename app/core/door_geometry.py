"""Pure door solids in wall coordinates: x along wall, y up, z through wall."""
import math

from app.core.door_styles import validate_door_style


def leaves_for(style: dict, width: float) -> int:
    """Return the leaf count at the style's inclusive double-door threshold."""
    return 2 if width >= validate_door_style(style)['double_from_m'] else 1


def _bounds(vertices):
    return {key: [fn(p[k] for p in vertices) for k in range(3)]
            for key, fn in (('min', min), ('max', max))}


def _box(parts, node, material, lo, hi, uv_sizes):
    """Append an indexed closed box; disconnected solids share a role part."""
    if any(b <= a for a,b in zip(lo,hi)):
        return
    key = (node, material)
    part = parts.setdefault(key, dict(node=node, material=material,
                                     vertices=[], faces=[], uvs=[], colors=[]))
    x,y,z = lo
    X,Y,Z = hi
    vertices = [[x,y,z],[X,y,z],[X,Y,z],[x,Y,z],
                [x,y,Z],[X,y,Z],[X,Y,Z],[x,Y,Z]]
    faces = [[0,3,2,1],[4,5,6,7],[0,1,5,4],
             [3,7,6,2],[0,4,7,3],[1,2,6,5]]
    start = len(part['vertices'])
    part['vertices'].extend(vertices)
    size = uv_sizes.get(material, 1.0)
    for face, axes in zip(faces, ((0,1),(0,1),(0,2),(0,2),(1,2),(1,2))):
        part['faces'].append([start+i for i in face])
        part['uvs'].append([[vertices[i][k]/size for k in axes] for i in face])
        part['colors'].append([1.0]*4)


def _panels(box, x0, x1, y0, y1, count):
    """Raise panels on both faces, keeping borders inside the leaf rectangle."""
    if not count:
        return
    cols, rows = (2,2) if count == 4 else (1,2)
    margin = min(.10, (x1-x0)/8, (y1-y0)/8)
    for col in range(cols):
        a = x0 + (x1-x0)*col/cols + margin
        b = x0 + (x1-x0)*(col+1)/cols - margin
        for row in range(rows):
            c = y0 + (y1-y0)*row/rows + margin
            d = y0 + (y1-y0)*(row+1)/rows - margin
            for z0,z1 in ((-.0345,-.0225),(.0225,.0345)):
                box('door_leaf', a,b,c,d,z0,z1)


def _glazing(box, style, x0, x1, y0, y1):
    """Build stiles, rails and real panes without an opaque backing box."""
    border = min(.07, (x1-x0)/5, (y1-y0)/8)
    a,b = x0+border,x1-border
    c,d = y0+border,y1-border
    box('door_leaf',x0,a,y0,y1,-.0225,.0225)
    box('door_leaf',b,x1,y0,y1,-.0225,.0225)
    box('door_leaf',a,b,y0,c,-.0225,.0225)
    box('door_leaf',a,b,d,y1,-.0225,.0225)
    glazed = style['leaf'] == 'glazed'
    if glazed:
        bottom = y0+(y1-y0)*.38
        box('door_leaf',a,b,c,bottom,-.0225,.0225)
        _panels(box,a,b,c,bottom,2)
        box('door_leaf',a,b,bottom,bottom+.04,-.0225,.0225)
        c = bottom+.04
    rows = style['glass_rows'] if glazed else 1
    cols = style['glass_cols'] if glazed else 1
    # Each cell owns a pane; intermediate bars are .04 m wide.
    dx,dy = (b-a)/cols,(d-c)/rows
    for col in range(cols):
        left,right = a+col*dx, a+(col+1)*dx
        for row in range(rows):
            low,high = c+row*dy,c+(row+1)*dy
            box('glass',left+(.02 if col else 0),right-(.02 if col<cols-1 else 0),
                low+(.02 if row else 0),high-(.02 if row<rows-1 else 0),-.005,.005)
    for col in range(1,cols):
        x = a+col*dx
        box('door_leaf',x-.02,x+.02,c,d,-.0225,.0225)
    for row in range(1,rows):
        y = c+row*dy
        box('door_leaf',a,b,y-.02,y+.02,-.0225,.0225)


def _hardware(box, style, x0, x1, y0, y1, outside):
    """Place shallow handle proxies on both faces and straps/studs outside."""
    x = max(x0+.015, x1-.06)
    y = max(y0+.03, min(1.0,y1-.03))
    dx,dy = {'lever':(.08,.02),'knob':(.03,.03),
             'ring':(.04,.06),'bar':(.025,.40)}[style['hardware']]
    dx = min(dx, 2*(x-x0), 2*(x1-x))
    dy = min(dy, 2*(y-y0), 2*(y1-y))
    for sign in (-1,1):
        zs = sorted((sign*.0225, sign*.0365))
        box('hardware',x-dx/2,x+dx/2,y-dy/2,y+dy/2,*zs)
    zs = sorted((outside*.0225,outside*.0305))
    if style['strap_hinges']:
        margin = min(.10,(y1-y0)/5)
        for y in (y0+margin,y1-margin):
            box('hardware',x0+.01,x0+(x1-x0)*.55,y-.015,y+.015,*zs)
    if style['studs']:
        for x in (x0+.03,x1-.03):
            for fraction in (.15,.38,.62,.85):
                y = y0+(y1-y0)*fraction
                box('hardware',x-.007,x+.007,y-.007,y+.007,*zs)


def build_door(style: dict, width: float, height: float, thickness: float, *,
               piece: str = 'single', outside: int = 1, tier: str = 'full',
               uv_sizes: dict | None = None) -> dict:
    """Build role-merged closed boxes with per-corner metre UVs.

    The opening spans x .07 .. .07+width, below the head at height.
    double_a contains the frame and one half leaf. double_b is the right
    leaf alone in its own hinge frame: x=0 is its hinge edge and y=0 its
    bottom edge. The placer lifts double_b by 0.025 m and mirrors it for
    the right hinge. leaf_bbox describes the structural swing leaf; shallow
    ornaments may project at most .015 m beyond it. Low tier omits details.
    """
    if piece not in ('single','double_a','double_b'):
        raise ValueError('piece must be single, double_a or double_b')
    if tier not in ('full','low') or outside not in (-1,1):
        raise ValueError('tier must be full or low and outside must be +1 or -1')
    if not all(math.isfinite(v) for v in (width,height,thickness)) or width <= .15 or height <= .15 or thickness <= 0:
        raise ValueError('door dimensions must be finite and positive, width/height above .15 m')
    uv_sizes = uv_sizes or {}
    if any(not math.isfinite(v) or v <= 0 for v in uv_sizes.values()):
        raise ValueError('UV sizes must be finite and positive')
    style = validate_door_style(style)
    parts = {}
    depth = (thickness+.04)/2
    if piece != 'double_b':
        for lo,hi in (([0,0,-depth],[.07,height,depth]),
                      ([width+.07,0,-depth],[width+.14,height,depth]),
                      ([0,height,-depth],[width+.14,height+.07,depth]),
                      ([.07,0,-depth],[width+.07,.02,depth])):
            _box(parts,'frame','door_frame',lo,hi,uv_sizes)
    leaf_width = width-.01 if piece == 'single' else (width-.015)/2
    x0 = 0 if piece == 'double_b' else .075
    y0 = 0 if piece == 'double_b' else .025
    x1,y1 = x0+leaf_width,y0+height-.030
    leaf_bbox = {'min':[x0,y0,-.0225], 'max':[x1,y1,.0225]}

    def box(material,a,b,c,d,e,f):
        _box(parts,'leaf',material,[a,c,e],[b,d,f],uv_sizes)

    if tier == 'full' and style['leaf'] in ('glass','glazed'):
        _glazing(box,style,x0,x1,y0,y1)
    else:
        box('door_leaf',x0,x1,y0,y1,-.0225,.0225)
    if tier == 'full':
        if style['leaf'] == 'panel':
            capacity = 4 if leaf_width >= .7 and y1-y0 >= 1.9 else 2 if leaf_width >= .55 else 0
            _panels(box,x0,x1,y0,y1,min(style['panels'],capacity))
        _hardware(box,style,x0,x1,y0,y1,outside)
    bounds = _bounds([v for part in parts.values() for v in part['vertices']])
    return dict(parts=list(parts.values()), bounds=bounds, leaf_bbox=leaf_bbox,
                size_m=[bounds['max'][k]-bounds['min'][k] for k in (0,1)])
