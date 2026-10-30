using System;
using System.Collections.Generic;
using AnimaNative.Ui;
using Godot;

namespace AnimaNative.Check;

public static class HitchCheck
{
    public static int Run(Viewport viewport)
    {
        var lines=new List<string>();
        double now=0;
        HitchLog.Init(viewport,()=>now); HitchLog.Armed=true;
        float oldScale=viewport.Scaling3DScale;
        try {
            viewport.Scaling3DScale=.7f;
            HitchLog.EndFrame(133.3,lines.Add);
            if(lines.Count!=1 || !lines[0].Contains("render scale 0.70")) throw new InvalidOperationException("hitch effective viewport scale");
            if(!lines[0].Contains("focus no") && !lines[0].Contains("focus yes")) throw new InvalidOperationException("hitch missing window focus");
            if(!lines[0].Contains("visible no") && !lines[0].Contains("visible yes")) throw new InvalidOperationException("hitch missing drawable visibility");
            viewport.Scaling3DScale=1;
            HitchLog.EndFrame(100,lines.Add);
            if(!lines[1].Contains("render scale 1.00")) throw new InvalidOperationException("hitch follows effective resize scale");
            for(int i=0;i<348;i++) HitchLog.EndFrame(100,lines.Add);
            if(lines.Count!=300) throw new InvalidOperationException("hitch detail cap");
            now=60000; HitchLog.EndFrame(16,lines.Add);
            if(lines.Count!=301 || !lines[300].StartsWith($"hitches 60 s: n=350, unfocused={(DisplayServer.WindowIsFocused() ? 0 : 350)},")
                || !lines[300].Contains("p50 frame 100 ms, p50 gpu 0 ms")) throw new InvalidOperationException("hitch summary beyond detail cap");
            for(int i=0;i<4;i++) HitchLog.EndFrame(200,lines.Add);
            now=120000; HitchLog.EndFrame(16,lines.Add);
            if(lines.Count!=302 || !lines[301].StartsWith("hitches 60 s: n=4,") || !lines[301].Contains("p50 frame 200 ms")) throw new InvalidOperationException("hitch second window reset");
            now=180000; HitchLog.EndFrame(16,lines.Add);
            if(lines.Count!=302) throw new InvalidOperationException("hitch quiet window summary");
            HitchLog.Armed=false; HitchLog.EndFrame(133,lines.Add);
            if(lines.Count!=302) throw new InvalidOperationException("hitch unarmed window");
            return 9;
        } finally { viewport.Scaling3DScale=oldScale; HitchLog.Init(viewport); }
    }
}
