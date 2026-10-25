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
///   • everything outside the interior casts shadows while f &lt; 0.4;
///   • the cutouts of a kept plan-hull / ground model open at f &gt; 0.03 (not on a shell area), by swapping the
///     whole model for its cut copy;
///   • an outdoor outline wall is camera-culled only while the interior is up (its instance's <c>cull_active</c>),
///     and an outdoor outline wall of another storey is only there while the interior is not;
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
    /// <summary>Kept models with cutouts: the whole model and its cut copy (one of the two is shown).</summary>
    public List<(Node3D Whole, Node3D Cut)> Cutouts { get; } = new();
    /// <summary>Outdoor outline walls of another storey: shown only while the interior is not.</summary>
    public List<Node3D> ClosedOnly { get; } = new();
    /// <summary>Outdoor recipe meshes whose outline walls cull only while the interior is up.</summary>
    public List<GeometryInstance3D> OutdoorCull { get; } = new();
    /// <summary><c>tile.modelIsShellArea</c>: its cutouts stay shut (the model itself fades).</summary>
    public bool ShellArea { get; set; }

    public double Fade { get; private set; }
    public double Occl { get; private set; }

    private readonly List<GeometryInstance3D> _roofMeshes = new();
    private readonly List<GeometryInstance3D> _shellMeshes = new();
    private readonly List<GeometryInstance3D> _allMeshes = new();
    private readonly HashSet<GeometryInstance3D> _roofSet = new();
    private FadeLook? _look;
    private double _roof = 1, _appliedRoof = 1, _appliedOccl;
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
            if (Interior is null || !Interior.IsAncestorOf(g)) _shellMeshes.Add(g);
        }
        _look = null;
        _cutOn = null;
        _shadow = null;
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
        if (!ShellArea && _cutOn != f > 0.03)
        {
            _cutOn = f > 0.03;
            foreach (var (whole, cut) in Cutouts)
            {
                whole.Visible = !_cutOn.Value;
                cut.Visible = _cutOn.Value;
            }
        }
        if (_look is not { } old || old.RoofVisible != look.RoofVisible)
            foreach (var p in RoofParts) p.Visible = look.RoofVisible;
        if (_shadow != look.ShellShadow)
        {
            _shadow = look.ShellShadow;
            var mode = look.ShellShadow ? GeometryInstance3D.ShadowCastingSetting.On : GeometryInstance3D.ShadowCastingSetting.Off;
            foreach (var g in _shellMeshes) g.CastShadow = mode;
        }
        if (_look is not { } prev || prev.InteriorVisible != look.InteriorVisible)
        {
            if (Interior is not null) Interior.Visible = look.InteriorVisible;
            foreach (var n in ClosedOnly) n.Visible = !look.InteriorVisible;
            foreach (var g in OutdoorCull) g.SetInstanceShaderParameter("cull_active", look.InteriorVisible ? 1f : 0f);
        }
        _look = look;
        _roof = look.Roof;
        WriteTransparency();
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
