using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Threading.Tasks;

namespace AnimaNative.Sky;

/// <summary>
/// One explored-cells texture as <c>setFogVeilCells</c> (client3d/src/scene/fogVeil.ts) fills it: one R8 texel per
/// 64 m cell over <see cref="FogVeil.Grid"/>, 255 where the avatar has been, 0 elsewhere (the padding ring included);
/// no grid = the neutral one zero texel.
/// </summary>
public sealed record FogCells(FogGrid? Grid, int Cols, int Rows, byte[] Data)
{
    /// <summary><c>neutralCells</c>: "nothing is explored" — one zero texel.</summary>
    public static readonly FogCells Neutral = new(null, 1, 1, new byte[1]);

    /// <summary>The geometry uniform (cx0, cz0, cols, rows); the neutral texture reads (0, 0, 1, 1).</summary>
    public (double X, double Y, double Z, double W) Geom
        => Grid is { } g ? (g.Cx0, g.Cz0, g.Cols, g.Rows) : (0, 0, 1, 1);

    /// <summary>How many texels say "explored".</summary>
    public int Explored
    {
        get
        {
            int n = 0;
            foreach (var b in Data) if (b != 0) n++;
            return n;
        }
    }
}

public static partial class FogVeil
{
    /// <summary>
    /// <c>setFogVeilCells</c>' data half: the grid of every readable key, then 255 at each key's texel — a key the
    /// strict parser refuses is skipped, a key outside the (capped) grid is dropped.
    /// </summary>
    public static FogCells Cells(IReadOnlyList<string>? cells)
    {
        cells ??= Array.Empty<string>();
        if (Grid(cells) is not { } grid) return FogCells.Neutral;
        int cols = (int)grid.Cols, rows = (int)grid.Rows;
        var data = new byte[cols * rows];
        foreach (var key in cells)
        {
            if (ParseCell(key) is not { } c) continue;
            double at = TexIndex(c.Cx, c.Cz, grid);
            if (at >= 0) data[(int)at] = 255;
        }
        return new FogCells(grid, cols, rows, data);
    }
}

/// <summary>
/// The veil's module state of <c>fogVeil.ts</c>, Godot-free (<typeparamref name="T"/> = the renderer's texture): two
/// cell textures A/B with their geometries, the crossfade <see cref="Mix"/> (0 = A, 1 = B) and the strength
/// <see cref="Alpha"/> made of the camera height, the <c>fogged</c> flag and the debug switch.
///
///   · <see cref="SetCells"/>: the new set becomes B, the old B becomes A, the fade restarts at 0; the old A is retired
///     unless it is still bound or the neutral texture (a change during a fade restarts it from the half-shown state);
///   · <see cref="Tick"/>: the fade runs 0 → 1 over <see cref="FogVeil.FadeS"/>; when it lands, A takes B (both samplers
///     on the new set) and the old A is retired;
///   · <see cref="Release"/>: back to the neutral texture (teardown).
/// </summary>
public sealed class FogVeilState<T> where T : class
{
    private readonly T _neutral;
    private readonly Func<FogCells, T> _make;
    private readonly Action<T> _retire;
    private double _camHeight;
    private bool _fogged = true, _debugOff;

    public FogVeilState(T neutral, Func<FogCells, T> make, Action<T>? retire = null)
    {
        _neutral = neutral;
        _make = make;
        _retire = retire ?? (_ => { });
        A = B = neutral;
    }

    public T A { get; private set; }
    public T B { get; private set; }
    public (double X, double Y, double Z, double W) GeomA { get; private set; } = (0, 0, 1, 1);
    public (double X, double Y, double Z, double W) GeomB { get; private set; } = (0, 0, 1, 1);
    /// <summary><c>uFogMix</c>: 0 = show A, 1 = show B.</summary>
    public double Mix { get; private set; } = 1;
    /// <summary><c>uFogAlpha</c>: <c>FOG_ALPHA_MAX · fogHeightAlpha(h)</c>, or 0 when switched off or unfogged.</summary>
    public double Alpha { get; private set; }
    /// <summary>The explored texels of the newest set (B) — for the log and the check.</summary>
    public int ExploredCells { get; private set; }
    /// <summary>Counts every change of A, B or their geometries (a binding re-pushes the textures when it moved).</summary>
    public int Version { get; private set; }

    public bool Fogged => _fogged;
    public double CameraHeight => _camHeight;

    private void PushAlpha() => Alpha = _debugOff || !_fogged ? 0 : FogVeil.AlphaMax * FogVeil.HeightAlpha(_camHeight);

    /// <summary><c>setFogVeilCameraHeight</c>: a non-finite height reads 0 (no veil).</summary>
    public void SetCameraHeight(double metres)
    {
        _camHeight = double.IsFinite(metres) ? metres : 0;
        PushAlpha();
    }

    /// <summary><c>setFogVeilFogged</c>: the admin's unfiltered view (<c>fogged: false</c>) has no veil.</summary>
    public void SetFogged(bool on)
    {
        _fogged = on;
        PushAlpha();
    }

    /// <summary><c>setFogVeilDebugOff</c>.</summary>
    public void SetDebugOff(bool on)
    {
        _debugOff = on;
        PushAlpha();
    }

