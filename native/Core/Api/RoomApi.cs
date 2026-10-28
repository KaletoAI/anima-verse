using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Embody;

namespace AnimaNative.Api;

public sealed partial class AnimaApi
{
    /// <summary>Task 51 / E7-T6: api.ts enterRoom, verbatim {room_id}; cookie session, 10 s headers/body deadline.</summary>
    public async Task<PositionAnswer> EnterRoomAsync(string roomId, CancellationToken ct=default)
    {
        using var deadline=CancellationTokenSource.CreateLinkedTokenSource(ct);
        deadline.CancelAfter(RoomEntryChannel.TimeoutMs);
        using var request=new HttpRequestMessage(HttpMethod.Post,Relative("/play/enter-room"))
        { Content=new StringContent(JsonSerializer.Serialize(new { room_id=roomId }),Encoding.UTF8,"application/json") };
        using var response=await _http.SendAsync(request,HttpCompletionOption.ResponseHeadersRead,deadline.Token);
        if (response.StatusCode==HttpStatusCode.Unauthorized) Unauthorized?.Invoke();
        // enterRoom in the browser accepts any 2xx; a successful response need not contain a JSON body.
        var bytes=await response.Content.ReadAsByteArrayAsync(deadline.Token);
        using var doc=JsonDocument.Parse(bytes.Length==0 ? "{}" : Encoding.UTF8.GetString(bytes));
        return new((int)response.StatusCode,doc.RootElement.Clone());
    }
}
