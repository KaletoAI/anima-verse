using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace AnimaNative.Api;

public sealed partial class AnimaApi
{
    /// <summary>Task 52 / E7-T7: api.ts getPlaces, using the existing authenticated cookie session.</summary>
    public Task<JsonDocument> GetPlacesAsync() => GetJson("/play/places");

    /// <summary>Task 52: activity payload unchanged; bound headers/body to 10 seconds and retain refusal text.</summary>
    public async Task<PositionAnswer> PostActivityAsync(JsonElement body, CancellationToken ct=default)
    {
        using var deadline=CancellationTokenSource.CreateLinkedTokenSource(ct);
        deadline.CancelAfter(10000);
        using var request=new HttpRequestMessage(HttpMethod.Post,Relative("/play/self/activity"))
        { Content=new StringContent(body.GetRawText(),Encoding.UTF8,"application/json") };
        using var response=await _http.SendAsync(request,HttpCompletionOption.ResponseHeadersRead,deadline.Token);
        if(response.StatusCode==HttpStatusCode.Unauthorized) Unauthorized?.Invoke();
        var bytes=await response.Content.ReadAsByteArrayAsync(deadline.Token);
        using var doc=JsonDocument.Parse(bytes.Length==0 ? "{}" : Encoding.UTF8.GetString(bytes));
        return new((int)response.StatusCode,doc.RootElement.Clone());
    }
}
