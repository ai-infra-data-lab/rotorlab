"""ROSS element matrices; stationary-frame lateral eigensolve and forced response.

q(t) = Re(Q exp(i*w*t)), +z rotation: x -> y. M q''+(C+Omega G)q'+Kq=F.
All coefficient matrices are constant in this first version. Only x,y,alpha,beta
are retained (no axial/torsional modes). No invented results on solver failure.
"""
import os
from pathlib import Path
_cache = Path(__file__).resolve().parent / ".cache"
_cache.mkdir(exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_cache / "matplotlib"))
for _key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_key, "1")
import warnings
import numpy as np
from scipy import linalg, sparse
from scipy.optimize import linear_sum_assignment
import ross as rs
from model import validate_model, sweep_cases, InputError
from limits import LIMITS


def coefficient_matrix(el, prefix):
    return np.array([[el[prefix + "xx"], el[prefix + "xy"]],
                     [el[prefix + "yx"], el[prefix + "yy"]]], dtype=float)


def assemble(data):
    d = validate_model(data)
    materials = {m["id"]: m for m in d["materials"]}
    def material(s, i):
        props = materials[s.get("material_id") or d["default_material_id"]]
        return rs.Material(name=f"ShaftMaterial{i}", rho=props["rho"],
                           E=props["E_GPa"] * 1e9, G_s=props["G_GPa"] * 1e9)
    shafts = [rs.ShaftElement(n=i, L=s["length_mm"] / 1000, idl=s["id_mm"] / 1000,
                              odl=s["od_mm"] / 1000, idr=s["idr_mm"] / 1000,
                              odr=s["odr_mm"] / 1000, material=material(s, i),
                              shear_effects=True, rotary_inertia=True, gyroscopic=True)
              for i, s in enumerate(d["shafts"])]
    disks = [rs.DiskElement(n=s["node"], m=s["mass_kg"], Id=s["Id_kgm2"], Ip=s["Ip_kgm2"])
             for s in d["disks"]]
    supports = []
    for key, klass in (("bearings", rs.BearingElement), ("seals", rs.SealElement)):
        for s in d[key]:
            supports.append(klass(n=s["node"], **{p: s[p] for p in
                            ("kxx", "kyy", "kxy", "kyx", "cxx", "cyy", "cxy", "cyx")}))
    rotor = rs.Rotor(shafts, disks, supports)
    per_node = rotor.number_dof
    mapping = shafts[0].dof_mapping()
    local = [mapping[x] for x in ("x_0", "y_0", "alpha_0", "beta_0")]
    idx = [i * per_node + j for i in range(len(shafts) + 1) for j in local]
    cut = np.ix_(idx, idx)
    M, K, C, G = rotor.M()[cut], rotor.K(0)[cut], rotor.C(0)[cut], rotor.G()[cut]
    return d, rotor, M, K, C, G


def _state_eigen(A):
    n = len(A) // 2
    values, vectors = linalg.eig(A, check_finite=False, overwrite_a=True)
    if np.any(np.abs(values.imag) < 1e-7):
        raise InputError("非振動の実固有値を検出しました。支持・減衰・連成係数を確認してください。")
    keep = np.flatnonzero(values.imag > 1e-7)
    keep = keep[np.argsort(values[keep].imag)]
    return values[keep], vectors[:n, keep]


def eigen(M, K, D):
    n = len(M)
    A = np.zeros((2*n, 2*n))
    A[:n, n:] = np.eye(n)
    A[n:, :n] = -linalg.solve(M, K, assume_a="pos")
    A[n:, n:] = -linalg.solve(M, D, assume_a="pos")
    return _state_eigen(A)


def eigen_solver(M, K, C, G):
    """Factor the same mass matrix once; still solve the complete spectrum."""
    n = len(M)
    factor = linalg.cho_factor(M)
    base = np.zeros((2*n, 2*n))
    base[:n, n:] = np.eye(n)
    base[n:, :n] = -linalg.cho_solve(factor, K)
    base[n:, n:] = -linalg.cho_solve(factor, C)
    gyro = -linalg.cho_solve(factor, G)
    def solve(omega):
        A = base.copy()
        A[n:, n:] += omega * gyro
        return _state_eigen(A)
    return solve


