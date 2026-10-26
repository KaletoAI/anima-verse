using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Scene;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// The crossfade and the neighbour occlusion of ONE mounted location — the native twin of tiles.ts
/// <c>applyTileFade</c> and <c>applyTileOcclusion</c>, driven per frame by <see cref="WorldBuilder.TickView"/>. The
/// numbers are the Core's (<see cref="SceneView.FadeStep"/>, <see cref="SceneView.FadeOpacities"/>,
/// <see cref="SceneView.OcclusionStep"/>, scene_view.json); this class only writes them onto nodes:
///
///   • interior group visible at fade &gt; 0.03 (it is mounted once and held at fade 0 — no rebuild to open);
///   • roof parts (a fading building model: display shell / shell_area / roof_only, and the far-shell copies)
///     at opacity max(0, 1 − 1.4·f), hidden from f ≥ 0.95;
///   • everything outside the interior casts shadows while f &lt; 0.4 (only when there IS an interior — without one the
///     construction flags stand, as the browser returns early);
///   • the cutouts of a building model open at f &gt; 0.03 (not on a shell area): the <c>cut_on</c> uniform of its
///     cut materials (<see cref="CutHandle.SetCutoutsEnabled"/>, the browser's <c>setTileCutoutsEnabled</c> —
///     per fragment, no second model); a ground model hides altogether while a storey below ground is shown
///     (<see cref="SetGroundHidden"/>, driven by <see cref="LocationStoreys"/>);
///   • an outdoor outline wall is camera-culled only while the interior is up (its instance's <c>cull_active</c>);
///     which storey's walls stand is <see cref="LocationStoreys"/>' business;
///   • a neighbour between the camera and the open location fades by the occlusion, hidden from 0.95.
///
/// TRANSPARENCY (Step 0 of Task 15): the opacities go into <see cref="GeometryInstance3D.Transparency"/> — one
/// per mesh instance, multiplied by Godot into whatever its material does (StandardMaterial3D's own alpha, the recipe
/// shader's <c>ALPHA *= opacity</c>). No material is cloned or switched: at transparency 0 a mesh stays in the
/// opaque pass with its depth pre-pass and shadows, and <see cref="SceneView.InstanceTransparency"/> hands back 0
/// exactly where Godot would draw it opaque anyway (fade alpha ≥ 0.999), so the transparent pass costs only while a
/// fade is running (or a neighbour is held faded).
/// </summary>
public sealed class LocationFade
{
    /// <summary>The interior group (the browser's <c>tile.interior</c>, <c>g</c>); null when the scene has none.</summary>
    public Node3D? Interior { get; set; }
    /// <summary>Roof parts: fading building models and far-shell copies (<c>tile.roofParts</c>/<c>roofMats</c>).</summary>
    public List<Node3D> RoofParts { get; } = new();
    /// <summary>The cutout handles of the building model(s) (<c>tile.cutouts</c>), switched with the fade.</summary>
    public List<CutHandle> Cutouts { get; } = new();
    /// <summary>Display-ground models (with or without cutouts): they hide in a basement view.</summary>
    public List<Node3D> GroundModels { get; } = new();
    /// <summary><c>sm.visible = !(f &gt; 0.03 &amp;&amp; levelFilter &lt; 0)</c> for the ground model(s).</summary>
    public bool GroundHidden { get; private set; }
    /// <summary>Outdoor recipe meshes whose outline walls cull only while the interior is up.</summary>
    public List<GeometryInstance3D> OutdoorCull { get; } = new();
    /// <summary><c>tile.modelIsShellArea</c>: its cutouts stay shut (the model itself fades).</summary>
    public bool ShellArea { get; set; }

    /// <summary>Meta on an overlay mesh (door marks): never a shadow caster, never a pick target.</summary>
    public const string OverlayMeta = "overlay";

    public double Fade { get; private set; }
    public double Occl { get; private set; }

    private readonly List<GeometryInstance3D> _roofMeshes = new();
    private readonly List<GeometryInstance3D> _shellMeshes = new();
    private readonly List<GeometryInstance3D> _allMeshes = new();
    private readonly HashSet<GeometryInstance3D> _roofSet = new();
    private FadeLook? _look;
    private double _roof = 1, _appliedRoof = double.NaN, _appliedOccl = double.NaN;
    private bool? _cutOn, _shadow;

    /// <summary>
    /// Index the mounted group once it is complete (every placement awaited) and put it in the closed state:
    /// fade 0 — interior hidden, roof opaque, cutouts shut, outdoor culling off.
    /// </summary>
    public void Collect(Node3D group)
    {
        _roofMeshes.Clear();
        _shellMeshes.Clear();
        _allMeshes.Clear();
        foreach (var part in RoofParts) _roofMeshes.AddRange(Walk(part).OfType<GeometryInstance3D>());
        _roofSet.Clear();
        _roofSet.UnionWith(_roofMeshes);
        foreach (var g in Walk(group).OfType<GeometryInstance3D>())
        {
            _allMeshes.Add(g);
            // The flat overlays (door marks) never cast: the browser's would only at f < 0.4, where they are hidden.
            // Without an interior applyTileFade returns before its shadow traverse: every mesh keeps its construction
            // flag (the building model casts, the rest does not — SceneModels.CastNone, RecipePiece.Cast; Task 26c).
            if (Interior is not null && !Interior.IsAncestorOf(g) && !g.HasMeta(OverlayMeta)) _shellMeshes.Add(g);
        }
        _look = null;
        _cutOn = null;
        _shadow = null;
        _appliedRoof = _appliedOccl = double.NaN;   // every (new) mesh gets its transparency written
        Apply(Fade);
    }

