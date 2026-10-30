using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Hud;
using AnimaNative.Overview;
using AnimaNative.Ui;
using AnimaNative.World;
using Godot;

namespace AnimaNative;

/// <summary>Main, HUD wiring: the game actions the HUD sends, selection, picking, the info panel and the open view.</summary>
public partial class Main : Node3D
{
    private string CacheRoot => _options?.CacheDir ?? ProjectSettings.GlobalizePath("user://cache");
    private ulong _nextCacheReadout;
    private void PublishClientCache(bool force = false)
    {
        if (_hud is not { } hud || !IsInstanceValid(hud)) return;
        ulong now = Time.GetTicksMsec();
        if (!force && now < _nextCacheReadout) return;
        _nextCacheReadout = now + 1000;
        var stats = _api?.CacheStore?.Readout;
        hud.SetState("clientCache", stats is null ? null : new JsonObject
            { ["bytes"] = stats.Bytes, ["limitBytes"] = stats.LimitBytes, ["entries"] = stats.Entries });
    }

    // ---- HUD scene side (Task S4) ---------------------------------------------------

    /// <summary>The overlay (once per process) + the game actions this spike answers.</summary>
    private void AttachHud()
    {
        _hud = HudOverlay.Ensure(GetTree(), Log);
        if (_hud is null) return;
        var hud = _hud;
        _camera!.KeysBlocked = () => IsInstanceValid(hud) && hud.KeysToHud;
        hud.Handlers.Clear();
        hud.Handlers["zoomTo"] = args => ZoomTo(args.Count > 0 ? args[0]?.GetValue<string>() : null);
        // The chat panel's box (HUD CSS px) → the camera's view shift (viewport px).
        hud.Handlers["setChatBox"] = args => _camera?.SetChatBox(hud.ChatBoxInWindow(args));
        hud.Handlers["clearSelection"] = _ => SelectForInput(null);
        hud.Handlers["closeOpenView"] = _ => CloseOpenLocation();
        hud.Handlers["closeInfo"] = _ => SetInfo(null);
        hud.Handlers["infoAction"] = args => InfoAction(Arg(args, 0), Arg(args, 1));
        AttachAudioHandlers(hud);
        hud.Handlers["backToTitle"] = _ => OnSession(SessionEvent.BackToTitle);
        hud.Handlers["setShowAll"] = args =>
        {
            if (args.Count > 0 && args[0] is JsonValue v && v.TryGetValue<bool>(out var on)) _ = ApplyShowAllAsync(on);
        };
        hud.Handlers["applyScatterPrefs"] = ApplyScatterPrefs;
        hud.Handlers["applyGraphicsPrefs"] = ApplyGraphicsPrefs;
        hud.Handlers["clearClientCache"] = _ =>
        {
            _api?.CacheStore?.RequestClear();
            PublishClientCache(force: true);
        };
        PublishClientCache(force: true);
        // Hud.tsx: a new speakable line of this room → npcs.say(speaker, text); unknown names are ignored.
        hud.Handlers["sayBubble"] = args =>
        {
            if (Arg(args, 0) is { } who && Arg(args, 1) is { } text) _tags?.Say(who, text);
        };
        // The browser sets a marker that survives ONE page reload, so the next boot skips the title gate (a
        // character take-over reloads the page). Natively the marker is only acknowledged: any reload of the HUD
        // page after its first load rebuilds the world with the live session, whichever arrives first (SessionFlow).
        hud.Handlers["markResume"] = _ => OnSession(SessionEvent.ResumeMarked);
        hud.PageLoaded = () => { _audio?.StopSpeech(); OnSession(SessionEvent.HudPageLoaded); };
        AttachEmbody(hud);
        // Scene-owned fields the chat, plaque and menu read (minimum viable set).
        hud.SetState("mode", "overview");
        hud.SetState("connection", "ok");
        hud.SetState("clock", "");
        hud.SetState("selected", null);
        hud.SetState("openView", null);
        hud.SetState("info", null);
    }

    /// <summary>main.ts <c>roomOf.get(avatarName)</c>: the room the avatar's row names ("" without one).</summary>
    private static string AvatarRoomOf(JsonElement map)
    {
        var name = Str(map, "avatar");
        if (string.IsNullOrEmpty(name) || !map.TryGetProperty("characters", out var chars) || chars.ValueKind != JsonValueKind.Array)
            return "";
        foreach (var c in chars.EnumerateArray())
            if (Str(c, "name") == name) return Str(c, "room_id") ?? "";
        return "";
    }

