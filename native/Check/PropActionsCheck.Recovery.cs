using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Embody;
using AnimaNative.Figures;
using AnimaNative.Hud;
using AnimaNative.Props;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

public static partial class PropActionsCheck
{
    private static async Task<int> CheckNoExitAndDeadRun(Node3D host,string fixtures)
    {
        int n=0;
        void Is(string label,bool ok) { n++; if(!ok) throw new InvalidOperationException("propactions recovery "+label); }
        JsonObject Read(string file)=>JsonNode.Parse(File.ReadAllText(Path.Combine(fixtures,"propactions",file)))!.AsObject();
        var source=new MenuSource(new FixtureSource(Path.Combine(fixtures,"propactions"),fixtures));
        var world=new Node3D(); host.AddChild(world); var hud=new HudOverlay();
        var builder=new WorldBuilder(source,_=>{},strict:true);
        AvatarPositionController? position=null; AvatarOffersController? offers=null;
        double now=1000;
        try {
            await builder.BuildAsync(world,"Fixture Prop Room"); builder.SetOpen("loc-props",true);
            builder.Slots["loc-props"].Fade.Snap(1);
            var mgr=new FigureManager(source,builder.Height!,_=>{},strict:true) {
                AutoTick=false,Slots=()=>builder.Slots,GroundYAt=builder.FigureGroundY };
            world.AddChild(mgr);
            using(var initial=await source.GetWorldMapAsync()) await mgr.Apply(initial.RootElement);
            var avatar=mgr.Figures["fixture-avatar"]; InstallMeasuredRig(avatar);
            var steering=new PlayerSteering(mgr,builder); steering.SetActive(true);
            position=new(mgr,builder,steering,source,()=>now);
            using(var initial=await source.GetWorldMapAsync()) position.SetActive(true,initial.RootElement);
            offers=new(mgr,builder,steering,source,hud,position,()=>now);
            offers.SetActive(true); await offers.PendingPropAction!;
            async Task Request(string id) {
                source.PendingRequest=new();
                var action=source.Offers[0]!;
                hud.Handlers["pickPropAction"](new JsonArray(action["action_id"]!.DeepClone(),action["target"]!.DeepClone(),action["definition_revision"]!.DeepClone()));
                int maps=source.WorldRequests;
                source.PendingState=new();
                source.PendingRequest.SetResult(JsonDocument.Parse($$"""{"execution_id":"{{id}}","status":"approaching"}"""));
                Is("approaching answer polls map before private state returns",source.WorldRequests==maps+1);
                source.PendingState.SetResult(JsonDocument.Parse(source.StateOverride!.ToJsonString())); source.PendingState=null;
                await offers.PendingPropAction!; source.PendingRequest=null;
            }
            foreach(string status in new[]{"cancelled","failed","withdrawn"}) {
                source.StateOverride=JsonNode.Parse($$"""{"current":[{"execution_id":"{{status}}","status":"approaching"}],"outgoing":[]}""")!.AsObject();
                source.MapOverride=Read(status=="withdrawn" ? "worldmap_approach.json" : "worldmap_cancelled.json");
                await Request(status);
                if(status=="withdrawn") Is("adopted before withdrawal",avatar.Route?.OwnedApproach==true);
                source.MapOverride=Read("worldmap_cancelled.json");
                if(status!="withdrawn") source.StateOverride=JsonNode.Parse($$"""{"current":[],"outgoing":[],"recent_results":[{"execution_id":"{{status}}","status":"{{status}}","reason":"execution_owner_error"}]}""")!.AsObject();
                if(status=="failed") {
                    offers.RefreshPropWorld=()=>Task.FromException(new InvalidOperationException("map offline"));
                    await offers.PropActions!.PrepareAsync("offline");
                }
                try { if(status=="failed") await offers.PropActions!.ChangedAsync("offline"); else await offers.PropActions!.RefreshAsync(); }
                catch(InvalidOperationException error) when(status=="failed" && error.Message=="map offline") { }
                offers.RefreshPropWorld=null;
                Is(status+" clears control and write gates",!mgr.ServerDriven && !steering.PropActionDriven && !steering.PropPreparationPending && !position.Channel.ReportsPaused);
                Is(status+" clears pose/route gates",avatar.Route is null && avatar.PropEntry is null && !avatar.PropEntryBlocked && !steering.AvatarSeated && avatar.Face is null && avatar.Lean is null);
                int states=source.StateRequests,maps=source.WorldRequests,fit=0;
                avatar.FitClip=_=>{ fit++; return false; };
                for(int i=0;i<120;i++) { now+=17; offers.Tick(); mgr.Tick(1.0/60); }
                Is(status+" no pending-run poll/fit churn",source.StateRequests==states && source.WorldRequests==maps && fit==0);
                Is(status+" steerable",steering.WalkTo(new(avatar.Position.X+.5,avatar.Position.Z)));
                steering.CancelRoute();
            }
            source.MapOverride=Read("worldmap_active.json");
            source.StateOverride=JsonNode.Parse("""{"current":[{"execution_id":"seat","status":"active"}],"outgoing":[]}""")!.AsObject();
            await offers.PropActions!.RefreshAsync(); mgr.Tick(0); steering.SetSeated(true);
            Is("no-exit starts seated",avatar.CurrentClip=="sitting");
            source.MapOverride=Read("worldmap_approach.json"); var row=source.MapOverride["characters"]![0]!;
            row["activity_animation"]="sitting"; row["travel"]!["journey_id"]="journey-no-exit";
            row["travel"]!["waypoints"]=new JsonArray(new JsonArray(2,0),new JsonArray(2,-.5),new JsonArray(4,-.5));
            row["travel"]!["progress_m"]=0; row["travel"]!["starts_in_s"]=.3;
            row["travel"]!["paces_m_s_real"]=new JsonArray(null,1); row["travel"]!["floor_y"]=0;
            source.StateOverride["current"]![0]!["execution_id"]="no-exit"; source.StateOverride["current"]![0]!["status"]="approaching";
            await Request("no-exit");
            for(int i=0;i<3;i++) {
                mgr.Tick(.099);
                Is("no-exit seated through lead",avatar.CurrentClip=="sitting" && !avatar.Bridging && Math.Abs(avatar.Position.Z)<1e-6);
            }
            mgr.Tick(.003);
            Is($"no-exit stands upright at waypoint 2 clip={avatar.CurrentClip} position={avatar.Position} released={avatar.Route?.SeatReleased}",avatar.CurrentClip==FigureClips.PoseKind("standing",avatar.Poses) && Math.Abs(avatar.Position.Z+.5)<1e-6 && Math.Abs(avatar.Position.Y-.01)<1e-6);
            var previous=avatar.Position;
            for(int i=0;i<30;i++) { mgr.Tick(1.0/60); Is("no-exit bounded walk",avatar.Position.DistanceTo(previous)<=.25001); previous=avatar.Position; }
            Is("no-exit walks on",avatar.Position.X>2 && Math.Abs(avatar.Position.Z+.5)<1e-6 && avatar.CurrentClip=="walk");
            return n;
        } finally { offers?.Dispose(); position?.Dispose(); hud.Free(); builder.StopResidency(); builder.Models?.FreeAll(); world.QueueFree(); }
    }
}
