# Local compute on the GPU

Since 2026-11-18, local compute jobs run on the GPU when the server process can use one, and on the CPU
otherwise. A local compute job is numeric work this server does itself (no hub job, no image backend). Today
that means the XPBD drape of the hair fits: HairDeck below the ear, and the HAAR strands. The module that owns
this is `app/core/gpu_compute.py`. Its docstring is the how-to for the next job that adopts it.

## The rule

A new local compute job is written once, as Taichi kernels, and runs through `gpu_compute.session(...)`. It
never calls `ti.init` itself and never picks a device itself. Everything below follows from that one choke
point:

- **Device.** `server.gpu_compute_device`:
  - `auto` (default) takes a *real* GPU through Vulkan.
  - `cpu` forces Taichi's CPU backend.
  - A software Vulkan device never counts as a GPU: llvmpipe/lavapipe, SwiftShader and gfxstream are excluded
    by their ICD manifest before Taichi starts, and by their device name after. This matters because a process
    that may not open the GPU otherwise gets llvmpipe, and Taichi still reports `Arch.vulkan`.
  - Whatever the outcome, the server logs ONE line saying where jobs run and why, e.g. "no access to
    /dev/dri/renderD128 — the server process lacks the 'render' group".
- **Concurrency.** `server.gpu_compute_parallel` caps how many jobs use the GPU at once.
  - The cap holds across the server *and* its refit worker processes, through slot files under
    `<instance>/.gpu-compute-slots`. This is the same `app/core/process_slots.py` mechanism as
    `server.blender_max_concurrent`.
  - A job that finds no free slot waits. It never falls back to the CPU on its own: the GPU result differs from
    the CPU result in its last bits, and waiting for one running drape beats a CPU run. The wait shows in the
    live progress line ("Waiting for the GPU").
- **Result records name their device** (`"device": {"arch", "name"}`, for the drape `report.push.drape_xpbd.device` /
  `report.drape.device` of a hair fit). **The device is never part of staleness**: a fit made on the CPU is not
  refitted because the GPU is now available, nor the other way round.
- **f32 only.** No f64 and no CPU-only Taichi features, so the kernels run unchanged on both architectures.
- **Few launches per step.**
  - On Vulkan every dependent kernel launch costs a barrier (~40–55 µs), whatever its size.
  - A job whose input would make thousands of tiny launches per step loses on the GPU. One example is the
    drape of an unwelded mesh with 3191 graph colours.
  - Such a job asks for the CPU arch with `cpu=True`. The drape does this above `drape.GPU_MAX_COLOURS`
    (256) colours. The decision depends on the input only, so the same input runs on the same arch on every
    machine.

## Getting the server onto the GPU (Linux)

The server process must be allowed to open the render node (`/dev/dri/renderD*`, group `render`).

- **No access yet:** add the user with `sudo usermod -aG render <user>`.
- **Member, but the login predates the membership:** `./start.sh` notices this case and starts uvicorn
  through `sg render`. `--status` and `--stop` work as before.
- **Checking it:** the expected device and the reason are at the end of the description of "Local compute
  device" in `/admin/settings` → Server. Each process also writes a `GPU compute: …` line to `logs/main.log` at
  its first job.
- **Docker:** see "Optional: the GPU for local compute jobs" in `docker/DEPLOYMENT.md`.

## Measured (2026-11-18, Radeon 8060S iGPU, 28 logical cores)

**One drape, GPU against the CPU arch.** The rows below are the drape alone (`t_run_s`, synchronised):

| Item | CPU arch, best thread count | Vulkan | CPU ↔ Vulkan over the free vertices: max / p99 / p50 |
|---|---|---|---|
| HairDeck Rosi | 8.3 s | 3.3 s | 23 / 0.46 / 0.001 mm |
| HairDeck Kira | 6.7 s | 3.5 s | 31 / 2.85 / 0.001 mm |
| HAAR Glut | 7.7 s | 2.1 s | 15 / 0.03 / 0.002 mm |

