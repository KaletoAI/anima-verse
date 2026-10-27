using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Figures;
using AnimaNative.Scene;
using Godot;
using Json = AnimaNative.World.Json;

namespace AnimaNative;

public partial class Main : Node3D
{
    private JsonElement[] _propOffers = Array.Empty<JsonElement>();
    private JsonElement[] _roomPlaces = Array.Empty<JsonElement>();
    private string? _menuPlaceId;
    private Vector2 _menuPoint;
    private int _actionEpoch;
    private bool _actionRefreshBusy, _actionRefreshAgain;
    private bool _ownedApproaching;
    private long _offerFetchSerial;
    private double _nextMotionRefreshMs, _motionBurstUntilMs;
    private readonly HashSet<string> _propActionBarriers = new(StringComparer.Ordinal);
    private readonly HashSet<string> _completedPropActionBarriers = new(StringComparer.Ordinal);
    private TaskCompletionSource? _actionRefreshCompletion;
    private readonly Dictionary<string, object?> _propActionBarrierLeases = new(StringComparer.Ordinal);

    private async Task PreparePropActionAsync(string requestId)
    {
        bool pending = _positionBusy;
        try
        {
            await _controlPreparation;
            await _positionWrite;
            if (pending && _positionWriteError is { } failure) throw new InvalidOperationException(failure);
            if (!Leaving && !_stop.IsCancellationRequested) _hud?.SendPropActionPrepared(requestId);
        }
        catch (Exception error)
        {
            if (!Leaving) _hud?.SendPropActionPrepared(requestId, error.Message);
        }
    }

    private void TickPropActionRefresh()
    {
        if (!_interactive || Leaving || _api is null || _actionRefreshBusy || _figures is null) return;
        double now = Time.GetTicksMsec();
        if (now < _nextMotionRefreshMs || !(_ownedApproaching || _figures.HasSemanticMotion || now < _motionBurstUntilMs)) return;
        _nextMotionRefreshMs = now + 150;
        _ = RefreshActionViewAsync();
    }

    private void AttachPropActions()
    {
        if (_hud is not { } hud) return;
        hud.Handlers["closePlaceMenu"] = _ => ClosePlaceMenu();
        hud.Handlers["pickPropAction"] = args => _ = MutatePropActionAsync(async api =>
        {
            if (Arg(args, 0) is not { } action || args.Count < 3 || args[1] is not JsonObject target
                || Arg(args, 2) is not { } revision) throw new ArgumentException("Action, exact target and revision required");
            using var doc = JsonDocument.Parse(target.ToJsonString());
            return await api.RequestPropActionAsync(action, doc.RootElement, revision, Arg(args, 3));
        });
        hud.Handlers["respondPropAction"] = args => _ = MutatePropActionAsync(api =>
            api.RespondPropActionAsync(Arg(args, 0) ?? throw new ArgumentException("Execution required"),
                args.Count > 1 && args[1] is JsonValue accept && accept.TryGetValue<bool>(out var yes) && yes));
        hud.Handlers["cancelPropAction"] = args => _ = MutatePropActionAsync(api =>
            api.CancelPropActionAsync(Arg(args, 0) ?? throw new ArgumentException("Execution required")));
        hud.Handlers["pickRoomPose"] = args => _ = MutatePropActionAsync(api =>
        {
            string id = Arg(args, 0) ?? "", pose = Arg(args, 1) ?? "";
            // Furniture never uses this path; freebody poses are validated by the canonical body endpoint.
            if (id.Length > 0 && !_roomPlaces.Any(p => Json.Str(p, "id") == id && p.TryGetProperty("poses", out var poses)
                && poses.EnumerateArray().Any(q => Json.Str(q, "key") == pose)))
                throw new InvalidOperationException("Room pose offer expired");
            return api.SetRoomPoseAsync(id, pose);
        });
        hud.Handlers["enterEmbodied"] = args => _ = EnterNativeControlAsync();
        hud.Handlers["takeControl"] = args => _ = EnterNativeControlAsync();
        hud.Handlers["exitEmbodied"] = _ => ExitNativeControl();
        hud.PropActionPrepare = requestId =>
        {
            _propActionBarriers.Add(requestId); // synchronous: no further manual step or position publication can start
            if (_propActionBarrierLeases.Remove(requestId, out var oldLease)) _timers.ClearTimeout(oldLease);
            _propActionBarrierLeases[requestId] = _timers.SetTimeout(() =>
            {
                if (Leaving || _stop.IsCancellationRequested) return;
                // A lost HUD/finally cannot strand input: expiry still requires a fresh canonical read before release.
                _completedPropActionBarriers.Add(requestId);
                _actionEpoch++;
                _ = RefreshActionViewAsync();
            }, 10_000);
            _ = PreparePropActionAsync(requestId);
        };
        hud.PropActionsChanged = requestId =>
        {
            if (requestId is not null) _completedPropActionBarriers.Add(requestId);
            _actionEpoch++;
            _motionBurstUntilMs = Time.GetTicksMsec() + 5000;
            _ = RefreshActionViewAsync();
        };
    }

    private async Task MutatePropActionAsync(Func<AnimaApi, Task<JsonDocument>> mutate)
    {
        if (_api is not { } api || Leaving) return;
        try
        {
            ExitNativeControl();
            await _controlPreparation;
            await _positionWrite;
            using var answer = await mutate(api);
            if (Json.Str(answer.RootElement, "status") == "refused")
                throw new InvalidOperationException(Json.Str(answer.RootElement, "reason", "Action refused"));
            ClosePlaceMenu();
            _actionEpoch++;
            _motionBurstUntilMs = Time.GetTicksMsec() + 5000;
            await RefreshActionViewAsync();
            _hud?.NotifyPropActionsChanged();
        }
        catch (Exception error)
        {
            _hud?.SendUi("toast", JsonValue.Create(error.Message), JsonValue.Create(true));
            await RefreshActionViewAsync();
        }
    }

