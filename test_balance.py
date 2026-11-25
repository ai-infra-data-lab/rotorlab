"""Checks for the selection geometry and each JIS allocation branch."""

import math
import unittest

from balance import calculate_balance
from model import InputError, sample_model, validate_model


class BalanceTests(unittest.TestCase):
    def setUp(self):
        self.model = validate_model(sample_model())
        for shaft in self.model["shafts"]:
            shaft["length_mm"] = 200
        self.model["disks"][0]["mass_kg"] = 10
        self.settings = {"disk_indices": [0], "grade": 2.5, "max_rpm": 6000,
                         "plane_count": 2, "bearing_a_mm": 0, "bearing_b_mm": 1000,
                         "plane_i_mm": 200, "plane_ii_mm": 700}
        self.total = 250 / (2 * math.pi)

    def check_planes(self, clause, ratios, **settings):
        result = calculate_balance(self.model, self.settings | settings)
        self.assertTrue(result["clause"].startswith(clause))
        self.assertAlmostEqual(result["total_g_mm"], self.total)
        self.assertEqual(len(result["planes"]), len(ratios))
        for plane, ratio in zip(result["planes"], ratios):
            self.assertAlmostEqual(plane["limit_g_mm"], self.total * ratio)
        return result

    def test_single_and_inboard_planes(self):
        self.check_planes("5.1", (1,), plane_count=1)
        result = self.check_planes("5.2 (1)", (0.6, 0.4))
        self.assertEqual((result["mass_kg"], result["center_mm"]), (10, 400))
        self.check_planes("5.2 (1)", (0.6, 0.4), plane_i_mm=0, plane_ii_mm=1000)

    def test_outboard_planes(self):
        self.check_planes("5.2 (2)", (80 / 169, 50 / 169), plane_i_mm=-100, plane_ii_mm=1200)

    def test_close_planes_separate_static_and_couple(self):
        result = self.check_planes("5.2 (3)", (15 / 8, 15 / 8, 5 / 12),
                                   plane_i_mm=350, plane_ii_mm=550, plane_iii_mm=400)
        self.assertEqual(result["details"]["couple_phase_deg"], 180)
        self.assertEqual(result["planes"][2]["position_mm"], 400)
        with self.assertRaisesRegex(InputError, "修正面III"):
            calculate_balance(self.model, self.settings | {"plane_i_mm": 350, "plane_ii_mm": 550})

    def test_general_branch_overhung_center(self):
        self.model["disks"][0]["node"] = 6
        result = self.check_planes("5.2 (4)", (7 / 32, 7 / 16), plane_i_mm=800, plane_ii_mm=1200)
        self.assertEqual((result["details"]["k"], result["details"]["ratio"]), (0.3, 2))

    def test_selected_taper_uses_assigned_material_and_original_position(self):
        model = self.model
        model["materials"].append(dict(model["materials"][0], id="b", name="B", rho=4200))
        model["shafts"][1].update(od_mm=40, odr_mm=80, id_mm=10, idr_mm=20, material_id="b")
        result = calculate_balance(model, self.settings | {"plane_count": 1, "shaft_indices": [1], "disk_indices": []})
        end_area = math.pi / 4 * (40**2 - 10**2)
        self.assertAlmostEqual(result["mass_kg"], 4200 * 200 * end_area * 7 / 3 * 1e-9)
        self.assertAlmostEqual(result["center_mm"], 200 + 200 * 17 / 28)
        combined = calculate_balance(model, self.settings | {"plane_count": 1, "shaft_indices": [1]})
        self.assertAlmostEqual(combined["mass_kg"], result["mass_kg"] + 10)
        self.assertAlmostEqual(combined["center_mm"],
                               (result["mass_kg"] * result["center_mm"] + 10 * 400) / combined["mass_kg"])

    def test_invalid_selection_and_reference_positions(self):
        for inputs in ({"disk_indices": []}, {"shaft_indices": [0, 0]}, {"shaft_indices": [-1]},
                       {"bearing_b_mm": 0}, {"plane_ii_mm": 200}, {"max_rpm": 0}, {"grade": 3}):
            with self.subTest(inputs=inputs), self.assertRaises(InputError):
                calculate_balance(self.model, self.settings | inputs)
