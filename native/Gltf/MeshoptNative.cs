using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using Godot;

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
/// copies it there) and in <c>native/bin/</c> (runs from the project, where
/// the csproj build target compiles it).
/// </summary>
internal static unsafe class MeshoptNative
{
    private const string Lib = "meshoptimizer";

    static MeshoptNative()
    {
        NativeLibrary.SetDllImportResolver(typeof(MeshoptNative).Assembly, Resolve);
    }

    /// <summary>Force the static constructor (resolver registration) before the first call.</summary>
    public static void EnsureLoaded() => _ = meshopt_decodeVertexVersion(null, 0);

    private static IntPtr Resolve(string name, Assembly assembly, DllImportSearchPath? path)
    {
        if (name != Lib) return IntPtr.Zero;
        foreach (var candidate in Candidates())
            if (File.Exists(candidate) && NativeLibrary.TryLoad(candidate, out var handle)) return handle;
        throw new DllNotFoundException("libmeshoptimizer.so not found; looked in: " + string.Join(", ", Candidates()));
    }

    private static IEnumerable<string> Candidates()
    {
        var exeDir = Path.GetDirectoryName(OS.GetExecutablePath()) ?? ".";
        yield return Path.Combine(exeDir, "libmeshoptimizer.so");
        var res = ProjectSettings.GlobalizePath("res://");
        if (!string.IsNullOrEmpty(res) && Directory.Exists(res))
            yield return Path.Combine(res, "bin", "libmeshoptimizer.so");
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
