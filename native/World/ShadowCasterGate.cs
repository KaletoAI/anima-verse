using System;
using System.Collections.Generic;
using System.Diagnostics;
using AnimaNative.Sky;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// The browser's shadow box on Godot (Task 26c, <see cref="ShadowBoxGate"/>): every <see cref="GeometryInstance3D"/> that
/// enters the tree is registered (<c>SceneTree.node_added</c> / <c>node_removed</c> — one registry for every class, no
/// per-feature bookkeeping); a pass sets <see cref="Layer"/> on the casters whose bounds meet the browser's prism and
/// clears it on the rest, and the sun's <c>shadow_caster_mask</c> is that layer alone. Godot 4.7.2 tests
/// <c>visible_layers &amp; layer_mask &amp; caster_mask</c> per instance in its directional shadow cull
/// (renderer_scene_cull.cpp), so an instance without the layer never enters the shadow pass. Which classes cast at all is
/// still each node's <c>cast_shadow</c> (the browser's <c>castShadow</c> per class); the gate only adds WHERE.
///
/// Instances on <see cref="HemiUniforms.Layer"/> (terrain, scatter — none of them casts) never get the layer: the
/// hemisphere pair's cull mask would light them again. A node whose <c>cast_shadow</c> is off is skipped (its layer is
/// left as it is — it casts nothing either way); <see cref="MarkDirty"/> asks for a pass when a class turns its casting
/// on (the crossfade's shell shadow).
/// </summary>
public sealed class ShadowCasterGate
{
    /// <summary>Render layer 19: "inside the browser's shadow box".</summary>
    public const uint Layer = 1u << 18;

    private static ShadowCasterGate? _current;
    private readonly HashSet<GeometryInstance3D> _all = new();
    private readonly HashSet<GeometryInstance3D> _in = new();
    private readonly List<GeometryInstance3D> _scratch = new();
    private SceneTree? _tree;
    private ShadowBoxGate.Box? _last;
    private (double X, double Y, double Z) _lastOffset;
    private ulong _lastMs;
    private bool _dirty = true, _off;

    /// <summary>Registered instances / instances inside the last gated prism.</summary>
    public int Registered => _all.Count;
    public int Inside => _in.Count;
    /// <summary>Passes made and the time of the last one (ms), for the log and the check.</summary>
    public int Passes { get; private set; }
    public double LastPassMs { get; private set; }
    /// <summary>The prism of the last pass (null before the first).</summary>
    public ShadowBoxGate.Box? LastBox => _last;

    /// <summary>The bench switch <c>shadow-full-view</c>: every caster gets the layer (Godot's frustum fit alone decides).</summary>
    public bool Off
    {
        get => _off;
        set
        {
            if (_off == value) return;
            _off = value;
            _dirty = true;
        }
    }

    /// <summary>A class turned its casting on or off (the crossfade): the next <see cref="Update"/> makes a pass.</summary>
    public static void MarkDirty()
    {
        if (_current is { } g) g._dirty = true;
    }

    /// <summary>Registers every instance under <paramref name="root"/> now and every one that enters the tree later.</summary>
    public void Attach(Node root)
    {
        _tree = root.GetTree();
        _tree.NodeAdded += OnAdded;
        _tree.NodeRemoved += OnRemoved;
        var stack = new Stack<Node>();
        stack.Push(root);
        while (stack.Count > 0)
        {
            var n = stack.Pop();
            OnAdded(n);
            foreach (var c in n.GetChildren()) stack.Push(c);
        }
        _current = this;
    }

    public void Detach()
    {
        if (_tree is not null && GodotObject.IsInstanceValid(_tree))
        {
            _tree.NodeAdded -= OnAdded;
            _tree.NodeRemoved -= OnRemoved;
        }
        _tree = null;
        _all.Clear();
        _in.Clear();
        if (ReferenceEquals(_current, this)) _current = null;
    }

    private void OnAdded(Node n)
    {
        if (n is GeometryInstance3D g && _all.Add(g)) _dirty = true;
    }

    private void OnRemoved(Node n)
    {
        if (n is not GeometryInstance3D g) return;
        _all.Remove(g);
        _in.Remove(g);
    }

    /// <summary>
    /// The frame's sun (<see cref="StageAmbience.Track"/>): the snapped centre and the offset. A pass runs when it is due
    /// (see <see cref="ShadowBoxGate"/>); otherwise nothing is touched.
    /// </summary>
    public void Update((double X, double Y, double Z) centre, (double X, double Y, double Z) offset)
    {
        ulong now = Time.GetTicksMsec();
        bool due = _dirty || _last is not { } last || offset != _lastOffset || ShadowBoxGate.Moved(last, centre)
                   || now - _lastMs >= (ulong)(ShadowBoxGate.RefreshS * 1000);
        if (!due) return;
        _lastMs = now;
        _lastOffset = offset;
        Pass(ShadowBoxGate.Of(centre, offset));
    }

    /// <summary>A pass now over the last prism (a switch or a check that must not wait for the next frame).</summary>
    public void MarkPass()
    {
        if (_last is { } box) Pass(box);
        else _dirty = true;
    }

    /// <summary>One pass over every registered instance (public for the check).</summary>
    public void Pass(ShadowBoxGate.Box box)
    {
        var sw = Stopwatch.StartNew();
        _dirty = false;
        _last = box;
        _scratch.Clear();
        _scratch.AddRange(_all);
        foreach (var g in _scratch)
        {
            if (!GodotObject.IsInstanceValid(g))
            {
                _all.Remove(g);
                _in.Remove(g);
                continue;
            }
            if ((g.Layers & HemiUniforms.Layer) != 0) continue;
            if (g.CastShadow == GeometryInstance3D.ShadowCastingSetting.Off) continue;
            bool want = _off || Meets(g, box);
            bool has = _in.Contains(g);
            if (want == has) continue;
            if (want)
            {
                _in.Add(g);
                g.Layers |= Layer;
            }
            else
            {
                _in.Remove(g);
                g.Layers &= ~Layer;
            }
        }
        Passes++;
        LastPassMs = sw.Elapsed.TotalMilliseconds;
    }

    /// <summary>The instance's bounds (local AABB through its global transform) against the prism.</summary>
    public static bool Meets(GeometryInstance3D g, ShadowBoxGate.Box box)
    {
        var aabb = g.GetAabb();
        var xf = g.GlobalTransform;
        var c = xf * aabb.GetCenter();
        var e = aabb.Size * 0.5f;
        static (double, double, double) V(Vector3 v) => (v.X, v.Y, v.Z);
        return ShadowBoxGate.Overlaps(box, V(c), V(xf.Basis.Column0 * e.X), V(xf.Basis.Column1 * e.Y), V(xf.Basis.Column2 * e.Z));
    }
}
