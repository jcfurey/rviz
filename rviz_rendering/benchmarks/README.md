# Point cloud measurements

This optional benchmark exercises the actual RViz point renderer.
It measures repeated replacement, box geometry, and a rolling window of ten point batches.
It is a diagnostic tool, not a timing assertion in the unit-test suite.

Build a Release or RelWithDebInfo overlay, with `RVIZ_BUILD_BENCHMARKS=ON` for `rviz_rendering`.
For an existing configured workspace:

```bash
source install/setup.bash
cmake -S src/rviz/rviz_rendering -B build/rviz_rendering -DRVIZ_BUILD_BENCHMARKS=ON
cmake --build build/rviz_rendering --target point_cloud_benchmark -j4
```

Adjust the source/build paths to your workspace.
Use a working graphical display and the same backend and scale for each comparison.
On Linux/X11:

```bash
QT_QPA_PLATFORM=xcb QT_SCALE_FACTOR=1 python3 \
  src/rviz/rviz_rendering/benchmarks/run_cloud_benchmarks.py \
  --binary build/rviz_rendering/point_cloud_benchmark \
  --output results/cloud-upload
```

The Python runner uses Linux `ldd` to record loaded library paths and SHA-256 hashes.
It also records Qt, driver, GPU device, scale, raw samples, and per-run median/p95/p99/maximum times.
Output directories must be new, so earlier results are preserved.
Warmup samples are excluded; outliers are retained.
Runs are serial.
Keep builds, profilers, other graphics workloads, and power settings constant while measuring.
Do not compare profiler timings to native timings.

To compare an ABI-compatible pre-change renderer against the current overlay, add `--baseline-lib-dir /path/to/saved/libraries`.
The runner verifies that it actually resolves different renderer libraries, then alternates the order of baseline and fixed processes each round.
Do not mix libraries from different ROS releases.
For incompatible revisions, build separate overlays and run each binary in a clean environment, retaining both result directories.

Default workloads, each with 20 warmup and 200 measured updates in three rounds:

| Workload | Points per update | Retained batches | Mode |
| --- | ---: | ---: | --- |
| `1m-points` | 1,000,000 | 1 | Points |
| `6m-points` | 6,000,000 | 1 | Points |
| `250k-boxes` | 250,000 | 1 | Boxes |
| `100k-decay10` | 100,000 | 10 | Points |

Select workloads with repeated `--workload` arguments.
Use `--samples 2000` for a longer run and `--render` to also draw every update in a 640×480 logical-pixel window.
The direct executable accepts:

```text
point_cloud_benchmark POINTS SAMPLES WARMUP RETAINED_BATCHES points|boxes render|upload
```

`update_ms` includes clearing or evicting old points and adding/uploading the new batch.
`render_call_ms` measures the CPU-side render call, including any driver waits; it is not isolated GPU execution time.
Upload mode makes no deliberate render calls.
Neither mode measures ROS transport, TF, message transformations, selection, image decoding, input latency, or full RViz application FPS.
Data is synthetic and generated before timing.
Retention is a fixed batch count, not `PointCloudCommon`'s wall-clock decay policy.
Compare medians of the per-run summaries, and retain p95/p99 and raw logs to spot variance.

Linux RSS samples include the process and driver allocations resident in CPU memory.
They are not live allocation counts or GPU memory measurements.
Allocator caches can retain memory; a larger final RSS alone does not establish a leak.
Other platforms report -1.
Point counts are checked after timing; that check copies the retained points, so its temporary allocation is excluded from RSS samples.
Use resource counts and a memory checker for lifetime regressions.

Before claiming end-to-end improvements, replay the same representative rosbag with the same QoS, TF, point styles, decay, image transports, window sizes, and scale.
Record received/dropped messages, input latency, CPU/RSS, and frame times.
Repeat on the intended GPU/driver and desktop, including mixed-DPI monitor moves and repeated image-panel docking.
Synthetic renderer numbers cannot establish those results.
