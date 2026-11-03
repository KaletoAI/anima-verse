using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Props;
using Godot;

namespace AnimaNative.Figures;

/// <summary>The private answer owns the root and clip clock until release; polls only confirm lifecycle.</summary>
public sealed class OwnPropPlayback(JsonObject plan,string key,double startedAt,double startY,double startYaw,bool cancel)
{
    public JsonObject Plan=plan;
    public string Key=key,Phase="",PoseKey="";
    public double StartedAt=startedAt,StartY=startY,StartYaw=startYaw;
    public bool Cancel=cancel,AccessLogged,AnchorLogged,FinaleOn;
    public JsonObject? HeldSample;
    public double? HeldEntryPhase;
}

public partial class FigureManager
{
    private readonly HashSet<string> _releasedOwnPropPairs=new(StringComparer.Ordinal);
    private readonly HashSet<string> _ownMotionKeys=new(StringComparer.Ordinal);
    public OwnPropPlayback? OwnPropMotion { get; private set; }
    public event Action? OwnPropMotionReleased;
    /// <summary>Whether the avatar's own furniture run is still live as far as the client knows (the controller's state).</summary>
    public Func<bool>? OwnPropRunLive { get; set; }
    /// <summary>The own pair's interaction left the rows before the run's end reached the client: ask for the state now.</summary>
    public event Action? OwnPairEnding;
    /// <summary>How long a vanished own pair is held for the run's end before both halves let go anyway (real seconds).</summary>
    public const double OwnPairEndHoldS=3;
    private string _endingOwnPair="";
    private double _endingOwnPairAt;
    /// <summary>
    /// A pair the avatar plays in its own furniture run ended on the server (the HUD pair stop, a partner who left): the
    /// worldmap poll drops the interaction from BOTH rows at once, but the avatar ends with its run — the stand-up
    /// comes with the prop-actions state, read on its own clock. The NPC used to stop at the worldmap poll and the
    /// avatar a poll later. Both halves keep playing until the own run's end lets the avatar go
    /// (<see cref="WithdrawOwnPropInteraction"/>) — the same frame — or <see cref="OwnPairEndHoldS"/> passed.
    /// </summary>
    private bool OwnPairEndingHeld(string pairId)
    {
        if(_endingOwnPair==pairId) return true;
        if(!_figures.TryGetValue(AvatarName,out var avatar) || avatar.Pair?.Id!=pairId || _releasedOwnPropPairs.Contains(pairId)) return false;
        if(!(OwnPropMotion is { Cancel:false } || OwnPropRunLive?.Invoke()==true)) return false;
        if(_rowByName.TryGetValue(AvatarName,out var row) && row.Interaction?.Id==pairId) return false;
        _endingOwnPair=pairId; _endingOwnPairAt=_clock;
        _log($"[prop] own pair {pairId} ended on the server; both halves wait for the run's end");
        OwnPairEnding?.Invoke();
        return true;
    }
    private void ReleaseEndingOwnPair()
    {
        if(_endingOwnPair.Length==0) return;
        string id=_endingOwnPair; _endingOwnPair="";
        _releasedOwnPropPairs.Add(id);
        foreach(var figure in _figures.Values) if(figure.Pair?.Id==id) figure.Pair=null;
    }
    private void ExpireEndingOwnPair() { if(_endingOwnPair.Length>0 && _clock-_endingOwnPairAt>OwnPairEndHoldS) ReleaseEndingOwnPair(); }

