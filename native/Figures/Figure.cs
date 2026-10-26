using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Overview;
using AnimaNative.Scatter;
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
    /// <summary>
    /// A spot kept after a stand-up (npcs.ts <c>npc.settle</c>, standSettle.ts): the server point it was taken against
    /// and the figure's offset from it; null = the figure walks to the server's point.
    /// </summary>
    public (P2 Server, P2 Offset)? Settle { get; set; }
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
    /// nothing) becomes the target; <paramref name="snap"/> turns the body at once. While a holding bridge runs
    /// (<see cref="HoldsFacing"/>) the turn is only remembered — snap included — and eased into once it has ended.
    /// </summary>
    public void FaceTowards(Vector3 dir, bool snap = false)
    {
        if (NpcWalk.FacingYaw(new Vec3(dir.X, dir.Y, dir.Z)) is not { } yaw) return;
        if (HoldsFacing)
        {
            _pendingYaw = yaw;
            return;
        }
        TargetYaw = yaw;
        if (snap) Yaw = yaw;
        ApplyRotation();
    }

    /// <summary><c>setYaw(yaw)</c>: the root's absolute target yaw; only remembered while a holding bridge runs.</summary>
    public void SetYaw(double yaw)
    {
        if (HoldsFacing)
        {
            _pendingYaw = yaw;
            return;
        }
        TargetYaw = yaw;
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
        ResetSecondaryMotion();   // npcs.ts: every placement snap / arrival / first sync resets the secondary motion
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
    /// <param name="bindOffset">the Figure constructor's anchoring (<see cref="FigureBind.Offset"/>: centred on the bind box
    /// in XZ, its bottom on 0) in the root frame; null = the body already stands on its origin (capsule, portrait).</param>
    public void SetBody(Node3D body, bool isGlb, Skeleton3D? skeleton, AnimationPlayer? player,
                        IReadOnlyList<string>? clipKinds = null, V3? bindOffset = null)
    {
        Secondary?.Release();
        Secondary = null;
        _secondaryPlaced = false;
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
        ResetBridges();
        var bind = bindOffset ?? V3.Zero;
        _travelBase = new P2(bind.X, bind.Z);
        _groundY = bind.Y;
        AddChild(body);
        ApplyBody();
        UpdateClip();
        // figures.ts Figure constructor: createSecondaryMotion(THREE, this.root, this.motion, model.template).
        _secondaryRev = Motion?.Rev;
        if (isGlb && skeleton is not null) Secondary = SecondaryMotionModifier.TryCreate(body, skeleton, Motion);
    }

    // ---- secondary motion (figures.ts: secondary, secondaryRev, secondaryPlaced, resetSecondaryMotion) -------------

    /// <summary>The character's motion payload (worldmap <c>motion</c>, else model3d <c>motion</c>); null = none yet.</summary>
    public MotionPayload? Motion { get; set; }
    /// <summary>The secondary motion of the body (null = no extension bone of the payload on this rig, or no rig).</summary>
    public SecondaryMotionModifier? Secondary { get; private set; }
    /// <summary>This frame's <c>frozen</c> (the world's <c>game_rate</c> 0; a pair at rate 0) for the secondary motion.</summary>
    public bool SecondaryFrozen { get; set; }
    /// <summary>The check steps the motion itself (<see cref="SecondaryMotionModifier.StepNow"/>).</summary>
    public bool SecondaryManual { get; set; }
    private string? _secondaryRev;
    private Vector3 _secondaryPos;
    private bool _secondaryPlaced;

    /// <summary><c>resetSecondaryMotion()</c>: the particles start over at their targets; the jump watch restarts.</summary>
    public void ResetSecondaryMotion()
    {
        Secondary?.RequestReset();
        _secondaryPlaced = false;
    }

    /// <summary>
    /// The secondary part of <c>Figure.update</c>: a new payload revision reconfigures (or builds the motion once a
    /// payload names bones this rig has), a root that moved more than 2 m since the last frame is a jump (reset), and
    /// the frame's frozen / far go to the modifier, which steps after the mixer with the real frame time.
    /// </summary>
    private void TickSecondary()
    {
        if (Skeleton is null || Body is null) return;
        var rev = Motion?.Rev;
        if (rev != _secondaryRev)
        {
            _secondaryRev = rev;
            if (Secondary is { } s) s.Configure(Motion);
            else if (IsGlb) Secondary = SecondaryMotionModifier.TryCreate(Body, Skeleton, Motion);
        }
        if (Secondary is not { } motion) return;
        var position = IsInsideTree() ? GlobalPosition : Position;
        // Safety net for owners that replace placement directly: >2 m is a jump.
        if (_secondaryPlaced && position.DistanceTo(_secondaryPos) > 2) motion.RequestReset();
        _secondaryPos = position;
        _secondaryPlaced = true;
        motion.Frozen = SecondaryFrozen;
        motion.Far = LoadedTier == FigureTier.Low;
        motion.Manual = SecondaryManual;
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

    // ---- bridges (figures.ts Figure, Task 31) ------------------------------------------------------------------------

    /// <summary>The server's <c>transition_clips</c> (the clip library's table): which bridge opens between two kinds.</summary>
    public IReadOnlyList<ClipTransition> Transitions { get; set; } = Array.Empty<ClipTransition>();
    /// <summary>Per bound Animation the fit's travel / turn / lift / ground offset (the template's, shared).</summary>
    public IReadOnlyDictionary<Animation, ClipExtras> Extras { get; set; } = new Dictionary<Animation, ClipExtras>();
    /// <summary>World metres per template unit (<c>baseScale</c>): the body node's scale.</summary>
    public double BaseScale { get; set; } = 1;
    /// <summary>
    /// The clock bridges are timed by, seconds (the browser's <c>performance.now()</c>): the manager's accumulated frame
    /// time, so a headless check runs the same rules on simulated frames. Default: the engine's monotonic clock.
    /// </summary>
    public Func<double> Clock { get; set; } = () => Time.GetTicksUsec() / 1e6;

    /// <summary>One bridge as it played: the clip, its own clock (three's <c>action.time</c>, LoopOnce + clamp), its extras
    /// and when the next clip started fading it out (its weight falls over the crossfade from there).</summary>
    private sealed class BridgeRun
    {
        public required string Kind { get; init; }
        public required double Length { get; init; }
        public ClipExtras? Extras { get; init; }
        public double Time;
        public double? FadeOutAt;
    }

    /// <summary>The running bridge — the gate (<c>transition</c>); null when none runs.</summary>
    private BridgeRun? _transition;
    /// <summary>The bridge whose clip is on screen (<c>current</c> while a bridge plays); null once another clip plays.</summary>
    private BridgeRun? _currentRun;
    /// <summary>Every bridge still fading (its clock and weight are read by the lift until it is gone).</summary>
    private readonly List<BridgeRun> _runs = new();
    private double _bridgeUntil, _bridgeAccel, _bridgeStart;
    /// <summary>The figure's own animation clock (three's mixer time): advanced by every <see cref="UpdateFigure"/>.</summary>
    private double _animTime;
    private double? _pendingYaw;
    // Root motion of a holding bridge (figures.ts `travelBase` … `holding`): the instance follows the travel, the
    // owner takes it over (`TakeTravel`). The base is where the bind anchoring put the body in XZ (centred on its box).
    private P2 _travelBase = new(0, 0);
    /// <summary>figures.ts <c>groundY</c>: the body's height that puts its lowest bind point on the root (feet on y = 0).</summary>
    private double _groundY;
    private RootPath? _travelPath;
    private BridgeRun? _travelAction;
    private P2 _travelOrigin = new(0, 0);
    private P2 _heldTravel = new(0, 0);
    private bool _holding;
    // The turn handed from the hips to the root (figures.ts `turn` … `turnNow`).
    private RootTurn? _turn;
    private BridgeRun? _turnAction;
    private double _turnBase, _turnNow;
    private P2 _turnPivot = new(0, 0);
    // The height of a holding bridge (figures.ts `liftAction` … `liftCarryAt`).
    private BridgeRun? _liftAction;
    private BridgeLiftSpec? _liftSpec;
    private double _liftStart, _lift, _liftCarry, _liftCarryAt;

    /// <summary>The body's bind anchoring in the root frame (x, z = the centring base, y = <c>groundY</c>), for the check.</summary>
    public V3 BindOffset => new(_travelBase.X, _groundY, _travelBase.Z);
    /// <summary>The lift applied right now (metres over the root), for the check.</summary>
    public double Lift => _lift;
    /// <summary>The instance's horizontal offset from its base in the root frame (the held travel, turned back by ψ).</summary>
    public P2 BodyOffset => InstanceOffset();
    /// <summary>The ψ the instance is turned back by right now (0 = none).</summary>
    public double TurnNow => _turnNow;

    private Animation? AnimOf(string kind) => Player is { } p && p.HasAnimation(kind) ? p.GetAnimation(kind) : null;
    private ClipExtras? ExtrasOf(string kind) => AnimOf(kind) is { } a && Extras.TryGetValue(a, out var x) ? x : null;

    /// <summary><c>clipGroundOffset(clip)</c> of a bound kind in world metres (× <see cref="BaseScale"/>), 0 when unmeasured.</summary>
    public double GroundOffsetM(string kind) => (ExtrasOf(kind)?.GroundOffset ?? 0) * BaseScale;

    private bool HasAction(string kind) => _clipKinds.Contains(kind) && Player is { } p && p.HasAnimation(kind);

    private bool OwnsBody(BridgeRun? run) => run is not null && _transition == run && _currentRun == run;

    /// <summary>
    /// <c>Figure.play(kind, terrainClip, sink)</c>: the kind lower-cased (empty = the standing pose). A running bridge is
    /// never cut. A transition rule (<see cref="FigureClips.Transition"/>: exact &gt; exit &gt; enter) whose bridge clip
    /// this rig HAS opens it: one-shot, faded in over <see cref="BridgeLift.BridgeFadeInS"/>, deadline = its length +
    /// 0.5 s; a holding rule (<c>accel</c> ≤ 0) takes the facing over and carries the figure along the clip's travel and
    /// turn. Otherwise as before: nothing changes when kind, gate and sink were asked for already; the body drops by
    /// <c>clipGroundOffset·baseScale + sink</c> while the ground names the clip; <c>resolveClipKind</c> over the bound
    /// actions, else the first; the stand-in pace; the action's own loop flag; a crossfade of
    /// <see cref="ClipLibraryRules.CrossfadeS"/> from the start of the clip.
    /// </summary>
    public void Play(string rawKind, bool terrainClip = false, double sink = 0)
    {
        WantedClip = (rawKind, terrainClip, sink);
        var kind = (rawKind.Length > 0 ? rawKind : FigureClips.PoseKind(FigureClips.Standing, Poses)).ToLowerInvariant();
        // A bridge is running: let it finish; the frame after it asks again.
        if (Bridging) return;
        var rule = FigureClips.Transition(CurrentKind, kind, Transitions);
        var via = rule?.Kind ?? "";
        if (rule is not null && via.Length > 0 && via != kind && HasAction(via))
        {
            StartBridge(via, rule.Accel);
            return;
        }
        double sinkM = terrainClip && double.IsFinite(sink) && sink > 0 ? sink : 0;
        if (kind == CurrentKind && terrainClip == _terrainClip && sinkM == _sink) return;
        _terrainClip = terrainClip;
        _sink = sinkM;
        if (Player is null)
        {
            SetClipDrop(terrainClip ? sinkM : 0);
            CurrentKind = kind;
            return;
        }
        var chosen = FigureClips.ResolveClipKind(kind, _clipKinds, Poses);
        var resolved = chosen.Length > 0 ? chosen : _clipKinds.FirstOrDefault() ?? "";
        // The drop belongs to the clip that ACTUALLY plays; the ground's sink comes on top, in world metres.
        SetClipDrop(terrainClip && resolved.Length > 0 ? GroundOffsetM(resolved) + sinkM : terrainClip ? sinkM : 0);
        double pace = ClipLibraryRules.StandInPace(kind, chosen);
        CurrentKind = kind;
        if (resolved.Length == 0 || !Player.HasAnimation(resolved)) return;   // nothing bound: bind pose
        CurrentPace = pace;
        Player.SpeedScale = (float)pace;
        // The same action keeps playing (a stand-in for another kind): only its pace changes.
        if (resolved == CurrentClip) return;
        // A different action starts from its first frame (the browser's reset().fadeIn(0.25)); a bridge on screen fades.
        if (_currentRun is { } run) run.FadeOutAt ??= _animTime;
        _currentRun = null;
        Player.Play(resolved, ClipLibraryRules.CrossfadeS);
        CurrentClip = resolved;
    }

    // ---- pair clips (figures.ts playPair, npcs.ts PairPlay, Task 32) -------------------------------------------------

    /// <summary>The running pair interaction (npcs.ts <c>npc.interaction</c>): placement AND clip come from it; null = none.</summary>
    public PairPlay? Pair { get; set; }

    /// <summary>
    /// <c>playPair(clipName, t, frozen, loop)</c>: play the half of a PAIR clip at the clip time <paramref name="t"/> (REAL
    /// seconds, the phase <see cref="PairClip.Phase"/> derived). The pair takes the body over: a running bridge ends HERE
    /// (its clip fades out), the ground drop is 0. The time is wrapped (cycle) or clamped a millisecond short of the end
    /// (one-shot) against the length the loaded clip has; a new half starts with the 0.25 s fade at that time, the same
    /// half re-seeks only when its own time drifted more than <see cref="PairClip.ResyncS"/> (measured on the circle for
    /// a cycle). <paramref name="frozen"/> stops the player where it stands. False when the half is not bound on this rig.
    /// </summary>
    public bool PlayPair(string clipName, double t, bool frozen, bool loop)
    {
        if (Player is not { } p || !HasAction(clipName)) return false;
        ReleaseBridge();
        SetClipDrop(0);
        _terrainClip = false;
        _sink = 0;
        var anim = p.GetAnimation(clipName);
        double duration = anim.Length > 0 ? anim.Length : 1;
        double clipT = Math.Max(t, 0);
        double want = loop ? clipT % duration : Math.Min(clipT, duration - 1e-3);
        if (CurrentClip != clipName)
        {
            // three sets the loop on the ACTION; Godot keeps it on the Animation, which the template's figures share —
            // every one of them reads the same listing / interaction flag for this half.
            var mode = loop ? Animation.LoopModeEnum.Linear : Animation.LoopModeEnum.None;
            if (anim.LoopMode != mode) anim.LoopMode = mode;
            if (_currentRun is { } run) run.FadeOutAt ??= _animTime;
            _currentRun = null;
            p.Play(clipName, ClipLibraryRules.CrossfadeS);
            p.Seek(want, false);
            CurrentKind = clipName;
            CurrentClip = clipName;
        }
        else
        {
            double raw = Math.Abs(p.CurrentAnimationPosition - want);
            if ((loop ? Math.Min(raw, duration - raw) : raw) > PairClip.ResyncS)
            {
                // A one-shot that ran out stopped (clampWhenFinished holds its last frame): restart it for the seek.
                if (!p.IsPlaying()) p.Play(clipName);
                p.Seek(want, false);
            }
        }
        CurrentPace = 1;
        p.SpeedScale = frozen ? 0 : 1;
        return true;
    }

    /// <summary>The time the figure's player stands at (the action's own clock), for the check; NaN without a clip.</summary>
    public double ClipTime => Player is { } p && CurrentClip.Length > 0 ? p.CurrentAnimationPosition : double.NaN;

    /// <summary>The bridge branch of <c>play</c>: the gate, the deadline, the held facing, the travel and the turn.</summary>
    private void StartBridge(string via, double accel)
    {
        var anim = Player!.GetAnimation(via);
        var run = new BridgeRun { Kind = via, Length = anim.Length, Extras = Extras.TryGetValue(anim, out var x) ? x : null };
        _transition = run;
        _runs.Add(run);
        double now = Clock();
        // Half a second of slack over the clip: the crossfade at each end, and a frame loop that is never on time.
        _bridgeUntil = now + anim.Length + 0.5;
        _bridgeAccel = accel;
        _bridgeStart = now;
        // A bridge that HOLDS the figure holds all of it: a turn ordered in this very frame is taken back.
        if (accel <= 0)
        {
            TargetYaw = Yaw;
            _pendingYaw = null;
        }
        // Rule 5 of the root motion: a travel still held means its owner never took it — folded in, never dropped.
        if (_holding)
        {
            GD.Print($"[figures] {CharacterName}: bridge {CurrentKind} -> {via} starts while a bridge travel is still held — folding it in");
            _travelOrigin = InstanceOffset();
            _heldTravel = _travelOrigin;
        }
        // Rule 1: only a HOLDING bridge carries the figure, and only along a clip that brought a travel path.
        _travelPath = accel <= 0 ? run.Extras?.Path : null;
        _travelAction = _travelPath is not null ? run : null;
        StartTurn(_travelPath is not null ? run.Extras?.Turn : null, run);
        GD.Print($"[figures] {CharacterName}: bridge {CurrentKind} -> {via}");
        if (_currentRun is { } prev) prev.FadeOutAt ??= _animTime;
        if (Player.CurrentAnimation == via) Player.Seek(0, false);
        Player.SpeedScale = 1;
        Player.Play(via, BridgeLift.BridgeFadeInS);
        _currentRun = run;
        CurrentKind = via;
        CurrentClip = via;
        CurrentPace = 1;
    }

    /// <summary>
    /// <c>bridging</c>: a bridge clip is running — false again the moment it ends, and after its deadline even if its
    /// end never came (a gate must not wait for ever).
    /// </summary>
    public bool Bridging
    {
        get
        {
            if (_transition is null) return false;
            if (Clock() > _bridgeUntil)
            {
                ReleaseBridge();
                return false;
            }
            return true;
        }
    }

    /// <summary>THE one way a bridge ends: the gate opens; travel, turn, facing and height let go in the same frame.</summary>
    private void ReleaseBridge()
    {
        _transition = null;
        _bridgeUntil = 0;
        _bridgeAccel = 0;
    }

    /// <summary><c>cancelBridge</c>: give the running bridge up; what plays instead is the next frame's business.</summary>
    public void CancelBridge()
    {
        if (_transition is null) return;
        ReleaseBridge();
    }

    /// <summary><c>holdsFacing</c>: a HOLDING bridge plays — faceTowards/setYaw only remember what was asked for.</summary>
    public bool HoldsFacing => Bridging && _bridgeAccel <= 0 && OwnsBody(_transition);

    /// <summary><c>bridgePace</c>: how fast the running bridge lets the figure be (0 while none runs, 0 for a holding rule).</summary>
    public double BridgePace => Bridging ? FigureClips.BridgePace(_bridgeAccel, Clock() - _bridgeStart) : 0;

    /// <summary><c>paceLimit</c>: 1 while no bridge runs, the running bridge's pace while one does.</summary>
    public double PaceLimit => Bridging ? BridgePace : 1;

    /// <summary>
    /// <c>paceLimitFor(kind)</c>: the running bridge's pace, or the pace of the bridge that switching to
    /// <paramref name="kind"/> WOULD open (the very rule <see cref="Play"/> applies), or 1 when neither holds it.
    /// </summary>
    public double PaceLimitFor(string kind)
    {
        if (Bridging) return BridgePace;
        var k = (kind ?? "").ToLowerInvariant();
        var rule = FigureClips.Transition(CurrentKind, k, Transitions);
        var via = rule?.Kind ?? "";
        if (rule is null || via.Length == 0 || via == k || !HasAction(via)) return 1;
        return FigureClips.BridgePace(rule.Accel, 0);
    }

    /// <summary><c>holdsTravel</c>: a bridge's travel the owner has not taken yet (during the bridge and after it).</summary>
    public bool HoldsTravel => _holding;

    /// <summary><c>holdsHeight</c>: from <see cref="BeginBridgeLift"/> until that bridge ends the height is the lift's.</summary>
    public bool HoldsHeight => Bridging && OwnsBody(_liftAction);

    /// <summary>
    /// <c>takeTravel()</c>: the offset of the last root-motion bridge in WORLD metres (turned by the root's yaw) — the
    /// owner moves its root by exactly this — and the instance back on its base; null when nothing is held. With a
    /// turn still running, the rest of it goes on about the pivot and is held again for the next hand-over.
    /// </summary>
    public P2? TakeTravel()
    {
        if (!_holding) return null;
        var o = InstanceOffset();
        var (wx, wz) = BridgeTravel.ToWorld(o.X, o.Z, Yaw);
        _holding = false;
        _heldTravel = new P2(0, 0);
        _travelOrigin = new P2(0, 0);
        _travelPath = null;
        _travelAction = null;
        if (_turnAction is not null)
        {
            var p = _turnPivot;
            var back = BridgeTravel.ToWorld(_travelBase.X + p.X, _travelBase.Z + p.Z, _turnNow);
            _travelOrigin = new P2(back.X - p.X - _travelBase.X, back.Z - p.Z - _travelBase.Z);
            _heldTravel = _travelOrigin;
        }
        else
        {
            _turnNow = 0;
            _turnPivot = new P2(0, 0);
        }
        ApplyBody();
        return new P2(wx, wz);
    }

    /// <summary>Begin the turn of the bridge that opens now, or none; the pivot is the hips' rest point × the body scale.</summary>
    private void StartTurn(RootTurn? turn, BridgeRun run)
    {
        _turn = turn;
        _turnAction = turn is not null ? run : null;
        _turnBase = Yaw;
        _turnNow = 0;
        _turnPivot = new P2(0, 0);
        if (turn is not null && run.Extras?.PivotFrame is { } pf) _turnPivot = new P2(pf.X * BaseScale, pf.Z * BaseScale);
    }

    /// <summary>The instance's offset from its base in the root frame now: the held travel turned back by ψ about the pivot.</summary>
    private P2 InstanceOffset()
    {
        var p = _turnPivot;
        var (x, z) = BridgeTravel.ToWorld(_travelBase.X + _heldTravel.X + p.X, _travelBase.Z + _heldTravel.Z + p.Z, -_turnNow);
        return new P2(x - p.X - _travelBase.X, z - p.Z - _travelBase.Z);
    }

    /// <summary>
    /// <c>beginBridgeLift(startLiftM)</c>: the owner has just put the root of a figure whose HOLDING bridge started this
    /// frame onto the new floor, <paramref name="startLiftM"/> lower; the figure takes that height over (plus a lift
    /// still in force). Only for a holding bridge measured on this rig; false = the owner keeps the height.
    /// </summary>
    public bool BeginBridgeLift(double startLiftM)
    {
        var bridge = _transition;
        if (bridge is null || !Bridging || _bridgeAccel > 0 || !OwnsBody(bridge)) return false;
        if (bridge.Extras?.Lift is not { } spec || !double.IsFinite(startLiftM)) return false;
        _liftAction = bridge;
        _liftSpec = spec;
        _liftStart = startLiftM + _lift;
        _liftCarry = 0;
        _lift = _liftStart;
        ApplyBody();
        return true;
    }

    /// <summary>
    /// <c>shiftBridgeLift(dropM)</c>: the owner's floor changed while the figure holds the height; the root went
    /// <paramref name="dropM"/> lower and the difference is handed over again, the part the ramp no longer carries
    /// fading out over LIFT_RAMP_S. False (nothing done) when no lift is held.
    /// </summary>
    public bool ShiftBridgeLift(double dropM)
    {
        var action = _liftAction;
        if (action is null || _liftSpec is null || !HoldsHeight || !double.IsFinite(dropM)) return false;
        double want = _lift + dropM;
        _liftStart += dropM;
        _liftCarryAt = action.Time;
        _liftCarry = 0;
        _liftCarry = want - LiftValue(action.Time);
        _lift = want;
        ApplyBody();
        return true;
    }

    private double LiftValue(double t)
        => BridgeLift.LiftAt(t, _liftStart, _liftSpec!.EndLift * BaseScale, _liftSpec.FirstContactS)
           + BridgeLift.FadeCarry(_liftCarry, t - _liftCarryAt);

    /// <summary>figures.ts <c>setClipDrop</c>: the clip's ground offset (+ the sink) the body hangs under the root.</summary>
    private void SetClipDrop(double drop)
    {
        if (Math.Abs(drop - Drop) < 1e-4) return;
        Drop = drop;
        ApplyBody();
    }

    /// <summary>The body: <c>(base + offset).xz</c>, height <c>groundY − drop + lift</c> (a portrait never drops).</summary>
    private void ApplyBody()
    {
        if (Body is not { } b || !IsInstanceValid(b)) return;
        if (Portrait is not null)
        {
            b.Position = Vector3.Zero;
            return;
        }
        var o = InstanceOffset();
        b.Position = new Vector3((float)(_travelBase.X + o.X), (float)(_groundY - Drop + _lift), (float)(_travelBase.Z + o.Z));
    }

    /// <summary>Forget every bridge (a new body): gate, travel, turn and lift.</summary>
    private void ResetBridges()
    {
        _transition = _currentRun = _travelAction = _turnAction = _liftAction = null;
        _runs.Clear();
        _bridgeUntil = _bridgeAccel = _bridgeStart = 0;
        _pendingYaw = null;
        _travelPath = null;
        _turn = null;
        _liftSpec = null;
        _holding = false;
        _heldTravel = _travelOrigin = _turnPivot = new P2(0, 0);
        _turnNow = _turnBase = _lift = _liftStart = _liftCarry = _liftCarryAt = 0;
    }

    private double WeightOf(BridgeRun run)
        => run.FadeOutAt is { } at ? Math.Max(0, 1 - (_animTime - at) / ClipLibraryRules.CrossfadeS) : 1;

    /// <summary>
    /// <c>Figure.update(dt)</c> for the native body: a turn remembered during a holding bridge becomes the target; the
    /// yaw eases; the animation advances (the player in manual mode, so pose and root motion stay in the same frame);
    /// a bridge that reached its end lets go; the turn ψ(t) goes onto the root and the instance is turned back about the
    /// pivot; the travel carries the instance; the lift follows the ramp, fading with the bridge's weight once it no
    /// longer owns the body.
    /// </summary>
    public void UpdateFigure(double dt)
    {
        if (_pendingYaw is { } py && !HoldsFacing)
        {
            TargetYaw = py;
            _pendingYaw = null;
        }
        Yaw = NpcWalk.EaseYaw(Yaw, TargetYaw, dt);
        _animTime += dt;
        Player?.Advance(dt);
        foreach (var run in _runs) run.Time = Math.Min(run.Length, run.Time + dt);
        if (_transition is { } tr && tr.Time >= tr.Length) ReleaseBridge();   // the mixer's "finished"
        bool turning = _turn is not null && _turnAction is not null;
        if (turning)
        {
            _turnNow = BridgeTravel.TurnAt(_turn!, _turnAction!.Time);
            Yaw = _turnBase + _turnNow;
            TargetYaw = Yaw;
            _holding = true;
            if (!OwnsBody(_turnAction))
            {
                _turn = null;
                _turnAction = null;
            }
        }
        bool travelling = _travelPath is not null && _travelAction is not null;
        if (travelling)
        {
            var (tx, tz) = BridgeTravel.TravelAt(_travelPath!, _travelAction!.Time);
            _heldTravel = new P2(_travelOrigin.X + tx * BaseScale, _travelOrigin.Z + tz * BaseScale);
            _holding = true;
            if (!OwnsBody(_travelAction))
            {
                _travelPath = null;
                _travelAction = null;
            }
        }
        if (_liftAction is { } la && _liftSpec is not null)
        {
            double lift = LiftValue(la.Time);
            if (OwnsBody(la)) _lift = lift;
            else
            {
                double weight = WeightOf(la);
                if (weight > 1e-4) _lift = lift * weight;
                else
                {
                    _lift = 0;
                    _liftCarry = 0;
                    _liftAction = null;
                    _liftSpec = null;
                }
            }
        }
        _runs.RemoveAll(r => r != _transition && r != _currentRun && r != _liftAction && r != _turnAction && r != _travelAction
                             && WeightOf(r) <= 0);
        ApplyRotation();
        ApplyBody();
        TickSecondary();
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
