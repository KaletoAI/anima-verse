using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Nav;
using AnimaNative.Orders;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Figures;

/// <summary>
/// Plan E3 Tasks 5/6: the bridge between the motion orders (§ A11b) and the figures. Every figure that appears in an
/// order's <c>actors</c> gets one <see cref="OrderPlayer"/>; the worldmap rows (field <c>order</c>, root
/// <c>motion_now</c>/<c>order_seq</c>) and the push topic <c>orders</c> (<see cref="PullOrdersAsync"/>) feed it through
/// <see cref="AdoptOrders"/>. The player owns the figure from <c>exit</c> through <c>walk</c> and <c>entry</c> up to the
/// loop's start pose (<see cref="TickOrder"/>, the first branch of <c>StepFigure</c>); from <c>loop_started</c> on the
/// order only means "no re-placement" (decision 18): pose, pair clip, solo scene clock, finale and phase pose come from
/// the row as before. A row without <c>order</c> ends a server order covered by the root <c>order_seq</c> with a
/// <see cref="OrderEndBlendS"/> blend into the rest placement (decision 6). The avatar plays its orders too (Task 6):
/// a click starts a local order (<see cref="StartLocalOrder"/>) that the answer's order adopts in place; its link rides
/// ask the server for the room (<see cref="AvatarLinkRide"/>). The avatar walks its furniture orders itself (Task 7): at
/// its access it reports the arrival (<see cref="IWorldSource.PostOrderArrivedAsync"/>) and plays the entry without
/// waiting for the answer; a refusal aborts the order (<see cref="OrderPlayer.Refuse"/>). A ground click inside a building
/// is a local <c>walk</c> order of the avatar on the click planner's path (<see cref="StartClickWalk"/>, Task 10).
/// </summary>
public partial class FigureManager
{
    /// <summary>The blend from an ended order into the row's rest placement (decision 6).</summary>
    public const double OrderEndBlendS = 0.3;

    private readonly Dictionary<string, OrderPlayer> _orderPlayers = new(StringComparer.Ordinal);
    private readonly Dictionary<string, (Order Order, double MotionNow, double At)> _parkedOrders = new(StringComparer.Ordinal);
    private readonly Dictionary<string, (Vector3 From, double At)> _orderBlends = new(StringComparer.Ordinal);
    private readonly Dictionary<string, string> _orderLoopShown = new(StringComparer.Ordinal);
    /// <summary>
    /// A server walk let go at its end (<see cref="EndedServerWalk"/>): order id and the newest revision seen. The row
    /// carries the ended order for the server's tail; without this every poll there would adopt it again and keep the
    /// rows from placing the figure. Forgotten once a row comes without that order.
    /// </summary>
    private readonly Dictionary<string, (string Id, long Revision)> _releasedWalks = new(StringComparer.Ordinal);
    /// <summary>
    /// The loop start held before the row carries the loop pose (E3 final review I2): order id, since when, and whether
    /// an entry bridge was held (its last frame, <see cref="Figure.HoldPropPoseAtAnchor"/>).
    /// </summary>
    private readonly Dictionary<string, (string Id, double At, bool Bridge)> _orderLoopHeld = new(StringComparer.Ordinal);
    /// <summary>The longest a loop start waits for its row (the server's flip plus poll lag lie far below it).</summary>
    public const double LoopHoldMaxS = 10;
    private readonly Dictionary<string, OrderState> _orderShownState = new(StringComparer.Ordinal);
    private readonly Dictionary<string, double> _orderExitY = new(StringComparer.Ordinal);
    private readonly Dictionary<string, (string Key, JsonObject Spec)> _orderEntrySpecs = new(StringComparer.Ordinal);
    private readonly Dictionary<string, string> _arrivalReported = new(StringComparer.Ordinal);
    private long _orderSeqSeen;
    private (double Motion, double At)? _motionSeen;
    private Task? _ordersPull;
    private bool _ordersPullAgain;

    /// <summary>The navigation of a location (id → map; null = none yet: the player walks straight).</summary>
    public Func<string, IPathProvider?>? NavOf { get; set; }

    /// <summary>
    /// The world map out in the open (<see cref="World.WorldBuilder.OutdoorNav"/>): the avoidance agents of figures whose
    /// order walks outside every location (plan E3 Task 11); null = no avoidance out there.
    /// </summary>
    public Func<LocationNav?>? OutdoorNav { get; set; }

    /// <summary>
    /// The walls of a location's storey at a height, in world xz with the body radius
    /// (<see cref="World.WorldBuilder.OrderWalls"/>): the wall clamp of an avoided order step; null = none.
    /// </summary>
    public Func<string, double, (IReadOnlyList<AnimaNative.Embody.WallSegment> Segments, double Radius)?>? OrderWallsAt { get; set; }

    /// <summary>A figure's order reached its access (event <c>arrived_access</c>; the avatar's also reports it, Task 7).</summary>
    public event Action<string, Order>? OrderArrivedAtAccess;

    /// <summary>
    /// The server's answer to the avatar's arrival report: name, the order and the refusal's reason ("" = accepted). A
    /// refusal has already aborted the order when it is still the figure's current one.
    /// </summary>
    public event Action<string, Order, string>? OrderArrivalAnswered;

    /// <summary>Every frame the bridge shows of a live order (the check records the states with it).</summary>
    public event Action<string, OrderFrame>? OrderFrameShown;

    /// <summary>An order of this figure ended (event <c>aborted</c> or <c>ended</c>): the controller hands the avatar back.</summary>
    public event Action<string>? OrderEnded;

    /// <summary>
    /// The avatar's ride over a link of its order walk, per kind (<c>stairs</c>, <c>lift</c>): the room-entry ride of
    /// <c>AvatarRoomsController</c>. Read at each ride's start (<c>ResolvedLinkRide.Begin</c>); null (no rooms controller, or the
    /// hook returns null) rides like an NPC.
    /// </summary>
    public Func<string, ILinkRide?>? AvatarLinkRide { get; set; }

    /// <summary>A server order the avatar must not play (the order of a run its click already gave up, review W3.4).</summary>
    public Func<Order, bool>? IgnoresAvatarOrder { get; set; }

    /// <summary>
    /// The server's motion clock now, as last seen (root <c>motion_now</c> of a worldmap poll or of <c>/play/orders</c>)
    /// plus the client seconds since; before any, the client clock.
    /// </summary>
    public double MotionNow => _motionSeen is { } seen ? seen.Motion + (_clock - seen.At) : _clock;

    /// <summary>The highest order <c>seq</c> seen (adopted, <c>/play/orders</c> or the worldmap's <c>order_seq</c>).</summary>
    public long OrderSeqSeen => _orderSeqSeen;

    public OrderPlayer? OrderPlayerOf(string name) => _orderPlayers.GetValueOrDefault(name);

    /// <summary>
    /// The figure plays an order that is not over (Idle/Abort are over) — not counting the avatar's click walk
    /// (<see cref="StartClickWalk"/>): the player still owns that walk like any free walk (position reports, corrections,
    /// offers and the prop guard go on), only the order draws it.
    /// </summary>
    public bool HasLiveOrder(string name)
        => PlaysOrder(name) && !_clickWalkIds.Contains(_orderPlayers[name].Current!.Id);

