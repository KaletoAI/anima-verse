using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Figures;
using AnimaNative.Orders;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Embody;

/// <summary>
/// Task 10: world-placeable room items glue on <see cref="AvatarOffersController"/> —
/// refetches <c>GET /play/locations/{id}/items</c> on mount, location/room change, sync topic <c>"self"</c>, and after
/// actions; gates aura, ray picking, hover highlight and F-key nearest-offer to the avatar's confirmed room; walks to
/// <c>POST /play/room-item/approach</c> via the normal click walk and triggers <c>take</c> / <c>read</c> / package
/// actions only on arrival.
/// </summary>
public sealed partial class AvatarOffersController
{
    private sealed class ItemWalkWatch(int seq, P2 goal, string? orderId)
    {
        public readonly int Seq = seq;
        public readonly P2 Goal = goal;
        public string? OrderId = orderId;
        public bool OrderReachedLoop;
        public readonly TaskCompletionSource<bool> Completion = new();
    }

    private Task? _itemsRefresh;
    private bool _itemsRefreshAgain;
    private string _lastItemsLoc = "";
    private string _lastItemsRoom = "";
    private int _itemActionSeq;
    private ItemWalkWatch? _activeItemWalk;
    private LocationSlot? _hoveredItemSlot;
    private (string RoomId, string ItemId)? _hoveredItemKey;

    public Task? PendingItems { get; private set; }
    public Task? PendingItemAction { get; private set; }
    public bool HasItemHover { get; private set; }

    private bool AnyMenuOrOverlayOpen =>
        _hud.Ui.MenuOpen
        || _hud.Ui.OverlayOpen
        || _hud.SceneOwned("placeMenu") is not null
        || _hud.SceneOwned("itemMenu") is not null;

    /// <summary>Distance in metres to the nearest visible item in the avatar's confirmed room, or null.</summary>
    public double? NearestItemOfferDistance
        => CanUse && !AnyMenuOrOverlayOpen && FindNearestConfirmedItem() is { } nearest ? nearest.Dist : null;

    private void AttachItems()
    {
        _hud.Handlers["pickItemAction"] = PickItemActionHandler;
        _hud.Handlers["closeItemMenu"] = CloseItemMenuHandler;
        _hud.Handlers["openNearestItemMenu"] = OpenNearestItemMenuHandler;
        _hud.ItemOfferDistance = () => NearestItemOfferDistance;
        _world.Ready += OnItemSlotReady;
        _world.Remounted += OnItemSlotRemounted;
        _position.RoomChanged += OnItemRoomChanged;
        _figures.OrderFrameShown += OnItemOrderFrameShown;
        _figures.AfterTick += OnItemAfterTick;

        if (_world.Slots.Values.Any(s => s.Ready && s.Ring == Ring.Near && s.Items is { IsMounted: true }))
            PendingItems = RefreshItemsAsync();
    }

    private void DetachItems()
    {
        CancelPendingItemWalk();
        ClearItemHover();
        _hud.SetState("itemMenu", null);
        _hud.ItemOfferDistance = null;
        _hud.Handlers.Remove("pickItemAction");
        _hud.Handlers.Remove("closeItemMenu");
        _hud.Handlers.Remove("openNearestItemMenu");
        _world.Ready -= OnItemSlotReady;
        _world.Remounted -= OnItemSlotRemounted;
        _position.RoomChanged -= OnItemRoomChanged;
        _figures.OrderFrameShown -= OnItemOrderFrameShown;
        _figures.AfterTick -= OnItemAfterTick;
    }

    private void DeactivateItems()
    {
        CancelPendingItemWalk();
        ClearItemHover();
        _hud.SetState("itemMenu", null);
    }

    /// <summary>Push signal (<c>sync</c> topic <c>"self"</c>) or explicit external invalidation.</summary>
    public void NotifyItemsChanged()
    {
        if (_disposed || Suspended) return;
        PendingItems = RefreshItemsAsync();
    }

    private void OnItemSlotReady(LocationSlot slot)
    {
        if (_disposed || Suspended || slot.Items is not { IsMounted: true }) return;
        PendingItems = RefreshItemsAsync();
    }

    private void OnItemSlotRemounted(LocationSlot previous, LocationSlot current)
    {
        if (_hoveredItemSlot == previous) ClearItemHover();
        if (!_disposed && !Suspended && current.Items is { IsMounted: true })
            PendingItems = RefreshItemsAsync();
    }

