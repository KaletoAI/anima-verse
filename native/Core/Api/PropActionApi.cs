using System.Collections.Generic;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace AnimaNative.Api;

/// <summary>Task 57 / E7-T12: the browser player-ui propActions.ts endpoints, separate from room poses.</summary>
public partial interface IWorldSource
{
    bool SupportsPropActions => false;
    Task<JsonDocument> GetPropActionsAsync() => Task.FromException<JsonDocument>(new ApiException(404,"/play/prop-actions"));
    Task<JsonDocument> GetPropActionStateAsync() => Task.FromException<JsonDocument>(new ApiException(404,"/play/prop-actions/state"));
    Task<JsonDocument> RequestPropActionAsync(string actionId,JsonElement target,string revision,string? partner=null,CancellationToken ct=default)
        => Task.FromException<JsonDocument>(new ApiException(404,"/play/prop-actions/request"));
    Task<JsonDocument> RespondPropActionAsync(string executionId,bool accept,CancellationToken ct=default)
        => Task.FromException<JsonDocument>(new ApiException(404,"/play/prop-actions/respond"));
    Task<JsonDocument> CancelPropActionAsync(string executionId,CancellationToken ct=default)
        => Task.FromException<JsonDocument>(new ApiException(404,"/play/prop-actions/cancel"));
}

/// <summary>Task 57: exact request objects shared with the strict fixture replayer; partner is absent unless supplied.</summary>
public static class PropActionRequest
{
    public static JsonElement Request(string actionId,JsonElement target,string revision,string? partner=null)
    {
        var body=new Dictionary<string,object> { ["action_id"]=actionId,["target"]=target,["revision"]=revision };
        if(partner is not null) body["partner"]=partner;
        return JsonSerializer.SerializeToElement(body);
    }
    public static JsonElement Respond(string executionId,bool accept)=>JsonSerializer.SerializeToElement(new { execution_id=executionId,accept });
    public static JsonElement Cancel(string executionId)=>JsonSerializer.SerializeToElement(new { execution_id=executionId });
}

public sealed partial class AnimaApi
{
    public bool SupportsPropActions => true;
    public Task<JsonDocument> GetPropActionsAsync()=>GetJson("/play/prop-actions");
    public Task<JsonDocument> GetPropActionStateAsync()=>GetJson("/play/prop-actions/state");
    public Task<JsonDocument> RequestPropActionAsync(string actionId,JsonElement target,string revision,string? partner=null,CancellationToken ct=default)
        =>PostPropAction("/play/prop-actions/request",PropActionRequest.Request(actionId,target,revision,partner),ct);
    public Task<JsonDocument> RespondPropActionAsync(string executionId,bool accept,CancellationToken ct=default)
        =>PostPropAction("/play/prop-actions/respond",PropActionRequest.Respond(executionId,accept),ct);
    public Task<JsonDocument> CancelPropActionAsync(string executionId,CancellationToken ct=default)
        =>PostPropAction("/play/prop-actions/cancel",PropActionRequest.Cancel(executionId),ct);
    /// <summary>Task 57: existing cookie/error/401 semantics; cancellation bounds both response headers and body.</summary>
    private async Task<JsonDocument> PostPropAction(string path,JsonElement body,CancellationToken ct)
    {
        using var deadline=CancellationTokenSource.CreateLinkedTokenSource(ct); deadline.CancelAfter(10000);
        using var request=new HttpRequestMessage(HttpMethod.Post,Relative(path))
        { Content=new StringContent(body.GetRawText(),Encoding.UTF8,"application/json") };
        using var response=await _http.SendAsync(request,HttpCompletionOption.ResponseContentRead,deadline.Token);
        return await ReadJson(response,path);
    }
}
