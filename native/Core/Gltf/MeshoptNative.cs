using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;

namespace AnimaNative.Gltf;

/// <summary>
/// P/Invoke into the vendored meshoptimizer (native/third_party/meshoptimizer,
/// MIT, v1.3) built as <c>libmeshoptimizer.so</c>. Signatures copied from
/// <c>src/meshoptimizer.h</c> (the header is <c>extern "C"</c>, cdecl):
///
///   int  meshopt_decodeVertexBuffer(void* dst, size_t count, size_t size, const unsigned char* buf, size_t buf_size)
///   int  meshopt_decodeIndexBuffer(void* dst, size_t count, size_t index_size, const unsigned char* buf, size_t buf_size)
///   int  meshopt_decodeIndexSequence(void* dst, size_t count, size_t index_size, const unsigned char* buf, size_t buf_size)
///   void meshopt_decodeFilterOct/Quat/Exp/Color(void* buffer, size_t count, size_t stride)
///
/// The library is looked up next to the executable (exported build; build.sh
/// copies it there), in the directories the host registered through
/// <see cref="EnsureLoaded"/> (the Godot side passes <c>res://bin</c> =
/// <c>native/bin/</c>, where the csproj build target compiles it, for runs
/// from the project) and next to this assembly. This class knows no engine:
/// the host resolves its own paths.
/// </summary>
internal static unsafe class MeshoptNative
{
    private const string Lib = "meshoptimizer";

    private static readonly List<string> SearchDirectories = new();

    static MeshoptNative()
    {
        NativeLibrary.SetDllImportResolver(typeof(MeshoptNative).Assembly, Resolve);
    }

    /// <summary>
    /// Register extra directories to search (after the executable's folder) and
    /// force the static constructor (resolver registration) plus the library
    /// load before the first real call.
    /// </summary>
    public static void EnsureLoaded(params string[] searchDirectories)
    {
        lock (SearchDirectories)
            foreach (var dir in searchDirectories)
                if (!string.IsNullOrEmpty(dir) && !SearchDirectories.Contains(dir)) SearchDirectories.Add(dir);
        _ = meshopt_decodeVertexVersion(null, 0);
    }

    private static IntPtr Resolve(string name, Assembly assembly, DllImportSearchPath? path)
    {
        if (name != Lib) return IntPtr.Zero;
        foreach (var candidate in Candidates())
            if (File.Exists(candidate) && NativeLibrary.TryLoad(candidate, out var handle)) return handle;
        throw new DllNotFoundException("libmeshoptimizer.so not found; looked in: " + string.Join(", ", Candidates()));
    }

    private static IEnumerable<string> Candidates()
    {
        // Environment.ProcessPath is the engine binary — the same path as
        // Godot's OS.GetExecutablePath(), i.e. the export folder.
        var exeDir = Path.GetDirectoryName(Environment.ProcessPath ?? "") ?? "";
        if (exeDir.Length > 0) yield return Path.Combine(exeDir, "libmeshoptimizer.so");
        string[] registered;
        lock (SearchDirectories) registered = SearchDirectories.ToArray();
        foreach (var dir in registered)
            if (Directory.Exists(dir)) yield return Path.Combine(dir, "libmeshoptimizer.so");
        var asmDir = Path.GetDirectoryName(typeof(MeshoptNative).Assembly.Location);
        if (!string.IsNullOrEmpty(asmDir)) yield return Path.Combine(asmDir, "libmeshoptimizer.so");
    }

    [DllImport(Lib, CallingConvention = CallingConvention.Cdecl)]
    public static extern int meshopt_decodeVertexBuffer(void* destination, nuint vertexCount, nuint vertexSize,
                                                        byte* buffer, nuint bufferSize);

    [DllImport(Lib, CallingConvention = CallingConvention.Cdecl)]
    public static extern int meshopt_decodeIndexBuffer(void* destination, nuint indexCount, nuint indexSize,
                                                       byte* buffer, nuint bufferSize);

    [DllImport(Lib, CallingConvention = CallingConvention.Cdecl)]
    public static extern int meshopt_decodeIndexSequence(void* destination, nuint indexCount, nuint indexSize,
                                                         byte* buffer, nuint bufferSize);

    [DllImport(Lib, CallingConvention = CallingConvention.Cdecl)]
    public static extern int meshopt_decodeVertexVersion(byte* buffer, nuint bufferSize);

    [DllImport(Lib, CallingConvention = CallingConvention.Cdecl)]
    public static extern void meshopt_decodeFilterOct(void* buffer, nuint count, nuint stride);

    [DllImport(Lib, CallingConvention = CallingConvention.Cdecl)]
    public static extern void meshopt_decodeFilterQuat(void* buffer, nuint count, nuint stride);

    [DllImport(Lib, CallingConvention = CallingConvention.Cdecl)]
    public static extern void meshopt_decodeFilterExp(void* buffer, nuint count, nuint stride);

    [DllImport(Lib, CallingConvention = CallingConvention.Cdecl)]
    public static extern void meshopt_decodeFilterColor(void* buffer, nuint count, nuint stride);
}
