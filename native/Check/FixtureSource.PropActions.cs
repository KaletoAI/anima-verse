using System;
using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;

namespace AnimaNative.Check;

public sealed partial class FixtureSource
{
    public bool SupportsPropActions => File.Exists(Path.Combine(_dir,"answers.json"));
    private JsonElement _propSteps;
    private int _propStep;
    public bool PropScenarioComplete=>_propSteps.ValueKind==JsonValueKind.Array && _propStep==_propSteps.GetArrayLength();
    /// <summary>Task 57: select one Task 56 lifecycle; no implicit clock, mutation, retry or exhausted-table fallback.</summary>
    public void SelectPropActionScenario(string name)
    {
        using var doc=JsonDocument.Parse(File.ReadAllBytes(PathOf("answers.json")));
        if(doc.RootElement.GetProperty("format").GetString()!="anima-prop-action-answers/1") throw new InvalidDataException("Prop-action answer format");
        _propSteps=doc.RootElement.GetProperty("scenarios").GetProperty(name).Clone(); _propStep=0;
    }
    private JsonDocument PropStep(string method,string path,JsonElement? body=null)
    {
        if(_propSteps.ValueKind!=JsonValueKind.Array || _propStep>=_propSteps.GetArrayLength())
            throw new InvalidOperationException("Prop-action scenario absent or exhausted");
        var step=_propSteps[_propStep];
        if(step.GetProperty("method").GetString()!=method || step.GetProperty("path").GetString()!=path
            || !JsonNode.DeepEquals(body is { } b ? JsonNode.Parse(b.GetRawText()) : null,JsonNode.Parse(step.GetProperty("request").GetRawText())))
            throw new InvalidOperationException($"Prop-action request mismatch at step {_propStep}: {method} {path}");
        _propStep++;
        var doc=step.TryGetProperty("body_file",out var file) ? JsonDocument.Parse(File.ReadAllBytes(Path.Combine(_dir,file.GetString()!)))
            : JsonDocument.Parse(step.GetProperty("body").GetRawText());
        int status=step.GetProperty("status").GetInt32();
        if(status is >=200 and <300) return doc;
        using(doc) throw new ApiException(status,path,doc.RootElement.TryGetProperty("detail",out var detail) ? detail.ToString() : doc.RootElement.ToString());
    }
    public Task<JsonDocument> GetPropActionsAsync()=>Task.FromResult(PropStep("GET","/play/prop-actions"));
    public Task<JsonDocument> GetPropActionStateAsync()=>Task.FromResult(PropStep("GET","/play/prop-actions/state"));
    public Task<JsonDocument> RequestPropActionAsync(string actionId,JsonElement target,string revision,string? partner=null,CancellationToken ct=default)
    { ct.ThrowIfCancellationRequested(); return Task.FromResult(PropStep("POST","/play/prop-actions/request",PropActionRequest.Request(actionId,target,revision,partner))); }
    public Task<JsonDocument> RespondPropActionAsync(string executionId,bool accept,CancellationToken ct=default)
    { ct.ThrowIfCancellationRequested(); return Task.FromResult(PropStep("POST","/play/prop-actions/respond",PropActionRequest.Respond(executionId,accept))); }
    public Task<JsonDocument> CancelPropActionAsync(string executionId,CancellationToken ct=default)
    { ct.ThrowIfCancellationRequested(); return Task.FromResult(PropStep("POST","/play/prop-actions/cancel",PropActionRequest.Cancel(executionId))); }
}