    private void OnItemSlotDropped(LocationSlot slot)
    {
        if (_hoveredItemSlot == slot) ClearItemHover();
        var (locId, _) = ConfirmedWhere();
        if (slot.Loc.Id == locId)
        {
            CancelPendingItemWalk();
            _hud.SetState("itemMenu", null);
        }
    }

    private void OnItemRoomChanged()
    {
        if (_disposed || Suspended) return;
        SyncItemsConfirmedRooms();
        PendingItems = RefreshItemsAsync();
    }

    private void SyncItemsWhere()
    {
        if (_disposed || Suspended) return;
        var (loc, room) = ConfirmedWhere();
        SyncItemsConfirmedRooms();
        if (loc != _lastItemsLoc || room != _lastItemsRoom)
            PendingItems = RefreshItemsAsync();
    }

    private (string LocId, string RoomId) ConfirmedWhere()
    {
        if (_position.LocationId.Length > 0)
            return (_position.LocationId, _position.RoomId);
        if (Map is { } map && Self(map) is { } me)
        {
            string loc = Text(me, "location_id");
            string room = _steering.RoomId.Length > 0 ? _steering.RoomId : Text(me, "room_id");
            return (loc, room);
        }
        return ("", _steering.RoomId);
    }

    private void SyncItemsConfirmedRooms()
    {
        var (loc, room) = ConfirmedWhere();
        foreach (var slot in _world.Slots.Values)
        {
            if (slot.Items is not { IsMounted: true } layer) continue;
            layer.SetConfirmedRoom(slot.Loc.Id == loc ? room : null);
        }
        if (_hud.SceneOwned("itemMenu") is not null)
        {
            if (loc.Length == 0 || _world.Slots.GetValueOrDefault(loc) is not { Ready: true, Ring: Ring.Near, Items: { IsMounted: true } activeLayer })
                _hud.SetState("itemMenu", null);
            else
                RefreshOpenItemMenu(activeLayer);
        }
    }

    public Task RefreshItemsAsync()
    {
        if (_disposed || Suspended) return Task.CompletedTask;
        if (_itemsRefresh is { IsCompleted: false })
        {
            _itemsRefreshAgain = true;
            return _itemsRefresh;
        }
        return _itemsRefresh = RunItemsRefreshLoopAsync();
    }

    private async Task RunItemsRefreshLoopAsync()
    {
        do
        {
            _itemsRefreshAgain = false;
            await RefreshItemsOnceAsync();
        } while (!_disposed && !Suspended && _itemsRefreshAgain);
    }

    private async Task RefreshItemsOnceAsync()
    {
        var (confirmedLoc, confirmedRoom) = ConfirmedWhere();
        _lastItemsLoc = confirmedLoc;
        _lastItemsRoom = confirmedRoom;

        var nearSlots = _world.Slots.Values
            .Where(s => s.Ready && s.Ring == Ring.Near && s.Items is { IsMounted: true })
            .ToArray();

        foreach (var slot in nearSlots)
        {
            if (_disposed || Suspended) return;
            if (slot.Items is not { IsMounted: true } preLayer) continue;
            preLayer.SetConfirmedRoom(slot.Loc.Id == confirmedLoc ? confirmedRoom : null);

            try
            {
                using var doc = await _source.GetLocationItemsAsync(slot.Loc.Id);
                if (_disposed || Suspended) return;
                if (!_world.Slots.TryGetValue(slot.Loc.Id, out var current)
                    || !ReferenceEquals(current, slot)
                    || !slot.Ready
                    || slot.Ring != Ring.Near
                    || slot.Items is not { IsMounted: true } layer)
                    continue;

                var (nowLoc, nowRoom) = ConfirmedWhere();
                layer.SetConfirmedRoom(slot.Loc.Id == nowLoc ? nowRoom : null);
                if (doc is not null)
                {
                    var items = ItemPayload.Parse(doc.RootElement);
                    await layer.Apply(items);
                    if (_disposed) return;
                    if (slot.Loc.Id == nowLoc) RefreshOpenItemMenu(layer);
                }
            }
            catch (Exception e)
            {
                if (!_disposed && slot.Loc.Id == confirmedLoc)
                    GD.Print($"[native] [items] refresh {slot.Loc.Id} failed: {e.Message}");
            }
        }
    }

