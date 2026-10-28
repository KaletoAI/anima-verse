using System;
using AnimaNative.Overview;
using AnimaNative.World;

namespace AnimaNative.Embody;

/// <summary>
/// Task 49 / E7-T4: worldHeight.ts rayGroundHit over the composite height sampler. One finest lattice cell
/// per horizontal march, clipped to the height slab widened by 1 m, at most 4096 steps and 40 bisections.
/// A grazing intra-cell extremum has the browser's same limitation; no dependency on CDLOD mesh resolution.
/// </summary>
public static class GroundRay
{
    public static Vec3? Hit(WorldHeight height, Vec3 origin, Vec3 direction)
    {
        double len = Math.Sqrt(direction.X*direction.X + direction.Y*direction.Y + direction.Z*direction.Z);
        if (!(len > 0) || !double.IsFinite(len)) return null;
        double ux=direction.X/len, uy=direction.Y/len, uz=direction.Z/len;
        double min=double.PositiveInfinity, max=double.NegativeInfinity, step=height.Overview.Grid.Step;
        void Include(HeightGrid grid)
        {
            foreach (float h in grid.Heights) { min=Math.Min(min,h); max=Math.Max(max,h); }
            if (grid.Step > 0 && (!(step > 0) || grid.Step < step)) step=grid.Step;
        }
        Include(height.Overview.Grid);
        foreach (var tile in height.Tiles) Include(tile.Grid);
        if (!double.IsFinite(min) || !double.IsFinite(max)) return null;
        min-=1; max+=1;
        double t0=0,t1=4000;
        if (Math.Abs(uy)>1e-9)
        {
            double a=(min-origin.Y)/uy, b=(max-origin.Y)/uy;
            t0=Math.Max(0,Math.Min(a,b)); t1=Math.Min(t1,Math.Max(a,b));
        }
        else if (origin.Y<min || origin.Y>max) return null;
        if (!(t1>t0)) return null;
        Vec3 At(double t) => new(origin.X+t*ux,origin.Y+t*uy,origin.Z+t*uz);
        double F(double t) { var p=At(t); return p.Y-height.GroundAt(p.X,p.Z); }
        if (F(t0)<=0) return At(t0);
        double hs=double.Hypot(ux,uz), dt=step>0 && hs>1e-9 ? step/hs : t1-t0;
        if (!(dt>0)) dt=t1-t0;
        if ((t1-t0)/dt>4096) dt=(t1-t0)/4096;
        double ta=t0;
        for (double tb=t0+dt;;tb+=dt)
        {
            tb=Math.Min(tb,t1);
            if (F(tb)<=0)
            {
                double lo=ta,hi=tb;
                for (int i=0;i<40;i++) { double mid=(lo+hi)/2; if (F(mid)>0) lo=mid; else hi=mid; }
                return At(hi);
            }
            ta=tb;
            if (tb>=t1) return null;
        }
    }
}
