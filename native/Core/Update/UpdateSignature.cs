using System;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;

namespace AnimaNative.Update;

/// <summary>Release signature of the update manifest: ECDSA P-256 / SHA-256 over <see cref="Canonical"/>, DER-encoded
/// (RFC 3279 sequence) in <c>static/native/version.json.sig</c>, produced by <c>native/tools/publish_appimage.py</c>.</summary>
/// <remarks>Fail closed: without a usable baked key, a signature file or a valid signature no update is offered and
/// nothing is installed. The canonical bytes are defined identically in <c>publish_appimage.py</c>
/// (<c>canonical_manifest</c>); <c>scripts/smoke_update_signing.py</c> carries a worked example.</remarks>
public static class UpdateSignature
{
    // ================= RELEASE SIGNING PUBLIC KEY =================
    // Base64 SubjectPublicKeyInfo (DER) of the ECDSA P-256 release key, exactly as printed by
    // native/tools/make_update_signing_key.py. Empty = this build verifies nothing and therefore never updates.
    public const string PublicKeySpki = "";
    // ==============================================================

    /// <summary>Largest accepted signature file; a DER ECDSA P-256 signature is at most 72 bytes.</summary>
    public const int MaxSignatureBytes = 256;

    /// <summary>The ONE canonical serialisation of the signed manifest fields (UTF-8, LF line ends, final LF):
    /// <c>anima-native-update-v1\nversion=&lt;version&gt;\nfile=&lt;file&gt;\nsize=&lt;decimal bytes&gt;\nsha256=&lt;lowercase hex&gt;\n</c>.
    /// <c>built_utc</c> is informational and not signed.</summary>
    public static byte[] Canonical(string version, string file, long size, string sha256)
        => Encoding.UTF8.GetBytes("anima-native-update-v1\n"
            + "version=" + version + "\n"
            + "file=" + file + "\n"
            + "size=" + size.ToString(CultureInfo.InvariantCulture) + "\n"
            + "sha256=" + sha256.ToLowerInvariant() + "\n");

    /// <summary>True when <paramref name="publicKeySpki"/> is a base64 SubjectPublicKeyInfo of a 256-bit EC key.</summary>
    public static bool IsConfigured(string? publicKeySpki)
    {
        using var key = LoadKey(publicKeySpki);
        return key is not null;
    }

    /// <summary>Verify a DER signature over the canonical bytes; any malformed input is simply "not valid".</summary>
    public static bool Verify(string? publicKeySpki, byte[] canonical, byte[]? signature)
    {
        if (signature is null || signature.Length == 0 || signature.Length > MaxSignatureBytes) return false;
        using var key = LoadKey(publicKeySpki);
        if (key is null) return false;
        try { return key.VerifyData(canonical, signature, HashAlgorithmName.SHA256, DSASignatureFormat.Rfc3279DerSequence); }
        catch (Exception) { return false; } // a malformed signature or a failing crypto backend: fail closed
    }

    private static ECDsa? LoadKey(string? publicKeySpki)
    {
        if (string.IsNullOrWhiteSpace(publicKeySpki)) return null;
        ECDsa? key = null;
        try
        {
            var spki = Convert.FromBase64String(publicKeySpki.Trim());
            key = ECDsa.Create();
            key.ImportSubjectPublicKeyInfo(spki, out var read);
            // Exactly one 256-bit EC key, nothing trailing: anything else is a configuration error.
            if (read != spki.Length || key.KeySize != 256) { key.Dispose(); return null; }
            return key;
        }
        catch (Exception)
        {
            // Bad base64, a non-key blob or a missing crypto backend all mean "no usable key": fail closed.
            key?.Dispose();
            return null;
        }
    }
}
