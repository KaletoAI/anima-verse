using System;
using System.IO;
using System.Linq;
using System.Text;

namespace AnimaNative.Update;

/// <summary>Linux argv before Godot consumes engine flags. Preserve argument boundaries, including empty values.</summary>
/// <remarks>AppRun starts the engine as <c>anima-native.x86_64 --log-file &lt;session&gt;.engine.log …</c> and the restarted
/// AppRun prepends a fresh pair, so a leading <c>--log-file &lt;path&gt;</c> pair is AppRun's own and is dropped here —
/// otherwise every update adds one more and the new session logs into the previous session's file.</remarks>
public static class RestartArguments
{
    public static string[] Current() => FromLinuxCommandLine(File.ReadAllBytes("/proc/self/cmdline"));

    public static string[] FromLinuxCommandLine(byte[] commandLine)
    {
        if (commandLine.Length == 0 || commandLine[^1] != 0)
            throw new InvalidDataException("Cannot read the original restart arguments.");
        var argv = Encoding.UTF8.GetString(commandLine, 0, commandLine.Length - 1).Split('\0');
        if (argv[0].Length == 0) throw new InvalidDataException("Missing original executable argument.");
        var start = 1;
        while (start + 1 < argv.Length && argv[start] == "--log-file") start += 2;
        return argv.Skip(start).ToArray();
    }
}
