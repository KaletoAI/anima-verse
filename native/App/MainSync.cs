using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Overview;
using AnimaNative.Scene;
using AnimaNative.Sync;
using Godot;

namespace AnimaNative;

/// <summary>Main, polling: the worldmap poll, the push stream, the location re-sync and the admin's "show all" view.</summary>
public partial class Main : Node3D
{
    // ---- sync: the browser's polling cadence and push stream (Task 10) ------------------------------------

    /// <summary>
    /// The world map poll of main.ts: ONE subscription <c>c3d-worldmap</c> with the browser's budget
    /// (<see cref="PollSpec.Worldmap3d"/>: 3 s, 6 s while the push stream is connected, at least 3 s apart, backoff on
    /// failures) on <see cref="PollScheduler"/>; online the push stream <c>/events/sync</c> (<see cref="SyncStream"/>)
    /// wakes it early on <c>presence</c>/<c>world</c> and makes a resync drop what was in flight. The location details
    /// re-sync every 120 s and whenever a poll names another revision.
    /// </summary>
    private void StartSync()
    {
        // Task 39 D6: use the world's loaded masks, and follow streamed windows/ground replacements.
        _scatter?.BindGround(() => _builder?.Ground);
        if (_api is { } api)
        {
            _hub = new SyncStream(url => new HttpEventSource(api.OpenEventStreamAsync, url, Log), _timers);
            var hub = _hub;
            bool wasConnected = false;
            int seenGen = 0;
            hub.OnState(() =>
            {
                if (hub.Connected == wasConnected && hub.Generation == seenGen) return;
                wasConnected = hub.Connected;
                seenGen = hub.Generation;
                Log(hub.Describe());
            });
        }
        _poll = new PollScheduler(_timers, _hub);
        _nextTickMs = Time.GetTicksMsec() + PollSchedule.TickMs;
        _pollSub = _poll.Subscribe<PolledMap>(WorldmapKey, FetchWorldMapAsync, PollSpec.Worldmap3d, OnWorldMap);
        if (_locCache?.Cached is { } first)
        {
            _locSync = new LocationsSync(_locCache, l =>
            {
                _builder?.TakeDetails(l.Root);
                Log($"locations re-synced (ETag {l.Etag})");
            });
            _locSync.Seed(first);
            _ = _locSync.SyncAsync();
            ArmLocationsResync();
        }
    }

    private void ArmLocationsResync()
    {
        _locTimer = _timers.SetTimeout(() =>
        {
            if (_stop.IsCancellationRequested || _locSync is null) return;
            _ = _locSync.SyncAsync();
            ArmLocationsResync();
        }, LocationsSync.ResyncMs);
    }

    /// <summary>Back to the title, a lost session, the scene going: no poll, no stream, no timer survives.</summary>
    private void StopSync()
    {
        _pollSub?.Dispose();
        _pollSub = null;
        _poll = null;
        _hub?.Stop();
        _hub = null;
        _timers.ClearTimeout(_locTimer);
        _locTimer = null;
        _locSync = null;
        _nextTickMs = double.PositiveInfinity;
    }

    /// <summary>A polled map with the view revision it was asked under (main.ts <c>PolledMap</c>).</summary>
    private sealed record PolledMap(JsonElement Map, int ViewRev);

    private async Task<PolledMap> FetchWorldMapAsync()
    {
        int rev = _viewRev;
        using var doc = _api is { } api ? await api.GetWorldMapAsync(_showAll) : await _source!.GetWorldMapAsync();
        return new PolledMap(doc.RootElement.Clone(), rev);
    }

    /// <summary>The poll's callback: an error that is not a lost session marks the connection lost.</summary>
    private void OnWorldMap(PolledMap? polled, Exception? error)
    {
        if (_stop.IsCancellationRequested || Leaving) return;
        if (error is not null)
        {
            if (AnimaApi.IsAuthError(error)) return;   // the login comes back (OnUnauthorized)
            Log($"worldmap poll failed: {error.Message} — next in {(_poll?.IntervalMs(WorldmapKey) ?? 0) / 1000:0} s");
            _figures?.MarkPollFailed();
            if (_conn.Lost()) _hud?.SetState("connection", ConnectionState.LostValue);
            return;
        }
        if (polled is not null) ApplyWorldMap(polled);
    }

    /// <summary>
    /// main.ts <c>applyWorldMap</c>, the parts this client has: drop a map of an older view; re-sync the details
    /// when the map names another revision; the figures, the pins and the selection follow the map; connection and
    /// clock only on change; a placed location the world has not taken in forces a details re-sync and is revealed.
    /// </summary>
    private void ApplyWorldMap(PolledMap p)
    {
        if (p.ViewRev != _viewRev || _viewSwitchBusy || _figures is null) return;
        var map = p.Map;
        try
        {
            if (_locSync is not null && _locSync.Differs(LocationsSync.MapRev(map))) _ = _locSync.SyncAsync();
            _figures.ApplyPolled(map);
            _scatter?.SyncWorldMap(map); // Task 39 D4/D5: every accepted poll, including view switches.
            var clock = ConnectionState.ClockOf(map);
            if (_conn.Ok(clock))
            {
                _hud?.SetState("connection", ConnectionState.OkValue);
                _hud?.SetState("clock", clock);
            }
            if (_selected is not null) Select(_selected);   // refreshSelection(map)
            AnnounceSceneProblems(map);                      // what the composer found wrong (§ 4.3)
            // terrainGround.sync(terrain_sig, world_bounds, …, height_sig): the frame, the loaders' idle occasion and
            // the reload chains of the two signatures (Task 24).
            _ = _streamer?.Sync(map);
            // The avatar's exploration memory travels the same way — on its own signature, never in the poll.
            SyncExplored(map);
            if (_interactive && _builder is not null && _builder.FreshOf(map).Count > 0)
            {
                // Discovery needs details even when the endpoint revision has not changed.
                _ = _locSync?.SyncAsync(force: true);
                _ = RevealAsync(map);
            }
        }
        catch (Exception e)
        {
            Log($"worldmap apply failed: {e.Message}");
            if (!AnimaApi.IsAuthError(e) && _conn.Lost()) _hud?.SetState("connection", ConnectionState.LostValue);
        }
    }

