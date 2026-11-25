using System;
using System.Collections.Generic;
using System.Linq;
using Godot;

namespace AnimaNative.Figures;

public partial class FigureManager
{
    /// <summary>The manual release of the avatar's furniture run is under way: no direct seat commit for the avatar.</summary>
    public Func<bool>? SuppressAvatarPropEntry { get; set; }
    public void ClearPropEntry(string name,bool preservePose=false)
    {
        if(!_figures.TryGetValue(name,out var f)) return;
        f.PropEntryBlocked=false; f.PropCommitPending=false; f.PropCommitKey="";
        if(!preservePose) f.FinishPropEntry(FigureClips.PoseKind("standing",f.Poses));
        f.Route=null; f.DropTravelLine();
        f.SetHidden(false);
    }

    /// <summary>
    /// A held place on a fixed marker (`place` without a pair): the figure takes the held pose on its slot without a
    /// walk-to-sit bridge. The approach and the entry are the order's (plan E3, FigureManager.Orders.cs); a row carries no
    /// entry projection any more.
    /// </summary>
    private bool AdoptPropEntry(Figure fig,FigurePlan plan)
    {
        if(!_rowByName.TryGetValue(fig.CharacterName,out var row)) return false;
        fig.PropEntryBlocked=false;
        fig.PropCommitPending=false;
        string commit="";
        // A running pair owns clip and placement (TickPair, npcs.ts tickInteraction): its activity is the bare pair
        // KIND, which no rig binds — committing it would leave the commit pending and keep the half from playing.
        if(row.Interaction is null && row.Place is { } place && Slots?.Invoke().GetValueOrDefault(row.LocationId) is { } tile
            && tile.Places.Markers.TryGetValue(row.RoomId,out var markers)
            && markers.TryGetValue(place.Id,out var marker) && marker.Fixed && !plan.Hidden
            && !(fig.CharacterName==AvatarName && SuppressAvatarPropEntry?.Invoke()==true)) {
            commit=$"{place.Id}#{place.Slot}#{row.ActivityAnimation}#{fig.Player?.GetInstanceId()}";
            if(fig.PropCommitKey!=commit) {
                if(fig.CharacterName==AvatarName) _log("[prop] direct seat; seated confirmed");
                fig.PropCommitPending=!fig.FinishPropEntry(row.ActivityAnimation);
                fig.SnapTo(new((float)plan.Pos.X,(float)plan.Pos.Y,(float)plan.Pos.Z));
                if(plan.Face is { } facing) fig.FaceTowards(new((float)facing.X,(float)facing.Y,(float)facing.Z),snap:true);
            }
        }
        fig.PropCommitKey=fig.PropCommitPending ? "" : commit;
        return false;
    }

    private readonly HashSet<string> _releasedOwnPropPairs=new(StringComparer.Ordinal);
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
    /// comes with the prop-actions state, read on its own clock. Both halves keep playing until the own run's end lets
    /// the avatar go (<see cref="WithdrawOwnPropInteraction"/>) — the same frame — or <see cref="OwnPairEndHoldS"/> passed.
    /// </summary>
    private bool OwnPairEndingHeld(string pairId)
    {
        if(_endingOwnPair==pairId) return true;
        if(!_figures.TryGetValue(AvatarName,out var avatar) || avatar.Pair?.Id!=pairId || _releasedOwnPropPairs.Contains(pairId)) return false;
        if(!(HasLiveOrder(AvatarName) || OwnPropRunLive?.Invoke()==true)) return false;
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
    public void WithdrawOwnPropInteraction()
    {
        if(_rowByName.TryGetValue(AvatarName,out var row) && row.Interaction is { } interaction) _releasedOwnPropPairs.Add(interaction.Id);
        if(_figures.TryGetValue(AvatarName,out var figure)) {
            if(figure.Pair is { } pair) _releasedOwnPropPairs.Add(pair.Id);
            figure.Pair=null;
        }
        ReleaseEndingOwnPair();
    }
}
