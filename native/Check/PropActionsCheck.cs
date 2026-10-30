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
            mgr.OwnedPropApproaching=_=>PropActionMotion.Text(control.OwnedRun?["status"])=="approaching";
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
                    for(int i=0;i<times.Length;i++) { for(double left=times[i]-previous;left>1e-8;left-=1.0/60) mgr.Tick(Math.Min(left,1.0/60)); previous=times[i]; Near("solo route X "+times[i],avatar.Position.X,xs[i]); Near("solo route Z "+times[i],avatar.Position.Z,zs[i]); Near("solo floor Y",avatar.Position.Y,0); }
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
                    Is("authoritative place releases failed entry",!avatar.PropEntryBlocked && !avatar.Hidden && avatar.PropEntry is null && avatar.CurrentClip=="sitting");
                    await mgr.Apply(active.RootElement); mgr.Tick(0);
                    Is("later held poll keeps representation available",!avatar.PropEntryBlocked && !avatar.Hidden && avatar.PropEntry is null);
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
                        for(int frame=0;frame<120;frame++) mgr.Tick(1.0/60); Near("NPC public detour X",npc.Position.X,5); Near("NPC public detour Z",npc.Position.Z,1);
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
        checks += await CheckLateApproach(host,fixtures);
        checks += await CheckMenus(host,fixtures);
        checks += await CheckSeatedSwitch(host,fixtures);
        checks += await CheckNoExitAndDeadRun(host,fixtures);
        checks += await CheckUpperStorey(host,fixtures);
        // Real bridge callback: the host cannot acknowledge a preparation while a position promise is outstanding.
        var hud=new HudOverlay(); var write=new TaskCompletionSource(); int changed=0;
        hud.PropActionPrepare=_=>write.Task; hud.PropActionsChanged=id=>{ if(id=="hud:57") changed++; };
        hud.hud_bridge("""{"v":4,"kind":"prop-action-prepare","request_id":"hud:57"}""");
        Is("bridge awaits position preparation",hud.PendingPropPreparation is { IsCompleted:false });
        write.SetResult(); await hud.PendingPropPreparation!;
        hud.hud_bridge("""{"v":4,"kind":"prop-actions-changed","request_id":"hud:57"}"""); Is("bridge invalidates correlated",changed==1); hud.Free();
        return $"propactions scenarios=11 checks={checks} solo=pass pair-request=pass pair-accept=pass pair-decline=pass cancel=pass stale-revision=pass upper-direct=pass upper-bridge=pass late-adoption=pass starts-wait=pass seated-switch=pass prepared=pass early-pair=pass route=6m npc=5m clip=1s lift=.0645 root=.129";
    }
    private static async Task<int> CheckLateApproach(Node3D host,string fixtures)
    {
        int n=0;
        void Is(string label,bool ok) { n++; if(!ok) throw new InvalidOperationException("propactions late "+label); }
        var vectors=JsonNode.Parse(File.ReadAllText(Path.Combine(fixtures,"../../shared/test-vectors/prop_action_motion.json")))!;
        Is("shared math format /1",vectors["format"]!.GetValue<string>()=="anima-test-vectors/1");
        foreach(var row in vectors["cases"]!.AsArray()) {
            var args=row!["args"]!.AsArray(); double got;
            if(row["fn"]!.GetValue<string>()=="projectApproachM")
                got=PropActionMotion.ProjectApproachM(args[0]!.AsArray().Select(p=>(PropActionMotion.Number(p![0]),PropActionMotion.Number(p[1]))).ToArray(),
                    (PropActionMotion.Number(args[1]![0]),PropActionMotion.Number(args[1]![1])));
            else if(row["fn"]!.GetValue<string>()=="ownedApproachStep")
                got=PropActionMotion.OwnedApproachStep(PropActionMotion.Number(args[0]),PropActionMotion.Number(args[1]),PropActionMotion.Number(args[2]),PropActionMotion.Number(args[3]),PropActionMotion.Number(args[4]),args.Count>5 ? PropActionMotion.Number(args[5]) : 0,args.Count>6 ? PropActionMotion.Number(args[6]) : 0);
            else if(row["fn"]!.GetValue<string>()=="ownedApproachCatchUp")
                got=PropActionMotion.OwnedApproachCatchUp(PropActionMotion.Number(args[0]),PropActionMotion.Number(args[1]),PropActionMotion.Number(args[2]),PropActionMotion.Number(args[3]),PropActionMotion.Number(args[4]),PropActionMotion.Number(args[5]));
            else continue;
            Is(row["label"]!.GetValue<string>(),Math.Abs(got-PropActionMotion.Number(row["expect"]))<1e-8);
        }
        var source=new FixtureSource(Path.Combine(fixtures,"propactions"),fixtures);
        using var hf=await source.GetHeightfieldAsync();
        var mgr=new FigureManager(source,new WorldHeight(HeightfieldOverview.Parse(hf.RootElement)),_=>{},strict:true)
            { AutoTick=false,GroundYAt=(_,_)=>0,OwnedPropApproaching=_=>true };
        host.AddChild(mgr);
        try {
            using(var initial=await source.GetWorldMapAsync()) await mgr.Apply(initial.RootElement);
            var avatar=mgr.Figures["fixture-avatar"]; InstallMeasuredRig(avatar);
            var start=avatar.Position;
            var map=JsonNode.Parse(File.ReadAllText(Path.Combine(source.Dir,"worldmap_approach.json")))!;
            map["characters"]![0]!["travel"]!["progress_m"]=1;
            map["characters"]![0]!["travel"]!["starts_in_s"]=.75;
            using(var fresh=JsonDocument.Parse(map.ToJsonString())) await mgr.Apply(fresh.RootElement);
            Is("future approach has no catch-up",avatar.Route!.CatchUpRate==0);
            mgr.Tick(.1); Is("future approach holds start",avatar.Position.DistanceTo(start)<.00001);
            Is("future approach stands",avatar.CurrentClip==FigureClips.PoseKind("standing",avatar.Poses));
            avatar.Transitions=new[]{new ClipTransition(FigureClips.PoseKind("standing",avatar.Poses),FigureClips.PoseKind("walking",avatar.Poses),"fixture-start-walk",0)};
            for(int i=0;i<45;i++) mgr.Tick(1.0/60);
            Is("start opens holding stand-to-walk bridge",avatar.Bridging && avatar.CurrentClip=="fixture-start-walk");
            Is("holding bridge prevents first step",avatar.Position.DistanceTo(start)<.00001);
            for(int i=0;i<35;i++) mgr.Tick(1.0/60);
            Is("walk begins after start and bridge",avatar.Position.X>start.X);
            avatar.Transitions=Array.Empty<ClipTransition>();
            avatar.SnapTo(start); avatar.Route=null;
            map["sync"]=new JsonObject { ["clock_age_ms"]=500,["build_ms"]=0 };
            using(var raw=JsonDocument.Parse(map.ToJsonString()))
            using(var aged=new MapReceipt(0,0,0).Attach(raw.RootElement)) await mgr.Apply(aged.RootElement);
            Is("receipt age is deducted from wait",Math.Abs(mgr.Clock-avatar.Route!.ReceivedAt-.5)<1e-6);
            mgr.Tick(.24); Is("aged route holds remaining quarter second",avatar.Position.DistanceTo(start)<.00001);
            mgr.Tick(.02); Is("aged route starts after remaining wait",avatar.Position.X>start.X);
            avatar.SnapTo(start); avatar.Route=null;
            map["characters"]![0]!["travel"]!["starts_in_s"]=null;
            map["characters"]![0]!["travel"]!["progress_m"]=5.4;
            using(var late=JsonDocument.Parse(map.ToJsonString())) await mgr.Apply(late.RootElement);
            Is("adoption keeps rendered position",avatar.Position.DistanceTo(start)<.00001);
            Is("starts at current projection",Math.Abs(avatar.Route!.ShownM)<.00001);
            mgr.Tick(0); Is("zero-time frame has no jump",avatar.Position.DistanceTo(start)<.00001);
            for(int i=0;i<50;i++) {
                var before=avatar.Position;
                if(i==5) {
                    map["characters"]![0]!["travel"]!["progress_m"]=6;
                    using var poll=JsonDocument.Parse(map.ToJsonString()); await mgr.Apply(poll.RootElement);
                    Is("later poll cannot snap forward",avatar.Position.DistanceTo(before)<.00001);
                }
                mgr.Tick(1.0/60);
                Is("frame step <= .25m",avatar.Position.DistanceTo(before)<=.25001);
            }
            Is("reaches access",avatar.Position.DistanceTo(new Vector3(2,0,-1))<.00001);
            mgr.Tick(.016); Is("no walking on spot",avatar.CurrentClip!="walk" && avatar.CurrentClip!="walking");
            Is("actual standing clip",avatar.CurrentClip==FigureClips.PoseKind("standing",avatar.Poses));
            avatar.SnapTo(start); avatar.Route=null;
            using(var late=JsonDocument.Parse(map.ToJsonString())) await mgr.Apply(late.RootElement);
            using(var active=await source.GetWorldMapFileAsync("worldmap_active.json")) await mgr.Apply(active.RootElement);
            Is("early seat keeps visible start",avatar.Position.DistanceTo(start)<.00001 && avatar.Route is not null);
            for(int i=0;i<50;i++) {
                var before=avatar.Position; mgr.Tick(1.0/60);
                Is("early seat keeps continuous approach",avatar.Position.DistanceTo(before)<=.25001);
            }
            mgr.TickPlacement();
            mgr.Tick(0);
            Is($"seat after visible arrival clip={avatar.CurrentClip} route={avatar.Route?.ShownM}",avatar.CurrentClip=="sitting" && avatar.Route is null);

            avatar.SnapTo(start); avatar.Route=null;
            using(var late=JsonDocument.Parse(map.ToJsonString())) await mgr.Apply(late.RootElement);
            var paired=JsonNode.Parse(File.ReadAllText(Path.Combine(source.Dir,"worldmap_active.json")))!;
            paired["characters"]![0]!["place"]=null;
            paired["characters"]![0]!["interaction"]=new JsonObject { ["id"]="pair",["kind"]="greeting-handshake",["role"]="a",["partner"]="fixture-npc",
                ["anchor"]=new JsonObject { ["x"]=2,["z"]=-1,["yaw"]=0 },["elapsed_s"]=0,["clip_duration_s"]=2,["rate"]=1 };
            using(var pair=JsonDocument.Parse(paired.ToJsonString())) await mgr.Apply(pair.RootElement);
            Is("interaction-only arrival keeps route",avatar.Route is { OwnedApproach:true } && avatar.Position.DistanceTo(start)<.00001 && avatar.Pair is null);
            return n;
        } finally { mgr.QueueFree(); }
    }
    private static async Task<int> CheckSeatedSwitch(Node3D host,string fixtures)
    {
        int n=0;
        void Is(string label,bool ok) { n++; if(!ok) throw new InvalidOperationException("propactions switch "+label); }
        var fixture=new FixtureSource(Path.Combine(fixtures,"propactions"),fixtures);
        JsonObject Read(string file)=>JsonNode.Parse(File.ReadAllText(Path.Combine(fixture.Dir,file)))!.AsObject();
        var source=new MenuSource(fixture);
        var world=new Node3D(); host.AddChild(world);
        var builder=new WorldBuilder(source,_=>{},strict:true); var hud=new HudOverlay();
        AvatarPositionController? position=null; AvatarOffersController? offers=null;
        try {
            await builder.BuildAsync(world,"Fixture Prop Room"); builder.SetOpen("loc-props",true);
            builder.Slots["loc-props"].Fade.Snap(1);
            var logs=new List<string>();
            var mgr=new FigureManager(source,builder.Height!,logs.Add,strict:true) {
                AutoTick=false,Slots=()=>builder.Slots,GroundYAt=builder.FigureGroundY };
            world.AddChild(mgr);
            using(var initial=await source.GetWorldMapAsync()) await mgr.Apply(initial.RootElement);
            var avatar=mgr.Figures["fixture-avatar"]; InstallMeasuredRig(avatar);
            var steering=new PlayerSteering(mgr,builder); steering.SetActive(true);
            position=new(mgr,builder,steering,source); using(var map=await source.GetWorldMapAsync()) position.SetActive(true,map.RootElement);
            offers=new(mgr,builder,steering,source,hud,position); offers.SetActive(true); await offers.PendingPropAction!;
            source.StateOverride=JsonNode.Parse("""{"current":[{"execution_id":"old","status":"active"}],"outgoing":[]}""")!.AsObject();
            source.MapOverride=Read("worldmap_active.json");
            await offers.PropActions!.RefreshAsync(); mgr.Tick(0); steering.SetSeated(true);
            Is("initial held pose",avatar.CurrentClip=="sitting");
            source.Offers[0]!["enabled"]=true; source.Offers[0]!["reason"]="";
            await offers.RefreshSemanticOffersAsync();
            Is("enabled menu pick while seated and owning run",offers.Pick(new(3,2,0),new(0,-1,0),new Vector2(100,120)));
            Is("server enabled row stays enabled",hud.SceneOwned("placeMenu")!["offer"]!["prop_actions"]![0]!["enabled"]!.GetValue<bool>());
            source.PendingRequest=new TaskCompletionSource<JsonDocument>();
            var action=source.Offers[0]!;
            hud.Handlers["pickPropAction"](new JsonArray(action["action_id"]!.DeepClone(),action["target"]!.DeepClone(),action["definition_revision"]!.DeepClone()));
            Is("unanswered request retains seat",steering.AvatarSeated && avatar.CurrentClip=="sitting");
            source.StateOverride["current"]![0]!["execution_id"]="new"; source.StateOverride["current"]![0]!["status"]="approaching";
            source.MapOverride=Read("worldmap_approach.json");
            var row=source.MapOverride["characters"]![0]!; row["activity_animation"]="fixture-get-up";
            row["travel"]!["waypoints"]=new JsonArray(new JsonArray(2,0),new JsonArray(2,-.5),new JsonArray(4,-.5));
            row["travel"]!["progress_m"]=0; row["travel"]!["starts_in_s"]=.75;
            row["travel"]!["paces_m_s_real"]=null; row["travel"]!["floor_y"]=0;
            avatar.FaceTowards(new Vector3(0,0,1),snap:true);
            using(var early=JsonDocument.Parse(source.MapOverride.ToJsonString())) mgr.ApplyPolled(early.RootElement.Clone());
            mgr.Tick(1.0/60);
            var adoptedBeforeAnswer=avatar.Route;
            Is("prepared seated switch plays exit before private answer",avatar.Bridging && avatar.CurrentClip=="fixture-get-up");
            double beforeAnswerTime=avatar.ClipTime;
            source.PendingRequest.SetResult(JsonDocument.Parse("""{"execution_id":"new","status":"approaching"}"""));
            await offers.PendingPropAction!;
            Is("request releases local seat without cancel call",!steering.AvatarSeated && source.CancelRequests==0);
            Is("no standing frame at seat",avatar.CurrentClip=="fixture-get-up");
            Is("private answer keeps adopted approach",ReferenceEquals(adoptedBeforeAnswer,avatar.Route));
            Is("private answer never restarts exit",Math.Abs(avatar.ClipTime-beforeAnswerTime)<1e-6);
            mgr.Tick(0);
            Is("exit plays during countdown",avatar.CurrentClip=="fixture-get-up" && avatar.Bridging);
            Is("future switch has no catch-up",avatar.Route!.CatchUpRate==0);
            Is("root remains at seat",Math.Abs(avatar.Position.Z)<1e-6);
            var previous=avatar.Body!.GlobalPosition;
            for(int i=0;i<44;i++) {
                mgr.Tick(1.0/60);
                var point=avatar.Body.GlobalPosition;
                Is("rendered exit/handoff <= .25m",point.DistanceTo(previous)<=.25001); previous=point;
                Is("no walking before start",avatar.CurrentClip!="walk");
            }
            Is("clip travel handed to stand point",Math.Abs(avatar.Position.X-2)<1e-5 && Math.Abs(avatar.Position.Z+.5)<1e-5);
            row["travel"]!["starts_in_s"]=null; row["travel"]!["progress_m"]=.5;
            row["travel"]!["paces_m_s_real"]=new JsonArray(null,1); row["activity_animation"]="";
            await offers.PropActions.RefreshAsync();
            for(int i=0;i<20;i++) {
                mgr.Tick(1.0/60); var point=avatar.Body.GlobalPosition;
                Is("rendered walk <= .25m",point.DistanceTo(previous)<=.25001); previous=point;
            }
            Is("walk begins on second leg",avatar.Position.X>2 && Math.Abs(avatar.Position.Z+.5)<1e-5 && avatar.CurrentClip=="walk");
            Is("switch diagnostic includes execution clip countdown",logs.Any(l=>l.Contains("switch from seat: old execution=old exit clip=fixture-get-up starts_in_s=0.750",StringComparison.Ordinal)));
            return n;
        } finally { offers?.Dispose(); position?.Dispose(); hud.Free(); builder.StopResidency(); builder.Models?.FreeAll(); world.QueueFree(); }
    }
    private static async Task<int> CheckUpperStorey(Node3D host,string fixtures)
    {
        int n=0;
        void Is(string label,bool ok) { n++; if(!ok) throw new InvalidOperationException("propactions upper "+label); }
        void Near(string label,double got,double want) => Is($"{label}: {got} expected {want}",Math.Abs(got-want)<.0002);
        var fixture=new FixtureSource(Path.Combine(fixtures,"propactions"),fixtures);
        JsonObject Read(string file)=>JsonNode.Parse(File.ReadAllText(Path.Combine(fixture.Dir,file)))!.AsObject();
        var scene=Read("scene_loc-props.json");
        scene["levels"]![0]!["level"]=1; scene["levels"]![0]!["floor_y"]=9.4;
        scene["rooms"]![0]!["level"]=1; scene["models"]![0]!["level"]=1;
        scene["models"]![0]!["bottom_y"]=9.4;
        scene["plates"]=new JsonArray(new JsonObject { ["level"]=1,["room_id"]="r-props",
            ["outline"]=scene["rooms"]![0]!["outline"]!.DeepClone(),["holes"]=new JsonArray(),
            ["top_y"]=9.4,["thickness"]=.02,["opacity_role"]="upper" });
        scene["markers"]![0]!["y_world"]=9.927; scene["markers"]![0]!["floor_y"]=9.4;
        var source=new MenuSource(fixture) { SceneOverride=scene };
        var world=new Node3D(); host.AddChild(world);
        var builder=new WorldBuilder(source,_=>{},strict:true); var hud=new HudOverlay();
        AvatarPositionController? position=null; AvatarOffersController? offers=null;
        try {
            await builder.BuildAsync(world,"Fixture Prop Room"); builder.SetOpen("loc-props",true);
            var tile=builder.Slots["loc-props"]; tile.Fade.Snap(1); builder.SetLevel("loc-props",1);
            var mgr=new FigureManager(source,builder.Height!,_=>{},strict:true) { AutoTick=false,Slots=()=>builder.Slots,GroundYAt=builder.FigureGroundY };
            world.AddChild(mgr); using(var map=await source.GetWorldMapAsync()) await mgr.Apply(map.RootElement);
            var avatar=mgr.Figures["fixture-avatar"]; InstallMeasuredRig(avatar);
            var steering=new PlayerSteering(mgr,builder); steering.SetActive(true);
            position=new(mgr,builder,steering,source); using(var map=await source.GetWorldMapAsync()) position.SetActive(true,map.RootElement);
            offers=new(mgr,builder,steering,source,hud,position); offers.SetActive(true); await offers.PendingPropAction!;
            source.PendingRequest=new TaskCompletionSource<JsonDocument>();
            var request=source.Offers[0]!;
            hud.Handlers["pickPropAction"](new JsonArray(request["action_id"]!.DeepClone(),request["target"]!.DeepClone(),request["definition_revision"]!.DeepClone()));
            var beforePrivate=avatar.Position;
            source.MapOverride=Read("worldmap_approach.json"); source.MapOverride["characters"]![0]!["travel"]!["progress_m"]=5.4;
            source.MapOverride["characters"]![0]!["travel"]!["floor_y"]=9.4;
            using(var poll=JsonDocument.Parse(source.MapOverride.ToJsonString())) mgr.ApplyPolled(poll.RootElement.Clone());
            Is("prepared approach adopted before private state",avatar.Route is { OwnedApproach:true } && avatar.Position.DistanceTo(beforePrivate)<.00001);
            mgr.Tick(1.0/60);
            Is("pre-private frame stays continuous",double.Hypot(avatar.Position.X-beforePrivate.X,avatar.Position.Z-beforePrivate.Z)<=.25001);
            source.MapOverride=Read("worldmap.json");
            source.PendingRequest.SetResult(JsonDocument.Parse("{\"status\":\"refused\",\"reason\":\"claimed\"}"));
            await offers.PendingPropAction!; source.PendingRequest=null;
            foreach(bool explicitFloor in new[]{true,false}) {
                source.StateOverride=new JsonObject { ["current"]=new JsonArray(new JsonObject { ["execution_id"]="upper-"+explicitFloor,["status"]="approaching" }),["outgoing"]=new JsonArray() };
                source.MapOverride=Read("worldmap_approach.json");
                source.MapOverride["characters"]![0]!["travel"]!["journey_id"]="upper-"+explicitFloor;
                if(explicitFloor) source.MapOverride["characters"]![0]!["travel"]!["floor_y"]=9.4;
                await offers.PropActions!.RefreshAsync();
                for(int frame=0;frame<420;frame++) mgr.Tick(1.0/60);
                Near("approach uses upper floor "+explicitFloor,avatar.Position.Y,9.41);
                Is("owned approach suppresses reports",!position.Channel.CanReport());
                source.StateOverride["current"]![0]!["status"]="active";
                int transitionReads=source.OfferRequests;
                offers.RefreshPropWorld=()=>Task.CompletedTask;
                await offers.PropActions.RefreshAsync();
                Is("private arrival refreshes offers without map event",source.OfferRequests>transitionReads);
                source.StateOverride["current"]!.AsArray().Clear();
                transitionReads=source.OfferRequests;
                await offers.PropActions.RefreshAsync();
                Is("polled own completion refreshes offers without map event",source.OfferRequests>transitionReads);
                source.StateOverride["current"]!.AsArray().Add(new JsonObject { ["execution_id"]="upper-"+explicitFloor,["status"]="active" });
                offers.RefreshPropWorld=null;
                await offers.PropActions.RefreshAsync();
                Is("private active state retains older exact approach",avatar.Route?.ExactPath is not null);
                source.StateOverride["current"]![0]!["status"]="approaching";
                if(!explicitFloor) {
                    source.MapOverride=Read("worldmap_entry.json");
                    var spec=source.MapOverride["characters"]![0]!["prop_action_entry"]!;
                    spec["access"]!["y"]=9.4; spec["anchor"]!["y"]=9.529;
                    await offers.PropActions.RefreshAsync(); mgr.Tick(0);
                    Near("upper bridge access",avatar.Position.Y,9.4);
                    Near("upper bridge clip clock",avatar.ClipTime,1);
                    Near("upper bridge support",avatar.PropEntryLift,.0645);
                }
                // Direct arrival has no bridge projection. It must play the held pose immediately.
                Animation? delayedPose=null;
                if(explicitFloor) {
                    var library=avatar.Player!.GetAnimationLibrary("");
                    delayedPose=library.GetAnimation("sitting"); library.RemoveAnimation("sitting");
                    avatar.Transitions=new[]{new ClipTransition("*","sitting","fixture-sit-down",0)};
                    avatar.FitClip=_=>false;
                }
                source.StateOverride["current"]![0]!["status"]="active";
                source.MapOverride=Read("worldmap_active.json");
                await offers.PropActions.RefreshAsync(); mgr.Tick(0);
                if(delayedPose is { } heldClip) {
                    Is("unfitted direct pose never starts bridge",!avatar.Bridging);
                    avatar.FitClip=kind=> { if(kind!="sitting") return false; avatar.Player!.GetAnimationLibrary("").AddAnimation(kind,heldClip); return true; };
                    mgr.Tick(0);
                    Is("direct retries lazy pose without another poll",avatar.CurrentClip=="sitting" && !avatar.Bridging);
                    InstallMeasuredRig(avatar); mgr.Tick(0);
                    Is("direct model swap retains held pose without bridge",avatar.CurrentClip=="sitting" && !avatar.Bridging);
                }
                Near("direct anchor",avatar.Position.Y,9.529);
                Is("direct seated clip without bridge",avatar.CurrentClip=="sitting" && avatar.PropEntry is null && !avatar.Bridging);
                int offerReads=source.OfferRequests;
                offers.RefreshPropWorld=()=>Task.CompletedTask;
                source.EnableOffersOnCancel=true;
                steering.Step(.016,new HashSet<string>{"w"},0); await offers.PendingPropAction!;
                Is("release refetches semantic offers without a map event",source.OfferRequests>offerReads);
                offers.RefreshPropWorld=null;
                await offers.PropActions.RefreshAsync();
                Is("keys await explicit cancellation",source.CancelRequests==(explicitFloor ? 1 : 2) && !steering.PropActionDriven && !steering.PropPreparationPending);
                Near("release correction stays on upper floor",avatar.Target.Y,9.41);
            }
            return n;
        } finally { offers?.Dispose(); position?.Dispose(); hud.Free(); builder.StopResidency(); builder.Models?.FreeAll(); world.QueueFree(); }
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
        public JsonObject? MapOverride,StateOverride,SceneOverride;
        public int CancelRequests,OfferRequests,WorldRequests,StateRequests;
        public TaskCompletionSource<JsonDocument>? PendingState;
        public bool EnableOffersOnCancel;
        public TaskCompletionSource<JsonDocument>? PendingOffers,PendingRequest;
        public Task<JsonDocument> CancelPropActionAsync(string executionId,System.Threading.CancellationToken ct=default)
        {
            CancelRequests++; if(EnableOffersOnCancel) { Offers[0]!["enabled"]=true; Offers[0]!["reason"]=""; } MapOverride=JsonNode.Parse(File.ReadAllText(Path.Combine(_fixture.Dir,"worldmap_cancelled.json")))!.AsObject();
            StateOverride=new JsonObject { ["current"]=new JsonArray(),["outgoing"]=new JsonArray() };
            return Task.FromResult(JsonDocument.Parse("{\"status\":\"cancelled\"}"));
        }
        public bool SupportsPropActions=>true;
        public MenuSource(FixtureSource fixture) { _fixture=fixture; Offers=JsonNode.Parse(File.ReadAllText(Path.Combine(fixture.Dir,"offers.json")))!.AsArray(); Offers[0]!["enabled"]=false; Offers[0]!["reason"]="claimed"; }
        public Task<JsonDocument> GetPropActionsAsync() { OfferRequests++; return PendingOffers?.Task ?? Task.FromResult(JsonDocument.Parse(Offers.ToJsonString())); }
        public Task<JsonDocument> GetPropActionStateAsync() { StateRequests++; return PendingState?.Task ?? Task.FromResult(JsonDocument.Parse(StateOverride?.ToJsonString() ?? "{\"current\":[],\"outgoing\":[],\"incoming\":[],\"recent_results\":[]}")); }
        public Task<JsonDocument> GetPlacesAsync()=>Task.FromResult(JsonDocument.Parse("{\"room_id\":\"r-props\",\"places\":[]}"));
        public Task<JsonDocument> RequestPropActionAsync(string actionId,JsonElement target,string revision,string? partner=null,System.Threading.CancellationToken ct=default)
        { Request=JsonNode.Parse(PropActionRequest.Request(actionId,target,revision,partner).GetRawText()); return PendingRequest?.Task ?? Task.FromResult(JsonDocument.Parse("{\"execution_id\":\"\",\"status\":\"refused\",\"reason\":\"claimed\"}")); }
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
        var exit=new Animation { Length=.5 }; library.AddAnimation("fixture-get-up",exit);
        library.AddAnimation("fixture-start-walk",new Animation { Length=.5 });
        player.AddAnimationLibrary("",library);
        fig.SetBody(body,true,skeleton,player,new[]{"fixture-start-walk","fixture-get-up","fixture-sit-down","sitting","walk",FigureClips.PoseKind("standing",fig.Poses)},bodyHeight:1.7); fig.BaseScale=1;
        fig.Extras=new Dictionary<Animation,ClipExtras> {
            [clip]=new() { Path=new RootPath(new float[]{0,2},new float[]{0,0,0,-1}) },
            [exit]=new() { Path=new RootPath(new float[]{0,.5f},new float[]{0,0,0,-.5f}),Lift=new BridgeLiftSpec(0,.5) } };
        bool ready=!deferred; int requests=0;
        fig.FitClip=kind=> { requests++; if(!ready || kind!="fixture-sit-down") return false; library.AddAnimation(kind,clip); return true; };
        return (()=>ready=true,()=>requests);
    }
}