    private void RefreshOpenItemMenu(ItemsLayer layer)
    {
        if (_hud.SceneOwned("itemMenu") is not JsonObject menu
            || menu["item"]?["item_id"]?.GetValue<string>() is not { Length: > 0 } openId)
            return;

        var fresh = layer.Items.FirstOrDefault(i => i.ItemId == openId && layer.IsInConfirmedRoom(i.RoomId));
        if (fresh is null)
        {
            _hud.SetState("itemMenu", null);
            return;
        }

        var updated = (JsonObject)menu.DeepClone();
        updated["item"] = MenuItemJson(fresh);
        _hud.SetState("itemMenu", updated);
    }

    private (WorldItem Item, double Distance, LocationSlot Slot)? HitConfirmedItem(Vec3 origin, Vec3 direction)
    {
        var (locId, roomId) = ConfirmedWhere();
        if (locId.Length == 0 || roomId.Length == 0) return null;
        if (_world.Slots.GetValueOrDefault(locId) is not { Ready: true, Ring: Ring.Near, Items: { IsMounted: true } layer } slot)
            return null;
        layer.SetConfirmedRoom(roomId);
        if (layer.HitDetail(origin, direction, item => layer.IsInConfirmedRoom(item.RoomId)) is not { } hit)
            return null;
        return (hit.Item, hit.Distance, slot);
    }

    private double? HitSemanticPropDistance(Vec3 origin, Vec3 direction)
    {
        if (HitSemanticProp(origin, direction) is not { } prop) return null;
        var o = new Vector3((float)origin.X, (float)origin.Y, (float)origin.Z);
        return (prop.Point - o).Length();
    }

    private bool TryPickConfirmedItem(Vec3 origin, Vec3 direction, Vector2 viewport)
    {
        if (!CanUse || AnyMenuOrOverlayOpen) return false;
        if (HitConfirmedItem(origin, direction) is not { } hit) return false;
        double? propDist = HitSemanticPropDistance(origin, direction);
        if (propDist is double pd && pd < hit.Distance - 0.02) return false;
        OpenItemMenuAt(hit.Item, viewport);
        return true;
    }

    private bool TryHoverConfirmedItem(Vec3 origin, Vec3 direction, double? propDist)
    {
        if (!CanUse || AnyMenuOrOverlayOpen) return false;
        if (HitConfirmedItem(origin, direction) is not { } hit) return false;
        if (propDist is double pd && pd < hit.Distance - 0.02) return false;
        Places.ClearHover();
        HasPropHover = false;
        SetItemHover(hit.Slot, hit.Item);
        return true;
    }

    private void SetItemHover(LocationSlot slot, WorldItem item)
    {
        var key = (item.RoomId, item.ItemId);
        if (_hoveredItemSlot == slot && _hoveredItemKey == key && HasItemHover) return;
        ClearItemHover();
        _hoveredItemSlot = slot;
        _hoveredItemKey = key;
        HasItemHover = true;
        slot.Items?.SetHovered(item.RoomId, item.ItemId);
    }

    private void ClearItemHover()
    {
        if (_hoveredItemSlot?.Items is { IsMounted: true } layer)
            layer.SetHovered(null, null);
        _hoveredItemSlot = null;
        _hoveredItemKey = null;
        HasItemHover = false;
    }

    private (WorldItem Item, double Dist, LocationSlot Slot)? FindNearestConfirmedItem()
    {
        if (Avatar is not { } avatar) return null;
        var (locId, roomId) = ConfirmedWhere();
        if (locId.Length == 0 || roomId.Length == 0) return null;
        if (_world.Slots.GetValueOrDefault(locId) is not { Ready: true, Ring: Ring.Near, Items: { IsMounted: true } layer } slot)
            return null;

        layer.SetConfirmedRoom(roomId);
        WorldItem? best = null;
        double bestDist = double.PositiveInfinity;
        foreach (var item in layer.Items)
        {
            if (!layer.IsInConfirmedRoom(item.RoomId)) continue;
            if (layer.GetItemNode(item.RoomId, item.ItemId) is not { Visible: true } node) continue;
            if (node.IsInsideTree() && !node.IsVisibleInTree()) continue;

            var anchor = layer.WorldAnchorOf(item);
            double d = double.Hypot(anchor.X - avatar.Position.X, anchor.Z - avatar.Position.Z);
            if (!double.IsFinite(d) || d < 0) continue;
            if (d < bestDist || (d == bestDist && best is not null && string.CompareOrdinal(item.ItemId, best.ItemId) < 0))
            {
                best = item;
                bestDist = d;
            }
        }

        return best is null ? null : (best, bestDist, slot);
    }