def banded(matrix, width=7):
    """Adjacent four-DOF nodes give at most seven off-diagonals."""
    n = len(matrix)
    out = np.zeros((2*width+1, n), dtype=matrix.dtype)
    for offset in range(-width, width+1):
        start, stop = max(0, offset), min(n, n+offset)
        out[width-offset, start:stop] = np.diag(matrix, offset)
    return out


def normalized_shapes(vectors):
    trans = np.array([i for n in range(len(vectors)//4) for i in (4*n, 4*n+1)])
    shapes = []
    for q in vectors.T:
        qn = q / q[trans[np.argmax(abs(q[trans]))]]
        shapes.append({"x_re": _clean_array(qn[0::4].real), "x_im": _clean_array(qn[0::4].imag),
                       "y_re": _clean_array(qn[1::4].real), "y_im": _clean_array(qn[1::4].imag)})
    return shapes


def mode_shapes_at(data, rpm, targets):
    """Recompute requested-speed shapes, matching stored tracked eigenvalues."""
    d, _, M, K, C, G = assemble(data)
    if isinstance(rpm, bool) or not isinstance(rpm, (int, float)) or not np.isfinite(rpm) or not 0 <= rpm <= d['analysis']['max_rpm']:
        raise InputError("モード形状の回転数を確認してください。")
    t = np.asarray(targets, dtype=float)
    if t.shape != (d['analysis']['modes'], 2) or not np.isfinite(t).all():
        raise InputError("モード形状の固有値を確認してください。")
    vals, vec = eigen(M, K, C + rpm*np.pi/30*G)
    expected = t[:, 0] + 2j*np.pi*t[:, 1]
    distance = abs(expected[:, None] - vals[None, :]) / np.maximum(1, abs(expected[:, None]))
    rows, cols = linear_sum_assignment(distance)
    order = cols[np.argsort(rows)]
    if np.max(distance[np.arange(len(t)), order]) > 1e-5:
        raise InputError("保存した固有値と一致しません。再解析してください。")
    return {"mode_shapes": normalized_shapes(vec[:, order])}


def mac_matrix(previous, current, mass):
    weighted = mass @ current
    inner = previous.conj().T @ weighted
    a = np.real(np.sum(previous.conj() * (mass @ previous), axis=0))
    b = np.real(np.sum(current.conj() * weighted, axis=0))
    return np.clip(abs(inner)**2 / np.outer(a, b), 0, 1)


def whirl(q):
    # Qy=-i Qx describes positive (forward) orbit with exp(i*w*t).
    s = np.imag(np.sum(q[0::4].conj() * q[1::4]))
    scale = np.sum(abs(q[0::4])**2 + abs(q[1::4])**2)
    return "FW" if s < -1e-5 * scale else "BW" if s > 1e-5 * scale else "直線/混合"


def _clean_array(x):
    return np.asarray(x, dtype=float).tolist()


def analyze(data, *, include_shapes=True):
    d, rotor, M, K, C, G = assemble(data)
    a = d["analysis"]
    # Include selected operating speed exactly in the scan.
    rpms = np.unique(np.r_[np.linspace(0, a["max_rpm"], a["points"]), a["operating_rpm"]])
    ns = len(d["shafts"]) + 1
    count = a["modes"]
    freq, decay, logs, shapes, directions, quality, max_real = [], [], [], [], [], [], []
    solve_eigen = eigen_solver(M, K, C, G)
    mass_sparse = sparse.csr_matrix(M)
    all_shapes = include_shapes and len(rpms)*count*ns*4 <= LIMITS["shape_values"]
    op = int(np.argmin(abs(rpms-a["operating_rpm"])))
    prev = None
    min_mac = 1.0
    for speed_index, rpm in enumerate(rpms):
        omega = rpm * np.pi / 30
        vals, vec = solve_eigen(omega)
        max_real.append(float(np.max(vals.real)))
        if prev is None:
            order = np.arange(count)
            scores = np.ones(count)
        else:
            mac = mac_matrix(prev, vec, mass_sparse)
            rows, cols = linear_sum_assignment(-mac)
            order = cols[np.argsort(rows)]
            scores = mac[np.arange(count), order]
            min_mac = min(min_mac, float(min(scores)))
        vals, vec = vals[order], vec[:, order]
        prev = vec
        freq.append(vals.imag / (2 * np.pi))
        decay.append(vals.real)
        logs.append(-2 * np.pi * vals.real / vals.imag)
        quality.append(scores)
        directions.append([whirl(vec[:, j]) for j in range(count)])
        # Keep the operating point; other shapes are requested on demand for large scans.
        shapes.append(normalized_shapes(vec) if include_shapes and (all_shapes or speed_index == op) else None)
    freq, decay, logs = np.array(freq), np.array(decay), np.array(logs)
    criticals = []
    for j in range(count):
        dif = freq[:, j] - rpms / 60
        for i in range(len(rpms)-1):
            if dif[i] * dif[i+1] < 0 or dif[i] == 0:
                t = -dif[i] / (dif[i+1] - dif[i])
                criticals.append({"mode": j+1, "rpm": float(rpms[i] + t*(rpms[i+1]-rpms[i]))})
        if dif[-1] == 0:
            criticals.append({"mode": j+1, "rpm": float(rpms[-1])})
    # Static problem excludes seals; fluid seals do not support weight in this model.
    K_static = K.copy()
    for seal in d["seals"]:
        ix = np.array([4*seal["node"], 4*seal["node"]+1])
        K_static[np.ix_(ix, ix)] -= coefficient_matrix(seal, "k")
    accel = np.zeros(len(M))
    accel[1::4] = -9.80665
    with warnings.catch_warnings():
        warnings.simplefilter("error", linalg.LinAlgWarning)
        try:
            sag = linalg.solve(K_static, M @ accel)
        except (linalg.LinAlgError, linalg.LinAlgWarning) as exc:
            raise InputError("静解析が解けません。支持位置と剛性を確認してください。") from exc
    reactions = []
    for b in d["bearings"]:
        u = sag[4*b["node"]:4*b["node"]+2]
        r = -coefficient_matrix(b, "k") @ u
        reactions.append({"node": b["node"], "fx_N": float(r[0]), "fy_N": float(r[1])})
    # Synchronous linear response at every scan speed; no modal truncation.
    responses, dynamic_reactions = [], []
    Mb, Kb, Cb, Gb = (banded(x) for x in (M, K, C, G))
    for rpm in rpms:
        w = rpm * np.pi / 30
        F = np.zeros(len(M), dtype=complex)
        for un in d["unbalances"]:
            fx = un["g_mm"] * 1e-6 * w**2 * np.exp(1j * np.deg2rad(un["phase_deg"]))
            F[4*un["node"]] += fx
            F[4*un["node"]+1] += -1j * fx
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", linalg.LinAlgWarning)
                Q = linalg.solve_banded((7, 7), Kb - w*w*Mb + 1j*w*(Cb+w*Gb), F)
                # Check the full-system residual, including cross-coupled coefficients.
                A = K - w*w*M + 1j*w*(C+w*G)
                scale = np.linalg.norm(A, ord=np.inf)*np.linalg.norm(Q, ord=np.inf) + np.linalg.norm(F, ord=np.inf)
                if np.linalg.norm(A@Q-F, ord=np.inf) > 1e-9*max(scale, 1e-30):
                    raise linalg.LinAlgError("Response residual exceeds tolerance")
        except (linalg.LinAlgError, linalg.LinAlgWarning) as exc:
            raise InputError("同期応答が特異または悪条件です。無減衰の共振点・係数・分割点を確認してください。") from exc
        responses.append(Q)
        dynamic_reactions.append([abs((coefficient_matrix(b, "k") + 1j*w*coefficient_matrix(b, "c")) @
                                      Q[4*b["node"]:4*b["node"]+2]).tolist() for b in d["bearings"]])
    Q = np.array(responses)
    probe = 4*a["probe_node"]
    op = int(np.argmin(abs(rpms-a["operating_rpm"])))
    theta = np.linspace(0, 2*np.pi, 121)
    amp_x = abs(Q[:, probe])*1e6
    amp_y = abs(Q[:, probe+1])*1e6
    def phases(values):
        # Phase is undefined at zero amplitude; preserve a gap rather than invent 0°.
        return [float(np.rad2deg(np.angle(v))) if abs(v) > 1e-18 else None for v in values]
    stable = "不安定" if max_real[op] > 1e-7 else "漸近安定" if max_real[op] < -1e-7 else "中立/判定境界"
    notes = ["線形・単軸・剛体円板・固定支持。軸受/シール係数は一定。実機・規格適合の検証は未実施。",
             "危険速度は追跡した表示モードの1×交点を線形補間。応答ピークは離散点上の最大値です。",
             "軌道・変位は地面基準の絶対変位、振幅は片振幅。位相は Re(Q exp(iωt)) の規約です。"]
    if min_mac < 0.7:
        notes.append(f"モード追跡の最小MAC={min_mac:.3f}。重根・交差付近のモード番号は不確かです。分割点を増やして確認してください。")
    if max(max_real) > 1e-7:
        notes.append("走査範囲に不安定な固有値があります。該当回転数の定常応答は実際の安定運転振幅を意味しません。")
    if any(not x.get("source", "").strip() for x in d["bearings"] + d["seals"]):
        notes.append("出典が未入力の動特性係数があります。")
    return {
        "model": d, "engine": f"ROSS {rs.__version__} / lateral matrix solver 0.4",
        "rpm": rpms.tolist(), "frequency_hz": freq.tolist(), "real_part": decay.tolist(),
        "log_dec": logs.tolist(), "whirl": directions, "mac": np.array(quality).tolist(),
        "max_real_all_modes": max_real, "critical_speeds": criticals,
        "node_mm": (np.r_[0, np.cumsum([s["length_mm"] for s in d["shafts"]])]).tolist(),
        "static_x_um": (sag[0::4]*1e6).tolist(), "static_y_um": (sag[1::4]*1e6).tolist(),
        "reactions": reactions, "mode_shapes": shapes,
        "amplitude_x_um": amp_x.tolist(), "amplitude_y_um": amp_y.tolist(),
        "phase_x_deg": phases(Q[:, probe]),
        "phase_y_deg": phases(Q[:, probe+1]),
        "orbit_x_um": (np.real(Q[op, probe]*np.exp(1j*theta))*1e6).tolist(),
        "orbit_y_um": (np.real(Q[op, probe+1]*np.exp(1j*theta))*1e6).tolist(),
        "dynamic_reactions_N": dynamic_reactions,
        "operating_index": op, "stability": stable,
        "peak_rpm": float(rpms[np.argmax(np.maximum(amp_x, amp_y))]),
        "peak_um": float(max(max(amp_x), max(amp_y))),
        "mass_kg": float(np.sum((M @ accel)[1::4]) / -9.80665),
        "notes": notes,
    }


def analyze_sweep(data, specification):
    """Independent full solves; skip shape generation for comparison cases."""
    cases = sweep_cases(data, specification, lazy=True)
    fields = ("engine", "rpm", "max_real_all_modes",
              "critical_speeds", "amplitude_x_um", "amplitude_y_um", "phase_x_deg", "phase_y_deg",
              "operating_index", "stability", "peak_rpm", "peak_um", "mass_kg", "notes")
    output = []
    for case in cases:
        summary = {key: case[key] for key in ("index", "parameters")}
        try:
            result = analyze(case["model"], include_shapes=False)
            compact = {key: result[key] for key in fields}
            compact["lowest_frequency_hz"] = np.min(result["frequency_hz"], axis=1).tolist()
            output.append(dict(summary, status="ok", result=compact))
        except (InputError, ValueError, linalg.LinAlgError) as exc:
            output.append(dict(summary, status="error", error=str(exc)))
    success = sum(c["status"] == "ok" for c in output)
    return dict(cases=output, total=len(output), success=success, failed=len(output)-success,
                specification=specification, base_model=validate_model(data))
