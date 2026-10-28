using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;

namespace AnimaNative.Check;

public sealed partial class FixtureSource
{
    private JsonElement _placeSteps;
    private int _placeStep;
    public List<JsonObject> ActivityRequests { get; }=new();
    /// <summary>Task 52 check barrier: expose pending-write stale gating without a network socket.</summary>
    public Task? ActivityBarrier { get; set; }
    public Task? PlacesBarrier { get; set; }

    /// <summary>Task 52: strict Task 46 places/activity answer table, independent of room and position queues.</summary>
    public void SelectPlaceScenario(string name)
    {
        using var doc=JsonDocument.Parse(File.ReadAllBytes(PathOf("pos_answers.json")));
        _placeSteps=doc.RootElement.GetProperty("scenarios").GetProperty(name).Clone();
        _placeStep=0; ActivityRequests.Clear();
    }
    private JsonElement PlaceStep(string method,string path,JsonNode? request)
    {
        if(_placeSteps.ValueKind!=JsonValueKind.Array || _placeStep>=_placeSteps.GetArrayLength())
            throw new InvalidOperationException("Place fixture scenario absent or exhausted");
        var step=_placeSteps[_placeStep];
        if(step.GetProperty("method").GetString()!=method || step.GetProperty("path").GetString()!=path
            || !JsonNode.DeepEquals(request,JsonNode.Parse(step.GetProperty("request").GetRawText())))
            throw new InvalidOperationException("Place fixture request does not match step "+_placeStep);
        _placeStep++; return step;
    }
    public async Task<JsonDocument> GetPlacesAsync()
    {
        // General fixture checks do not select an interactive scenario and never synthesize availability.
        if(_placeSteps.ValueKind!=JsonValueKind.Array) return JsonDocument.Parse("{\"room_id\":\"\",\"places\":[]}");
        var step=PlaceStep("GET","/play/places",null);
        if(step.GetProperty("status").GetInt32()!=200) throw new ApiException(step.GetProperty("status").GetInt32(),"/play/places");
        if(PlacesBarrier is { } barrier) await barrier;
        return JsonDocument.Parse(step.GetProperty("body").GetRawText());
    }
    public async Task<PositionAnswer> PostActivityAsync(JsonElement body,CancellationToken ct=default)
    {
        ct.ThrowIfCancellationRequested();
        var request=JsonNode.Parse(body.GetRawText())!.AsObject();
        var step=PlaceStep("POST","/play/self/activity",request);
        ActivityRequests.Add(request);
        if(ActivityBarrier is { } barrier) await barrier.WaitAsync(ct);
        return new PositionAnswer(step.GetProperty("status").GetInt32(),step.GetProperty("body").Clone());
    }
}
