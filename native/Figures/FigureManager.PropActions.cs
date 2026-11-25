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
                // An entry that ends in a PAIR hands clip and height to the half (TickPair): its activity is the bare pair
                // kind, which no rig binds, so committing it fails before the entry's support lift is dropped — the body
                // stayed lifted by the whole rise from the floor to the seat on top of the anchor root.
                if(row.Interaction is not null) fig.HoldPropPoseAtAnchor();
                else fig.FinishPropEntry(row.ActivityAnimation.Length>0 ? row.ActivityAnimation : FigureClips.PoseKind("standing",fig.Poses));
                fig.PropEntry=null; fig.Route=null;
                if((row.Place is not null || row.Interaction is not null) && Slots is null) return true;
            }
            string commit="";
            // A running pair owns clip and placement (TickPair, npcs.ts tickInteraction): its activity is the bare pair
            // KIND, which no rig binds — committing it would leave the commit pending and keep the half from playing.
            if(row.Interaction is null && row.Place is { } place && Slots?.Invoke().GetValueOrDefault(row.LocationId) is { } tile
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
}
