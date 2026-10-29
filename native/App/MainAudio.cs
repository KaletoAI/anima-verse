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
    private AudioOut EnsureAudio()
    {
        if (_audio is not null) return _audio;
        _audio = new AudioOut { Name = "AudioOut" }.Configure(() => _source, Log);
        AddChild(_audio);
        return _audio;
    }
    private void AttachAudioHandlers(HudOverlay hud) => EnsureAudio().AttachHandlers(hud.Handlers);
    private void ReadStoredAudioStart(IReadOnlyDictionary<string, string> stored)
        => EnsureAudio().InitializePrefs(stored.GetValueOrDefault(AudioPrefs.Key));
}
