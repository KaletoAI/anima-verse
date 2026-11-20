using System.Net;
using System.Net.Http;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Sync;

namespace AnimaNative.Api;

public partial interface IWorldSource
{
    /// <summary>
    /// <c>GET /characters/{name}/model/hair-strands</c> (the URL of <c>model.hair_strands</c>, docs/schnittstellen-3d.md
    /// "Hair strands"): the status, the <c>ETag</c> and the JSON body of a 2xx — 404 and 5xx come back as a status, not
    /// as an exception (the strand cache tells "none" from "later" by it). A source that does not serve it answers 404.
    /// </summary>
    Task<ConditionalAnswer> GetHairStrandRecordAsync(string url) => Task.FromResult(new ConditionalAnswer(404, "", null));
}

public sealed partial class AnimaApi
{
    public async Task<ConditionalAnswer> GetHairStrandRecordAsync(string url)
    {
        var uri = Relative(url);
        using var req = new HttpRequestMessage(HttpMethod.Get, uri);
        double start = MonotonicMs;
        using var res = await _http.SendAsync(req);
        Measurements.Add("JSON", "download", MonotonicMs - start, 1);
        string etag = res.Headers.ETag?.ToString() ?? "";
        if (res.StatusCode == HttpStatusCode.Unauthorized) await EnsureOk(res, uri.AbsolutePath);   // the lost session, announced
        if (!res.IsSuccessStatusCode) return new ConditionalAnswer((int)res.StatusCode, etag, null);
        var bytes = await res.Content.ReadAsByteArrayAsync();
        Measurements.Add("JSON", "download", 0, bytes: bytes.Length);
        using var doc = JsonDocument.Parse(bytes);
        return new ConditionalAnswer((int)res.StatusCode, etag, doc.RootElement.Clone());
    }
}
