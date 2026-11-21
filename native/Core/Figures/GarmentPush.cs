using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using AnimaNative.Scene;

namespace AnimaNative.Figures;

/// <summary>
/// The pure half of the GPU garment push — the native twin of packages/scene-render/src/garmentCollision.ts
/// (<c>garmentKind</c>, <c>garmentCapsules</c>, <c>COLLIDE_GLSL_*</c>, <c>patchCollisionVertexShader</c>), own capsules
/// only (the partner block of the browser is a later stage). Godot-free; the Godot half is
/// <c>Figures/GarmentPushModifier.cs</c>.
///
/// THE SHADER TEXT. Godot has no <c>onBeforeCompile</c>: the push is inserted into the text of a spatial shader that
/// draws the garment's material (the StandardMaterial3D generator port <see cref="StandardShaderCode"/>, or a
/// ShaderMaterial's own code) — the declarations and the function before <c>vertex()</c>, the call as the LAST
/// statement of <c>vertex()</c> (<see cref="Inject"/>). The function is a line-by-line transcription of the browser's
/// GLSL (<c>GLSL_PASS_OWN</c>, <c>glslAxisOffset</c>, <c>GLSL_SETUP_OWN</c>, <c>glslSqueezeFunction</c> over the own list)
/// and so of <see cref="Collision.PushOutOfCapsules"/>; every constant comes from <see cref="Collision"/>. Two
/// differences, both forced by Godot: the unskinned position is the parameter <c>position</c> (Godot skins before
/// <c>vertex()</c> and has no <c>position</c> attribute — the caller passes <c>CUSTOM0.xyz</c>, the bind position the
/// mesh copy carries), and the <c>_COLLIDE</c> weight is <c>CUSTOM0.w</c> (1 where the GLB has none) instead of a
/// <c>COLLIDE_WEIGHT</c> attribute; the edition (plain / squeeze) is chosen when the text is built instead of by
/// <c>#ifdef</c>. native/tests/GarmentPushTests.cs executes this text against the TypeScript's vectors.
/// </summary>
public static class GarmentPush
{
    /// <summary>garmentCollision.ts <c>CLOTH_EXCLUDED_REGIONS</c>: the arm, the hair-only and the partner-only regions.</summary>
    public static readonly string[] ClothExcludedRegions =
        new[] { "arm" }.Concat(Collision.HairOnlyRegions).Concat(Collision.PartnerOnlyRegions).ToArray();

    /// <summary>The marker the inserted code carries (a text that holds it is not patched again).</summary>
    public const string Marker = "collidePush(";

    /// <summary><c>garmentKind</c> from a garment node's name alone (<c>garment_&lt;kind&gt;_…</c>); "" when it does not say.</summary>
    public static string KindFromName(string name)
    {
        var m = Regex.Match(name, "^garment_([^_]+)_");
        return m.Success ? m.Groups[1].Value : "";
    }

    /// <summary>
    /// <c>garmentCapsules(kind, bound)</c>: hair → the <see cref="Collision.HairRegions"/>; footwear and accessory →
    /// none; every other kind → all but <see cref="ClothExcludedRegions"/>; payload order, at most
    /// <see cref="Collision.CollideMax"/>.
    /// </summary>
    public static List<T> Capsules<T>(string? kind, IEnumerable<T> bound, Func<T, string> region)
    {
        if (kind is "footwear" or "accessory") return new List<T>();
        if (kind == "hair") return bound.Where(e => Collision.HairRegions.Contains(region(e))).Take(Collision.CollideMax).ToList();
        return bound.Where(e => !ClothExcludedRegions.Contains(region(e))).Take(Collision.CollideMax).ToList();
    }

    /// <summary><c>collidingGarmentMeshes</c>' test: a garment of this kind collides at all (a torso capsule would push it).</summary>
    public static bool Collides(string? kind) => Capsules(kind, new[] { "torso" }, r => r).Count > 0;

    /// <summary>The GLSL float literal of a number (<c>glslFloat</c>: always with a decimal point or an exponent).</summary>
    public static string Float(double v) => CutShader.Number(v);

    // ---- the GLSL (garmentCollision.ts, own list) ----------------------------------------------------------------

