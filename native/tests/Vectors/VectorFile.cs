using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Xunit;
using Xunit.Sdk;

namespace AnimaNative.Tests.Vectors;

/// <summary>A vector file that breaks the rules of format <c>anima-test-vectors/1</c>.</summary>
public sealed class VectorFormatException : Exception
{
    public VectorFormatException(string message, Exception? inner = null) : base(message, inner) { }
}

/// <summary>One case of a vector file; <see cref="Args"/> are unresolved (see <see cref="VectorFile.ResolveArgs(VectorCase)"/>).</summary>
public sealed record VectorCase(string Label, string Fn, JsonArray Args, JsonNode? Expect, double Eps)
{
    /// <summary>The expectation is <c>{"$throws": true}</c>: the call must throw.</summary>
    public bool ExpectsThrow => Expect is JsonObject o && o.Count == 1 && o.ContainsKey(VectorFile.ThrowsKey);

    /// <summary>xUnit shows the label as the theory row's argument.</summary>
    public override string ToString() => Label;
}

/// <summary>
/// Loader and runner for the shared test vectors, the C# twin of shared/test-vectors/vectors.mjs
/// (spec: shared/test-vectors/README.md). Loading validates the whole file and throws
/// <see cref="VectorFormatException"/>, never skips. A vector test class holds a dispatch table
/// <c>fn → Func&lt;JsonArray, JsonNode?&gt;</c> and one theory over the case labels:
/// <code>
/// public static TheoryData&lt;string&gt; Cases => VectorFile.Labels("bench_math");
/// [Theory, MemberData(nameof(Cases))]
/// public void Case(string label) => File.Value.AssertCase(label, Dispatch);
/// </code>
/// A case whose <c>fn</c> is missing from the table fails with its label.
/// </summary>
public sealed class VectorFile
{
    public const string Format = "anima-test-vectors/1";
    public const double DefaultEps = 1e-9;
    internal const string ThrowsKey = "$throws";
    private const string FixtureKey = "$fixture";
    private const string WithKey = "$with";

    private static readonly Regex NamePattern = new("^[a-z0-9_]+$", RegexOptions.CultureInvariant);
    private static readonly Lazy<string> VectorDir = new(FindVectorDir);

    /// <summary>Where the file came from, used in messages.</summary>
    public string Origin { get; }

    /// <summary>Repo path of the smoke holding the hand derivations.</summary>
    public string Source { get; }

    public JsonObject Fixtures { get; }

    public IReadOnlyList<VectorCase> Cases { get; }

    private VectorFile(string origin, string source, JsonObject fixtures, IReadOnlyList<VectorCase> cases)
    {
        Origin = origin;
        Source = source;
        Fixtures = fixtures;
        Cases = cases;
    }

    // ---- loading ------------------------------------------------------------------------------

    /// <summary><c>&lt;repo&gt;/shared/test-vectors</c>, found by walking up from the test assembly.</summary>
    public static string Directory => VectorDir.Value;

    private static string FindVectorDir()
    {
        for (var dir = new DirectoryInfo(AppContext.BaseDirectory); dir is not null; dir = dir.Parent)
        {
            var candidate = Path.Combine(dir.FullName, "shared", "test-vectors");
            if (System.IO.Directory.Exists(candidate)) return candidate;
        }
        throw new VectorFormatException($"no shared/test-vectors above {AppContext.BaseDirectory}");
    }

    /// <summary>Load <c>shared/test-vectors/&lt;name&gt;.json</c> (name: lowercase letters, digits, underscores).</summary>
    public static VectorFile Load(string name)
    {
        if (!NamePattern.IsMatch(name)) throw new VectorFormatException($"bad vector file name \"{name}\"");
        return LoadPath(Path.Combine(Directory, name + ".json"));
    }