    private bool PlaysOrder(string name)
        => _orderPlayers.TryGetValue(name, out var p) && p.Current is not null && p.State is not (OrderState.Idle or OrderState.Abort);

    /// <summary>The order (or its end blend) owns the figure's place: <see cref="ApplyPlan"/> never re-places it (spec 2).</summary>
    private bool HoldsOrderPlacement(Figure fig)
        => PlaysOrder(fig.CharacterName) || _orderBlends.ContainsKey(fig.CharacterName);

    /// <summary>
    /// A client-made order (<see cref="Order.IsLocal"/>, <see cref="LocalOrders"/>) for its drawn actors, accepted at once
    /// on the motion clock it was issued at (lag 0). True when a figure took it. <paramref name="path"/> replaces the
    /// location's navigation (<see cref="NavOf"/>) for this order's walk.
    /// </summary>
    public bool StartLocalOrder(Order local, IPathProvider? path = null)
    {
        if (path is not null) _orderPaths[local.Id] = path;
        bool any = false;
        foreach (var actor in local.Actors)
            if (_figures.TryGetValue(actor.Name, out var fig))
            {
                _parkedOrders.Remove(actor.Name);
                any |= AcceptOrder(fig, local, local.IssuedS);
            }
        return any;
    }

    /// <summary>The path a local order walks on instead of its location's navigation (order id → path).</summary>
    private readonly Dictionary<string, IPathProvider> _orderPaths = new(StringComparer.Ordinal);
    /// <summary>The ids of the avatar's click walks still played (<see cref="StartClickWalk"/>).</summary>
    private readonly HashSet<string> _clickWalkIds = new(StringComparer.Ordinal);

    /// <summary>
    /// Plan E3 Task 10 (decision 12): a ground click of the avatar inside a building is a local <c>walk</c> order
    /// (<see cref="LocalOrders.Walk"/>, never sent to the server) played by the avatar's <see cref="OrderPlayer"/> on
    /// <paramref name="path"/> (<see cref="ClickWalkPath"/>): links ridden through <see cref="AvatarLinkRide"/>, stuck and
    /// replans of <see cref="OrderWalk"/>. It ends — the figure stays where the order drew it, no end blend, no
    /// <see cref="OrderEnded"/> — at its goal, at a refused link ride (at the link foot), at its second failure to make
    /// progress (<see cref="OrderPlayer.WalkFailures"/>, final review E2 I-2) and at <see cref="EndClickWalk"/>.
    /// True when the avatar took it.
    /// </summary>
    public bool StartClickWalk(Order walk, IPathProvider path)
    {
        _clickWalkIds.Add(walk.Id);
        if (StartLocalOrder(walk, path) && OrderPlayerOf(AvatarName)?.Current?.Id == walk.Id) return true;
        _clickWalkIds.Remove(walk.Id);
        _orderPaths.Remove(walk.Id);
        return false;
    }

    /// <summary>The avatar's click walk <paramref name="id"/> is still played.</summary>
    public bool ClickWalkLive(string id)
        => _clickWalkIds.Contains(id) && _orderPlayers.TryGetValue(AvatarName, out var p) && p.Current?.Id == id
           && p.State is not (OrderState.Idle or OrderState.Abort);

    /// <summary>
    /// The avatar's click walk <paramref name="id"/> stands at a link whose ride is requested or running
    /// (<see cref="OrderPlayer.WalkRiding"/>): steering holds keys and clicks, the position channel its corrections and
    /// the rooms controller its offers until the ride is over (what <c>VerticalRide</c> held for the E2 ride).
    /// </summary>
    public bool ClickWalkRiding(string id)
        => ClickWalkLive(id) && _orderPlayers[AvatarName].WalkRiding;

    /// <summary>
    /// Ends the avatar's click walk <paramref name="id"/> where it stands: <paramref name="reason"/> (e.g. <c>input</c>,
    /// a walk key) refuses the order first (<see cref="OrderPlayer.Refuse"/>), then the avatar's order is let go at once —
    /// no aborted frame, no turn-away, no <see cref="OrderEnded"/>; the player's input owns the figure from here.
    /// </summary>
    public void EndClickWalk(string id, string reason)
    {
        if (_orderPlayers.TryGetValue(AvatarName, out var player) && player.Current?.Id == id)
        {
            if (reason.Length > 0) player.Refuse(reason);
            DropClickWalkPlayer(AvatarName);
            if (_figures.TryGetValue(AvatarName, out var fig)) { fig.Target = fig.Position; fig.Waypoints.Clear(); }
        }
        _clickWalkIds.Remove(id);
        _orderPaths.Remove(id);
    }

    /// <summary>The ids of the client-local room walks (<c>local:&lt;n&gt;</c>), apart from the avatar's click counter.</summary>
    private int _roomWalks = 1_000_000;
    /// <summary>The ids of the room walks still played: at their goal they hand the figure back to the rows.</summary>
    private readonly HashSet<string> _roomWalkIds = new(StringComparer.Ordinal);

    /// <summary>
    /// Plan E3 Task 9 (review W6): a room change of an NPC row WITHOUT a server order (a party follower, a refused walk,
    /// an admin move) walks a client-local <c>walk</c> (<see cref="LocalOrders.Walk"/>) from where the figure is drawn to
    /// the row's new point, over the navmesh of the location (links ridden on the way). Not for a player-driven figure
    /// (input owns it), a row that carries an order, an unmounted location or a figure already on the point. True when the figure took it.
    /// </summary>
    private bool StartRoomWalk(Figure fig, FigurePlan plan)
    {
        string name = fig.CharacterName;
        if (IsPlayerDriven(name)) return false;
        if (!_rowByName.TryGetValue(name, out var row) || (row.Order is not null && !Released(name, row.Order)) || row.LocationId.Length == 0) return false;
        if (Slots?.Invoke().GetValueOrDefault(row.LocationId) is not { } tile) return false;
        double dx = plan.Pos.X - fig.Position.X, dz = plan.Pos.Z - fig.Position.Z;
        if (dx * dx + dz * dz <= OrderPlayer.ArriveTolM * OrderPlayer.ArriveTolM) return false;
        int Level(string? room) => room is not null && tile.Stands.RoomLevels.TryGetValue(room, out var l) ? l : 0;
        var start = new OrderPoint(fig.Position.X, fig.Position.Y, fig.Position.Z, fig.Yaw * 180 / Math.PI);
        var goal = new OrderPoint(plan.Pos.X, plan.Pos.Y, plan.Pos.Z, start.YawDeg);
        var walk = LocalOrders.Walk(++_roomWalks, MotionNow, LocalOrders.DefaultSpeedMS, name, start, plan.FromRoom ?? "",
                                    Level(plan.FromRoom), goal, row.LocationId, plan.InRoom ?? "", Level(plan.InRoom));
        if (!StartLocalOrder(walk)) return false;
        _roomWalkIds.Add(walk.Id);
        return true;
    }

