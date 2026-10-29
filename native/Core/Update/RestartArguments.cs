using System;
using System.IO;
using System.Linq;
using System.Text;

namespace AnimaNative.Update;

/// <summary>Linux argv before Godot consumes engine flags. Preserve argument boundaries, including empty values.</summary>
public static class RestartArguments
{
    public static string[] Current() => FromLinuxCommandLine(File.ReadAllBytes("/proc/self/cmdline"));

    public static string[] FromLinuxCommandLine(byte[] commandLine)
    {
        if (commandLine.Length == 0 || commandLine[^1] != 0)
            throw new InvalidDataException("Cannot read the original restart arguments.");
        var argv = Encoding.UTF8.GetString(commandLine, 0, commandLine.Length - 1).Split('\0');
        if (argv[0].Length == 0) throw new InvalidDataException("Missing original executable argument.");
        return argv.Skip(1).ToArray();
    }
}