    /// <summary>
    /// The lock look of the marks follows the HUD's verdicts and the avatar's room (main.ts frame hook: repainted only
    /// when the lock map, the location it was answered for or the room changed — here the HUD-owned version and the
    /// room are the comparison).
    /// </summary>
    private void SyncLocks()
    {
        if (_builder is null || _hud is not { } hud || !IsInstanceValid(hud)) return;
        if (hud.HudOwnedVersion == _lockVersion && _avatarRoom == _lockRoom) return;
        _lockVersion = hud.HudOwnedVersion;
        _lockRoom = _avatarRoom;
        _builder.SetLocks(Scene.LockState.FromHud(hud.HudOwned("lockedRooms"), hud.HudOwned("lockedLoc"),
                                                  hud.HudOwned("lockedLocations"), _avatarRoom));
    }

    /// <summary>
    /// <c>applyScatterPrefs(prefs)</c> from the HUD's menu: checked again here (<see cref="ScatterPrefs.Check"/> — a
    /// malformed message must not invert the band), then both scatter and world-prop LOD (Task 40).
    /// Undergrowth keeps its fixed distances, as in ground.ts.
    /// </summary>
    private void ApplyScatterPrefs(JsonArray args)
    {
        if (args.Count == 0 || args[0] is not JsonObject p)
        {
            Log("applyScatterPrefs: no prefs object — ignored");
            return;
        }
        var check = ScatterPrefs.Check(HudUi.Num(p, "scatterNearM"), HudUi.Num(p, "scatterFarM"), HudUi.Num(p, "scatterCullM"));
        if (check.Prefs is not { } prefs)
        {
            Log($"applyScatterPrefs refused ({check.Error}): {p.ToJsonString()}");
            return;
        }
        _scatterPrefs = prefs;
        Scatter.ScatterDetail.Apply(ScatterPrefs.LodCfgOf(prefs), _scatter?.Field, _builder?.WorldProps);
        Log($"scatter detail distances {prefs.ScatterNearM}/{prefs.ScatterFarM}/{prefs.ScatterCullM} m"
            + (_scatter is null ? " applied to world props (scatter is disabled)" : " applied to scatter and world props"));
    }

    /// <summary>
    /// <c>applyGraphicsPrefs(prefs)</c> from the menu's Graphics tab (Task 26d, bridge v2): checked again here
    /// (<see cref="GraphicsPrefs.Check"/> — a malformed message leaves the picture alone), then applied at runtime. A
    /// bench run keeps its picture (reproducibility): the change is logged and ignored.
    /// </summary>
    private void ApplyGraphicsPrefs(JsonArray args)
    {
        if (args.Count == 0 || args[0] is not JsonObject p)
        {
            Log("applyGraphicsPrefs: no prefs object — ignored");
            return;
        }
        var check = GraphicsPrefs.Check(p["antiAliasing"], p["shadows"]);
        if (check.Prefs is not { } prefs)
        {
            Log($"applyGraphicsPrefs refused ({check.Error}): {p.ToJsonString()}");
            return;
        }
        if (_options!.Bench)
        {
            Log($"applyGraphicsPrefs ignored during a bench run (kept msaa {GetViewport().Msaa3D}, shadows as the run set them)");
            return;
        }
        ApplyGraphics(prefs, "menu");
    }

    /// <summary>
    /// The Graphics tab onto the frame: the viewport's 3D MSAA (<c>Viewport.msaa_3d</c>, settable at runtime) unless
    /// <c>--msaa</c> was given (it wins for the whole run), and the sun's shadow with its caster gate
    /// (<see cref="StageAmbience.Shadows"/>).
    /// </summary>
    private void ApplyGraphics(GraphicsPrefs prefs, string from)
    {
        var msaa = _options!.Msaa ?? CliOptions.MsaaOfSamples(GraphicsPrefs.MsaaSamplesOf(prefs.AntiAliasing));
        if (GetViewport().Msaa3D != msaa) GetViewport().Msaa3D = msaa;
        if (_stage is not null) _stage.Shadows = prefs.Shadows;
        Log($"graphics ({from}): anti-aliasing {prefs.AntiAliasing}"
            + (_options.Msaa is { } cli ? $" (--msaa wins: {cli})" : $" → msaa {msaa}")
            + $", shadows {(prefs.Shadows ? "on" : "off")}");
    }

    /// <summary>
    /// <c>selected = { char, isAvatar }</c> with the character's row of the latest
    /// worldmap (the HUD's <c>MapCharacter</c>, passed through unchanged); a name
    /// that is not on the map drops the selection, like main.ts <c>refreshSelection</c>.
    /// </summary>
    private void Select(string? name)
    {
        if (_hud is null) return;
        _selected = null;
        JsonNode? value = null;
        if (name is not null && _figures?.LatestMap is { } map
            && map.TryGetProperty("characters", out var chars) && chars.ValueKind == JsonValueKind.Array)
        {
            foreach (var row in chars.EnumerateArray())
            {
                if (Str(row, "name") != name) continue;
                value = new JsonObject
                {
                    ["char"] = JsonNode.Parse(row.GetRawText()),
                    ["isAvatar"] = Str(map, "avatar") == name,
                };
                _selected = name;
                break;
            }
        }
        _hud.SetState("selected", value);
    }

