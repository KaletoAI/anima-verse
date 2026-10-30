/*
 * libanima_mallinfo.so — the one symbol the patched libcef.so imports instead of glibc's mallinfo().
 *
 * CEF's MemoryInfra dump (MallocDumpProvider::OnMemoryDump) adds mallinfo().arena + .hblkhd in signed 32 bits and
 * traps (ud2 -> SIGILL) when the sum passes 2 GiB. libcef.so is the browser process INSIDE the Godot process, so
 * Godot's own heap counts and the client died after long sessions. tools/patch_cef_mallinfo.py renames libcef's
 * import to `mallinf_` (gdCEF is loaded with RTLD_DEEPBIND, so a plain LD_PRELOAD of `mallinfo` is never consulted);
 * this answers with glibc's 64-bit mallinfo2() figures clamped so that no sum of two fields can overflow.
 * Preloaded by run.sh / AppRun for the client and, inherited, for CEF's helper processes.
 */
#include <limits.h>
#include <malloc.h>

static int clamp(size_t v) { return v > INT_MAX / 4 ? INT_MAX / 4 : (int)v; }

struct mallinfo mallinf_(void)
{
    struct mallinfo2 m = mallinfo2();
    struct mallinfo r;
    r.arena = clamp(m.arena);
    r.ordblks = clamp(m.ordblks);
    r.smblks = clamp(m.smblks);
    r.hblks = clamp(m.hblks);
    r.hblkhd = clamp(m.hblkhd);
    r.usmblks = clamp(m.usmblks);
    r.fsmblks = clamp(m.fsmblks);
    r.uordblks = clamp(m.uordblks);
    r.fordblks = clamp(m.fordblks);
    r.keepcost = clamp(m.keepcost);
    return r;
}
