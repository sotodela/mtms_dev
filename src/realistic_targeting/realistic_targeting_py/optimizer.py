import numpy as np


class TargetingInputError(ValueError):
    pass


def solve_least_squares(
    efields,
    target_directions,
    target_indices=None,
    regularization=1e-6,
    nonnegative=False,
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

    A = np.stack(
        [efields[coil_index, target_indices, :] for coil_index in range(num_coils)],
        axis=-1,
    ).reshape(num_targets * components, num_coils)
    b = target_directions.reshape(num_targets * components)

    if regularization > 0:
        reg = np.sqrt(float(regularization)) * np.eye(num_coils)
        A_solve = np.vstack([A, reg])
        b_solve = np.concatenate([b, np.zeros(num_coils)])
    else:
        A_solve = A
        b_solve = b

    weights, *_ = np.linalg.lstsq(A_solve, b_solve, rcond=None)
    if nonnegative:
        weights = np.clip(weights, 0.0, None)

    achieved = (A @ weights).reshape(num_targets, components)
    residual = achieved.reshape(-1) - b
    denominator = np.linalg.norm(b)
    score = float(np.linalg.norm(residual) / denominator) if denominator else float(np.linalg.norm(residual))
    best_coil_index = int(np.argmax(np.abs(weights))) if weights.size else -1

    return {
        "weights": weights,
        "best_coil_index": best_coil_index,
        "score": score,
        "achieved_fields": achieved,
    }