    /// <summary>
    /// A click the HUD did not take (engine.ts <c>pointerup</c>, a left release without a drag): the ray through
    /// the pointer — the camera's own, which honours the view shift — asks the figures first, then the
    /// locations (<see cref="PickChain"/>): a figure gets the plaque and keeps the panel, a location opens its
    /// info panel and clears the selection, empty ground clears both.
    /// </summary>
    private void PickAt(Vector2 click)
    {
        if (_figures is null || _camera is null) return;
        var (o, d) = _camera.RayAt(click);
        var figure = _figures.CharacterAt(o, d);
        // Asked only when no figure took the click, as engine.ts does.
        var location = figure is null ? _picking?.Pick(o, d) : null;
        var outcome = PickChain.Resolve(figure?.Name, location?.Id, () =>
        {
            // Task 52: Task 57's prop-action hook runs inside Pick before room markers/dioramas.
            if (_avatarOffers?.Pick(o, d, click) == true) return true;
            if (_avatarRooms?.Picking.Hit(o, d) is { } vertical)
            { _avatarRooms.UseVertical(vertical.Target); return true; }
            return false;
        }, embodied: Embodied);
        Log($"pick at ({click.X:0},{click.Y:0}): "
            + (figure is { } f ? $"figure {f.Name} at {f.Distance:0.##} m ({_figures.LastPickCandidates} near the ray, "
                                 + $"{_figures.LastPickSkinnedVertices} vertices skinned, {_figures.LastPickMs:0.##} ms)"
               : location is { } l ? $"location {l.Id} at {l.Distance:0.##} m ({_picking!.LastBoxTests} boxes, "
                                     + $"{_picking.LastTriangleQueries} meshes, {_picking.LastMs:0.##} ms)"
               : "nothing"));
        SelectForInput(outcome.Selected);
        if (outcome.Info == InfoChange.Clear) SetInfo(null);
        else if (outcome.Info == InfoChange.Show) ShowInfo(outcome.InfoLocationId!);
    }

    // ---- info panel, open view, hover, auto-close (Task 9) -----------------------------------------

    private void SetInfo(JsonObject? info)
    {
        _info = info;
        _hud?.SetState("info", info?.DeepClone());
    }

    /// <summary>
    /// main.ts <c>engine.onPick(id)</c>: the panel of a known place (its world-map row), with the characters in
    /// it, its events, who is in which room, the view state and the avatar's whereabouts. An id without a row
    /// leaves the panel as it is.
    /// </summary>
    private void ShowInfo(string id)
    {
        var map = _figures?.LatestMap ?? _builder?.FirstMap;
        if (map is not { } m) return;
        var slot = _builder?.Slots.GetValueOrDefault(id);
        // `openable: !!residency.get(id) && openable(tile)` — a place that is not built cannot be opened.
        if (InfoPanel.FromWorldMap(m, id, new InfoView(slot?.Openable == true, _openView.OpenId == id)) is { } info)
            SetInfo(info);
    }

    /// <summary>
    /// main.ts <c>infoAction(id, kind)</c>: "Close view" closes the open location; "Zoom in" and "Look inside"
    /// fly to the place's centre at <c>min(targetDist, 15)</c>, "Look inside" also opens it. Then only the
    /// panel's <c>view.open</c> is brought up to date.
    /// </summary>
    private void InfoAction(string? id, string? kind)
    {
        if (id is null || _camera is null) return;
        if (kind == "closeView") CloseOpenLocation();
        else if (PlaceCentre(id) is { } centre)
        {
            _camera.FlyTo(centre, OpenView.FlyInDist(_camera.Control.TargetDist));
            if (kind == "lookInside") OpenLocation(id);
        }
        if (_info is { } info && Str(info, "id") == id && info["view"] is JsonObject v)
        {
            v["open"] = _openView.OpenId == id;
            SetInfo(info);
        }
    }

    /// <summary><c>openLocation(id)</c>: only a built, openable place; the previously open one closes.</summary>
    private void OpenLocation(string id)
    {
        var slot = _builder?.Slots.GetValueOrDefault(id);
        if (!_openView.TryOpen(id, slot?.Openable == true, out var closed)) return;
        // Opening one location closes the current one — both crossfade off their diverged targets (TickView).
        if (closed is not null) _builder!.SetOpen(closed, false);
        _builder!.SetOpen(id, true);
        RefreshOpenBadge();
    }

