using System;
using System.Linq;
using System.Reflection;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// The core library must stay loadable without Godot: no reference to any
/// Godot assembly, and every public type lives under <c>AnimaNative.</c>.
/// </summary>
public class CoreIsGodotFreeTests
{
    private const string CoreAssemblyName = "AnimaNative.Core";

    private static Assembly LoadCore() => Assembly.Load(new AssemblyName(CoreAssemblyName));

    [Fact]
    public void NoGodotReference()
    {
        var core = LoadCore();
        var godot = core.GetReferencedAssemblies()
            .Select(a => a.Name ?? "")
            .Where(n => n.StartsWith("Godot", StringComparison.Ordinal))
            .ToList();
        Assert.True(godot.Count == 0, $"{CoreAssemblyName} references Godot assemblies: {string.Join(", ", godot)}");
    }

    [Fact]
    public void AllTypesInAnimaNamespace()
    {
        var core = LoadCore();
        var types = core.GetExportedTypes();
        Assert.NotEmpty(types);
        var outside = types
            .Where(t => !(t.FullName ?? "").StartsWith("AnimaNative.", StringComparison.Ordinal))
            .Select(t => t.FullName)
            .ToList();
        Assert.True(outside.Count == 0, $"public types outside AnimaNative.*: {string.Join(", ", outside)}");
    }
}
