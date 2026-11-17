"""Taper/material physical invariants, schema migration, independent sweep solves."""
import copy
import json
import math
import unittest
from unittest.mock import patch
import numpy as np
from model import InputError, sample_model, validate_model, sweep_cases, MAX_SWEEP_CASES
from engine import assemble, analyze, analyze_sweep


class ExtensionTests(unittest.TestCase):
    def test_v1_migration_and_cylinder_limit(self):
        old=sample_model()
        canonical=validate_model(old)
        self.assertEqual(canonical['schema_version'],3)
        self.assertEqual(old['schema_version'],1)
        self.assertEqual(canonical['shafts'][0]['odr_mm'],50)
        self.assertEqual(validate_model(canonical),canonical)
        for a,b in zip(assemble(old)[2:],assemble(canonical)[2:]):
            np.testing.assert_allclose(a,b,atol=0,rtol=0)

    def test_taper_mass_and_gravity_moment_with_individual_materials(self):
        d=sample_model()
        d['shafts'][0].update(odr_mm=90,id_mm=10,idr_mm=20,
            material=dict(rho=4500,E_GPa=110,G_GPa=42))
        d['shafts'][2]['material']=dict(rho=8200,E_GPa=180,G_GPa=70)
        d=validate_model(d)
        r=analyze(d)
        mass=0;moment=0;start=0
        for s in d['shafts']:
            L=s['length_mm']/1000
            rho=next(m for m in d['materials'] if m['id']==(s.get('material_id') or d['default_material_id']))['rho']
            # Exact integral of a linearly tapered annular cross section.
            a=s['od_mm']/1000;b=(s['odr_mm']-s['od_mm'])/1000
            c=s['id_mm']/1000;e=(s['idr_mm']-s['id_mm'])/1000
            m=rho*math.pi/4*L*(a*a+a*b+b*b/3-c*c-c*e-e*e/3)
            local=rho*math.pi/4*L*L*(a*a/2+2*a*b/3+b*b/4-c*c/2-2*c*e/3-e*e/4)
            mass+=m;moment+=start*m+local;start+=L
        x=np.array(r['node_mm'])/1000
        for disk in d['disks']:
            mass+=disk['mass_kg'];moment+=disk['mass_kg']*x[disk['node']]
        self.assertAlmostEqual(r['mass_kg'],mass,places=7)
        self.assertAlmostEqual(sum(b['fy_N'] for b in r['reactions']),mass*9.80665,places=5)
        self.assertAlmostEqual(sum(b['fy_N']*x[b['node']] for b in r['reactions']),moment*9.80665,places=5)

    def test_material_override_does_not_change_other_elements(self):
        d=sample_model();original=copy.deepcopy(d)
        d['shafts'][0]['material']=dict(rho=7810,E_GPa=105.5,G_GPa=40.6)
        _,rotor,M,K,_,_=assemble(d)
        _,_,M0,K0,_,_=assemble(original)
        np.testing.assert_allclose(M,M0)
        self.assertGreater(np.max(abs(K-K0)),1)
        self.assertEqual(rotor.shaft_elements[0].material.E,105.5e9)
        self.assertEqual(rotor.shaft_elements[1].material.E,211e9)
        self.assertEqual(d['material'],original['material'])

    def test_right_end_and_material_validation(self):
        for change in (lambda d:d['shafts'][0].update(odr_mm=10,idr_mm=11),
                       lambda d:d['shafts'][0].update(odr_mm=float('nan')),
                       lambda d:d['shafts'][0].update(material=dict(rho=-1,E_GPa=100,G_GPa=40)),
                       lambda d:d['shafts'][0].update(material=dict(rho=5000,E_GPa=100,G_GPa=10))):
            d=sample_model();change(d)
            with self.assertRaises(InputError):validate_model(d)

    def test_sweep_matches_independent_single_case_and_preserves_base(self):
        d=sample_model();original=copy.deepcopy(d)
        spec=dict(mode='cartesian',parameters=[dict(bearing=0,coefficient='kxx_kyy',values=[5e5,1e6,2e6])])
        batch=analyze_sweep(d,spec)
        self.assertEqual((batch['total'],batch['success'],batch['failed']),(3,3,0))
        for c in batch['cases']:
            expected=copy.deepcopy(d);v=c['parameters'][0]['value']
            expected['bearings'][0].update(kxx=v,kyy=v)
            separate=analyze(expected)
            np.testing.assert_allclose(c['result']['amplitude_x_um'],separate['amplitude_x_um'])
            np.testing.assert_allclose(c['result']['lowest_frequency_hz'],np.min(separate['frequency_hz'],axis=1))
            self.assertNotIn('model',c)
            self.assertNotIn('mode_shapes',c['result'])
        self.assertEqual(d,original)
        json.dumps(batch,allow_nan=False)

    def test_cartesian_and_paired(self):
        p=[dict(bearing=0,coefficient='kxx',values=[1e6,2e6]),dict(bearing=1,coefficient='kyy',values=[3e6,4e6])]
        full=sweep_cases(sample_model(),dict(mode='cartesian',parameters=p))
        paired=sweep_cases(sample_model(),dict(mode='paired',parameters=p))
        self.assertEqual(len(full),4);self.assertEqual(len(paired),2)
        self.assertEqual([c['model']['bearings'][1]['kyy'] for c in full],[3e6,4e6,3e6,4e6])
        self.assertEqual(paired[1]['model']['bearings'][0]['kxx'],2e6)
        p[1]['values']=[3e6]
        broadcast=sweep_cases(sample_model(),dict(mode='paired',parameters=p))
        self.assertEqual(len(broadcast),2)
        self.assertTrue(all(c['model']['bearings'][1]['kyy']==3e6 for c in broadcast))

    def test_sweep_limits_overlap_and_invalid_values(self):
        specs=[dict(mode='cartesian',parameters=[dict(bearing=0,coefficient='kxx',values=[1e6]*17),dict(bearing=1,coefficient='kyy',values=[1e6]*17)]),
               dict(mode='paired',parameters=[dict(bearing=0,coefficient='kxx',values=[1e6,2e6]),dict(bearing=1,coefficient='kyy',values=[1e6]*3)]),
               dict(parameters=[dict(bearing=0,coefficient='kxx_kyy',values=[1e6]),dict(bearing=0,coefficient='kyy',values=[2e6])])]
        for value in (0,-1,float('inf'),True):
            specs.append(dict(parameters=[dict(bearing=0,coefficient='kxx',values=[value])]))
        for spec in specs:
            with self.assertRaises(InputError):sweep_cases(sample_model(),spec)

    def test_partial_failure_has_no_fabricated_curve(self):
        # Exercise the batch contract without relying on a solver's roundoff at resonance.
        spec=dict(parameters=[dict(bearing=0,coefficient='kxx',values=[1e6,2e6])])
        minimal={key:None for key in ('engine','rpm','frequency_hz','log_dec','max_real_all_modes','critical_speeds',
                 'amplitude_x_um','amplitude_y_um','phase_x_deg','phase_y_deg','operating_index','stability','peak_rpm','peak_um','mass_kg','notes')}
        minimal['frequency_hz']=[[1,2]]
        with patch('engine.analyze',side_effect=[InputError('singular case'),minimal]):
            result=analyze_sweep(sample_model(),spec)
        self.assertEqual(result['failed'],1)
        self.assertNotIn('result',result['cases'][0])
        self.assertEqual(result['cases'][1]['status'],'ok')


if __name__=='__main__':unittest.main()
