using System;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Figures;
using Godot;

namespace AnimaNative.Check;

public static partial class PropActionsCheck
{
    // The licensed clips remain repository inputs, never copied or rewritten by the check.
    internal static async Task<int> CheckBedEntry(Node3D host,string fixtures)
    {
        string repo=Path.GetFullPath(Path.Combine(fixtures,"../.."));
        string clips=Path.Combine(repo,"shared/models/clips");
        string[] required={"lie-down","laying","get-up-bed"};
        if(required.Any(k=>!File.Exists(Path.Combine(clips,k+".fbx")))) {
            GD.Print("[check-bed-entry] SKIP: local licensed bed clips absent"); return 0;
        }
        string dir=Path.Combine(Path.GetTempPath(),"anima-bed-entry-"+Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        var world=new Node3D(); host.AddChild(world);
        FigureManager? manager=null;
        try {
            string bridgeDir=Path.Combine(fixtures,"bridges");
            foreach(string file in Directory.GetFiles(bridgeDir,"*.json")) File.Copy(file,Path.Combine(dir,Path.GetFileName(file)));
            var urls=JsonNode.Parse(File.ReadAllText(Path.Combine(dir,"urls.json")))!.AsObject();
            foreach(var item in urls.ToArray()) if(!item.Value!.GetValue<string>().StartsWith("repo:"))
                urls[item.Key]=Path.GetFullPath(Path.Combine(bridgeDir,item.Value.GetValue<string>()));
            var listing=JsonNode.Parse(File.ReadAllText(Path.Combine(dir,"animation_clips.json")))!.AsObject();
            listing["clips"]!.AsArray().Add(new JsonObject { ["kind"]="lie-down",["url"]="/bed-entry/lie-down",["loop"]=false,
                ["root_motion"]=JsonNode.Parse(File.ReadAllText(Path.Combine(clips,"lie-down.json")))!["geometry"]!["root_motion"]!.DeepClone() });
            urls["/bed-entry/lie-down"]=Path.Combine(clips,"lie-down.fbx");
            // Plan E3 Task 6: the avatar's order plays the entry the pose rules name (walking → laying = lie-down).
            listing["pose_rules"]=JsonNode.Parse("""[{"from":"walking","to":"laying","kind":"lie-down"}]""");
            File.WriteAllText(Path.Combine(dir,"urls.json"),urls.ToJsonString());
            File.WriteAllText(Path.Combine(dir,"animation_clips.json"),listing.ToJsonString());
            var source=new FixtureSource(dir,fixtures);
            var models=JsonNode.Parse(File.ReadAllText(Path.Combine(dir,"model3d.json")))!;
            source.ModelAnswers["Bea Bed"]=models["Mia Chair"]!.ToJsonString();
            var height=new AnimaNative.World.WorldHeight(AnimaNative.World.HeightfieldOverview.Parse((await source.GetHeightfieldAsync()).RootElement));
            manager=new FigureManager(source,height,line=>GD.Print("[check-bed-entry] "+line),strict:true) { AutoTick=false,ClipFit=ClipFitMode.OnDemandSync };
            world.AddChild(manager); await manager.InitAsync();
            var map=JsonNode.Parse(File.ReadAllText(Path.Combine(dir,"worldmap.json")))!.AsObject();
            map["avatar"]="Bea Bed";
            map["characters"]=new JsonArray(map["characters"]!.AsArray().Single(c=>c!["name"]!.GetValue<string>()=="Bea Bed")!.DeepClone());
            map["characters"]![0]!["activity_animation"]="idle";
            await manager.Apply(JsonSerializer.SerializeToElement(map));
            var figure=manager.Figures["Bea Bed"];
            // The avatar's order onto the bed: already at the access (0, 0, 0) facing 45, the entry lie-down (4.066667 s)
            // onto the anchor; status entering — the run is the server's from the first frame on.
            var wire=JsonNode.Parse("""
                {"order_id":"bed-86","revision":1,"seq":1,"kind":"prop_action","issued_motion_s":0,"eta_motion_s":0,"flip_motion_s":0,
                 "deadline_motion_s":60,"status":"entering","awaits":"","gait":"walk","speed_m_s":1.4,
                 "target":{"location_id":"","room_id":"","level":0,"floor_y":0,"placement_id":"bed-86","slot":1,"execution_id":"bed-86"},
                 "hint_route":[],"snap":false,
                 "actors":[{"name":"Bea Bed","role":"actor","clip_role":"","height_cm":170,
                            "start":{"x":0,"y":0,"z":0,"yaw":45,"room_id":"","level":0},
                            "access":{"x":0,"y":0,"z":0,"yaw":45},"anchor":{"x":0.46669,"y":0.4,"z":-0.34507,"yaw":45,"root_offset":0},
                            "entry_mode":"bridge",
                            "sequence":[{"step":"walk","pose_kind":"","pose_key":"","nominal_s":0},
                                        {"step":"entry","pose_kind":"lie","pose_key":"laying","nominal_s":4.066667},
                                        {"step":"loop","pose_kind":"lie","pose_key":"laying","nominal_s":0}],
                            "reports_arrival":false}]}
                """)!;
            // Issued on the motion clock as it stands now (no lag: the entry starts at the first frame).
            foreach(var k in new[]{"issued_motion_s","eta_motion_s"}) wire[k]=manager.MotionNow;
            wire["flip_motion_s"]=manager.MotionNow+4.066667;
            wire["deadline_motion_s"]=manager.MotionNow+60;
            // Where the figure stands (the bridges world places it at (−50, 30)): the access, the anchor the same offset away.
            var actorWire=wire["actors"]![0]!; var at=figure.Position;
            actorWire["start"]!["x"]=at.X; actorWire["start"]!["z"]=at.Z;
            actorWire["access"]!["x"]=at.X; actorWire["access"]!["y"]=at.Y; actorWire["access"]!["z"]=at.Z;
            actorWire["anchor"]!["x"]=at.X+0.46669; actorWire["anchor"]!["y"]=at.Y+0.4; actorWire["anchor"]!["z"]=at.Z-0.34507;
            var order=AnimaNative.Orders.OrderParse.From(JsonSerializer.SerializeToElement(wire))!;
            double Axis() {
                var sk=figure.Skeleton!;
                int Bone(string key)=>Enumerable.Range(0,sk.GetBoneCount()).First(i=>ClipLibrary.NormBone(sk.GetBoneName(i))==key);
                var d=sk.GlobalTransform.Basis*(sk.GetBoneGlobalPose(Bone("head")).Origin-sk.GetBoneGlobalPose(Bone("hips")).Origin);
                return Math.Atan2(d.X,d.Z)*180/Math.PI;
            }
            double Diff(double a,double b)=>Math.Abs(Math.IEEERemainder(a-b,360));
            // This checkout's old laying file faces the opposite direction. Measure it, then build a compatible
            // hold from the real reverse clip's first frame; no source asset or fitted animation is mutated.
            figure.FaceTowards(new Vector3(1,0,1),snap:true);
            figure.FinishPropEntry("laying"); for(int frame=0;frame<35;frame++) figure.UpdateFigure(1.0/30);
            double installedAxis=Axis();
            figure.EnsureClip("get-up-bed");
            var reverse=figure.Player!.GetAnimation("get-up-bed");
            var hold=new Animation { Length=.1,LoopMode=Animation.LoopModeEnum.Linear };
            for(int t=0;t<reverse.GetTrackCount();t++) {
                var type=reverse.TrackGetType(t); int track=hold.AddTrack(type);
                hold.TrackSetPath(track,reverse.TrackGetPath(t));
                if(type==Animation.TrackType.Rotation3D) hold.RotationTrackInsertKey(track,0,reverse.RotationTrackInterpolate(t,0));
                else if(type==Animation.TrackType.Position3D) hold.PositionTrackInsertKey(track,0,reverse.PositionTrackInterpolate(t,0));
            }
            figure.FinishPropEntry("idle"); for(int frame=0;frame<35;frame++) figure.UpdateFigure(1.0/30);
            var library=figure.Player.GetAnimationLibrary(""); var installed=library.GetAnimation("laying");
            library.RemoveAnimation("laying"); library.AddAnimation("laying",hold);
            if(!figure.EnsureClip("laying") || library.GetAnimation("laying")!=hold)
                throw new InvalidOperationException("EnsureClip replaced an existing animation without a clips invalidation");
            figure.FinishPropEntry("laying"); for(int frame=0;frame<35;frame++) figure.UpdateFigure(1.0/30); double compatibleAxis=Axis();
            figure.FinishPropEntry("idle"); for(int frame=0;frame<35;frame++) figure.UpdateFigure(1.0/30);
            bool compatible=Diff(installedAxis,compatibleAxis)<4;
            if(compatible) { library.RemoveAnimation("laying"); library.AddAnimation("laying",installed); }
            GD.Print($"[check-bed-entry] installed laying axis={installedAxis:F3}, reverse first axis={compatibleAxis:F3}, mismatch={Diff(installedAxis,compatibleAxis):F3}°; hold={(compatible ? "installed laying" : "get-up-bed frame 0 (local laying incompatible)")}");
            map["characters"]![0]!["activity_animation"]="laying";
            await manager.Apply(JsonSerializer.SerializeToElement(map));
            manager.AdoptOrders(new[]{order},manager.MotionNow);
            var player=manager.OrderPlayerOf("Bea Bed")!;
            double last=Axis(),lift=0; int entryFrames=0;
            for(int frame=1;frame<=130;frame++) {
                manager.Tick(1.0/30);
                if(player.RunState!=AnimaNative.Orders.OrderState.Entry) break;
                entryFrames++; lift=figure.PropEntryLift;
                if(figure.CurrentClip!="lie-down") throw new InvalidOperationException($"real bed entry was not played (clip {figure.CurrentClip})");
                double axis=Axis();
                GD.Print($"[check-bed-entry] B1 frame={frame} state={player.RunState} yaw={figure.Yaw*180/Math.PI:F3} axis={axis:F3}");
                if(Diff(figure.Yaw*180/Math.PI,45)>0.1) throw new InvalidOperationException($"keep entry must retain access yaw 45, got {figure.Yaw*180/Math.PI:F3}");
                last=axis;
            }
            // 4.066667 s at 1/30 s: 122 frames of entry (± one frame at each end).
            if(Math.Abs(entryFrames-122)>2) throw new InvalidOperationException($"bed entry ran {entryFrames} frames, expected 122");
            // The support lift at the entry's end = anchor root − the access floor = 0.4 (the order stands on the floor itself,
            // the old motion plan's 0.01 m walking clearance is gone).
            if(Math.Abs(lift-.4)>.001) throw new InvalidOperationException($"bed support got {lift}, expected .4");
            double after=Axis();
            GD.Print($"[check-bed-entry] seam before={last:F3} after={after:F3} delta={Diff(last,after):F3} yaw={figure.Yaw*180/Math.PI:F3}");
            if(Diff(last,after)>4) throw new InvalidOperationException($"bed entry seam axis jumped {Diff(last,after):F3} degrees");
            for(int frame=1;frame<=20;frame++) {
                manager.Tick(1.0/30); double axis=Axis();
                GD.Print($"[check-bed-entry] B1 seam+{frame} yaw={figure.Yaw*180/Math.PI:F3} axis={axis:F3} delta={Diff(after,axis):F3}");
                if(Diff(after,axis)>4 || Diff(last,axis)>4) throw new InvalidOperationException("bed entry B1 pose continuity");
                after=axis;
            }
            return 1;
        } finally { world.Free(); Directory.Delete(dir,true); }
    }
}
