using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;
using AnimaNative.Overview;
using AnimaNative.Scatter;

namespace AnimaNative.Scene;

/// <summary>
/// The per-fragment cuts of one placed mesh, in WORLD coordinates (the browser's three patches, packages/scene-render):
///   • <see cref="Clip"/> — § B1 <c>clip_outline</c> (clip.ts): keep only what lies INSIDE the polygon (≤ 64 points);
///   • <see cref="Cutouts"/> — § B1 <c>cutouts</c> (cutouts.ts): discard what lies inside ANY polygon (≤ 16 × 64) or,
///     with <see cref="Padding"/> &gt; 0, within that distance of one of their edges; switched by the <c>cut_on</c>
///     uniform at runtime (starts off), never by a recompile;
///   • <see cref="Plane"/> — § B2 <c>cut_plane</c> (depthCut.ts): keep where <c>n·p + c ≥ 0</c>.
/// The polygons arrive already limited (<see cref="ClipMath"/>); <see cref="CutShader.Pack"/> applies those limits.
/// </summary>
public sealed record CutUniforms(
    IReadOnlyList<P2> Clip,
    IReadOnlyList<P2> CutPoints, IReadOnlyList<int> CutOffsets, IReadOnlyList<int> CutLengths,
    double Padding, CutPlaneData? Plane)
{
    public bool HasClip => Clip.Count >= 3;
    public bool HasCutouts => CutLengths.Count > 0;
    public bool HasPlane => Plane is not null;
    public bool Any => HasClip || HasCutouts || HasPlane;
    public int CutMaxLen => CutLengths.Count == 0 ? 0 : CutLengths.Max();

    /// <summary>
    /// What the compiled shader depends on (the browser's <c>customProgramCacheKey</c>s <c>clip:n</c> and
    /// <c>cutout:polys:lengths:padding</c>, plus the plane flag): two placements with the same key share one program.
    /// </summary>
    public string ShapeKey => string.Create(CultureInfo.InvariantCulture,
        $"clip:{(HasClip ? Clip.Count : 0)}|cutout:{CutLengths.Count}:{string.Join(",", CutLengths)}:{CutShader.Number(Padding)}|plane:{(HasPlane ? 1 : 0)}");
}

/// <summary>
/// The native form of the browser's room clip, area cutouts and depth cut: ONE test appended to a spatial shader's
/// code (<see cref="Inject"/>), evaluated per fragment on the fragment's world position — the browser does the same
/// in <c>onBeforeCompile</c> patches (clip and cutouts) and with a hardware clipping plane (the depth cut; here a
/// discard, because Godot has no per-material clip planes). <see cref="Discards"/> is the line-for-line CPU twin of the
/// injected GLSL, so the check can say which points a packed uniform set discards; its semantics are pinned to the
/// vector-checked <see cref="ClipMath"/> / <see cref="DepthCutMath"/> by the tests.
/// </summary>
public static class CutShader
{
    /// <summary>
    /// The uniforms of one placement: the clip outline and the cutout polygons through <see cref="ClipMath"/>'s limits
    /// (64 points, 16 polygons of ≥ 3 points), the padding as given (the caller applies <see cref="ClipMath.CutoutPadding"/>).
    /// </summary>
    public static CutUniforms Pack(IReadOnlyList<P2>? clip, IEnumerable<IReadOnlyList<P2>>? cutouts, double padding,
                                   CutPlaneData? plane)
    {
        var clipPts = ClipMath.ClipOutlinePoints(clip);
        if (clipPts.Count < 3) clipPts = new List<P2>();
        var points = new List<P2>();
        var offsets = new List<int>();
        var lengths = new List<int>();
        foreach (var poly in ClipMath.CutoutPolygons(cutouts))
        {
            offsets.Add(points.Count);
            lengths.Add(poly.Count);
            points.AddRange(poly);
        }
        return new CutUniforms(clipPts, points, offsets, lengths, lengths.Count > 0 && padding > 0 ? padding : 0, plane);
    }

