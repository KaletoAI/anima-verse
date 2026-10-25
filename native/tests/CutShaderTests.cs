using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.World;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// Task 17: the per-fragment cuts (<see cref="CutShader"/>), the StandardMaterial3D generator port
/// (<see cref="StandardShaderCode"/>), the runtime tier decision and the sweep's change test. Expectations are derived by
/// hand in the comments from packages/scene-render clip.ts / cutouts.ts / depthCut.ts, Godot 4.7.2 material.cpp and
/// main.ts tickModelTiers; the cut semantics are pinned to the vector-checked <see cref="ClipMath"/>.
/// </summary>
public class CutShaderTests
{
    private static P2 P(double x, double z) => new(x, z);

    [Fact]
    public void GeneratorEmitsTheEnginesDefaultMaterial()
    {
        // material.cpp for a default StandardMaterial3D: blend_mix, depth_draw_opaque, cull_back, diffuse_burley,
        // specular_schlick_ggx; roughness channel R (hint_roughness_r); filter linear-mipmap + repeat.
        var code = StandardShaderCode.Generate(new StandardShaderSpec())!;
        Assert.Contains("render_mode blend_mix, depth_draw_opaque, cull_back, diffuse_burley, specular_schlick_ggx;\n", code);
        Assert.Contains("uniform sampler2D texture_albedo : source_color, filter_linear_mipmap, repeat_enable;", code);
        Assert.Contains("uniform sampler2D texture_roughness : hint_roughness_r, filter_linear_mipmap, repeat_enable;", code);
        Assert.Contains("	UV = UV * uv1_scale.xy + uv1_offset.xy;", code);
        Assert.Contains("	ALBEDO = albedo.rgb * albedo_tex.rgb;", code);
        Assert.Contains("	vec4 roughness_texture_channel = vec4(1.0, 0.0, 0.0, 0.0);", code);
        Assert.DoesNotContain("ALPHA", code);   // opaque: no alpha line
        Assert.DoesNotContain("COLOR", code);   // no vertex colour
    }

    [Fact]
    public void GeneratorFollowsTheGltfFeatures()
    {
        // A glTF material with COLOR_0, an ORM texture (roughness G), a normal map, an emissive texture (operator
        // multiply), occlusion and alphaMode MASK, double-sided, KHR_materials_unlit off.
        var s = new StandardShaderSpec
        {
            AlbedoFromVertexColor = true, RoughnessChannel = StandardShaderSpec.Channel.Green, NormalMap = true,
            Emission = true, EmissionAdd = false, AmbientOcclusion = true,
            Transparency = StandardShaderSpec.TransparencyMode.AlphaScissor, Cull = StandardShaderSpec.CullKind.Disabled,
        };
        var code = StandardShaderCode.Generate(s)!;
        Assert.Contains(", cull_disabled,", code);
        Assert.Contains("	albedo_tex *= COLOR;", code);
        Assert.Contains("hint_roughness_g", code);
        Assert.Contains("	NORMAL_MAP_DEPTH = normal_scale;", code);
        Assert.Contains("	EMISSION = (emission.rgb * emission_tex) * emission_energy;", code);
        Assert.Contains("	ALPHA *= albedo.a * albedo_tex.a;", code);
        Assert.Contains("	ALPHA_SCISSOR_THRESHOLD = alpha_scissor_threshold;", code);
        Assert.Contains("	AO_LIGHT_AFFECT = ao_light_affect;", code);
        // Every declared uniform is in the list the Godot side feeds (14 base + scissor 1 + emission 3 + normal 2 + AO 3).
        var declared = Regex.Matches(code, @"^uniform \w+ (\w+)", RegexOptions.Multiline).Select(m => m.Groups[1].Value).ToList();
        Assert.Equal(StandardShaderCode.Uniforms(s), declared);
        Assert.Equal(23, declared.Count);
        Assert.Equal(14, StandardShaderCode.Uniforms(new StandardShaderSpec()).Count);
    }

    [Fact]
    public void AnUnsupportedFeatureIsNotConverted()
        => Assert.Null(StandardShaderCode.Generate(new StandardShaderSpec { Unsupported = new[] { "clearcoat" } }));

