using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Embody;
using AnimaNative.Figures;
using AnimaNative.Hud;
using AnimaNative.Overview;
using AnimaNative.Scene;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// Task 52 / E7-T7 O-cases use the mounted Task 46 world and actual HUD, steering and write adapters.
/// Gate (3,4), inward (0,-1): walk-in ends at (3,3.5), strictly inside z=4. Locked gate is (40,4).
/// Three independent offer points exercise talk 2.4 vs stairs 1, talk alone, and entry alone.
/// Room-seat has two free slots and two poses; its numbered slot is a hard snap, not a walking goal.
/// </summary>
public static class EmbodyOffersCheck
{
    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        int n=0;
        void Is(string label,bool ok) { n++; if(!ok) throw new InvalidOperationException("embody offers "+label); }
        void Near(string label,double got,double want) => Is($"{label}: {got:R}, expected {want:R}",Math.Abs(got-want)<.0002);
        var source=new FixtureSource(Path.Combine(fixtures,"embody"),fixtures);
        var world=new Node3D(); host.AddChild(world);
        var builder=new WorldBuilder(source,_=>{},strict:true);
        var hud=new HudOverlay();
        AvatarOffersController? offers=null;
        AvatarPositionController? position=null;
        try
        {
            await builder.BuildAsync(world,"Fixture Hall");
            var hall=builder.Slots["loc-hall"]; builder.SetOpen("loc-hall",true); hall.Fade.Snap(1);
            var manager=new FigureManager(source,builder.Height!,_=>{},strict:true)
            { AutoTick=false,ClipFit=ClipFitMode.OnDemandSync,Slots=()=>builder.Slots,GroundYAt=builder.FigureGroundY };
            world.AddChild(manager); await manager.InitAsync(); manager.SetProcess(false);
            using var map=await source.GetWorldMapAsync(); await manager.Apply(map.RootElement); await manager.EnsurePool();
            var f=manager.Figures[manager.AvatarName];
            var steering=new PlayerSteering(manager,builder) { RoomId="r-a" }; steering.SetActive(true);
            double now=100;
            // The real position channel is exercised explicitly at the crossing with a strict scripted request.
            var channel=new PositionChannel(source.ReportPositionAsync,()=>now,"fixture-entry-52");
            position=new(manager,builder,steering,source,()=>now,channel);
            position.SetActive(true,map.RootElement);
            offers=new(manager,builder,steering,source,hud,position,()=>now);
            offers.SetActive(true); hud.SetState("mode","embodied");
            var toasts=new List<string>(); offers.Toast=toasts.Add;
            void At(float x,float z) { steering.CancelRoute(); manager.SnapPlayerTo(f.CharacterName,new(x,.01f,z)); }
            var npc=manager.Figures["fixture-npc"];
            At(-3,1); npc.SnapTo(new(-3,.01f,3.4f)); npc.SetHidden(false);
            offers.UpdateOffers();
            Near("O1 live talk distance",hud.SceneOwned("talkTarget")!["dist"]!.GetValue<double>(),2.4);
            hud.SetState("stairs",new JsonObject { ["dist"]=1.0 });
            Is("O1 stairs wins 2.4 vs 1.0",offers.NearestOffer=="stairs");
            hud.SetState("stairs",null); At(-3,2); offers.UpdateOffers();
            Is("O1 second point talk",offers.NearestOffer=="talk");
            npc.SetHidden(true); offers.UpdateOffers(); Is("O1 hidden NPC excluded",hud.SceneOwned("talkTarget") is null);
            At(3,5); offers.UpdateOffers(); Is("O1 third point enter",offers.NearestOffer=="enter");
            At(40,5); offers.LockedLocations=new Dictionary<string,string>{{"loc-locked","Fixture gate is locked."}};
            offers.UpdateOffers();
            Is("O2 locked offer private",offers.HasLockedEntry && hud.SceneOwned("enterOffer") is null);
            hud.RouteSceneKey(new InputEventKey { Keycode=Key.F,Pressed=true }); await offers.PendingEntry!;
            Is("O2 toast without walking",toasts.Last()=="Fixture gate is locked." && steering.WalkIn is null);
            At(3,5);
            position.SetActive(false);
            var outside=JsonNode.Parse(map.RootElement.GetRawText())!;
            outside["characters"]![0]!["location_id"]=""; outside["characters"]![0]!["room_id"]="";
            outside["characters"]![0]!["pos"]=new JsonObject { ["x"]=3,["z"]=5 };
            using(var exterior=JsonDocument.Parse(outside.ToJsonString())) position.SetActive(true,exterior.RootElement);
            Is("O3 starts outside any location",position.LocationId=="");
            offers.UpdateOffers(); await offers.EnterAsync();
            Is("O3 walk-in owns root",steering.WalkIn is not null);
            Near("O3 goal X",steering.WalkIn!.Goal.X,3); Near("O3 inward .5m",steering.WalkIn.Goal.Z,3.5);
            Near("O3 four seconds",steering.WalkIn.Until-steering.Clock,4);
            // Reports stay enabled during guided movement; the endpoint determines the new location.
            for(int i=0;i<120;i++) { steering.Step(1.0/60,new HashSet<string>(),0); manager.Tick(1.0/60); }
            // 26 steps * (3.4/60) = 1.473333...; ordinary movement stops within its .05 m arrival gate.
            Near("O3 crossed opening",f.Position.Z,3.5266666667);
            source.SelectPositionScenario("entry-crossing"); now=330;
            manager.Tick(0); await channel.WhenIdle;
            Is("O3 report adopts destination",position.LocationId=="loc-hall" && position.RoomId=="r-b" && source.PositionRequests.Count==1);
            position.SetActive(false);

            At(-3,1); steering.RoomId="r-a";
            var diorama=hall.Placements.Single(p=>p.Spec.Role=="room").Node!;
            diorama.Visible=false;
            source.SelectPlaceScenario("take-room-pose"); await offers.RefreshPlacesAsync();
            Is("O4 two free rings",offers.Places.RingCount==2);
            var ring=offers.Places.Rings[0];
            Is("O4 ring ray opens menu",offers.Pick(new(ring.X+.285,ring.Y+2,ring.Z),new(0,-1,0),new(120,80)));
            Is("O4 two labelled poses",hud.SceneOwned("placeMenu")!["offer"]!["poses"]!.AsArray().Count==2);
            Near("O4 menu CSS X",hud.SceneOwned("placeMenu")!["x"]!.GetValue<double>(),120);
            var activityGate=new TaskCompletionSource(); source.ActivityBarrier=activityGate.Task;
            hud.Handlers["pickRoomPose"](new JsonArray("room-seat","sitting"));
            Is("O4 pending write owns infinity",double.IsPositiveInfinity(position.OwnSeatChangeAt) && steering.SeatWritePending);
            position.SetActive(true,map.RootElement);
            var stale=JsonNode.Parse(map.RootElement.GetRawText())!;
            stale["characters"]![0]!["activity_animation"]="reading";
            stale["characters"]![0]!["pos"]=new JsonObject { ["x"]=40,["z"]=5 };
            using(var old=JsonDocument.Parse(stale.ToJsonString()))
            {
                string activity=f.Activity; var before=f.Position;
                await manager.Apply(old.RootElement);
                Is("O4 stale position and clip held",f.Position==before && f.Activity==activity);
            }
            activityGate.SetResult(); await offers.PendingActivity!; source.ActivityBarrier=null;
            Is("O4 acknowledged seat blocks position reports",!channel.CanReport());
            position.SetActive(false);
            Is("O4 exact pose post",source.ActivityRequests.Count==1 && source.ActivityRequests[0].ToJsonString()=="{\"place_id\":\"room-seat\",\"pose\":\"sitting\"}");
            Is("O4 menu closes",hud.SceneOwned("placeMenu") is null);
            var seated=JsonNode.Parse(map.RootElement.GetRawText())!.AsObject();
            seated["characters"]![0]!["place"]=new JsonObject { ["id"]="room-seat",["room_id"]="r-a",["slot"]=1 };
            using var seatDoc=JsonDocument.Parse(seated.ToJsonString()); now=500;
            offers.ReconcilePlace(seatDoc.RootElement,500);
            var seat=hall.Places.Markers["r-a"]["room-seat"].Slots[1];
            Near("O5 slot snap X",f.Position.X,seat.X); Near("O5 slot snap Y",f.Position.Y,seat.Y); Near("O5 slot snap Z",f.Position.Z,seat.Z);
            Is("O5 avatar seated",steering.AvatarSeated);
            seated["characters"]![0]!["activity_animation"]="reading";
            using(var changed=JsonDocument.Parse(seated.ToJsonString())) offers.ReconcilePlace(changed.RootElement,500);
            Is("O5 same slot accepts new pose clip",f.Activity=="reading");
            var standGate=new TaskCompletionSource(); source.ActivityBarrier=standGate.Task;
            int inputs=0; var onInput=steering.SteeringInput;
            steering.SteeringInput=p=> { inputs++; onInput?.Invoke(p); };
            steering.Step(.016,new HashSet<string>{"w"},0);
            steering.Step(.016,new HashSet<string>{"d"},0);
            Is("O6 pending stand-up keeps local input",inputs==2);
            standGate.SetResult(); await offers.PendingActivity!; source.ActivityBarrier=null; steering.SteeringInput=onInput;
            Is("O6 stand-up post",source.ActivityRequests.Count==2 && source.ActivityRequests[1].ToJsonString()=="{\"activity\":\"\"}");
            Is("O6 stand-up clears seat",!steering.AvatarSeated);
            steering.Step(.016,new HashSet<string>{"w"},0);
            Is("O6 held key posts only once",source.ActivityRequests.Count==2);
            offers.ReconcilePlace(seatDoc.RootElement,499);
            Is("O6 stale seat ignored",!steering.AvatarSeated);
            // A real mounted room mesh replaces rings. The hit's xz must stay within .6 m of a free slot.
            diorama.Visible=true; offers.Tick();
            Is("O7 mounted diorama replaces rings",offers.Places.RingCount==0);
            var inside=offers.Places.Hit(new(-3.3,8,.59),new(0,-1,0));
            Is("O7 diorama .59m accepted "+string.Join(";",Meshes(diorama).Select(m=>$"visible={m.IsVisibleInTree()} bounds={m.GlobalTransform*m.GetAabb()}")),inside is { Id:"room-seat",Diorama:true });
            Is("O7 diorama .61m rejected",offers.Places.Hit(new(-3.3,8,.61),new(0,-1,0)) is null);
            offers.Places.Hover(inside);
            var lit=Meshes(diorama).Where(m=>m.MaterialOverlay is not null).ToArray();
            Is("O7 shared spot material",lit.Length>0 && lit.All(m=>ReferenceEquals(m.MaterialOverlay,PlaceTargets.SharedSpotMaterial)));
            offers.Places.ClearHover(); Is("O7 hover restores materials",lit.All(m=>m.MaterialOverlay is null));

            // Same numbered slot, new pose and a quarter-turn footprint: local +Z faces world +X.
            var marker=hall.Places.Markers["r-a"]["room-seat"];
            hall.Places.Markers["r-a"]["room-seat"]=new PlaceEntry { Id=marker.Id,RoomId=marker.RoomId,Group=marker.Group,
                Slots=marker.Slots,Rotation=0,Tilt=12,Roll=-7,Diorama=true };
            hall.Stands.Frame=new(hall.Stands.Frame.Center,Math.PI/2);
            now=600; offers.ReconcilePlace(seatDoc.RootElement,600);
            Near("O8 footprint-facing X",f.Face!.Value.X,1); Near("O8 footprint-facing Z",f.Face.Value.Z,0);
            Near("O8 tilt",f.Lean!.Value.Tilt,12); Near("O8 roll",f.Lean.Value.Roll,-7);
            source.SelectPlaceScenario("take-room-pose"); await offers.RefreshPlacesAsync();
            await offers.PickRoomPoseAsync("room-seat","sitting");
            Is("O8 seated object approach creates route",steering.WalkTo(new(-2,2)));
            steering.Step(.016,new HashSet<string>(),0); await offers.PendingActivity!;
            Is("O8 second seat stands up again",source.ActivityRequests.Count==2 && !steering.AvatarSeated);
            Is("O8 stand-up preserves object approach route",steering.Route is not null);
            source.SelectPlaceScenario("places-refresh-race"); now=700;
            var firstGate=new TaskCompletionSource(); var secondGate=new TaskCompletionSource();
            source.PlacesBarrier=firstGate.Task; var first=offers.RefreshPlacesAsync();
            source.PlacesBarrier=secondGate.Task; var second=offers.RefreshPlacesAsync();
            firstGate.SetResult(); await first;
            Is("O9 older GET can apply while newer GET is pending",offers.Pick(new(-3.3,8,.1),new(0,-1,0),new(120,80))
                && hud.SceneOwned("placeMenu")!["offer"]!["label"]!.GetValue<string>()=="Older inventory");
            secondGate.SetResult(); await second; source.PlacesBarrier=null;
            Is("O9 newer GET refreshes open menu",hud.SceneOwned("placeMenu")!["offer"]!["label"]!.GetValue<string>()=="Newer inventory");
            offers.SetActive(false); Is("O10 overview drops rings and hover",offers.Places.RingCount==0 && !offers.Places.HasHover);
            return $"offers={n} O1-O10=ok entry_goal=(3,3.5) crossed_z=3.526667 report_z=3.53 walk_in=0.5m/4s places=2poses/2slots stand_up=posted";
        }
        catch(Exception e) { throw new InvalidOperationException("Task 52 O-case failure: "+e, e); }
        finally
        {
            offers?.Dispose(); position?.Dispose(); hud.Free(); builder.StopResidency(); builder.Models?.FreeAll(); world.QueueFree();
            await host.ToSignal(host.GetTree(),SceneTree.SignalName.ProcessFrame);
            await host.ToSignal(host.GetTree(),SceneTree.SignalName.ProcessFrame);
        }
    }
    private static IEnumerable<MeshInstance3D> Meshes(Node node)
    {
        if(node is MeshInstance3D mesh) yield return mesh;
        foreach(var child in node.GetChildren()) foreach(var m in Meshes(child)) yield return m;
    }
}