    /// <summary><c>closeOpenLocation()</c>.</summary>
    private void CloseOpenLocation()
    {
        if (_openView.Close() is { } closed) _builder?.SetOpen(closed, false);
        RefreshOpenBadge();
    }

    /// <summary><c>refreshOpenBadge</c>: the open place's name, when it has one.</summary>
    private void RefreshOpenBadge()
    {
        var name = _openView.OpenId is { } id ? RowsOfPlaces().GetValueOrDefault(id)?.Name : null;
        _hud?.SetState("openView", OpenView.BadgeName(name));
    }

    /// <summary>
    /// <c>applyHoverCursor</c>: the pointing hand over a pickable location, the arrow elsewhere — only for a
    /// pointer over the SCENE (the camera reports moves the HUD did not take), and only while clicks pick.
    /// </summary>
    private void Hover(Vector2? at)
    {
        var shape = Input.CursorShape.Arrow;
        if (at is { } p && _hud?.Active == true && _picking is not null && _camera is not null)
        {
            var (o, d) = _camera.RayAt(p);
            if (_avatarOffers?.HasHover == true || _avatarRooms?.Picking.HasHover == true || _picking.Pick(o, d) is not null) shape = Input.CursorShape.PointingHand;
        }
        if (_hud is not null) _hud.SceneCursor = shape;
        if (_hud?.PointerOverHud == true) return;   // the page owns the cursor there
        Input.SetDefaultCursorShape(shape);
    }

    /// <summary>The world-map location rows by id (latest poll, else the build's), parsed once per poll.</summary>
    private Dictionary<string, LocationInfo> RowsOfPlaces()
    {
        int serial = _figures?.PollSerial ?? -1;
        if (_placeRows is { } cached && cached.Serial == serial) return cached.Rows;
        var map = _figures?.LatestMap ?? _builder?.FirstMap;
        var rows = new Dictionary<string, LocationInfo>();
        if (map is { } m)
            foreach (var l in LocationInfo.ParseList(m))
                rows[l.Id] = l;
        _placeRows = (serial, rows);
        return rows;
    }

    /// <summary><c>tile.center</c>: the built group's position, else the row's position on the ground.</summary>
    private Vector3? PlaceCentre(string id)
    {
        if (_builder?.Slots.GetValueOrDefault(id) is { } slot && IsInstanceValid(slot.Group)) return slot.Group.Position;
        if (RowsOfPlaces().GetValueOrDefault(id) is { IsPlaced: true } row && _builder?.Height is { } h)
            return new Vector3((float)row.PosX!.Value, (float)h.GroundAt(row.PosX.Value, row.PosZ!.Value), (float)row.PosZ.Value);
        return null;
    }

    /// <summary>
    /// A place for the event pins and the location labels (main.ts <c>places.get(id)</c>): centre x/z, the ground
    /// datum (<c>tile.center.y</c>) and <c>tile.height</c> — the built group's, else the ground under the row's pin
    /// (<c>footprintCentre</c>) and <c>buildPlace</c>'s reading height.
    /// </summary>
    private (double X, double GroundY, double Z, double Height)? PlaceOf(string id)
    {
        if (_builder?.Slots.GetValueOrDefault(id) is { } slot && IsInstanceValid(slot.Group))
            return (slot.Group.Position.X, slot.Group.Position.Y, slot.Group.Position.Z, slot.Height);
        if (RowsOfPlaces().GetValueOrDefault(id) is not { IsPlaced: true } row || _builder?.Height is not { } h) return null;
        var (isBuilding, nature) = LocationView.Kind(row);
        return (row.PosX!.Value, h.GroundAt(row.PosX.Value, row.PosZ!.Value), row.PosZ.Value,
                EventPinRule.DefaultPlaceHeight(isBuilding, nature, LocationView.DetectStyle(row)));
    }

    /// <summary>A built location the neighbour occlusion has hidden (its group invisible).</summary>
    private bool OccludedPlace(string id)
        => _builder?.Slots.GetValueOrDefault(id) is { } slot && IsInstanceValid(slot.Group) && !slot.Group.Visible;

    /// <summary>The location labels follow the world's places and their latest rows.</summary>
    private void SyncPlaceLabels()
    {
        if (_placeLabels is null || _builder is null) return;
        _placeLabels.Sync(_builder.Known, RowsOfPlaces());
    }

    /// <summary>The plaque's "Zoom to" (main.ts <c>zoomTo</c>): fly to the figure's root + 0.85 m at 4.5 m; no follow.</summary>
    private void ZoomTo(string? name)
    {
        if (name is null || _figures is null || _camera is null || _camera.Follow is not null) return;
        if (!_figures.Figures.TryGetValue(name, out var fig) || !IsInstanceValid(fig)) return;
        _camera.ZoomTo(fig.GlobalPosition);
        Log($"camera → {name} (HUD zoomTo)");
    }
}
