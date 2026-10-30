using System;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Text.Json;

namespace AnimaNative.Cache;

/// <summary>Task 64 / E10-T3: length-safe, culture-independent dependency keys inside format v1.
/// A plan hashes the effective set-selected library; a fit hashes its source projection plus standing reference,
/// so a changed unused clip cannot invalidate a template and an unrelated fit can survive a plan change.</summary>
public static class DerivedKeys
{
    /// <summary>Task 64: bump whenever retarget, relock, ground measurement, plan rules or fitting inputs change
    /// (ClipLibrary.Compute/Write, TemplateClips, RestAdapter, BridgeFit or their core math). ONE fit version
    /// governs both plan and fitted-resource entries; never add a separate plan/ground/relock version.</summary>
    public const int FitCodeVersion = 2;
    /// <summary>Task 64: bump when FBX import or source/rig extraction changes.</summary>
    public const int ClipImportVersion = 1;
    public static string Hash(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes));
    public static string Of(params object?[] values) => Hash(JsonSerializer.SerializeToUtf8Bytes(values));
    public static string Template(string modelUrl, IReadOnlyList<string> sets, double height, string rig, string model)
        => Of(FitCodeVersion, ClipImportVersion, modelUrl, sets, BitConverter.DoubleToInt64Bits(height), rig, model);
}