    /// <summary><c>COLLIDE_GLSL_DECLARATIONS</c> without the weight attribute, plus the squeeze constants.</summary>
    public static string Declarations => string.Join("\n", new[]
    {
        $"#define COLLIDE_MAX {Collision.CollideMax}",
        $"#define COLLIDE_PASSES {Collision.CollidePasses}",
        $"#define COLLIDE_EPS {Float(Collision.CollideEps)}",
        $"#define COLLIDE_MIN_D {Float(Collision.CollideMinD)}",
        $"#define SQUEEZE_ROUNDS {Collision.SqueezeRounds}",
        $"#define SQUEEZE_STEPS {Collision.SqueezeSteps}",
        $"#define SQUEEZE_MIN_N {Float(Collision.SqueezeMinN)}",
        "uniform vec4 collideA[ COLLIDE_MAX ];",
        "uniform vec4 collideB[ COLLIDE_MAX ];",
        "uniform vec4 collideBindA[ COLLIDE_MAX ];",
        "uniform vec4 collideBindB[ COLLIDE_MAX ];",
        "uniform int collideCount;",
    });

    /// <summary><c>GLSL_PASS_OWN</c>: one pass over the own list, bind rule included.</summary>
    public const string PassOwn = @"    for ( int i = 0; i < COLLIDE_MAX; i ++ ) {
      if ( i >= collideCount ) break;
      float ax = collideA[ i ].x;
      float ay = collideA[ i ].y;
      float az = collideA[ i ].z;
      float r = collideA[ i ].w;
      if ( collideBindA[ i ].w >= 0.0 ) {
        float bx = collideBindA[ i ].x;
        float by = collideBindA[ i ].y;
        float bz = collideBindA[ i ].z;
        float bbx = collideBindB[ i ].x - bx;
        float bby = collideBindB[ i ].y - by;
        float bbz = collideBindB[ i ].z - bz;
        float bpx = position.x - bx;
        float bpy = position.y - by;
        float bpz = position.z - bz;
        float bl2 = bbx * bbx + bby * bby + bbz * bbz;
        float bt = bl2 > COLLIDE_EPS ? clamp( ( bpx * bbx + bpy * bby + bpz * bbz ) / bl2, 0.0, 1.0 ) : 0.0;
        float ex = bpx - bbx * bt;
        float ey = bpy - bby * bt;
        float ez = bpz - bbz * bt;
        r = min( r, sqrt( ex * ex + ey * ey + ez * ez ) );
      }
      float abx = collideB[ i ].x - ax;
      float aby = collideB[ i ].y - ay;
      float abz = collideB[ i ].z - az;
      float apx = p.x - ax;
      float apy = p.y - ay;
      float apz = p.z - az;
      float len2 = abx * abx + aby * aby + abz * abz;
      float t = len2 > COLLIDE_EPS ? clamp( ( apx * abx + apy * aby + apz * abz ) / len2, 0.0, 1.0 ) : 0.0;
      float dx = apx - abx * t;
      float dy = apy - aby * t;
      float dz = apz - abz * t;
      float d = sqrt( dx * dx + dy * dy + dz * dz );
      if ( d < r && d > COLLIDE_MIN_D ) {
        float k = r / d - 1.0;
        p.x += dx * k;
        p.y += dy * k;
        p.z += dz * k;
      }
    }
";

    /// <summary><c>COLLIDE_GLSL_PASSES</c>.</summary>
    public static string Passes => "  for ( int it = 0; it < COLLIDE_PASSES; it ++ ) {\n" + PassOwn + "  }\n";

    /// <summary>The signature: the browser's <c>vec3 collidePush( vec3 p )</c> plus the unskinned position.</summary>
    private const string Signature = "vec3 collidePush( vec3 p, vec3 position ) {";

    /// <summary><c>COLLIDE_GLSL_FUNCTION</c>: the ordinary passes (cloth).</summary>
    public static string FunctionPlain => "\n" + Signature + "\n" + Passes + "  return p;\n}\n";

    /// <summary><c>glslAxisOffset(x, y, z, pad)</c> over the own list.</summary>
    public static string AxisOffset(string x, string y, string z, string pad) => string.Join("\n", new[]
    {
        "float ax = collideA[ i ].x;",
        "float ay = collideA[ i ].y;",
        "float az = collideA[ i ].z;",
        "float abx = collideB[ i ].x - ax;",
        "float aby = collideB[ i ].y - ay;",
        "float abz = collideB[ i ].z - az;",
        $"float apx = {x} - ax;",
        $"float apy = {y} - ay;",
        $"float apz = {z} - az;",
        "float len2 = abx * abx + aby * aby + abz * abz;",
        "float t = len2 > COLLIDE_EPS ? clamp( ( apx * abx + apy * aby + apz * abz ) / len2, 0.0, 1.0 ) : 0.0;",
        "float dx = apx - abx * t;",
        "float dy = apy - aby * t;",
        "float dz = apz - abz * t;",
        "float d = sqrt( dx * dx + dy * dy + dz * dz );",
    }.Select(line => pad + line));

    /// <summary><c>glslEach([GLSL_OWN], pad, body)</c>.</summary>
    private static string Each(string pad, string body)
        => $"{pad}for ( int i = 0; i < COLLIDE_MAX; i ++ ) {{\n{pad}  if ( i >= collideCount ) break;\n{body}{pad}}}\n";

    /// <summary><c>GLSL_SETUP_OWN</c>.</summary>
    private static string SetupOwn => @"    float r = collideA[ i ].w;
    if ( collideBindA[ i ].w >= 0.0 ) {
      float bx = collideBindA[ i ].x;
      float by = collideBindA[ i ].y;
      float bz = collideBindA[ i ].z;
      float bbx = collideBindB[ i ].x - bx;
      float bby = collideBindB[ i ].y - by;
      float bbz = collideBindB[ i ].z - bz;
      float bpx = position.x - bx;
      float bpy = position.y - by;
      float bpz = position.z - bz;
      float bl2 = bbx * bbx + bby * bby + bbz * bbz;
      float bt = bl2 > COLLIDE_EPS ? clamp( ( bpx * bbx + bpy * bby + bpz * bbz ) / bl2, 0.0, 1.0 ) : 0.0;
      float ex = bpx - bbx * bt;
      float ey = bpy - bby * bt;
      float ez = bpz - bbz * bt;
      r = min( r, sqrt( ex * ex + ey * ey + ez * ez ) );
    }
    sr[ i ] = r;
