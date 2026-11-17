"""Capacity boundaries and equivalence of the larger-model calculation path."""
import copy
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

import numpy as np
from scipy import linalg
from scipy.optimize import linear_sum_assignment

from limits import LIMITS
from model import InputError, sample_model, validate_model, sweep_cases
from engine import analyze, assemble, eigen, eigen_solver, banded, mode_shapes_at


def refined_model(elements):
    d = sample_model()
    d['shafts'] = [dict(length_mm=1500/elements, od_mm=50, id_mm=0) for _ in range(elements)]
    for key in ('disks', 'bearings', 'unbalances'):
        for el in d[key]:
            el['node'] = round(el['node']*elements/6)
    d['analysis'].update(probe_node=round(4*elements/6), points=3)
    return d


class CapacityTests(unittest.TestCase):
    def test_capacity_boundaries(self):
        d = refined_model(LIMITS['shafts'])
        d['analysis'].update(points=LIMITS['points'], modes=LIMITS['modes'])
        for key in ('disks', 'bearings', 'seals', 'unbalances'):
            if key == 'seals':
                d[key] = [copy.deepcopy(d['bearings'][0])]
            d[key] = [copy.deepcopy(d[key][i % len(d[key])]) for i in range(LIMITS['components'])]
        self.assertEqual(len(validate_model(d)['shafts']), LIMITS['shafts'])
        for key in ('shafts', 'disks', 'bearings', 'seals', 'unbalances'):
            bad = copy.deepcopy(d)
            bad[key].append(copy.deepcopy(bad[key][0]))
            with self.assertRaises(InputError):
                validate_model(bad)
        for key in ('points', 'modes'):
            bad = copy.deepcopy(d)
            bad['analysis'][key] = LIMITS[key]+1
            with self.assertRaises(InputError):
                validate_model(bad)
        d['analysis'].update(points=2, modes=1)
        validate_model(d)

    def test_sweep_boundaries_and_lazy_cases(self):
        spec = dict(parameters=[dict(bearing=0, coefficient='kxx', values=[1e6]*LIMITS['sweep_cases'])])
        cases = sweep_cases(sample_model(), spec, lazy=True)
        self.assertFalse(isinstance(cases, list))
        self.assertEqual(sum(1 for _ in cases), LIMITS['sweep_cases'])
        spec['parameters'][0]['values'].append(1e6)
        with self.assertRaises(InputError):
            sweep_cases(sample_model(), spec, lazy=True)
        d = sample_model()
        d['bearings'] = [copy.deepcopy(d['bearings'][i % 2]) for i in range(LIMITS['sweep_parameters'])]
        spec = dict(parameters=[dict(bearing=i, coefficient='kxx', values=[1e6])
                                for i in range(LIMITS['sweep_parameters'])])
        self.assertEqual(len(sweep_cases(d, spec)), 1)
        spec['parameters'].append(dict(bearing=LIMITS['sweep_parameters'], coefficient='kxx', values=[1e6]))
        with self.assertRaises(InputError):
            sweep_cases(d, spec)

    def test_cached_complete_spectrum_matches_original(self):
        d = sample_model()
        d['bearings'][0].update(kyy=8e5, kxy=2e4, kyx=-1e4)
        _, _, M, K, C, G = assemble(d)
        solve = eigen_solver(M, K, C, G)
        for w in (0, 172, 600):
            expected, _ = eigen(M, K, C+w*G)
            actual, _ = solve(w)
            rows, cols = linear_sum_assignment(abs(expected[:, None]-actual[None, :]))
            np.testing.assert_allclose(actual[cols], expected[rows], rtol=1e-7, atol=1e-6)

    def test_banded_response_matches_dense_with_cross_coupling(self):
        d = refined_model(30)
        d['shafts'][0].update(odr_mm=60, id_mm=5, idr_mm=10)
        d['bearings'][0].update(kyy=8e5, kxy=2e4, kyx=-1e4, cxy=5, cyx=-3)
        _, _, M, K, C, G = assemble(d)
        for w in (0, 123, 600):
            A = K-w*w*M+1j*w*(C+w*G)
            F = np.zeros(len(M), complex)
            F[40:42] = [1, -1j]
            expected = linalg.solve(A, F)
            actual = linalg.solve_banded((7, 7), banded(A), F)
            np.testing.assert_allclose(actual, expected, rtol=2e-7, atol=1e-12)

    def test_on_demand_shapes_match_full_result(self):
        d = sample_model()
        d['analysis']['points'] = 3
        d['bearings'][0]['kyy'] = 8e5
        complete = analyze(d)
        with patch.dict(LIMITS, shape_values=1):
            compact = analyze(d)
        self.assertEqual(sum(x is not None for x in compact['mode_shapes']), 1)
        i = 0
        targets = list(zip(compact['real_part'][i], compact['frequency_hz'][i]))
        shapes = mode_shapes_at(d, compact['rpm'][i], targets)['mode_shapes']
        for actual, expected in zip(shapes, complete['mode_shapes'][i]):
            for key in actual:
                np.testing.assert_allclose(actual[key], expected[key], rtol=1e-6, atol=1e-6)
        with self.assertRaises(InputError):
            mode_shapes_at(d, 0, [[0, 0]]*d['analysis']['modes'])
        without = analyze(d, include_shapes=False)
        self.assertTrue(all(x is None for x in without['mode_shapes']))
        np.testing.assert_allclose(without['frequency_hz'], complete['frequency_hz'])
        json.dumps(compact, allow_nan=False)

    def test_100_element_example_physics_and_response(self):
        d = json.loads(Path(__file__).with_name('examples').joinpath('rotor-100-elements.json').read_text(encoding='utf-8'))
        self.assertEqual(len(d['shafts']), 100)
        x = np.r_[0, np.cumsum([s['length_mm'] for s in d['shafts']])]/1000
        np.testing.assert_allclose(x[[disk['node'] for disk in d['disks']]], [0.5, 1.0], atol=1e-12)
        self.assertAlmostEqual(x[-1], 1.5, places=12)
        started = time.perf_counter()
        r = analyze(d)
        elapsed = time.perf_counter()-started
        expected_mass = sum(np.pi/4*((s['od_mm']/1000)**2-(s['id_mm']/1000)**2)
                            *s['length_mm']/1000*d['material']['rho'] for s in d['shafts'])
        expected_mass += sum(disk['mass_kg'] for disk in d['disks'])
        self.assertAlmostEqual(r['mass_kg'], expected_mass, places=7)
        weight = expected_mass*9.80665
        self.assertLess(abs(sum(b['fy_N'] for b in r['reactions'])-weight)/weight, 1e-6)
        moment = sum(np.pi/4*(s['od_mm']/1000)**2*s['length_mm']/1000*d['material']['rho']
                     *(x[i]+x[i+1])/2 for i, s in enumerate(d['shafts']))
        moment += sum(disk['mass_kg']*x[disk['node']] for disk in d['disks'])
        self.assertLess(abs(sum(b['fy_N']*x[b['node']] for b in r['reactions'])-moment*9.80665)
                        /(moment*9.80665), 1e-6)
        self.assertEqual(np.shape(r['frequency_hz']), (21, 12))
        # Refinement can reveal high-frequency modes with near-zero support damping.
        # Do not assume that damping of the displayed low modes proves all-mode decay.
        self.assertLessEqual(max(r['max_real_all_modes']), 1e-7)
        self.assertLess(np.max(r['real_part'][r['operating_index']]), 0)
        self.assertGreater(r['peak_um'], 0)
        self.assertTrue(np.isfinite(r['amplitude_x_um']).all())
        # Compare the selected operating-speed response to an independent dense solve.
        _, _, M, K, C, G = assemble(d)
        w = d['analysis']['operating_rpm']*np.pi/30
        F = np.zeros(len(M), complex)
        for un in d['unbalances']:
            fx = un['g_mm']*1e-6*w*w*np.exp(1j*np.deg2rad(un['phase_deg']))
            F[4*un['node']] += fx; F[4*un['node']+1] -= 1j*fx
        Q = linalg.solve(K-w*w*M+1j*w*(C+w*G), F)
        i = r['operating_index'];node = d['analysis']['probe_node']
        np.testing.assert_allclose([r['amplitude_x_um'][i],r['amplitude_y_um'][i]],
                                   abs(Q[4*node:4*node+2])*1e6, rtol=2e-6, atol=1e-8)
        json.dumps(r, allow_nan=False)
        print('\n100-element calculation: '+json.dumps(dict(seconds=round(elapsed,3),
              points=len(r['rpm']), modes=12, mass_kg=r['mass_kg'], peak_um=r['peak_um'],
              stability=r['stability'], max_real_operating=r['max_real_all_modes'][i],
              displayed_max_real_operating=max(r['real_part'][i])), ensure_ascii=True), flush=True)


if __name__ == '__main__':
    unittest.main()