    /// <summary>A GLSL float literal (always with a decimal point or an exponent), invariant culture.</summary>
    public static string Number(double v)
    {
        var s = v.ToString("R", CultureInfo.InvariantCulture);
        return s.Contains('.') || s.Contains('E') || s.Contains('e') ? s.Replace("E", "e") : s + ".0";
    }

    /// <summary>
    /// <paramref name="code"/> with the cut test appended: the defines and uniforms right after its
    /// <c>render_mode</c> line, a function <c>av_cut_discard(world)</c> after them, and ONE
    /// <c>if (av_cut_discard(…)) discard;</c> as the LAST statement of <c>fragment()</c> — after every texture fetch,
    /// so the derivatives stay in uniform control flow. Culling goes to <c>cull_disabled</c> (the browser's
    /// DoubleSide: the cut edges stay open). Throws when the code has no <c>render_mode</c> line or no
    /// <c>fragment()</c>.
    /// </summary>
    public static string Inject(string code, CutUniforms u)
    {
        int rm = code.IndexOf("render_mode ", StringComparison.Ordinal);
        if (rm < 0) throw new ArgumentException("shader without render_mode");
        int rmEnd = code.IndexOf(';', rm);
        var mode = code.Substring(rm, rmEnd - rm);
        var modeTwoSided = mode.Contains("cull_back") ? mode.Replace("cull_back", "cull_disabled")
                         : mode.Contains("cull_front") ? mode.Replace("cull_front", "cull_disabled")
                         : mode.Contains("cull_disabled") ? mode : mode + ", cull_disabled";
        var head = new StringBuilder();
        head.Append("\n// Anima native: the browser's room clip / area cutouts / depth cut (packages/scene-render clip.ts,\n");
        head.Append("// cutouts.ts, depthCut.ts), per fragment on its world position.\n");
        if (u.HasClip)
        {
            head.Append($"#define CLIP_N {u.Clip.Count}\n");
            head.Append("uniform vec2 clip_pts[CLIP_N];\n");
        }
        if (u.HasCutouts)
        {
            head.Append($"#define CUT_POLYS {u.CutLengths.Count}\n");
            head.Append($"#define CUT_MAX_LEN {u.CutMaxLen}\n");
            if (u.Padding > 0) head.Append($"#define CUT_PADDING_SQ {Number(u.Padding * u.Padding)}\n");
            head.Append($"uniform vec2 cut_pts[{u.CutPoints.Count}];\n");
            head.Append("uniform int cut_off[CUT_POLYS];\n");
            head.Append("uniform int cut_len[CUT_POLYS];\n");
            head.Append("uniform float cut_on = 0.0;\n");
        }
        if (u.HasPlane) head.Append("uniform vec4 cut_plane;\n");
        head.Append("bool av_cut_discard(vec3 w) {\n");
        head.Append("	vec2 p = vec2(w.x, w.z);\n");
        if (u.HasClip)
            head.Append(@"	bool clip_inside = false;
	vec2 clip_prev = clip_pts[CLIP_N - 1];
	for (int i = 0; i < CLIP_N; i++) {
		vec2 clip_cur = clip_pts[i];
		if (((clip_cur.y > p.y) != (clip_prev.y > p.y)) &&
				(p.x < (clip_prev.x - clip_cur.x) * (p.y - clip_cur.y) / (clip_prev.y - clip_cur.y) + clip_cur.x)) {
			clip_inside = !clip_inside;
		}
		clip_prev = clip_cur;
	}
	if (!clip_inside) return true;
");
        if (u.HasCutouts)
            head.Append(@"	if (cut_on > 0.5) {
		bool cut_hit = false;
		for (int q = 0; q < CUT_POLYS; q++) {
			int off = cut_off[q];
			int len = cut_len[q];
			if (len < 3) continue;
			bool inside = false;
			vec2 prev = cut_pts[off + len - 1];
			for (int i = 0; i < CUT_MAX_LEN; i++) {
				if (i >= len) break;
				vec2 cur = cut_pts[off + i];
				if (((cur.y > p.y) != (prev.y > p.y)) &&
						(p.x < (prev.x - cur.x) * (p.y - cur.y) / (prev.y - cur.y) + cur.x)) {
					inside = !inside;
				}
#ifdef CUT_PADDING_SQ
				vec2 edge = cur - prev;
				float t = clamp(dot(p - prev, edge) / max(dot(edge, edge), 1e-8), 0.0, 1.0);
				vec2 delta = p - (prev + t * edge);
				if (dot(delta, delta) <= CUT_PADDING_SQ) cut_hit = true;
#endif
				prev = cur;
			}
			if (inside || cut_hit) { cut_hit = true; break; }
		}
		if (cut_hit) return true;
	}
");
        if (u.HasPlane) head.Append("	if (dot(cut_plane.xyz, w) + cut_plane.w < 0.0) return true;\n");
        head.Append("	return false;\n}\n");

        var withHead = code[..rm] + modeTwoSided + ";\n" + head + code[(rmEnd + 1)..];
        int frag = withHead.IndexOf("void fragment()", StringComparison.Ordinal);
        if (frag < 0) throw new ArgumentException("shader without fragment()");
        int open = withHead.IndexOf('{', frag);
        int depth = 0, close = -1;
        for (int i = open; i < withHead.Length; i++)
        {
            if (withHead[i] == '{') depth++;
            else if (withHead[i] == '}' && --depth == 0) { close = i; break; }
        }
        if (close < 0) throw new ArgumentException("fragment() is not closed");
        return withHead[..close]
               + "	// Last statement: the cut (after every texture fetch, see CutShader.Inject).\n"
               + "	if (av_cut_discard((INV_VIEW_MATRIX * vec4(VERTEX, 1.0)).xyz)) discard;\n"
               + withHead[close..];
    }

    /// <summary>
    /// The CPU twin of the injected <c>av_cut_discard</c>, line for line (single precision aside): does a fragment at
    /// world <paramref name="w"/> go, with the cutouts switched <paramref name="cutOn"/>?
    /// </summary>
    public static bool Discards(CutUniforms u, Vec3 w, bool cutOn)
    {
        var p = new P2(w.X, w.Z);
        if (u.HasClip)
        {
            bool clipInside = false;
            var clipPrev = u.Clip[^1];
            for (int i = 0; i < u.Clip.Count; i++)
            {
                var cur = u.Clip[i];
                if ((cur.Z > p.Z) != (clipPrev.Z > p.Z)
                    && p.X < (clipPrev.X - cur.X) * (p.Z - cur.Z) / (clipPrev.Z - cur.Z) + cur.X) clipInside = !clipInside;
                clipPrev = cur;
            }
            if (!clipInside) return true;
        }
        if (u.HasCutouts && cutOn)
        {
            bool cutHit = false;
            double padSq = u.Padding * u.Padding;
            for (int q = 0; q < u.CutLengths.Count; q++)
            {
                int off = u.CutOffsets[q], len = u.CutLengths[q];
                if (len < 3) continue;
                bool inside = false;
                var prev = u.CutPoints[off + len - 1];
                for (int i = 0; i < len; i++)
                {
                    var cur = u.CutPoints[off + i];
                    if ((cur.Z > p.Z) != (prev.Z > p.Z)
                        && p.X < (prev.X - cur.X) * (p.Z - cur.Z) / (prev.Z - cur.Z) + cur.X) inside = !inside;
                    if (u.Padding > 0)
                    {
                        double ex = cur.X - prev.X, ez = cur.Z - prev.Z;
                        double t = Math.Clamp(((p.X - prev.X) * ex + (p.Z - prev.Z) * ez) / Math.Max(ex * ex + ez * ez, 1e-8), 0, 1);
                        double dx = p.X - (prev.X + t * ex), dz = p.Z - (prev.Z + t * ez);
                        if (dx * dx + dz * dz <= padSq) cutHit = true;
                    }
                    prev = cur;
                }
                if (inside || cutHit) { cutHit = true; break; }
            }
            if (cutHit) return true;
        }
        if (u.Plane is { } pl && pl.Normal.X * w.X + pl.Normal.Y * w.Y + pl.Normal.Z * w.Z + pl.Constant < 0) return true;
        return false;
    }
}
