using System;
using System.Threading.Tasks;
using Godot;

namespace AnimaNative;

public partial class Main : Node3D
{
    /// <summary>Task 57: semantic mutations force a fresh full map through the normal view/revision-aware consumer.</summary>
    private async Task RefreshPropWorldAsync()
    {
        var map=await FetchWorldMapAsync();
        if(Leaving || _stop.IsCancellationRequested) return;
        if(_viewSwitchBusy || map.ViewRev!=_viewRev || _figures is null)
            throw new InvalidOperationException("Furniture motion refresh was superseded by a view change");
        ApplyWorldMap(map);
    }
}
