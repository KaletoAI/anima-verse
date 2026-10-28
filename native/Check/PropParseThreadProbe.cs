using System.Collections.Concurrent;
using Godot;

namespace AnimaNative.Check;

/// <summary>Check-only observer of Godot's actual parse/generate boundary (Task 37); never changes the glTF state.</summary>
internal partial class PropParseThreadProbe : GltfDocumentExtension
{
    public static readonly ConcurrentQueue<int> Parsed = new();
    public static readonly ConcurrentQueue<int> Generated = new();

    public override Error _ImportPreflight(GltfState state, string[] extensions)
    {
        Parsed.Enqueue(System.Environment.CurrentManagedThreadId);
        return Error.Ok;
    }

    public override Error _ImportPreGenerate(GltfState state)
    {
        Generated.Enqueue(System.Environment.CurrentManagedThreadId);
        return Error.Ok;
    }
}