- Vulkan repeats itself exactly, run to run.
- The outliers are single vertices at chaotic contacts.
- The fit functions give the same gate verdicts on both devices. Checked with `fit_haar` on two strand sets
  (both refused for the same reason and count) and the HairDeck fits of Rosi and Kira (both accepted, the same
  max push).

**How many at once (`server.gpu_compute_parallel`, default 4).**

- **HairDeck drape of Rosi**, launch-bound: 1–8 processes at once, 3 rounds of 5 drapes each, machine load 11–20
  from other jobs.

| at once | one drape (median) | drapes per minute (median of the rounds) | GPU busy |
|---|---|---|---|
| 1 | 4.8 s | 8 | 24 % |
| 2 | 5.1 s | 17 | 36 % |
| 3 | 5.6 s | 26 | 56 % |
| 4 | 6.6 s | 31 | 72 % |
| 6 | 6.8 s | 47 | 84 % |
| 8 | 8.9 s | 46 | 88 % |

- **HAAR strand drape of Glut**, compute-bound: 1 round of 4 drapes each.

| at once | one drape (median) | drapes per minute | GPU busy |
|---|---|---|---|
| 1 | 2.1 s | 26 | 76 % |
| 2 | 3.7 s | 30 | 85 % |
| 4 | 7.2 s | 31 | 94 % |
| 6 | 10.6 s | 33 | 98 % |
| 8 | 14.1 s | 32 | 99 % |

The two kinds behave differently:

- **HairDeck: parallel pays while the GPU has headroom.**
  - The throughput grows up to 6 and is flat at 8. There one drape is slower than alone on the CPU (8.3 s).
  - The GPU never reached 100 %. Each job drives its launches from one CPU core, so the knee is the host side,
    at about 85 % GPU busy.
- **HAAR: one drape nearly fills the GPU.**
  - From 2 on, the throughput stays flat, and each drape only waits longer.
  - At 6, one drape takes longer than alone on the CPU (7.7 s).
- **4 is the largest count where no single drape of either kind is slower than on the CPU.** 6 would be the
  HairDeck-only answer: +50 % HairDeck throughput, but HAAR drapes 40 % slower than on the CPU.
- **A finer rule would let a job take several slots** (HAAR 2, HairDeck 1). It is not built.
- **Memory:** the drape buffers live in GTT (shared system memory), +0.2–0.5 GB per job.

## Threads on the CPU side

The CPU work of a fit takes `fit_kernels.threads()`. That covers:

- the numba kernels;
- the cKDTree `workers=` and pykdtree's OpenMP threads (`fit_kernels.kdtree`);
- the EDT;
- the drape when it runs on the CPU arch;
- in a refit worker, the onnxruntime session of a BiRefNet matte.

- **Refit workers** read a live budget that the server keeps current:
  - `refit_pool.fit_threads_for(n)` = `(cpu_count - 2) // n`, at most `refit_pool.FIT_THREADS_MAX`.
  - n is the number of fits computing right now.
  - A lone fit gets the full share, and n fits never oversubscribe the cores.
- **The kernels give the same bits for any thread count**, so the budget changes speed only, never a result.
- **Workers keep nice 10.**
- **pykdtree** reads `OMP_NUM_THREADS` once per process, so `fit_kernels.kdtree` sets the calling thread's
  OpenMP count before each tree.
- **onnxruntime** fixes its thread count per session. A worker's BiRefNet session is made for the budget and
  rebuilt when the budget is more than 1.5x off (~5 s).
- **Both follow the budget only once it is explicit** (a worker, a bench). The server process keeps their
  defaults.
- **Measured on the old fixed `OMP_NUM_THREADS=1`:**
  - a BiRefNet-DIS matte took 21–22 s, against 6.3 s on 16 threads and 7.8 s on 6;
  - an 8-nearest pykdtree query (400k points, 1.2M queries) took 5.4–6.9 s, against 0.30 s and 0.74 s.
- **Other OpenMP users** in a worker get the pool's fair share through `OMP_NUM_THREADS`.
