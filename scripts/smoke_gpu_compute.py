#!/usr/bin/env python3
"""GPU compute with a CPU fallback (``app/core/gpu_compute.py``) — device resolution, the cross-process GPU slots,
the arch switch for launch-bound jobs. No world, no server, no storage.

Usage: ./.venv/bin/python scripts/smoke_gpu_compute.py
       (the GPU parts need a usable GPU: on Linux the process needs the ``render`` group — ``sg render -c "<cmd>"``.
       Without one they print SKIP and the smoke still exits 0.)

Every expectation follows from the module docstring:

[G1] ``hardware_icds`` on a folder of hand-made ICD manifests (``VK_DRIVER_FILES`` names them): libvulkan_radeon.so,
     libGLX_nvidia.so.0 and libvulkan_intel.so are hardware; libvulkan_lvp.so (lavapipe/llvmpipe),
     libvk_swiftshader.so and libvulkan_gfxstream.so are software -> hardware = [radeon, nvidia, intel] (that order:
     the list's order), software = [lvp, swiftshader, gfxstream]. No vendor is named in the rule, so the NVIDIA
     manifest counts like the Radeon one.
[G2] Device resolution, each in a child process (Taichi's arch is per process):
     (a) ``server.gpu_compute_device`` pinned to ``cpu`` -> ``{"arch": "cpu", "reason": "server.gpu_compute_device =
         cpu"}``, Taichi on its CPU arch;
     (b) ``auto`` with only a SOFTWARE driver visible (``VK_DRIVER_FILES`` = the system's lavapipe manifest) -> cpu,
         reason "no hardware Vulkan driver installed (only software: ...)" — never llvmpipe;
     (c) ``auto`` as this process is: a render node this process may open -> vulkan with a device name that is no
         software rasteriser; none -> cpu with ``render_access()``'s reason (it names the group the process lacks).
[G3] The cross-process slots (GPU part): limit pinned to 1 in a temp folder; this process holds the only slot (a
     plain ``process_slots.try_slots``) and releases it after 1.0 s while a drape asks for it -> the drape runs on
     vulkan, ``report.t_slot_wait_s`` in [1.0, 1.0 + 2 x 0.25 + 0.5] (one poll interval of slack per side plus
     scheduling), and the live progress line of the open scope read "Waiting for the GPU" while it waited.
[G4] The arch switch (GPU part, rule 3): drape A (X2 of smoke_drape_xpbd: a 5 x 5 patch on a sphere) on vulkan;
     the same drape with ``drape.GPU_MAX_COLOURS`` patched to 0 (every drape is launch-bound now) -> its report
     says arch cpu with reason "the job asked for the CPU"; then A again -> vulkan, and bit-equal to the first
     vulkan run (Vulkan is run-to-run deterministic). The CPU run satisfies the same geometry as the GPU run (every
     vertex at |p| >= 0.103: clear 0.004 minus 1 mm grid slack) — the two differ only in their last bits.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def child_device(env_extra, pin_cpu=False):
    code = ("import json, sys; sys.path.insert(0, %r)\n"
            "from app.core import gpu_compute\n"
            "%s"
            "print('DEVICE ' + json.dumps(gpu_compute.device()))\n") % (
        str(ROOT), "gpu_compute.pin((None, 1, 'cpu'))\n" if pin_cpu else "")
    env = dict(os.environ, **env_extra)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT), env=env,
                         timeout=300)
    rows = [ln[7:] for ln in out.stdout.splitlines() if ln.startswith("DEVICE ")]
    return (json.loads(rows[-1]) if rows else None), out


def g1():
    from app.core import gpu_compute
    libs = {"radeon_icd.json": "libvulkan_radeon.so", "nvidia_icd.json": "libGLX_nvidia.so.0",
            "intel_icd.json": "libvulkan_intel.so", "lvp_icd.json": "libvulkan_lvp.so",
            "vk_swiftshader_icd.json": "libvk_swiftshader.so", "gfxstream_vk_icd.json": "libvulkan_gfxstream.so"}
    with tempfile.TemporaryDirectory(prefix="icd-") as tmp:
        files = []
        for name, lib in libs.items():
            p = Path(tmp) / name
            p.write_text(json.dumps({"ICD": {"api_version": "1.4.318", "library_path": lib},
                                     "file_format_version": "1.0.1"}))
            files.append(str(p))
        saved = {k: os.environ.get(k) for k in ("VK_DRIVER_FILES", "VK_ICD_FILENAMES")}
        os.environ["VK_DRIVER_FILES"] = ":".join(files)
        try:
            hw, sw = gpu_compute.hardware_icds()
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    hw_n, sw_n = [Path(p).name for p in hw], [Path(p).name for p in sw]
    check(hw_n == ["radeon_icd.json", "nvidia_icd.json", "intel_icd.json"],
          f"[G1] hardware: {hw_n}")
    check(sw_n == ["lvp_icd.json", "vk_swiftshader_icd.json", "gfxstream_vk_icd.json"], f"[G1] software: {sw_n}")


def g2():
    from app.core import gpu_compute
    dev, out = child_device({}, pin_cpu=True)
    check(dev is not None and dev["arch"] == "cpu" and dev.get("reason") == "server.gpu_compute_device = cpu",
          f"[G2a] pinned cpu: {dev or out.stderr[-400:]}")
    lvp = next((d / "lvp_icd.json" for d in gpu_compute.icd_dirs() if (d / "lvp_icd.json").is_file()), None)
    if lvp is None:
        print("SKIP [G2b] no lavapipe manifest installed on this machine")
    else:
        dev, out = child_device({"VK_DRIVER_FILES": str(lvp), "VK_ICD_FILENAMES": str(lvp)})
        check(dev is not None and dev["arch"] == "cpu"
              and dev.get("reason", "").startswith("no hardware Vulkan driver installed (only software: lvp_icd"),
              f"[G2b] only lavapipe visible -> cpu: {dev or out.stderr[-400:]}")
    access = gpu_compute.render_access()
    dev, out = child_device({})
    if access["usable"]:
        check(dev is not None and dev["arch"] == "vulkan" and not gpu_compute.SOFTWARE_DEVICE.search(dev["name"]),
              f"[G2c] render node usable -> a hardware Vulkan device: {dev or out.stderr[-400:]}")
    else:
        check(dev is not None and dev["arch"] == "cpu" and dev.get("reason") == access["reason"]
              and "GPU compute: CPU" in out.stderr,
              f"[G2c] no usable render node -> cpu, reason {dev and dev.get('reason')!r}, one log line")
    return dev is not None and dev["arch"] == "vulkan"


def x2_drape():
    from app.core import drape
    from app.core.garment_fit import Sdf
    lo = np.array([-0.14, -0.14, -0.14])
    n = np.ceil((np.array([0.14, 0.20, 0.14]) - lo) / 0.002).astype(int) + 1
    ax = [lo[i] + 0.002 * np.arange(n[i]) for i in range(3)]
    gx, gy, gz = np.meshgrid(*ax, indexing="ij")
    field = Sdf(field=np.sqrt(gx * gx + gy * gy + gz * gz) - 0.10, lo=lo, vox=0.002)
    xs, zs = np.meshgrid(np.arange(5) * 0.01, np.arange(5) * 0.01, indexing="ij")
    X = np.stack([xs.ravel(), np.zeros(25), zs.ravel()], 1) + np.array([-0.02, 0.15, -0.02])
    F = []
    for i in range(4):
        for k in range(4):
            a, b, c, d = i * 5 + k, (i + 1) * 5 + k, (i + 1) * 5 + k + 1, i * 5 + k + 1
            F += [[a, b, c], [a, c, d]]
    p = drape.DrapeParams(substeps=1500, dt=1e-3, gravity=9.81, a_stretch=0.0, a_bend=1e-4, damp=0.02, mu=0.6,
                          grow=0.0, max_push=0.001, lmax=0.0)
    return drape.run(X, np.array(F), X.copy(), np.zeros(25, bool), field, p, clear=0.004)


def g3():
    from app.core import cpu_progress, gpu_compute, process_slots
    with tempfile.TemporaryDirectory(prefix="gpu-slots-") as tmp:
        gpu_compute.pin((tmp, 1, "auto"))
        try:
            x2_drape()                                   # warm: resolve + compile outside the timed wait
            fd = process_slots.try_slots(Path(tmp), 1)
            lines = []
            stop = threading.Event()

            def watch():
                while not stop.is_set():
                    snap = cpu_progress.snapshot("smoke:gpu")
                    if snap:
                        lines.append(snap.get("line", ""))
                    time.sleep(0.05)
            th = threading.Thread(target=watch, daemon=True)
            timer = threading.Timer(1.0, lambda: os.close(fd))
            with cpu_progress.scope("smoke:gpu"):
                th.start()
                timer.start()
                res = x2_drape()
            stop.set()
            th.join()
            timer.join()
        finally:
            gpu_compute.pin(None)
    w = res.report["t_slot_wait_s"]
    check(fd is not None and res.report["device"]["arch"] == "vulkan" and 1.0 <= w <= 2.0,
          f"[G3] the only slot held 1 s by this process: the drape waited {w} s on {res.report['device']}")
    check(any("Waiting for the GPU" in ln for ln in lines),
          f"[G3] the live line said so while waiting: {sorted(set(lines))[:3]}")


def g4():
    from app.core import drape
    a = x2_drape()
    saved = drape.GPU_MAX_COLOURS
    drape.GPU_MAX_COLOURS = 0
    try:
        c = x2_drape()
    finally:
        drape.GPU_MAX_COLOURS = saved
    b = x2_drape()
    arches = [r.report["device"]["arch"] for r in (a, c, b)]
    check(arches == ["vulkan", "cpu", "vulkan"] and c.report["device"].get("reason") == "the job asked for the CPU",
          f"[G4] vulkan, launch-bound -> cpu, vulkan again: {arches} ({c.report['device']})")
    check(np.array_equal(a.X, b.X), "[G4] the two vulkan runs: array_equal (run-to-run deterministic)")
    for name, r in (("vulkan", a), ("cpu", c)):
        rad = np.linalg.norm(r.X, axis=1)
        check(rad.min() >= 0.103, f"[G4] {name}: every vertex at |p| >= 0.103 (min {rad.min():.5f})")
    print(f"       vulkan vs cpu: max {np.abs(a.X - c.X).max() * 1000:.4f} mm")


def main() -> int:
    g1()
    gpu = g2()
    from app.core import gpu_compute
    if gpu and gpu_compute.device()["arch"] == "vulkan":
        g3()
        g4()
    else:
        print("SKIP [G3] [G4] no usable GPU in this process (" + str(gpu_compute.device().get("reason")) + ")")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
