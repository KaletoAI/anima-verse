using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Embody;
using AnimaNative.Figures;
using AnimaNative.Scatter;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// Task 50 / E7-T5 P-cases: real fixture writes, targets, E6 routes and residency pins. A 100 Hz duration
/// clock reports at 330,660,…,1980 ms over 2 s; a stopped root drains once. Refusal (1,2)→(-3,2) walks
/// four metres; a ten metre foreign move holds its teleport owner until detail is ready, then snaps/flys.
/// </summary>
public static class EmbodyPositionCheck
{
    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        int n = 0;
        void Is(string label, bool value) { n++; if (!value) throw new InvalidOperationException("embody position " + label); }
        void Near(string label, double actual, double expected, double tolerance = .0002) => Is($"{label}: {actual:R} expected {expected:R}",Math.Abs(actual-expected)<=tolerance);
        static PositionAnswer Answer(string json, int status = 200)
        { using var doc = JsonDocument.Parse(json); return new(status,doc.RootElement.Clone()); }
        var source = new FixtureSource(Path.Combine(fixtures,"embody"),fixtures);
        var world = new Node3D { Name = "EmbodyPositionWorld" }; host.AddChild(world);
        var builder = new WorldBuilder(source,_=>{},strict:true);
        AvatarPositionController? controller = null;
        try
        {
            n += await PositionChannelCheck.RunAsync(source);
            await builder.BuildAsync(world,"Fixture Hall");
            var manager = new FigureManager(source,builder.Height!,_=>{},strict:true)
            { AutoTick=false,ClipFit=ClipFitMode.OnDemandSync,Slots=()=>builder.Slots, GroundMoveAt=builder.FigureGroundMove,GroundYAt=builder.FigureGroundY };
            world.AddChild(manager); await manager.InitAsync(); manager.SetProcess(false);
            using var map = await source.GetWorldMapAsync();
            await manager.Apply(map.RootElement); await manager.EnsurePool();
            var fig = manager.Figures[manager.AvatarName];
            var steering = new PlayerSteering(manager,builder); steering.SetActive(true);
            double now=0;
            var none=new HashSet<string>(); var d=new HashSet<string>{"d"};
            var sent=new List<PositionReport>();
            var channel=new PositionChannel((p,_)=>{sent.Add(p); return Task.FromResult(Answer("{\"ok\":true,\"room_id\":\"\"}"));},()=>now,"fixture-session-46");
            controller=new(manager,builder,steering,source,()=>now,channel);
            controller.SetActive(true);
            void Frame(IReadOnlySet<string> keys, double dt=.01)
            { now+=dt*1000; controller.BeforeSteering(); steering.Step(dt,keys,0); manager.Tick(dt); }
            void At(float x,float z) { steering.CancelRoute(); manager.SnapPlayerTo(fig.CharacterName,new(x,(float)builder.FigureGroundY(x,z),z)); }
            async Task Poll(Action<JsonNode> edit)
            {
                var node=JsonNode.Parse(map.RootElement.GetRawText())!; edit(node["characters"]![0]!);
                using var raw=JsonDocument.Parse(node.ToJsonString());
                using var doc=new MapReceipt(now,now,now).Attach(raw.RootElement); await manager.Apply(doc.RootElement);
            }
            At(-15,-10);
            // Establish the rendered starting point without reporting a manual test relocation.
            Frame(none,0);
            for(int i=0;i<200;i++) Frame(d);
            Is("P1 six moving reports",sent.Count==6);
            for(int i=0;i<6;i++) { Near("P1 cadence "+i,sent[i].t_ms,(i+1)*330); Is("P1 seq "+i,sent[i].seq==i+1); }
            for(int i=0;i<100;i++) Frame(none);
            Is("P1 one final report",sent.Count==7);
            Near("P1 final reports actual stop",sent[^1].x,Math.Floor(fig.Position.X*100+.5)/100);
            Is("P1 room answer clears previous room",steering.RoomId=="");
            for(int i=0;i<100;i++) Frame(none);
            Is("P1 standing stays quiet",sent.Count==7);
            controller.Dispose(); controller=null;

            // The answer table is strict, has no implicit mutation, and preserves the server's exact refusal.
            source.SelectPositionScenario("refusal-walk"); now=330;
            channel=new(source.ReportPositionAsync,()=>now,"fixture-session-46");
            controller=new(manager,builder,steering,source,()=>now,channel); controller.SetActive(true);
            var toasts=new List<string>(); controller.Toast=toasts.Add;
            At(1,2); channel.Tick(new(1,2),true);
            Is("P2 fixture 409 consumed",source.PositionRequests.Count==1);
            Is("P2 correction owns walking goal",steering.Correction is not null && fig.Position.X==1 && fig.Target.X == -3);
            Is("P2 server toast verbatim",toasts.Count==1 && toasts[0]=="Fixture wall refuses movement.");
            Frame(none); Is("P2 walks rather than snaps",fig.Position.X<1 && fig.Position.X>0);
            for(int i=0;i<150;i++) Frame(none);
            Near("P2 arrives home",fig.Position.X,-3,.2);
            Is("P2 disc blocks",!steering.OnGroundClick(new(1,2)));
            for(int i=0;i<260;i++) Frame(none);
            Is("P2 disc expires at four seconds",steering.OnGroundClick(new(1,2)));
            steering.CancelRoute();
            controller.Dispose(); controller=null;

            source.SelectPositionScenario("throttled-retry"); now=330;
            channel=new(source.ReportPositionAsync,()=>now,"fixture-session-46");
            channel.Tick(new(-3,0),true); Is("P3 throttle remains dirty",channel.Dirty);
            now=660; channel.Tick(new(-3,0),false);
            Is("P3 retry accepts and clears dirty",source.PositionRequests.Count==2 && !channel.Dirty); channel.Dispose();

            var undiscovered=JsonNode.Parse(map.RootElement.GetRawText())!;
            undiscovered["locations"]!.AsArray().Add(new JsonObject { ["id"]="unmounted",["pos_x"]=10000,["pos_z"]=0,["yaw_deg"]=90,
                ["boundary"]=new JsonArray(new JsonArray(-4,-2),new JsonArray(4,-2),new JsonArray(4,2),new JsonArray(-4,2)) });
            using(var remote=JsonDocument.Parse(undiscovered.ToJsonString()))
            {
                builder.SetStreamView(remote.RootElement,new[]{(0.0,0.0)});
                Is("payload-only rotated footprint holds readiness",builder.PlaceAt(10000,3)=="unmounted" && !builder.IsReady("unmounted"));
                Is("rotated footprint excludes outside point",builder.PlaceAt(10003,0) is null);
            }
            builder.SetStreamView(map.RootElement,new[]{(0.0,0.0)});

            // A 10 m foreign relocation lands inside loc-hall, whose mounted shell deliberately lacks readiness.
            now=10000; channel=new((p,_)=>Task.FromResult(Answer("{\"ok\":true}")),()=>now,"fixture-session-46");
            controller=new(manager,builder,steering,source,()=>now,channel); controller.SetActive(true);
            At(9990,0);
            undiscovered["characters"]![0]!["pos"]=new JsonObject{["x"]=10000,["z"]=0};
            using(var raw=JsonDocument.Parse(undiscovered.ToJsonString()))
            using(var stamped=new MapReceipt(now,now,now).Attach(raw.RootElement))
                manager.ApplyPolled(stamped.RootElement.Clone());
            Is("first-discovery teleport holds before residency receives poll",controller.PendingSnap?.Id=="unmounted" && fig.Position.X==9990);
            controller.SetActive(false); controller.SetActive(true);
            Is("cancelled teleport releases its pin",!builder.StreamPins.ContainsKey("teleport"));
            At(-13,1); var hall=builder.Slots["loc-hall"]; hall.Ready=false;
            builder.HoldPlayerApproach(-3,1);
            Is("approach owns its readiness pin",builder.StreamPins.GetValueOrDefault("approach")=="loc-hall");
            int fly=0; controller.FlyTo=_=>fly++;
            await Poll(row=>row["pos"]=new JsonObject{["x"]=-3,["z"]=1});
            Is("P4 nonready teleport holds",controller.PendingSnap is not null && steering.PendingSnap && fig.Position.X == -13);
            Is("P4 teleport owner pinned",builder.StreamPins.GetValueOrDefault("teleport")=="loc-hall");
            Is("P4 teleport clears previous approach owner",!builder.StreamPins.ContainsKey("approach"));
            builder.Pin("loc-hall","entry"); builder.Pin("loc-hall","approach");
            builder.Release("wrong-id","entry"); Is("entry release checks place",builder.StreamPins.ContainsKey("entry"));
            Frame(d); Near("P4 keys held",fig.Position.X,-13);
            hall.Ready=true; Frame(none);
            Near("P4 ready snaps",fig.Position.X,-3);
            Is("P4 flies once and releases own pin",fly==1 && !builder.StreamPins.ContainsKey("teleport") && builder.StreamPins.ContainsKey("entry"));
            builder.Release("loc-hall","entry"); builder.Release("loc-hall","approach");
            steering.Correction=null;
            now+=100;
            channel.Tick(new(-2.5,1),true);
            long echoSeq=channel.Seq;
            At(-13,1);
            await Poll(row=> {row["pos"]=new JsonObject{["x"]=-3,["z"]=1}; row["pos_origin"]=new JsonObject{["session"]=channel.Session,["seq"]=echoSeq};});
            Near("P5 own echo ignored",fig.Position.X,-13);
            Is("P5 own echo no correction",steering.Correction is null && controller.PendingSnap is null);

            // E6 journey adoption, input's reserved write, and a payload stamped with that seq acknowledge cancellation.
            now+=100; At(-3,1);
            JsonObject Journey(string id) => new() { ["journey_id"]=id,["waypoints"]=new JsonArray(new JsonArray(-3,1),new JsonArray(-3,-20)),["progress_m"]=0,["paces_m_s_real"]=new JsonArray(3.4),["starts_in_s"]=0 };
            await Poll(row=>row["travel"]=Journey("j50"));
            Is("P6 SERVER owns E6 route",channel.Driver.Kind==DriverKind.SERVER && manager.ServerDriven && fig.Route is not null);
            Frame(d);
            Is("P6 input CANCELLING",channel.Driver.Kind==DriverKind.CANCELLING && !manager.ServerDriven && fig.Route is null);
            long cancelSeq=channel.Seq;
            await Poll(row=>row["travel"]=Journey("j50")); manager.TickPlacement();
            Is("P6 old journey suppressed",channel.Driver.Kind==DriverKind.CANCELLING && fig.Route is null);
            await Poll(row=> {row["travel"]=Journey("j50"); row["pos_origin"]=new JsonObject{["session"]=channel.Session,["seq"]=cancelSeq};});
            Is("P6 acknowledgement PLAYER",channel.Driver.Kind==DriverKind.PLAYER && fig.Route is null);
            Is("P6 suppression survives ack",channel.Suppressed("j50"));
            await Poll(row=>row["travel"]=Journey("replacement"));
            Is("replacement journey adopted",channel.Driver.Kind==DriverKind.SERVER && fig.Route is not null);

            // A stale poll must not remove an E6 route or snap its root while a seat write is pending.
            controller.OwnSeatChangeAt=double.PositiveInfinity;
            var stalePosition=fig.Position;
            await Poll(row=>row["travel"]=null); manager.TickPlacement();
            Is("stale poll preserves server route",fig.Route is not null && fig.Position.DistanceTo(stalePosition)<.00001);
            controller.OwnSeatChangeAt=0;

            await Poll(row=> {row["travel"]=null; row["prop_action_entry"]=new JsonObject{["id"]="task57-hook"};});
            Is("Task57 prop entry is server driven",steering.PropActionDriven && manager.ServerDriven);
            var propPoint=fig.Position; long propSeq=channel.Seq; Frame(d);
            Is("Task57 prop entry has no local input/report",channel.Seq==propSeq && steering.Route is null);
            await Poll(row=> {row["travel"]=null; row["local_approach"]=new JsonObject{["room_id"]="r-a"};});
            Is("Task57 local approach is server driven",steering.PropActionDriven && manager.ServerDriven);
            Frame(d); Is("Task57 approach has no report",channel.Seq==propSeq);
            await Poll(row=>row["travel"]=null); steering.Correction=null;
            steering.MovementLocked=true; var locked=fig.Position; long before=channel.Seq;
            for(int i=0;i<50;i++) Frame(d);
            Is("party follower keys dead and no report",fig.Position.DistanceTo(locked)<.00001 && channel.Seq==before);
            steering.MovementLocked=false;
            fig.Pair=new PairPlay { Id="task50-pair", Clip="unloaded__a", Anchor=new(fig.Position.X,fig.Position.Z,0,null) };
            for(int i=0;i<50;i++) Frame(d);
            Is("pair interaction no report",channel.Seq==before);
            fig.Pair=null;
            steering.SetActive(false);
            return $"position={n} P1-P6=ok cadence=330ms final=1 refusal=walk/4s teleport=hold/snap echo=ignored driver=SERVER/CANCELLING/PLAYER";
        }
        finally
        {
            controller?.Dispose(); builder.StopResidency(); builder.Models?.FreeAll(); world.QueueFree();
            await host.ToSignal(host.GetTree(),SceneTree.SignalName.ProcessFrame);
            await host.ToSignal(host.GetTree(),SceneTree.SignalName.ProcessFrame);
        }
    }
}
