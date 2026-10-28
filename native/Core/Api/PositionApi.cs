using System;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Embody;
using AnimaNative.Scatter;

namespace AnimaNative.Api;

/// <summary>Task 50 / E7-T5: verbatim /play/pos wire names; monotonic sampling time and per-session sequence.</summary>
public sealed record PositionReport(double x, double z, long seq, double t_ms, string session);

/// <summary>Task 50: retain both fixture error bodies and FastAPI detail objects, including the server's sentence.</summary>
public sealed record PositionAnswer(int Status, JsonElement Body)
{
    private JsonElement Detail => Body.TryGetProperty("detail", out var d) && d.ValueKind == JsonValueKind.Object ? d : Body;
    private string Text(string key) => Detail.TryGetProperty(key, out var s) && s.ValueKind == JsonValueKind.String ? s.GetString()! : "";
    public bool Ok => Status is >= 200 and < 300 && Body.TryGetProperty("ok", out var ok) && ok.ValueKind == JsonValueKind.True;
    public string Reason => Text("reason");
    public string Message => Text("message") is { Length: > 0 } m ? m : Text("error") is { Length: > 0 } e ? e
        : Body.TryGetProperty("detail", out var d) && d.ValueKind == JsonValueKind.String ? d.GetString()! : "";
    public P2? Pos => Detail.TryGetProperty("pos", out var p) && p.ValueKind == JsonValueKind.Object
        && p.TryGetProperty("x", out var x) && x.TryGetDouble(out double xx)
        && p.TryGetProperty("z", out var z) && z.TryGetDouble(out double zz) && double.IsFinite(xx) && double.IsFinite(zz) ? new(xx, zz) : null;
    public string RoomId => Text("room_id");
}

public sealed partial class AnimaApi
{
    private readonly SemaphoreSlim _positionFlight = new(1, 1);

    /// <summary>
    /// Task 50 / E7-T5: use the existing cookie client, serialize writes, abort headers AND body after 8000 ms.
    /// Refusals are data for correction; 401 still raises the existing relogin event. Credentials never enter this body.
    /// </summary>
    public async Task<PositionAnswer> ReportPositionAsync(PositionReport report, CancellationToken ct = default)
    {
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(ct);
        deadline.CancelAfter(PositionChannel.TimeoutMs);
        await _positionFlight.WaitAsync(deadline.Token);
        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Post, Relative("/play/pos"))
            { Content = new StringContent(JsonSerializer.Serialize(report), Encoding.UTF8, "application/json") };
            using var response = await _http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, deadline.Token);
            if (response.StatusCode == HttpStatusCode.Unauthorized) Unauthorized?.Invoke();
            var bytes = await response.Content.ReadAsByteArrayAsync(deadline.Token);
            using var doc = JsonDocument.Parse(bytes);
            return new((int)response.StatusCode, doc.RootElement.Clone());
        }
        finally { _positionFlight.Release(); }
    }
}