    [Fact]
    public void InjectAppendsTheTestAsTheLastFragmentStatementAndGoesTwoSided()
    {
        var u = CutShader.Pack(new[] { P(0, 0), P(1, 0), P(0, 1) }, null, 0, new CutPlaneData(new Vec3(1, 0, 0), 0));
        var code = CutShader.Inject(StandardShaderCode.Generate(new StandardShaderSpec())!, u);
        Assert.Contains("render_mode blend_mix, depth_draw_opaque, cull_disabled,", code);
        Assert.DoesNotContain("cull_back", code);
        Assert.Contains("#define CLIP_N 3\nuniform vec2 clip_pts[CLIP_N];", code);
        Assert.Contains("uniform vec4 cut_plane;", code);
        Assert.DoesNotContain("cut_on", code);   // no cutouts → no switch
        int discard = code.IndexOf("if (av_cut_discard((INV_VIEW_MATRIX * vec4(VERTEX, 1.0)).xyz)) discard;", StringComparison.Ordinal);
        int lastFetch = code.LastIndexOf("ROUGHNESS = roughness_tex * roughness;", StringComparison.Ordinal);
        Assert.True(discard > lastFetch && lastFetch > 0);
        Assert.Equal("}\n", code[(code.IndexOf('\n', discard) + 1)..]);   // nothing but the closing brace after it
        Assert.Throws<ArgumentException>(() => CutShader.Inject("shader_type spatial;\nrender_mode cull_back;\nvoid vertex() {}", u));
    }

    [Fact]
    public void PaddingIsACompileTimeConstantWithADecimalPoint()
    {
        var sq = new[] { new[] { P(-1, -1), P(1, -1), P(1, 1), P(-1, 1) } };
        var code = CutShader.Inject(StandardShaderCode.Generate(new StandardShaderSpec())!, CutShader.Pack(null, sq, 0.25, null));
        Assert.Contains("#define CUT_POLYS 1\n#define CUT_MAX_LEN 4\n#define CUT_PADDING_SQ 0.0625\n", code);
        Assert.Contains("uniform vec2 cut_pts[4];", code);
        Assert.Contains("uniform float cut_on = 0.0;", code);   // starts OFF like uCutOn
        Assert.Equal("1.0", CutShader.Number(1));
        Assert.Equal("1e-07", CutShader.Number(1e-7));
        Assert.DoesNotContain("CUT_PADDING_SQ", CutShader.Inject(StandardShaderCode.Generate(new StandardShaderSpec())!,
                                                                 CutShader.Pack(null, sq, 0, null)).Split("#ifdef")[0]);
    }

    [Fact]
    public void PackAppliesTheComposerLimits()
    {
        // ≤ 64 clip points; a clip under 3 points clips nothing; ≤ 16 cutout polygons, each ≥ 3 points; flat offsets.
        var ring = Enumerable.Range(0, 70).Select(i => P(Math.Cos(i * 0.09), Math.Sin(i * 0.09))).ToList();
        Assert.Equal(64, CutShader.Pack(ring, null, 0, null).Clip.Count);
        Assert.False(CutShader.Pack(new[] { P(0, 0), P(1, 1) }, null, 0, null).HasClip);
        var tri = new[] { P(0, 0), P(1, 0), P(0, 1) };
        var polys = Enumerable.Repeat((IReadOnlyList<P2>)tri, 18).Prepend(new[] { P(5, 5), P(6, 6) }).ToList();
        var u = CutShader.Pack(null, polys, 0.1, null);
        Assert.Equal(16, u.CutLengths.Count);
        Assert.Equal(Enumerable.Range(0, 16).Select(i => i * 3), u.CutOffsets);
        Assert.Equal(48, u.CutPoints.Count);
        Assert.Equal(0.1, u.Padding);
        Assert.Equal(0, CutShader.Pack(tri, null, 0.1, null).Padding);   // padding only travels with cutouts
        Assert.Equal("clip:0|cutout:16:3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3:0.1|plane:0", u.ShapeKey);
    }

