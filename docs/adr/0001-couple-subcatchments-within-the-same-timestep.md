---
status: accepted
---

# Couple subcatchments within the same model timestep

An upstream subcatchment's outflow volume becomes downstream inlet volume in the
same model timestep, with subcatchments evaluated in topological order. Delaying
the transfer until the next timestep would insert an artificial `Δt` of storage
at a shared boundary that has no physical store; downstream spatial travel and
outlet storage provide the actual delay. This replaces the previous
`timestep - 1` scheduling behavior and means coarse-timestep sensitivity must be
managed through convergence checks or smaller internal timesteps, not a hidden
transfer queue.
