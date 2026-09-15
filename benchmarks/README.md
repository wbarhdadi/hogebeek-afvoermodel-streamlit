# Core-model baseline

Run `python benchmarks/run_baseline.py` to reproduce the pre-refactor baseline.
It executes the existing `app.run_model` entry point against a deterministic
three-cell Q-outlet subcatchment and reports numerical results, minimum and
median elapsed time, plus `tracemalloc` allocation growth and peak.

`core_model_reference.json` is the numerical regression fixture; the test suite
compares outputs with normal floating-point tolerance. Performance figures are
reported at run time rather than committed because they depend on the host.

There is no representative Hoge Beek project dataset in version control: `/data/`
is ignored. Consequently the synthetic benchmark must not be used to claim the
required 5x speedup. Once anonymised or distributable project data is supplied,
add a separate benchmark fixture that records dimensions, timestep count, output
tolerances, elapsed time, and process-level memory.
