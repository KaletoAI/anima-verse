using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// The material clones one placement's cuts live on (the browser's <c>__clipClone</c> / <c>__cutoutClone</c> /
/// depth-cut clones). They belong to the PLACEMENT, never to the model cache: the template's own materials stay
/// untouched, every cut mesh wears a per-instance surface override. Dropping the placement drops them (Godot
/// resources are reference-counted — no explicit dispose, and nothing shared is ever freed).
/// </summary>
public sealed class CutHandle
{
    public sealed record Entry(MeshInstance3D Mesh, int Surface, ShaderMaterial Material, CutUniforms Uniforms);

    public List<Entry> Entries { get; } = new();
    /// <summary>Surfaces left uncut: their material uses a feature the shader port lacks (<see cref="CutMaterials.SpecOf"/>).</summary>
    public int Fallbacks { get; internal set; }
    public bool HasCutouts => Entries.Any(e => e.Uniforms.HasCutouts);
    public bool HasPlane => Entries.Any(e => e.Uniforms.HasPlane);
    /// <summary>The cutout switch (<c>uCutOn</c>): starts OFF, like the browser's — a tile is built in the far view.</summary>
    public bool CutoutsOn { get; private set; }

    /// <summary><c>setEnabled(on)</c>: holes on (interior view) or off (far view) — a uniform, never a recompile.</summary>
    public void SetCutoutsEnabled(bool on)
    {
        if (CutoutsOn == on) return;
        CutoutsOn = on;
        foreach (var e in Entries)
            if (e.Uniforms.HasCutouts) e.Material.SetShaderParameter("cut_on", on ? 1f : 0f);
    }

    /// <summary>The depth cut's world plane moved with its frame (a re-datum): write it again.</summary>
    public void SetPlane(CutPlaneData plane)
    {
        for (int i = 0; i < Entries.Count; i++)
        {
            var e = Entries[i];
            if (!e.Uniforms.HasPlane) continue;
            e.Material.SetShaderParameter("cut_plane", CutMaterials.PlaneVector(plane));
            Entries[i] = e with { Uniforms = e.Uniforms with { Plane = plane } };
        }
    }
}

/// <summary>
/// The native twin of packages/scene-render <c>applyClipOutline</c> (clip.ts), <c>applyCutouts</c> (cutouts.ts) and
/// <c>applyDepthCut</c> (depthCut.ts): every mesh of a placed model wears, per surface, a ShaderMaterial whose code is
/// the source material's own shader (Godot 4.7.2's StandardMaterial3D generator, ported in
/// <see cref="StandardShaderCode"/>; a ShaderMaterial source keeps its code) with ONE per-fragment test appended
/// (<see cref="CutShader.Inject"/>): outside the room clip, inside a switched-on cutout (plus the GLB's padding),
/// behind the depth-cut plane → discarded. Double-sided like the browser (the cut edges stay open). The shader of a
/// (code, shape) pair is compiled once and shared (<see cref="ShaderSafety"/> checks it); the points are uniforms.
/// </summary>
public static class CutMaterials
{
    private static readonly Dictionary<string, Shader> Shaders = new();

    /// <summary>Uncut surfaces since start (a feature the port lacks, or a shader that failed to compile).</summary>
    public static int TotalFallbacks { get; private set; }

    /// <summary>The GLB extra the hull builder writes on every mesh node (app/core/hull_model.py), model metres.</summary>
    public const string PaddingExtra = "interior_cutout_padding_m";

