using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Overview;
using Godot;

namespace AnimaNative.Figures;

/// <summary>
/// One character on the map. The node sits at the figure's FEET (the browser's NPC root) in world metres, turned to its
/// facing; its body is either the character's GLB (scaled to its height, with an AnimationPlayer carrying the WHOLE
/// retargeted clip library along its set chain, one action per kind plus the browser's synonym aliases), a fallback-pool
/// model, the portrait sprite or a capsule placeholder.
///
/// It WALKS like the browser's NPC (Task 30, npcs.ts <c>Npc</c> + figures.ts <c>Figure</c>): the 1 Hz placement writes
/// the goal (<see cref="Target"/>), the stations of a room change (<see cref="Waypoints"/>) and a guided stair climb
/// (<see cref="Ride"/>); <see cref="FigureManager"/> steps it every frame through <see cref="NpcWalk"/>. The yaw eases
/// ×10/s towards the last asked direction (<see cref="FaceTowards"/>), the clip follows the ground word
/// (<see cref="Play(string, bool, double)"/>).
/// </summary>
public partial class Figure : Node3D
{
    /// <summary>The server's answer for the model: not asked yet, a model, none (404 / no url), a transient failure.</summary>
    public enum ModelAnswer { Unknown, Ready, None, Failed }

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

    /// <summary>What the server said about this character's model (figures.ts <c>apiModels</c> + <c>firstAttemptFailed</c>).</summary>
    public ModelAnswer Api { get; set; } = ModelAnswer.Unknown;
    /// <summary>The row's <c>avatar_url</c> (the portrait picture) and whether it is the player's avatar (gold pointer).</summary>
    public string AvatarUrl { get; set; } = "";
    public bool IsAvatar { get; set; }
    /// <summary>The portrait sprite while the figure has no model at all (null otherwise).</summary>
    public Portrait? Portrait { get; private set; }
    /// <summary>The fallback-pool model the body comes from (Soldier / Xbot / Robot), null otherwise.</summary>
    public string? PoolModel { get; private set; }
    /// <summary>A pool model's own height (the manifest's), which the body is scaled to instead of the character's.</summary>
    public double? PoolHeight { get; private set; }

    /// <summary>The height the name tag anchors on (<c>tagAnchorY(figure?.height ?? null)</c>): none for a portrait.</summary>
    public double? TagHeight => Portrait is not null ? null : PoolHeight ?? HeightM;

    /// <summary>Wear the portrait sprite (no model at all).</summary>
    public void SetPortrait(Portrait portrait)
    {
        SetBody(portrait.Root, false, null, null);
        portrait.Root.Position = Vector3.Zero;   // a sprite never drops into the ground (no clip, npcs.ts' sprite branch)
        Portrait = portrait;
        PoolModel = null;
        PoolHeight = null;
    }

    /// <summary>Mark the current body as a fallback-pool model of <paramref name="height"/> m.</summary>
    public void MarkPool(string model, double height)
    {
        PoolModel = model;
        PoolHeight = height;
    }
    public AnimationPlayer? Player { get; private set; }
    public Skeleton3D? Skeleton { get; private set; }
    public Node3D? Body { get; private set; }
    /// <summary>The body's underwater ghost (<c>figure.ghost</c>), made with the body, built on the first submersion.</summary>
    public World.SubmergedGhost? Ghost { get; private set; }

    // ---- walking state (npcs.ts Npc) ---------------------------------------------------------------------------------

    /// <summary>The goal the figure walks to (<c>npc.target</c>): the placement's point, y included.</summary>
    public Vector3 Target { get; set; }
    /// <summary>The stations left on the way (<c>npc.waypoints</c>): doors, stair landings, lift stops.</summary>
    public List<Vector3> Waypoints { get; } = new();
    /// <summary>The guided stair climb while one runs (<c>npc.ride</c>, stairs.ts <c>StairRide</c>); null = none.</summary>
    public Scene.StairRide? Ride { get; set; }
    /// <summary>The ground pace of the next step (<c>npc.pace</c>): 1 for every figure the server drives.</summary>
    public double Pace { get; set; } = 1;
    /// <summary>The payload says the character is under way (<c>npc.travelling</c>): it walks without the run boost.</summary>
    public bool Travelling { get; set; }
    /// <summary>The last frame moved the figure (<c>plan.moving</c>) and, moving, ran.</summary>
    public bool Moving { get; private set; }
    public bool Running { get; private set; }
    /// <summary>The ground word the last frame stood on (the movement type: walk_run / walk / swim / crawl).</summary>
    public string Movement { get; private set; } = FigureClips.WalkRun;
    /// <summary>The body's drop under the root (the ground's sink while the ground names the clip, figures.ts <c>setClipDrop</c>).</summary>
    public double Drop { get; private set; }
    public string Rule { get; set; } = "";
    /// <summary>The standing facing (world direction, y ignored): a seat's marker or the movement target; null = none.</summary>
    public Vector3? Face { get; set; }
    /// <summary>A seat's lean in degrees (<c>setLean(tilt, roll)</c>, Euler YXZ like the browser's root); null = upright.</summary>
    public (double Tilt, double Roll)? Lean { get; set; }
    /// <summary>The placement hides the figure (another storey, a closed interior).</summary>
    public bool Hidden { get; private set; }

    /// <summary>The root's yaw now and the yaw it eases to (figures.ts <c>root.rotation.y</c> / <c>targetYaw</c>: south, π).</summary>
    public double Yaw { get; private set; }
    public double TargetYaw { get; private set; } = Math.PI;

    public Figure(string name)
    {
        CharacterName = name;
        Name = ("Fig_" + name.Replace(' ', '_')).ValidateNodeName();
    }

