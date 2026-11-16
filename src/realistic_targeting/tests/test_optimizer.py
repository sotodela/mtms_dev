import unittest

import numpy as np

from realistic_targeting_py.optimizer import TargetingInputError, solve_least_squares


class AvoidanceSolverTests(unittest.TestCase):
    def setUp(self):
        self.fields = np.array([[[1., 0, 0], [1, 0, 0]], [[1., 0, 0], [0, 0, 0]]])

    def solve(self, strength=0, indices=None):
        return solve_least_squares(self.fields, [[1., 0, 0]], [0],
                                   avoidance_indices=indices, avoidance_strength=strength)

    def test_zero_strength_preserves_original_solution(self):
        np.testing.assert_allclose(self.solve()["weights"], self.solve(0, [1])["weights"])

    def test_avoidance_uses_channel_freedom_to_preserve_target_and_suppress_region(self):
        baseline, avoided = self.solve(0, [1]), self.solve(10, [1])
        self.assertLess(avoided["avoidance_rms_field"], baseline["avoidance_rms_field"] * 1e-4)
        np.testing.assert_allclose(avoided["achieved_fields"], [[1, 0, 0]], atol=1e-5)
        self.assertGreater(avoided["weights"][1], .99)

    def test_penalty_is_mean_not_sum_over_points(self):
        result = self.solve(3, [1])
        fields = np.concatenate([self.fields, self.fields[:, 1:, :]], axis=1)
        doubled = solve_least_squares(fields, [[1., 0, 0]], [0], avoidance_indices=[1, 2], avoidance_strength=3)
        np.testing.assert_allclose(result["weights"], doubled["weights"], atol=1e-10)

    def test_increasing_strength_trades_target_accuracy_for_suppression_when_necessary(self):
        results = [solve_least_squares(self.fields[:1], [[1., 0, 0]], [0],
                                      avoidance_indices=[1], avoidance_strength=a) for a in [0, 1, 10]]
        self.assertGreater(results[0]["avoidance_max_field"], results[1]["avoidance_max_field"])
        self.assertGreater(results[1]["avoidance_max_field"], results[2]["avoidance_max_field"])
        self.assertLess(results[0]["score"], results[2]["score"])

    def test_invalid_strength_and_indices_are_rejected(self):
        for strength, indices in [(-1, [1]), (float('nan'), []), (float('inf'), []), (1, [2]), (1, [-1])]:
            with self.subTest(strength=strength, indices=indices), self.assertRaises(TargetingInputError):
                self.solve(strength, indices)

    def test_empty_region_is_noop_and_reports_zero_field(self):
        result = self.solve(100, [])
        np.testing.assert_allclose(result["weights"], self.solve()["weights"])
        self.assertEqual(result["avoidance_rms_field"], 0.)
        self.assertEqual(result["avoidance_max_field"], 0.)


if __name__ == '__main__':
    unittest.main()
