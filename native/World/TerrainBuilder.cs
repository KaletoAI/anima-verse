using System;
using System.Collections.Generic;
using Godot;

namespace AnimaNative.World;

/// <summary>Counts of one built terrain grid.</summary>
public readonly record struct GridMeshStats(int Vertices, int Triangles);

/// <summary>
/// Terrain as plain height meshes: the overview grid for the whole world as ONE
/// mesh, plus each loaded 2 m tile as its own mesh. No surface textures, no
/// water, no LOD — one neutral vertex colour (S1a scope).
///
/// Where a fine tile is loaded, the overview cells it covers fully are left out,
/// so the two grids do not z-fight. The overview grid hangs on the world origin
/// and its step divides the 256 m tile (§ A16.5: 4 m, doubled while over
/// budget), so those cells line up with the tile edges exactly.
/// </summary>
public static class TerrainBuilder
{
    public static readonly Color OverviewColor = new(0.47f, 0.55f, 0.38f);
    public static readonly Color TileColor = new(0.50f, 0.58f, 0.40f);

    /// <summary>The overview mesh; <paramref name="covered"/> says which tiles are drawn finely.</summary>
    public static (MeshInstance3D Node, GridMeshStats Stats) BuildOverview(
        HeightGrid grid, double tileM, Func<(int, int), bool> covered)
    {
        bool Skip(int i, int j)
        {
            double x0 = grid.OriginX + i * grid.Step, z0 = grid.OriginZ + j * grid.Step;
            double x1 = x0 + grid.Step, z1 = z0 + grid.Step;
            int tx = (int)Math.Floor((x0 + x1) * 0.5 / tileM), tz = (int)Math.Floor((z0 + z1) * 0.5 / tileM);
            bool inside = x0 >= tx * tileM - 1e-6 && x1 <= (tx + 1) * tileM + 1e-6
                          && z0 >= tz * tileM - 1e-6 && z1 <= (tz + 1) * tileM + 1e-6;
            return inside && covered((tx, tz));
        }
        return Build(grid, OverviewColor, Skip, "TerrainOverview");
    }

    /// <summary>
    /// One fine tile. With <paramref name="water"/> and a wet tile (Wasser v2 K-A) every vertex stands on
    /// <c>liftedHeight(h, level, sd)</c> — the water variant's vertex lift, done once here instead of per frame —
    /// and carries the lift (metres of water over the bed, the browser's <c>vTlodWet</c>) in <c>UV2.x</c>; the
    /// node is tagged <c>wet</c> so the ground step dresses it in the water variant.
    /// </summary>
    public static (MeshInstance3D Node, GridMeshStats Stats) BuildTile(HeightTile tile, bool water = false)
    {
        var field = water && tile.Water is { } w && w.Wet > 0 ? w : null;
        var r = Build(tile.Grid, TileColor, (_, _) => false, $"TerrainTile_{tile.Key.Tx}_{tile.Key.Tz}", field);
        if (field is not null) r.Item1.SetMeta("wet", true);
        return r;
    }

    private static (MeshInstance3D, GridMeshStats) Build(HeightGrid g, Color color,
                                                         Func<int, int, bool> skipCell, string name,
                                                         Ground.WaterTileField? water = null)
    {
        int rows = g.Rows, cols = g.Cols;
        var node = new MeshInstance3D { Name = name };
        if (rows < 2 || cols < 2) return (node, new GridMeshStats(0, 0));

        var verts = new Vector3[rows * cols];
        var normals = new Vector3[rows * cols];
        var colors = new Color[rows * cols];
        var wet = water is not null ? new Vector2[rows * cols] : null;
        for (int j = 0; j < rows; j++)
        for (int i = 0; i < cols; i++)
        {
            int k = j * cols + i;
            float y = g.At(i, j);
            if (water is not null && wet is not null && water.Rows == rows && water.Cols == cols)
            {
                float lifted = (float)Ground.Water.Lifted(y, water.Level[k], water.Sd[k]);
                wet[k] = new Vector2(lifted - y, 0);
                y = lifted;
            }
            verts[k] = new Vector3((float)(g.OriginX + i * g.Step), y, (float)(g.OriginZ + j * g.Step));
            // Central differences (one-sided at the border): n = (-dh/dx, 1, -dh/dz).
            int i0 = Math.Max(i - 1, 0), i1 = Math.Min(i + 1, cols - 1);
            int j0 = Math.Max(j - 1, 0), j1 = Math.Min(j + 1, rows - 1);
            float dhdx = (g.At(i1, j) - g.At(i0, j)) / (float)((i1 - i0) * g.Step);
            float dhdz = (g.At(i, j1) - g.At(i, j0)) / (float)((j1 - j0) * g.Step);
            normals[k] = new Vector3(-dhdx, 1f, -dhdz).Normalized();
            colors[k] = color;
        }

        var indices = new List<int>((rows - 1) * (cols - 1) * 6);
        for (int j = 0; j < rows - 1; j++)
        for (int i = 0; i < cols - 1; i++)
        {
            if (skipCell(i, j)) continue;
            int a = j * cols + i, b = a + 1, c = a + cols, d = c + 1;
            // Godot's front faces wind CLOCKWISE seen from the viewer: from above
            // (x right, z down the screen) a → b → c is clockwise.
            indices.Add(a); indices.Add(b); indices.Add(c);
            indices.Add(b); indices.Add(d); indices.Add(c);
        }
        if (indices.Count == 0) return (node, new GridMeshStats(verts.Length, 0));

        var arrays = new Godot.Collections.Array();
        arrays.Resize((int)Mesh.ArrayType.Max);
        arrays[(int)Mesh.ArrayType.Vertex] = verts;
        arrays[(int)Mesh.ArrayType.Normal] = normals;
        arrays[(int)Mesh.ArrayType.Color] = colors;
        if (wet is not null) arrays[(int)Mesh.ArrayType.TexUV2] = wet;
        arrays[(int)Mesh.ArrayType.Index] = indices.ToArray();
        var mesh = new ArrayMesh();
        mesh.AddSurfaceFromArrays(Mesh.PrimitiveType.Triangles, arrays);
        mesh.SurfaceSetMaterial(0, Materials.VertexColor);
        node.Mesh = mesh;
        return (node, new GridMeshStats(verts.Length, indices.Count / 3));
    }
}

/// <summary>Shared untextured materials (one instance each, so draws can batch).</summary>
public static class Materials
{
    private static StandardMaterial3D? _vertexColor;

    /// <summary>Lit, albedo from the vertex colour, no texture.</summary>
    public static StandardMaterial3D VertexColor => _vertexColor ??= new StandardMaterial3D
    {
        VertexColorUseAsAlbedo = true,
        VertexColorIsSrgb = true,
        Roughness = 0.95f,
        Metallic = 0f,
    };
}