    public bool PlayOwnPropMotion(JsonObject motion,string source,string executionId="")
    {
        if(!_figures.TryGetValue(AvatarName,out var figure)) return false;
        bool cancel=source=="cancel";
        string key=cancel ? "cancel|"+executionId : PropActionMotion.Text(motion["execution_id"])+"|"+PropActionMotion.Text(motion["journey_id"]);
        if(!_ownMotionKeys.Add(key)) {
            if(!cancel && OwnPropMotion is { } current && current.Key==key && current.Phase!="arrived"
                && !JsonNode.DeepEquals(current.Plan["paces_m_s_real"],motion["paces_m_s_real"])) UpdateOwnPaces(current,motion);
            return false;
        }
        JsonObject plan=(JsonObject)motion.DeepClone();
        if(cancel) {
            double x=PropActionMotion.Number(motion["stand"]?[0]),z=PropActionMotion.Number(motion["stand"]?[1]);
            double floor=OwnPropMotion?.Plan["floor_y"]?.GetValue<double>() ?? OwnPropFloor(figure,null,x,z)-FigureGround.WalkClearanceM;
            double yaw=figure.Yaw*180/Math.PI;
            JsonObject At()=>new() { ["x"]=x,["y"]=floor+FigureGround.WalkClearanceM,["z"]=z,["yaw"]=yaw };
            plan=new JsonObject { ["execution_id"]=executionId,["journey_id"]=key,["floor_y"]=floor,
                ["waypoints"]=new JsonArray(motion["seat"]!.DeepClone(),motion["stand"]!.DeepClone()),
                ["paces_m_s_real"]=new JsonArray((JsonNode?)null),["departure"]=motion.DeepClone(),["access"]=At(),["anchor"]=At(),["entry"]=null };
        }
        OwnPropMotion=new(plan,key,_clock,figure.Position.Y,figure.Yaw,cancel);
        bool matchingHeld=!cancel && plan["departure"] is null && _rowByName.TryGetValue(AvatarName,out var currentRow)
            && currentRow.Place is { } heldPlace && heldPlace.Id==PropActionMotion.Text(plan["anchor"]?["place_id"])
            && heldPlace.Slot==(int)PropActionMotion.Number(plan["anchor"]?["slot"]);
        if(!matchingHeld) WithdrawOwnPropInteraction();
        figure.PropEntry=null; figure.PropEntryBlocked=figure.PropCommitPending=false;
        figure.Route=null; figure.Reckon=null; figure.Waypoints.Clear(); figure.Settle=null; figure.DropTravelLine();
        figure.Face=null; figure.Lean=null; figure.SurfaceGroup="ground"; figure.ApplyRotation();
        double total=TravelPath.PolylineLength(plan["waypoints"]!.AsArray().Select(p=>(PropActionMotion.Number(p![0]),PropActionMotion.Number(p[1]))).ToArray());
        _log($"[prop] motion received source={source} exec {PropActionMotion.Text(plan["execution_id"])} total_m {total:F3} departure {(plan["departure"] is null ? "no" : "yes")} entry {PropActionMotion.Text(plan["entry"]?["mode"])}");
        TickOwnPropMotion(figure,0,0);
        return true;
    }
    private void UpdateOwnPaces(OwnPropPlayback playback,JsonObject motion)
    {
        double elapsed=Math.Max(0,_clock-playback.StartedAt);
        var sample=playback.HeldSample ?? PropActionMotion.SampleMotion(playback.Plan,elapsed);
        string phase=PropActionMotion.Text(sample["phase"]);
        double entryDuration=PropActionMotion.Number(playback.Plan["entry"]?["duration_s"]);
        double entryPhase=playback.HeldEntryPhase ?? (entryDuration>0 ? (elapsed-OwnEntryAt(playback.Plan))/entryDuration : 1);
        playback.Plan["paces_m_s_real"]=motion["paces_m_s_real"]?.DeepClone();
        if(phase=="entry") {
            if(motion["paces_m_s_real"] is null) {
                playback.HeldEntryPhase=Math.Clamp(entryPhase,0,1); playback.HeldSample=(JsonObject)sample.DeepClone();
            } else {
                playback.StartedAt=_clock-OwnEntryAt(playback.Plan)-Math.Max(0,entryPhase)*entryDuration;
                playback.HeldSample=null; playback.HeldEntryPhase=null;
            }
            return;
        }
        if(phase is "departure" or "arrived") return;
        if(motion["paces_m_s_real"] is null) {
            playback.HeldSample=(JsonObject)sample.DeepClone(); playback.HeldSample["phase"]="frozen"; return;
        }
        var points=playback.Plan["waypoints"]!.AsArray().Select(p=>(X:PropActionMotion.Number(p![0]),Z:PropActionMotion.Number(p[1]))).ToArray();
        double distance=0,time=0;
        int first=0;
        if(playback.Plan["departure"] is { } departure) {
            first=1;
            if(PropActionMotion.Text(departure["exit_clip"]).Length>0) time=Math.Max(0,PropActionMotion.Number(departure["exit_s"]));
        }
        distance=PropActionMotion.ProjectApproachM(points.Skip(first).ToArray(),(PropActionMotion.Number(sample["x"]),PropActionMotion.Number(sample["z"])));
        var paces=motion["paces_m_s_real"]!.AsArray();
        for(int i=first+1;i<points.Length && distance>0;i++) {
            double length=double.Hypot(points[i].X-points[i-1].X,points[i].Z-points[i-1].Z),step=Math.Min(distance,length);
            double pace=i-1<paces.Count ? PropActionMotion.Number(paces[i-1]) : 0;
            if(pace>0) time+=step/pace;
            distance-=length;
        }
        playback.StartedAt=_clock-time; playback.HeldSample=null;
    }
    public void WithdrawOwnPropInteraction()
    {
        if(_rowByName.TryGetValue(AvatarName,out var row) && row.Interaction is { } interaction) _releasedOwnPropPairs.Add(interaction.Id);
        if(_figures.TryGetValue(AvatarName,out var figure)) {
            if(figure.Pair is { } pair) _releasedOwnPropPairs.Add(pair.Id);
            figure.Pair=null;
        }
        ReleaseEndingOwnPair();
    }
    public void ClearOwnPropMotion() { OwnPropMotion=null; }
    private double OwnPropFloor(Figure figure,JsonObject? plan,double x,double z)
    {
        if(plan?["floor_y"]?.GetValue<double>() is { } floor && double.IsFinite(floor)) return floor+FigureGround.WalkClearanceM;
        if(_rowByName.TryGetValue(figure.CharacterName,out var row) && Slots?.Invoke().GetValueOrDefault(row.LocationId) is { } tile) {
            var local=AnimaNative.Scene.SceneView.WorldToTile(tile.Stands.Frame,x,z);
            if(tile.Stands.RoomStandY(row.RoomId,local.X,local.Z) is { } roomFloor) return roomFloor;
        }
        return RoomStandAt?.Invoke(figure.CharacterName,x,z) ?? GroundY(x,z);
    }
    private static double OwnEntryAt(JsonObject plan)
    {
        double time=0; int first=0;
        if(plan["departure"] is { } departure) {
            first=1; if(PropActionMotion.Text(departure["exit_clip"]).Length>0) time=Math.Max(0,PropActionMotion.Number(departure["exit_s"]));
        }
        if(plan["paces_m_s_real"] is not JsonArray paces) return double.PositiveInfinity;
        var points=plan["waypoints"]!.AsArray();
        for(int i=first+1;i<points.Count;i++) {
            double length=double.Hypot(PropActionMotion.Number(points[i]![0])-PropActionMotion.Number(points[i-1]![0]),PropActionMotion.Number(points[i]![1])-PropActionMotion.Number(points[i-1]![1]));
            if(length==0 || (i-1<paces.Count && paces[i-1] is null)) continue;
            double pace=i-1<paces.Count ? PropActionMotion.Number(paces[i-1]) : 0;
            if(pace<=0) return double.PositiveInfinity;
            time+=length/pace;
        }
        return time;
    }
    private static JsonObject OwnEntrySpec(JsonObject plan)
    {
        var spec=(JsonObject)plan["entry"]!.DeepClone();
        spec["access"]=plan["access"]!.DeepClone(); spec["anchor"]=plan["anchor"]!.DeepClone();
        spec["root_offset"]=plan["anchor"]?["root_offset"]?.DeepClone(); spec["height_cm"]=plan["height_cm"]?.DeepClone();
        spec["game_seconds_per_real_second"]=1; return spec;
    }
    private void TickOwnPropMotion(Figure figure,double dt,double camDist)
    {
        var playback=OwnPropMotion!; var plan=playback.Plan; double elapsed=Math.Max(0,_clock-playback.StartedAt);
        var sample=playback.HeldSample ?? PropActionMotion.SampleMotion(plan,elapsed); string phase=PropActionMotion.Text(sample["phase"]);
        bool changed=phase!=playback.Phase;
        double? handBackYaw=null;
        if(playback.Cancel && phase=="arrived") {
            // Seek the last measured turn even if a slow frame skipped the entire departure.
            var departure=plan["departure"]!;
            if(PropActionMotion.Text(departure["exit_clip"]).Length>0)
                figure.PlayOwnPropDeparture(PropActionMotion.Text(departure["exit_clip"]),1,
                    playback.StartY-OwnPropFloor(figure,plan,PropActionMotion.Number(sample["x"]),PropActionMotion.Number(sample["z"])));
            double clipEnd=figure.Yaw*180/Math.PI;
            var decision=PropActionMotion.HandBackYaw(clipEnd,departure["stand_yaw_deg"] is { } stand ? PropActionMotion.Number(stand) : null);
            if(decision.Mismatch) _log($"[prop] stand yaw mismatch clip={clipEnd:F1} server={PropActionMotion.Number(departure["stand_yaw_deg"]):F1}");
            handBackYaw=decision.YawDeg*Math.PI/180;
            figure.FinishPropEntry(FigureClips.PoseKind("standing",figure.Poses));
        }
        if(changed && playback.Phase=="departure" && !playback.Cancel) figure.FinishPropEntry(FigureClips.PoseKind("standing",figure.Poses));
        double x=PropActionMotion.Number(sample["x"]),z=PropActionMotion.Number(sample["z"]);
        if(phase=="departure") { x=PropActionMotion.Number(plan["departure"]?["seat"]?[0]); z=PropActionMotion.Number(plan["departure"]?["seat"]?[1]); }
        double y=phase is "walking" or "frozen" or "departure" ? OwnPropFloor(figure,plan,x,z) : PropActionMotion.Number(sample["y"]);
        if(phase=="arrived" && !playback.Cancel) AdoptInteraction(figure);
        figure.Position=figure.Target=new((float)x,(float)y,(float)z);
        figure.SetHidden(false);
        double yaw=handBackYaw ?? (phase=="departure" ? playback.StartYaw : PropActionMotion.Number(sample["yaw"])*Math.PI/180);
        if(handBackYaw is { } finalYaw) figure.HandBackPropYaw(finalYaw);
        else if((phase!="arrived" || figure.Pair is null) && !(phase=="arrived" && HoldsPairFacing(figure))) figure.FaceTowards(new((float)Math.Sin(yaw),0,(float)Math.Cos(yaw)),snap:true);
        if(phase is "entry" or "arrived" && !playback.AccessLogged) { playback.AccessLogged=true; _log("[prop] motion arrived at access"); }
        if(phase=="departure") {
            double duration=Math.Max(0,PropActionMotion.Number(plan["departure"]?["exit_s"]));
            bool ready=figure.PlayOwnPropDeparture(PropActionMotion.Text(plan["departure"]?["exit_clip"]),duration>0 ? elapsed/duration : 1,playback.StartY-y);
            if(!ready && changed) (PropEntryError ?? _log).Invoke($"{figure.CharacterName}: measured exit clip/support unavailable");
        } else if(phase=="entry") {
            var spec=OwnEntrySpec(plan);
            if(playback.HeldEntryPhase is not null) spec["game_seconds_per_real_second"]=0;
            double duration=PropActionMotion.Number(spec["duration_s"]);
            bool ready=figure.PlayPropEntry(spec,playback.HeldEntryPhase ?? (duration>0 ? (elapsed-OwnEntryAt(plan))/duration : 1));
            if(!ready && changed) (PropEntryError ?? _log).Invoke($"{figure.CharacterName}: measured entry clip/support {PropActionMotion.Text(spec["kind"])} unavailable");
        } else if(phase=="arrived") {
            string pose=playback.Cancel ? FigureClips.PoseKind("standing",figure.Poses) : PropActionMotion.Text(plan["entry"]?["pose_key"]);
            if(pose.Length==0) pose=FigureClips.PoseKind("standing",figure.Poses);
            if(!playback.Cancel && _rowByName.TryGetValue(figure.CharacterName,out var held)
                && held.Place is { } place && place.Id==PropActionMotion.Text(plan["anchor"]?["place_id"])
                && place.Slot==(int)PropActionMotion.Number(plan["anchor"]?["slot"]) && held.ActivityAnimation.Length>0) pose=held.ActivityAnimation;
            if(changed && plan["entry"] is { } entry && PropActionMotion.Text(entry["mode"])=="bridge") {
                figure.PlayPropEntry(OwnEntrySpec(plan),1); figure.HoldPropPoseAtAnchor();
            }
            if(!playback.Cancel && figure.Pair is not null && TickPair(figure,dt,PropActionMotion.Number(plan["anchor"]?["y"]))) {
                playback.Phase=phase; return;
            }
            string role=PropActionMotion.Text(plan["role"]);
            if(role is "a" or "b" or "c" or "d" or "e" && !pose.EndsWith("__"+role,StringComparison.Ordinal)) pose+="__"+role;
            string poseKey=$"{pose}|{figure.Player?.GetInstanceId()}";
            var finale=!playback.Cancel && figure.Finale is { Role:null } ? StepFinale(figure,dt,WorldFrozen) : null;
            if(finale is { } solo && figure.PlayPair(solo.Clip,solo.T,WorldFrozen,false,restart:solo.Start,frameStep:solo.Start ? 0 : dt)) playback.FinaleOn=true;
            else if(playback.FinaleOn || playback.PoseKey!=poseKey) {
                if(figure.FinishPropEntry(pose)) { playback.PoseKey=poseKey; playback.FinaleOn=false; }
            }
            if(!playback.Cancel && !playback.AnchorLogged) {
                playback.AnchorLogged=true;
                _log($"[prop] motion seated on anchor {PropActionMotion.Text(plan["anchor"]?["place_id"])}/{PropActionMotion.Number(plan["anchor"]?["slot"])}");
            }
            if(playback.Cancel) { OwnPropMotion=null; OwnPropMotionReleased?.Invoke(); return; }
            figure.SecondaryFrozen=WorldFrozen; figure.UpdateFigure(finale?.Start==true ? 0 : dt);
        } else {
            bool walking=phase=="walking";
            string clip=FigureClips.PoseKind(walking ? "walking" : "standing",figure.Poses);
            if(changed) figure.FinishPropEntry(clip);
            figure.SetMotion(walking,false,FigureClips.WalkRun);
            figure.SecondaryFrozen=phase=="frozen"; figure.UpdateFigure(dt);
        }
        playback.Phase=phase;
        figure.Portrait?.Tick(dt,camDist,phase=="walking");
    }
}