    /// <summary>The server refused the figure's order (a reservation, a room): it stops where it stands (event <c>aborted</c>).</summary>
    public void RefuseOrder(string name, string reason)
    {
        if (_orderPlayers.TryGetValue(name, out var player)) player.Refuse(reason);
    }

    /// <summary>Lets go of the figure's order at once, without an end blend (the hand-back of the avatar).</summary>
    public void DropOrder(string name)
    {
        if (!_orderPlayers.TryGetValue(name, out var player) || player.Current is null) return;
        ForgetOrders(name);
    }

    /// <summary>
    /// Lets go of the figure's (local) order and goes back to what its row says (review Task 6 I2: a refused click while
    /// the server still holds the own run): the row's order when it carries one, else the row's placement at once — the
    /// held place seats the figure again (no end blend, no event).
    /// </summary>
    public void ResumeRowOrder(string name)
    {
        DropOrder(name);
        if (!_figures.TryGetValue(name, out var fig)) return;
        if (_rowByName.TryGetValue(name, out var row) && row.Order is { } order
            && !(name == AvatarName && IgnoresAvatarOrder?.Invoke(order) == true) && Mounted(order.LocationId))
            AcceptOrder(fig, order, MotionNow);
        if (!HasLiveOrder(name) && _lastPlans.TryGetValue(name, out var plan)) ApplyPlan(fig, plan, false);
    }

    /// <summary>
    /// Hands the orders to the players of their NPC actors. <paramref name="motionNow"/> is the server's motion clock the
    /// orders were read at; the client clock is <see cref="Clock"/>. An order of a location that is not mounted (or of a
    /// figure not drawn yet) is parked and accepted at its mount with the entry rule (lag counted from the park).
    /// </summary>
    public void AdoptOrders(IEnumerable<Order> orders, double motionNow)
    {
        foreach (var order in orders)
        {
            _orderSeqSeen = Math.Max(_orderSeqSeen, order.Seq);
            foreach (var actor in order.Actors)
            {
                string name = actor.Name;
                if (name.Length == 0 || (name == AvatarName && IgnoresAvatarOrder?.Invoke(order) == true)) continue;
                if (Released(name, order)) continue;
                if (!_figures.TryGetValue(name, out var fig) || !Mounted(order.LocationId))
                {
                    if (!_parkedOrders.TryGetValue(name, out var parked) || Newer(order, parked.Order))
                        _parkedOrders[name] = (order, motionNow, _clock);
                    continue;
                }
                if (_parkedOrders.TryGetValue(name, out var old))
                {
                    // A newer order waits for its mount: an older one arriving meanwhile (a stale row) must not replace it.
                    if (Newer(old.Order, order)) continue;
                    _parkedOrders.Remove(name);
                }
                AcceptOrder(fig, order, motionNow);
            }
        }
    }

    /// <summary>The order is the figure's released server walk (<see cref="_releasedWalks"/>), not a newer revision of it.</summary>
    private bool Released(string name, Order? order)
        => order is not null && _releasedWalks.TryGetValue(name, out var r) && r.Id == order.Id && order.Revision <= r.Revision;

    private static bool Newer(Order a, Order b) => a.Seq != b.Seq ? a.Seq > b.Seq : a.Revision > b.Revision;

    private bool Mounted(string locationId)
        => locationId.Length == 0 || Slots is null || Slots.Invoke().ContainsKey(locationId);

    private bool AcceptOrder(Figure fig, Order order, double motionNow)
    {
        string name = fig.CharacterName;
        var player = PlayerFor(name);
        string? before = player.Current?.Id;
        bool local = player.Current is { IsLocal: true };
        double issuedBefore = player.IssuedLocal;
        if (!player.Accept(order, _clock, motionNow, V(fig.Position), fig.Yaw * 180 / Math.PI)) return false;
        // A new order replaced a click walk (a furniture click, a server order), or adopted a local order in place: the
        // old id's path and click bookkeeping go with it.
        if (before is { } replaced && replaced != order.Id) { _clickWalkIds.Remove(replaced); _orderPaths.Remove(replaced); }
        // A revision, or the adoption of a local order in place (same target, the local clock kept): the figure keeps going.
        if (before == order.Id || (local && !order.IsLocal && player.IssuedLocal == issuedBefore)) return true;
        _orderBlends.Remove(name);
        _orderLoopShown.Remove(name);
        _orderLoopHeld.Remove(name);
        _orderExitY[name] = fig.Position.Y;
        fig.Route = null; fig.Reckon = null; fig.Settle = null; fig.Ride = null;
        fig.Waypoints.Clear(); fig.DropTravelLine();
        fig.PropEntryBlocked = false; fig.PropCommitPending = false; fig.PropCommitKey = "";
        fig.Travelling = false;
        return true;
    }

    private OrderPlayer PlayerFor(string name)
    {
        if (_orderPlayers.TryGetValue(name, out var player)) return player;
        // The avatar's link rides ask the server for the room first (plan E3 Task 6, R2d). Which ride applies is decided
        // at each ride's start, not here: the player may be born before the hook is wired, or outlive an avatar change.
        var rides = new Dictionary<string, ILinkRide>(StringComparer.Ordinal)
        {
            ["stairs"] = new ResolvedLinkRide("stairs", () => AvatarRideOf(name, "stairs"), new NpcStairsRide(() => _orderPlayers.TryGetValue(name, out var p) && p.Current is { } o
                && Slots?.Invoke().GetValueOrDefault(o.LocationId) is { } tile ? tile.Places.Stairs : Array.Empty<AnimaNative.Scene.StairLink>())),
            ["lift"] = new ResolvedLinkRide("lift", () => AvatarRideOf(name, "lift"), new NpcLiftRide()),
        };
        var created = new OrderPlayer(name, new OrderClipDurations(this, name), rides);
        // A player born between two polls (a pull, a mount) starts in the world's freeze state, not unfrozen.
        created.SetFrozen(WorldFrozen, _clock);
        return _orderPlayers[name] = created;
    }

    /// <summary>The avatar's ride of a kind when <paramref name="name"/> is the avatar NOW and the hook is wired, else null.</summary>
    private ILinkRide? AvatarRideOf(string name, string kind)
        => name == AvatarName && AvatarLinkRide is { } hook ? hook(kind) : null;

    /// <summary>
    /// One figure's ride of one kind, resolved at <see cref="Begin"/> (review Task 6 I4): the avatar's room-entry ride when
    /// the figure is the avatar at that moment, else the NPC ride. Poll/Abort go to the ride the last Begin chose.
    /// </summary>
    private sealed class ResolvedLinkRide(string kind, Func<ILinkRide?> avatar, ILinkRide npc) : ILinkRide
    {
        private ILinkRide _active = npc;
        public string Kind => kind;
        public LinkRideState Begin(string actor, NavLink link)
        {
            _active = avatar() ?? npc;
            return _active.Begin(actor, link);
        }
        public LinkRideState Poll(ref Vec3 pos, double dt, double speedMS) => _active.Poll(ref pos, dt, speedMS);
        public void Abort() => _active.Abort();
    }

