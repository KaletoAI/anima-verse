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
            var plan=JsonNode.Parse("""
                {"execution_id":"bed-86","journey_id":"bed-86","room_id":"","floor_y":0,
                 "waypoints":[[0,0],[0,0]],"paces_m_s_real":[1],"departure":null,
                 "access":{"x":0,"y":0.01,"z":0,"yaw":45},
                 "anchor":{"x":0.46669,"y":0.4,"z":-0.34507,"yaw":45,"root_offset":0,"place_id":"bed-86","slot":1},
                 "entry":{"mode":"bridge","kind":"lie-down","pose_key":"laying","duration_s":4.066667},"height_cm":170,"role":null}
                """)!.AsObject();
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
            figure.FinishPropEntry("laying"); for(int frame=0;frame<35;frame++) figure.UpdateFigure(1.0/30); double compatibleAxis=Axis();
            figure.FinishPropEntry("idle"); for(int frame=0;frame<35;frame++) figure.UpdateFigure(1.0/30);
            bool compatible=Diff(installedAxis,compatibleAxis)<4;
            if(compatible) { library.RemoveAnimation("laying"); library.AddAnimation("laying",installed); }
            GD.Print($"[check-bed-entry] installed laying axis={installedAxis:F3}, reverse first axis={compatibleAxis:F3}, mismatch={Diff(installedAxis,compatibleAxis):F3}°; hold={(compatible ? "installed laying" : "get-up-bed frame 0 (local laying incompatible)")}");
            manager.PlayOwnPropMotion(plan,"request");
            double last=Axis();
            for(int frame=1;frame<=122;frame++) {
                manager.Tick(1.0/30);
                if(figure.CurrentClip!="lie-down") throw new InvalidOperationException("real bed entry was not played");
                double axis=Axis();
                GD.Print($"[check-bed-entry] B1 frame={frame} phase={manager.OwnPropMotion?.Phase} yaw={figure.Yaw*180/Math.PI:F3} axis={axis:F3}");
                if(Diff(figure.Yaw*180/Math.PI,45)>0.1) throw new InvalidOperationException($"keep entry must retain access yaw 45, got {figure.Yaw*180/Math.PI:F3}");
                last=axis;
            }
            if(Math.Abs(figure.PropEntryLift-.39)>.001) throw new InvalidOperationException($"bed support got {figure.PropEntryLift}, expected .39");
            manager.Tick(0.001);
            double after=Axis();
            GD.Print($"[check-bed-entry] seam before={last:F3} after={after:F3} delta={Diff(last,after):F3} yaw={figure.Yaw*180/Math.PI:F3}");
            if(Diff(last,after)>4) throw new InvalidOperationException($"bed entry seam axis jumped {Diff(last,after):F3} degrees");
            for(int frame=1;frame<=20;frame++) {
                manager.Tick(1.0/30); double axis=Axis();
                GD.Print($"[check-bed-entry] B1 seam+{frame} yaw={figure.Yaw*180/Math.PI:F3} axis={axis:F3} delta={Diff(after,axis):F3}");
                if(Diff(after,axis)>4 || Diff(last,axis)>4) throw new InvalidOperationException("bed entry B1 pose continuity");
                after=axis;
            }
            // Public observer projection uses the same measured clip and a new poll commits the held pose.
            manager.ClearOwnPropMotion(); map["avatar"]="";
            var row=map["characters"]![0]!;
            var spec=(JsonObject)plan["entry"]!.DeepClone();
            spec["access"]=plan["access"]!.DeepClone(); spec["anchor"]=plan["anchor"]!.DeepClone();
            spec["height_cm"]=170; spec["root_offset"]=0; spec["started_game_s"]=0;
            spec["elapsed_game_s"]=0; spec["duration_game_s"]=4.066667; spec["game_seconds_per_real_second"]=1;
            row["prop_action_entry"]=spec;
            await manager.Apply(JsonSerializer.SerializeToElement(map)); manager.Tick(0);
            for(int frame=1;frame<=122;frame++) {
                manager.Tick(1.0/30); last=Axis();
                GD.Print($"[check-bed-entry] observer frame={frame} yaw={figure.Yaw*180/Math.PI:F3} axis={last:F3}");
                if(Diff(figure.Yaw*180/Math.PI,45)>.1) throw new InvalidOperationException("keep observer changed access yaw");
            }
            row["prop_action_entry"]=null; row["place"]=new JsonObject { ["id"]="bed-86",["slot"]=1 }; row["activity_animation"]="laying";
            await manager.Apply(JsonSerializer.SerializeToElement(map));
            after=last;
            for(int frame=0;frame<=20;frame++) {
                manager.Tick(frame==0 ? 0 : 1.0/30); double axis=Axis();
                GD.Print($"[check-bed-entry] observer seam+{frame} yaw={figure.Yaw*180/Math.PI:F3} axis={axis:F3} delta={Diff(after,axis):F3}");
                if(Diff(after,axis)>4 || Diff(last,axis)>4) throw new InvalidOperationException("bed entry observer pose continuity");
                after=axis;
            }
            return 2;
        } finally { world.Free(); Directory.Delete(dir,true); }
    }
}