    /// <summary>
    /// Cut one placed model. <paramref name="frame"/> takes a node of the placement into the world (the location group's
    /// transform times the chain under it — the placement may still hang detached; the location groups hang in an
    /// untransformed "Locations" node, so the group's own transform is its world transform). <paramref name="clipWorld"/> and
    /// <paramref name="cutoutsWorld"/> are world xz (already through <c>tileToWorld</c>), <paramref name="plane"/> a
    /// world plane. Null when there is nothing to cut.
    /// </summary>
    public static CutHandle? Apply(Node3D placed, IReadOnlyList<P2>? clipWorld, IReadOnlyList<IReadOnlyList<P2>>? cutoutsWorld,
                                   CutPlaneData? plane, Func<Node3D, Transform3D> frame)
    {
        var probe = CutShader.Pack(clipWorld, cutoutsWorld, 0, plane);
        if (!probe.Any) return null;
        var handle = new CutHandle();
        // One clone per (source material, padding) within the placement: meshes sharing a material share its cut twin.
        var converted = new Dictionary<(Material, double), ShaderMaterial?>();
        foreach (var mi in Walk(placed).OfType<MeshInstance3D>())
        {
            if (mi.Mesh is null) continue;
            double padding = 0;
            if (probe.HasCutouts && PaddingOf(mi) is { } declared)
            {
                var s = frame(mi).Basis.Scale;
                padding = ClipMath.CutoutPadding(declared, Math.Max(Math.Abs(s.X), Math.Max(Math.Abs(s.Y), Math.Abs(s.Z))));
            }
            var u = padding > 0 ? CutShader.Pack(clipWorld, cutoutsWorld, padding, plane) : probe;
            for (int s = 0; s < mi.Mesh.GetSurfaceCount(); s++)
            {
                var src = mi.GetSurfaceOverrideMaterial(s) ?? mi.Mesh.SurfaceGetMaterial(s) ?? new StandardMaterial3D();
                if (!converted.TryGetValue((src, padding), out var mat)) converted[(src, padding)] = mat = Convert(src, u);
                if (mat is null) { handle.Fallbacks++; TotalFallbacks++; continue; }
                mi.SetSurfaceOverrideMaterial(s, mat);
                handle.Entries.Add(new CutHandle.Entry(mi, s, mat, u));
            }
        }
        return handle;
    }

    /// <summary>
    /// <c>mesh.userData.interior_cutout_padding_m</c>: three puts the glTF node's extras on the mesh object (and the
    /// mesh's extras, the node's winning); Godot's importer puts them into the <c>extras</c> meta of the generated node
    /// and of the mesh resource. Null when undeclared.
    /// </summary>
    public static double? PaddingOf(MeshInstance3D mi)
    {
        foreach (var o in new GodotObject?[] { mi, mi.Mesh })
            if (o is not null && o.HasMeta("extras") && o.GetMeta("extras").VariantType == Variant.Type.Dictionary)
            {
                var extras = o.GetMeta("extras").AsGodotDictionary();
                if (extras.TryGetValue(PaddingExtra, out var v)
                    && v.VariantType is Variant.Type.Float or Variant.Type.Int) return v.AsDouble();
            }
        return null;
    }

    /// <summary>A world plane as the <c>cut_plane</c> uniform (xyz = normal, w = constant).</summary>
    public static Vector4 PlaneVector(CutPlaneData p)
        => new((float)p.Normal.X, (float)p.Normal.Y, (float)p.Normal.Z, (float)p.Constant);

    /// <summary>A Godot transform as the column-major 4×4 array <see cref="DepthCutMath.CutPlane"/> reads (three's <c>elements</c>).</summary>
    public static double[] ColumnMajor(Transform3D t) => new double[]
    {
        t.Basis.X.X, t.Basis.X.Y, t.Basis.X.Z, 0,
        t.Basis.Y.X, t.Basis.Y.Y, t.Basis.Y.Z, 0,
        t.Basis.Z.X, t.Basis.Z.Y, t.Basis.Z.Z, 0,
        t.Origin.X, t.Origin.Y, t.Origin.Z, 1,
    };