    /// <summary>
    /// The order part of one worldmap payload: the rows' orders on the root <c>motion_now</c>; a row WITHOUT one ends a
    /// server order its root <c>order_seq</c> covers (decision 6; a local order or an older row changes nothing); the
    /// world freeze reaches every player.
    /// </summary>
    private void AdoptRowOrders(JsonElement root)
    {
        double? motionNow = root.TryGetProperty("motion_now", out var mn) && mn.ValueKind == JsonValueKind.Number ? mn.GetDouble() : null;
        long orderSeq = root.TryGetProperty("order_seq", out var os) && os.ValueKind == JsonValueKind.Number && os.TryGetInt64(out var sv) ? sv : 0;
        // A row without the released walk ends its tail: the next order of that id would be a new one.
        foreach (var row in _rows)
            if (_releasedWalks.TryGetValue(row.Name, out var released) && row.Order?.Id != released.Id) _releasedWalks.Remove(row.Name);
        var orders = _rows.Where(r => r.Order is not null).Select(r => r.Order!).ToList();
        if (motionNow is { } now) { _motionSeen = (now, _clock); AdoptOrders(orders, now); }
        _orderSeqSeen = Math.Max(_orderSeqSeen, orderSeq);
        var named = orders.SelectMany(o => o.Actors.Select(a => a.Name)).ToHashSet(StringComparer.Ordinal);
        foreach (var row in _rows)
        {
            // A row whose order did not parse is no "row without order": it must not end the running one.
            if (row.Order is not null || row.OrderUnreadable || named.Contains(row.Name)) continue;
            if (_orderPlayers.TryGetValue(row.Name, out var player)) player.RowWithoutOrder(orderSeq, _clock);
            if (_parkedOrders.TryGetValue(row.Name, out var parked) && !parked.Order.IsLocal && orderSeq >= parked.Order.Seq)
                _parkedOrders.Remove(row.Name);
        }
        foreach (var player in _orderPlayers.Values) player.SetFrozen(FrozenFor(player), _clock);
    }

    /// <summary>
    /// The world freeze of one player: every order stops with the world, except the avatar's click walk — the player's
    /// own input, which walks on during a freeze like the keys do (plan E3 Task 10).
    /// </summary>
    private bool FrozenFor(OrderPlayer player)
        => WorldFrozen && !(player.Current is { } order && _clickWalkIds.Contains(order.Id));

    /// <summary>
    /// The push topic <c>orders</c>: <c>GET /play/orders?since=</c> the highest seq seen, adopted on the answer's
    /// <c>motion_now</c>. One request at a time; a push during one asks once more afterwards. A source without the
    /// endpoint (404) changes nothing and logs nothing.
    /// </summary>
    public Task PullOrdersAsync()
    {
        if (_ordersPull is { IsCompleted: false })
        {
            _ordersPullAgain = true;
            return _ordersPull;
        }
        return _ordersPull = PullLoopAsync();
    }

    private async Task PullLoopAsync()
    {
        do
        {
            _ordersPullAgain = false;
            try
            {
                using var doc = await _source.GetOrdersAsync(_orderSeqSeen);
                var payload = OrdersPayload.Parse(doc.RootElement);
                if (payload.MotionNow is { } now) { _motionSeen = (now, _clock); AdoptOrders(payload.Orders, now); }
                _orderSeqSeen = Math.Max(_orderSeqSeen, payload.Seq);
            }
            catch (ApiException e) when (e.Status == 404)
            {
                return;
            }
            catch (Exception e)
            {
                _log($"[orders] pull failed: {e.Message}");
                return;
            }
        } while (_ordersPullAgain);
    }

    /// <summary>A parked order whose figure exists and whose location is mounted now: accepted (lag counted from the park).</summary>
    private void AcceptParked(Figure fig)
    {
        string name = fig.CharacterName;
        if (!_parkedOrders.TryGetValue(name, out var parked) || !Mounted(parked.Order.LocationId)) return;
        _parkedOrders.Remove(name);
        AcceptOrder(fig, parked.Order, parked.MotionNow + (_clock - parked.At));
    }

    /// <summary>
    /// Lets go of the avatar's click walk only: its player and the shown state of that order. A server order parked
    /// for its mount meanwhile and the arrival bookkeeping stay (unlike <see cref="ForgetOrders"/>).
    /// </summary>
    private void DropClickWalkPlayer(string name)
    {
        if (_orderPlayers.TryGetValue(name, out var player) && player.Current is { } current)
        {
            _clickWalkIds.Remove(current.Id);
            _orderPaths.Remove(current.Id);
        }
        _orderPlayers.Remove(name);
        _orderBlends.Remove(name);
        _orderLoopShown.Remove(name);
        _orderLoopHeld.Remove(name);
        _orderShownState.Remove(name);
        _orderExitY.Remove(name);
        _orderEntrySpecs.Remove(name);
    }

    private void ForgetOrders(string name)
    {
        ReleaseAgent(name);
        if (_orderPlayers.TryGetValue(name, out var player) && player.Current is { } current)
        {
            _clickWalkIds.Remove(current.Id);
            _orderPaths.Remove(current.Id);
        }
        _orderPlayers.Remove(name);
        _parkedOrders.Remove(name);
        _orderBlends.Remove(name);
        _orderLoopShown.Remove(name);
        _orderLoopHeld.Remove(name);
        _orderShownState.Remove(name);
        _orderExitY.Remove(name);
        _orderEntrySpecs.Remove(name);
        _arrivalReported.Remove(name);
        _releasedWalks.Remove(name);
    }

    /// <summary>
    /// The avatar stands at the access of a server order that names it <c>reports_arrival</c> (event
    /// <c>arrived_access</c>, or <c>entry_started</c> when the answer's order adopted a local one already waiting there):
    /// report the arrival once per order, without holding the entry back. The answer comes later; a refusal aborts
    /// the order if it is still the current one. A source without the endpoint (404) and a lost request change
    /// nothing — the server's deadline ends a run whose arrival never came.
    /// </summary>
    private void ReportArrival(string name, Order order, Vec3 at, double yawRad)
    {
        if (name != AvatarName || order.IsLocal || order.ActorNamed(name) is not { ReportsArrival: true }) return;
        if (_arrivalReported.TryGetValue(name, out var sent) && sent == order.Id) return;
        _arrivalReported[name] = order.Id;
        _ = ReportArrivalAsync(name, order, at, yawRad);
    }

    private async Task ReportArrivalAsync(string name, Order order, Vec3 at, double yawRad)
    {
        string reason;
        try
        {
            using var doc = await _source.PostOrderArrivedAsync(order.Id, at.X, at.Z, yawRad, order.RoomId);
            reason = OrderArrived.RefusalOf(doc.RootElement);
        }
        catch (ApiException e) when (e.Status == 404)
        {
            return;
        }
        catch (ApiException e) when (e.Status == 409)
        {
            reason = OrderArrived.RefusalOf(e);
        }
        catch (Exception e)
        {
            _log($"[orders] arrival report for {order.Id} failed: {e.Message}");
            return;
        }
        if (reason.Length > 0)
        {
            _log($"[orders] arrival of {name} refused: {reason}");
            if (_orderPlayers.TryGetValue(name, out var player) && player.Current?.Id == order.Id) player.Refuse(reason);
        }
        OrderArrivalAnswered?.Invoke(name, order, reason);
    }

