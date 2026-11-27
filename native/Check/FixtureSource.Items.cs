using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;

namespace AnimaNative.Check;

public sealed partial class FixtureSource
{
    public List<string> LocationItemsRequests { get; } = new();
    public List<string> ApproachItemRequests { get; } = new();
    public List<string> PickupItemRequests { get; } = new();
    public List<(string ItemId, string ActionId)> RoomItemActionRequests { get; } = new();

    public Func<string, JsonDocument?>? LocationItemsProvider { get; set; }
    public Func<string, JsonDocument>? ApproachItemHandler { get; set; }
    public Func<string, JsonDocument>? PickupItemHandler { get; set; }
    public Func<string, string, JsonDocument>? RoomItemActionHandler { get; set; }

    public Task<JsonDocument?> GetLocationItemsAsync(string locationId)
    {
        LocationItemsRequests.Add(locationId);
        return Task.FromResult(LocationItemsProvider?.Invoke(locationId));
    }

    public Task<JsonDocument> ApproachRoomItemAsync(string itemId, CancellationToken ct = default)
    {
        ct.ThrowIfCancellationRequested();
        ApproachItemRequests.Add(itemId);
        if (ApproachItemHandler is { } handler)
            return Task.FromResult(handler(itemId));
        return Task.FromException<JsonDocument>(new ApiException(404, "/play/room-item/approach", "Item not here"));
    }

    public Task<JsonDocument> PickupRoomItemAsync(string itemId, CancellationToken ct = default)
    {
        ct.ThrowIfCancellationRequested();
        PickupItemRequests.Add(itemId);
        if (PickupItemHandler is { } handler)
            return Task.FromResult(handler(itemId));
        return Task.FromException<JsonDocument>(new ApiException(404, "/play/pickup", "Item not here"));
    }

    public Task<JsonDocument> RunRoomItemActionAsync(string itemId, string actionId, CancellationToken ct = default)
    {
        ct.ThrowIfCancellationRequested();
        RoomItemActionRequests.Add((itemId, actionId));
        if (RoomItemActionHandler is { } handler)
            return Task.FromResult(handler(itemId, actionId));
        return Task.FromException<JsonDocument>(new ApiException(404, "/play/room-item/action", "Item not here"));
    }
}
