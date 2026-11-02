using System;
using System.Threading.Tasks;
using AnimaNative.Sync;

namespace AnimaNative.Figures;

/// <summary>Main-thread debounce with at most one reload and one pending follow-up.</summary>
public sealed class ClipReloadQueue(ISyncClock clock, Func<Task> reload, Action<Exception> failed) : IDisposable
{
    private object? _timer;
    private bool _busy, _pending, _disposed;
    public void Push()
    {
        if (_disposed) return;
        _pending = true;
        clock.ClearTimeout(_timer);
        _timer = clock.SetTimeout(() => { _timer = null; if (!_busy) _ = Run(); }, 1000);
    }
    private async Task Run()
    {
        if (_disposed || !_pending) return;
        _busy = true;
        _pending = false;
        try { await reload(); }
        catch (Exception e) { if (!_disposed) failed(e); }
        finally
        {
            _busy = false;
            if (!_disposed && _pending && _timer is null) _ = Run();
        }
    }
    public void Dispose()
    {
        _disposed = true;
        clock.ClearTimeout(_timer);
        _timer = null;
    }
}