    private void OpenNearestItemMenuHandler(JsonArray _)
    {
        if (!CanUse || AnyMenuOrOverlayOpen) return;
        if (FindNearestConfirmedItem() is not { } nearest) return;

        Vector2 viewportPt = new(640, 360);
        if (_figures.GetViewport() is { } vp)
        {
            var anchor = nearest.Slot.Items!.WorldAnchorOf(nearest.Item);
            var worldPos = new Vector3((float)anchor.X, (float)(anchor.Y + nearest.Item.SizeM * 0.5), (float)anchor.Z);
            if (vp.GetCamera3D() is { } cam && !cam.IsPositionBehind(worldPos))
                viewportPt = cam.UnprojectPosition(worldPos);
            else
                viewportPt = vp.GetVisibleRect().Size * 0.5f;
        }
        OpenItemMenuAt(nearest.Item, viewportPt);
    }

    private void OpenItemMenuAt(WorldItem item, Vector2 viewport)
    {
        ClearHover();
        var css = _hud.ViewportToCss(viewport);
        _hud.SetState("itemMenu", new JsonObject
        {
            ["x"] = (double)css.X,
            ["y"] = (double)css.Y,
            ["item"] = MenuItemJson(item),
        });
    }

    private static JsonObject MenuItemJson(WorldItem item)
    {
        var actions = new JsonArray();
        foreach (var a in item.Actions)
        {
            var entry = new JsonObject
            {
                ["id"] = a.Id,
                ["label"] = a.Label,
            };
            if (a.Source.Length > 0) entry["source"] = a.Source;
            actions.Add(entry);
        }
        return new JsonObject
        {
            ["item_id"] = item.ItemId,
            ["name"] = item.Name,
            ["quantity"] = item.Quantity,
            ["actions"] = actions,
        };
    }

    private void CloseItemMenuHandler(JsonArray _) => CloseItemMenu();

    private void CloseItemMenu() => _hud.SetState("itemMenu", null);

    private void PickItemActionHandler(JsonArray args)
    {
        CloseItemMenu();
        if (args.Count < 2
            || args[0] is not JsonValue idVal || !idVal.TryGetValue<string>(out var itemId)
            || args[1] is not JsonValue actVal || !actVal.TryGetValue<string>(out var actionId))
            return;
        if (itemId.Length == 0 || actionId.Length == 0 || actionId == "look") return;
        PendingItemAction = PickItemActionAsync(itemId, actionId);
    }

    public async Task PickItemActionAsync(string itemId, string actionId)
    {
        CloseItemMenu();
        if (itemId.Length == 0 || actionId.Length == 0 || actionId == "look") return;

        int seq = ++_itemActionSeq;
        CancelActiveItemWalkWatch();
        if (!CanUse) return;

        var (locId, _) = ConfirmedWhere();
        if (locId.Length == 0 || _world.Slots.GetValueOrDefault(locId) is not { Ready: true, Ring: Ring.Near })
            return;

        double lx, lz;
        string approachRoom;
        try
        {
            using var approachDoc = await _source.ApproachRoomItemAsync(itemId, _lifetime.Token);
            if (_disposed || seq != _itemActionSeq || !CanUse) return;
            var root = approachDoc.RootElement;
            if (!root.TryGetProperty("point", out var pt) || pt.ValueKind != JsonValueKind.Array || pt.GetArrayLength() < 2
                || World.Json.NumOrNull(pt[0]) is not double px || World.Json.NumOrNull(pt[1]) is not double pz)
                return;
            lx = px;
            lz = pz;
            approachRoom = Text(root, "room_id");
        }
        catch (OperationCanceledException)
        {
            return;
        }
        catch (Exception e)
        {
            if (!_disposed)
            {
                HandleItemActionError(e);
                await RefreshItemsAsync();
            }
            return;
        }

        if (_world.Slots.GetValueOrDefault(locId) is not { Ready: true, Ring: Ring.Near } slot || Avatar is not { } avatar)
            return;

        var worldGoal = SceneView.TileToWorld(slot.Stands.Frame, lx, lz);
        var goal = new P2(worldGoal.X, worldGoal.Z);
        string canonRoom = slot.RoomIdOf(approachRoom) ?? approachRoom;
        int? level = canonRoom.Length > 0 && slot.Stands.RoomLevels.TryGetValue(canonRoom, out int lv) ? lv : null;

        bool arrived = await WalkToItemApproachAsync(avatar, goal, level, seq);
        if (!arrived || _disposed || seq != _itemActionSeq || !CanUse)
            return;

        try
        {
            switch (actionId)
            {
                case "take":
                    using (await _source.PickupRoomItemAsync(itemId, _lifetime.Token)) { }
                    break;
                case "read":
                    _hud.SendUi("openItemReader", JsonValue.Create(itemId));
                    break;
                default:
                    using (await _source.RunRoomItemActionAsync(itemId, actionId, _lifetime.Token)) { }
                    break;
            }

            if (!_disposed)
                await RefreshItemsAsync();
        }
        catch (OperationCanceledException)
        {
        }
        catch (Exception e)
        {
            if (!_disposed)
            {
                HandleItemActionError(e);
                await RefreshItemsAsync();
            }
        }
    }