    private void Retire(T tex)
    {
        if (ReferenceEquals(tex, _neutral) || ReferenceEquals(tex, A) || ReferenceEquals(tex, B)) return;
        _retire(tex);
    }

    /// <summary><c>setFogVeilCells</c>: the whole memory, every time (the payload is flat and complete).</summary>
    public FogCells SetCells(IReadOnlyList<string>? cells)
    {
        var data = FogVeil.Cells(cells);
        var next = data.Grid is null ? _neutral : _make(data);
        var previousA = A;
        A = B;
        GeomA = GeomB;
        B = next;
        GeomB = data.Geom;
        Mix = 0;
        ExploredCells = data.Explored;
        Version++;
        Retire(previousA);
        return data;
    }

    /// <summary><c>tickFogVeil</c>: true when anything moved (the mix, or the settle that hands A the new set).</summary>
    public bool Tick(double dt)
    {
        if (Mix >= 1) return false;
        Mix = Math.Min(1, Mix + (dt > 0 ? dt : 0) / FogVeil.FadeS);
        if (Mix < 1) return true;
        var old = A;
        A = B;
        GeomA = GeomB;
        Version++;
        Retire(old);
        return true;
    }

    /// <summary><c>releaseFogVeil</c>: nothing explored, nothing held.</summary>
    public void Release()
    {
        var a = A;
        var b = B;
        A = B = _neutral;
        GeomA = GeomB = (0, 0, 1, 1);
        Mix = 1;
        ExploredCells = 0;
        Version++;
        Retire(a);
        Retire(b);
    }
}

/// <summary>
/// main.ts <c>syncExplored(map)</c>: the veil's memory on its own signature. Every map sets the <c>fogged</c> flag; a
/// moved <c>explored_sig</c> refetches <c>/play/explored</c> (one fetch at a time); an empty signature is a memory of
/// nothing; the SERVER's signature of the answer is kept; a failed fetch keeps what stands and tries at the next map.
/// </summary>
public sealed class ExploredSync
{
    private readonly Func<Task<(IReadOnlyList<string>? Cells, string? Sig)>> _fetch;
    private readonly Action<IReadOnlyList<string>> _cells;
    private readonly Action<bool> _fogged;
    private readonly Action<string>? _log;
    private string? _sig;
    private bool _busy;

    public ExploredSync(Func<Task<(IReadOnlyList<string>? Cells, string? Sig)>> fetch, Action<IReadOnlyList<string>> cells,
                        Action<bool> fogged, Action<string>? log = null)
    {
        _fetch = fetch;
        _cells = cells;
        _fogged = fogged;
        _log = log;
    }

    /// <summary>
    /// The <c>/play/explored</c> answer <c>{cells, sig}</c>: the string keys of <c>cells</c> (anything else is skipped —
    /// the strict cell parser decides later), <c>sig</c> when it is a string; missing fields are null.
    /// </summary>
    public static (IReadOnlyList<string>? Cells, string? Sig) Parse(JsonElement root)
    {
        if (root.ValueKind != JsonValueKind.Object) return (null, null);
        List<string>? cells = null;
        if (root.TryGetProperty("cells", out var c) && c.ValueKind == JsonValueKind.Array)
        {
            cells = new List<string>(c.GetArrayLength());
            foreach (var e in c.EnumerateArray())
                if (e.ValueKind == JsonValueKind.String) cells.Add(e.GetString()!);
        }
        string? sig = root.TryGetProperty("sig", out var s) && s.ValueKind == JsonValueKind.String ? s.GetString() : null;
        return (cells, sig);
    }

    /// <summary><c>map.fogged !== false</c> and <c>map.explored_sig ?? ''</c> of a worldmap.</summary>
    public static (bool Fogged, string Sig) OfMap(JsonElement map)
    {
        bool fogged = !(map.ValueKind == JsonValueKind.Object && map.TryGetProperty("fogged", out var f) && f.ValueKind == JsonValueKind.False);
        string sig = map.ValueKind == JsonValueKind.Object && map.TryGetProperty("explored_sig", out var e) && e.ValueKind == JsonValueKind.String
            ? e.GetString()! : "";
        return (fogged, sig);
    }

    /// <summary>The signature the cells standing now belong to (null = none taken yet).</summary>
    public string? Sig => _sig;
    public int Fetches { get; private set; }
    public int Failures { get; private set; }

    /// <param name="fogged"><c>map.fogged !== false</c> — absent counts as fogged.</param>
    /// <param name="exploredSig"><c>map.explored_sig ?? ''</c>.</param>
    public async Task SyncAsync(bool fogged, string exploredSig)
    {
        _fogged(fogged);
        string sig = exploredSig ?? "";
        if (sig == _sig || _busy) return;
        if (sig.Length == 0)
        {
            _sig = sig;
            _cells(Array.Empty<string>());
            return;
        }
        _busy = true;
        try
        {
            Fetches++;
            var (cells, serverSig) = await _fetch();
            _sig = serverSig ?? sig;
            _cells(cells ?? Array.Empty<string>());
        }
        catch (Exception e)
        {
            Failures++;
            _log?.Invoke($"veil: explored cells could not be fetched ({e.Message}) — the veil stands, next map retries");
        }
        finally
        {
            _busy = false;
        }
    }
}
