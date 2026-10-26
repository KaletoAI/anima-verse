using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Figures;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Bench;

/// <summary>What one matrix pass can switch: the live objects of the running world (any may be missing).</summary>
public sealed class BenchSwitchContext
{
    public StageAmbience? Stage { get; init; }
    public DistanceFog? Fog { get; init; }
    public Func<WorldBackdrop?>? Backdrop { get; init; }
    public WorldBuilder? Builder { get; init; }
    public FigureManager? Figures { get; init; }
    /// <summary>The browser's shadow-caster box (Task 26c).</summary>
    public ShadowCasterGate? Gate { get; init; }
}

/// <summary>A switch in force: whether it found anything to switch, what it did, and how to put it back.</summary>
public sealed record BenchSwitch(string Variant, bool Applied, string Detail, Action Restore);

/// <summary>
/// The runtime feature switches of <c>--bench-matrix</c> (Task 26b, <see cref="BenchMatrix"/>): each variant switches
/// exactly one feature off on the LIVE world — a node hidden, a uniform zeroed, a light's flag, a renderer setting — and
/// its <see cref="BenchSwitch.Restore"/> puts back exactly what it found. Nothing is rebuilt; nothing else changes
/// between passes. A switch that finds nothing to switch (no mirror in the world, no GPU for the compute fog) still
/// runs its pass and says so (<c>applied: false</c>), so every matrix has the same rows.
/// </summary>
public static class BenchSwitches
{
    private static readonly Action Nothing = () => { };

    public static BenchSwitch Apply(string variant, BenchSwitchContext c) => variant switch
    {
        BenchMatrix.Baseline => new(variant, true, "nothing switched", Nothing),
        "no-shadow" => NoShadow(c),
        "shadow-full-view" => ShadowFullView(c),
        "no-hemi-extra-lights" => NoHemi(c),
        "no-fog-pass" => NoFog(c),
        "no-veil" => NoVeil(),
        "no-backdrop" => NoBackdrop(c),
        "no-water-extras" => NoWaterExtras(c),
        "no-mirrors" => NoMirrors(c),
        "no-prop-lights" => NoPropLights(c),
        "no-cut-shader" => NoCutShader(),
        "terrain-lod-coarse" => TerrainCoarse(c),
        "shadow-atlas-2048" => Atlas2048(),
        "fog-pass" => FogPass(c),
        "no-figures" => NoFigures(c),
        _ => throw new ArgumentException($"bench matrix: no switch for variant '{variant}'"),
    };

    private static BenchSwitch NoShadow(BenchSwitchContext c)
    {
        if (c.Stage is not { } s) return new("no-shadow", false, "no stage", Nothing);
        bool was = s.Sun.ShadowEnabled;
        s.Sun.ShadowEnabled = false;
        return new("no-shadow", was, was ? "sun shadow off" : "the sun had no shadow", () => s.Sun.ShadowEnabled = was);
    }

    private static BenchSwitch ShadowFullView(BenchSwitchContext c)
    {
        if (c.Gate is not { } g) return new("shadow-full-view", false, "no caster gate", Nothing);
        bool was = g.Off;
        int inside = g.Inside;
        g.Off = true;
        g.MarkPass();
        return new("shadow-full-view", !was, $"caster box off: {g.Inside} of {g.Registered} instances carry the caster layer (box: {inside})",
                   () =>
                   {
                       g.Off = was;
                       g.MarkPass();
                   });
    }

    private static BenchSwitch NoHemi(BenchSwitchContext c)
    {
        if (c.Stage is not { } s) return new("no-hemi-extra-lights", false, "no stage", Nothing);
        bool up = s.HemiUp.Visible, down = s.HemiDown.Visible;
        s.HemiUp.Visible = false;
        s.HemiDown.Visible = false;
        HemiUniforms.Off = true;
        int mats = HemiUniforms.Materials().Count;
        return new("no-hemi-extra-lights", true, $"2 pair lights hidden, the term zero on {mats} ground/scatter materials (ambient only)", () =>
        {
            s.HemiUp.Visible = up;
            s.HemiDown.Visible = down;
            HemiUniforms.Off = false;
        });
    }

    private static BenchSwitch NoFog(BenchSwitchContext c)
    {
        if (c.Fog is not { } f || !GodotObject.IsInstanceValid(f)) return new("no-fog-pass", false, "no fog", Nothing);
        bool was = f.Off;
        f.Off = true;
        f.Decide();
        return new("no-fog-pass", true, "distance fog off (no pass, no copies)", () =>
        {
            f.Off = was;
            f.Decide();
        });
    }