    /// <summary>
    /// The cut twin of one source material: a StandardMaterial3D through the generator port, a ShaderMaterial through its
    /// own code; null when it cannot be (unsupported feature, a shader that does not compile) — the surface then keeps its
    /// own material, uncut, and the reason is logged once.
    /// </summary>
    public static ShaderMaterial? Convert(Material src, CutUniforms u)
    {
        string? baseCode;
        string kind;
        StandardShaderSpec? spec = null;
        switch (src)
        {
            case StandardMaterial3D std:
                spec = SpecOf(std);
                baseCode = StandardShaderCode.Generate(spec);
                if (baseCode is null) { LogOnce($"cut: material '{std.ResourceName}' keeps its look uncut ({string.Join(", ", spec.Unsupported)})"); return null; }
                kind = "std" + (spec.Emission ? "+e" : "") + (spec.NormalMap ? "+n" : "") + (spec.AmbientOcclusion ? "+ao" : "")
                       + (spec.Transparency == StandardShaderSpec.TransparencyMode.AlphaScissor ? "+scissor"
                          : spec.Transparency == StandardShaderSpec.TransparencyMode.AlphaHash ? "+hash" : "");
                break;
            case ShaderMaterial sm when sm.Shader is { } sh && sh.GetMode() == Shader.Mode.Spatial:
                baseCode = sh.Code;
                // Named by its uniform count: the check can then derive the cut shader's count by hand (+ the cut's own).
                kind = "shader" + sh.GetShaderUniformList().Count;
                break;
            default:
                LogOnce($"cut: a {src.GetClass()} keeps its look uncut (no spatial shader to extend)");
                return null;
        }
        string code;
        try { code = CutShader.Inject(baseCode, u); }
        catch (ArgumentException e) { LogOnce($"cut: {kind} keeps its look uncut ({e.Message})"); return null; }
        if (!Shaders.TryGetValue(code, out var shader))
        {
            shader = new Shader { Code = code };
            Shaders[code] = shader;
        }
        if (!ShaderSafety.Ok(shader, ShaderName(kind, u))) return null;
        var mat = new ShaderMaterial { Shader = shader, RenderPriority = src.RenderPriority, NextPass = src.NextPass };
        if (src is StandardMaterial3D s3 && spec is not null) FeedStandard(mat, s3, spec);
        else if (src is ShaderMaterial sm2)
            foreach (var p in sm2.Shader.GetShaderUniformList())
            {
                var name = p.AsGodotDictionary()["name"].AsString();
                mat.SetShaderParameter(name, sm2.GetShaderParameter(name));
            }
        FeedCut(mat, u);
        return mat;
    }

    /// <summary>The <see cref="ShaderSafety"/> name of a cut shader: base kind plus the cuts it carries.</summary>
    public static string ShaderName(string kind, CutUniforms u)
        => $"cut[{kind}{(u.HasClip ? "+clip" : "")}{(u.HasCutouts ? "+cutouts" : "")}{(u.Padding > 0 ? "+pad" : "")}{(u.HasPlane ? "+plane" : "")}]";

    /// <summary>The cut uniforms (the switch starts OFF).</summary>
    private static void FeedCut(ShaderMaterial mat, CutUniforms u)
    {
        static Vector2[] V(IReadOnlyList<P2> pts) => pts.Select(p => new Vector2((float)p.X, (float)p.Z)).ToArray();
        if (u.HasClip) mat.SetShaderParameter("clip_pts", V(u.Clip));
        if (u.HasCutouts)
        {
            mat.SetShaderParameter("cut_pts", V(u.CutPoints));
            mat.SetShaderParameter("cut_off", u.CutOffsets.ToArray());
            mat.SetShaderParameter("cut_len", u.CutLengths.ToArray());
            mat.SetShaderParameter("cut_on", 0f);
        }
        if (u.Plane is { } pl) mat.SetShaderParameter("cut_plane", PlaneVector(pl));
    }