    /// <summary>
    /// The first branch of <c>StepFigure</c>: one frame of the figure's order. True when the order drew the figure
    /// (exit, walk, waiting at the access, entry, the end blend); false from the loop on (decision 18: the row's
    /// branches pose the figure, the order only keeps it on its slot) and without a live order.
    /// </summary>
    private bool TickOrder(Figure fig, double dt, double camDist)
    {
        string name = fig.CharacterName;
        AcceptParked(fig);
        if (_orderBlends.TryGetValue(name, out var blend)) return TickOrderBlend(fig, blend, dt, camDist);
        if (!_orderPlayers.TryGetValue(name, out var player) || player.Current is not { } order) return false;
        player.SetFrozen(FrozenFor(player), _clock);
        PrepareAvoidedStep(fig, player, order);
        var frame = player.Tick(_clock, _orderPaths.TryGetValue(order.Id, out var own) ? own : NavOf?.Invoke(order.LocationId));
        bool shownBefore = _orderShownState.TryGetValue(name, out var wasState);
        if (frame.Events.Count > 0 || frame.State != OrderState.Idle || (shownBefore && wasState != OrderState.Idle))
        {
            _orderShownState[name] = frame.State;
            OrderFrameShown?.Invoke(name, frame);
        }
        if (_clickWalkIds.Contains(order.Id) && ClickWalkEnds(fig, player, order, frame)) return false;
        foreach (var e in frame.Events)
        {
            if (e == "arrived_access")
            {
                OrderArrivedAtAccess?.Invoke(name, order);
                ReportArrival(name, order, frame.Position, frame.YawDeg * Math.PI / 180);
            }
            else if (e == "entry_started") ReportArrival(name, order, frame.Position, frame.YawDeg * Math.PI / 180);
            else if (e == "ended") { _orderBlends[name] = (fig.Position, _clock); OrderEnded?.Invoke(name); }
            else if (e == "aborted")
            {
                fig.FinishPropEntry(FigureClips.PoseKind("standing", fig.Poses));
                fig.Position = new Vector3((float)frame.Position.X, (float)OrderFloorY(fig, frame.Position), (float)frame.Position.Z);
                fig.Target = fig.Position;
                OrderEnded?.Invoke(name);
            }
        }
        if (_orderBlends.TryGetValue(name, out var ended)) return TickOrderBlend(fig, ended, dt, camDist);
        // The world freeze folds every live state into Frozen; the chain's own state decides who draws: from the loop on
        // the row's branches do, frozen or not (decision 18 — they hold the pair, the solo clip and the finale still).
        bool frozen = frame.State == OrderState.Frozen;
        switch (frozen ? player.RunState : frame.State)
        {
            case OrderState.Idle:
            case OrderState.Abort:
                return false;
            case OrderState.Loop when _roomWalkIds.Remove(order.Id) || EndedServerWalk(name, order):
                // A room walk at its goal — or a server walk the server has ended (E3 final review I3: its order stays
                // published for the tail, and without this the rows could not re-place the figure for 10 s): blended
                // into the row's rest placement, then the rows place the figure again.
                if (!order.IsLocal)
                {
                    long revision = order.Revision;
                    if (_rowByName.GetValueOrDefault(name)?.Order is { } rowOrder && rowOrder.Id == order.Id) revision = Math.Max(revision, rowOrder.Revision);
                    _releasedWalks[name] = (order.Id, revision);
                }
                _orderPlayers.Remove(name);
                _orderShownState.Remove(name);
                _orderBlends[name] = (fig.Position, _clock);
                return TickOrderBlend(fig, _orderBlends[name], dt, camDist);
            case OrderState.Loop:
                if (!_orderLoopShown.TryGetValue(name, out var shownId) || shownId != order.Id) ShowLoopStart(fig, player, frame);
                ApplyLoopSurface(fig, player);
                if (!HoldsLoopStart(fig, order)) return false;
                // The row does not carry the loop pose yet: the order keeps the figure on its slot in the held frame.
                fig.SecondaryFrozen = WorldFrozen;
                fig.UpdateFigure(frozen ? 0 : dt);
                fig.Portrait?.Tick(dt, camDist, false);
                return true;
        }
        if (frozen)
        {
            fig.SecondaryFrozen = true;
            fig.UpdateFigure(0);
            return true;
        }
        DrawOrderFrame(fig, player, frame, dt, camDist);
        return true;
    }

    /// <summary>
    /// The end of the avatar's click walk in this frame (<see cref="StartClickWalk"/>): at its goal (the chain's loop),
    /// aborted (a refused link ride: at the link foot) or at the second failure to make progress. The figure is put on
    /// the frame's point (the foot height from the floor) and the order let go. False while it walks on.
    /// </summary>
    private bool ClickWalkEnds(Figure fig, OrderPlayer player, Order order, OrderFrame frame)
    {
        bool ended = player.RunState is OrderState.Loop or OrderState.Idle or OrderState.Abort || frame.Events.Contains("aborted");
        bool failed = !ended && player.WalkFailures >= 2;
        if (!ended && !failed) return false;
        var p = frame.Position;
        fig.Position = new Vector3((float)p.X, (float)OrderFloorY(fig, p), (float)p.Z);
        if (failed) _log($"[orders] click walk {order.Id} gave up after {player.WalkFailures} failures to make progress");
        else if (frame.Events.Contains("link_refused")) _log($"[orders] click walk {order.Id} ended at a refused link ride");
        EndClickWalk(order.Id, failed ? "stuck" : "");
        return true;
    }

