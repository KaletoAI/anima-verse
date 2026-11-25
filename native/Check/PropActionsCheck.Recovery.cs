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
    /// <summary>
    /// The server's order of an own run (wire form of app/core/motion_orders.py): bench-56 slot (2, 0.129, 0), access (2, −1);
    /// its seq lies above every fixture map's <c>order_seq</c>, so a row without order does not end it.
    /// </summary>
    private static JsonObject OwnOrder(string id,double issued,int revision=1,string status="approaching")=>JsonNode.Parse($$"""
        {"order_id":"{{id}}","revision":{{revision}},"seq":{{1000+revision}},"kind":"prop_action","issued_motion_s":{{issued}},
         "eta_motion_s":{{issued+3.642157}},"flip_motion_s":{{issued+5.642157}},"deadline_motion_s":{{issued+60}},
         "status":"{{status}}","awaits":"","gait":"walk","speed_m_s":1.4,
         "target":{"location_id":"loc-props","room_id":"r-props","level":0,"floor_y":0,"placement_id":"bench-56","slot":0,"execution_id":"{{id}}"},
         "hint_route":[],"snap":false,
         "actors":[{"name":"fixture-avatar","role":"actor","clip_role":"","height_cm":170,
                    "start":{"x":-3,"y":0,"z":-2,"yaw":0,"room_id":"r-props","level":0},
                    "access":{"x":2,"y":0,"z":-1,"yaw":180},"anchor":{"x":2,"y":0.129,"z":0,"yaw":180,"root_offset":0.398},
                    "entry_mode":"bridge",
                    "sequence":[{"step":"walk","pose_kind":"","pose_key":"","nominal_s":0},
                                {"step":"entry","pose_kind":"seat","pose_key":"sitting","nominal_s":2},
                                {"step":"loop","pose_kind":"seat","pose_key":"sitting","nominal_s":0}],
                    "reports_arrival":true}]}
        """)!.AsObject();
    private static JsonObject RunState(string id,string status="approaching")=>new() {
        ["current"]=new JsonArray(new JsonObject { ["execution_id"]=id,["status"]=status }),["outgoing"]=new JsonArray() };
    /// <summary>
    /// Plan E3 Task 6: the own run on orders (fixtures/propactions/README.md numbers): the click walks a local order, the
    /// answer's order adopts it without a restart, a poll never moves the avatar, the revision <c>entering</c> plays the
    /// entry onto the slot; the run's end hands the avatar back (at the latest after the hold); in-place switches,
    /// detached HUD answers and a pair stop keep their Task 57 contracts; the shared B1 vectors stay checked.
    /// </summary>
    private static async Task<int> CheckOwnOrders(Node3D host,string fixtures)
    {
        int checks=CheckMotionVectors(fixtures);
        void Is(string label,bool ok) { checks++; if(!ok) throw new InvalidOperationException("propactions own order "+label); }
        void Near(string label,double actual,double expected,double eps=.05)=>Is($"{label}: got={actual:R} expected={expected:R}",Math.Abs(actual-expected)<=eps);
        JsonObject Read(string file)=>JsonNode.Parse(File.ReadAllText(Path.Combine(fixtures,"propactions",file)))!.AsObject();
        var fixture=new FixtureSource(Path.Combine(fixtures,"propactions"),fixtures);
        var source=new MenuSource(fixture) { CancelKeepsWorld=true }; var world=new Node3D(); host.AddChild(world);
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
            foreach(var row in source.Offers) { row!["enabled"]=true; row["reason"]=""; }
            const double Dt=1.0/60;
            void Step(double seconds) { for(double t=0;t<seconds-1e-9;t+=Dt) { now+=Dt*1000; mgr.Tick(Dt); offers.Tick(); } }
            var action=source.Offers[0]!;
            void Click()=>hud.Handlers["pickPropAction"](new JsonArray(action["action_id"]!.DeepClone(),action["target"]!.DeepClone(),action["definition_revision"]!.DeepClone()));
            async Task End(string id,string status="cancelled") {
                source.StateOverride=new JsonObject { ["current"]=new JsonArray(),["outgoing"]=new JsonArray(),["recent_results"]=new JsonArray(new JsonObject { ["execution_id"]=id,["status"]=status }) };
                await offers.PropActions!.RefreshAsync();
            }
            bool HandedBack()=>!mgr.HasLiveOrder(mgr.AvatarName) && !mgr.ServerDriven && !steering.PropActionDriven;

            // ---- the click walks at once; the answer's order takes over without a restart ----
            var held=new TaskCompletionSource<JsonDocument>(); source.OnRequest=_=>held.Task;
            Click(); Step(.25);
            // 0.25 s × 1.4 m/s = 0.35 m along (5, 1)/√26 from (−3, −2) → (−2.656796, −1.931359).
            Near("local order walks before any answer x",avatar.Position.X,-2.656796); Near("local order walks before any answer z",avatar.Position.Z,-1.931359);
            Is("the order blocks steering and position writes",steering.PropActionDriven && !position.Channel.CanReport());
            var player=mgr.OrderPlayerOf(mgr.AvatarName)!; double issued=player.IssuedLocal;
            source.StateOverride=RunState("run-x");
            held.SetResult(JsonDocument.Parse(new JsonObject { ["execution_id"]="run-x",["status"]="approaching",["order"]=OwnOrder("run-x",mgr.MotionNow) }.ToJsonString()));
            await offers.PendingPropAction!;
            Is($"the answer's order adopts the local one (id={player.Current?.Id})",player.Current?.Id=="run-x" && player.IssuedLocal==issued);
            var shown=avatar.Position;
            var approach=Read("worldmap_approach.json"); approach["characters"]![0]!["travel"]!["progress_m"]=5.8;
            mgr.ApplyPolled(JsonSerializer.SerializeToElement(approach));
            Near("a journey poll cannot move the avatar",avatar.Position.X,shown.X,1e-5);
            await offers.PropActions!.RefreshAsync();
            Is("a repeated state keeps the order",player.Current?.Id=="run-x" && player.IssuedLocal==issued);
            Step(4);
            // √26 / 1.4 = 3.642 s to the access; the journey server's order waits there for "entering".
            Near("waits at the access x",avatar.Position.X,2); Near("waits at the access z",avatar.Position.Z,-1);
            Is($"held at the access for the arrival (state={player.RunState})",player.RunState==AnimaNative.Orders.OrderState.WaitAccess);
            mgr.AdoptOrders(new[]{ AnimaNative.Orders.OrderParse.From(JsonSerializer.SerializeToElement(OwnOrder("run-x",mgr.MotionNow-4.25,2,"entering")))! },mgr.MotionNow);
            Step(.1); Is($"the revision entering starts the entry (state={player.RunState})",player.RunState==AnimaNative.Orders.OrderState.Entry);
            Step(2.5);
            Is($"the loop on the slot (state={player.RunState})",player.RunState==AnimaNative.Orders.OrderState.Loop);
            Near("on the slot x",avatar.Position.X,2); Near("on the slot z",avatar.Position.Z,0); Near("on the slot y",avatar.Position.Y,.129);
            var active=Read("worldmap_active.json"); active["characters"]![0]!["pos"]!["x"]=99;
            mgr.ApplyPolled(JsonSerializer.SerializeToElement(active)); Step(Dt);
            Near("a seated poll cannot move the avatar",avatar.Position.X,2);
            // The run ends: the order's loop is let go at the latest after the hold (3 s).
            await End("run-x"); Step(1);
            Is("the run's end waits for the order's exit",mgr.ServerDriven && steering.PropActionDriven);
            Step(2.1);
            Is("the run's end hands back after the hold",HandedBack());

            // ---- a detached HUD answer carries its order: the avatar plays it at once ----
            source.StateOverride=RunState("run-h");
            hud.hud_bridge(new JsonObject { ["v"]=4,["kind"]="prop-actions-changed",["request_id"]="hud:83",["source"]="request",
                ["result"]=new JsonObject { ["execution_id"]="run-h",["status"]="approaching",["order"]=OwnOrder("run-h",mgr.MotionNow) } }.ToJsonString());
            await offers.PendingPropAction!; Step(.25);
            Is($"the HUD answer's order plays (id={mgr.OrderPlayerOf(mgr.AvatarName)?.Current?.Id})",mgr.OrderPlayerOf(mgr.AvatarName)?.Current?.Id=="run-h" && mgr.ServerDriven);
            await End("run-h"); Step(3.1); Is("the HUD run's end hands back",HandedBack());

            // ---- another action on the same piece switches IN PLACE: no hand-back between the runs ----
            source.StateOverride=RunState("switch-old","active"); await offers.PropActions!.RefreshAsync();
            source.StateOverride=new JsonObject { ["current"]=new JsonArray(new JsonObject { ["execution_id"]="switch-new",["status"]="active" }),["outgoing"]=new JsonArray(),
                ["recent_results"]=new JsonArray(new JsonObject { ["execution_id"]="switch-old",["status"]="completed",["reason"]="ended" }) };
            await offers.PropActions!.RefreshAsync(); Step(.1);
            Is("the switch keeps the avatar the server's",mgr.ServerDriven && steering.PropActionDriven && !position.Channel.CanReport());
            Is("the switch tracks the new run",offers.PropActions!.OwnExecutionId=="switch-new");
            await End("switch-new","completed"); Step(Dt);
            Is("the new run's end hands back",HandedBack());

            // ---- a refusal while nothing runs: stand, hand back ----
            source.OnRequest=_=>Task.FromResult(JsonDocument.Parse("{\"execution_id\":\"\",\"status\":\"refused\",\"reason\":\"claimed\"}"));
            Click(); await offers.PendingPropAction!; Step(.1);
            Is("a refusal hands back",HandedBack());
            source.OnRequest=null;

            // The pair is stopped on the server (HUD pair stop: POST /play/interact/end) while the own run still plays it:
            // the worldmap poll drops the interaction from both rows, the run's end comes with the prop-actions state. Both
            // halves hold until then and end in ONE frame (fails on 39f31bea: the NPC let go at the worldmap poll, the
            // avatar a state poll later). Afterwards nothing is left over: the next action walks at once.
            foreach(bool answered in new[]{true,false}) {
                string tag=answered ? "state" : "timeout", pairId="pair-stop-"+tag;
                                var npcFigure=mgr.Figures["fixture-npc"];
                JsonNode Half(string role)=>JsonNode.Parse("{\"id\":\""+pairId+"\",\"kind\":\"pair-pose\",\"role\":\""+role
                    +"\",\"members\":{\"a\":\"fixture-npc\",\"b\":\"fixture-avatar\"},\"anchor\":{\"x\":2,\"z\":0,\"yaw\":0,\"place_id\":\"prop-bench-56-seat56\"},\"elapsed_s\":0,\"clip_duration_s\":1,\"loop\":true,\"rate\":1}")!;
                var both=Read("worldmap_active.json"); both["characters"]![0]!["place"]!["slot"]=1;
                both["characters"]![0]!["interaction"]=Half("b");
                both["characters"]!.AsArray().First(c=>c!["name"]!.GetValue<string>()=="fixture-npc")!["interaction"]=Half("a");
                source.MapOverride=both; mgr.ApplyPolled(JsonSerializer.SerializeToElement(both));
                source.StateOverride=RunState(pairId,"active"); await offers.PropActions!.RefreshAsync(); mgr.ApplyPolled(JsonSerializer.SerializeToElement(both)); Step(.1);
                Is($"pair stop: both halves run {tag} (npc={npcFigure.Pair?.Id ?? "none"} avatar={avatar.Pair?.Id ?? "none"})",avatar.Pair?.Id==pairId && npcFigure.Pair?.Id==pairId);
                int asked=0; void Ask()=>asked++; mgr.OwnPairEnding+=Ask;
                var ended=both.DeepClone().AsObject();
                foreach(var c in ended["characters"]!.AsArray()) { c!["interaction"]=null; c["place"]=null; }
                source.MapOverride=ended; mgr.ApplyPolled(JsonSerializer.SerializeToElement(ended)); Step(.1);
                mgr.OwnPairEnding-=Ask;
                Is($"pair stop: the NPC half waits for the avatar's end {tag} (npc={npcFigure.Pair?.Id ?? "none"} avatar={avatar.Pair?.Id ?? "none"})",
                    npcFigure.Pair?.Id==pairId && avatar.Pair?.Id==pairId);
                Is("pair stop: the state is asked for at once "+tag,asked==1);
                if(answered) {
                    source.MapOverride=Read("worldmap_cancelled.json"); await End(pairId); offers.Tick();
                    Is($"pair stop: both halves end in one frame (npc={npcFigure.Pair?.Id ?? "none"} avatar={avatar.Pair?.Id ?? "none"})",npcFigure.Pair is null && avatar.Pair is null);
                } else {
                    Step(FigureManager.OwnPairEndHoldS);
                    Is("pair stop: an end that never comes lets both go",npcFigure.Pair is null && avatar.Pair is null);
                    source.MapOverride=Read("worldmap_cancelled.json"); await End(pairId); offers.Tick();
                }
                Step(Dt);
                Is("pair stop hands back "+tag,HandedBack());
            }
            var prepareWrite=new TaskCompletionSource(); int notices=0; hud.PropActionPrepare=_=>prepareWrite.Task; hud.PropActionsChanged=_=>notices++;
            hud.hud_bridge("{\"v\":4,\"kind\":\"prop-action-prepare\",\"request_id\":\"hud:prepare\"}");
            Is("HUD waits for outstanding write",hud.PendingPropPreparation is { IsCompleted:false }); prepareWrite.SetResult(); await hud.PendingPropPreparation!;
            hud.hud_bridge("{\"v\":4,\"kind\":\"prop-actions-changed\",\"request_id\":\"hud:prepare\"}"); Is("HUD correlates changed notification",notices==1);

            // The observed NPC on its seat in a furniture pair.
            var observer=mgr.Figures["fixture-npc"]; InstallMeasuredRig(observer);
            // The entry ends in a furniture PAIR: the row holds the prop seat AND the interaction, its activity is the bare
            // pair kind "pair-pose" (no rig binds it). The NPC plays its half pair-pose__b at the anchor — the held-pose
            // commit must not stay pending on the bare kind (fails on 781bd9c1: the figure kept its entry clip).
            observer.Player!.GetAnimationLibrary("").AddAnimation("pair-pose__b",new Animation { Length=1,LoopMode=Animation.LoopModeEnum.Linear });
            mgr.Clips.Index.PairRoots["pair-pose__b"]=new(){[""]=new PairRoot(new RootPath(new float[]{0},new float[]{0,0}),PairScale.Origin)};
            var paired=Read("worldmap_entry.json"); foreach(var c in paired["characters"]!.AsArray()) c!.AsObject().Remove("prop_action_entry"); var npcRow=paired["characters"]![1]!;
            npcRow["activity_animation"]="pair-pose";
            npcRow["place"]=JsonNode.Parse("""{"id":"prop-bench-56-seat56","slot":1,"x":2,"z":0,"facing":180,"room_id":"r-props"}""");
            npcRow["interaction"]=JsonNode.Parse("""{"id":"npc-pair","kind":"pair-pose","role":"b","members":{"a":"fixture-avatar","b":"fixture-npc"},"anchor":{"x":2,"z":0,"yaw":0,"place_id":"prop-bench-56-seat56"},"elapsed_s":0,"clip_duration_s":1,"loop":true,"rate":1}""");
            mgr.ApplyPolled(JsonSerializer.SerializeToElement(paired)); Step(.1);
            Is($"NPC partner holds its pair (pending={observer.PropCommitPending})",!observer.PropCommitPending && observer.Pair is not null);
            Is($"NPC partner plays its pair half (clip={observer.CurrentClip})",observer.CurrentClip=="pair-pose__b");
            // ...without the entry's support lift: the entry at phase 1 lifts the body by the whole rise from the access
            // floor to the anchor root (0.129 here) — on top of a root that already stands on the anchor (fails on
            // 39f31bea: the bare pair kind could not be committed, so the lift stayed; Kira sat a bed height too high).
            Near("NPC partner's half carries no entry lift",observer.PropEntryLift,0);
            Step(.4);   // past the 0.4 s pair blend from where the entry left the figure
            Near("NPC partner stands at the pair anchor x",observer.Position.X,2); Near("NPC partner stands at the pair anchor z",observer.Position.Z,0);
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
            // An NPC getting up from a seat on this storey for an approach: its exact local route is withheld while the
            // seat leg runs (the leg starts inside the furniture), so the row's travel route places it — on the journey's
            // floor, not on the ground under the building (fails on 39f31bea: the figure fell to storey 0 until it walked).
            var npc=mgr.Figures["fixture-npc"];
            var rows=JsonNode.Parse(map.RootElement.GetRawText())!.AsObject();
            var npcRow=rows["characters"]!.AsArray().First(c=>c!["name"]!.GetValue<string>()=="fixture-npc")!;
            npcRow["travel"]=JsonNode.Parse("""{"target_id":"","journey_id":null,"waypoints":[[4,2],[4,1],[2,1]],"progress_m":0,"total_m":3,"floor_y":9.4,"starts_in_s":100,"paces_m_s_real":null}""");
            mgr.ApplyPolled(JsonSerializer.SerializeToElement(rows));
            for(int i=0;i<20;i++) mgr.Tick(.25);
            Near("NPC travel route stands on the journey's floor",npc.Position.Y,9.41);
            Near("NPC travel route holds its start before it walks",npc.Position.X,4);
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
