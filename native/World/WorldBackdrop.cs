using System.Collections.Generic;
using AnimaNative.Sky;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// The far backdrop of § A17 (client3d/src/scene/backdrop.ts): two rings of mountain silhouettes at 380 m and 440 m
/// around the camera target — scenery only, no shadow, never pickable. The ridge is <see cref="Backdrop.RidgeProfile"/>
/// (vector-checked), the strips <see cref="BackdropMesh.Ring"/>, the tint <see cref="BackdropLook"/>. The node only ever
/// TRANSLATES (<see cref="Follow"/>), so north stays north while the target moves. The rings are unlit; the distance fog
/// pass (<see cref="DistanceFog"/>) hazes them like everything else, which is the browser's <c>fog: true</c>.
/// </summary>
public partial class WorldBackdrop : Node3D
{
    private readonly List<MeshInstance3D> _meshes = new();
    private readonly StandardMaterial3D?[] _materials = new StandardMaterial3D?[Backdrop.Layers];
    /// <summary>What the standing rings were built from; null until the first build, "" = the ring is off.</summary>
    private string? _builtKey;
    private double _night;
    private LinearRgb _sky = StageLight.BootSky;

    /// <summary>How many times rings were built (the check proves an unchanged payload rebuilds nothing).</summary>
    public int Builds { get; private set; }
    public string? BuiltKey => _builtKey;
    public IReadOnlyList<MeshInstance3D> Rings => _meshes;
    /// <summary>The ring material of a layer (null = that ring had nothing to draw, or none is built).</summary>
    public StandardMaterial3D? MaterialOf(int layer) => layer >= 0 && layer < _materials.Length ? _materials[layer] : null;

    /// <summary>
    /// <c>backdrop.sync(map.backdrop ?? null)</c>: rebuilds only when the key [height_m, seed, arcs] changed; null removes
    /// the rings.
    /// </summary>
    public void Sync(BackdropSpec? spec)
    {
        var key = spec?.Key ?? "";
        if (key == _builtKey) return;
        _builtKey = key;
        Clear();
        if (spec is null) return;
        Builds++;
        var profile = Backdrop.RidgeProfile(spec.Seed, spec.Arcs, spec.HeightM);
        for (int layer = 0; layer < Backdrop.Layers; layer++)
        {
            if (BackdropMesh.Ring(profile, layer) is not { } ring) continue;
            var verts = new Vector3[ring.Positions.Length / 3];
            for (int i = 0; i < verts.Length; i++)
                verts[i] = new Vector3((float)ring.Positions[i * 3], (float)ring.Positions[i * 3 + 1], (float)ring.Positions[i * 3 + 2]);
            var arrays = new Godot.Collections.Array();
            arrays.Resize((int)Mesh.ArrayType.Max);
            arrays[(int)Mesh.ArrayType.Vertex] = verts;
            arrays[(int)Mesh.ArrayType.Index] = ring.Indices;
            var mesh = new ArrayMesh();
            mesh.AddSurfaceFromArrays(Mesh.PrimitiveType.Triangles, arrays);
            var mat = new StandardMaterial3D
            {
                // MeshBasicMaterial: unlit, front faces only (the faces point at the centre, BackdropMesh).
                ShadingMode = BaseMaterial3D.ShadingModeEnum.Unshaded,
                CullMode = BaseMaterial3D.CullModeEnum.Back,
                DisableReceiveShadows = true,
            };
            var mi = new MeshInstance3D
            {
                Name = $"Ridge{layer}",
                Mesh = mesh,
                MaterialOverride = mat,
                CastShadow = GeometryInstance3D.ShadowCastingSetting.Off,
                GIMode = GeometryInstance3D.GIModeEnum.Disabled,
            };
            _materials[layer] = mat;
            _meshes.Add(mi);
            AddChild(mi);
        }
        ApplyTint();
    }

    /// <summary><c>setDayNight(night, sky)</c>: the engine's night factor and the sky it just set (linear working space).</summary>
    public void SetDayNight(double night, LinearRgb sky)
    {
        _night = BackdropLook.ClampNight(night);
        _sky = sky;
        ApplyTint();
    }

    /// <summary>The frame hook: <c>group.position.set(target.x, 0, target.z)</c> — position only, never rotation.</summary>
    public void Follow(Vector3 target)
    {
        var p = new Vector3(target.X, 0, target.Z);
        if (Position != p) Position = p;
    }

    private void ApplyTint()
    {
        for (int layer = 0; layer < _materials.Length; layer++)
        {
            if (_materials[layer] is not { } mat) continue;
            // An unlit Godot albedo is decoded from sRGB like a light colour: Encode hands the renderer three's linear colour.
            var c = GodotSrgb.Encode(BackdropLook.Colour(layer, _night, _sky));
            mat.AlbedoColor = new Color((float)c.R, (float)c.G, (float)c.B);
        }
    }

    private void Clear()
    {
        foreach (var m in _meshes)
            if (IsInstanceValid(m)) m.QueueFree();
        _meshes.Clear();
        for (int i = 0; i < _materials.Length; i++) _materials[i] = null;
    }
}
