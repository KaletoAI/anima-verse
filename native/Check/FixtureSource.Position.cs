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
    private JsonElement _positionSteps;
    private int _positionStep;
    public List<PositionReport> PositionRequests { get; } = new();

    /// <summary>Task 50 / E7-T5: choose the Task 46 table explicitly; exhausted/unknown/mismatched writes fail.</summary>
    public void SelectPositionScenario(string name)
    {
        using var doc = JsonDocument.Parse(File.ReadAllBytes(PathOf("pos_answers.json")));
        _positionSteps = doc.RootElement.GetProperty("scenarios").GetProperty(name).Clone();
        _positionStep = 0; PositionRequests.Clear();
    }

    public Task<PositionAnswer> ReportPositionAsync(PositionReport report, CancellationToken ct = default)
    {
        ct.ThrowIfCancellationRequested();
        if (_positionSteps.ValueKind != JsonValueKind.Array || _positionStep >= _positionSteps.GetArrayLength())
            throw new InvalidOperationException("Position fixture scenario absent or exhausted");
        var step = _positionSteps[_positionStep];
        if (step.GetProperty("method").GetString() != "POST" || step.GetProperty("path").GetString() != "/play/pos"
            || !JsonNode.DeepEquals(JsonSerializer.SerializeToNode(report), JsonNode.Parse(step.GetProperty("request").GetRawText())))
            throw new InvalidOperationException("Position fixture request does not match step " + _positionStep);
        _positionStep++; PositionRequests.Add(report);
        return Task.FromResult(new PositionAnswer(step.GetProperty("status").GetInt32(), step.GetProperty("body").Clone()));
    }
}
