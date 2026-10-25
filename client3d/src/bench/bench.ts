/** Browser-only driver. The shared JSON is bundled by Vite, never copied. */
import rawPath from '../../../shared/bench/camera_path_v1.json';
import type { Engine } from '../scene/engine';
import { loadPath, samplePath, type Vec3 } from './benchPath';
import { summarize, type BenchSample } from './benchStats';

export interface BenchEnvironment {
  output(result: Record<string, unknown>): void;
  anchor(): {pos: Vec3; locationId: string | null; heightSource: string};
  switches(scatter: boolean, water: boolean): () => void;
}

export function initBench(engine: Engine, env: BenchEnvironment): void {
  const params = new URLSearchParams(location.search);
  const api = {start, running: false, last: null as Record<string, unknown> | null};
  (window as unknown as {__bench: typeof api}).__bench = api;

  function start(): void {
    if (api.running) return;
    const path = loadPath(rawPath);
    const anchor = env.anchor();
    const flags = {bench: 'auto' === params.get('bench') ? 'auto' : 'manual',
      url: Object.fromEntries(params), hash: location.hash || '', goto: params.get('goto'), scatter: params.get('scatter') !== '0', water: params.get('water') !== '0'};
    const restore = env.switches(flags.scatter, flags.water);
    api.running = true;
    const samples: BenchSample[] = [];
    let phase: 'warm' | 'run' = 'warm';
    let elapsed = 0, warm = 0, sampleTime = 0;
    // Keep the existing orbit state intact for normal play after the run.
    const oldTarget = engine.target.clone();
    const oldDist = engine.dist, oldTargetDist = engine.targetDist;
    const oldYaw = engine.yaw, oldTargetYaw = engine.targetYaw;
    engine.benchFrame = dt => {
      if (phase === 'warm') {
        warm += dt;
        if (warm >= path.warmup) {phase = 'run'; elapsed = 0;}
      } else elapsed += dt;
      sampleTime = phase === 'run' ? Math.min(elapsed, path.duration) : 0;
    };
    engine.benchCamera = () => {
      const {pos, target} = samplePath(path, sampleTime);
      engine.target.set(...target).add({x:anchor.pos[0],y:anchor.pos[1],z:anchor.pos[2]});
      engine.camera.position.set(pos[0]+anchor.pos[0],pos[1]+anchor.pos[1],pos[2]+anchor.pos[2]);
      engine.camera.lookAt(engine.target);
      engine.camera.clearViewOffset();
      engine.dist = engine.targetDist = Math.hypot(...pos.map((v,i)=>v-target[i]));
    };
    engine.benchRendered = (dt,cpuMs,calls,tris) => {
      // The transition frame establishes t=0; only subsequent intervals count.
      if (phase !== 'run' || elapsed === 0) return;
      samples.push({dt,cpuMs,gpuMs:null,calls,tris});
      if (elapsed < path.duration) return;
      const summary = summarize(samples);
      api.last = {backend:'webgl', path:'shared/bench/camera_path_v1.json', pathVersion:path.version,
        duration:path.duration,warmup:path.warmup,flags,anchor,
        ua:navigator.userAgent,dpr:engine.renderer.getPixelRatio(),
        size:`${innerWidth}x${innerHeight}`, ...summary,
        fps:summary.fpsMean,gpuMs:null,draws:summary.callsMedian,triangles:summary.trisMedian};
      console.info('[bench] result ' + JSON.stringify(api.last));
      env.output(api.last);
      engine.benchFrame=undefined; engine.benchCamera=undefined; engine.benchRendered=undefined;
      engine.target.copy(oldTarget); engine.dist=oldDist; engine.targetDist=oldTargetDist;
      engine.yaw=oldYaw; engine.targetYaw=oldTargetYaw;
      restore(); api.running=false;
    };
    console.info(`[bench] warm-up ${path.warmup}s; drive ${path.duration}s`);
  }
  if (params.get('bench') === 'auto') requestAnimationFrame(start);
}
