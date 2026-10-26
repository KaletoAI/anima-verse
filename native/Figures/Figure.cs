using System;
using System.Collections.Generic;
using System.Linq;
using Godot;

namespace AnimaNative.Figures;

/// <summary>
/// One character on the map. The node sits at the figure's FEET in world
/// metres (y = world ground), turned to its walking direction; its body is
/// either the character's GLB (scaled to its height, with an AnimationPlayer
/// carrying the WHOLE retargeted clip library along its set chain, one action per
/// kind plus the browser's synonym aliases) or a capsule placeholder.
///
/// Motion between polls is still the spike's simple rule (NPC walking is Task 30): a new
/// target lerps in over the poll interval (<see cref="FigureManager.PollSeconds"/>); while
/// the planned speed exceeds <see cref="WalkSpeed"/> the walking pose's clip plays, else
/// <c>standingClipFor(activity_animation)</c> — every figure plays its activity.
/// </summary>
public partial class Figure : Node3D
{
    public const double WalkSpeed = 0.2;   // m/s

    public string CharacterName { get; }
    /// <summary>The model_sig the current body was loaded for (null = none / placeholder without a store).</summary>
    public string? LoadedSig { get; set; }
    public string? WantedSig { get; set; }
    /// <summary>The row's <c>model_rev</c> (null = absent) and the <c>model.model_rev</c> the body was loaded with (null = none).</summary>
    public string? WantedRev { get; set; }
    public string? LoadedRev { get; set; }
    public bool Loading { get; set; }
    /// <summary>A load failed transiently and a retry is scheduled (30 s, the browser's <c>setTimeout</c>).</summary>
    public bool RetryPending { get; set; }
    public double HeightM { get; set; } = FigureManager.DefaultHeightM;
    /// <summary>The character's set chain (<c>animation_sets</c>, the last non-empty one, like <c>setCharacterSets</c>).</summary>
    public IReadOnlyList<string> Sets { get; set; } = Array.Empty<string>();
    /// <summary>The wanted distance tier (view state) and the tier/URL of the body on screen.</summary>
    public FigureTier WantedTier { get; set; } = FigureTier.Full;
    public FigureTier LoadedTier { get; set; } = FigureTier.Full;
    public string? LoadedUrl { get; set; }
    /// <summary>Library kind → the set its file came from (the set chain's choice), for the check and the log.</summary>
    public IReadOnlyDictionary<string, string> ClipSets { get; set; } = new Dictionary<string, string>();
    /// <summary>Keys of the retargeted clips this figure's template carries, and their estimated memory (keys × <see cref="FigureManager.KeyBytes"/>).</summary>
    public long ClipKeys { get; set; }
    public long ClipBytes { get; set; }
    /// <summary>Clip tracks bound on this figure's skeleton (every kind of its library).</summary>
    public int BoundTracks { get; set; }
    /// <summary>Library kinds this humanoid figure could not bind (<c>missingClipKinds</c>) — it plays a stand-in.</summary>
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
    /// <param name="clipKinds">the kinds the player's library holds, in bind order (null without a player).</param>
    public void SetBody(Node3D body, bool isGlb, Skeleton3D? skeleton, AnimationPlayer? player,
                        IReadOnlyList<string>? clipKinds = null)
    {
        Ghost?.Dispose();
        Body?.QueueFree();
        Body = body;
        Ghost = new World.SubmergedGhost(body);
        IsGlb = isGlb;
        Skeleton = skeleton;
        Player = player;
        _clipKinds = player is null ? Array.Empty<string>() : clipKinds ?? Array.Empty<string>();
        CurrentKind = CurrentClip = "";
        CurrentPace = 1;
        AddChild(body);
        UpdateClip();
    }

    /// <summary><c>setSubmerged(level)</c>: the ghost cut at the mirror over the figure's bed, or hidden (null = dry).</summary>
    public void SetSubmerged(double? waterLevel) => Ghost?.Set(waterLevel);

    /// <summary>The server's movement poses the clip choice reads (the clip library's table).</summary>
    public PoseClips Poses { get; set; } = PoseClips.Default;

    /// <summary>The row's <c>activity_animation</c> (npcs.ts <c>npc.animation</c>): what a STANDING figure plays.</summary>
    public string Activity { get; set; } = "";

    /// <summary>The action kinds of the bound library, in action order (<c>[...this.actions.keys()]</c>).</summary>
    public IReadOnlyList<string> ClipKinds => _clipKinds;
    private IReadOnlyList<string> _clipKinds = Array.Empty<string>();

    /// <summary>The kind last asked for (<c>currentKind</c>), the action that plays it (<c>""</c> = bind pose) and its pace.</summary>
    public string CurrentKind { get; private set; } = "";
    public string CurrentClip { get; private set; } = "";
    public double CurrentPace { get; private set; } = 1;

    /// <summary>
    /// The kind this figure asks for — npcs.ts' one clip decision through <see cref="FigureClips"/>: moving =
    /// <c>moveClip(walk_run, walking)</c>, standing = <c>standingClipFor(activity_animation, idleClip(walk_run))</c>.
    /// The ground word (swim/crawl) and the run rule arrive with NPC walking (Task 30); until then the ground is dry.
    /// </summary>
    public string WantedClip => Moving ? ClipLibrary.MovingKindOf(Poses)
        : FigureClips.StandingClipFor(Activity, FigureClips.IdleClip(FigureClips.WalkRun, Poses), Poses);

    /// <summary>Ask for the wanted clip (<see cref="Play"/> of <see cref="WantedClip"/>).</summary>
    public void UpdateClip() => Play(WantedClip);

    /// <summary>Forget what plays and ask again (after something drove the player directly, e.g. a check).</summary>
    public void Replay()
    {
        CurrentKind = CurrentClip = "";
        UpdateClip();
    }

    /// <summary>
    /// <c>Figure.play(kind)</c> without the bridges (Task 31): the kind lower-cased (empty = the standing pose);
    /// nothing changes when it was asked for already; <c>resolveClipKind</c> over the bound actions, else the
    /// first action; the stand-in pace (<see cref="ClipLibraryRules.StandInPace"/>); the action's own loop flag
    /// (baked into its Animation: a one-shot holds its last frame — Godot's <c>LOOP_NONE</c> stops there);
    /// a crossfade of <see cref="ClipLibraryRules.CrossfadeS"/> from the start of the clip.
    /// </summary>
    public void Play(string rawKind)
    {
        var kind = (rawKind.Length > 0 ? rawKind : FigureClips.PoseKind(FigureClips.Standing, Poses)).ToLowerInvariant();
        if (Player is null || kind == CurrentKind) return;
        var chosen = FigureClips.ResolveClipKind(kind, _clipKinds, Poses);
        var resolved = chosen.Length > 0 ? chosen : _clipKinds.FirstOrDefault() ?? "";
        double pace = ClipLibraryRules.StandInPace(kind, chosen);
        CurrentKind = kind;
        if (resolved.Length == 0 || !Player.HasAnimation(resolved)) return;   // nothing bound: bind pose
        CurrentPace = pace;
        Player.SpeedScale = (float)pace;
        // The same action keeps playing (a stand-in for another kind): only its pace changes.
        if (resolved == CurrentClip) return;
        // A different action starts from its first frame (the browser's reset().fadeIn(0.25)).
        Player.Play(resolved, ClipLibraryRules.CrossfadeS);
        CurrentClip = resolved;
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
