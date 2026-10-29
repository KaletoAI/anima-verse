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
public static class PropActionsCheck
{
    public static async Task<string> RunAsync(Node3D host,string fixtures)
    {
        string dir=Path.Combine(fixtures,"propactions"); int checks=0;
        void Is(string name,bool value) { checks++; if(!value) throw new InvalidOperationException("propactions "+name); }
        void Near(string name,double got,double want,double eps=1e-5)=>Is($"{name}: {got:R} expected {want:R}",Math.Abs(got-want)<=eps);
        using var target=JsonDocument.Parse("""{"location_id":"loc-props","room_id":"r-props","placement_id":"bench-56","variant_uid":"variant-56"}""");
        var lazy=new Figure("fixture-lazy-entry"); host.AddChild(lazy);
        try {
            using var input=JsonDocument.Parse(File.ReadAllText(Path.Combine(dir,"worldmap_entry.json")));
            var spec=JsonNode.Parse(input.RootElement.GetProperty("characters")[0].GetProperty("prop_action_entry").GetRawText())!.AsObject();
            var fit=InstallMeasuredRig(lazy,deferred:true);
            Is("lazy entry requests real fitting",!lazy.PlayPropEntry(spec,.5) && fit.Requests()==1);
            fit.Complete(); Is("lazy entry plays after actual fit",lazy.PlayPropEntry(spec,.5) && fit.Requests()==2);
            lazy.Player!.GetAnimationLibrary("").RemoveAnimation("sitting");
            lazy.FinishPropEntry("sitting");
            Is("unfitted held pose is requested without fabricated playback",fit.Requests()==3);
        } finally { lazy.QueueFree(); }
        foreach(string scenario in new[]{"solo","pair-request","pair-accept","pair-decline","cancel","stale-revision"})
        {
            var source=new FixtureSource(dir,fixtures);
            using var hf=await source.GetHeightfieldAsync();
            var mgr=new FigureManager(source,new WorldHeight(HeightfieldOverview.Parse(hf.RootElement)),_=>{},strict:true)
                { AutoTick=false,GroundYAt=(_,_)=>0 };
            host.AddChild(mgr);
            using var control=new PropActionControl(source,()=>mgr.Clock*1000);
            mgr.OwnedPropApproaching=()=>PropActionMotion.Text(control.OwnedRun?["status"])=="approaching";
            mgr.SuppressAvatarJourney=control.ManualGate.Withdrawn;
            control.RefreshWorld=async ()=> { using var map=await source.GetWorldMapAsync(); await mgr.Apply(map.RootElement); };
            var notices=new List<string?>(); control.NotifyChanged+=notices.Add;
            try
            {
                using(var initial=await source.GetWorldMapAsync()) await mgr.Apply(initial.RootElement);
                var avatar=mgr.Figures["fixture-avatar"]; var npc=mgr.Figures["fixture-npc"];
                InstallMeasuredRig(avatar);
                source.SelectPropActionScenario(scenario);
                if(scenario=="solo") {
                    using var offers=await source.GetPropActionsAsync(); Is("solo two semantic offers",offers.RootElement.GetArrayLength()==2);
                    using var result=await control.MutateAsync(()=>source.RequestPropActionAsync("pose-56",target.RootElement,"revision-56"));
                    Is("solo admitted without synthetic seating",Json.Str(result.RootElement,"status")=="approaching" && avatar.Route?.ExactPath is not null && avatar.PropEntry is null);
                    var times=new[]{0,3,4,5,6,20}; var xs=new[]{-3,0,0,1,2,2}; var zs=new[]{-2,-2,-1,-1,-1,-1}; double previous=0;
                    for(int i=0;i<times.Length;i++) { mgr.Tick(times[i]-previous); previous=times[i]; Near("solo route X "+times[i],avatar.Position.X,xs[i]); Near("solo route Z "+times[i],avatar.Position.Z,zs[i]); Near("solo floor Y",avatar.Position.Y,0); }
                    using var entry=await source.GetWorldMapAsync(); await mgr.Apply(entry.RootElement);
                    mgr.Tick(0); Is("entry live",avatar.PropEntry?.Played==true); Near("entry measured clip time",avatar.ClipTime,1); Near("entry measured support",avatar.PropEntryLift,.0645);
                    Near("entry root stays at access",avatar.Position.Z,-1); Near("entry body travels half metre in world",avatar.Body!.GlobalPosition.Z-avatar.Position.Z,.5);
                    var playback=avatar.PropEntry;
                    var elapsed=JsonNode.Parse(entry.RootElement.GetRawText())!;
                    elapsed["characters"]![0]!["prop_action_entry"]!["elapsed_game_s"]=2.5;
                    using(var poll=JsonDocument.Parse(elapsed.ToJsonString())) await mgr.Apply(poll.RootElement);
                    mgr.Tick(0); Is("elapsed poll keeps clip identity",ReferenceEquals(playback,avatar.PropEntry));
                    Near("elapsed poll seeks measured clock",avatar.ClipTime,1.25); Near("elapsed poll measured support",avatar.PropEntryLift,.080625);
                    Near("elapsed poll continues measured body travel",avatar.Body!.GlobalPosition.Z-avatar.Position.Z,.625);
                    using(var state=await source.GetPropActionStateAsync()) Is("entry private phase",Json.Str(state.RootElement.GetProperty("current")[0],"phase")=="entry");
                    using var active=await source.GetWorldMapAsync(); await mgr.Apply(active.RootElement);
                    Near("commit root X",avatar.Position.X,2); Near("commit root Y",avatar.Position.Y,.129); Near("commit root Z",avatar.Position.Z,0);
                    Is("entry cleared after commit",avatar.PropEntry is null && avatar.Route is null);
                    control.RefreshWorld=()=>Task.CompletedTask; await control.RefreshAsync();
                    Is("solo active private run",PropActionMotion.Text(control.OwnedRun?["status"])=="active");
                    int unavailable=0; mgr.PropEntryError=_=>unavailable++;
                    var absent=JsonNode.Parse(entry.RootElement.GetRawText())!;
                    absent["characters"]![0]!["prop_action_entry"]!["kind"]="uninstalled-entry";
                    using(var missing=JsonDocument.Parse(absent.ToJsonString())) await mgr.Apply(missing.RootElement);
                    mgr.Tick(0); mgr.Tick(0);
                    Is("missing measured readiness reported once",unavailable==1 && avatar.PropEntry?.Played==false);
                    await mgr.Apply(active.RootElement);
                    Is("missing readiness cannot teleport to held anchor",avatar.PropEntryBlocked && avatar.Hidden && Math.Abs(avatar.Position.Z+1)<1e-5);
                    await mgr.Apply(active.RootElement); mgr.Tick(0);
                    Is("later held poll keeps failed representation unavailable",avatar.PropEntryBlocked && avatar.Hidden && Math.Abs(avatar.Position.Z+1)<1e-5);
                }
                else if(scenario=="pair-request") {
                    using var result=await control.MutateAsync(()=>source.RequestPropActionAsync("pair-56",target.RootElement,"revision-56","fixture-npc"));
                    Is("request awaits consent",Json.Str(result.RootElement,"status")=="awaiting_consent" && control.OwnedRun is null);
                    var outgoing=control.State["outgoing"]![0]!;
                    Is("outgoing cannot respond",outgoing["can_respond"]!.GetValue<bool>()==false && avatar.Route is null && npc.Route is null);
                }
                else if(scenario is "pair-accept" or "pair-decline") {
                    using var incoming=await source.GetPropActionStateAsync(); var invite=incoming.RootElement.GetProperty("incoming")[0];
                    Is("incoming permission",invite.GetProperty("can_respond").GetBoolean());
                    Is("semantic actor is NPC",Json.Str(invite,"actor")=="fixture-npc");
                    Is("physical a is avatar",Json.Str(invite.GetProperty("roles").GetProperty("clip"),"a")=="fixture-avatar");
                    using var result=await control.MutateAsync(()=>source.RespondPropActionAsync("execution-56-invite",scenario=="pair-accept"));
                    if(scenario=="pair-accept") {
                        Is("both exact routes",avatar.Route?.ExactPath is not null && npc.Route?.ExactPath is not null);
                        mgr.Tick(2); Near("NPC public detour X",npc.Position.X,5); Near("NPC public detour Z",npc.Position.Z,1);
                        Near("own pair approach X",avatar.Position.X,-1); Near("own pair approach Z",avatar.Position.Z,-2);
                        var roles=control.OwnedRun!["roles"]!;
                        Is("access role ownership retained",PropActionMotion.Text(roles["access"]?["actor"])=="partner" && PropActionMotion.Text(roles["access"]?["partner"])=="actor");
                    } else {
                        Is("decline terminal",Json.Str(result.RootElement,"reason")=="consent_declined" && control.OwnedRun is null);
                        Is("decline no public motion",avatar.Route is null && npc.Route is null);
                        Is("terminal cannot cancel",control.State["recent_results"]![0]!["can_cancel"]!.GetValue<bool>()==false);
                    }
                }
                else if(scenario=="cancel") {
                    using(var approach=await source.GetWorldMapFileAsync("worldmap_approach.json")) await mgr.Apply(approach.RootElement);
                    bool released=false;
                    await control.ReleaseAsync("execution-56-solo","journey-56-solo",()=>{ released=true; mgr.ClearPropEntry("fixture-avatar"); });
                    Is("cancel explicitly awaited and withdrawn",released && control.ManualGate.Withdrawn("journey-56-solo"));
                    Is("cancel clears public motion",avatar.Route is null && avatar.PropEntry is null);
                    Near("cancel X",avatar.Position.X,0); Near("cancel Z",avatar.Position.Z,-1);
                    using(var old=await source.GetWorldMapFileAsync("worldmap_approach.json")) await mgr.Apply(old.RootElement);
                    Is("cancel stale journey suppressed",avatar.Route is null);
                }
                else {
                    control.RefreshWorld=()=>Task.CompletedTask;
                    try { using var bad=await control.MutateAsync(()=>source.RequestPropActionAsync("pose-56",target.RootElement,"stale")); throw new InvalidOperationException("stale request accepted"); }
                    catch(ApiException e) { Is("stale exact 409 reason",e.Status==409 && e.Message.Contains("stale_definition",StringComparison.Ordinal)); }
                    Is("refusal releases only after fresh state",!control.Paused && control.OwnedRun is null);
                }
                Is(scenario+" exactly consumed",source.PropScenarioComplete);
                Is(scenario+" invalidates exactly once including refusal",notices.Count==1 && !string.IsNullOrEmpty(notices[0]));
            }
            finally { mgr.QueueFree(); }
        }
        checks += await CheckMenus(host,fixtures);
        // Real bridge callback: the host cannot acknowledge a preparation while a position promise is outstanding.
        var hud=new HudOverlay(); var write=new TaskCompletionSource(); int changed=0;
        hud.PropActionPrepare=_=>write.Task; hud.PropActionsChanged=id=>{ if(id=="hud:57") changed++; };
        hud.hud_bridge("""{"v":3,"kind":"prop-action-prepare","request_id":"hud:57"}""");
        Is("bridge awaits position preparation",hud.PendingPropPreparation is { IsCompleted:false });
        write.SetResult(); await hud.PendingPropPreparation!;
        hud.hud_bridge("""{"v":3,"kind":"prop-actions-changed","request_id":"hud:57"}"""); Is("bridge invalidates correlated",changed==1); hud.Free();
        return $"propactions scenarios=6 checks={checks} solo=pass pair-request=pass pair-accept=pass pair-decline=pass cancel=pass stale-revision=pass route=6m npc=5m clip=1s lift=.0645 root=.129";
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
            Is("blocked mesh opens",offers.Pick(origin,direction,new Vector2(100,120)));
            Is("blocked prop hover uses the shared cursor hook",offers.Hover(origin,direction) && offers.HasHover);
            offers.Tick(); Is("semantic menu survives the next frame",hud.SceneOwned("placeMenu") is not null);
            var menu=hud.SceneOwned("placeMenu")!["offer"]!;
            Is("exact actions including blocked",menu["prop_actions"]!.AsArray().Count==2 && menu["prop_actions"]![0]!["enabled"]!.GetValue<bool>()==false);
            Is("no room pose alias",menu["poses"]!.AsArray().Count==0 && PropActionMotion.Text(menu["id"])=="prop-action:bench-56");
            var action=menu["prop_actions"]![0]!;
            hud.Handlers["pickPropAction"](new JsonArray(action["action_id"]!.DeepClone(),action["target"]!.DeepClone(),action["definition_revision"]!.DeepClone()));
            await offers.PendingPropAction!;
            Is("HUD dispatch exact body",source.Request?["action_id"]?.GetValue<string>()=="pose-56" && source.Request?["revision"]?.GetValue<string>()=="revision-56"
                && source.Request?["target"]?["placement_id"]?.GetValue<string>()=="bench-56" && !source.Request!.AsObject().ContainsKey("partner"));
            Is("refusal resumes preparation",!steering.PropPreparationPending && !position.Channel.ReportsPaused);
            foreach(var row in source.Offers) row!["target"]!["variant_uid"]="wrong";
            await offers.RefreshSemanticOffersAsync();
            Is("stale variant is unpickable",!offers.Pick(origin,direction,new Vector2(100,120)));
            offers.Dispose(); offers=null;
            Is("teardown detaches bridge and commands",hud.PropActionPrepare is null && hud.PropActionsChanged is null && !hud.Handlers.ContainsKey("pickPropAction")
                && steering.ReleasePropAction is null && manager.OwnedPropApproaching is null);
            return n;
        } finally { offers?.Dispose(); position?.Dispose(); hud?.Free(); builder.StopResidency(); builder.Models?.FreeAll(); world.QueueFree(); }
    }
    /// <summary>Check-only snapshot server: real fixture geometry plus controlled blocked/verdict changes, without sockets.</summary>
    private sealed class MenuSource : IWorldSource
    {
        private readonly FixtureSource _fixture;
        public JsonArray Offers { get; }
        public JsonNode? Request;
        public bool SupportsPropActions=>true;
        public MenuSource(FixtureSource fixture) { _fixture=fixture; Offers=JsonNode.Parse(File.ReadAllText(Path.Combine(fixture.Dir,"offers.json")))!.AsArray(); Offers[0]!["enabled"]=false; Offers[0]!["reason"]="claimed"; }
        public Task<JsonDocument> GetPropActionsAsync()=>Task.FromResult(JsonDocument.Parse(Offers.ToJsonString()));
        public Task<JsonDocument> GetPropActionStateAsync()=>Task.FromResult(JsonDocument.Parse("{\"current\":[],\"outgoing\":[],\"incoming\":[],\"recent_results\":[]}"));
        public Task<JsonDocument> GetPlacesAsync()=>Task.FromResult(JsonDocument.Parse("{\"room_id\":\"r-props\",\"places\":[]}"));
        public Task<JsonDocument> RequestPropActionAsync(string actionId,JsonElement target,string revision,string? partner=null,System.Threading.CancellationToken ct=default)
        { Request=JsonNode.Parse(PropActionRequest.Request(actionId,target,revision,partner).GetRawText()); return Task.FromResult(JsonDocument.Parse("{\"execution_id\":\"\",\"status\":\"refused\",\"reason\":\"claimed\"}")); }
        public Task<JsonDocument> GetWorldMapAsync()=>_fixture.GetWorldMapFileAsync("worldmap.json");
        public Task<JsonDocument> GetHeightfieldAsync()=>_fixture.GetHeightfieldAsync();
        public Task<JsonDocument> GetHeightTilesAsync(IReadOnlyList<(int Tx,int Tz)> keys)=>_fixture.GetHeightTilesAsync(keys);
        public Task<JsonDocument> GetLocations3dAsync()=>_fixture.GetLocations3dAsync();
        public Task<JsonDocument?> GetLocationSceneAsync(string id)=>_fixture.GetLocationSceneAsync(id);
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
        if(!deferred) library.AddAnimation("fixture-sit-down",clip); library.AddAnimation("sitting",new Animation { Length=1,LoopMode=Animation.LoopModeEnum.Linear });
        player.AddAnimationLibrary("",library);
        fig.SetBody(body,true,skeleton,player,new[]{"fixture-sit-down","sitting"},bodyHeight:1.7); fig.BaseScale=1;
        fig.Extras=new Dictionary<Animation,ClipExtras> { [clip]=new() { Path=new RootPath(new float[]{0,2},new float[]{0,0,0,-1}) } };
        bool ready=!deferred; int requests=0;
        fig.FitClip=kind=> { requests++; if(!ready || kind!="fixture-sit-down") return false; library.AddAnimation(kind,clip); return true; };
        return (()=>ready=true,()=>requests);
    }
}
