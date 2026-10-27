"""JSON model and strict engineering input validation; all UI units explicit."""
import copy
import math


class InputError(ValueError):
    pass


def sample_model():
    return {
        "schema_version": 1,
        "name": "単軸タービン・学習モデル（架空）",
        "note": "寸法・物性・軸受係数は説明用の仮定値。実機データではありません。",
        "material": {"rho": 7810, "E_GPa": 211, "G_GPa": 81.2},
        "shafts": [{"length_mm": 250, "od_mm": 50, "id_mm": 0} for _ in range(6)],
        "disks": [
            {"node": 2, "mass_kg": 32.58972765, "Id_kgm2": 0.17808928, "Ip_kgm2": 0.32956362},
            {"node": 4, "mass_kg": 52.96625953, "Id_kgm2": 0.4604787, "Ip_kgm2": 0.86744423},
        ],
        "bearings": [dict(node=n, kxx=1e6, kyy=1e6, kxy=0, kyx=0,
                          cxx=500, cyy=500, cxy=0, cyx=0, source="仮定値") for n in (0, 6)],
        "seals": [],
        "unbalances": [{"node": 2, "g_mm": 100, "phase_deg": 0}],
        "analysis": {"max_rpm": 12000, "operating_rpm": 6000, "points": 61, "probe_node": 4, "modes": 6},
    }


def validate_model(data):
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise InputError("対応するモデル形式は schema_version=1 です。")
    d = copy.deepcopy(data)
    def number(obj, key, label, minimum=None, maximum=None, integer=False):
        v = obj.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise InputError(f"{label}: 有限の数値を入力してください。")
        if minimum is not None and v < minimum or maximum is not None and v > maximum:
            raise InputError(f"{label}: 範囲 {minimum} ～ {maximum} を確認してください。")
        if integer and int(v) != v:
            raise InputError(f"{label}: 整数を入力してください。")
        if integer:
            obj[key] = int(v)
        return v
    if not isinstance(d.get("name"), str) or not d["name"].strip() or len(d["name"]) > 120:
        raise InputError("モデル名は1～120文字で入力してください。")
    if not isinstance(d.get("note", ""), str):
        raise InputError("モデル注記は文字列で入力してください。")
    mat = d.get("material")
    if not isinstance(mat, dict):
        raise InputError("材料を指定してください。")
    number(mat, "rho", "密度 [kg/m³]", 1, 30000)
    E = number(mat, "E_GPa", "ヤング率 [GPa]", 0.001, 2000)
    G = number(mat, "G_GPa", "せん断弾性係数 [GPa]", 0.001, 2000)
    if not -1 < E / (2 * G) - 1 < 0.5:
        raise InputError("EとGから求まるポアソン比が -1 < ν < 0.5 を満たしません。")
    for key in ("shafts", "disks", "bearings", "seals", "unbalances"):
        if not isinstance(d.get(key), list) or len(d[key]) > 40 or any(not isinstance(x, dict) for x in d[key]):
            raise InputError(f"{key}: 部品のリスト（最大40件）が必要です。")
    if not 1 <= len(d["shafts"]) <= 24:
        raise InputError("軸要素は1～24個にしてください。")
    nn = len(d["shafts"])
    for i, el in enumerate(d["shafts"]):
        number(el, "length_mm", f"軸{i} 長さ [mm]", 0.1, 20000)
        od = number(el, "od_mm", f"軸{i} 外径 [mm]", 0.1, 5000)
        id_ = number(el, "id_mm", f"軸{i} 内径 [mm]", 0, 4999)
        if id_ >= od:
            raise InputError(f"軸{i}: 内径は外径より小さくしてください。")
    if len({b.get("node") for b in d["bearings"] if isinstance(b.get("node"), (int, float))}) < 2:
        raise InputError("異なる2節点以上に軸受を配置してください。")
    for key in ("disks", "bearings", "seals", "unbalances"):
        for i, el in enumerate(d[key]):
            number(el, "node", f"{key}[{i}] 節点", 0, nn, integer=True)
            if key == "disks":
                for field in ("mass_kg", "Id_kgm2", "Ip_kgm2"):
                    number(el, field, f"円板{i} {field}", 1e-12, 1e7)
                if el["Ip_kgm2"] > 2 * el["Id_kgm2"] * (1 + 1e-8):
                    raise InputError(f"円板{i}: 軸対称円板は Ip ≤ 2 Id を満たす必要があります。")
            elif key in ("bearings", "seals"):
                for p in ("kxx", "kyy", "kxy", "kyx", "cxx", "cyy", "cxy", "cyx"):
                    number(el, p, f"{key}[{i}] {p}", -1e12, 1e12)
                if key == "bearings" and (el["kxx"] <= 0 or el["kyy"] <= 0):
                    raise InputError("軸受の直接剛性 kxx, kyy は正数にしてください。")
                if not isinstance(el.get("source", ""), str):
                    raise InputError("係数の出典は文字列で入力してください。")
            else:
                number(el, "g_mm", "不釣合い [g mm]", 0, 1e9)
                number(el, "phase_deg", "位相 [deg]", -36000, 36000)
    a = d.get("analysis")
    if not isinstance(a, dict):
        raise InputError("解析条件が必要です。")
    mx = number(a, "max_rpm", "最大回転数 [rpm]", 1, 200000)
    number(a, "operating_rpm", "確認回転数 [rpm]", 0, mx)
    number(a, "points", "回転数分割点数", 11, 121, integer=True)
    number(a, "modes", "表示モード数", 2, min(12, 4 * (nn + 1)), integer=True)
    number(a, "probe_node", "計測節点", 0, nn, integer=True)
    return d
