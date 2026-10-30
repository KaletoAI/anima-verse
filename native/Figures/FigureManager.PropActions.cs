using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Props;
using Godot;

namespace AnimaNative.Figures;

/// <summary>Task 57: per-figure public entry projection; identity survives elapsed polls without replaying the clip.</summary>
public sealed class PropEntryPlayback(JsonObject spec,string key,int stamp,double receivedAt)
{
    public JsonObject Spec=spec;
    public string Key=key;
    public int Stamp=stamp;
    public double ReceivedAt=receivedAt;
    public bool Played,Failed;
}

public partial class FigureManager
{
    public Func<bool>? SuppressAvatarPropEntry { get; set; }
    public Action<string>? PropEntryError { get; set; }
    public void ClearPropEntry(string name,bool preservePose=false)
    {
        if(!_figures.TryGetValue(name,out var f)) return;
        f.PropEntry=null; f.PropEntryBlocked=false; f.PropCommitPending=false; f.PropCommitKey="";
        if(!preservePose) f.FinishPropEntry(FigureClips.PoseKind("standing",f.Poses));
        f.Route=null; f.DropTravelLine();
        f.SetHidden(false);
    }
    private bool AdoptExactPropRoute(Figure fig,CharacterRow row)
    {
        JsonObject? path=null;
        if(row.Name!=AvatarName && row.LocalApproach is { } local && PropActionMotion.Text(local["room_id"])==row.RoomId) path=local;
        if(path?["waypoints"] is not JsonArray { Count:>=2 } wp || path["progress_m"] is null) return false;
        string key="prop|"+PropActionMotion.Text(path["journey_id"])+"|"+wp.ToJsonString();
        var points=wp.Select(p=>(X:PropActionMotion.Number(p![0]),Z:PropActionMotion.Number(p[1]))).ToArray();
        if(fig.Route is not { } route || route.Key!=key)
            fig.Route=route=new JourneyRoute { Key=key,Points=points,TotalM=TravelPath.PolylineLength(points),Stamp=-1 };
        if(route.Stamp!=Stats.Polls) {
            route.ExactPath=(JsonObject)path.DeepClone(); route.ReceivedAt=_mapAppliedClock-_ageAtAppliedS; route.Stamp=Stats.Polls;
            route.Paces=(path["paces_m_s_real"] as JsonArray)?.Select(p=>p?.GetValue<double>()).ToArray();
            route.ShownM=route.TargetM=PropActionMotion.Number(path["progress_m"]);
            if(PropActionMotion.Number(path["starts_in_s"])>_clock-route.ReceivedAt
                && row.ActivityAnimation!=FigureClips.PoseKind("standing",fig.Poses)) route.DepartureClip=row.ActivityAnimation;
        }
        fig.Waypoints.Clear(); fig.Settle=null; fig.Reckon=null; return true;
    }
    private bool AdoptPropEntry(Figure fig,FigurePlan plan)
    {
        if(!_rowByName.TryGetValue(fig.CharacterName,out var row)) return false;
        bool hadEntry=fig.PropEntry is not null;
        var spec=!plan.Hidden && !(fig.CharacterName==AvatarName && SuppressAvatarPropEntry?.Invoke()==true) ? row.PropActionEntry : null;
        if(spec is null) {
            // A held place is authoritative even when the live entry was missed or could not be fitted.
            // Its absence ends the entry gate without waiting for a clip or a deadline.
            fig.PropEntryBlocked=false;
            fig.PropCommitPending=false;
            if(fig.PropEntry is { } previous) {
                if(previous.Played) fig.PlayPropEntry(previous.Spec,1);
                if(row.Place is not null || row.Interaction is not null) {
                    fig.Position=EntryPoint(previous.Spec["anchor"]!); fig.Target=fig.Position;
                    fig.FaceTowards(EntryFacing(previous.Spec["anchor"]!),snap:true);
                }
                if(fig.CharacterName==AvatarName && row.Place is not null) _log("[prop] seated confirmed");
                fig.FinishPropEntry(row.ActivityAnimation.Length>0 ? row.ActivityAnimation : FigureClips.PoseKind("standing",fig.Poses));
                fig.PropEntry=null; fig.Route=null;
                if((row.Place is not null || row.Interaction is not null) && Slots is null) return true;
            }
            string commit="";
            if(row.Place is { } place && Slots?.Invoke().GetValueOrDefault(row.LocationId) is { } tile
                && tile.Places.Markers.TryGetValue(row.RoomId,out var markers)
                && markers.TryGetValue(place.Id,out var marker) && marker.Fixed && !plan.Hidden
                && !(fig.CharacterName==AvatarName && SuppressAvatarPropEntry?.Invoke()==true)) {
                commit=$"{place.Id}#{place.Slot}#{row.ActivityAnimation}#{fig.Player?.GetInstanceId()}";
                if(fig.PropCommitKey!=commit) {
                    // Direct entry has no prop_action_entry; take the held pose without another walk-to-sit bridge.
                    if(fig.CharacterName==AvatarName && !hadEntry) _log("[prop] direct seat; seated confirmed");
                    fig.PropCommitPending=!fig.FinishPropEntry(row.ActivityAnimation);
                    fig.SnapTo(new((float)plan.Pos.X,(float)plan.Pos.Y,(float)plan.Pos.Z));
                    if(plan.Face is { } facing) fig.FaceTowards(new((float)facing.X,(float)facing.Y,(float)facing.Z),snap:true);
                }
            }
            fig.PropCommitKey=fig.PropCommitPending ? "" : commit;
            return false;
        }
        fig.PropCommitPending=false;
        string key=PropActionMotion.EntryIdentity(spec);
        if(fig.PropEntry is not { } entry || entry.Key!=key) {
            if(fig.CharacterName==AvatarName) _log($"[prop] entry start bridge={PropActionMotion.Text(spec["kind"])}");
            fig.PropEntryBlocked=false; fig.PropEntry=new((JsonObject)spec.DeepClone(),key,Stats.Polls,_clock);
        } else if(entry.Stamp!=Stats.Polls) {
            entry.Spec=(JsonObject)spec.DeepClone(); entry.Stamp=Stats.Polls; entry.ReceivedAt=_clock;
        }
        fig.Route=null; fig.Waypoints.Clear(); fig.DropTravelLine(); fig.SetHidden(plan.Hidden); return true;
    }
    private static Vector3 EntryPoint(JsonNode point)=>new((float)PropActionMotion.Number(point["x"]),(float)PropActionMotion.Number(point["y"]),(float)PropActionMotion.Number(point["z"]));
    private static Vector3 EntryFacing(JsonNode point) { double yaw=PropActionMotion.Number(point["yaw"])*Math.PI/180; return new((float)Math.Sin(yaw),0,(float)Math.Cos(yaw)); }
    private void TickPropEntry(Figure fig)
    {
        var entry=fig.PropEntry!; var spec=entry.Spec;
        fig.Position=EntryPoint(spec["access"]!); fig.Target=fig.Position;
        bool ready=fig.PlayPropEntry(spec,PropActionMotion.EntryPhase(spec,_clock-entry.ReceivedAt));
        if(!ready && !entry.Failed) (PropEntryError ?? _log).Invoke($"{fig.CharacterName}: measured entry clip/support {PropActionMotion.Text(spec["kind"])} unavailable");
        entry.Played|=ready; entry.Failed=!ready;
    }
    private double PropApproachFloor(Figure fig,JourneyRoute route,double x,double z)
    {
        // The server's floor_y is the bare floor; the walking clearance comes on top, as for every room floor.
        if(route.ExactPath?["floor_y"]?.GetValue<double>() is { } floor && double.IsFinite(floor)) return floor+AnimaNative.Figures.FigureGround.WalkClearanceM;
        if(_rowByName.TryGetValue(fig.CharacterName,out var row)
            && Slots?.Invoke().GetValueOrDefault(row.LocationId) is { } tile) {
            var local=AnimaNative.Scene.SceneView.WorldToTile(tile.Stands.Frame,x,z);
            if(tile.Stands.RoomStandY(row.RoomId,local.X,local.Z) is { } roomFloor) return roomFloor;
        }
        return RoomStandAt?.Invoke(fig.CharacterName,x,z) ?? GroundY(x,z);
    }
    private void StepExactPropRoute(Figure fig,JourneyRoute route,double dt,double camDist)
    {
        double age=_clock-route.ReceivedAt,starts=PropActionMotion.Number(route.ExactPath!["starts_in_s"]);
        bool waiting=starts>age;
        if(route.DepartureClip.Length>0 && !route.DepartureStarted) {
            double rootY=fig.Position.Y,goalY=PropApproachFloor(fig,route,fig.Position.X,fig.Position.Z);
            route.DepartureStarted=fig.PlayDeparture(route.DepartureClip);
            if(route.DepartureStarted) { fig.Face=null; fig.Lean=null; fig.SurfaceGroup="ground"; fig.ApplyRotation(); }
            if(route.DepartureStarted && fig.BeginBridgeLift(rootY-goalY))
                fig.Position=new(fig.Position.X,(float)goalY,fig.Position.Z);
        }
        if(!fig.Bridging && fig.HoldsTravel && ApplyBridgeTravel(fig))
            route.ShownM=PropActionMotion.ProjectApproachM(route.Points,(fig.Position.X,fig.Position.Z));
        if(waiting || (route.DepartureStarted && fig.Bridging)) {
            if(route.DepartureClip.Length==0 || route.DepartureStarted) fig.Play(FigureClips.PoseKind("standing",fig.Poses));
            fig.SecondaryFrozen=WorldFrozen; fig.UpdateFigure(dt); fig.Portrait?.Tick(dt,camDist,false);
            return;
        }
        var before=fig.Position;
        var paces=route.Paces;
        route.TargetM=TravelPath.AdvanceAlongPaces(route.Points,paces,PropActionMotion.Number(route.ExactPath!["progress_m"]),
            Math.Max(0,_clock-route.ReceivedAt-Math.Max(0,PropActionMotion.Number(route.ExactPath["starts_in_s"]))));
        var point=PropActionMotion.LocalApproachPoint(route.ExactPath!,_clock-route.ReceivedAt);
        route.ShownM=route.TargetM;
        fig.Position=new((float)point.X,(float)PropApproachFloor(fig,route,point.X,point.Z),(float)point.Z); fig.Target=fig.Position;
        // The walking request opens its bridge even while that bridge forbids the first step.
        bool moving=double.Hypot(point.X-before.X,point.Z-before.Z)>1e-6;
        if(double.Hypot(point.X-before.X,point.Z-before.Z)>1e-6) fig.FaceTowards(fig.Position-before);
        UpdateTravelLine(fig);
        fig.SetMotion(moving,false,FigureClips.WalkRun);
        fig.Play(FigureClips.PoseKind(moving ? "walking" : "standing",fig.Poses));
        fig.SecondaryFrozen=WorldFrozen; fig.UpdateFigure(dt); fig.Portrait?.Tick(dt,camDist,moving);
    }
}
