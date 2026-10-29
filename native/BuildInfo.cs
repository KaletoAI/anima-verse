using System.Linq;
using System.Reflection;

namespace AnimaNative;

/// <summary>The immutable build identity, available to the launcher and update checks.</summary>
public static class BuildInfo
{
    public static string Version { get; } = typeof(BuildInfo).Assembly
        .GetCustomAttributes<AssemblyMetadataAttribute>()
        .FirstOrDefault(a => a.Key == "AnimaNative.Version")?.Value ?? "development";
}
