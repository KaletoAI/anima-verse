using System.Text.Json;
using AnimaNative.Sky;
using AnimaNative.World;
using Godot;

namespace AnimaNative;

/// <summary>
/// Main, the exploration veil (main.ts "THE VEIL"): the memory on its own signature (<see cref="ExploredSync"/> —
/// every map sets <c>fogged</c>, a moved <c>explored_sig</c> refetches <c>/play/explored</c>), and per frame the
/// crossfade plus the strength from the camera height above its target (<see cref="VeilUniforms"/>).
/// </summary>
public partial class Main : Node3D
{
    private ExploredSync? _explored;

    /// <summary>After the world stands: the sync against this session's source, then the boot map's memory.</summary>
    private void StartVeil(JsonElement firstMap)
    {
        var source = _source!;
        _explored = new ExploredSync(
            async () =>
            {
                using var doc = await source.GetExploredAsync();
                return ExploredSync.Parse(doc.RootElement);
            },
            cells =>
            {
                VeilUniforms.SetCells(cells);
                var s = VeilUniforms.State;
                Log($"veil: {s.ExploredCells} explored cells (sig {_explored?.Sig ?? "?"}), grid {s.GeomB}");
            },
            VeilUniforms.SetFogged, Log);
        SyncExplored(firstMap);
    }

    /// <summary><c>syncExplored(map)</c>: from the boot map, every poll and the admin's view switch.</summary>
    private void SyncExplored(JsonElement map)
    {
        if (_explored is null) return;
        var (fogged, sig) = ExploredSync.OfMap(map);
        _ = _explored.SyncAsync(fogged, sig);
    }

    /// <summary>main.ts' frame hook: <c>tickFogVeil(dt)</c>, then <c>setFogVeilCameraHeight(camera.y − target.y)</c>.</summary>
    private void TickVeil(double delta)
    {
        if (_camera is null) return;
        VeilUniforms.Tick(delta);
        VeilUniforms.SetCameraHeight(_camera.GlobalPosition.Y - _camera.Target.Y);
    }
}
