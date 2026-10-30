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

namespace AnimaNative.Check;

public static partial class PropActionsCheck
{
    private static JsonObject Motion(string id="motion-83")=>JsonNode.Parse($$"""
        {"execution_id":"{{id}}","journey_id":"journey-{{id}}","room_id":"r-props","floor_y":0,
         "waypoints":[[-3,-2],[0,-2],[0,-1],[2,-1]],"paces_m_s_real":[1,1,1],"departure":null,
         "access":{"x":2,"y":0,"z":-1,"yaw":180},
         "anchor":{"x":2,"y":0.129,"z":0,"yaw":180,"root_offset":0,"place_id":"prop-bench-56-seat56","slot":1},
         "entry":{"mode":"bridge","kind":"fixture-sit-down","pose_key":"sitting","duration_s":2},"height_cm":170,"role":null}
        """)!.AsObject();
    private static JsonObject RunState(JsonObject plan,string status="approaching")=>new() {
        ["current"]=new JsonArray(new JsonObject { ["execution_id"]=plan["execution_id"]!.DeepClone(),["status"]=status,["motion"]=plan.DeepClone() }),["outgoing"]=new JsonArray() };
    private static JsonObject Answer(JsonObject plan)=>new() { ["execution_id"]=plan["execution_id"]!.DeepClone(),["status"]="approaching",["motion"]=plan.DeepClone() };
    private static async Task<int> CheckMotionPlayback(Node3D host,string fixtures)
    {
        int checks=CheckMotionVectors(fixtures);
        void Is(string label,bool ok) { checks++; if(!ok) throw new InvalidOperationException("propactions B1 "+label); }
        void Near(string label,double actual,double expected,double eps=1e-5)=>Is($"{label}: got={actual:R} expected={expected:R}",Math.Abs(actual-expected)<=eps);
        JsonObject Read(string file)=>JsonNode.Parse(File.ReadAllText(Path.Combine(fixtures,"propactions",file)))!.AsObject();
        var fixture=new FixtureSource(Path.Combine(fixtures,"propactions"),fixtures);
        var source=new MenuSource(fixture); var world=new Node3D(); host.AddChild(world);
        var builder=new WorldBuilder(source,_=>{},strict:true); var hud=new HudOverlay();
        AvatarPositionController? position=null; AvatarOffersController? offers=null;
        double now=1000;
        try {
            await builder.BuildAsync(world,"Fixture Prop Room"); builder.SetOpen("loc-props",true); builder.Slots["loc-props"].Fade.Snap(1);
            var mgr=new FigureManager(source,builder.Height!,_=>{},strict:true) { AutoTick=false,Slots=()=>builder.Slots,GroundYAt=builder.FigureGroundY };
            world.AddChild(mgr);
            using var initial=await source.GetWorldMapAsync(); await mgr.Apply(initial.RootElement);
            var avatar=mgr.Figures["fixture-avatar"]; InstallMeasuredRig(avatar);
            var steering=new PlayerSteering(mgr,builder); steering.SetActive(true);
            position=new(mgr,builder,steering,source,()=>now); position.SetActive(true,initial.RootElement);
            offers=new(mgr,builder,steering,source,hud,position,()=>now); offers.SetActive(true); await offers.PendingPropAction!;
            void Step(double seconds) { now+=seconds*1000; mgr.Tick(seconds); }
            async Task Start(JsonObject plan,bool respond=false) {
                source.StateOverride=RunState(plan);
                if(respond) { source.RespondAnswer=Answer(plan); hud.Handlers["respondPropAction"](new JsonArray(plan["execution_id"]!.DeepClone(),true)); }
                else {
                    source.PendingRequest=new(); source.PendingRequest.SetResult(JsonDocument.Parse(Answer(plan).ToJsonString()));
                    var action=source.Offers[0]!;
                    hud.Handlers["pickPropAction"](new JsonArray(action["action_id"]!.DeepClone(),action["target"]!.DeepClone(),action["definition_revision"]!.DeepClone()));
                }
                await offers.PendingPropAction!; source.PendingRequest=null;
            }
            async Task End(JsonObject plan,string status="cancelled") {
                source.StateOverride=new JsonObject { ["current"]=new JsonArray(),["outgoing"]=new JsonArray(),["recent_results"]=new JsonArray(new JsonObject { ["execution_id"]=plan["execution_id"]!.DeepClone(),["status"]=status }) };
                await offers.PropActions!.RefreshAsync();
            }
            var first=Motion();
            source.PendingRequest=new(); source.PendingState=new();
            var action=source.Offers[0]!;
            hud.Handlers["pickPropAction"](new JsonArray(action["action_id"]!.DeepClone(),action["target"]!.DeepClone(),action["definition_revision"]!.DeepClone()));
                        source.PendingRequest.SetResult(JsonDocument.Parse(Answer(first).ToJsonString()));
            Step(.25);
            Near("answer moves before state or world poll",avatar.Position.X,-2.75);
            Is("answer blocks steering and position writes",steering.PropActionDriven && !position.Channel.CanReport());
            source.StateOverride=RunState(first); source.PendingState.SetResult(JsonDocument.Parse(source.StateOverride.ToJsonString()));
            source.PendingState=null; await offers.PendingPropAction!; source.PendingRequest=null;
            var playback=mgr.OwnPropMotion;
            source.MapOverride=Read("worldmap_approach.json"); source.MapOverride["characters"]![0]!["travel"]!["progress_m"]=5.8;
            source.MapOverride["characters"]![0]!["travel"]!["starts_in_s"]=100;
            mgr.ApplyPolled(JsonSerializer.SerializeToElement(source.MapOverride));
            Near("world route poll cannot move own root",avatar.Position.X,-2.75);
            await offers.PropActions!.RefreshAsync();
            Is("repeated state does not restart plan",ReferenceEquals(playback,mgr.OwnPropMotion));
            Step(.25); Near("own clock ignores server lead/progress",avatar.Position.X,-2.5); Near("walking clearance",avatar.Position.Y,.01);
            Step(5.5); Is("entry starts at own access time",mgr.OwnPropMotion?.Phase=="entry"); Near("entry begins immediately at access",avatar.Position.Z,-1);
            Step(1); Near("measured entry phase",avatar.ClipTime,1); Near("measured entry support",avatar.PropEntryLift,.0645); Near("measured body root path",avatar.Body!.GlobalPosition.Z-avatar.Position.Z,.5);
            source.MapOverride=Read("worldmap_active.json"); source.MapOverride["characters"]![0]!["place"]!["slot"]=1;
            source.MapOverride["characters"]![0]!["pos"]!["x"]=99;
            mgr.ApplyPolled(JsonSerializer.SerializeToElement(source.MapOverride));
            Near("early authoritative seat cannot cut entry",avatar.Position.Z,-1);
            Step(1); Near("anchor X ignores local marker and server correction",avatar.Position.X,2); Near("anchor root Y",avatar.Position.Y,.129); Near("anchor Z",avatar.Position.Z,0);
            Is("arrived uses direct held clip",avatar.CurrentClip=="sitting" && !avatar.Bridging);
            var library=avatar.Player!.GetAnimationLibrary(""); library.AddAnimation("author-held",new Animation { Length=1,LoopMode=Animation.LoopModeEnum.Linear });
            avatar.FitClip=kind=>kind=="author-held";
            source.MapOverride["characters"]![0]!["activity_animation"]="author-held";
            mgr.ApplyPolled(JsonSerializer.SerializeToElement(source.MapOverride)); Step(0);
            Is("matching anchor adopts changed authored activity",avatar.CurrentClip=="author-held"); Near("activity adoption retains anchor",avatar.Position.X,2);
            InstallMeasuredRig(avatar); avatar.Player!.GetAnimationLibrary("").AddAnimation("author-held",new Animation { Length=1,LoopMode=Animation.LoopModeEnum.Linear }); Step(0); Near("body replacement retains anchor",avatar.Position.Y,.129);
            Is("body replacement replays available held pose",avatar.CurrentClip=="sitting" || avatar.CurrentClip=="author-held");
            source.StateOverride=RunState(first); source.StateOverride["current"]![0]!["motion"]!["paces_m_s_real"]=null;
            await offers.PropActions!.RefreshAsync(); Step(1); Near("late frozen state cannot rewind arrived anchor",avatar.Position.Z,0);
            source.MapOverride=Read("worldmap_cancelled.json"); await End(first);
            Is("terminal releases all local gates",mgr.OwnPropMotion is null && !mgr.ServerDriven && !steering.PropActionDriven && !steering.PropPreparationPending && !position.Channel.ReportsPaused);

            // A pair initiator and a reloaded owner receive their own plan through current, before any world poll.
            foreach(string id in new[]{"pair-state","reload-state"}) {
                var plan=Motion(id); source.StateOverride=RunState(plan); source.MapOverride=Read("worldmap_pair.json");
                await offers.PropActions!.RefreshAsync(); Step(.5);
                Near(id+" advances from private plan",avatar.Position.X,-2.5);
                var npc=mgr.Figures["fixture-npc"];
                Is(id+" observer retains local_approach",npc.Route?.ExactPath is not null);
                Near(id+" observer route",npc.Position.X,4.5);
                await End(plan);
            }
            var accepted=Motion("respond"); await Start(accepted,respond:true); Step(.5); Near("respond answer starts own walk",avatar.Position.X,-2.5); await End(accepted);

            // The exit clock is measured clip time. Its non-linear path remains on the held-seat root.
            foreach(bool clip in new[]{true,false}) {
                var plan=Motion("departure-"+clip);
                plan["waypoints"]=new JsonArray(new JsonArray(2,0),new JsonArray(2,-.5),new JsonArray(4,-.5));
                plan["paces_m_s_real"]=new JsonArray(null,1);
                plan["departure"]=new JsonObject { ["seat"]=new JsonArray(2,0),["stand"]=new JsonArray(2,-.5),["exit_clip"]=clip ? "fixture-get-up" : "",["exit_s"]=clip ? .5 : 0 };
                plan["access"]=new JsonObject { ["x"]=4,["y"]=0,["z"]=-.5,["yaw"]=90 };
                avatar.SnapTo(new(2,.129f,0)); avatar.FaceTowards(Vector3.Back,snap:true);
                if(clip) {
                    var exit=avatar.Player!.GetAnimationLibrary("").GetAnimation("fixture-get-up");
                    var extras=new Dictionary<Animation,ClipExtras>(avatar.Extras);
                    extras[exit]=new() { Path=new RootPath(new float[]{0,.25f,.5f},new float[]{0,0,0,-.1f,0,-.5f}),Lift=new BridgeLiftSpec(0,.5) }; avatar.Extras=extras;
                }
                await Start(plan);
                if(clip) {
                    Step(.25); Near("exit holds seat root",avatar.Position.Z,0); Near("exit follows measured nonlinear path",avatar.Body!.GlobalPosition.Z,-.1); Near("exit seeks own measured clip",avatar.ClipTime,.25); Near("exit uses nonlinear measured support lift",avatar.Body!.GlobalPosition.Y,.1052);
                    Step(.25); Near("exit ends on server stand",avatar.Position.Z,-.5);
                } else { Near("clipless departure stands in answer batch",avatar.Position.Z,-.5); Is("clipless departure upright",avatar.CurrentClip=="walk" || avatar.CurrentClip==FigureClips.PoseKind("standing",avatar.Poses)); }
                Step(.25); Near("departure then exact pace",avatar.Position.X,2.25); await End(plan);
            }
            var frozen=Motion("frozen"); frozen["paces_m_s_real"]=null;
            await Start(frozen); Step(30); Near("frozen clock holds initial X",avatar.Position.X,-3); Is("frozen does not open entry",mgr.OwnPropMotion?.Phase=="frozen");
            frozen["paces_m_s_real"]=new JsonArray(1,1,1); source.StateOverride=RunState(frozen); await offers.PropActions!.RefreshAsync(); Step(.5);
            Near("same journey resumes frozen clock without leap",avatar.Position.X,-2.5);
            frozen["paces_m_s_real"]=null; source.StateOverride=RunState(frozen); await offers.PropActions.RefreshAsync(); Step(20); Near("mid-walk freeze preserves shown progress",avatar.Position.X,-2.5);
            frozen["paces_m_s_real"]=new JsonArray(2,2,2); source.StateOverride=RunState(frozen); await offers.PropActions.RefreshAsync(); Step(.25); Near("pace update resumes at shown segment",avatar.Position.X,-2);
            await End(frozen);
            var completed=Motion("completed"); await Start(completed); Step(8);
            source.StateOverride=RunState(completed,"active"); await offers.PropActions.RefreshAsync(); await End(completed,"completed");
            Is("completed active action releases anchor pin",mgr.OwnPropMotion is null && !steering.PropActionDriven);
            foreach(bool explicitFloor in new[]{true,false}) {
                var upper=Motion("upper-"+explicitFloor); upper["floor_y"]=explicitFloor ? JsonValue.Create(9.4) : null;
                upper["access"]!["y"]=9.4; upper["anchor"]!["y"]=9.529;
                await Start(upper); Step(.25); Near("floor source "+explicitFloor,avatar.Position.Y,explicitFloor ? 9.41 : .01);
                await End(upper);
            }
            var entryFrozen=Motion("entry-freeze"); await Start(entryFrozen); Step(7);
            entryFrozen["paces_m_s_real"]=null; source.StateOverride=RunState(entryFrozen); await offers.PropActions!.RefreshAsync(); Step(20);
            Near("entry freeze holds measured clip phase",avatar.ClipTime,1); Near("entry freeze stays at access",avatar.Position.Z,-1);
            entryFrozen["paces_m_s_real"]=new JsonArray(1,1,1); source.StateOverride=RunState(entryFrozen); await offers.PropActions.RefreshAsync(); Step(.5);
            Near("entry resumes remaining own clip duration",avatar.ClipTime,1.5); Step(.5); Near("resumed entry ends on anchor",avatar.Position.Z,0); await End(entryFrozen);
            // Cancellation and failure during the measured entry release where the body is rendered.
            foreach(string terminal in new[]{"cancelled","failed"}) {
                var interrupted=Motion("entry-"+terminal); await Start(interrupted); Step(7);
                var rendered=avatar.Body!.GlobalPosition;
                await End(interrupted,terminal);
                Near(terminal+" preserves measured rendered X",avatar.Body.GlobalPosition.X,rendered.X);
                Near(terminal+" preserves measured rendered Y",avatar.Body.GlobalPosition.Y,rendered.Y);
                Near(terminal+" preserves measured rendered Z",avatar.Body.GlobalPosition.Z,rendered.Z);
                Is(terminal+" clears route and pose gates",avatar.Route is null && avatar.PropEntry is null && !avatar.PropEntryBlocked && avatar.Face is null && avatar.Lean is null);
                Is(terminal+" returns steering",steering.WalkTo(new(avatar.Position.X+.5,avatar.Position.Z))); steering.CancelRoute();
            }
            foreach(bool clip in new[]{true,false}) {
                var seated=Motion("cancel-"+clip); await Start(seated); Step(8);
                source.CancelAnswer=new JsonObject { ["execution_id"]=seated["execution_id"]!.DeepClone(),["status"]="cancelled",["motion"]=new JsonObject {
                    ["seat"]=new JsonArray(2,0),["stand"]=new JsonArray(2,.5),["exit_clip"]=clip ? "fixture-get-up" : "",["exit_s"]=clip ? .5 : 0 } };
                if(clip) {
                    source.CancelError=new ApiException(409,"/play/prop-actions/cancel","claimed");
                    var beforeCancel=mgr.OwnPropMotion;
                    hud.Handlers["cancelPropAction"](new JsonArray(seated["execution_id"]!.DeepClone())); await offers.PendingPropAction!;
                    Is("failed cancellation retains motion and permits retry",ReferenceEquals(beforeCancel,mgr.OwnPropMotion) && steering.PropActionDriven && !offers.PropActions!.Paused);
                    source.CancelError=null;
                }
                var stalePair=Read("worldmap_active.json"); stalePair["characters"]![0]!["interaction"]=JsonNode.Parse("""{"id":"old-pair","kind":"pair-pose","role":"b","partner":"fixture-npc","anchor":{"x":2,"z":0,"yaw":0,"place_id":"prop-bench-56-seat56"},"elapsed_s":0,"clip_duration_s":1,"loop":true,"rate":1}""");
                stalePair["characters"]![0]!["interaction"]!["id"]="old-pair-"+clip;
                mgr.ApplyPolled(JsonSerializer.SerializeToElement(stalePair)); Step(0); Is("cancel starts with authoritative pair present",avatar.Pair is not null);
                int states=source.StateRequests,maps=source.WorldRequests;
                hud.Handlers["cancelPropAction"](new JsonArray(seated["execution_id"]!.DeepClone())); await offers.PendingPropAction!;
                Is("cancel answer needs no follow-up state or world poll",source.StateRequests==states && source.WorldRequests==maps);
                if(clip) { Is("cancel retains ownership during exit",mgr.OwnPropMotion?.Cancel==true && steering.PropActionDriven); Step(.25); Near("cancel measured exit clock",avatar.ClipTime,.25); Step(.25); }
                Near("cancel answer stands at server point",avatar.Position.Z,.5);
                Is($"cancel hands back input after exit own={mgr.OwnPropMotion?.Phase} driven={steering.PropActionDriven} paused={position.Channel.ReportsPaused} gate={offers.PropActions!.Paused}",mgr.OwnPropMotion is null && !steering.PropActionDriven && !position.Channel.ReportsPaused);
                mgr.ApplyPolled(JsonSerializer.SerializeToElement(stalePair)); Step(0); Near("stale seat poll cannot reclaim cancelled figure",avatar.Position.Z,.5); Is("stale paired poll cannot reclaim released figure",avatar.Pair is null);
                stalePair["characters"]![0]!["interaction"]!["id"]="fresh-pair-"+clip;
                mgr.ApplyPolled(JsonSerializer.SerializeToElement(stalePair)); Step(0); Is("new interaction remains adoptable after release",avatar.Pair is not null);
            }
            // Real HTTP rejection is an exception, while the in-page verdict can carry refused/failed JSON.
            foreach(bool exception in new[]{false,true}) {
                var rejected=Motion("reject-"+exception); await Start(rejected); Step(.5); var rendered=avatar.Position;
                source.PendingRequest=new(); source.StateOverride=RunState(rejected,"active");
                hud.Handlers["pickPropAction"](new JsonArray(action["action_id"]!.DeepClone(),action["target"]!.DeepClone(),action["definition_revision"]!.DeepClone()));
                if(exception) source.PendingRequest.SetException(new ApiException(409,"/play/prop-actions/request","stale_definition"));
                else source.PendingRequest.SetResult(JsonDocument.Parse("{\"status\":\"refused\",\"reason\":\"claimed\"}"));
                await offers.PendingPropAction!; source.PendingRequest=null;
                Is("refusal/exception releases own playback despite stale active state "+exception,mgr.OwnPropMotion is null && !steering.PropActionDriven && offers.PropActions!.OwnedRun is null);
                Near("refusal stays at rendered point "+exception,avatar.Position.X,rendered.X);
            }
            var offline=Motion("offline-refusal"); await Start(offline); Step(.25);
            source.PendingRequest=new(); source.PendingState=new();
            hud.Handlers["pickPropAction"](new JsonArray(action["action_id"]!.DeepClone(),action["target"]!.DeepClone(),action["definition_revision"]!.DeepClone()));
            source.PendingRequest.SetException(new ApiException(409,"/play/prop-actions/request","stale_definition"));
            Is("known request failure releases before blocked state refresh",mgr.OwnPropMotion is null && !steering.PropPreparationPending && !position.Channel.ReportsPaused && !offers.PropActions!.Paused);
            source.PendingState.SetException(new InvalidOperationException("state offline")); await offers.PendingPropAction!;
            source.PendingRequest=source.PendingState=null;
            Is("failed reconciliation cannot reclaim released input",mgr.OwnPropMotion is null && !mgr.ServerDriven && !steering.PropActionDriven && !steering.PropPreparationPending && !position.Channel.ReportsPaused && !offers.PropActions!.Paused);
            Is("offline failure remains steerable",steering.WalkTo(new(avatar.Position.X+.5,avatar.Position.Z))); steering.CancelRoute();
            // Pair pose_key names a semantic kind; role selects the installed half immediately.
            var pair=Motion("pair-role"); pair["entry"]!["pose_key"]="pair-pose"; pair["role"]="b";
            library=avatar.Player!.GetAnimationLibrary(""); library.AddAnimation("pair-pose__b",new Animation { Length=1,LoopMode=Animation.LoopModeEnum.Linear });
            avatar.FitClip=kind=>kind=="pair-pose__b";
            await Start(pair); Step(8); Is("pair role selects bound half",avatar.CurrentClip=="pair-pose__b"); await End(pair);

            var raced=Motion("active-pair-before-state"); raced["entry"]!["pose_key"]="pair-pose"; raced["role"]="b";
            source.MapOverride=Read("worldmap_active.json"); source.MapOverride["characters"]![0]!["place"]!["slot"]=1;
            source.MapOverride["characters"]![0]!["interaction"]=JsonNode.Parse("""{"id":"valid-pair-before-state","kind":"pair-pose","role":"b","partner":"fixture-npc","anchor":{"x":2,"z":0,"yaw":0,"place_id":"prop-bench-56-seat56"},"elapsed_s":0,"clip_duration_s":1,"loop":true,"rate":1}""");
            mgr.ApplyPolled(JsonSerializer.SerializeToElement(source.MapOverride)); source.StateOverride=RunState(raced);
            await offers.PropActions!.RefreshAsync(); Step(8); Is("early matching active pair survives delayed state plan",avatar.Pair?.Id=="valid-pair-before-state"); await End(raced);
            source.MapOverride=Read("worldmap_cancelled.json");
            // The detached HUD transports the same request answer before the state reconciliation starts.
            var detached=Motion("hud-result"); source.PendingState=new();
            hud.hud_bridge(new JsonObject { ["v"]=4,["kind"]="prop-actions-changed",["request_id"]="hud:83",["source"]="request",["result"]=Answer(detached) }.ToJsonString());
            Step(.25); Near("detached HUD answer starts immediately",avatar.Position.X,-2.75);
            source.PendingState.SetResult(JsonDocument.Parse(RunState(detached).ToJsonString())); source.PendingState=null; await offers.PendingPropAction!;
            source.StateOverride=RunState(detached,"active");
            hud.hud_bridge(new JsonObject { ["v"]=4,["kind"]="prop-actions-changed",["request_id"]="hud:refused",["source"]="request",["result"]=new JsonObject { ["status"]="refused",["reason"]="claimed" } }.ToJsonString());
            await offers.PendingPropAction!;
            Is("detached refusal tombstones old active state",mgr.OwnPropMotion is null && !steering.PropActionDriven && offers.PropActions!.OwnedRun is null);
            var prepareWrite=new TaskCompletionSource(); int notices=0; hud.PropActionPrepare=_=>prepareWrite.Task; hud.PropActionsChanged=_=>notices++;
            hud.hud_bridge("{\"v\":4,\"kind\":\"prop-action-prepare\",\"request_id\":\"hud:prepare\"}");
            Is("HUD waits for outstanding write",hud.PendingPropPreparation is { IsCompleted:false }); prepareWrite.SetResult(); await hud.PendingPropPreparation!;
            hud.hud_bridge("{\"v\":4,\"kind\":\"prop-actions-changed\",\"request_id\":\"hud:prepare\"}"); Is("HUD correlates changed notification",notices==1);

            // Existing observer entry still uses public elapsed timing and measured fitting.
            var npcEntry=Read("worldmap_entry.json"); npcEntry["characters"]![1]!["prop_action_entry"]=npcEntry["characters"]![0]!["prop_action_entry"]!.DeepClone(); npcEntry["characters"]![0]!["prop_action_entry"]=null;
            var observer=mgr.Figures["fixture-npc"]; var lazy=InstallMeasuredRig(observer,deferred:true);
            mgr.ApplyPolled(JsonSerializer.SerializeToElement(npcEntry)); Step(0);
            Is("observer lazy measured entry requests fitting",observer.PropEntry?.Played==false && lazy.Requests()>0);
            lazy.Complete(); Step(0); Is("observer fits measured clip",observer.PropEntry?.Played==true); Near("observer public entry clock",observer.ClipTime,1); Near("observer public support lift",observer.PropEntryLift,.0645);
            var oldEntry=observer.PropEntry; npcEntry["characters"]![1]!["prop_action_entry"]!["elapsed_game_s"]=2.5;
            mgr.ApplyPolled(JsonSerializer.SerializeToElement(npcEntry)); Step(0); Is("observer elapsed poll retains identity",ReferenceEquals(oldEntry,observer.PropEntry)); Near("observer elapsed poll seeks clock",observer.ClipTime,1.25);
            return checks;
        } finally { offers?.Dispose(); position?.Dispose(); hud.Free(); builder.StopResidency(); builder.Models?.FreeAll(); world.QueueFree(); }
    }
    private static async Task<int> CheckUpperMotion(Node3D host,string fixtures)
    {
        var fixture=new FixtureSource(Path.Combine(fixtures,"propactions"),fixtures);
        var scene=JsonNode.Parse(File.ReadAllText(Path.Combine(fixture.Dir,"scene_loc-props.json")))!;
        scene["levels"]![0]!["level"]=1; scene["levels"]![0]!["floor_y"]=9.4;
        scene["rooms"]![0]!["level"]=1; scene["models"]![0]!["level"]=1; scene["models"]![0]!["bottom_y"]=9.4;
        scene["plates"]=new JsonArray(new JsonObject { ["level"]=1,["room_id"]="r-props",["outline"]=scene["rooms"]![0]!["outline"]!.DeepClone(),
            ["holes"]=new JsonArray(),["top_y"]=9.4,["thickness"]=.02,["opacity_role"]="upper" });
        scene["markers"]![0]!["y_world"]=9.927; scene["markers"]![0]!["floor_y"]=9.4;
        var source=new MenuSource(fixture) { SceneOverride=scene.AsObject() };
        var world=new Node3D(); host.AddChild(world); var builder=new WorldBuilder(source,_=>{},strict:true); int checks=0;
        void Near(string label,double actual,double expected) { checks++; if(Math.Abs(actual-expected)>.0002) throw new InvalidOperationException($"propactions upper {label}: {actual} expected {expected}"); }
        try {
            await builder.BuildAsync(world,"Fixture Prop Room"); builder.SetOpen("loc-props",true); builder.Slots["loc-props"].Fade.Snap(1); builder.SetLevel("loc-props",1);
            var mgr=new FigureManager(source,builder.Height!,_=>{},strict:true) { AutoTick=false,Slots=()=>builder.Slots,GroundYAt=builder.FigureGroundY }; world.AddChild(mgr);
            using var map=await source.GetWorldMapAsync(); await mgr.Apply(map.RootElement); var avatar=mgr.Figures["fixture-avatar"]; InstallMeasuredRig(avatar);
            foreach(bool explicitFloor in new[]{true,false}) {
                var plan=Motion("upper-world-"+explicitFloor); plan["floor_y"]=explicitFloor ? JsonValue.Create(9.4) : null;
                plan["access"]!["y"]=9.4; plan["anchor"]!["y"]=9.529;
                mgr.PlayOwnPropMotion(plan,"state"); mgr.Tick(.5); Near("room walking clearance "+explicitFloor,avatar.Position.Y,9.41);
                mgr.Tick(6.5); Near("entry root at upper access "+explicitFloor,avatar.Position.Y,9.4); Near("measured support on upper storey "+explicitFloor,avatar.PropEntryLift,.0645);
                mgr.Tick(1); Near("server anchor root on upper storey "+explicitFloor,avatar.Position.Y,9.529);
                mgr.ClearOwnPropMotion();
            }
            return checks;
        } finally { builder.StopResidency(); builder.Models?.FreeAll(); world.QueueFree(); }
    }
    private static int CheckMotionVectors(string fixtures)
    {
        var file=JsonNode.Parse(File.ReadAllText(Path.Combine(fixtures,"../../shared/test-vectors/prop_action_motion.json")))!;
        JsonNode? Resolve(JsonNode? node) {
            if(node is JsonObject obj && obj["$fixture"] is { } name) {
                var resolved=file["fixtures"]![name.GetValue<string>()]!.DeepClone();
                if(obj["$with"] is JsonObject changes) foreach(var pair in changes) resolved[pair.Key]=pair.Value?.DeepClone();
                return resolved;
            }
            return node?.DeepClone();
        }
        int checks=0;
        foreach(var row in file["cases"]!.AsArray().OfType<JsonObject>().Where(row=>row["fn"]!.GetValue<string>()=="sampleMotion")) {
            var args=row["args"]!.AsArray(); var actual=PropActionMotion.SampleMotion(Resolve(args[0])!,PropActionMotion.Number(args[1])); var expected=row["expect"]!;
            bool match=PropActionMotion.Text(actual["phase"])==PropActionMotion.Text(expected["phase"])
                && new[]{"x","y","z","yaw"}.All(key=>Math.Abs(PropActionMotion.Number(actual[key])-PropActionMotion.Number(expected[key]))<=1e-9);
            if(!match) throw new InvalidOperationException($"propactions shared vector {row["label"]}: {actual} expected {expected}");
            checks++;
        }
        if(checks<25) throw new InvalidOperationException("missing shared B1 motion vectors");
        return checks;
    }
}
