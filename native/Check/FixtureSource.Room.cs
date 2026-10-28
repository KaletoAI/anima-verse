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
    private JsonElement _roomSteps;
    private int _roomStep;
    public List<string> RoomRequests { get; }=new();

    /// <summary>Task 51: independent strict enter-room queue from Task 46's table; no implicit map mutation.</summary>
    public void SelectRoomScenario(string name)
    {
        using var doc=JsonDocument.Parse(File.ReadAllBytes(PathOf("pos_answers.json")));
        _roomSteps=doc.RootElement.GetProperty("scenarios").GetProperty(name).Clone();
        _roomStep=0; RoomRequests.Clear();
    }
    public Task<PositionAnswer> EnterRoomAsync(string roomId,CancellationToken ct=default)
    {
        ct.ThrowIfCancellationRequested();
        if (_roomSteps.ValueKind!=JsonValueKind.Array || _roomStep>=_roomSteps.GetArrayLength())
            throw new InvalidOperationException("Room fixture scenario absent or exhausted");
        var step=_roomSteps[_roomStep];
        if (step.GetProperty("method").GetString()!="POST" || step.GetProperty("path").GetString()!="/play/enter-room"
            || !JsonNode.DeepEquals(JsonSerializer.SerializeToNode(new { room_id=roomId }),JsonNode.Parse(step.GetProperty("request").GetRawText())))
            throw new InvalidOperationException("Room fixture request does not match step "+_roomStep);
        _roomStep++; RoomRequests.Add(roomId);
        return Task.FromResult(new PositionAnswer(step.GetProperty("status").GetInt32(),step.GetProperty("body").Clone()));
    }
}
