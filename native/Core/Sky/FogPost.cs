using System;
using AnimaNative.Scene;

namespace AnimaNative.Sky;

/// <summary>
/// The browser's distance fog as ONE screen pass over the finished 3D picture.
///
/// <b>What the browser does.</b> three r185's linear fog (<c>fog_fragment</c>, every material of the scene has
/// <c>fog: true</c>) takes <c>vFogDepth = −mvPosition.z</c> — the VIEW-SPACE depth, not the distance — and mixes
/// <c>gl_FragColor.rgb = mix(gl_FragColor.rgb, fogColor, smoothstep(220, 520, vFogDepth))</c> AFTER
/// <c>colorspace_fragment</c>: the canvas is the render target, so the colour is already sRGB-encoded and
/// <c>fogColor</c> is uploaded in the output colour space (<c>getUnlitUniformColorSpace</c>). The fog is therefore a
/// mix in DISPLAY space with the sky's sRGB value (engine.ts <c>setGameHour</c> writes the sky into the fog colour).
///
/// <b>Why a screen pass.</b> Godot 4.7.2's own fog (Environment depth fog, and a shader's <c>FOG</c> output alike)
/// mixes in LINEAR space before the output encode (scene_forward_clustered.glsl:
/// <c>frag_color.rgb = frag_color.rgb · fog.a + fog.rgb</c>), and the Environment fog measures <c>length(vertex)</c>, the
/// radial distance. Neither can be bent into three's display-space mix from inside a lit material, because the lit
/// colour is not known there. This pass knows it: after the transparent pass it reads the opaque colour (the screen
/// texture, linear HDR) and the opaque depth, rebuilds the view depth from the depth buffer (exact: view z is affine
/// over a triangle, so it equals three's interpolated <c>vFogDepth</c>), and writes three's result. It is one material
/// for every material class (ground, water, scatter, recipe pieces, cut clones, imported GLB materials, the backdrop,
/// pins) — none of them fogs itself.
///
/// <b>Blending.</b> The pass draws with <c>blend_mix</c> at α = f and colour X = (R − S·(1 − f)) / f, where S is the
/// screen texture and R = toLinear(mix(toSrgb(S), fogSrgb, f)). On an opaque pixel the blend gives X·f + S·(1 − f) = R,
/// whose output encode is three's display value. A transparent surface drawn earlier in the frame (dst = S + T) keeps
/// its share attenuated by (1 − f) of the opaque depth behind it. Background pixels (depth 0 under reverse Z) are left
/// alone — the background IS the sky colour, as in the browser (the scene background is never fogged there).
/// </summary>
public static class FogPost
{
    /// <summary>Material priority of the pass: Godot sorts transparent surfaces by priority FIRST, so the maximum
    /// (127, <c>Material.RENDER_PRIORITY_MAX</c>) draws it after every other transparent surface.</summary>
    public const int RenderPriority = 127;

    /// <summary>The camera of the overview (OverviewCamera.cs; engine.ts <c>PerspectiveCamera(45, …, 0.2, 800)</c>).</summary>
    public const double CameraNear = 0.2, CameraFar = 800;

    /// <summary>The spatial shader of the pass. The fog band is printed from <see cref="Fog.NearM"/> / <see cref="Fog.FarM"/>.</summary>
    public static string ShaderCode { get; } = BuildCode();

    private static string BuildCode() => $@"shader_type spatial;
// Anima native: the browser's distance fog (three's linear fog over the VIEW depth, mixed in display space after the
// sRGB encode; client3d/src/scene/engine.ts + fogConstants.ts) as one pass over the finished picture (Sky/FogPost.cs).
render_mode unshaded, blend_mix, depth_draw_never, depth_test_disabled, cull_disabled, shadows_disabled, fog_disabled;
uniform sampler2D screen_tex : hint_screen_texture, filter_nearest, repeat_disable;
uniform sampler2D depth_tex : hint_depth_texture, filter_nearest, repeat_disable;
// The sky in the OUTPUT colour space (three's fogColor, getRGB(target, SRGBColorSpace)).
uniform vec3 fog_srgb = vec3(0.623529, 0.780392, 0.909804);

// Godot's own output transfer pair (color.h / tonemap.glsl): toLinear(toSrgb(c)) = c, so what this pass writes is shown
// exactly as the display-space value it computed.
vec3 av_to_srgb(vec3 c) {{
	return mix(1.055 * pow(max(c, vec3(0.0)), vec3(1.0 / 2.4)) - 0.055, 12.92 * c, lessThan(c, vec3(0.0031308)));
}}
vec3 av_to_linear(vec3 c) {{
	return mix(pow(max((c + 0.055) * (1.0 / 1.055), vec3(0.0)), vec3(2.4)), c * (1.0 / 12.92), lessThan(c, vec3(0.04045)));
}}
void vertex() {{
	// A full-screen quad (QuadMesh 2 x 2): straight into clip space, on the near plane (reverse Z).
	POSITION = vec4(VERTEX.xy, 1.0, 1.0);
}}
void fragment() {{
	float d = texture(depth_tex, SCREEN_UV).r;
	// Reverse Z clears to 0: nothing was drawn here, the background is the sky already.
	if (d <= 0.0) discard;
	vec4 v = INV_PROJECTION_MATRIX * vec4(SCREEN_UV * 2.0 - 1.0, d, 1.0);
	// three: smoothstep(fogNear, fogFar, vFogDepth) with vFogDepth = -mvPosition.z.
	float f = smoothstep({CutShader.Number(Fog.NearM)}, {CutShader.Number(Fog.FarM)}, -v.z / v.w);
	if (f <= 0.0) discard;
	vec3 s = texture(screen_tex, SCREEN_UV).rgb;
	vec3 r = av_to_linear(mix(av_to_srgb(s), fog_srgb, f));
	// blend_mix: X * f + dst * (1 - f) = r on an opaque pixel (dst = s).
	ALBEDO = (r - s * (1.0 - f)) / f;
	ALPHA = f;
}}
";

