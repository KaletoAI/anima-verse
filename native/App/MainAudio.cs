using System.Collections.Generic;
using AnimaNative.Audio;
using AnimaNative.Hud;
using Godot;

namespace AnimaNative;

/// <summary>Task 59: audio lifetime belongs to Main, with source access after session login and before HUD handoff.
/// New wiring is isolated here so concurrent MainWorld/TerrainStreamer work is untouched.</summary>
public partial class Main : Node3D
{
    private AudioOut? _audio;
    private SoundtrackDriver? _soundtrack;

    /// <summary>Task 60: start once the mounted world exists, after stored prefs and session source are available.
    /// Overview samples the camera target; embodied samples the rendered avatar root, never a server destination.
    /// FootprintAt selects the smallest mounted footprint and reads fresh terrain after every world rebuild.</summary>
    private void TickSoundtrackFrame()
    {
        if (_source is null || _builder?.FirstMap is null || _camera is null || _stop.IsCancellationRequested) return;
        if (_soundtrack is null)
        {
            var output = EnsureAudio();
            var source = _source;
            _soundtrack = new SoundtrackDriver(() => Time.GetTicksMsec(), SoundtrackView,
                (x, z) => _builder?.FootprintAt(x, z)?.Loc.Terrain ?? "", source.GetAudioManifestAsync,
                (urls, fade) => output.PlayPlaylist(PlaylistBus.Music, urls, fade),
                (urls, fade) => output.PlayPlaylist(PlaylistBus.Ambient, urls, fade),
                output.Prefs.MusicOn, output.Prefs.AmbientOn);
            output.PrefsChanged += SoundtrackPrefsChanged;
        }
        _soundtrack.Pump();
    }

    private SoundtrackFrame SoundtrackView()
    {
        var avatar = Embodied ? AvatarFigure() : null;
        var camera = _camera?.Target;
        return new(_night, Embodied ? "embodied" : "overview",
            avatar is null ? null : (avatar.GlobalPosition.X, avatar.GlobalPosition.Z),
            camera is { } at ? (at.X, at.Z) : null);
    }
    private void SoundtrackPrefsChanged(AudioPrefs prefs) => _soundtrack?.SetSwitches(prefs.MusicOn, prefs.AmbientOn);

    /// <summary>Task 60: scene reload ends this manifest lifetime, including a character switch on the same cookie.</summary>
    private void StopSoundtrack()
    {
        if (_audio is not null) _audio.PrefsChanged -= SoundtrackPrefsChanged;
        _soundtrack?.Dispose(); _soundtrack = null;
    }
    private AudioOut EnsureAudio()
    {
        if (_audio is not null) return _audio;
        _audio = new AudioOut { Name = "AudioOut" }.Configure(() => _source, Log);
        AddChild(_audio);
        return _audio;
    }
    private void AttachAudioHandlers(HudOverlay hud)
    {
        var output = EnsureAudio();
        output.AttachHandlers(hud.Handlers);
        hud.Speak = output.Speak;
    }
    private void ReadStoredAudioStart(IReadOnlyDictionary<string, string> stored)
        => EnsureAudio().InitializePrefs(stored.GetValueOrDefault(AudioPrefs.Key));
}
