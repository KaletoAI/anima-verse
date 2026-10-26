using System;
using AnimaNative.Scene;

namespace AnimaNative.Sky;

/// <summary>
/// The distance fog of <see cref="FogPost"/> as ONE compute pass on the finished colour buffer (Task 26b; the default since
/// Task 26c, <c>--fog=pass</c> / bench variant <c>fog-pass</c> = the screen pass) — the same numbers, a cheaper road.
///
/// <b>What the screen pass costs besides itself.</b> A spatial shader that reads <c>hint_screen_texture</c> and
/// <c>hint_depth_texture</c> makes Godot 4.7.2 (renderer_scene_render_rd.cpp <c>_render_buffers_copy_screen_texture</c> /
/// <c>_render_buffers_copy_depth_texture</c>, called from render_forward_clustered.cpp before the transparent pass) copy
/// the whole RGBA16F colour buffer into the blur texture, build that texture's FULL mip chain (12 levels at 3816 px, one
/// dispatch each) and copy the depth buffer into an R32F texture — every frame, whether the pass needs mips or not. With
/// MSAA the colour and the depth are resolved for it as well, before the transparent pass.
///
/// <b>The compute pass.</b> A <c>CompositorEffect</c> at <c>POST_TRANSPARENT</c> (the colour is resolved there anyway)
/// reads the depth texture and the colour image in place and writes three's display-space mix for every pixel in the
/// fog band: <c>linear(mix(srgb(c), fog_srgb, f))</c> with <c>f = smoothstep(220, 520, z)</c> and the view depth
/// <c>z = n·f/(d·(f − n) + n)</c> rebuilt from the reverse-Z depth (<see cref="FogPost.ViewDepth"/>). For an opaque pixel
/// that is exactly what the screen pass's blend lands on (<see cref="Shown"/> = <see cref="FogPost.Shown"/>, unit-tested).
/// A transparent surface over the fog band is mixed with the opaque depth behind it (the screen pass instead attenuated
/// it by 1 − f) — neither is the browser's per-material fog for transparents; the difference is limited to transparent
/// pixels beyond 220 m.
/// </summary>
public static class FogCompute
{
    /// <summary>Work group edge (8 × 8 invocations).</summary>
    public const int Group = 8;

    /// <summary>The push constant block in bytes: size.xy, near, far, fog_srgb.rgba (std430, 2 × 16 bytes).</summary>
    public const int PushBytes = 32;

    /// <summary>The GLSL 450 compute source (Godot's <c>RDShaderSource.SourceCompute</c>: no <c>#[compute]</c> header).</summary>
    public static string ShaderCode { get; } = $@"#version 450
// Anima native: the browser's distance fog (three's linear fog over the VIEW depth, mixed in display space) as one
// compute pass on the finished 3D colour buffer, post-transparent (Sky/FogCompute.cs; the screen-pass twin is FogPost.cs).
layout(local_size_x = {Group}, local_size_y = {Group}, local_size_z = 1) in;
layout(rgba16f, set = 0, binding = 0) uniform restrict image2D color_image;
layout(set = 0, binding = 1) uniform sampler2D depth_tex;
layout(push_constant, std430) uniform Params {{
	vec2 size;
	float near_m;
	float far_m;
	vec4 fog_srgb;
}} params;

vec3 av_to_srgb(vec3 c) {{
	return mix(1.055 * pow(max(c, vec3(0.0)), vec3(1.0 / 2.4)) - 0.055, 12.92 * c, lessThan(c, vec3(0.0031308)));
}}
vec3 av_to_linear(vec3 c) {{
	return mix(pow(max((c + 0.055) * (1.0 / 1.055), vec3(0.0)), vec3(2.4)), c * (1.0 / 12.92), lessThan(c, vec3(0.04045)));
}}
void main() {{
	ivec2 px = ivec2(gl_GlobalInvocationID.xy);
	if (px.x >= int(params.size.x) || px.y >= int(params.size.y)) return;
	float d = texelFetch(depth_tex, px, 0).r;
	// Reverse Z clears to 0: nothing was drawn here, the background is the sky already.
	if (d <= 0.0) return;
	float z = params.near_m * params.far_m / (d * (params.far_m - params.near_m) + params.near_m);
	float f = smoothstep({CutShader.Number(Fog.NearM)}, {CutShader.Number(Fog.FarM)}, z);
	if (f <= 0.0) return;
	vec4 c = imageLoad(color_image, px);
	imageStore(color_image, px, vec4(av_to_linear(mix(av_to_srgb(c.rgb), params.fog_srgb.rgb, f)), c.a));
}}
";

    /// <summary>Work groups for a buffer of <paramref name="width"/> × <paramref name="height"/> pixels.</summary>
    public static (int X, int Y) Groups(int width, int height)
        => (Math.Max(0, (width + Group - 1) / Group), Math.Max(0, (height + Group - 1) / Group));

    /// <summary>The push constant bytes (little-endian floats, the block's std430 layout).</summary>
    public static byte[] Push(int width, int height, double near, double far, (double R, double G, double B) fogSrgb)
    {
        var f = new float[] { width, height, (float)near, (float)far, (float)fogSrgb.R, (float)fogSrgb.G, (float)fogSrgb.B, 0f };
        var bytes = new byte[PushBytes];
        Buffer.BlockCopy(f, 0, bytes, 0, PushBytes);
        return bytes;
    }

    private static double ToSrgb(double c) => c < 0.0031308 ? 12.92 * c : 1.055 * Math.Pow(Math.Max(c, 0), 1 / 2.4) - 0.055;
    private static double ToLinear(double c) => c < 0.04045 ? c / 12.92 : Math.Pow(Math.Max((c + 0.055) / 1.055, 0), 2.4);

    /// <summary>
    /// The CPU twin of the kernel, line for line: what the display shows for a pixel of linear colour
    /// <paramref name="color"/> at depth-buffer value <paramref name="depth"/>, in display sRGB 0..1.
    /// </summary>
    public static (double R, double G, double B) Shown((double R, double G, double B) color, double depth,
                                                       (double R, double G, double B) fogSrgb,
                                                       double near = FogPost.CameraNear, double far = FogPost.CameraFar)
    {
        if (depth <= 0) return (ToSrgb(color.R), ToSrgb(color.G), ToSrgb(color.B));
        double z = near * far / (depth * (far - near) + near);
        double f = FogPost.Smoothstep(Fog.NearM, Fog.FarM, z);
        if (f <= 0) return (ToSrgb(color.R), ToSrgb(color.G), ToSrgb(color.B));
        double Mix(double c, double fs) => ToSrgb(ToLinear(ToSrgb(c) + (fs - ToSrgb(c)) * f));
        return (Mix(color.R, fogSrgb.R), Mix(color.G, fogSrgb.G), Mix(color.B, fogSrgb.B));
    }
}
