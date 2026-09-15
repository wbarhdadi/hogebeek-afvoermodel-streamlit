# Hoge Beek participatory flood model

This context models rainfall-driven flow and water levels in coupled Hoge Beek subcatchments. It is used to explore scenarios with Regionaal Landschap Dijleland.

## Hydrology

**Subcatchment**:
A spatially distributed part of the Hoge Beek system with one outlet and, optionally, upstream inlet(s).
_Avoid_: basin, area

**Rainfall depth**:
Rainfall accumulated over one stated interval, expressed in millimetres. It is the rainfall quantity consumed by the model.
_Avoid_: rainfall intensity, precipitation rate

**Rainfall intensity**:
Average rainfall rate over an interval, expressed in millimetres per hour. It must be converted to rainfall depth before simulation.
_Avoid_: rainfall amount

**Outflow volume**:
The water volume leaving a subcatchment during one model timestep, expressed in cubic metres.
_Avoid_: discharge

**Discharge**:
Outflow rate at a subcatchment outlet, expressed in cubic metres per second.
_Avoid_: flow volume, Q when the unit is not stated

**Water level**:
Absolute simulated water-surface elevation, expressed in metres TAW.
_Avoid_: flood depth

**Flooded area**:
The estimated maximum area in a subcatchment where the simulated water depth reaches at least a stated threshold at any time during one simulation, expressed in hectares. Dashboard outputs use thresholds of 0.01 m and 0.10 m.
_Avoid_: wet area, inundation risk

**Water depth**:
The simulated height of water above local terrain, expressed in metres.
_Avoid_: water level, flood level

**Hydrograph**:
The time series of simulated discharge at a subcatchment outlet, expressed in cubic metres per second.
_Avoid_: flow graph, discharge volume

**Time to peak**:
The elapsed time from the first timestep with rainfall greater than zero to the timestep with the highest simulated discharge.
_Avoid_: response time, lag time

**Maximum water-depth map**:
A spatial representation of the greatest simulated water depth reached by each raster cell during one simulation. It uses six classes: less than 0.01 m, 0.01–0.25 m, 0.25–0.50 m, 0.50–1 m, 1–2 m, and more than 2 m.
_Avoid_: flood-risk map, water-level map

**Measure**:
A mapped intervention that alters one or more spatial model inputs for a scenario.
_Avoid_: adaptation, mitigation