    /// <summary>
    /// Godot's depth-buffer value at view depth <paramref name="z"/> (metres in front of the camera): the perspective
    /// projection remapped to [0, 1] and reversed (Godot 4.3+), <c>d = n·(f − z) / ((f − n)·z)</c> — 1 at the near plane,
    /// 0 at the far plane.
    /// </summary>
    public static double DepthAt(double z, double near = CameraNear, double far = CameraFar)
        => near * (far - z) / ((far - near) * z);

    /// <summary>The CPU twin of <c>-v.z / v.w</c> in the shader: the view depth of a depth-buffer value (the inverse of
    /// <see cref="DepthAt"/>), <c>z = n·f / (d·(f − n) + n)</c>.</summary>
    public static double ViewDepth(double d, double near = CameraNear, double far = CameraFar)
        => near * far / (d * (far - near) + near);

    /// <summary>GLSL <c>smoothstep(e0, e1, x)</c> (the GLSL 4.50 definition: t = clamp((x − e0)/(e1 − e0), 0, 1), t²(3 − 2t)).</summary>
    public static double Smoothstep(double e0, double e1, double x)
    {
        double t = Math.Clamp((x - e0) / (e1 - e0), 0, 1);
        return t * t * (3 - 2 * t);
    }

    /// <summary>The sky as the pass's <c>fog_srgb</c>: three's fog colour in the output space,
    /// <c>getRGB(target, SRGBColorSpace)</c> = three's <c>LinearToSRGB</c> per channel, unquantised.</summary>
    public static (double R, double G, double B) FogSrgb(LinearRgb sky)
        => (LinearRgb.LinearToSrgb(sky.R), LinearRgb.LinearToSrgb(sky.G), LinearRgb.LinearToSrgb(sky.B));

    private static double ToSrgb(double c) => c < 0.0031308 ? 12.92 * c : 1.055 * Math.Pow(Math.Max(c, 0), 1 / 2.4) - 0.055;
    private static double ToLinear(double c) => c < 0.04045 ? c / 12.92 : Math.Pow(Math.Max((c + 0.055) / 1.055, 0), 2.4);

    /// <summary>
    /// The CPU twin of the fragment, line for line: for a screen colour <paramref name="screen"/> (linear) and a
    /// depth-buffer value <paramref name="depth"/>, the colour X and alpha f the pass blends with — null where it
    /// discards (background, or in front of the fog band).
    /// </summary>
    public static (double R, double G, double B, double Alpha)? Fragment((double R, double G, double B) screen, double depth,
                                                                         (double R, double G, double B) fogSrgb)
    {
        if (depth <= 0) return null;
        double f = Smoothstep(Fog.NearM, Fog.FarM, ViewDepth(depth));
        if (f <= 0) return null;
        double X(double s, double fs)
        {
            double r = ToLinear(ToSrgb(s) + (fs - ToSrgb(s)) * f);
            return (r - s * (1 - f)) / f;
        }
        return (X(screen.R, fogSrgb.R), X(screen.G, fogSrgb.G), X(screen.B, fogSrgb.B), f);
    }

    /// <summary>
    /// What the display shows for an OPAQUE pixel of linear colour <paramref name="screen"/> at depth-buffer value
    /// <paramref name="depth"/> after the pass (blend_mix onto dst = screen, then Godot's output encode), in display
    /// sRGB 0..1 — three's <c>mix(sRGB(colour), fogSrgb, f)</c>.
    /// </summary>
    public static (double R, double G, double B) Shown((double R, double G, double B) screen, double depth,
                                                       (double R, double G, double B) fogSrgb)
    {
        if (Fragment(screen, depth, fogSrgb) is not { } x) return (ToSrgb(screen.R), ToSrgb(screen.G), ToSrgb(screen.B));
        double f = x.Alpha;
        return (ToSrgb(x.R * f + screen.R * (1 - f)), ToSrgb(x.G * f + screen.G * (1 - f)), ToSrgb(x.B * f + screen.B * (1 - f)));
    }
}