    /// <summary>Exit, walk, the wait at the access and the entry: the root from the frame, the foot height from the floor.</summary>
    private void DrawOrderFrame(Figure fig, OrderPlayer player, OrderFrame frame, double dt, double camDist)
    {
        string name = fig.CharacterName;
        var p = frame.Position;
        var before = fig.Position;
        bool moving = false;
        var rules = Clips.PoseRules;
        switch (frame.State)
        {
            case OrderState.Exit:
            {
                double floor = OrderFloorY(fig, p);
                fig.Position = new Vector3((float)p.X, (float)floor, (float)p.Z);
                string clip = rules.ExitKind(frame.PoseKey ?? "") ?? "";
                double dur = player.PhaseDuration;
                double startLift = (_orderExitY.TryGetValue(name, out var y0) ? y0 : floor) - floor;
                if (clip.Length == 0 || !fig.PlayOwnPropDeparture(clip, dur > 0 ? frame.PhaseTime / dur : 1, startLift))
                    fig.Play(FigureClips.PoseKind("standing", fig.Poses));
                break;
            }
            case OrderState.Walk:
            case OrderState.WaitAccess:
            {
                // The exit's stand-up bridge is over once the walk runs: let it go into the standing pose.
                if (fig.Bridging) fig.FinishPropEntry(FigureClips.PoseKind("standing", fig.Poses));
                double dx = p.X - before.X, dz = p.Z - before.Z;
                moving = frame.State == OrderState.Walk && dx * dx + dz * dz > 1e-12;
                var yaw = frame.YawDeg * Math.PI / 180;
                fig.FaceTowards(new Vector3((float)Math.Sin(yaw), 0, (float)Math.Cos(yaw)));
                if (player.Current!.LocationId.Length == 0)
                {
                    // Out in the open (plan E3 Task 9, review I1): the ground rules of the route tick — wade/swim/crawl
                    // clip, sink, floated root height, underwater ghost — on the order's own position and pace.
                    var open = WalkGround.OrderFrame(WordAt(p.X, p.Z), moving, fig.Poses);
                    if (fig.Portrait is null) fig.SetSubmerged(open.GhostCutY);
                    fig.Position = new Vector3((float)p.X, (float)EaseRootY(fig, before.Y, open.RootY, dt), (float)p.Z);
                    fig.SetMotion(moving, false, open.Movement);
                    PlayLifting(fig, open.Clip, open.TerrainClip, open.Sink, before.Y, open.RootY, "ground");
                    if (moving && dt > 0 && ScalesGait(player)) fig.ScaleClip(OrderWalk.ClipRate(Math.Sqrt(dx * dx + dz * dz) / dt));
                    break;
                }
                fig.Position = new Vector3((float)p.X, (float)OrderFloorY(fig, p), (float)p.Z);
                fig.SetMotion(moving, false, FigureClips.WalkRun);
                fig.Play(FigureClips.PoseKind(moving ? "walking" : "standing", fig.Poses));
                // Spec 5d: the gait clip runs at the order's tempo (the step's own speed: RVO may slow it).
                if (moving && dt > 0 && ScalesGait(player)) fig.ScaleClip(OrderWalk.ClipRate(Math.Sqrt(dx * dx + dz * dz) / dt));
                break;
            }
            case OrderState.Entry:
            {
                fig.Position = new Vector3((float)p.X, (float)OrderFloorY(fig, p), (float)p.Z);
                var actor = player.Current!.ActorNamed(name)!;
                string clip = rules.EntryKind(frame.PoseKey ?? "") ?? "";
                double dur = player.PhaseDuration;
                var spec = EntrySpec(fig, player.Current!, actor, clip, p, frame.YawDeg);
                if (clip.Length == 0 || !fig.PlayPropEntry(spec, dur > 0 ? frame.PhaseTime / dur : 1))
                {
                    // Decision 14: no clip in the loaded model — the phase is a held pose of its nominal length.
                    var yaw = frame.YawDeg * Math.PI / 180;
                    fig.FaceTowards(new Vector3((float)Math.Sin(yaw), 0, (float)Math.Cos(yaw)));
                    fig.Play(FigureClips.PoseKind("standing", fig.Poses));
                }
                break;
            }
        }
        fig.Target = fig.Position;
        fig.Waypoints.Clear();
        if (_lastPlans.TryGetValue(name, out var plan)) fig.SetHidden(plan.Hidden);
        fig.SecondaryFrozen = WorldFrozen;
        fig.UpdateFigure(dt);
        fig.Portrait?.Tick(dt, camDist, moving);
    }

    /// <summary>
    /// <c>loop_started</c>: the figure on the order's slot (the anchor), facing its yaw; the entry bridge is let go — into
    /// the pair's half when the row holds one, else into the row's pose. From here the row's branches play it.
    /// </summary>
    private void ShowLoopStart(Figure fig, OrderPlayer player, OrderFrame frame)
    {
        string name = fig.CharacterName;
        _orderLoopShown[name] = player.Current!.Id;
        var p = frame.Position;
        fig.Position = new Vector3((float)p.X, (float)p.Y, (float)p.Z);
        fig.Target = fig.Position;
        fig.Waypoints.Clear();
        var yaw = frame.YawDeg * Math.PI / 180;
        var facing = new Vector3((float)Math.Sin(yaw), 0, (float)Math.Cos(yaw));
        fig.Face = facing;
        fig.FaceTowards(facing, snap: true);
        var row = _rowByName.GetValueOrDefault(name);
        bool bridge = fig.Bridging || fig.PropEntryLift != 0;
        if (row?.Interaction is not null) fig.HoldPropPoseAtAnchor();
        else if (!string.IsNullOrEmpty(player.PhasePoseKind) && RowAwaitsLoopPose(row, player.Current!))
        {
            // E3 final review I2: the client reaches the loop before the server's flip (START_SLACK_S, ticker beat, push
            // batch, poll), and until then the row still carries the pose from before the run. The entry's last frame is
            // held on the slot until a row shows the order active (HoldsLoopStart) — never a stale or standing pose.
            if (bridge) fig.HoldPropPoseAtAnchor();
            _orderLoopHeld[name] = (player.Current!.Id, _clock, bridge);
        }
        else if (bridge)
            fig.FinishPropEntry(RowLoopClip(fig, row));
    }

    private static string RowLoopClip(Figure fig, CharacterRow? row)
        => row is { ActivityAnimation.Length: > 0 } ? row.ActivityAnimation : FigureClips.PoseKind("standing", fig.Poses);

    /// <summary>The row still shows <paramref name="order"/> before its flip: its pose is the one from before the run.</summary>
    private static bool RowAwaitsLoopPose(CharacterRow? row, Order order)
        => row is { Interaction: null, Order: { } shown } && shown.Id == order.Id && shown.Status is not ("active" or "ended");

    /// <summary>The loop start of <paramref name="order"/> is held (<see cref="ShowLoopStart"/>); let go — into the row's pose —
    /// once a row carries it or after <see cref="LoopHoldMaxS"/>.</summary>
    private bool HoldsLoopStart(Figure fig, Order order)
    {
        string name = fig.CharacterName;
        if (!_orderLoopHeld.TryGetValue(name, out var held)) return false;
        var row = _rowByName.GetValueOrDefault(name);
        if (held.Id == order.Id && RowAwaitsLoopPose(row, order) && _clock - held.At < LoopHoldMaxS) return true;
        _orderLoopHeld.Remove(name);
        if (held.Bridge && row?.Interaction is null) fig.FinishPropEntry(RowLoopClip(fig, row));
        return false;
    }

    /// <summary>The loop start of <paramref name="name"/> waits for its row's loop pose (<see cref="ShowLoopStart"/>).</summary>
    public bool HoldsLoopStartPose(string name) => _orderLoopHeld.ContainsKey(name);

    /// <summary>
    /// A server <c>walk</c> the server has ended (E3 final review I3): the row carries its <c>ended</c> revision (the target
    /// is written then), or the ended revision came first and the row's point is already the walk's goal.
    /// </summary>
    private bool EndedServerWalk(string name, Order order)
    {
        if (order.Kind != "walk" || order.IsLocal) return false;
        var row = _rowByName.GetValueOrDefault(name);
        if (row?.Order is { } shown && shown.Id == order.Id && shown.Status == "ended") return true;
        if (order.Status != "ended" || order.Goal is not { } goal || !_lastPlans.TryGetValue(name, out var plan)) return false;
        double dx = plan.Pos.X - goal.X, dz = plan.Pos.Z - goal.Z;
        return dx * dx + dz * dz <= OrderPlayer.ArriveTolM * OrderPlayer.ArriveTolM;
    }

