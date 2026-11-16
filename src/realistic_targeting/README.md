# Realistic targeting service

`/run_realistic_targeting` fits channel weights to requested field vectors.
The current implementation uses regularized linear least squares; it does not
implement the nonlinear spatial targeting algorithm in `lainem11/E-field_targeting`.

The objective is

    ||A_target w - desired||² + alpha / N_avoid * ||A_avoid w||² + lambda * ||w||²

`avoidance_indices` are row indices into the supplied E-field arrays, not global
cortex mesh IDs. `avoidance_strength` is alpha and must be finite and nonnegative.
A zero strength or empty avoidance selection disables the penalty. Averaging over
avoided points prevents the penalty from growing simply with point count; this
is a mesh-point average, not an area-weighted surface integral.

Avoidance is a soft penalty. Increasing alpha may reduce target accuracy; it does
not guarantee a maximum field in the avoided area. The response reports target
relative residual (`score`) separately from avoidance RMS and maximum field.
Field metrics use the same units as the input field vectors.

In the InVesalius plugin:

1. Select coil positions, directed targets, and the calculation ROI as usual.
2. Choose **Avoid for**: the shared default or a specific directed target. Editing
   a target's region/strength creates an override; **Use shared default** removes
   it. An empty target override allows that target to opt out of shared avoidance.
   Then enable **Select avoidance area** and click the E-field cortex mesh. The shared
   radius control determines the patch size along connected mesh edges; avoidance
   points are highlighted orange. Choose **Add** to include patches or **Erase**
   to remove patches with the same surface-distance brush. This is an edge-based
   approximation of geodesic distance and depends on the mesh connectivity;
   disconnected vertices are not welded automatically.
3. Set **Strength (0 = off)**. Start with 1, compare target error and avoidance
   metrics, then adjust as appropriate for the field scaling and regularization.
4. Prepare a new request. Fields are calculated at the union of the calculation
   ROI and every target's effective avoidance points. Each directed target is
   optimized independently using its own override or the shared default. A target
   inside its own active avoidance region is rejected. Other targets may still
   avoid that location.
5. Select a result to display its directly recalculated field. JSON export records
   the avoidance selection, strength, solver metrics, and direct field metrics.

**Clear avoidance** removes all selected avoidance patches. Import/export retains
avoidance settings. The local fallback uses the same objective as the ROS service.

When changing the service definition, rebuild both `realistic_targeting` and
`neuronavigation`, since both images contain the generated ROS interface:

    docker compose -f docker-compose.dev.yml up -d --build neuronavigation realistic_targeting