    /// <summary>
    /// <c>faceTowards(dir, snap)</c>: the yaw of <paramref name="dir"/> (<see cref="NpcWalk.FacingYaw"/>; too short =
    /// nothing) becomes the target; <paramref name="snap"/> turns the body at once.
    /// </summary>
    public void FaceTowards(Vector3 dir, bool snap = false)
    {
        if (NpcWalk.FacingYaw(new Vec3(dir.X, dir.Y, dir.Z)) is not { } yaw) return;
        TargetYaw = yaw;
        if (snap) Yaw = yaw;
        ApplyRotation();
    }

    /// <summary>The per-frame turn (figures.ts <c>update</c>): the shortest way, eased ×10/s.</summary>
    public void TickYaw(double dt)
    {
        Yaw = NpcWalk.EaseYaw(Yaw, TargetYaw, dt);
        ApplyRotation();
    }

    /// <summary>
    /// Put the figure at <paramref name="at"/> (a snap: the first placement, a view change) — stations and climb dropped,
    /// goal = the point (npcs.ts <c>update</c>'s <c>st.snap</c> branch).
    /// </summary>
    public void SnapTo(Vector3 at)
    {
        Position = at;
        Target = at;
        Waypoints.Clear();
        Ride = null;
    }

    /// <summary>The frame's motion outcome (the manager's step): moving, running, the ground word.</summary>
    public void SetMotion(bool moving, bool running, string movement)
    {
        Moving = moving;
        Running = moving && running;
        Movement = movement;
    }

    /// <summary>
    /// The root's rotation: the eased yaw, and the seat's lean as X (tilt) and Z (roll) in Godot's default Euler order
    /// YXZ — the browser's <c>rotation.order = 'YXZ'</c>.
    /// </summary>
    public void ApplyRotation()
    {
        var lean = Lean ?? (0, 0);
        Rotation = new Vector3((float)(lean.Tilt * Math.PI / 180), (float)Yaw, (float)(lean.Roll * Math.PI / 180));
    }

    /// <summary>Show or hide the figure for the placement (<c>npc.root.visible = !st.hidden</c>).</summary>
    public void SetHidden(bool hidden)
    {
        Hidden = hidden;
        Visible = !hidden;
    }

    /// <summary>Swap the body. The old one is freed (it owns its duplicated meshes/skeleton).</summary>
    /// <param name="clipKinds">the kinds the player's library holds, in bind order (null without a player).</param>
    public void SetBody(Node3D body, bool isGlb, Skeleton3D? skeleton, AnimationPlayer? player,
                        IReadOnlyList<string>? clipKinds = null)
    {
        Ghost?.Dispose();
        Body?.QueueFree();
        Body = body;
        Portrait = null;
        PoolModel = null;
        PoolHeight = null;
        Ghost = new World.SubmergedGhost(body);
        IsGlb = isGlb;
        Skeleton = skeleton;
        Player = player;
        _clipKinds = player is null ? Array.Empty<string>() : clipKinds ?? Array.Empty<string>();
        CurrentKind = CurrentClip = "";
        CurrentPace = 1;
        _terrainClip = false;
        _sink = 0;
        Drop = 0;
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
    /// What the figure asked for last (<c>play(kind, terrainClip, sink)</c> of the manager's frame; "" = the standing
    /// pose) — a new body plays it again at once.
    /// </summary>
    public (string Kind, bool TerrainClip, double Sink) WantedClip { get; private set; } = ("", false, 0);

    /// <summary>Ask for the wanted clip again (<see cref="Play(string, bool, double)"/> of <see cref="WantedClip"/>).</summary>
    public void UpdateClip() => Play(WantedClip.Kind, WantedClip.TerrainClip, WantedClip.Sink);

    /// <summary>Forget what plays and ask again (after something drove the player directly, e.g. a check).</summary>
    public void Replay()
    {
        CurrentKind = CurrentClip = "";
        UpdateClip();
    }

    private bool _terrainClip;
    private double _sink;

    /// <summary>
    /// <c>Figure.play(kind, terrainClip, sink)</c> without the bridges (Task 31): the kind lower-cased (empty = the
    /// standing pose); nothing changes when kind, gate and sink were asked for already; the body DROPS by the ground's
    /// sink while the ground names the clip (<c>setClipDrop(clipGroundOffset·scale + sink)</c> — the measured clip
    /// ground offset is Task 31's, 0 until then); <c>resolveClipKind</c> over the bound actions, else the first
    /// action; the stand-in pace (<see cref="ClipLibraryRules.StandInPace"/>); the action's own loop flag (baked into
    /// its Animation: a one-shot holds its last frame — Godot's <c>LOOP_NONE</c> stops there); a crossfade of
    /// <see cref="ClipLibraryRules.CrossfadeS"/> from the start of the clip.
    /// </summary>
    public void Play(string rawKind, bool terrainClip = false, double sink = 0)
    {
        WantedClip = (rawKind, terrainClip, sink);
        var kind = (rawKind.Length > 0 ? rawKind : FigureClips.PoseKind(FigureClips.Standing, Poses)).ToLowerInvariant();
        double sinkM = terrainClip && double.IsFinite(sink) && sink > 0 ? sink : 0;
        if (kind == CurrentKind && terrainClip == _terrainClip && sinkM == _sink) return;
        _terrainClip = terrainClip;
        _sink = sinkM;
        SetDrop(terrainClip ? sinkM : 0);
        if (Player is null) return;
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

    /// <summary>figures.ts <c>setClipDrop</c>: the body hangs <paramref name="drop"/> m under the root (a portrait never drops).</summary>
    private void SetDrop(double drop)
    {
        Drop = drop;
        if (Body is { } b && Portrait is null && IsInstanceValid(b)) b.Position = new Vector3(0, (float)-drop, 0);
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