    private static BenchSwitch NoVeil()
    {
        int mats = VeilUniforms.Materials().Count;
        VeilUniforms.Off = true;
        return new("no-veil", mats > 0, $"fv_alpha 0 on {mats} ground materials (alpha was {VeilUniforms.State.Alpha:0.###})",
                   () => VeilUniforms.Off = false);
    }

    private static BenchSwitch NoBackdrop(BenchSwitchContext c)
    {
        if (c.Backdrop?.Invoke() is not { } b || !GodotObject.IsInstanceValid(b)) return new("no-backdrop", false, "no backdrop", Nothing);
        bool was = b.Visible;
        b.Visible = false;
        return new("no-backdrop", b.Rings.Count > 0, $"{b.Rings.Count} rings hidden", () => b.Visible = was);
    }

    private static BenchSwitch NoWaterExtras(BenchSwitchContext c)
    {
        var restore = new List<Action>();
        int ripple = 0, ghosts = 0, sheets = 0, falls = 0;
        // The terrain water's ripple: the wet program's switch uniform.
        if (c.Builder?.Terrain is { } t && c.Builder.Ground?.WaterMaterial is { } wm && ReferenceEquals(t.Materials.Wet, wm))
        {
            var old = wm.GetShaderParameter("tw_ripple_on");
            wm.SetShaderParameter("tw_ripple_on", 0f);
            ripple = 1;
            restore.Add(() => wm.SetShaderParameter("tw_ripple_on", old.VariantType == Variant.Type.Nil ? 1f : old));
        }
        // The underwater ghosts: the switch every ghost reads, then each one re-decides (figures re-gate every frame too).
        var all = AllGhosts(c).ToList();
        bool offWas = SubmergedGhost.Off;
        ghosts = all.Count(g => g.Visible);
        SubmergedGhost.Off = true;
        foreach (var g in all) g.Reapply();
        restore.Add(() =>
        {
            SubmergedGhost.Off = offWas;
            foreach (var g in AllGhosts(c)) g.Reapply();
        });
        // Waterfalls and prop water sheets: hidden, their own visibility put back.
        if (c.Builder?.Waterfalls is { } wf && GodotObject.IsInstanceValid(wf))
        {
            bool was = wf.Visible;
            wf.Visible = false;
            falls = wf.Falls.Count;
            restore.Add(() => wf.Visible = was);
        }
        foreach (var sheet in AllSheets(c))
        {
            if (!GodotObject.IsInstanceValid(sheet) || !sheet.Visible) continue;
            sheet.Visible = false;
            sheets++;
            restore.Add(() => { if (GodotObject.IsInstanceValid(sheet)) sheet.Visible = true; });
        }
        bool applied = ripple + ghosts + sheets + falls > 0;
        return new("no-water-extras", applied, $"ripple off on {ripple} water material, {ghosts} ghosts, {falls} waterfalls, {sheets} prop water sheets hidden",
                   () => { foreach (var r in restore) r(); });
    }

    private static IEnumerable<SubmergedGhost> AllGhosts(BenchSwitchContext c)
    {
        if (c.Builder is { } b)
        {
            foreach (var slot in b.Slots.Values)
                foreach (var rec in slot.Placements)
                    if (rec.Ghost is { } g) yield return g;
            foreach (var w in b.WorldPropWater)
                if (w.Ghost is { } g) yield return g;
        }
        if (c.Figures is { } f && GodotObject.IsInstanceValid(f))
            foreach (var fig in f.Figures.Values)
                if (fig.Ghost is { } g) yield return g;
    }

    private static IEnumerable<MeshInstance3D> AllSheets(BenchSwitchContext c)
    {
        if (c.Builder is not { } b) yield break;
        foreach (var slot in b.Slots.Values)
            foreach (var rec in slot.Placements)
                if (rec.WaterSheets is { } list)
                    foreach (var s in list) yield return s;
        foreach (var w in b.WorldPropWater)
            foreach (var s in w.Sheets) yield return s;
    }

    private static BenchSwitch NoMirrors(BenchSwitchContext c)
    {
        if (c.Builder?.Mirrors is not { } m || !GodotObject.IsInstanceValid(m)) return new("no-mirrors", false, "no mirror layer", Nothing);
        int panes = m.Panes.Count, passes = m.Panes.Sum(p => p.Passes);
        bool was = m.Suspended;
        m.Suspended = true;
        return new("no-mirrors", panes > 0, $"{panes} panes, no passes (they had made {passes} so far)", () => m.Suspended = was);
    }

