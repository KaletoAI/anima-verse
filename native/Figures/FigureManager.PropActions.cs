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
    public Func<bool>? OwnedPropApproaching { get; set; }
    public Func<bool>? SuppressAvatarPropEntry { get; set; }
    public Action<string>? PropEntryError { get; set; }
    public bool HasPropMotion=>_figures.Values.Any(f=>f.PropEntry is not null || f.Route?.ExactPath is not null);
    public void ClearPropEntry(string name)
    {
        if(!_figures.TryGetValue(name,out var f)) return;
        f.PropEntry=null; f.PropEntryBlocked=false; f.PropCommitPending=false; f.PropCommitKey=""; f.FinishPropEntry(FigureClips.PoseKind("standing",f.Poses));
        f.Route=null; f.DropTravelLine(); f.SetHidden(false);
    }
    private bool AdoptExactPropRoute(Figure fig,CharacterRow row)
    {
        JsonObject? path=null;
        if(row.Name!=AvatarName && row.LocalApproach is { } local && PropActionMotion.Text(local["room_id"])==row.RoomId) path=local;
        else if(row.Name==AvatarName && OwnedPropApproaching?.Invoke()==true && row.Travel is { } tr)
        {
            path=new JsonObject { ["waypoints"]=new JsonArray(tr.Waypoints?.Select(p=>(JsonNode?)new JsonArray(p.X,p.Z)).ToArray() ?? Array.Empty<JsonNode?>()),
                ["floor_y"]=tr.FloorY,["progress_m"]=tr.ProgressM,["starts_in_s"]=tr.StartsInS ?? 0,["journey_id"]=tr.JourneyId,
                ["paces_m_s_real"]=tr.Paces is null ? null : new JsonArray(tr.Paces.Select(p=>(JsonNode?)JsonValue.Create(p)).ToArray()) };
        }
        if(path?["waypoints"] is not JsonArray { Count:>=2 } wp || path["progress_m"] is null
            || (row.Name==AvatarName && SuppressAvatarJourney?.Invoke(PropActionMotion.Text(path["journey_id"]))==true)) return false;
        string key="prop|"+PropActionMotion.Text(path["journey_id"])+"|"+wp.ToJsonString();
        var points=wp.Select(p=>(X:PropActionMotion.Number(p![0]),Z:PropActionMotion.Number(p[1]))).ToArray();
        if(fig.Route is not { } route || route.Key!=key)
            fig.Route=route=new JourneyRoute { Key=key,Points=points,TotalM=TravelPath.PolylineLength(points),Stamp=-1 };
        if(route.Stamp!=Stats.Polls) {
            route.ExactPath=(JsonObject)path.DeepClone(); route.ReceivedAt=_mapAppliedClock; route.Stamp=Stats.Polls;
            route.Paces=(path["paces_m_s_real"] as JsonArray)?.Select(p=>p?.GetValue<double>()).ToArray();
            route.TargetM=route.ShownM=PropActionMotion.Number(path["progress_m"]);
        }
        fig.Waypoints.Clear(); fig.Settle=null; fig.Reckon=null; return true;
    }
    private bool AdoptPropEntry(Figure fig,FigurePlan plan)
    {
        if(!_rowByName.TryGetValue(fig.CharacterName,out var row)) return false;
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
        if(route.ExactPath?["floor_y"]?.GetValue<double>() is { } floor && double.IsFinite(floor)) return floor;
        if(_rowByName.TryGetValue(fig.CharacterName,out var row)
            && Slots?.Invoke().GetValueOrDefault(row.LocationId) is { } tile) {
            var local=AnimaNative.Scene.SceneView.WorldToTile(tile.Stands.Frame,x,z);
            if(tile.Stands.RoomStandY(row.RoomId,local.X,local.Z) is { } roomFloor) return roomFloor;
        }
        return RoomStandAt?.Invoke(fig.CharacterName,x,z) ?? GroundY(x,z);
    }
    private void StepExactPropRoute(Figure fig,JourneyRoute route,double dt,double camDist)
    {
        var before=fig.Position; var point=PropActionMotion.LocalApproachPoint(route.ExactPath!,_clock-route.ReceivedAt);
        fig.Position=new((float)point.X,(float)PropApproachFloor(fig,route,point.X,point.Z),(float)point.Z); fig.Target=fig.Position;
        bool moving=double.Hypot(point.X-before.X,point.Z-before.Z)>1e-6;
        if(moving) fig.FaceTowards(fig.Position-before);
        var paces=Enumerable.Range(0,route.Points.Count-1).Select(i=>(double?)(route.Paces is { } ps && i<ps.Count ? ps[i] ?? 0 : 0)).ToArray();
        route.ShownM=route.TargetM=TravelPath.AdvanceAlongPaces(route.Points,paces,PropActionMotion.Number(route.ExactPath!["progress_m"]),
            Math.Max(0,_clock-route.ReceivedAt-Math.Max(0,PropActionMotion.Number(route.ExactPath["starts_in_s"]))));
        UpdateTravelLine(fig);
        fig.SetMotion(moving,false,FigureClips.WalkRun);
        fig.Play(FigureClips.PoseKind(moving ? "walking" : "standing",fig.Poses));
        fig.SecondaryFrozen=WorldFrozen; fig.UpdateFigure(dt); fig.Portrait?.Tick(dt,camDist,moving);
    }
}
