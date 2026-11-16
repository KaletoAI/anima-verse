"""Vendored subset of svgpathtools 1.8.0 (MIT, see LICENSE) — the path/bezier maths
pygarment needs. The SVG writer/reader modules (paths2svg, document, svg_to_paths,
smoothing) are left out: they need ``svgwrite`` and we never draw SVG."""
from .bezier import (bezier_point, bezier2polynomial,
                     polynomial2bezier, split_bezier,
                     bezier_bounding_box, bezier_intersections,
                     bezier_by_line_intersections)
from .path import (Path, Line, QuadraticBezier, CubicBezier, Arc,
                   bezier_segment, is_bezier_segment, is_path_segment,
                   is_bezier_path, concatpaths, poly2bez, bpoints2bezier,
                   closest_point_in_path, farthest_point_in_path,
                   path_encloses_pt, bbox2path, polygon, polyline)
from .parser import parse_path, parse_transform, SVGSyntaxWarning
from .polytools import polyroots, polyroots01, rational_limit, real, imag
