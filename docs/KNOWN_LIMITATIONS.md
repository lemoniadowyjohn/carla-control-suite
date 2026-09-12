# Known Limitations

- RQ3 has no valid paired generated/manual Ingolstadt capture because the CARLA RPC boundary remains blocked.
- RQ5(a) has no generated-train/manual-test transfer result and depends on valid RQ3 datasets.
- RQ5(b) has no appropriate labeled real-world Ingolstadt dataset and remains deferred.
- RQ2 current measurements are local, registered comparisons; they do not by themselves prove improved whole-map quality over the thesis.
- RQ1 timestamp normalization identifies the observed difference in committed fixtures, but exhaustive byte-source isolation remains bounded.
- Large `run_*.xodr` artifacts are intentionally not required for portable CI.