    /// <summary>Load a vector file by path.</summary>
    public static VectorFile LoadPath(string path)
    {
        string text;
        try { text = File.ReadAllText(path); }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException)
        {
            throw new VectorFormatException($"{path}: cannot read ({e.Message})", e);
        }
        return Parse(text, path);
    }

    /// <summary>The case labels of a file, as theory data (loading validates the file).</summary>
    public static TheoryData<string> Labels(string name)
    {
        var data = new TheoryData<string>();
        foreach (var c in Load(name).Cases) data.Add(c.Label);
        return data;
    }

    /// <summary>Parse and validate vector JSON text; <paramref name="origin"/> names it in errors.</summary>
    public static VectorFile Parse(string text, string origin = "<vectors>")
    {
        JsonNode? root;
        try
        {
            // Strict JSON like JSON.parse: no comments, no trailing commas, no NaN/Infinity literals.
            root = JsonNode.Parse(text, documentOptions: new JsonDocumentOptions
            {
                CommentHandling = JsonCommentHandling.Disallow,
                AllowTrailingCommas = false,
            });
        }
        catch (JsonException e)
        {
            throw new VectorFormatException($"{origin}: not valid JSON ({e.Message})", e);
        }
        try
        {
            return Validate(root, origin);
        }
        catch (ArgumentException e)
        {
            // System.Text.Json materialises a JsonObject lazily and throws on a duplicate key then.
            throw new VectorFormatException($"{origin}: {e.Message}", e);
        }
    }

    private static VectorFile Validate(JsonNode? root, string origin)
    {
        void Fail(string msg) => throw new VectorFormatException($"{origin}: {msg}");

        // First, because walking materialises every object (duplicate keys surface here).
        AssertFinite(root, origin);

        if (root is not JsonObject data) { Fail("top level must be an object"); return null!; }
        if (!(data.TryGetPropertyValue("format", out var format) && IsString(format, out var f) && f == Format))
            Fail($"format must be \"{Format}\", got {(data.ContainsKey("format") ? VectorCompare.Show(format) : "<missing>")}");
        if (!(data.TryGetPropertyValue("source", out var src) && IsString(src, out var source) && source.Length > 0))
        {
            Fail("\"source\" must name the smoke holding the derivations");
            return null!;
        }

        var fixtures = new JsonObject();
        if (data.TryGetPropertyValue("fixtures", out var fx))
        {
            if (fx is not JsonObject fo) Fail("\"fixtures\" must be an object");
            else fixtures = fo;
        }
        if (!(data.TryGetPropertyValue("cases", out var cs) && cs is JsonArray rawCases && rawCases.Count > 0))
        {
            Fail("\"cases\" must be a non-empty array");
            return null!;
        }

        var labels = new HashSet<string>(StringComparer.Ordinal);
        var cases = new List<VectorCase>();
        for (int i = 0; i < rawCases.Count; i++)
        {
            if (rawCases[i] is not JsonObject c) { Fail($"case #{i} must be an object"); return null!; }
            if (!(c.TryGetPropertyValue("label", out var l) && IsString(l, out var label) && label.Length > 0))
            {
                Fail($"case #{i} needs a non-empty \"label\"");
                return null!;
            }
            if (!labels.Add(label)) Fail($"duplicate label \"{label}\"");
            if (!(c.TryGetPropertyValue("fn", out var fnNode) && IsString(fnNode, out var fn) && fn.Length > 0))
            {
                Fail($"\"{label}\" needs a non-empty \"fn\"");
                return null!;
            }
            if (!(c.TryGetPropertyValue("args", out var a) && a is JsonArray args))
            {
                Fail($"\"{label}\" needs an \"args\" array");
                return null!;
            }
            if (!c.TryGetPropertyValue("expect", out var expect)) Fail($"\"{label}\" needs an \"expect\"");

            double eps = DefaultEps;
            if (c.TryGetPropertyValue("eps", out var epsNode)
                && !(VectorCompare.TryNum(epsNode, out eps) && eps >= 0))
                Fail($"\"{label}\": \"eps\" must be a number >= 0");

            if (expect is JsonObject eo && eo.ContainsKey(ThrowsKey)
                && !(eo.Count == 1 && eo[ThrowsKey] is JsonValue tv && tv.TryGetValue(out JsonElement te)
                     && te.ValueKind == JsonValueKind.True))
                Fail($"\"{label}\": a throw expectation is exactly {{\"$throws\": true}}");

            // Resolve once at load so a dangling $fixture is a load error, not a run-time one.
            try { ResolveArgs(args, fixtures); }
            catch (VectorFormatException e) { Fail($"\"{label}\": {e.Message}"); }

            cases.Add(new VectorCase(label, fn, args, expect, eps));
        }
        return new VectorFile(origin, source, fixtures, cases);
    }

    private static bool IsString(JsonNode? node, out string s)
    {
        s = "";
        if (node is JsonValue v && v.TryGetValue(out JsonElement el) && el.ValueKind == JsonValueKind.String)
        {
            s = el.GetString()!;
            return true;
        }
        return false;
    }

    /// <summary>Throw on any non-finite number: JSON allows 1e400, which parses to Infinity.</summary>
    private static void AssertFinite(JsonNode? node, string where)
    {
        switch (node)
        {
            case JsonArray a:
                for (int i = 0; i < a.Count; i++) AssertFinite(a[i], $"{where}[{i}]");
                break;
            case JsonObject o:
                foreach (var (k, v) in o) AssertFinite(v, $"{where}.{k}");
                break;
            default:
                if (VectorCompare.TryNum(node, out double d) && !double.IsFinite(d))
                    throw new VectorFormatException($"{where}: non-finite number {d} is not allowed");
                break;
        }
    }

    // ---- fixtures -----------------------------------------------------------------------------

    /// <summary>The case's arguments with every fixture reference replaced by a fresh copy.</summary>
    public JsonArray ResolveArgs(VectorCase c) => ResolveArgs(c.Args, Fixtures);

    /// <summary>
    /// Replace every <c>{"$fixture": NAME}</c> (optionally with <c>"$with": {...}</c>) at any depth of
    /// <paramref name="args"/> by a deep copy of <c>fixtures[NAME]</c>; <c>$with</c> overrides the
    /// top-level keys of an object fixture. Always returns a new tree.
    /// </summary>
    public static JsonArray ResolveArgs(JsonArray args, JsonObject fixtures) => (JsonArray)DecodeSentinels(Walk(args, fixtures))!;

    // Decode only arguments, after expansion; raw fixtures and expectations stay JSON.
    // JsonElement.Undefined distinguishes JS undefined from JSON null without changing
    // the JsonArray dispatch API. Numeric sentinels are ordinary CLR double JsonValues.
    private static JsonNode? DecodeSentinels(JsonNode? node)
    {
        if (node is JsonArray a)
            return new JsonArray(a.Select(DecodeSentinels).ToArray());
        if (node is JsonObject o)
        {
            var result = new JsonObject();
            foreach (var (k, v) in o) result[k] = DecodeSentinels(v);
            return result;
        }
        if (IsString(node, out var s))
            return s switch
            {
                "$NaN" => JsonValue.Create(double.NaN),
                "$Infinity" => JsonValue.Create(double.PositiveInfinity),
                "$-Infinity" => JsonValue.Create(double.NegativeInfinity),
                "$undefined" => JsonValue.Create(default(JsonElement)),
                _ => node?.DeepClone(),
            };
        return node?.DeepClone();
    }

    private static JsonNode? Walk(JsonNode? node, JsonObject fixtures)
    {
        switch (node)
        {
            case JsonArray a:
                return new JsonArray(a.Select(x => Walk(x, fixtures)).ToArray());
            case JsonObject o when o.ContainsKey(FixtureKey):
            {
                var extra = o.Select(kv => kv.Key).Where(k => k != FixtureKey && k != WithKey).ToList();
                if (extra.Count > 0) throw new VectorFormatException($"fixture reference has stray keys {string.Join(", ", extra)}");
                if (!IsString(o[FixtureKey], out var name) || !fixtures.TryGetPropertyValue(name, out var fixture))
                    throw new VectorFormatException($"unknown fixture {VectorCompare.Show(o[FixtureKey])}");
                var copy = fixture?.DeepClone();
                if (!o.TryGetPropertyValue(WithKey, out var with)) return copy;
                if (with is not JsonObject wo) throw new VectorFormatException($"\"$with\" of fixture \"{name}\" must be an object");
                if (copy is not JsonObject co) throw new VectorFormatException($"\"$with\" needs an object fixture, \"{name}\" is not one");
                foreach (var (k, v) in wo) co[k] = v?.DeepClone();
                return co;
            }
            case JsonObject o:
            {
                var result = new JsonObject();
                foreach (var (k, v) in o) result[k] = Walk(v, fixtures);
                return result;
            }
            default:
                return node?.DeepClone();
        }
    }

    // ---- running ------------------------------------------------------------------------------

    /// <summary>The case with this label; throws when there is none.</summary>
    public VectorCase Case(string label)
        => Cases.FirstOrDefault(c => c.Label == label)
           ?? throw new XunitException($"{Origin}: no case labelled \"{label}\"");

    /// <summary>The fn names of this file that <paramref name="dispatch"/> does not know, in file order.</summary>
    public IReadOnlyList<string> MissingFunctions(IReadOnlyDictionary<string, Func<JsonArray, JsonNode?>> dispatch)
        => Cases.Select(c => c.Fn).Distinct().Where(fn => !dispatch.ContainsKey(fn)).ToList();

    /// <summary>
    /// Run one case; null when it passes, else the failure message (label, expected, actual, first
    /// difference). A fn missing from <paramref name="dispatch"/> is a failure, never a skip.
    /// </summary>
    public string? Check(VectorCase c, IReadOnlyDictionary<string, Func<JsonArray, JsonNode?>> dispatch)
    {
        if (!dispatch.TryGetValue(c.Fn, out var fn))
            return $"vector case \"{c.Label}\" ({Origin}) calls fn \"{c.Fn}\", which is not in the dispatch table";

        JsonNode? actual = null;
        Exception? threw = null;
        try { actual = fn(ResolveArgs(c)); }
        catch (Exception e) { threw = e; }

        string diff;
        if (c.ExpectsThrow)
        {
            if (threw is not null) return null;
            diff = $"expected a throw, returned {VectorCompare.Show(actual)}";
        }
        else if (threw is not null)
        {
            diff = $"threw {threw.GetType().Name}: {threw.Message}";
        }
        else if (VectorCompare.Near(c.Expect, actual, c.Eps, out diff))
        {
            return null;
        }
        string actualText = threw is not null ? $"<threw {threw.GetType().Name}: {threw.Message}>" : VectorCompare.Show(actual);
        return $"FAIL {c.Label} ({Origin}, source {Source})\n"
               + $"     expected: {VectorCompare.Show(c.Expect)}\n"
               + $"     actual:   {actualText}\n"
               + $"     {diff}";
    }

    /// <summary>Run the case with this label and fail the test with the message of <see cref="Check"/>.</summary>
    public void AssertCase(string label, IReadOnlyDictionary<string, Func<JsonArray, JsonNode?>> dispatch)
    {
        var failure = Check(Case(label), dispatch);
        if (failure is not null) throw new XunitException(failure);
    }
}
