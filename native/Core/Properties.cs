using System.Runtime.CompilerServices;

// The Godot project calls the Meshopt P/Invoke layer (MeshoptNative.EnsureLoaded)
// and a few internal helpers that predate the core split.
[assembly: InternalsVisibleTo("AnimaNative")]
[assembly: InternalsVisibleTo("AnimaNative.Tests")]