    /// <summary>Decision 6: from where the ended order left the figure into the row's rest placement, then the rows again.</summary>
    private bool TickOrderBlend(Figure fig, (Vector3 From, double At) blend, double dt, double camDist)
    {
        string name = fig.CharacterName;
        var rest = _lastPlans.TryGetValue(name, out var plan)
            ? new Vector3((float)plan.Pos.X, (float)plan.Pos.Y, (float)plan.Pos.Z) : blend.From;
        double f = Math.Clamp((_clock - blend.At) / OrderEndBlendS, 0, 1);
        fig.Position = blend.From.Lerp(rest, (float)f);
        fig.Target = fig.Position;
        fig.Waypoints.Clear();
        if (f >= 1)
        {
            _orderBlends.Remove(name);
            fig.Settle = null;
            return false;
        }
        fig.SecondaryFrozen = WorldFrozen;
        fig.UpdateFigure(dt);
        fig.Portrait?.Tick(dt, camDist, false);
        return true;
    }

    /// <summary>
    /// The entry clip's spec for <see cref="Figure.PlayPropEntry"/> (it only reads it): built once per order revision,
    /// clip and freeze state, not every frame.
    /// </summary>
    private JsonObject EntrySpec(Figure fig, Order order, OrderActor actor, string clip, Vec3 p, double yawDeg)
    {
        string name = fig.CharacterName;
        string key = $"{order.Id}/{order.Revision}/{clip}/{WorldFrozen}";
        if (_orderEntrySpecs.TryGetValue(name, out var cached) && cached.Key == key) return cached.Spec;
        var access = actor.Access ?? new OrderPoint(p.X, p.Y, p.Z, yawDeg);
        var anchor = actor.Anchor ?? access;
        JsonObject Point(OrderPoint q) => new() { ["x"] = q.X, ["y"] = q.Y, ["z"] = q.Z, ["yaw"] = q.YawDeg };
        var spec = new JsonObject
        {
            ["kind"] = clip, ["access"] = Point(access), ["anchor"] = Point(anchor), ["root_offset"] = actor.RootOffset,
            ["height_cm"] = actor.HeightCm ?? fig.HeightM * 100, ["clock_rate"] = WorldFrozen ? 0 : 1,
        };
        _orderEntrySpecs[name] = (key, spec);
        return spec;
    }

    /// <summary>
    /// From the loop on the row poses the figure (decision 18), on the slot's surface: the plan's group and lean when
    /// the row's place resolved a marker (as the placement did before orders), else the group of the order's loop pose
    /// kind (seat / lie). Without this the loop pose got the ground's height correction: the hold branch of
    /// <see cref="ApplyPlan"/> returns before it sets the group and the lean.
    /// </summary>
    private void ApplyLoopSurface(Figure fig, OrderPlayer player)
    {
        _lastPlans.TryGetValue(fig.CharacterName, out var plan);
        string group = plan is { SurfaceGroup: not "ground" } ? plan.SurfaceGroup : ClipHeightOffsets.Surface(player.PhasePoseKind);
        var lean = plan?.Lean;
        if (fig.SurfaceGroup == group && fig.Lean == lean) return;
        fig.SurfaceGroup = group;
        fig.Lean = lean;
        fig.ApplyRotation();
    }

    /// <summary>
    /// The foot height under an order frame (never the path's): the stand of the row's room at (x, z), else the room
    /// stand callback, else the ground — the one nearest the frame's own height; a frame more than 0.5 m off every one of
    /// them (a stair ride, an upper storey the row's room does not cover yet) keeps its own height.
    /// </summary>
    private double OrderFloorY(Figure fig, Vec3 p)
    {
        var floors = new List<double>();
        if (_rowByName.TryGetValue(fig.CharacterName, out var row) && Slots?.Invoke().GetValueOrDefault(row.LocationId) is { } tile)
        {
            var local = AnimaNative.Scene.SceneView.WorldToTile(tile.Stands.Frame, p.X, p.Z);
            if (tile.Stands.RoomStandY(row.RoomId, local.X, local.Z) is { } room) floors.Add(room);
        }
        if (RoomStandAt?.Invoke(fig.CharacterName, p.X, p.Z) is { } stand) floors.Add(stand);
        floors.Add(GroundY(p.X, p.Z));
        double best = floors.OrderBy(f => Math.Abs(f - p.Y)).First();
        return Math.Abs(best - p.Y) <= 0.5 ? best : p.Y;
    }

    /// <summary>
    /// <see cref="IClipDurations"/> of one figure: the entry/exit clip the pose rules name (<see cref="ClipLibrary.PoseRules"/>)
    /// as the loaded model binds it; null (→ the nominal seconds) without a rule or without that clip.
    /// </summary>
    private sealed class OrderClipDurations(FigureManager manager, string name) : IClipDurations
    {
        public double? Seconds(string step, string poseKind, string poseKey)
        {
            if (!manager._figures.TryGetValue(name, out var fig)) return null;
            string? clip = step switch
            {
                "exit" => manager.Clips.PoseRules.ExitKind(poseKey),
                "entry" => manager.Clips.PoseRules.EntryKind(poseKey),
                _ => null,
            };
            return clip is { Length: > 0 } && fig.HasClip(clip) ? fig.ClipSeconds(clip) : null;
        }
    }

    // ---- avoidance (plan E3 Task 11, spec 5d) -----------------------------------------------------------------------

    /// <summary>The avoidance priority of the avatar: an NPC (<see cref="NpcAvoidancePriority"/>) gives way to it, never back.</summary>
    public const float AvatarAvoidancePriority = 1f, NpcAvoidancePriority = 0.5f;

    /// <summary>The height band an agent covers: figures on another storey never avoid each other.</summary>
    public const float AgentHeightM = 1.8f;

    /// <summary>One figure's avoidance agent: the map it lives on, what it last reported and the answer that came back.</summary>
    private sealed class AvoidAgent
    {
        public required LocationNav Nav;
        public P2 Sent;
        public readonly HeldAvoidance Answer = new();
        public Vector3? LastPos;
        public AvoidanceMode Mode = AvoidanceMode.None;
        public float Priority = -1;
        /// <summary>The agent's key on the map: unique per manager (a check runs several managers on one map).</summary>
        public required string Key;
        /// <summary>The avoidance callback: the safe velocity paired with the velocity it answers.</summary>
        public Action<Vector3>? Callback;
    }

    private readonly Dictionary<string, AvoidAgent> _agents = new(StringComparer.Ordinal);
    /// <summary>Scratch list of agents whose figure is gone (reused per tick, no allocation in the hot path).</summary>
    private readonly List<string> _goneAgents = new();

