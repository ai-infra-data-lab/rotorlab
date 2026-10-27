"""Independent physical checks and published benchmark; python -m unittest -v."""
import copy
import json
import math
import re
import threading
import unittest
import urllib.request
import urllib.error
import numpy as np
from model import InputError, sample_model, validate_model
from engine import analyze, assemble, eigen


class PhysicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = sample_model()
        cls.result = analyze(cls.base)

    def test_published_friswell_5_9_1_frequencies(self):
        # Friswell et al. Dynamics of Rotating Machines (2010), example 5.9.1.
        # 1.5 m x 50 mm shaft, 70 mm disks OD 280/350, 1 MN/m end bearings.
        d = sample_model()
        for b in d["bearings"]:
            b["cxx"] = b["cyy"] = 0
        for disk, od in zip(d["disks"], (0.28, 0.35)):
            mass = 7810 * math.pi / 4 * (od**2 - 0.05**2) * 0.07
            disk.update(mass_kg=mass, Id_kgm2=mass/12*(3/4*(od**2+0.05**2)+0.07**2),
                        Ip_kgm2=mass/8*(od**2+0.05**2))
        _, _, M, K, C, G = assemble(d)
        # Published 6-DOF table includes 650.41 rad/s torsional mode.
        # Compare its five reported lateral modes to this lateral-only solver.
        for rpm, expected in [(0, [86.66,86.66,274.31,274.31,716.78]),
                               (4000, [85.39,87.80,251.78,294.71,600.18])]:
            val, _ = eigen(M,K,C+rpm*math.pi/30*G)
            np.testing.assert_allclose(val.imag[:5], expected, atol=0.025, rtol=0)

    def test_weight_and_moment_balance(self):
        r = self.result
        reactions = sum(b["fy_N"] for b in r["reactions"])
        self.assertAlmostEqual(reactions, r["mass_kg"]*9.80665, places=6)
        x = np.array(r["node_mm"]) / 1000
        d = self.base
        mass_moment = sum(math.pi/4*((s["od_mm"]/1000)**2-(s["id_mm"]/1000)**2)*
                          s["length_mm"]/1000*d["material"]["rho"]*(x[i]+x[i+1])/2
                          for i,s in enumerate(d["shafts"]))
        mass_moment += sum(b["mass_kg"]*x[b["node"]] for b in d["disks"])
        reaction_moment = sum(b["fy_N"]*x[b["node"]] for b in r["reactions"])
        self.assertAlmostEqual(reaction_moment, mass_moment*9.80665, places=6)

    def test_mass_symmetry_gyro_skew_and_positive_mass(self):
        _,_,M,_,_,G = assemble(self.base)
        np.testing.assert_allclose(M,M.T,atol=1e-12)
        np.testing.assert_allclose(G,-G.T,atol=1e-12)
        self.assertGreater(np.min(np.linalg.eigvalsh(M)),0)

    def test_linear_unbalance_scaling_and_cancellation(self):
        d=copy.deepcopy(self.base)
        d["unbalances"][0]["g_mm"] *= 2
        doubled=analyze(d)
        np.testing.assert_allclose(doubled["amplitude_x_um"],np.array(self.result["amplitude_x_um"])*2,rtol=1e-10)
        d=copy.deepcopy(self.base)
        second=copy.deepcopy(d["unbalances"][0]);second["phase_deg"]=180
        d["unbalances"].append(second)
        cancelled=analyze(d)
        self.assertLess(max(cancelled["amplitude_x_um"]),1e-10)

    def test_zero_unbalance_and_neutral_stability(self):
        d=copy.deepcopy(self.base);d["unbalances"]=[]
        for b in d["bearings"]:
            b["cxx"]=b["cyy"]=0
        r=analyze(d)
        self.assertEqual(max(r["amplitude_y_um"]),0)
        self.assertTrue(all(p is None for p in r["phase_y_deg"]))
        self.assertEqual(r["stability"],"中立/判定境界")

    def test_cross_coupling_instability(self):
        d=copy.deepcopy(self.base)
        for b in d["bearings"]:
            b["kxy"]=5e5;b["kyx"]=-5e5
        r=analyze(d)
        self.assertEqual(r["stability"],"不安定")
        self.assertTrue(any(v<0 for v in r["log_dec"][r["operating_index"]]))

    def test_seals_not_used_to_support_weight(self):
        d=copy.deepcopy(self.base)
        d["seals"]=[dict(node=3,kxx=5e5,kyy=5e5,kxy=0,kyx=0,cxx=50,cyy=50,cxy=0,cyx=0,source="test")]
        r=analyze(d)
        np.testing.assert_allclose(r["static_y_um"],self.result["static_y_um"],rtol=1e-9)
        self.assertGreater(abs(r["frequency_hz"][0][0]-self.result["frequency_hz"][0][0]),0.1)

    def test_mesh_refinement_lowest_frequency(self):
        d=copy.deepcopy(self.base)
        d["shafts"]=[dict(s,length_mm=s["length_mm"]/2) for s in d["shafts"] for _ in (0,1)]
        for key in ("disks","bearings","seals","unbalances"):
            for el in d[key]:el["node"]*=2
        d["analysis"]["probe_node"]*=2
        _,_,M,K,C,G=assemble(d)
        val,_=eigen(M,K,C)
        low=self.result["frequency_hz"][0][0]
        self.assertLess(abs(val[0].imag/(2*math.pi)-low)/low,0.002)

    def test_invalid_inputs(self):
        for change in (lambda d:d["shafts"][0].update(id_mm=60),
                       lambda d:d["bearings"][0].update(node=99),
                       lambda d:d["material"].update(E_GPa=float('nan')),
                       lambda d:d["analysis"].update(probe_node=1.5),
                       lambda d:d["analysis"].update(points=10000),
                       lambda d:d["disks"][0].update(Ip_kgm2=100)):
            d=copy.deepcopy(self.base);change(d)
            with self.assertRaises(InputError):validate_model(d)

    def test_finite_json_results(self):
        json.dumps(self.result,allow_nan=False)
        self.assertTrue(self.result["critical_speeds"])


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from server import Handler, ThreadingHTTPServer, TOKEN
        cls.http=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.url=f'http://127.0.0.1:{cls.http.server_port}'
        cls.token=TOKEN
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True);cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close();cls.thread.join()

    def test_page_and_assets(self):
        with urllib.request.urlopen(self.url) as r:
            page=r.read().decode();self.assertIn('RotorLab',page);self.assertIn(self.token,page)
        for path in ('/app.js','/style.css','/plotly.min.js'):
            with urllib.request.urlopen(self.url+path) as r:self.assertGreater(len(r.read()),100)

    def test_local_api_analysis_and_rejection(self):
        body=json.dumps(sample_model()).encode()
        req=urllib.request.Request(self.url+'/api/analyze',body,{'Content-Type':'application/json','X-RotorLab-Token':self.token})
        with urllib.request.urlopen(req) as r:self.assertIn('frequency_hz',json.load(r))
        bad=urllib.request.Request(self.url+'/api/analyze',body,{'Content-Type':'application/json'})
        with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(bad)
        self.assertEqual(caught.exception.code,403)
        bad_model=sample_model();bad_model['shafts'][0]['od_mm']=0
        req=urllib.request.Request(self.url+'/api/validate',json.dumps(bad_model).encode(),{'Content-Type':'application/json','X-RotorLab-Token':self.token})
        with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(req)
        self.assertEqual(caught.exception.code,400)


if __name__=='__main__':unittest.main()
