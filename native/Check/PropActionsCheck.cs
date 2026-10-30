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
using AnimaNative.Props;
using AnimaNative.World;
using Godot;
using Json=AnimaNative.World.Json;

namespace AnimaNative.Check;

/// <summary>
/// Task 57 / E7-T12: strict Task 56 six-scenario replay through actual API request builders, preparation/control
/// and figure rendering. Hand numbers come from fixtures/propactions/README.md. The check explicitly installs a
/// two-second measured synthetic entry rig; no installed asset readiness or server planner claim is implied.
/// Ownership ledger: check owns its world/manager/rig/HUD nodes and frees them; shared animation data is immutable.
/// </summary>
public static partial class PropActionsCheck
{
    public static async Task<string> RunAsync(Node3D host,string fixtures)
    {
        int checks=await CheckMotionPlayback(host,fixtures);
        checks+=await CheckUpperMotion(host,fixtures);
        checks+=await CheckMenus(host,fixtures);
        checks+=await CheckPolling(host,fixtures);
        return $"propactions B1 checks={checks} request=pass respond=pass state=pass cancel=pass anchor=pass observer=pass";
    }
    /// <summary>Task 57: actual streamed prop mesh, exact semantic offer join, HUD dispatch, disposal and manual release.</summary>
    private static async Task<int> CheckMenus(Node3D host,string fixtures)
    {
        int n=0;
        void Is(string label,bool ok) { n++; if(!ok) throw new InvalidOperationException("propactions menu "+label); }
        var fixture=new FixtureSource(Path.Combine(fixtures,"propactions"),fixtures);
        var world=new Node3D(); host.AddChild(world); var builder=new WorldBuilder(fixture,_=>{},strict:true);
        HudOverlay? hud=null; AvatarPositionController? position=null; AvatarOffersController? offers=null;
        try {
            await builder.BuildAsync(world,"Fixture Prop Room");
            builder.SetOpen("loc-props",true); builder.Slots["loc-props"].Fade.Snap(1);
            var source=new MenuSource(fixture);
            var manager=new FigureManager(fixture,builder.Height!,_=>{},strict:true) { AutoTick=false,Slots=()=>builder.Slots,GroundYAt=builder.FigureGroundY };
            world.AddChild(manager);
            using var map=await fixture.GetWorldMapAsync(); await manager.Apply(map.RootElement);
            var steering=new PlayerSteering(manager,builder); steering.SetActive(true);
            position=new(manager,builder,steering,source); position.SetActive(true,map.RootElement);
            hud=new HudOverlay(); offers=new(manager,builder,steering,source,hud,position);
            offers.SetActive(true); if(offers.PendingPropAction is { } initial) await initial;
            await offers.RefreshSemanticOffersAsync();
            var origin=new AnimaNative.Overview.Vec3(3,2,0); var direction=new AnimaNative.Overview.Vec3(0,-1,0);
            var prop=builder.Slots["loc-props"].Placements.Single(p=>p.Spec.PlacementId=="bench-56").Node!;
            static System.Collections.Generic.IEnumerable<MeshInstance3D> Meshes(Node node) {
                if(node is MeshInstance3D mesh) yield return mesh;
                foreach(var child in node.GetChildren()) foreach(var m in Meshes(child)) yield return m;
            }
            var meshes=Meshes(prop).ToArray();
            using var prior=new StandardMaterial3D();
            meshes[0].MaterialOverlay=prior;
            var old=meshes.Select(m=>m.MaterialOverlay).ToArray();
            void Restored(string why)=>Is(why,meshes.Select((m,i)=>ReferenceEquals(m.MaterialOverlay,old[i])).All(x=>x));
            Is("enabled semantic hover",offers.Hover(origin,direction) && meshes.Length>0
                && meshes.All(m=>ReferenceEquals(m.MaterialOverlay,PlaceTargets.SharedSpotMaterial)));
            offers.Hover(new(300,2,300),direction); Restored("leaving restores exact overlays");
            foreach(var row in source.Offers) row!["enabled"]=false;
            await offers.RefreshSemanticOffersAsync(); offers.Hover(origin,direction); Restored("all disabled has no overlay");
            Is("all disabled remains clickable",offers.Pick(origin,direction,new Vector2(100,120)));
            hud.Handlers["closePlaceMenu"](new());
            source.Offers[1]!["enabled"]=true;
            source.Offers[0]!["prop_label"]="Fixture bench";
            await offers.RefreshSemanticOffersAsync();
            offers.Hover(origin,direction); offers.Hover(origin,direction);
            offers.SetActive(false); Restored("deactivation restores after repeated hover");
            offers.SetActive(true); if(offers.PendingPropAction is { } reactivated) await reactivated;
            offers.Hover(origin,direction);
            var picked=AnimaNative.Overview.PickChain.Resolve(null,"loc-props",
                ()=>offers.Pick(origin,direction,new Vector2(100,120)),embodied:true);
            Is("blocked mesh consumes before location info",picked.Info==AnimaNative.Overview.InfoChange.Unchanged);
            Restored("opening menu restores exact overlays");
            Is("furniture title",PropActionMotion.Text(hud.SceneOwned("placeMenu")?["offer"]?["label"])=="Fixture bench");
            foreach(string? label in new string?[]{"",null}) {
                source.Offers[0]!["prop_label"]=label; await offers.RefreshSemanticOffersAsync();
                Is("action title fallback",PropActionMotion.Text(hud.SceneOwned("placeMenu")?["offer"]?["label"])=="Fixture solo pose");
            }

            Is("menu suppresses hover",!offers.Hover(origin,direction) && !offers.HasHover);
            offers.Tick(); Is("semantic menu survives the next frame",hud.SceneOwned("placeMenu") is not null);
            var menu=hud.SceneOwned("placeMenu")!["offer"]!;
            Is("exact actions including blocked",menu["prop_actions"]!.AsArray().Count==2 && menu["prop_actions"]![0]!["enabled"]!.GetValue<bool>()==false);
            Is("no room pose alias",menu["poses"]!.AsArray().Count==0 && PropActionMotion.Text(menu["id"])=="prop-action:bench-56");
            source.PendingOffers=new TaskCompletionSource<JsonDocument>();
            var refreshing=offers.RefreshSemanticOffersAsync();
            Is("in-flight refresh preserves previous rows",hud.SceneOwned("placeMenu")!["offer"]!["prop_actions"]![0]!["enabled"]!.GetValue<bool>()==false);
            source.Offers[0]!["enabled"]=true; source.Offers[0]!["reason"]="";
            source.PendingOffers.SetResult(JsonDocument.Parse(source.Offers.ToJsonString())); await refreshing;
            Is("fresh rows update open menu",hud.SceneOwned("placeMenu")!["offer"]!["prop_actions"]![0]!["enabled"]!.GetValue<bool>());
            source.PendingOffers=null;
            source.Offers[0]!["enabled"]=false; source.Offers[0]!["reason"]="claimed";
            await offers.RefreshSemanticOffersAsync();

            var action=menu["prop_actions"]![0]!;
            hud.Handlers["pickPropAction"](new JsonArray(action["action_id"]!.DeepClone(),action["target"]!.DeepClone(),action["definition_revision"]!.DeepClone()));
            await offers.PendingPropAction!;
            Is("HUD dispatch exact body",source.Request?["action_id"]?.GetValue<string>()=="pose-56" && source.Request?["revision"]?.GetValue<string>()=="revision-56"
                && source.Request?["target"]?["placement_id"]?.GetValue<string>()=="bench-56" && !source.Request!.AsObject().ContainsKey("partner"));
            Is("refusal resumes preparation",!steering.PropPreparationPending && !position.Channel.ReportsPaused);
            foreach(var row in source.Offers) row!["target"]!["variant_uid"]="wrong";
            await offers.RefreshSemanticOffersAsync();
            Is("stale variant is unpickable",!offers.Pick(origin,direction,new Vector2(100,120)));
            foreach(var row in source.Offers) row!["target"]!["variant_uid"]="variant-56";
            await offers.RefreshSemanticOffersAsync();
            offers.Hover(origin,direction);
            Is("hover before disposal",meshes.All(m=>ReferenceEquals(m.MaterialOverlay,PlaceTargets.SharedSpotMaterial)));
            offers.Dispose(); offers=null; Restored("disposal restores exact overlays");
            meshes[0].MaterialOverlay=null;
            Is("teardown detaches bridge and commands",hud.PropActionPrepare is null && hud.PropActionsChanged is null && !hud.Handlers.ContainsKey("pickPropAction")
                && steering.ReleasePropAction is null && manager.SuppressAvatarPropEntry is null);
            return n;
        } finally { offers?.Dispose(); position?.Dispose(); hud?.Free(); builder.StopResidency(); builder.Models?.FreeAll(); world.QueueFree(); }
    }
    /// <summary>Check-only snapshot server: real fixture geometry plus controlled blocked/verdict changes, without sockets.</summary>
    private sealed class MenuSource : IWorldSource
    {
        private readonly FixtureSource _fixture;
        public JsonArray Offers { get; }
        public JsonNode? Request;
        public JsonObject? MapOverride,StateOverride,CancelAnswer,RespondAnswer,SceneOverride;
        public Exception? CancelError;
        public int CancelRequests,OfferRequests,WorldRequests,StateRequests;
        public TaskCompletionSource<JsonDocument>? PendingState;
        public TaskCompletionSource<JsonDocument>? PendingOffers,PendingRequest;
        public Task<JsonDocument> CancelPropActionAsync(string executionId,System.Threading.CancellationToken ct=default)
        {
            CancelRequests++; if(CancelError is { } error) return Task.FromException<JsonDocument>(error); MapOverride=JsonNode.Parse(File.ReadAllText(Path.Combine(_fixture.Dir,"worldmap_cancelled.json")))!.AsObject();
            StateOverride=new JsonObject { ["current"]=new JsonArray(),["outgoing"]=new JsonArray() };
            return Task.FromResult(JsonDocument.Parse(CancelAnswer?.ToJsonString() ?? "{\"status\":\"cancelled\"}"));
        }
        public bool SupportsPropActions=>true;
        public MenuSource(FixtureSource fixture) { _fixture=fixture; Offers=JsonNode.Parse(File.ReadAllText(Path.Combine(fixture.Dir,"offers.json")))!.AsArray(); Offers[0]!["enabled"]=false; Offers[0]!["reason"]="claimed"; }
        public Task<JsonDocument> GetPropActionsAsync() { OfferRequests++; return PendingOffers?.Task ?? Task.FromResult(JsonDocument.Parse(Offers.ToJsonString())); }
        public Task<JsonDocument> GetPropActionStateAsync() { StateRequests++; return PendingState?.Task ?? Task.FromResult(JsonDocument.Parse(StateOverride?.ToJsonString() ?? "{\"current\":[],\"outgoing\":[],\"incoming\":[],\"recent_results\":[]}")); }
        public Task<JsonDocument> GetPlacesAsync()=>Task.FromResult(JsonDocument.Parse("{\"room_id\":\"r-props\",\"places\":[]}"));
        public Task<JsonDocument> RequestPropActionAsync(string actionId,JsonElement target,string revision,string? partner=null,System.Threading.CancellationToken ct=default)
        { Request=JsonNode.Parse(PropActionRequest.Request(actionId,target,revision,partner).GetRawText()); return PendingRequest?.Task ?? Task.FromResult(JsonDocument.Parse("{\"execution_id\":\"\",\"status\":\"refused\",\"reason\":\"claimed\"}")); }
        public Task<JsonDocument> RespondPropActionAsync(string id,bool accept,System.Threading.CancellationToken ct=default)=>Task.FromResult(JsonDocument.Parse(RespondAnswer?.ToJsonString() ?? "{\"status\":\"refused\"}"));
        public Task<JsonDocument> GetWorldMapAsync() { WorldRequests++; return MapOverride is { } map ? Task.FromResult(JsonDocument.Parse(map.ToJsonString())) : _fixture.GetWorldMapFileAsync("worldmap.json"); }
        public Task<JsonDocument> GetHeightfieldAsync()=>_fixture.GetHeightfieldAsync();
        public Task<JsonDocument> GetHeightTilesAsync(IReadOnlyList<(int Tx,int Tz)> keys)=>_fixture.GetHeightTilesAsync(keys);
        public Task<JsonDocument> GetLocations3dAsync()=>_fixture.GetLocations3dAsync();
        public Task<JsonDocument?> GetLocationSceneAsync(string id)=>SceneOverride is { } scene ? Task.FromResult<JsonDocument?>(JsonDocument.Parse(scene.ToJsonString())) : _fixture.GetLocationSceneAsync(id);
        public Task<byte[]> GetBytesAsync(string url)=>_fixture.GetBytesAsync(url);
        public Task<JsonDocument?> GetCharacterModelAsync(string name)=>_fixture.GetCharacterModelAsync(name);
        public Task<JsonDocument> GetAnimationClipsAsync()=>_fixture.GetAnimationClipsAsync();
        public Task<JsonDocument> GetTerrainAsync()=>_fixture.GetTerrainAsync();
        public Task<JsonDocument> GetTerrainLayersAsync(IReadOnlyList<string> keys)=>_fixture.GetTerrainLayersAsync(keys);
        public Task<JsonDocument> GetSurfaceTexturesAsync()=>_fixture.GetSurfaceTexturesAsync();
    }
    private static (Action Complete,Func<int> Requests) InstallMeasuredRig(Figure fig,bool deferred=false)
    {
        var body=new Node3D(); var skeleton=new Skeleton3D { Name="Rig" }; body.AddChild(skeleton);
        skeleton.AddBone("Hips"); skeleton.SetBoneRest(0,new Transform3D(Basis.Identity,new Vector3(0,1,0)));
        var player=new AnimationPlayer { CallbackModeProcess=AnimationMixer.AnimationCallbackModeProcess.Manual }; body.AddChild(player);
        var library=new AnimationLibrary(); var clip=new Animation { Length=2 };
        int hips=clip.AddTrack(Animation.TrackType.Position3D); clip.TrackSetPath(hips,"Rig:Hips");
        clip.PositionTrackInsertKey(hips,0,new Vector3(0,1,0)); clip.PositionTrackInsertKey(hips,2,new Vector3(0,.5f,0));
        library.AddAnimation(FigureClips.PoseKind("standing",fig.Poses),new Animation { Length=1,LoopMode=Animation.LoopModeEnum.Linear });
        library.AddAnimation("walk",new Animation { Length=1,LoopMode=Animation.LoopModeEnum.Linear });
        if(!deferred) library.AddAnimation("fixture-sit-down",clip); library.AddAnimation("sitting",new Animation { Length=1,LoopMode=Animation.LoopModeEnum.Linear });
        var exit=new Animation { Length=.5 }; int exitHips=exit.AddTrack(Animation.TrackType.Position3D); exit.TrackSetPath(exitHips,"Rig:Hips");
        exit.PositionTrackInsertKey(exitHips,0,new Vector3(0,.5f,0)); exit.PositionTrackInsertKey(exitHips,.25,new Vector3(0,.6f,0)); exit.PositionTrackInsertKey(exitHips,.5,new Vector3(0,1,0));
        library.AddAnimation("fixture-get-up",exit);
        library.AddAnimation("fixture-start-walk",new Animation { Length=.5 });
        player.AddAnimationLibrary("",library);
        fig.SetBody(body,true,skeleton,player,new[]{"fixture-start-walk","fixture-get-up","fixture-sit-down","sitting","author-held","pair-pose__b","walk",FigureClips.PoseKind("standing",fig.Poses)},bodyHeight:1.7); fig.BaseScale=1;
        fig.Extras=new Dictionary<Animation,ClipExtras> {
            [clip]=new() { Path=new RootPath(new float[]{0,2},new float[]{0,0,0,-1}) },
            [exit]=new() { Path=new RootPath(new float[]{0,.5f},new float[]{0,0,0,-.5f}),Lift=new BridgeLiftSpec(0,.5) } };
        bool ready=!deferred; int requests=0;
        fig.FitClip=kind=> { requests++; if(!ready || kind!="fixture-sit-down") return false; library.AddAnimation(kind,clip); return true; };
        return (()=>ready=true,()=>requests);
    }
}