    private static BenchSwitch NoPropLights(BenchSwitchContext c)
    {
        if (c.Builder?.PropLights is not { } p || !GodotObject.IsInstanceValid(p)) return new("no-prop-lights", false, "no prop light pool", Nothing);
        bool was = p.Visible;
        int lit = p.Lamps.Count(l => l.Visible);
        p.Visible = false;
        return new("no-prop-lights", true, $"6 lamps ({lit} lit) and {p.State.Count} sources' halos hidden", () => p.Visible = was);
    }

    private static BenchSwitch NoCutShader()
    {
        int surfaces = CutMaterials.LiveHandles().Sum(h => h.Entries.Count);
        CutMaterials.Plain = true;
        return new("no-cut-shader", surfaces > 0, $"{surfaces} cut surfaces wear their plain source material", () => CutMaterials.Plain = false);
    }

    private static BenchSwitch TerrainCoarse(BenchSwitchContext c)
    {
        if (c.Builder?.Terrain is not { } t || !GodotObject.IsInstanceValid(t)) return new("terrain-lod-coarse", false, "no terrain", Nothing);
        double was = t.PixelScaleFactor;
        t.PixelScaleFactor = was * 0.5;
        return new("terrain-lod-coarse", true, "pixel scale × 0.5 (allowed error 2 → 4 px)", () => t.PixelScaleFactor = was);
    }

    /// <summary>Godot's directional shadow atlas (<c>rendering/lights_and_shadows/directional_shadow/size</c>, 16 bits).</summary>
    public static (int Size, bool Bits16) AtlasSetting()
    {
        var size = ProjectSettings.GetSetting("rendering/lights_and_shadows/directional_shadow/size", 4096);
        var bits = ProjectSettings.GetSetting("rendering/lights_and_shadows/directional_shadow/16_bits", true);
        return (size.VariantType == Variant.Type.Int ? size.AsInt32() : 4096, bits.VariantType != Variant.Type.Bool || bits.AsBool());
    }

    private static BenchSwitch Atlas2048()
    {
        var (size, bits) = AtlasSetting();
        RenderingServer.DirectionalShadowAtlasSetSize(2048, bits);
        return new("shadow-atlas-2048", size != 2048, $"directional shadow atlas {size} → 2048 px",
                   () => RenderingServer.DirectionalShadowAtlasSetSize(size, bits));
    }

    /// <summary>
    /// Task 35: the figures' whole cost — the figure layer hidden (bodies, portraits, ghosts: nothing drawn, no skinning)
    /// AND its frame tick stopped (no walk, no clip advance, no placement / tier pass). Restore resumes both; the figures
    /// continue from where they stood.
    /// </summary>
    private static BenchSwitch NoFigures(BenchSwitchContext c)
    {
        if (c.Figures is not { } f || !GodotObject.IsInstanceValid(f)) return new("no-figures", false, "no figure manager", Nothing);
        bool visible = f.Visible, tick = f.AutoTick;
        int count = f.Figures.Count, animated = f.FiguresAnimated;
        f.Visible = false;
        f.AutoTick = false;
        return new("no-figures", count > 0, $"{count} figures ({animated} animated) hidden, their frame tick stopped", () =>
        {
            f.Visible = visible;
            f.AutoTick = tick;
        });
    }

    private static BenchSwitch FogPass(BenchSwitchContext c)
    {
        if (c.Fog is not { } f || !GodotObject.IsInstanceValid(f)) return new("fog-pass", false, "no fog", Nothing);
        bool live = f.ComputeActive;
        bool was = f.UseCompute;
        f.UseCompute = false;
        f.Decide();
        string why = live ? "the screen pass fogs the frame, the compute pass is off"
                     : f.Compute is null ? "no compute effect on the camera — the screen pass fogs anyway"
                     : f.Compute.Error.Length > 0 ? "the kernel did not compile — the screen pass fogs anyway: " + f.Compute.Error
                     : !was ? "--fog=pass — the screen pass fogs anyway"
                     : "no RenderingDevice (headless) — the screen pass fogs anyway";
        return new("fog-pass", live, why, () =>
        {
            f.UseCompute = was;
            f.Decide();
        });
    }
}
