using System.Threading.Tasks;

namespace AnimaNative.Audio;

/// <summary>Task 59: decoded duration without an engine dependency; adapters retain the engine's stream.</summary>
public interface IAudioClip { double Duration { get; } }

/// <summary>Task 59: one non-positional source, owned by the schedule until Stop (which also releases it).</summary>
public interface IAudioPlayback
{
    void Start(IAudioClip clip, double gain);
    void SetGain(double gain);
    void Stop();
}

/// <summary>Task 59: the cache flag is true for looping playlists and false for unique speech URLs.</summary>
public delegate Task<IAudioClip> AudioLoader(string url, bool cache);