    /// <summary>
    /// The StandardMaterial3D's own values under the engine's uniform names — what its setters write into the material
    /// (material.cpp: <c>set_albedo</c>, <c>set_texture</c> + <c>albedo_texture_size</c>, the channel masks of
    /// <c>_get_texture_mask</c>, <c>emission_energy</c> = multiplier × intensity only with physical light units, …).
    /// </summary>
    private static void FeedStandard(ShaderMaterial mat, StandardMaterial3D m, StandardShaderSpec spec)
    {
        static Vector4 Mask(StandardShaderSpec.Channel ch)
        {
            var v = StandardShaderCode.ChannelVector(ch);
            return new Vector4((float)v.X, (float)v.Y, (float)v.Z, (float)v.W);
        }
        mat.SetShaderParameter("albedo", m.AlbedoColor);
        if (m.AlbedoTexture is { } at)
        {
            mat.SetShaderParameter("texture_albedo", at);
            mat.SetShaderParameter("albedo_texture_size", new Vector2I(at.GetWidth(), at.GetHeight()));
        }
        if (spec.Transparency == StandardShaderSpec.TransparencyMode.AlphaScissor)
            mat.SetShaderParameter("alpha_scissor_threshold", m.AlphaScissorThreshold);
        else if (spec.Transparency == StandardShaderSpec.TransparencyMode.AlphaHash)
            mat.SetShaderParameter("alpha_hash_scale", m.AlphaHashScale);
        mat.SetShaderParameter("point_size", m.PointSize);
        mat.SetShaderParameter("roughness", m.Roughness);
        if (m.MetallicTexture is { } mt) mat.SetShaderParameter("texture_metallic", mt);
        mat.SetShaderParameter("metallic_texture_channel", Mask(ChannelOf(m.MetallicTextureChannel)));
        if (m.RoughnessTexture is { } rt) mat.SetShaderParameter("texture_roughness", rt);
        mat.SetShaderParameter("specular", m.MetallicSpecular);
        mat.SetShaderParameter("metallic", m.Metallic);
        if (spec.Emission)
        {
            if (m.EmissionTexture is { } et) mat.SetShaderParameter("texture_emission", et);
            mat.SetShaderParameter("emission", m.Emission);
            bool physical = ProjectSettings.GetSetting("rendering/lights_and_shadows/use_physical_light_units", false).AsBool();
            mat.SetShaderParameter("emission_energy", m.EmissionEnergyMultiplier * (physical ? m.EmissionIntensity : 1f));
        }
        if (spec.NormalMap)
        {
            if (m.NormalTexture is { } nt) mat.SetShaderParameter("texture_normal", nt);
            mat.SetShaderParameter("normal_scale", m.NormalScale);
        }
        if (spec.AmbientOcclusion)
        {
            if (m.AOTexture is { } ao) mat.SetShaderParameter("texture_ambient_occlusion", ao);
            mat.SetShaderParameter("ao_texture_channel", Mask(ChannelOf(m.AOTextureChannel)));
            mat.SetShaderParameter("ao_light_affect", m.AOLightAffect);
        }
        mat.SetShaderParameter("uv1_scale", m.Uv1Scale);
        mat.SetShaderParameter("uv1_offset", m.Uv1Offset);
        mat.SetShaderParameter("uv2_scale", m.UV2Scale);
        mat.SetShaderParameter("uv2_offset", m.UV2Offset);
    }

    private static StandardShaderSpec.Channel ChannelOf(BaseMaterial3D.TextureChannel ch) => ch switch
    {
        BaseMaterial3D.TextureChannel.Red => StandardShaderSpec.Channel.Red,
        BaseMaterial3D.TextureChannel.Green => StandardShaderSpec.Channel.Green,
        BaseMaterial3D.TextureChannel.Blue => StandardShaderSpec.Channel.Blue,
        BaseMaterial3D.TextureChannel.Alpha => StandardShaderSpec.Channel.Alpha,
        _ => StandardShaderSpec.Channel.Grayscale,
    };

