using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Embody;
using AnimaNative.Figures;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// Task 49 / E7-T4: real player targets and NPC stepping on fixtures/embody, at 60 Hz.
/// W at pi/4 is (-sqrt(.5),-sqrt(.5)); D is (+sqrt(.5),-sqrt(.5)). East wall X=6
/// keeps the centre at X&lt;=5.75 while northward motion continues. The party door at Z=2 passes.
/// The rock starts at X=8; its diagonal approach keeps Z motion. Height rises 1 m from X=9 to 10,
/// so the 45 degree ramp fails the world's .4 m / 40 degree gate. Inside the hall a click behind its north wall is a
/// walk order over the navmesh (plan E2 Task 6, E3 Task 10: the avatar's local walk order); outside every footprint a straight walk into the hall's footprint has zero progress:
/// frame 19 keeps the goal and frame 20 removes both goal and marker (fixtures/README.md "Embody checks on the navmesh").
/// Poll and cached placement tests deliberately supply the original avatar position after local walking.
/// </summary>
public static class EmbodyWalkCheck
{
    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        var source = new FixtureSource(Path.Combine(fixtures, "embody"), fixtures);
        var world = new Node3D { Name = "EmbodyWalkWorld" };
        host.AddChild(world);
        var builder = new WorldBuilder(source, _ => { }, strict: true);
        FigureManager? manager = null;
        int count = 0;
        void Is(string name, bool ok) { count++; if (!ok) throw new InvalidOperationException("embody walking " + name); }
        void Near(string name, double got, double want, double tol = 2e-4) => Is($"{name}: {got:R} expected {want:R}", Math.Abs(got-want) <= tol);
        var none = new HashSet<string>();
        var w = new HashSet<string> { "w" };
        var d = new HashSet<string> { "d" };
        const double dt = 1.0/60;
        try
        {
            await builder.BuildAsync(world, "Fixture Hall");
            var hall = builder.Slots["loc-hall"];
            hall.Fade.Snap(1);
            // Plan E2 Task 6 (review N-W3): the hall's navigation is swapped in before the first step, so every section
            // below walks on the navmesh (clamp, click routes) whatever the bake timing.
            for (int i=0; i<240 && builder.NavFor(hall) is null; i++) await host.ToSignal(host.GetTree(),SceneTree.SignalName.PhysicsFrame);
            Is("navigation swapped in within 240 physics frames",builder.NavFor(hall) is not null);
            manager = new FigureManager(source, builder.Height!, _ => { }, strict: true)
            {
                AutoTick = false, ClipFit = ClipFitMode.OnDemandSync, Slots = () => builder.Slots,
                GroundMoveAt = builder.FigureGroundMove, GroundYAt = builder.FigureGroundY,
            };
            world.AddChild(manager);
            await manager.InitAsync();
            using var doc = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(fixtures, "embody", "worldmap.json")));
            await manager.Apply(doc.RootElement);
            await manager.EnsurePool();
            var fig = manager.Figures["fixture-avatar"];
            var steering = new PlayerSteering(manager, builder) { RoomId = "r-a" };
            steering.SetActive(true);
            void At(float x, float z, float y = .01f) { steering.CancelRoute(); manager.SnapPlayerTo(fig.CharacterName, new(x,y,z)); }
            void Frame(IReadOnlySet<string> keys, double yaw = 0) { steering.Step(dt, keys, yaw); manager.Tick(dt); }

            At(-3,1);
            Frame(w, Math.PI/4);
            Near("W1 W yaw pi/4 X", fig.Position.X, -3-3.4*dt/Math.Sqrt(2));
            Near("W1 W yaw pi/4 Z", fig.Position.Z, 1-3.4*dt/Math.Sqrt(2));
            foreach (var (key, x, z) in new[] { ("a", -1.0, 1.0), ("s", 1.0, 1.0), ("d", 1.0, -1.0) })
            {
                At(-3,1); Frame(new HashSet<string>{key}, Math.PI/4);
                Near("W1 " + key + " X", fig.Position.X, -3+x*3.4*dt/Math.Sqrt(2));
                Near("W1 " + key + " Z", fig.Position.Z, 1+z*3.4*dt/Math.Sqrt(2));
            }
            // Shift runs (walk.ts sprintHeld): W + Shift at pi/4 steps 3.4 * 1.8 * dt along (-sqrt(.5), -sqrt(.5));
            // Shift alone does not move the figure; releasing Shift walks at 3.4 * dt again.
            var wShift = new HashSet<string> { "w", "shift" };
            At(-3,1);
            Frame(wShift, Math.PI/4);
            Near("W1 Shift+W runs X", fig.Position.X, -3-3.4*1.8*dt/Math.Sqrt(2));
            Near("W1 Shift+W runs Z", fig.Position.Z, 1-3.4*1.8*dt/Math.Sqrt(2));
            Is("W1 Shift+W marks the figure sprinting", fig.Sprint);
            At(-3,1);
            Frame(new HashSet<string> { "shift" }, Math.PI/4);
            Near("W1 Shift alone stands X", fig.Position.X, -3);
            Near("W1 Shift alone stands Z", fig.Position.Z, 1);
            At(-3,1);
            Frame(wShift, Math.PI/4); Frame(w, Math.PI/4);
            Near("W1 Shift released walks X", fig.Position.X, -3-3.4*(1.8+1)*dt/Math.Sqrt(2));
            Is("W1 Shift released clears sprint", !fig.Sprint);
            At(5.7f,1); steering.RoomId = "r-b";
            for (int i=0; i<60; i++) { Frame(d, Math.PI/4); Is("W2 east clearance frame " + i, fig.Position.X <= 5.75001); }
            Is("W2 slides north after 1s", fig.Position.Z < -.5);
            At(-.3f,2);
            for (int i=0; i<15; i++) Frame(d);
            Is("W3 door gap passes", fig.Position.X > .4);
            At(7.96f,9); steering.RoomId = "";
            Frame(d, Math.PI/4);
            Near("W4 rock slides X", fig.Position.X, 7.96);
            Is("W4 rock slides north", fig.Position.Z < 9);
            At(9,0,0);
            Frame(d);
            Near("W5 metre step blocks", fig.Position.X, 9);
            At(-3,-3.75f); steering.RoomId = "r-a";
            // Plan E2 Task 6: inside the hall a click behind the north wall no longer walks into it — the navmesh plans the
            // way out through the outside door (case 2 of NavRoutePlanner); the walk's end goal stays the click. Plan E3
            // Task 10: that walk is the avatar's local walk order.
            Is("W6 nav: a click behind the wall starts a walk order on the navmesh", steering.WalkTo(new(-3,-8)) && steering.WalkOrderId is not null);
            Is("W6 nav: Route is the end goal", steering.Route is { X: -3, Z: -8 });
            // Review Task 10 (I-2): the order walks the navmesh to the outside door's outer point only; the straight walk
            // with its gates (Blocked, walls, navmesh clamp, loading hold, terrain pace, 20-frame stall) takes the rest.
            var w6Door = steering.WalkGoal;
            var w6Doors = builder.FootprintAt(-3, -3.75) is { } w6Hall ? builder.NavOutsideDoors(w6Hall) : Array.Empty<P2>();
            Is($"W6 nav: the order's goal ({w6Door?.X:0.###}, {w6Door?.Z:0.###}) is an outside door's outer point",
               w6Door is { } wd && System.Linq.Enumerable.Any(w6Doors, o => double.Hypot(o.X - wd.X, o.Z - wd.Z) <= 1e-6));
            int w6 = 0;
            for (; w6 < 600 && steering.WalkOrderId is not null; w6++) Frame(none);
            Frame(none);
            Is("W6 nav: at the door the straight walk takes the rest", steering.WalkOrderId is null && steering.Route is { X: -3, Z: -8 }
               && manager.OrderPlayerOf(fig.CharacterName) is null);
            for (; w6 < 1200 && steering.Route is not null; w6++) Frame(none);
            // The hall's only outside door is the south one (outer point (3, 3.65)); planner case 2 then goes straight to
            // (-3, -8), back across the hall. The straight walk's gates hold it at the north wall (z -3.65 on the eroded
            // mesh, the wall at z -4) and its 20-frame stall ends it there — it never passes the wall.
            Is($"W6 nav: the straight walk is held inside by the north wall and stalls ({fig.Position.X:0.###}, {fig.Position.Z:0.###}) after {w6} frames",
               steering.Route is null && manager.WalkTarget is not { Visible: true } && fig.Position.Z > -3.7 && fig.Position.Z < -3.5);
            steering.CancelRoute();
            // The straight walk keeps its 20-frame stall: outside every footprint (no navigation) behind the hall, the click
            // on its far side (-3, 8) walks into the hall's footprint, which is foreign with an authored opening → blocked;
            // the first lead (-3, -3.95) is already inside it, so every frame's target is the start (zero progress).
            At(-3,-4.1f); steering.RoomId = "";
            // Object actions retain their approach planner, route and marker.
            Is("W6 object approach behind building accepted", steering.WalkTo(new(-3,8)) && steering.WalkOrderId is null);
            Is("W6 marker visible", manager.WalkTarget is { Visible: true });
            for (int i=0; i<19; i++) Frame(none);
            Is("W6 frame19 retains route", steering.Route is not null);
            Frame(none);
            Is("W6 frame20 drops route and marker", steering.Route is null && manager.WalkTarget is not { Visible: true });
            At(7,9);
            bool approach = steering.WalkTo(new(9,9));
            var pick = PickChain.Resolve(null, "rock-info", () => approach, embodied: true);
            Is("W7 blocked object approach clears info", !approach && pick.Info == InfoChange.Clear && pick.InfoLocationId is null);
            Is("empty embodied ground clears info",PickChain.Resolve(null,null,embodied:true).Info==InfoChange.Clear);
            Is("overview still opens location info",PickChain.Resolve(null,"hall").Info==InfoChange.Show);
            int calls = 0;
            var figurePick = PickChain.Resolve("npc", "hall", () => { calls++; return true; });
            Is("figure precedes object action", calls == 0 && figurePick.Selected == "npc");
            Is("object action preserves info", PickChain.Resolve(null,"hall", () => true).Info == InfoChange.Unchanged);
            At(-3,1);
            for (int i=0; i<30; i++) Frame(w);
            var walked = fig.Position;
            var localTarget = fig.Target;
            fig.Face = Vector3.Left;
            await manager.Apply(doc.RootElement);
            Near("poll preserves local position", fig.Position.Z, walked.Z);
            Near("poll preserves local target", fig.Target.Z, localTarget.Z);
            manager.TickPlacement();
            Is("poll and cached placement preserve facing", fig.Face == Vector3.Left);
            for (int i=0; i<120; i++) { manager.TickPlacement(); Frame(none); }
            Is("cached placement does not rewind", fig.Position.Z < -.6 && fig.Position.Z > -1);
            Is("local avatar has no route or reckoning", fig.Route is null && fig.Reckon is null && !fig.Travelling);
            Is("WASD overrides object approach", steering.WalkTo(new(-4,-2)));
            Frame(d);
            Is("key cancels route and marker", steering.Route is null && manager.WalkTarget is not { Visible: true });
            At(7,0);
            Is("foreign authored footprint blocks", !steering.WalkTo(new(0,0)));
            Is("free footprint boundary passes", steering.WalkTo(new(24,0)));
            steering.CancelRoute();
            steering.RememberRefused(new(8,0),new P2(7,0));
            Is("refused disc blocks", !steering.WalkTo(new(8,0)));
            for (int i=0; i<241; i++) steering.Step(dt,none,0);
            Is("refused disc expires after 4s", steering.WalkTo(new(8,0)));
            steering.CancelRoute();
            steering.RememberRefused(new(7.5,0),new P2(7,0));
            Is("refusal containing home is skipped", steering.WalkTo(new(7.5,0)));
            steering.CancelRoute();
            for (int i=0; i<9; i++) steering.RememberRefused(new(10+i,6),new P2(7,0));
            Is("refused memory keeps eight", steering.WalkTo(new(10,6)));
            Is("newest refused disc blocks", !steering.WalkTo(new(18,6)));
            steering.CancelRoute();
            At(-3,1,3.01f); steering.RoomId="r-up";
            Is("upper-floor object approach plans goal", steering.WalkTo(new(-2.01,0)));
            Near("upper-floor object approach X",steering.Route!.Value.X,-2.01);
            Near("upper room floor",builder.PlayerFloorY(hall,"r-up",-3,1),3.03);
            Is("unknown room has no walls",builder.PlayerWalls(hall,"unknown") is null);
            hall.Fade.Snap(0);
            Is("closed interior has no invisible walls",builder.PlayerWalls(hall,"r-a") is null);
            hall.Fade.Snap(1);
            var unrotated=builder.PlayerWalls(hall,"r-a")!.Value;
            var savedFrame=hall.Stands.Frame;
            hall.Stands.Frame=new(new Vec3(40,2,20),Math.PI/2);
            var rotated=builder.PlayerWalls(hall,"r-a")!.Value;
            var first=unrotated.Segments[0];
            var a=AnimaNative.Scene.SceneView.TileToWorld(hall.Stands.Frame,first.Ax,first.Az);
            var b=AnimaNative.Scene.SceneView.TileToWorld(hall.Stands.Frame,first.Bx,first.Bz);
            Near("rotated wall A X",rotated.Segments[0].Ax,a.X);
            Near("rotated wall A Z",rotated.Segments[0].Az,a.Z);
            Near("rotated wall B X",rotated.Segments[0].Bx,b.X);
            Near("rotated wall B Z",rotated.Segments[0].Bz,b.Z);
            hall.Stands.Frame=savedFrame;
            Is("wall cache invalidates frame",builder.PlayerWalls(hall,"r-a")!.Value.Segments[0]==first);
            At(-3,1); steering.RoomId="r-a";
            Frame(w);
            steering.MovementLocked=true;
            var locked=fig.Position; Frame(w);
            Is("movement lock stops residual target",fig.Position.DistanceTo(locked)<1e-5);
            steering.MovementLocked=false;
            hall.Ready=false;
            Frame(w);
            Is("unready approach holds and pins",fig.Position.DistanceTo(locked)<1e-5 && builder.StreamPins["approach"]=="loc-hall");
            hall.Ready=true;
            Frame(w);
            Is("ready approach resumes",fig.Position.Z<locked.Z);
            steering.SetActive(false);
            Is("exit releases approach pin",!builder.StreamPins.ContainsKey("approach"));
            await manager.Apply(doc.RootElement);
            Is("exit resumes poll placement", fig.Target.Z == 1);
            var seatedMap=JsonNode.Parse(doc.RootElement.GetRawText())!;
            seatedMap["characters"]![0]!["place"]=new JsonObject { ["id"]="room-seat", ["slot"]=0 };
            using var seatDoc=JsonDocument.Parse(seatedMap.ToJsonString());
            await manager.Apply(seatDoc.RootElement);
            Is("seat fixture is placed",manager.LastPlans[fig.CharacterName].Rule=="seat");
            steering.SetActive(true);
            At(-3,1,.5f);
            var body=new Node3D(); var player=new AnimationPlayer(); body.AddChild(player);
            var library=new AnimationLibrary();
            string idle=FigureClips.PoseKind("standing",fig.Poses);
            string walking=FigureClips.PoseKind("walking",fig.Poses);
            var standClip=new Animation { Length=1,LoopMode=Animation.LoopModeEnum.Linear };
            var walkClip=new Animation { Length=1,LoopMode=Animation.LoopModeEnum.Linear };
            var bridgeClip=new Animation { Length=.2 };
            var stopClip=new Animation { Length=1 };
            library.AddAnimation(idle,standClip); library.AddAnimation(walking,walkClip); library.AddAnimation("get-up",bridgeClip); library.AddAnimation("stop",stopClip);
            player.AddAnimationLibrary("",library);
            fig.SetBody(body,true,null,player,new[] {idle,walking,"get-up","stop"},bodyHeight:1.7);
            Is("replacement body clears previous clip-plan callbacks",fig.RefreshClipKinds is null && fig.FitClip is null);
            fig.BaseScale=1;
            fig.Clock=()=>manager.Clock;
            fig.Transitions=new[] { new ClipTransition(idle,walking,"get-up",0) };
            fig.Play(idle); fig.FaceTowards(Vector3.Back,snap:true);
            var heldStart=fig.Position;
            Frame(d);
            Is("holding bridge opens before first step",fig.Bridging && new Vector2(fig.Position.X-heldStart.X,fig.Position.Z-heldStart.Z).Length()<1e-5);
            Near("holding bridge facing stays",fig.Yaw,0);
            Is("standing source is held under renewed keys",fig.BridgeFrom==idle && !fig.CancelStopBridge(walking));
            Near("short stand-up tap grounds target before bridge hold",fig.Target.Y,.01);
            Frame(none);
            for (int i=0; i<40; i++) Frame(none);
            Near("released stand-up stays grounded",fig.Position.Y,.01,.04);
            // A new held-key bridge exercises the facing snap independently of the released seat bridge.
            fig.Play(idle); Frame(d);
            for (int i=0; i<20 && fig.Bridging; i++) Frame(d);
            Frame(d);
            Is("bridge ends and movement resumes",!fig.Bridging && fig.Position.X>heldStart.X);
            Near("bridge release snaps facing",fig.Yaw,Math.PI/2);
            Frame(none);
            fig.Transitions=new[] { new ClipTransition(idle,walking,"get-up",.5) };
            fig.Play(idle);
            Frame(d);
            Is("ramping bridge starts",fig.Bridging && fig.BridgePace>0);
            Frame(none);
            Is("release cancels ramping bridge",!fig.Bridging);
            // A stop bridge is the only holding bridge renewed keys may abandon.
            // Include a holding start rule: cancellation must not open that rule again.
            fig.Transitions=Array.Empty<ClipTransition>();
            fig.Play(walking); fig.Target=fig.Position;
            fig.Transitions=new[] { new ClipTransition(walking,idle,"stop",0), new ClipTransition(idle,walking,"get-up",0) };
            fig.Play(idle);
            Is("stop remembers walking source",fig.Bridging && fig.BridgeFrom==walking);
            var stopStart=fig.Position;
            // Plan E3 Task 10: a click inside the hall is the avatar's local walk order; the order draws the figure from its
            // first frame on and lets the stop bridge go at once (as renewed keys do) instead of waiting for it.
            Is("click walk planned while stop holds",steering.WalkTo(new(fig.Position.X+1,fig.Position.Z)) && steering.WalkOrderId is not null);
            Frame(none);
            // (The order plays the walking clip; a start rule idle → walking may open its bridge then — the order moves on.)
            Is("click walk order lets the stop go and walks",fig.BridgeFrom!=walking && fig.Position.X>stopStart.X && steering.WalkOrderId is not null);
            // Review Task 11 I1: the click walk (3.4 m/s, NpcWalk.WalkSpeed) keeps the key walk's clip pace, never 3.4 / 1.4 ≈ 2.4×.
            if (fig.Bridging) fig.CancelBridge(); // the start bridge holds the clip's pace; the walk's own frame follows
            Frame(none);
            GD.Print($"[embody] click walk clip: bridging {fig.Bridging} scale {fig.Player?.SpeedScale} pace {fig.CurrentPace}");
            Is("click walk clip at the key walk's pace",!fig.Bridging && fig.Player is { } cwp && Math.Abs(cwp.SpeedScale-fig.CurrentPace)<1e-6);
            steering.CancelRoute();
            Is("cancel ends the click walk order",steering.WalkOrderId is null && !manager.HasLiveOrder(fig.CharacterName) && manager.OrderPlayerOf(fig.CharacterName) is null);
            // The stop bridge again, for the keys (the start bridge the order's walking clip opened let go first).
            if (fig.Bridging) fig.CancelBridge();
            fig.Transitions=Array.Empty<ClipTransition>();
            fig.Play(walking); fig.Target=fig.Position;
            fig.Transitions=new[] { new ClipTransition(walking,idle,"stop",0), new ClipTransition(idle,walking,"get-up",0) };
            fig.Play(idle);
            Is("stop remembers walking source again",fig.Bridging && fig.BridgeFrom==walking);
            stopStart=fig.Position;
            Frame(d);
            Is("renewed keys cancel stop in same frame",!fig.Bridging && fig.Position.X>stopStart.X);
            Is("stop source cleared and walk crossfades",fig.BridgeFrom is null && fig.CurrentKind==walking && fig.CurrentClip==walking);
            Is("cancelled stop opens no start rule",fig.PaceLimitFor(walking)==1);
            fig.Transitions=Array.Empty<ClipTransition>();
            fig.Play(idle);
            fig.Transitions=new[] { new ClipTransition(idle,walking,"get-up",0) };
            fig.Extras=new Dictionary<Animation,ClipExtras> { [bridgeClip]=new() { Path=new RootPath(new float[] {0,.2f},new float[] {0,0,0,.4f}) } };
            fig.Play(walking);
            fig.UpdateFigure(.2);
            Is("completed bridge holds travel",!fig.Bridging && fig.HoldsTravel);
            var beforeTravel=fig.Position; var goalBeforeTravel=fig.Target;
            Is("player travel hands over",manager.TakePlayerTravel(fig.CharacterName) is not null);
            Near("travel root shift",fig.Position.DistanceTo(beforeTravel),.4);
            Is("travel shifts goal equally",((fig.Target-goalBeforeTravel)-(fig.Position-beforeTravel)).Length()<1e-5);
            Is("travel is taken once",manager.TakePlayerTravel(fig.CharacterName) is null);
            steering.SetActive(false);
            return $"walking={count} W1-W7=ok local_poll=held stall=20";
        }
        finally
        {
            builder.StopResidency(); builder.Models?.FreeAll(); world.QueueFree();
            // Task 49: standalone embody runs can quit immediately; flush queued nodes before returning.
            await host.ToSignal(host.GetTree(),SceneTree.SignalName.ProcessFrame);
            await host.ToSignal(host.GetTree(),SceneTree.SignalName.ProcessFrame);
        }
    }
}
