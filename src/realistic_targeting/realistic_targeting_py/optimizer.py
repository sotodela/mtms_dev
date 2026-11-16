import numpy as np


class TargetingInputError(ValueError):
    pass


def solve_least_squares(
    efields,
    target_directions,
    target_indices=None,
    regularization=1e-6,
    nonnegative=False,
    avoidance_indices=None,
    avoidance_strength=0.0,
):
    """Fit coil weights so the combined E-field matches target directions."""
    efields = np.asarray(efields, dtype=float)
    target_directions = np.asarray(target_directions, dtype=float)

    if efields.ndim != 3:
        raise TargetingInputError("efields must have shape (coils, points, components)")
    if target_directions.ndim != 2:
        raise TargetingInputError("target_directions must have shape (targets, components)")

    num_coils, num_points, components = efields.shape
    num_targets, target_components = target_directions.shape
    if components != target_components:
        raise TargetingInputError("E-field components and target direction components differ")
    if num_coils == 0:
        raise TargetingInputError("at least one coil E-field is required")
    if num_targets == 0:
        raise TargetingInputError("at least one target direction is required")

    if target_indices is None or len(target_indices) == 0:
        target_indices = np.arange(num_targets, dtype=int)
    else:
        target_indices = np.asarray(target_indices, dtype=int)

    if target_indices.shape[0] != num_targets:
        raise TargetingInputError("target_indices length must match target count")
    if np.any(target_indices < 0) or np.any(target_indices >= num_points):
        raise TargetingInputError("target index outside E-field point range")

    if not np.isfinite(avoidance_strength) or avoidance_strength < 0:
        raise TargetingInputError("avoidance_strength must be finite and nonnegative")
    avoidance_indices = np.asarray([] if avoidance_indices is None else avoidance_indices, dtype=int)
    if avoidance_indices.ndim != 1:
        raise TargetingInputError("avoidance_indices must be one-dimensional")
    avoidance_indices = np.unique(avoidance_indices)
    if np.any(avoidance_indices < 0) or np.any(avoidance_indices >= num_points):
        raise TargetingInputError("avoidance index outside E-field point range")

    A = np.stack(
        [efields[coil_index, target_indices, :] for coil_index in range(num_coils)],
        axis=-1,
    ).reshape(num_targets * components, num_coils)
    b = target_directions.reshape(num_targets * components)

    blocks, goals = [A], [b]
    B = efields[:, avoidance_indices, :].transpose(1, 2, 0).reshape(
        len(avoidance_indices) * components, num_coils
    )
    if avoidance_strength > 0 and len(avoidance_indices):
        # Mean squared vector magnitude; point count does not scale the penalty.
        blocks.append(np.sqrt(avoidance_strength / len(avoidance_indices)) * B)
        goals.append(np.zeros(B.shape[0]))
    if regularization > 0:
        blocks.append(np.sqrt(float(regularization)) * np.eye(num_coils))
        goals.append(np.zeros(num_coils))
    A_solve = np.vstack(blocks)
    b_solve = np.concatenate(goals)

    weights, *_ = np.linalg.lstsq(A_solve, b_solve, rcond=None)
    if nonnegative:
        weights = np.clip(weights, 0.0, None)

    achieved = (A @ weights).reshape(num_targets, components)
    residual = achieved.reshape(-1) - b
    denominator = np.linalg.norm(b)
    score = float(np.linalg.norm(residual) / denominator) if denominator else float(np.linalg.norm(residual))
    best_coil_index = int(np.argmax(np.abs(weights))) if weights.size else -1

    avoided_fields = (B @ weights).reshape(-1, components)
    avoided_norms = np.linalg.norm(avoided_fields, axis=1)
    return {
        "avoidance_rms_field": float(np.sqrt(np.mean(avoided_norms**2))) if avoided_norms.size else 0.0,
        "avoidance_max_field": float(np.max(avoided_norms)) if avoided_norms.size else 0.0,
        "weights": weights,
        "best_coil_index": best_coil_index,
        "score": score,
        "achieved_fields": achieved,
    }
