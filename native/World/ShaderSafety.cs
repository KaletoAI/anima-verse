using System.Collections.Generic;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// Every spatial shader of the client goes through here once (Task S3c): Godot's shader-language front end
/// runs inside <c>shader_set_code</c> — on the headless dummy renderer of <c>--check</c> / <c>--offline</c> as
/// well as on a GPU — and a shader that failed it reports NO uniforms. Each shader has uniforms by
/// construction, so "0 uniforms" is the compile failure. One log line per shader name says which way it went;
/// the caller falls back to a plain material instead of letting the engine draw the error colour.
/// </summary>
public static class ShaderSafety
{
    private static readonly Dictionary<ulong, bool> Verdicts = new();
    private static readonly HashSet<string> Logged = new();

    /// <summary>Lines the check reads back ("shader &lt;name&gt;: …").</summary>
    public static List<string> Lines { get; } = new();

    public static bool Ok(Shader shader, string name)
    {
        ulong id = shader.GetInstanceId();
        if (!Verdicts.TryGetValue(id, out bool ok))
        {
            int uniforms = shader.GetShaderUniformList().Count;
            ok = uniforms > 0;
            Verdicts[id] = ok;
            if (Logged.Add(name))
            {
                var line = ok ? $"shader {name}: compiled ({uniforms} uniforms)"
                              : $"shader {name}: FAILED to compile — plain material fallback";
                Lines.Add(line);
                if (ok) GD.Print("[native] " + line);
                else GD.PrintErr("[native] " + line);
            }
        }
        return ok;
    }
}
