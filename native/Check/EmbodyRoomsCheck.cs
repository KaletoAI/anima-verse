using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Api;
using System.Threading.Tasks;
using AnimaNative.Embody;
using AnimaNative.Figures;
using AnimaNative.Hud;
using AnimaNative.Overview;
using AnimaNative.Scene;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// Task 51 / E7-T6 R-cases. Hall A/B centres (-3,0)/(3,0); B owns (3,2), so the request is due
/// at 1500 ms, not 1499. Stair run x=.5..3 rises 0..3: at x=1.75 ramp y=1.51; head (3.5,3.01,-2).
/// At frame 31, x=31*17/300=1.7566666667 and ramp y=.01+(x-.5)*3/2.5=1.518.
/// Lift pads top at .01/3.01. Door within 2 m: .1 s * 3 rad/s = .3 rad, capped at 85 degrees.
/// All expectations are literals independent of production helpers. Uses actual mounted meshes and movement.
/// </summary>
public static class EmbodyRoomsCheck
{
    public static async Task<string> RunAsync(Node3D host,string fixtures)
    {
        int n=0;
        void Is(string label,bool value) { n++; if (!value) throw new InvalidOperationException("embody rooms "+label); }
        void Near(string label,double got,double want,double eps=.0002) => Is($"{label}: {got:R} expected {want:R}",Math.Abs(got-want)<=eps);
        var source=new FixtureSource(Path.Combine(fixtures,"embody"),fixtures);
        var world=new Node3D(); host.AddChild(world);
        var builder=new WorldBuilder(source,_=>{},strict:true);
        var hud=new HudOverlay();
        AvatarRoomsController? rooms=null;
        try
        {
            await builder.BuildAsync(world,"Fixture Hall");
            var hall=builder.Slots["loc-hall"]; builder.SetOpen("loc-hall",true); hall.Fade.Snap(1);
            var manager=new FigureManager(source,builder.Height!,_=>{},strict:true)
            { AutoTick=false, ClipFit=ClipFitMode.OnDemandSync, Slots=()=>builder.Slots, GroundMoveAt=builder.FigureGroundMove, GroundYAt=builder.FigureGroundY };
            world.AddChild(manager); await manager.InitAsync(); manager.SetProcess(false);
            using var map=await source.GetWorldMapAsync(); await manager.Apply(map.RootElement); await manager.EnsurePool();
            var f=manager.Figures[manager.AvatarName];
            var steering=new PlayerSteering(manager,builder) { RoomId="r-a" }; steering.SetActive(true);
            double now=0;
            rooms=new(manager,builder,steering,source,hud,()=>now);
            rooms.SetActive(true); hud.SetState("mode","embodied");
            void At(float x,float z,float y=.01f) { steering.CancelRoute(); manager.SnapPlayerTo(f.CharacterName,new(x,y,z)); }
            At(-.3f,2);
            for(int i=0;i<12;i++) { steering.Step(1.0/60,new HashSet<string>{"d"},0); manager.Tick(1.0/60); }
            Is("R1 walks through party doorway into B",f.Position.X>.3 && steering.RoomId=="r-a");
            source.SelectRoomScenario("enter-room"); rooms.Tick();
            now=1499; rooms.Tick(); Is("R1 hold before 1.5s",source.RoomRequests.Count==0);
            now=1500; rooms.Tick(); await rooms.Channel.Pending!;
            Is("R1 exactly one enter-room B",source.RoomRequests.SequenceEqual(new[]{"r-b"}));
            now=3000; rooms.Tick(); Is("R1 waits for confirmation",source.RoomRequests.Count==1);
            steering.RoomId="r-b"; rooms.Tick(); Is("R1 confirmation retires requested",rooms.Channel.RequestedRoom is null);
            source.SelectRoomScenario("enter-room-refused");
            Is("R2 refusal",!await rooms.Channel.EnterAsync("locked-room"));
            now=6999; Is("R2 refused 3999ms",rooms.Channel.Rejected("locked-room"));
            now=7000; Is("R2 expires at 4s",!rooms.Channel.Rejected("locked-room"));

            // Ride target is explicit fixture data; adding a script row never synthesizes a map poll.
            source.SelectRoomScenario("stairs-up"); At(0,-2); rooms.UpdateOffers();
            Is("R3 stair offer bus names",hud.SceneOwned("stairs")?["dest"]?["level"]?.GetValue<int>()==1);
            await rooms.RideStairsAsync();
            Is("R3 owned ride armed",f.Ride?.Armed==true && steering.VerticalRide is not null);
            Near("R3 four second deadline",steering.VerticalRide!.Until-steering.Clock,4);
            Is("R3 follows storey",hall.LevelFilter==1 && steering.RoomId=="r-up");
            Is("R3 offers clear at start",hud.SceneOwned("stairs") is null && hud.SceneOwned("elevator") is null);
            var none=new HashSet<string>();
            for(int i=0;i<31;i++) { steering.Step(1.0/60,none,0); manager.Tick(1.0/60); }
            Near("R3 hand ramp X",f.Position.X,1.7566666667); Near("R3 hand ramp height",f.Position.Y,1.518);
            for(int i=31;i<240;i++) { steering.Step(1.0/60,none,0); manager.Tick(1.0/60); }
            Near("R3 head X",f.Position.X,3.5,.05); Near("R3 head Y",f.Position.Y,3.01); Near("R3 head Z",f.Position.Z,-2);
            Is("R3 ownership released",steering.VerticalRide is null && f.Ride is null);
            builder.SetLevel("loc-hall",0); rooms.Tick(); Is("R3 manual view persists",hall.LevelFilter==0);
            steering.RoomId="r-b"; rooms.Tick(); steering.RoomId="r-up"; rooms.Tick(); Is("R3 server storey edge follows",hall.LevelFilter==1);

            steering.RoomId="r-b"; At(3,2); rooms.UpdateOffers();
            Is("R4 lift offer levels",hud.SceneOwned("elevator")?["levels"]?.AsArray().Count==2);
            source.SelectRoomScenario("lift-up");
            hud.RouteSceneKey(new InputEventKey { Keycode=Key.F,Pressed=true });
            await rooms.PendingRide!;
            Is("R4 sole option rides immediately",steering.VerticalRide is not null && !hud.SceneOwned("elevatorOpen")!.GetValue<bool>());
            for(int i=0;i<240;i++) { steering.Step(1.0/60,none,0); manager.Tick(1.0/60); }
            Near("R4 lift top Y",f.Position.Y,3.01);
            hall.Places.ElevatorStops[2]=new(4,6.01,2); hall.Stands.RoomCenters["third"]=new(4,6.01,2); hall.Stands.RoomLevels["third"]=2;
            rooms.FloorRoomIds=new Dictionary<int,string>{{2,"third"}};
            steering.RoomId="r-b"; At(3,2); rooms.UpdateOffers();
            hud.RouteSceneKey(new InputEventKey { Keycode=Key.F,Pressed=true });
            Is("R4 two options opens picker",hud.SceneOwned("elevatorOpen")!.GetValue<bool>() && steering.VerticalRide is null);
            hud.SetState("talkTarget",new JsonObject { ["dist"]=.1 }); rooms.SyncElevatorPicker();
            Is("R4 nearer offer folds picker",!hud.SceneOwned("elevatorOpen")!.GetValue<bool>());
            hud.SetState("talkTarget",null);

            // The stair mesh has its own shared-shader material clones; walking to it never queues a ride.
            At(-3,-2); steering.RoomId="r-a"; rooms.UpdateOffers();
            var rayO=new Vec3(1.75,10,-2); var rayD=new Vec3(0,-1,0);
            Is("R5 actual stair triangles hit",rooms.Picking.Hit(rayO,rayD) is { Target.Kind:"stairs" });
            var hit=rooms.Picking.Hit(rayO,rayD)!;
            var mesh=hit.Mesh; var original=mesh.GetActiveMaterial(0);
            rooms.Picking.Hover(hit);
            Is("R5 hover clones material",mesh.GetActiveMaterial(0)!=original);
            if(original is ShaderMaterial shader) Is("R5 shares shader",(mesh.GetActiveMaterial(0) as ShaderMaterial)?.Shader==shader.Shader);
            rooms.Picking.Hover(null); Is("R5 restores material",mesh.GetActiveMaterial(0)==original);
            rooms.UseVertical(hit.Target); Is("R5 walks to foot only",steering.Route is { X:0,Z:-2 } && steering.VerticalRide is null);
            Is("R5 marker mounted",manager.WalkTarget?.Visible==true);

            var doorNode=new Node3D(); hall.Group.AddChild(doorNode);
            var door=new DoorProp { Group=doorNode,Swing=1,At=new(0,2),Level=0,Rooms=new[]{"r-a","r-b"},BaseYaw=0 };
            var spec=hall.Scene!.Models.First();
            hall.Placements.Add(new PlacedModel { Spec=spec,Parent=hall.Group,Node=doorNode,Door=door });
            rooms.SetActive(false); At(-1,2); steering.RoomId="r-a";
            builder.TickProps(.1,null,Vector3.Zero,0,f.Position,"r-a");
            Near("R6 overview door 3rad/s",door.Angle,.3);
            builder.TickProps(.1,null,Vector3.Zero,0,f.Position,"r-a"); Near("R6 door second frame",door.Angle,.6);
            builder.SetLocks(new(new Dictionary<string,string>{{"r-b",""}},"loc-hall",new Dictionary<string,string>(),"r-a"));
            builder.TickProps(.1,null,Vector3.Zero,0,f.Position,"r-a"); Near("R6 locked closes",door.Angle,.3);
            builder.SetLocks(LockState.None);
            builder.TickProps(.1,null,Vector3.Zero,0,f.Position,"r-up"); Near("R6 own storey gates",door.Angle,0);
            rooms.SetActive(true); rooms.UpdateOffers(); rooms.SetActive(false);
            Is("R7 exit clears HUD",hud.SceneOwned("stairs") is null && hud.SceneOwned("elevator") is null && !hud.SceneOwned("elevatorOpen")!.GetValue<bool>());
            // Regression: plan_hull is a payload boolean, not a display string. Smallest overlapping room wins.
            var model=hall.Scene!.Models[0]; hall.Scene.Models[0]=model with { Role="building",Display="shell",PlanHull=true };
            hall.Stands.AlwaysVisible.Add("r-a");
            string? opened="unset"; rooms.AutoOpen=id=>opened=id;
            steering.RoomId="r-a"; At(-3,1); rooms.SetActive(true); rooms.Tick();
            Is("R8 plan hull outdoor zone closes",opened is null);
            hall.RoomRects.Add(new("hut",new(-3,1,1,1))); rooms.Tick();
            Is("R8 smaller indoor rectangle opens",opened=="loc-hall");
            hall.RoomRects.RemoveAt(hall.RoomRects.Count-1); hall.Stands.AlwaysVisible.Remove("r-a"); hall.Scene.Models[0]=model;
            rooms.AutoOpen=null;

            // Regression: a position response and a poll both sampled before the room acknowledgement cannot undo it.
            At(0,-2); steering.RoomId="r-a";
            var positionReply=new TaskCompletionSource<PositionAnswer>();
            var posChannel=new PositionChannel((_,_)=>positionReply.Task,()=>now,"rooms-position");
            using var position=new AvatarPositionController(manager,builder,steering,source,()=>now,posChannel);
            position.SetActive(true); rooms.AdoptRoom=position.AdoptRoom;
            posChannel.Tick(new(0,-2),true); Is("R9 old position really in flight",posChannel.InFlight);
            double oldPoll=now; now+=100;
            source.SelectRoomScenario("stairs-up"); rooms.UpdateOffers(); await rooms.RideStairsAsync();
            using var reply=JsonDocument.Parse("{\"ok\":true,\"room_id\":\"r-a\"}");
            positionReply.SetResult(new(200,reply.RootElement.Clone())); await posChannel.WhenIdle;
            Is("R9 old position answer cannot undo ride",steering.RoomId=="r-up");
            using var stale=new MapReceipt(oldPoll,now,now).Attach(map.RootElement); await manager.Apply(stale.RootElement);
            Is("R9 old poll cannot undo ride",steering.RoomId=="r-up");
            position.CorrectTo(new(0,-2));
            Is("R9 correction releases vertical owner",steering.VerticalRide is null && f.Ride is null);
            rooms.Channel.Reset(); At(3,2); steering.RoomId="foreign-ground"; rooms.GroundRoomId="foreign-ground";
            source.SelectRoomScenario("enter-room"); now+=100; rooms.Tick(); now+=1500; rooms.Tick();
            Is("R10 foreign ground ID cannot become a room here",source.RoomRequests.Count==0);
            return $"rooms={n} R1-R10=ok hold=1500 reject=4000 confirm=10000 ride=4s head=(3.5,3.01,-2) door=3rad/s";
        }
        finally
        {
            rooms?.Dispose(); hud.Free(); builder.StopResidency(); builder.Models?.FreeAll(); world.QueueFree();
            await host.ToSignal(host.GetTree(),SceneTree.SignalName.ProcessFrame);
            await host.ToSignal(host.GetTree(),SceneTree.SignalName.ProcessFrame);
        }
    }
}