    private async Task FetchActionOffersAsync()
    {
        if (_api is not { } api) return;
        if (_figures is { AvatarName.Length: 0 })
        {
            _propOffers = _roomPlaces = Array.Empty<JsonElement>();
            _ownedApproaching = false;
            ClosePlaceMenu();
            return;
        }
        int epoch = _actionEpoch;
        long serial = ++_offerFetchSerial;
        // Always fresh, including blocked offers: people, claims, variants and definitions can all change without seating.
        var offersTask = api.GetPropActionsAsync();
        var placesTask = api.GetPlacesAsync();
        var stateTask = api.GetPropActionStateAsync();
        using var offers = await offersTask;
        using var places = await placesTask;
        using var state = await stateTask;
        if (Leaving || _stop.IsCancellationRequested || epoch != _actionEpoch || serial != _offerFetchSerial) return;
        _ownedApproaching = state.RootElement.TryGetProperty("current", out var current)
            && current.EnumerateArray().Any(run => Json.Str(run, "status") == "approaching");
        if (_controlReady && current.ValueKind == JsonValueKind.Array && current.GetArrayLength() > 0)
            ExitNativeControl();
        _propOffers = offers.RootElement.ValueKind == JsonValueKind.Array
            ? offers.RootElement.EnumerateArray().Select(x => x.Clone()).ToArray() : Array.Empty<JsonElement>();
        _roomPlaces = places.RootElement.TryGetProperty("places", out var list)
            ? list.EnumerateArray().Select(x => x.Clone()).ToArray() : Array.Empty<JsonElement>();
        if (_menuPlaceId is not null) PublishPlaceMenu();
    }

    private async Task RefreshActionViewAsync()
    {
        if (_actionRefreshBusy)
        {
            _actionRefreshAgain = true;
            if (_actionRefreshCompletion is { } waiting) await waiting.Task;
            return;
        }
        _actionRefreshBusy = true;
        var completion = _actionRefreshCompletion = new TaskCompletionSource();
        try
        {
            do
            {
                _actionRefreshAgain = false;
                var polled = await FetchWorldMapAsync();
                if (!Leaving && !_stop.IsCancellationRequested && polled.ActionEpoch == _actionEpoch
                    && polled.ViewRev == _viewRev && !_viewSwitchBusy && _figures is not null)
                {
                    ApplyWorldMap(polled);
                }
            } while (_actionRefreshAgain && !Leaving && !_stop.IsCancellationRequested);
        }
        catch (Exception error)
        {
            if (!Leaving) _hud?.SendUi("toast", JsonValue.Create(error.Message), JsonValue.Create(true));
        }
        finally
        {
            _actionRefreshBusy = false;
            _actionRefreshCompletion = null;
            completion.SetResult();
        }
    }

    private void ClosePlaceMenu()
    {
        _menuPlaceId = null;
        _hud?.SetState("placeMenu", null);
    }

    private PlaceEntry? MenuEntry(string id)
    {
        if (_builder is null || _figures?.LatestMap is not { } map) return null;
        string loc = AnimaNative.World.Anchor.AvatarLocation(map) ?? "";
        return _builder.Slots.TryGetValue(loc, out var slot)
            && slot.Places.Markers.TryGetValue(_avatarRoom, out var markers) ? markers.GetValueOrDefault(id) : null;
    }

    private void PublishPlaceMenu()
    {
        if (_menuPlaceId is not { } id || MenuEntry(id) is not { } entry) { ClosePlaceMenu(); return; }
        var raw = _roomPlaces.FirstOrDefault(p => Json.Str(p, "id") == id);
        var offer = raw.ValueKind == JsonValueKind.Object ? JsonNode.Parse(raw.GetRawText())!.AsObject()
            : new JsonObject { ["id"] = id, ["label"] = id, ["group"] = entry.Group,
                ["free"] = 0, ["free_slots"] = new JsonArray(), ["poses"] = new JsonArray() };
        var semantic = new JsonArray();
        foreach (var action in PlaceSlots.PropActionsFor(entry, _propOffers)) semantic.Add(JsonNode.Parse(action.GetRawText()));
        if (entry.Fixed)
        {
            offer["prop_actions"] = semantic;
            offer["poses"] = new JsonArray();
        }
        _hud?.SetState("placeMenu", new JsonObject { ["x"] = _menuPoint.X, ["y"] = _menuPoint.Y, ["offer"] = offer });
    }

    private bool PickPropMenu(Vector2 click, Vector3 origin, Vector3 direction)
    {
        if (_figures?.LatestMap is not { } map || _builder is null) return false;
        string loc = AnimaNative.World.Anchor.AvatarLocation(map) ?? "";
        if (!_builder.Slots.TryGetValue(loc, out var slot) || !slot.Places.Markers.TryGetValue(_avatarRoom, out var entries)) return false;
        PlaceEntry? hit = null;
        float closest = float.PositiveInfinity;
        foreach (var entry in entries.Values)
        {
            foreach (var point in entry.Slots)
            {
                var p = new Vector3((float)point.X, (float)point.Y, (float)point.Z);
                float t = (p - origin).Dot(direction);
                if (t <= 0 || t >= closest || (origin + direction * t).DistanceSquaredTo(p) > 0.65f * 0.65f) continue;
                hit = entry; closest = t;
            }
        }
        if (hit is null) { ClosePlaceMenu(); return false; }
        _menuPlaceId = hit.Id;
        _menuPoint = _hud?.WindowToCss(click) ?? click;
        PublishPlaceMenu();
        return true;
    }
}