" + AxisOffset("p.x", "p.y", "p.z", "    ") + @"
    sIn[ i ] = d < r ? 1.0 : 0.0;
    sCount += sIn[ i ];
";

    /// <summary><c>COLLIDE_GLSL_FUNCTION_SQUEEZE</c> (<c>glslSqueezeFunction([GLSL_OWN], COLLIDE_GLSL_PASSES)</c>): hair.</summary>
    public static string FunctionSqueeze
    {
        get
        {
            var s = new StringBuilder();
            s.Append('\n').Append(Signature).Append('\n');
            s.Append("  float sr[ COLLIDE_MAX ];\n  float sIn[ COLLIDE_MAX ];\n");
            s.Append("  float sCount = 0.0;\n");
            s.Append(Each("  ", SetupOwn));
            s.Append(@"  float sDone = sCount < 0.5 ? 1.0 : 0.0;
  float qx = p.x;
  float qy = p.y;
  float qz = p.z;
  for ( int k = 0; k < SQUEEZE_ROUNDS; k ++ ) {
    if ( sDone > 0.5 ) break;
    float fail = 0.0;
    if ( k == 0 && sCount < 1.5 ) {
");
            s.Append(Each("      ", "        if ( sIn[ i ] > 0.5 ) {\n" + AxisOffset("p.x", "p.y", "p.z", "          ") + @"
          if ( d > COLLIDE_MIN_D ) {
            float kk = sr[ i ] / d - 1.0;
            qx = p.x + dx * kk;
            qy = p.y + dy * kk;
            qz = p.z + dz * kk;
          }
        }
"));
            s.Append(@"    } else {
      float nx = 0.0;
      float ny = 0.0;
      float nz = 0.0;
      float rMax = 0.0;
");
            s.Append(Each("      ", "        if ( sIn[ i ] > 0.5 ) {\n" + AxisOffset("p.x", "p.y", "p.z", "          ") + @"
          if ( d > COLLIDE_MIN_D ) {
            nx += dx / d;
            ny += dy / d;
            nz += dz / d;
          }
          rMax = sr[ i ] > rMax ? sr[ i ] : rMax;
        }
"));
            s.Append(@"      float nl = sqrt( nx * nx + ny * ny + nz * nz );
      if ( nl < SQUEEZE_MIN_N ) {
        fail = 1.0;
      } else {
        nx = nx / nl;
        ny = ny / nl;
        nz = nz / nl;
        float lo = 0.0;
        float hi = 2.0 * rMax;
        for ( int s = 0; s <= SQUEEZE_STEPS; s ++ ) {
          float tt = s == 0 ? hi : 0.5 * ( lo + hi );
          float ox = p.x + nx * tt;
          float oy = p.y + ny * tt;
          float oz = p.z + nz * tt;
          float clear = 1.0;
");
            s.Append(Each("          ", "            if ( sIn[ i ] > 0.5 ) {\n" + AxisOffset("ox", "oy", "oz", "              ") + @"
              if ( d < sr[ i ] ) clear = 0.0;
            }
"));
            s.Append(@"          if ( s == 0 ) {
            if ( clear < 0.5 ) {
              fail = 1.0;
              break;
            }
          } else if ( clear > 0.5 ) {
            hi = tt;
          } else {
            lo = tt;
          }
        }
        qx = p.x + nx * hi;
        qy = p.y + ny * hi;
        qz = p.z + nz * hi;
      }
    }
    if ( fail > 0.5 ) break;
    float added = 0.0;
");
            s.Append(Each("    ", "      if ( sIn[ i ] < 0.5 ) {\n" + AxisOffset("qx", "qy", "qz", "        ") + @"
        if ( d < sr[ i ] ) {
          sIn[ i ] = 1.0;
          added += 1.0;
        }
      }
"));
            s.Append(@"    sCount += added;
    if ( added < 0.5 || k == SQUEEZE_ROUNDS - 1 ) sDone = 1.0;
  }
  if ( sDone > 0.5 ) {
    p.x = qx;
    p.y = qy;
    p.z = qz;
  } else {
");
            s.Append(Passes).Append("  }\n  return p;\n}\n");
            return s.ToString();
        }
    }

    /// <summary>
    /// <c>COLLIDE_GLSL_APPLY</c> as Godot's LAST statement of <c>vertex()</c>: VERTEX there is the SKINNED position in
    /// the mesh instance's model space (what three calls <c>transformed</c> after <c>skinning_vertex</c>), CUSTOM0.xyz the
    /// unskinned one, CUSTOM0.w the <c>_COLLIDE</c> weight (1 without one).
    /// </summary>
    public const string Apply = "\t// Anima native: the garment push (garmentCollision.ts COLLIDE_GLSL_APPLY; CUSTOM0 = bind position, _COLLIDE).\n"
        + "\tVERTEX = mix( VERTEX, collidePush( VERTEX, CUSTOM0.xyz ), clamp( CUSTOM0.w, 0.0, 1.0 ) );\n";

    /// <summary>The block inserted before <c>vertex()</c>: declarations and the edition of the push.</summary>
    public static string Block(bool squeeze)
        => "\n// Anima native: the garment push (packages/scene-render garmentCollision.ts), capsules in the mesh's space.\n"
           + Declarations + "\n" + (squeeze ? FunctionSqueeze : FunctionPlain) + "\n";

    /// <summary>
    /// <c>patchCollisionVertexShader</c> for a Godot spatial shader: <see cref="Block"/> right before <c>void vertex()</c>
    /// and <see cref="Apply"/> as its last statement (a shader without <c>vertex()</c> gets one at its end). Throws
    /// <see cref="ArgumentException"/> when the push cannot be inserted faithfully: already patched, not spatial, a
    /// render mode that changes VERTEX's space (<c>skip_vertex_transform</c>, <c>world_vertex_coords</c>), CUSTOM0 already
    /// in use, a <c>return</c> inside <c>vertex()</c> (it would skip the push), or unbalanced braces.
    /// </summary>
    public static string Inject(string code, bool squeeze)
    {
        if (code.Contains(Marker, StringComparison.Ordinal)) throw new ArgumentException("already patched");
        if (!Regex.IsMatch(code, @"shader_type\s+spatial\s*;")) throw new ArgumentException("not a spatial shader");
        if (code.Contains("skip_vertex_transform", StringComparison.Ordinal) || code.Contains("world_vertex_coords", StringComparison.Ordinal))
            throw new ArgumentException("a render mode that moves VERTEX out of model space");
        if (code.Contains("CUSTOM0", StringComparison.Ordinal)) throw new ArgumentException("CUSTOM0 already in use");
        var v = Regex.Match(code, @"void\s+vertex\s*\(\s*\)\s*\{");
        if (!v.Success) return code.TrimEnd('\n') + "\n" + Block(squeeze) + "void vertex() {\n" + Apply + "}\n";
        int open = v.Index + v.Length - 1;
        int depth = 0, close = -1;
        for (int i = open; i < code.Length; i++)
        {
            if (code[i] == '{') depth++;
            else if (code[i] == '}' && --depth == 0) { close = i; break; }
        }
        if (close < 0) throw new ArgumentException("vertex() without its closing brace");
        if (Regex.IsMatch(code.Substring(open, close - open), @"\breturn\b")) throw new ArgumentException("a return inside vertex()");
        var body = code.Substring(0, close);
        if (!body.EndsWith('\n')) body += "\n";
        return code.Substring(0, v.Index) + Block(squeeze) + body.Substring(v.Index) + Apply + code.Substring(close);
    }
}
