using System;
using System.Collections.Generic;
using System.Text.Json.Nodes;
using AnimaNative.Tests.Vectors;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 39 (E4-T4): unchanged TS row vectors, dispatched through shape-only adapters.</summary>
public class ScatterRowVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("scatter_rows"));
    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = ScatterRowVectorAdapters.Dispatch();
    public static TheoryData<string> Cases => VectorFile.Labels("scatter_rows");
    [Theory, MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);
    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}