    /// <summary>
    /// What the generator port needs to know of a material, mapped by NAME from Godot's enums; every feature the port
    /// does not generate lands in <see cref="StandardShaderSpec.Unsupported"/>.
    /// </summary>
    public static StandardShaderSpec SpecOf(BaseMaterial3D m)
    {
        var bad = new List<string>();
        void Need(bool ok, string feature) { if (!ok) bad.Add(feature); }
        Need(m is StandardMaterial3D, "ORM material");
        Need(!m.Uv1Triplanar, "uv1 triplanar");
        Need(!m.UV2Triplanar, "uv2 triplanar");
        Need(!m.DetailEnabled, "detail");
        Need(!m.RefractionEnabled, "refraction");
        Need(!m.ClearcoatEnabled, "clearcoat");
        Need(!m.RimEnabled, "rim");
        Need(!m.AnisotropyEnabled, "anisotropy");
        Need(!m.HeightmapEnabled, "heightmap");
        Need(!m.SubsurfScatterEnabled, "subsurface scattering");
        Need(!m.SubsurfScatterTransmittanceEnabled, "transmittance");
        Need(!m.BacklightEnabled, "backlight");
        Need(!m.BentNormalEnabled, "bent normal");
        Need(!m.Grow, "grow");
        Need(!m.ProximityFadeEnabled, "proximity fade");
        Need(m.DistanceFadeMode == BaseMaterial3D.DistanceFadeModeEnum.Disabled, "distance fade");
        Need(m.BillboardMode == BaseMaterial3D.BillboardModeEnum.Disabled, "billboard");
        Need(!m.FixedSize, "fixed size");
        Need(!m.UsePointSize, "point size");
        Need(!m.AlbedoTextureMsdf, "msdf");
        Need(!m.UseParticleTrails, "particle trails");
        Need(!m.UseZClipScale, "z clip scale");
        Need(!m.UseFovOverride, "fov override");
        Need(m.StencilMode == BaseMaterial3D.StencilModeEnum.Disabled, "stencil");
        Need(m.AlphaAntialiasingMode == BaseMaterial3D.AlphaAntiAliasing.Off
             || m.Transparency is not (BaseMaterial3D.TransparencyEnum.AlphaScissor or BaseMaterial3D.TransparencyEnum.AlphaHash),
             "alpha antialiasing");
        return new StandardShaderSpec
        {
            Transparency = m.Transparency switch
            {
                BaseMaterial3D.TransparencyEnum.Alpha => StandardShaderSpec.TransparencyMode.Alpha,
                BaseMaterial3D.TransparencyEnum.AlphaScissor => StandardShaderSpec.TransparencyMode.AlphaScissor,
                BaseMaterial3D.TransparencyEnum.AlphaHash => StandardShaderSpec.TransparencyMode.AlphaHash,
                BaseMaterial3D.TransparencyEnum.AlphaDepthPrePass => StandardShaderSpec.TransparencyMode.AlphaDepthPrePass,
                _ => StandardShaderSpec.TransparencyMode.Disabled,
            },
            BlendMode = m.BlendMode switch
            {
                BaseMaterial3D.BlendModeEnum.Add => StandardShaderSpec.BlendModeKind.Add,
                BaseMaterial3D.BlendModeEnum.Sub => StandardShaderSpec.BlendModeKind.Sub,
                BaseMaterial3D.BlendModeEnum.Mul => StandardShaderSpec.BlendModeKind.Mul,
                BaseMaterial3D.BlendModeEnum.PremultAlpha => StandardShaderSpec.BlendModeKind.PremultAlpha,
                _ => StandardShaderSpec.BlendModeKind.Mix,
            },
            DepthDraw = m.DepthDrawMode switch
            {
                BaseMaterial3D.DepthDrawModeEnum.Always => StandardShaderSpec.DepthDrawKind.Always,
                BaseMaterial3D.DepthDrawModeEnum.Disabled => StandardShaderSpec.DepthDrawKind.Disabled,
                _ => StandardShaderSpec.DepthDrawKind.OpaqueOnly,
            },
            Cull = m.CullMode switch
            {
                BaseMaterial3D.CullModeEnum.Front => StandardShaderSpec.CullKind.Front,
                BaseMaterial3D.CullModeEnum.Disabled => StandardShaderSpec.CullKind.Disabled,
                _ => StandardShaderSpec.CullKind.Back,
            },
            Diffuse = m.DiffuseMode switch
            {
                BaseMaterial3D.DiffuseModeEnum.Lambert => StandardShaderSpec.DiffuseKind.Lambert,
                BaseMaterial3D.DiffuseModeEnum.LambertWrap => StandardShaderSpec.DiffuseKind.LambertWrap,
                BaseMaterial3D.DiffuseModeEnum.Toon => StandardShaderSpec.DiffuseKind.Toon,
                _ => StandardShaderSpec.DiffuseKind.Burley,
            },
            Specular = m.SpecularMode switch
            {
                BaseMaterial3D.SpecularModeEnum.Toon => StandardShaderSpec.SpecularKind.Toon,
                BaseMaterial3D.SpecularModeEnum.Disabled => StandardShaderSpec.SpecularKind.Disabled,
                _ => StandardShaderSpec.SpecularKind.SchlickGgx,
            },
            Shading = m.ShadingMode switch
            {
                BaseMaterial3D.ShadingModeEnum.Unshaded => StandardShaderSpec.ShadingKind.Unshaded,
                BaseMaterial3D.ShadingModeEnum.PerVertex => StandardShaderSpec.ShadingKind.PerVertex,
                _ => StandardShaderSpec.ShadingKind.PerPixel,
            },
            Filter = m.TextureFilter switch
            {
                BaseMaterial3D.TextureFilterEnum.Nearest => StandardShaderSpec.FilterKind.Nearest,
                BaseMaterial3D.TextureFilterEnum.Linear => StandardShaderSpec.FilterKind.Linear,
                BaseMaterial3D.TextureFilterEnum.NearestWithMipmaps => StandardShaderSpec.FilterKind.NearestWithMipmaps,
                BaseMaterial3D.TextureFilterEnum.NearestWithMipmapsAnisotropic => StandardShaderSpec.FilterKind.NearestWithMipmapsAnisotropic,
                BaseMaterial3D.TextureFilterEnum.LinearWithMipmapsAnisotropic => StandardShaderSpec.FilterKind.LinearWithMipmapsAnisotropic,
                _ => StandardShaderSpec.FilterKind.LinearWithMipmaps,
            },
            Repeat = m.TextureRepeat,
            DepthTest = m.DepthTest == BaseMaterial3D.DepthTestEnum.Inverted ? StandardShaderSpec.DepthTestKind.Inverted
                                                                             : StandardShaderSpec.DepthTestKind.Default,
            DisableDepthTest = m.NoDepthTest,
            AlbedoFromVertexColor = m.VertexColorUseAsAlbedo,
            SrgbVertexColor = m.VertexColorIsSrgb,
            AlbedoForceSrgb = m.AlbedoTextureForceSrgb,
            DontReceiveShadows = m.DisableReceiveShadows,
            DisableAmbientLight = m.DisableAmbientLight,
            ShadowToOpacity = m.ShadowToOpacity,
            DisableFog = m.DisableFog,
            DisableSpecularOcclusion = m.DisableSpecularOcclusion,
            RoughnessChannel = ChannelOf(m.RoughnessTextureChannel),
            NormalMap = m.NormalEnabled,
            Emission = m.EmissionEnabled,
            EmissionAdd = m.EmissionOperator == BaseMaterial3D.EmissionOperatorEnum.Add,
            EmissionOnUv2 = m.EmissionOnUV2,
            AmbientOcclusion = m.AOEnabled,
            AoOnUv2 = m.AOOnUV2,
            Unsupported = bad,
        };
    }

    private static readonly HashSet<string> Logged = new();

    private static void LogOnce(string line)
    {
        if (Logged.Add(line)) GD.Print("[native] " + line);
    }

    private static IEnumerable<Node> Walk(Node n)
    {
        yield return n;
        foreach (var c in n.GetChildren())
        foreach (var d in Walk(c))
            yield return d;
    }
}