    private Task<bool> WalkToItemApproachAsync(Figure avatar, P2 goal, int? level, int seq)
    {
        var current = new P2(avatar.Position.X, avatar.Position.Z);
        if (ClickMove.ReachedGoal(current, goal))
            return Task.FromResult(true);

        if (!_steering.WalkTo(goal, level))
            return Task.FromResult(false);

        var watch = new ItemWalkWatch(seq, goal, _steering.WalkOrderId);
        _activeItemWalk = watch;
        return watch.Completion.Task;
    }

    private void OnItemOrderFrameShown(string name, OrderFrame frame)
    {
        if (_activeItemWalk is not { OrderId: { } orderId } watch || name != _figures.AvatarName)
            return;
        var player = _figures.OrderPlayerOf(name);
        if (player?.Current?.Id != orderId)
            return;

        if (frame.Events.Contains("aborted")
            || frame.Events.Contains("no_path")
            || frame.Events.Contains("link_refused")
            || player.RunState == OrderState.Abort)
        {
            _activeItemWalk = null;
            watch.Completion.TrySetResult(false);
            return;
        }

        if (frame.State == OrderState.Loop || player.RunState == OrderState.Loop)
            watch.OrderReachedLoop = true;
    }

    private void OnItemAfterTick()
    {
        if (_activeItemWalk is not { } watch) return;

        if (_disposed || !_active || Suspended || watch.Seq != _itemActionSeq || _steering.PropActionDriven || _figures.ServerDriven)
        {
            _activeItemWalk = null;
            watch.Completion.TrySetResult(false);
            return;
        }

        if (watch.OrderId is { } orderId)
        {
            if (_figures.ClickWalkLive(orderId)) return;
            // Outside-door handoff: keep watching the straight segment if ClickWalk handed over at the threshold.
            if (watch.OrderReachedLoop && _steering.Route == watch.Goal)
            {
                watch.OrderId = null;
                return;
            }
            _activeItemWalk = null;
            watch.Completion.TrySetResult(watch.OrderReachedLoop);
            return;
        }

        if (_steering.Route == watch.Goal) return;
        _activeItemWalk = null;
        bool reached = Avatar is { } body && ClickMove.ReachedGoal(new P2(body.Position.X, body.Position.Z), watch.Goal);
        watch.Completion.TrySetResult(reached);
    }

    private void CancelPendingItemWalk()
    {
        _itemActionSeq++;
        CancelActiveItemWalkWatch();
    }

    private void CancelActiveItemWalkWatch()
    {
        if (_activeItemWalk is { } watch)
        {
            _activeItemWalk = null;
            watch.Completion.TrySetResult(false);
        }
    }

    private void HandleItemActionError(Exception e)
    {
        CloseItemMenu();
        ToastItemError(ExtractErrorDetail(e));
    }

    private void ToastItemError(string detail)
    {
        if (detail.Length == 0) detail = "Action failed";
        if (Toast is { } toast) toast(detail);
        else _hud.SendUi("toast", JsonValue.Create(detail), JsonValue.Create(false));
    }

    private static string ExtractErrorDetail(Exception e)
    {
        if (e is ApiException { Detail: { Length: > 0 } detail })
        {
            if (detail.TrimStart().StartsWith('{'))
            {
                try
                {
                    if (JsonNode.Parse(detail) is JsonObject obj)
                    {
                        foreach (var key in new[] { "detail", "reason_text", "error", "reason" })
                            if (obj[key] is JsonValue v && v.TryGetValue<string>(out var s) && s.Length > 0)
                                return s;
                    }
                }
                catch (JsonException) { }
            }
            return detail;
        }
        return e.Message;
    }
}