    /// <summary>
    /// The gait clip follows the order's tempo (spec 5d) — except on the avatar's click walk (review Task 11 I1): it still
    /// walks at <c>NpcWalk.WalkSpeed</c> 3.4 m/s like key walking, whose clip runs at rate 1, so scaling it would play the
    /// legs at 3.4 / 1.4 ≈ 2.4×. Until the click walk's tempo is decided, it keeps the key walk's clip pace.
    /// </summary>
    private bool ScalesGait(OrderPlayer player)
        => player.Current is not { } order || !_clickWalkIds.Contains(order.Id);

    /// <summary>The figure has an avoidance agent on <paramref name="nav"/> (check R8).</summary>
    public bool HasAgentOn(string name, LocationNav nav)
        => _agents.TryGetValue(name, out var a) && ReferenceEquals(a.Nav, nav) && nav.HasAgent(a.Key);

    /// <summary>
    /// Before an NPC's order tick: the avoidance's answer (taken only by a walk step), the wall clamp of the order's
    /// location at the figure's height and its storey height. The avatar never takes an answer — input and its click walk
    /// own it; it is only an agent so that NPCs give way.
    /// </summary>
    private void PrepareAvoidedStep(Figure fig, OrderPlayer player, Order order)
    {
        string name = fig.CharacterName;
        player.Avoidance = null;
        player.Walls = null;
        if (player.RunState != OrderState.Walk || name == AvatarName) return;
        if (_agents.TryGetValue(name, out var agent))
        {
            // Held until the next answer (review Task 11 I2): every drawn frame between two physics frames applies it.
            player.Avoidance = agent.Answer.Take((long)Engine.GetPhysicsFrames());
        }
        if (order.LocationId.Length == 0) return;
        if (OrderWallsAt?.Invoke(order.LocationId, fig.Position.Y) is { } walls)
            player.Walls = (from, to) => AnimaNative.Embody.Collide.ClampAgainstWalls(from, to, walls.Segments, walls.Radius);
        player.StoreyHeightM = Slots?.Invoke().GetValueOrDefault(order.LocationId)?.Scene is { StoreyM: > 0 } scene ? scene.StoreyM : 3;
    }

    /// <summary>
    /// After every figure stepped: each figure's agent on the map of where it is (spec 5d). An NPC with a live order is an
    /// agent on its order's location map (out in the open: <see cref="OutdoorNav"/>) — moving with the walk's desired
    /// velocity and <c>max_speed</c> = the order's speed, standing (velocity 0) at the access, in the loop and frozen, out
    /// of the avoidance in exit and entry (<see cref="AvoidanceClamp.ModeOf"/>). The avatar is an agent with its measured
    /// velocity on the map of its row's location, at a priority the NPCs give way to. Everyone else has no agent. A
    /// change of map moves the agent (<see cref="LocationNav.MoveAgentTo"/>, <c>AgentSetMap</c>).
    /// </summary>
    private void SyncAvoidance(double dt)
    {
        foreach (var fig in _figures.Values)
        {
            string name = fig.CharacterName;
            LocationNav? map = null;
            var mode = AvoidanceMode.None;
            P2 velocity = default;
            double maxSpeed = 0;
            bool avatar = name == AvatarName && name.Length > 0;
            if (avatar)
            {
                var loc = _rowByName.TryGetValue(name, out var row) ? row.LocationId : "";
                map = MapOf(loc);
                mode = AvoidanceMode.Moving;
                if (_agents.TryGetValue(name, out var known) && known.LastPos is { } last && dt > 0)
                    velocity = new P2((fig.Position.X - last.X) / dt, (fig.Position.Z - last.Z) / dt);
                maxSpeed = Math.Max(Math.Sqrt(velocity.X * velocity.X + velocity.Z * velocity.Z), 0.01);
            }
            else if (PlaysOrder(name) && _orderPlayers[name] is { Current: { } order } player)
            {
                map = MapOf(order.LocationId);
                mode = AvoidanceClamp.ModeOf(player.RunState, player.State == OrderState.Frozen);
                if (mode == AvoidanceMode.Moving) velocity = player.DesiredVelocity;
                maxSpeed = order.SpeedMS > 0 ? order.SpeedMS : LocalOrders.DefaultSpeedMS;
            }
            if (mode == AvoidanceMode.None || map is null)
            {
                ReleaseAgent(name);
                continue;
            }
            if (!_agents.TryGetValue(name, out var agent))
                agent = _agents[name] = new AvoidAgent { Nav = map, Key = $"{GetInstanceId()}/{name}" };
            else if (!ReferenceEquals(agent.Nav, map))
            {
                // The figure entered another location (or a released map left it without one): AgentSetMap, never a new agent.
                if (agent.Nav.HasAgent(agent.Key)) agent.Nav.MoveAgentTo(agent.Key, map);
                agent.Nav = map;
                agent.Answer.Clear();
            }
            if (!map.HasAgent(agent.Key))
            {
                // A new RID (its map was released and another came in the same tick, review Task 11 M2): nothing of the
                // old agent's settings is on it, so mode and priority are set again.
                agent.Mode = AvoidanceMode.None;
                agent.Priority = -1;
            }
            var a = agent;
            a.Callback ??= v => a.Answer.Set((a.Sent, new P2(v.X, v.Z)), (long)Engine.GetPhysicsFrames());
            var rid = map.AgentFor(agent.Key, fig.AvoidanceRadiusM, a.Callback);
            if (agent.Mode != mode)
            {
                NavigationServer3D.AgentSetAvoidanceEnabled(rid, mode != AvoidanceMode.Off);
                NavigationServer3D.AgentSetHeight(rid, AgentHeightM);
                agent.Mode = mode;
            }
            float priority = avatar ? AvatarAvoidancePriority : NpcAvoidancePriority;
            if (agent.Priority != priority)
            {
                NavigationServer3D.AgentSetAvoidancePriority(rid, priority);
                agent.Priority = priority;
            }
            NavigationServer3D.AgentSetPosition(rid, fig.Position);
            NavigationServer3D.AgentSetMaxSpeed(rid, (float)maxSpeed);
            NavigationServer3D.AgentSetVelocity(rid, new Vector3((float)velocity.X, 0, (float)velocity.Z));
            agent.Sent = velocity;
            agent.LastPos = fig.Position;
        }
        _goneAgents.Clear();
        foreach (var n in _agents.Keys)
            if (!_figures.ContainsKey(n)) _goneAgents.Add(n);
        foreach (var gone in _goneAgents) ReleaseAgent(gone);
    }

    /// <summary>The avoidance map of a location: its navigation (none yet: none), out in the open the world map.</summary>
    private LocationNav? MapOf(string locationId)
        => locationId.Length == 0 ? OutdoorNav?.Invoke() : NavOf?.Invoke(locationId) as LocationNav;

    /// <summary>Frees the figure's agent (on a map already released there is nothing left to free).</summary>
    private void ReleaseAgent(string name)
    {
        if (_agents.Remove(name, out var agent)) agent.Nav.FreeAgent(agent.Key);
    }

    /// <summary>Frees every agent of this manager (its exit from the tree; a check before it reuses the maps).</summary>
    public void ReleaseAvoidance()
    {
        foreach (var name in _agents.Keys.ToList()) ReleaseAgent(name);
    }
}
