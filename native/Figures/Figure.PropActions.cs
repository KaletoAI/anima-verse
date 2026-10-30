using System;
using System.Text.Json.Nodes;
using AnimaNative.Props;
using AnimaNative.Scatter;
using Godot;

namespace AnimaNative.Figures;

public partial class Figure
{
    public PropEntryPlayback? PropEntry { get; internal set; }
    public bool PropEntryBlocked { get; internal set; }
    internal bool PropCommitPending { get; set; }
    internal string PropCommitKey { get; set; } = "";
    public double PropEntryLift { get; private set; }
    /// <summary>
    /// Task 57: playPropEntry uses the installed measured root path and fitted hips track. Phase seeks the actual
    /// Animation length, capped by 1e-6. There is no synthesized intro, height-derived clock or extra root offset.
    /// The borrowed Animation/ClipExtras stay immutable; figure owns the manual player and bridge state.
    /// </summary>
    public bool PlayPropEntry(JsonObject spec,double phase)
    {
        string kind=PropActionMotion.Text(spec["kind"]);
        if(Player is not { } player || !HasAction(kind) || !EnsureClip(kind) || PropActionMotion.Number(spec["height_cm"])<=0) return false;
        var animation=AnimOf(kind);
        if(animation is null || animation.Length<=0 || !Extras.TryGetValue(animation,out var extras) || extras.Path is null) return false;
        int hips=-1;
        for(int i=0;i<animation.GetTrackCount();i++) {
            string path=animation.TrackGetPath(i).ToString();
            if(animation.TrackGetType(i)==Animation.TrackType.Position3D && path.Contains("hips",StringComparison.OrdinalIgnoreCase)) { hips=i; break; }
        }
        if(hips<0) return false;
        double time=Math.Min(animation.Length-1e-6,Math.Max(0,phase)*animation.Length);
        double first=animation.PositionTrackInterpolate(hips,0).Y,last=animation.PositionTrackInterpolate(hips,animation.Length).Y;
        double? lift=PropActionMotion.EntrySupportLift(first,last,animation.PositionTrackInterpolate(hips,time).Y,
            PropActionMotion.Number(spec["access"]?["y"]),PropActionMotion.Number(spec["anchor"]?["y"]),PropActionMotion.Number(spec["root_offset"]));
        if(lift is null) return false;
        if(CurrentClip!=kind || _transition?.Kind!=kind) {
            ReleaseBridge(); TakeTravel(); player.Stop(); _runs.Clear(); _currentRun=null;
            var run=new BridgeRun { Kind=kind,Length=animation.Length,Extras=extras };
            _transition=_currentRun=run; _runs.Add(run); _travelAction=run;
            _travelPath=extras.Path; _travelOrigin=new P2(0,0); _bridgeUntil=double.PositiveInfinity; _bridgeAccel=0;
            Yaw=TargetYaw=PropActionMotion.Number(spec["access"]?["yaw"])*Math.PI/180; StartTurn(extras.Turn,run);
            SetClipDrop(0); HeightCorrectionM=0; _terrainClip=false; _sink=0;
            var name=PlayName(kind,false); player.Play(name); CurrentClip=kind; CurrentKind=kind;
        }
        _transition!.Time=time; _travelAction=_transition;
        player.SpeedScale=0; player.Seek(time,true);
        double yaw=PropActionMotion.Number(spec["access"]?["yaw"])*Math.PI/180;
        if(_turn is null) Yaw=TargetYaw=yaw;
        _lift=PropEntryLift=lift.Value;
        SecondaryFrozen=PropActionMotion.Number(spec["game_seconds_per_real_second"])<=0;
        UpdateFigure(0); return true;
    }
    /// <summary>Answer-clock exit playback retains the measured root path and turn at the held seat.</summary>
    public bool PlayOwnPropDeparture(string kind,double phase,double startLift)
    {
        if(Player is not { } player || !EnsureClip(kind) || AnimOf(kind) is not { } animation) return false;
        double time=Math.Clamp(phase,0,1)*Math.Max(0,animation.Length-1e-6);
        if(CurrentClip!=kind || _transition?.Kind!=kind) {
            ReleaseBridge(); TakeTravel(); _runs.Clear(); _currentRun=null;
            var run=new BridgeRun { Kind=kind,Length=animation.Length,Extras=Extras.TryGetValue(animation,out var extras) ? extras : null };
            _transition=_currentRun=run; _runs.Add(run); _bridgeUntil=double.PositiveInfinity;
            _travelPath=run.Extras?.Path; _travelAction=run; _travelOrigin=new P2(0,0);
            StartTurn(run.Extras?.Turn,run);
            SetClipDrop(0); HeightCorrectionM=0; _terrainClip=false; _sink=0;
            player.Play(PlayName(kind,false)); CurrentClip=CurrentKind=kind;
        }
        double fraction=Math.Clamp(phase,0,1);
        int hips=-1;
        for(int i=0;i<animation.GetTrackCount();i++) if(animation.TrackGetType(i)==Animation.TrackType.Position3D
            && animation.TrackGetPath(i).ToString().Contains("hips",StringComparison.OrdinalIgnoreCase)) { hips=i; break; }
        if(hips>=0) {
            double first=animation.PositionTrackInterpolate(hips,0).Y,last=animation.PositionTrackInterpolate(hips,animation.Length).Y;
            if(Math.Abs(last-first)<1e-6) { if(Math.Abs(startLift)>1e-6) return false; fraction=1; }
            else fraction=Math.Clamp((animation.PositionTrackInterpolate(hips,time).Y-first)/(last-first),0,1);
        } else if(Math.Abs(startLift)>1e-6) return false;
        _transition!.Time=time; player.SpeedScale=0; player.Seek(time,true);
        _lift=startLift*(1-fraction); SecondaryFrozen=false; UpdateFigure(0); return true;
    }
    /// <summary>Bake the measured rendered displacement into the root before input takes ownership.</summary>
    public void ReleasePropAtRenderedPoint()
    {
        var travel=TakeTravel();
        Position+=new Vector3((float)(travel?.X ?? 0),(float)_lift,(float)(travel?.Z ?? 0)); Target=Position;
        HoldPropPoseAtAnchor();
    }
    /// <summary>Keep the current measured frame while removing its root displacement at the final anchor.</summary>
    public void HoldPropPoseAtAnchor()
    {
        ReleaseBridge(); TakeTravel(); _travelPath=null; _travelAction=null; _turn=null; _turnAction=null;
        _lift=PropEntryLift=0; ApplyBody();
        if(Player is { } player) player.SpeedScale=0;
    }
    /// <summary>Task 57: commit the played entry once, drop travel/lift, then play the direct pose without a bridge.</summary>
    public bool FinishPropEntry(string clip)
    {
        if(!EnsureClip(clip)) return false;
        ReleaseBridge(); TakeTravel(); _travelPath=null; _travelAction=null; _turn=null; _turnAction=null;
        _lift=PropEntryLift=0; ApplyBody();
        if(Player is { } player) player.SpeedScale=1;
        if(!PlayPair(clip,0,false,true)) return false;
        // A body replacement replays WantedClip before the next placement tick.
        WantedClip=(clip,false,0,"ground");
        return true;
    }
}
