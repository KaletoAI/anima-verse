using System;

namespace AnimaNative.Scene;

/// <summary>
/// Task 53 / E7-T8: shared corridor patch, chained after existing cut/sway shaders. Fragment VERTEX is view-space
/// after instance transforms and wind; INV_VIEW_MATRIX recovers its world position without a second vertex path.
/// Globals move once per frame; occ_gate belongs to owned hull clones. Shader code never depends on a node or frame.
/// </summary>
public static class OcclusionShader
{
    public const string Marker = "// Task 53: occlusion-corridor";
    public static string Inject(string code)
    {
        if (code.Contains(Marker, StringComparison.Ordinal)) return code;
        int rm = code.IndexOf("render_mode ", StringComparison.Ordinal);
        if (rm < 0) throw new ArgumentException("corridor shader without render_mode");
        int end = code.IndexOf(';', rm)+1;
        code = code[..end] + @"
// Task 53: occlusion-corridor
global uniform vec3 av_occ_a;
global uniform vec3 av_occ_b;
global uniform float av_occ_radius;
global uniform float av_occ_strength;
uniform float occ_gate = 1.0;
" + code[end..];
        int frag = code.IndexOf("void fragment()", StringComparison.Ordinal);
        if (frag < 0) throw new ArgumentException("corridor shader without fragment()");
        int open = code.IndexOf('{', frag), depth = 0, close = -1;
        for (int i = open; i < code.Length; i++)
        {
            if (code[i] == '{') depth++;
            else if (code[i] == '}' && --depth == 0) { close = i; break; }
        }
        if (close < 0) throw new ArgumentException("corridor fragment() is not closed");
        // After texture fetches so derivatives remain in uniform control flow, like CutShader.Inject.
        return code[..close] + @"
    if (av_occ_strength > 0.0) {
        vec3 av_occ_world = (INV_VIEW_MATRIX * vec4(VERTEX, 1.0)).xyz;
        vec3 av_occ_ab = av_occ_b - av_occ_a;
        float av_occ_t = clamp(dot(av_occ_world - av_occ_a, av_occ_ab) / max(dot(av_occ_ab, av_occ_ab), 1e-6), 0.0, 1.0);
        float av_occ_dist = distance(av_occ_world, av_occ_a + av_occ_ab * av_occ_t);
        float av_occ_hide = av_occ_strength * occ_gate * (1.0 - smoothstep(av_occ_radius * 0.5, av_occ_radius, av_occ_dist));
        vec2 av_occ_pix = mod(floor(FRAGCOORD.xy), 4.0);
        float av_occ_x0 = mod(av_occ_pix.x, 2.0);
        float av_occ_x1 = mod(floor(av_occ_pix.x / 2.0), 2.0);
        float av_occ_y0 = mod(av_occ_pix.y, 2.0);
        float av_occ_y1 = mod(floor(av_occ_pix.y / 2.0), 2.0);
        float av_occ_threshold = (abs(av_occ_y0 - av_occ_x0) * 8.0 + av_occ_y0 * 4.0
            + abs(av_occ_y1 - av_occ_x1) * 2.0 + av_occ_y1) / 16.0;
        if (av_occ_hide > av_occ_threshold) discard;
    }
" + code[close..];
    }
}
