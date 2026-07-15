import numpy as np
import rclpy
from rclpy.node import Node

from realistic_targeting.srv import RunRealisticTargeting
from realistic_targeting_py.optimizer import TargetingInputError, solve_least_squares


class RealisticTargetingNode(Node):
    def __init__(self):
        super().__init__("realistic_targeting")
        self.service = self.create_service(
            RunRealisticTargeting,
            "run_realistic_targeting",
            self.run_realistic_targeting,
        )
        self.get_logger().info("Realistic targeting service ready: /run_realistic_targeting")

    def run_realistic_targeting(self, request, response):
        self.get_logger().info(
            "Request received from /run_realistic_targeting: "
            f"{request.num_coils} coils, {request.num_points} points, "
            f"{len(request.target_indices)} targets"
        )
        try:
            components = request.efield_components or 3
            expected = request.num_coils * request.num_points * components
            if len(request.efields) != expected:
                raise TargetingInputError(
                    f"expected {expected} E-field values, got {len(request.efields)}"
                )

            efields = np.asarray(request.efields, dtype=float).reshape(
                request.num_coils,
                request.num_points,
                components,
            )
            if len(request.target_directions) % components != 0:
                raise TargetingInputError("target_directions length is not divisible by components")
            target_directions = np.asarray(request.target_directions, dtype=float).reshape(
                -1,
                components,
            )

            result = solve_least_squares(
                efields=efields,
                target_directions=target_directions,
                target_indices=request.target_indices,
                regularization=request.regularization,
                nonnegative=request.nonnegative,
            )
        except (TargetingInputError, ValueError) as exc:
            response.success = False
            response.message = str(exc)
            response.best_coil_index = -1
            response.score = float("inf")
            return response

        response.success = True
        response.message = "ok"
        response.weights = result["weights"].astype(float).tolist()
        response.best_coil_index = result["best_coil_index"]
        response.score = result["score"]
        response.achieved_fields = result["achieved_fields"].reshape(-1).astype(float).tolist()
        return response


def main(args=None):
    rclpy.init(args=args)
    node = RealisticTargetingNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