    [Fact]
    public void TheCpuTwinAgreesWithClipMathOnAGrid()
    {
        // A concave L as the room clip, a square and a triangle as cutouts with 0.3 m padding: every point of a 0.25 m
        // grid over [−6, 6]² gets the same verdict from the shader twin and from the vector-checked ClipMath.
        var ell = new[] { P(-4, -4), P(4, -4), P(4, 0), P(0, 0), P(0, 4), P(-4, 4) };
        var cuts = new List<IReadOnlyList<P2>> { new[] { P(1, 1), P(3, 1), P(3, 3), P(1, 3) }, new[] { P(-5, -5), P(-3, -5), P(-4, -3) } };
        var clipOnly = CutShader.Pack(ell, null, 0, null);
        var cutOnly = CutShader.Pack(null, cuts, 0.3, null);
        int n = 0;
        for (double x = -6; x <= 6; x += 0.25)
        for (double z = -6; z <= 6; z += 0.25)
        {
            var w = new Vec3(x, 1, z);
            Assert.Equal(!ClipMath.ClipKeepsPoint(P(x, z), ell), CutShader.Discards(clipOnly, w, true));
            Assert.Equal(ClipMath.CutoutDiscardsPoint(P(x, z), cuts, 0.3), CutShader.Discards(cutOnly, w, true));
            Assert.False(CutShader.Discards(cutOnly, w, false));
            n++;
        }
        Assert.Equal(49 * 49, n);
        // Hand points: (−2, 2) is in the L's upper arm (kept), (2, 2) in its notch (clipped); (3.2, 2) is 0.2 m from the
        // square's east edge (cut by the padding), (3.4, 2) is 0.4 m away (kept).
        Assert.False(CutShader.Discards(clipOnly, new Vec3(-2, 0, 2), true));
        Assert.True(CutShader.Discards(clipOnly, new Vec3(2, 0, 2), true));
        Assert.True(CutShader.Discards(cutOnly, new Vec3(3.2, 0, 2), true));
        Assert.False(CutShader.Discards(cutOnly, new Vec3(3.4, 0, 2), true));
    }

    [Fact]
    public void ThePlaneKeepsItsNonNegativeSide()
    {
        // three's convention (depthCut.ts): KEPT where n·p + c ≥ 0. n (0, 0, −1), c 99.5: z 99.5 is on the plane (kept),
        // z 99.6 is behind it (discarded).
        var u = CutShader.Pack(null, null, 0, new CutPlaneData(new Vec3(0, 0, -1), 99.5));
        Assert.False(CutShader.Discards(u, new Vec3(0, 0, 99.5), false));
        Assert.True(CutShader.Discards(u, new Vec3(0, 0, 99.6), false));
        Assert.False(CutShader.Discards(u, new Vec3(0, 50, 99), false));
    }

    [Fact]
    public void TierSwapFollowsTheHysteresisOverACameraSequence()
    {
        // Distances minus the half diagonal 70 → 44 → 50 → 61 m: 70 > 60 → low; 44 < 45 → full; 50 is inside the band →
        // stays full; 61 > 60 → low — the same from either start tier.
        const double w = 12, half = 12 * 0.7071067811865476;
        foreach (var start in new[] { "low", "full" })
        {
            var cur = start;
            var seen = new List<string>();
            foreach (var d in new[] { 70.0, 44.0, 50.0, 61.0 })
            {
                cur = LocationView.BuildingTier(Ring.Near, d + half, w, cur);
                seen.Add(cur);
            }
            Assert.Equal(new[] { "low", "full", "full", "low" }, seen);
        }
        // The band edges: exactly 45 stays low, exactly 60 stays full; the far ring is always low.
        Assert.Equal("low", LocationView.BuildingTier(Ring.Near, 45 + half, w, "low"));
        Assert.Equal("full", LocationView.BuildingTier(Ring.Near, 60 + half, w, "full"));
        Assert.Equal("low", LocationView.BuildingTier(Ring.Far, 1, w, "full"));
        // Interior: a closed area-detail scene low, opened full, far low.
        Assert.Equal("low", LocationView.InteriorTier(Ring.Near, true, false));
        Assert.Equal("full", LocationView.InteriorTier(Ring.Near, true, true));
        Assert.Equal("low", LocationView.InteriorTier(Ring.Far, false, true));
    }

    [Fact]
    public void ASceneIsRemountedOnlyWhenItsSignatureMoved()
    {
        // (old?.signature ?? null) !== (fresh?.signature ?? null)
        Assert.False(LocationView.SceneChanged("a", "a"));
        Assert.True(LocationView.SceneChanged("a", "b"));
        Assert.True(LocationView.SceneChanged("a", null));
        Assert.True(LocationView.SceneChanged(null, "a"));
        Assert.False(LocationView.SceneChanged(null, null));
    }
}