    /// <summary><c>tile.fade = fadeStep(tile.fade, tile.fadeTarget, dt)</c> then <c>applyTileFade</c>.</summary>
    public void Step(double dt, bool open)
    {
        double next = SceneView.FadeStep(Fade, open ? 1 : 0, dt);
        if (next == Fade && _look is not null) return;
        Fade = next;
        Apply(Fade);
    }

    /// <summary>Set the fade outright (the checks; a boot that should not crossfade in).</summary>
    public void Snap(double fade)
    {
        Fade = fade;
        Apply(fade);
    }

    /// <summary><c>applyTileFade</c> without the step (only what changed is written).</summary>
    private void Apply(double f)
    {
        var look = SceneView.FadeOpacities(f);
        if (_cutOn != f > 0.03)
        {
            _cutOn = f > 0.03;
            ApplyModels();
        }
        if (_look is not { } old || old.RoofVisible != look.RoofVisible)
            foreach (var p in RoofParts) p.Visible = look.RoofVisible;
        if (_shadow != look.ShellShadow)
        {
            _shadow = look.ShellShadow;
            var mode = look.ShellShadow ? GeometryInstance3D.ShadowCastingSetting.On : GeometryInstance3D.ShadowCastingSetting.Off;
            foreach (var g in _shellMeshes) g.CastShadow = mode;
            ShadowCasterGate.MarkDirty();
        }
        if (_look is not { } prev || prev.InteriorVisible != look.InteriorVisible)
        {
            if (Interior is not null) Interior.Visible = look.InteriorVisible;
            foreach (var g in OutdoorCull) g.SetInstanceShaderParameter("cull_active", look.InteriorVisible ? 1f : 0f);
        }
        _look = look;
        _roof = look.Roof;
        WriteTransparency();
    }

    /// <summary>A storey below ground is shown (or no longer is): the ground model(s) hide or come back.</summary>
    public void SetGroundHidden(bool hidden)
    {
        if (GroundHidden == hidden) return;
        GroundHidden = hidden;
        ApplyModels();
    }

    /// <summary>The cutouts by the fade state, a ground model hidden in a basement view.</summary>
    private void ApplyModels()
    {
        bool cut = !ShellArea && _cutOn == true;
        foreach (var h in Cutouts) h.SetCutoutsEnabled(cut);
        foreach (var g in GroundModels)
            if (GodotObject.IsInstanceValid(g)) g.Visible = !GroundHidden;
    }

    /// <summary>
    /// <c>applyTileOcclusion</c>: the occlusion step and the group's visibility (<c>occl &lt; 0.95</c>), then the
    /// opacities. Nothing is written for a location at 0 that nothing hides.
    /// </summary>
    public void StepOcclusion(Node3D group, bool hide, double dt)
    {
        if (Occl == 0 && !hide) return;
        Occl = SceneView.OcclusionStep(Occl, hide, dt);
        bool visible = Occl < SceneView.OccludedHideAt;
        if (group.Visible != visible) group.Visible = visible;
        WriteTransparency();
    }

    /// <summary>One transparency per mesh: the roof's opacity on roof parts, 1 elsewhere, both times (1 − occlusion).</summary>
    private void WriteTransparency()
    {
        bool occlChanged = Occl != _appliedOccl;
        if (!occlChanged && _roof == _appliedRoof) return;
        float roofT = (float)SceneView.InstanceTransparency(_roof, Occl);
        foreach (var g in _roofMeshes)
            if (GodotObject.IsInstanceValid(g) && g.Transparency != roofT) g.Transparency = roofT;
        if (occlChanged)
        {
            float t = (float)SceneView.InstanceTransparency(1, Occl);
            foreach (var g in _allMeshes)
                if (!_roofSet.Contains(g) && GodotObject.IsInstanceValid(g) && g.Transparency != t) g.Transparency = t;
        }
        _appliedRoof = _roof;
        _appliedOccl = Occl;
    }

    /// <summary>The mesh instances of the location (for the checks).</summary>
    public IReadOnlyList<GeometryInstance3D> Meshes => _allMeshes;
    public IReadOnlyList<GeometryInstance3D> RoofMeshes => _roofMeshes;

    private static IEnumerable<Node> Walk(Node n)
    {
        yield return n;
        foreach (var c in n.GetChildren())
        foreach (var d in Walk(c))
            yield return d;
    }
}
