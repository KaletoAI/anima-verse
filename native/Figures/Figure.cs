using System;
using Godot;

namespace AnimaNative.Figures;

/// <summary>
/// One character on the map. The node sits at the figure's FEET in world
/// metres (y = world ground), turned to its walking direction; its body is
/// either the character's GLB (scaled to its height, with an AnimationPlayer
/// carrying the retargeted idle/walk clips) or a capsule placeholder.
///
/// Motion between polls is the spike's simple rule: a new target lerps in over
/// the poll interval (<see cref="FigureManager.PollSeconds"/>); while the
/// planned speed exceeds <see cref="WalkSpeed"/> the walk clip plays, else idle.
/// </summary>
public partial class Figure : Node3D
{
    public const double WalkSpeed = 0.2;   // m/s
    private const float Blend = 0.2f;

    public string CharacterName { get; }
    /// <summary>The model_sig the current body was loaded for (null = none / placeholder without a store).</summary>
    public string? LoadedSig { get; set; }
    public string? WantedSig { get; set; }
    public bool Loading { get; set; }
    public double HeightM { get; set; } = FigureManager.DefaultHeightM;
    /// <summary>Clip tracks bound on this figure's skeleton (all roles).</summary>
    public int BoundTracks { get; set; }
    /// <summary>Roles (idle/walk) a humanoid figure could not bind — it stands in bind pose for them.</summary>
    public int UnboundClips { get; set; }

    public bool IsGlb { get; private set; }
    public AnimationPlayer? Player { get; private set; }
    public Skeleton3D? Skeleton { get; private set; }
    public Node3D? Body { get; private set; }
    /// <summary>The body's underwater ghost (<c>figure.ghost</c>), made with the body, built on the first submersion.</summary>
    public World.SubmergedGhost? Ghost { get; private set; }

    // Lerp state, ground plane (x, z).
    private Vector2 _from, _to;
    private double _elapsed, _duration = 1;
    public Vector2 Shown { get; private set; }
    public Vector2 Target => _to;
    public bool Moving => _elapsed < _duration && PlannedSpeed > WalkSpeed;
    public double PlannedSpeed { get; private set; }
    public string Rule { get; set; } = "";

    public Figure(string name)
    {
        CharacterName = name;
        Name = ("Fig_" + name.Replace(' ', '_')).ValidateNodeName();
    }

    /// <summary>New server target. The first one snaps; later ones lerp in over <paramref name="duration"/> s.</summary>
    public void SetTarget(Vector2 to, double duration, bool snap)
    {
        if (snap)
        {
            _from = _to = Shown = to;
            _elapsed = _duration = 1;
            PlannedSpeed = 0;
        }
        else
        {
            _from = Shown;
            _to = to;
            _elapsed = 0;
            _duration = Math.Max(duration, 1e-3);
            PlannedSpeed = (_to - _from).Length() / _duration;
            var d = _to - _from;
            if (d.LengthSquared() > 1e-8) Rotation = new Vector3(0, Mathf.Atan2(d.X, d.Y), 0);
        }
        UpdateClip();
    }

    /// <summary>Advance the lerp; <paramref name="groundAt"/> gives the world height at (x, z).</summary>
    public void Advance(double dt, Func<double, double, double> groundAt)
    {
        bool wasMoving = Moving;
        _elapsed = Math.Min(_elapsed + dt, _duration);
        float t = (float)(_elapsed / _duration);
        Shown = _from.Lerp(_to, t);
        Position = new Vector3(Shown.X, (float)groundAt(Shown.X, Shown.Y), Shown.Y);
        if (wasMoving != Moving) UpdateClip();
    }

    /// <summary>Swap the body. The old one is freed (it owns its duplicated meshes/skeleton).</summary>
    public void SetBody(Node3D body, bool isGlb, Skeleton3D? skeleton, AnimationPlayer? player)
    {
        Ghost?.Dispose();
        Body?.QueueFree();
        Body = body;
        Ghost = new World.SubmergedGhost(body);
        IsGlb = isGlb;
        Skeleton = skeleton;
        Player = player;
        AddChild(body);
        UpdateClip();
    }

    /// <summary><c>setSubmerged(level)</c>: the ghost cut at the mirror over the figure's bed, or hidden (null = dry).</summary>
    public void SetSubmerged(double? waterLevel) => Ghost?.Set(waterLevel);

    public string WantedClip => Moving ? "walk" : "idle";

    public void UpdateClip()
    {
        if (Player is null) return;
        var want = WantedClip;
        if (!Player.HasAnimation(want)) want = Player.HasAnimation("idle") ? "idle" : "";
        if (want.Length == 0) return;   // nothing bound: bind pose
        if (Player.CurrentAnimation != want) Player.Play(want, Blend);
    }

    /// <summary>Capsule placeholder standing on the node origin.</summary>
    public static Node3D Capsule(double heightM)
    {
        float h = (float)Math.Max(heightM, 0.6);
        float r = Math.Min(0.28f, h / 4f);
        var mi = new MeshInstance3D
        {
            Name = "Placeholder",
            Mesh = new CapsuleMesh { Height = h, Radius = r },
            Position = new Vector3(0, h / 2f, 0),
            MaterialOverride = new StandardMaterial3D { AlbedoColor = new Color(0.85f, 0.45f, 0.2f), Roughness = 0.8f, DiffuseMode = BaseMaterial3D.DiffuseModeEnum.Lambert },
        };
        var root = new Node3D { Name = "Body" };
        root.AddChild(mi);
        return root;
    }
}