    /// <summary>The (location, kind, room) keys already toasted this session (main.ts <c>announcedProblems</c>).</summary>
    private readonly HashSet<string> _announcedProblems = new();

    /// <summary>
    /// main.ts <c>announceSceneProblems(map)</c>: the scene problems of the avatar's location (its mounted scene) are
    /// toasted once per (location, kind, room) through the HUD's toast action (translated, error look), never one with
    /// <c>scope: "editor"</c>; each is also logged as a warning line.
    /// </summary>
    private void AnnounceSceneProblems(JsonElement map)
    {
        if (_builder is null) return;
        var here = AnimaNative.World.Anchor.AvatarLocation(map);
        var problems = here is not null && _builder.Slots.TryGetValue(here, out var slot) ? slot.Problems : null;
        foreach (var toast in SceneProblems.Announce(here, problems, _announcedProblems))
        {
            Log(toast.Log);
            _hud?.SendUi("toast", JsonValue.Create(toast.Message), JsonValue.Create(true));
        }
    }

    /// <summary><c>revealLocations(map)</c>: one at a time; a run of an older view mounts nothing.</summary>
    private async Task<int> RevealAsync(JsonElement map)
    {
        if (_revealBusy || _builder is null) return 0;
        _revealBusy = true;
        int rev = _viewRev;
        try
        {
            int added = await _builder.RevealAsync(map, () => rev == _viewRev && !_stop.IsCancellationRequested);
            if (added > 0) _placeRows = null;
            SyncPlaceLabels();
            return added;
        }
        catch (Exception e)
        {
            Log($"reveal failed: {e.Message}");
            return 0;
        }
        finally
        {
            _revealBusy = false;
        }
    }

    /// <summary>
    /// main.ts <c>applyShowAll(on)</c> — the admin's "show all locations", applied live: the flag and the view
    /// revision move BEFORE the request (a poll in flight of the old view is dropped), the other view's map is
    /// fetched and the world is reconciled against it: what it no longer carries goes (the avatar's own place
    /// stays), what it adds is revealed. A failed request rolls the flag back and says so in a toast.
    /// </summary>
    private async Task ApplyShowAllAsync(bool on)
    {
        if (!IsAdmin || on == _showAll || _viewSwitchBusy || _api is null || _builder is null || _figures is null) return;
        _viewSwitchBusy = true;
        try
        {
            _showAll = on;
            _viewRev++;
            JsonElement map;
            try
            {
                using var doc = await _api.GetWorldMapAsync(on);
                map = doc.RootElement.Clone();
            }
            catch (Exception e)
            {
                _showAll = !on;
                _viewRev++;
                Log($"show all: switch failed: {e.Message}");
                _hud?.SendUi("toast", JsonValue.Create("The view could not be switched."), JsonValue.Create(true));
                return;
            }
            if (_stop.IsCancellationRequested) return;
            _figures.ApplyPolled(map);
            _scatter?.SyncWorldMap(map); // Task 39 D4/D5: every accepted poll, including view switches.
            // main.ts syncs the ground right here with the switched view's frame (no three-second gap).
            _ = _streamer?.Sync(map);
            // …and with it the veil: the unfiltered view takes the haze away in the same frame.
            SyncExplored(map);
            var dropped = _builder.DropVanished(map);
            if (dropped.Count > 0)
            {
                if (_openView.OpenId is { } open && dropped.Contains(open)) CloseOpenLocation();
                // A view switch closes information that may describe a removed place.
                SetInfo(null);
            }
            _placeRows = null;
            if (_selected is not null) Select(_selected);
            int rev = _viewRev;
            int added = await _builder.RevealAsync(map, () => rev == _viewRev && !_stop.IsCancellationRequested);
            _placeRows = null;
            SyncPlaceLabels();
            Log($"show all locations {(on ? "ON" : "off")}: {dropped.Count} dropped, {added} revealed");
        }
        catch (Exception e)
        {
            Log($"show all: switch failed: {e.Message}");
            _hud?.SendUi("toast", JsonValue.Create("The view could not be switched."), JsonValue.Create(true));
        }
        finally
        {
            _viewSwitchBusy = false;
        }
    }


    private string SyncLine()
        => $"poll every {(_poll?.IntervalMs(WorldmapKey) ?? 0) / 1000:0} s ({_conn.Connection})"
           + (_hub is not null ? $", {_hub.Describe()}" : ", no push stream")
           + (_locSync is not null ? $", locations rev {_locSync.Rev}" : "")
           + (_showAll ? ", SHOW ALL" : "");
}
