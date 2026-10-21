"""Pure window solids: x along wall, y up, outside on signed z."""
import math

from app.core.door_geometry import _box, _bounds
from app.core.hull_facades import casement_bars
from app.core.window_styles import validate_window_style


def build_window(style: dict, width: float, height: float, thickness: float, *,
                 outside: int = 1, bars: bool = True, tier: str = 'full',
                 uv_sizes: dict | None = None) -> dict:
    """Build casing, casement, glazing and two sills as role-merged boxes.

    The hole begins at (.08,.07). Low tier keeps the ring and glass but
    omits bars. Sills face away from and toward the room respectively.
    """
    if tier not in ('full','low') or outside not in (-1,1):
        raise ValueError('tier must be full or low and outside must be +1 or -1')
    if not all(math.isfinite(v) for v in (width,height,thickness)) or width <= .15 or height <= .15 or thickness <= 0:
        raise ValueError('window dimensions must be finite and positive, width/height above .15 m')
    uv_sizes = uv_sizes or {}
    if any(not math.isfinite(v) or v <= 0 for v in uv_sizes.values()):
        raise ValueError('UV sizes must be finite and positive')
    style = validate_window_style(style)
    parts = {}

    def box(material, a,b,c,d,e,f):
        _box(parts, 'glass' if material == 'glass' else 'frame', material,
             [a,c,e], [b,d,f], uv_sizes)

    def ring(a,b,c,d, border, depth):
        for x0,x1,y0,y1 in ((a,a+border,c,d),(b-border,b,c,d),
                              (a+border,b-border,c,c+border),
                              (a+border,b-border,d-border,d)):
            box('window_frame',x0,x1,y0,y1,-depth,depth)

    x0,x1,y0,y1 = .08,width+.08,.07,height+.07
    ring(x0-.06,x1+.06,y0-.06,y1+.06,.06,(thickness+.04)/2)
    border = .05 if style['frame'] == 'metal' else .06
    ring(x0,x1,y0,y1,border,.03)
    if tier == 'full' and bars and style['bars']:
        centres, transom, bar_width = casement_bars(x0,x1,y0,y1,style['frame'])
        half = bar_width/2
        for centre in centres:
            box('window_frame',centre-half,centre+half,y0+border,y1-border,-.02,.02)
        if transom is not None:
            box('window_frame',x0+border,x1-border,transom-half,transom+half,-.02,.02)
    box('glass',x0+border,x1-border,y0+border,y1-border,-.005,.005)
    for start,end in ((thickness/2,thickness/2+.10),
                      (-thickness/2-.18,-thickness/2)):
        z0,z1 = sorted((outside*start,outside*end))
        box('trim',0,width+.16,0,.07,z0,z1)
    bounds = _bounds([v for part in parts.values() for v in part['vertices']])
    return dict(parts=list(parts.values()), bounds=bounds, size_m=[width+.16,height+.13])
