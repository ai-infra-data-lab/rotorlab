"""Material registry migration, reference integrity and FE material assignment."""
import copy
import json
import unittest
import numpy as np

from engine import assemble, analyze_sweep
from model import InputError, sample_model, validate_model


class MaterialTests(unittest.TestCase):
    def registry_model(self):
        d = validate_model(sample_model())
        d['materials'].append(dict(id='alloy-b', name='仮定材B', rho=4500,
                                   E_GPa=110, G_GPa=42, source='架空の検証用物性'))
        d['shafts'][0]['material_id'] = 'alloy-b'
        d['shafts'][3]['material_id'] = 'alloy-b'
        return d

    def test_legacy_override_migrates_losslessly(self):
        old = sample_model();old['schema_version'] = 2
        old['shafts'][0]['material'] = dict(rho=4500, E_GPa=110, G_GPa=42)
        original = copy.deepcopy(old)
        migrated = validate_model(old)
        self.assertEqual(migrated['schema_version'], 3)
        self.assertEqual(len(migrated['materials']), 2)
        self.assertNotIn('material', migrated)
        self.assertNotIn('material', migrated['shafts'][0])
        self.assertEqual(migrated['shafts'][0]['material_id'], 'legacy-shaft-0')
        for a, b in zip(assemble(old)[2:], assemble(migrated)[2:]):
            np.testing.assert_allclose(a, b, atol=0, rtol=0)
        _, rotor, *_ = assemble(migrated)
        self.assertEqual(rotor.shaft_elements[0].material.rho, 4500)
        self.assertEqual(rotor.shaft_elements[1].material.rho, old['material']['rho'])
        self.assertEqual(old, original)

    def test_shared_edit_and_rename_reach_only_selected_elements(self):
        d = self.registry_model()
        _, before, M0, K0, *_ = assemble(d)
        d['materials'][1].update(name='名前を変更', rho=5000, E_GPa=120, G_GPa=46)
        _, after, M1, K1, *_ = assemble(d)
        for index in range(6):
            if index in (0, 3):
                self.assertEqual(after.shaft_elements[index].material.rho, 5000)
                self.assertEqual(after.shaft_elements[index].material.E, 120e9)
            else:
                np.testing.assert_array_equal(before.shaft_elements[index].M(), after.shaft_elements[index].M())
                np.testing.assert_array_equal(before.shaft_elements[index].K(), after.shaft_elements[index].K())
        self.assertGreater(np.max(abs(M1-M0)), 0)
        self.assertGreater(np.max(abs(K1-K0)), 0)
        self.assertEqual(d['shafts'][0]['material_id'], 'alloy-b')

    def test_default_change_respects_explicit_choices(self):
        d = self.registry_model()
        d['shafts'][2]['material_id'] = 'default'
        d['default_material_id'] = 'alloy-b'
        _, rotor, *_ = assemble(d)
        self.assertEqual(rotor.shaft_elements[1].material.rho, 4500)
        self.assertEqual(rotor.shaft_elements[2].material.rho, 7810)

    def test_invalid_registry_and_dangling_references_rejected(self):
        changes = [lambda d:d['materials'].clear(),
                   lambda d:d['materials'].append(copy.deepcopy(d['materials'][0])),
                   lambda d:d['materials'][1].update(name=d['materials'][0]['name']),
                   lambda d:d['materials'][0].update(name='  '),
                   lambda d:d['materials'][0].update(rho=-1),
                   lambda d:d['materials'][0].update(E_GPa=float('nan')),
                   lambda d:d['materials'][0].update(source=123),
                   lambda d:d['shafts'][0].update(material_id='missing'),
                   lambda d:d['shafts'][0].update(material_id=True),
                   lambda d:d.update(default_material_id='missing'),
                   lambda d:d['materials'].pop(1),
                   lambda d:d.update(material=dict(rho=7810,E_GPa=211,G_GPa=81.2))]
        for change in changes:
            d = self.registry_model();change(d)
            with self.subTest(change=change), self.assertRaises(InputError):
                validate_model(d)

    def test_save_reload_and_sweep_preserve_choices(self):
        d = self.registry_model();d['analysis']['points'] = 3
        restored = validate_model(json.loads(json.dumps(d, ensure_ascii=False)))
        self.assertEqual(restored, d)
        spec = dict(parameters=[dict(bearing=0, coefficient='kxx', values=[1e6, 2e6])])
        result = analyze_sweep(restored, spec)
        self.assertEqual(result['success'], 2)
        self.assertEqual(result['base_model']['materials'], d['materials'])
        self.assertEqual(result['base_model']['shafts'][3]['material_id'], 'alloy-b')
        self.assertEqual(restored, d)


if __name__ == '__main__':
    unittest.main()
