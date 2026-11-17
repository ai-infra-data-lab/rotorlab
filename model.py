"""JSON model and strict engineering input validation; all UI units explicit."""
import copy
import math
import itertools

from limits import LIMITS

MAX_SWEEP_CASES = LIMITS["sweep_cases"]
STIFFNESS_FIELDS = ("kxx", "kyy", "kxy", "kyx")


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
    if not isinstance(data, dict) or isinstance(data.get("schema_version"), bool) or data.get("schema_version") not in (1, 2, 3):
        raise InputError("対応するモデル形式は schema_version=1、2、3です。")
    d = copy.deepcopy(data)
    old_version = d["schema_version"]
    d["schema_version"] = 3
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
    def material(mat, label):
        if not isinstance(mat, dict):
            raise InputError(f"{label}: 材料を指定してください。")
        number(mat, "rho", f"{label} 密度 [kg/m³]", 1, 30000)
        E = number(mat, "E_GPa", f"{label} ヤング率 [GPa]", 0.001, 2000)
        G = number(mat, "G_GPa", f"{label} せん断弾性係数 [GPa]", 0.001, 2000)
        if not -1 < E / (2 * G) - 1 < 0.5:
            raise InputError(f"{label}: EとGから求まるポアソン比が -1 < ν < 0.5 を満たしません。")
    if old_version < 3:
        material(d.get("material"), "共通材料")
    for key in ("shafts", "disks", "bearings", "seals", "unbalances"):
        capacity = LIMITS["shafts"] if key == "shafts" else LIMITS["components"]
        if not isinstance(d.get(key), list) or len(d[key]) > capacity or any(not isinstance(x, dict) for x in d[key]):
            raise InputError(f"{key}: 部品のリスト（最大{capacity}件）が必要です。")
    if not 1 <= len(d["shafts"]) <= LIMITS["shafts"]:
        raise InputError(f"軸要素は1～{LIMITS['shafts']}個にしてください。")
    nn = len(d["shafts"])
    if old_version < 3:
        if "materials" in d or "default_material_id" in d or any("material_id" in el for el in d["shafts"]):
            raise InputError("材料一覧を使うモデルは schema_version=3 で保存してください。")
        common = d.pop("material")
        d["materials"] = [dict(common, id="default", name="共通材料")]
        d["default_material_id"] = "default"
        for i, el in enumerate(d["shafts"]):
            props = el.pop("material", None)
            if props is not None:
                material(props, f"軸{i}の個別材料")
                material_id = f"legacy-shaft-{i}"
                d["materials"].append(dict(props, id=material_id, name=f"旧個別材料（軸{i}）"))
                el["material_id"] = material_id
    elif "material" in d or any("material" in el for el in d["shafts"]):
        raise InputError("schema_version=3の物性は材料一覧で指定してください。")
    registry = d.get("materials")
    if not isinstance(registry, list) or not 1 <= len(registry) <= LIMITS["materials"]:
        raise InputError(f"材料一覧は1～{LIMITS['materials']}件にしてください。")
    material_ids, material_names = set(), set()
    for i, props in enumerate(registry):
        material(props, f"材料{i}")
        mid, name = props.get("id"), props.get("name")
        if not isinstance(mid, str) or not mid.strip() or len(mid) > 64 or mid in material_ids:
            raise InputError("材料IDは重複しない1～64文字で指定してください。")
        if not isinstance(name, str) or not name.strip() or len(name) > 120 or name.strip() in material_names:
            raise InputError("材料名は重複しない1～120文字で入力してください。")
        if not isinstance(props.get("source", ""), str):
            raise InputError("材料の出典は文字列で入力してください。")
        props["name"] = name.strip()
        material_ids.add(mid); material_names.add(props["name"])
    default_id = d.get("default_material_id")
    if not isinstance(default_id, str) or default_id not in material_ids:
        raise InputError("既定材料を材料一覧から指定してください。")
    for i, el in enumerate(d["shafts"]):
        number(el, "length_mm", f"軸{i} 長さ [mm]", 0.1, 20000)
        el.setdefault("odr_mm", el.get("od_mm"))
        el.setdefault("idr_mm", el.get("id_mm"))
        for side, od_key, id_key in (("左端", "od_mm", "id_mm"), ("右端", "odr_mm", "idr_mm")):
            od = number(el, od_key, f"軸{i} {side}外径 [mm]", 0.1, 5000)
            id_ = number(el, id_key, f"軸{i} {side}内径 [mm]", 0, 4999)
            if id_ >= od:
                raise InputError(f"軸{i} {side}: 内径は外径より小さくしてください。")
        mid = el.get("material_id")
        if mid is not None and (not isinstance(mid, str) or mid not in material_ids):
            raise InputError(f"軸{i}: 材料一覧に存在する材料を選択してください。")
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
    number(a, "points", "回転数分割点数", 2, LIMITS["points"], integer=True)
    number(a, "modes", "表示モード数", 1, min(LIMITS["modes"], 4 * (nn + 1)), integer=True)
    number(a, "probe_node", "計測節点", 0, nn, integer=True)
    if "sweep" in d:
        s = d["sweep"]
        if not isinstance(s, dict) or s.get("mode") not in ("cartesian", "paired") or not isinstance(s.get("parameters"), list) or len(s["parameters"]) > LIMITS["sweep_parameters"]:
            raise InputError("保存された一括計算設定の形式を確認してください。")
        for p in s["parameters"]:
            if not isinstance(p, dict) or p.get("coefficient") not in (*STIFFNESS_FIELDS, "kxx_kyy"):
                raise InputError("保存された一括計算の剛性成分を確認してください。")
            number(p, "bearing", "一括計算の軸受番号", 0, len(d["bearings"])-1, integer=True)
            if p.get("values") is None:
                if not isinstance(p.get("raw"), str) or len(p["raw"]) > 4096:
                    raise InputError("候補値の入力形式を確認してください。")
            elif not isinstance(p["values"], list) or len(p["values"]) > MAX_SWEEP_CASES:
                raise InputError("保存された候補値の形式を確認してください。")
            elif any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in p["values"]):
                raise InputError("候補値は有限の数値にしてください。")
    return d


def sweep_cases(data, specification, *, lazy=False):
    """Validate all combinations before solving; never mutate the base model."""
    base = validate_model(data)
    if not isinstance(specification, dict):
        raise InputError("一括計算の条件を指定してください。")
    mode = specification.get("mode", "cartesian")
    if mode not in ("cartesian", "paired"):
        raise InputError("組合せ方式はcartesianまたはpairedです。")
    parameters = specification.get("parameters")
    if not isinstance(parameters, list) or not 1 <= len(parameters) <= LIMITS["sweep_parameters"]:
        raise InputError(f"一括計算のパラメータは1～{LIMITS['sweep_parameters']}行にしてください。")
    normalized, occupied = [], set()
    for index, p in enumerate(parameters):
        if not isinstance(p, dict):
            raise InputError("一括計算の各行を確認してください。")
        b, key, values = p.get("bearing"), p.get("coefficient"), p.get("values")
        if isinstance(b, bool) or not isinstance(b, int) or not 0 <= b < len(base["bearings"]):
            raise InputError(f"パラメータ{index+1}: 軸受番号を確認してください。")
        if key not in (*STIFFNESS_FIELDS, "kxx_kyy"):
            raise InputError("変更できる成分はkxx/kyy/kxy/kyx/kxx_kyyです。")
        targets = ("kxx", "kyy") if key == "kxx_kyy" else (key,)
        if any((b, field) in occupied for field in targets):
            raise InputError("同じ軸受・剛性成分が重複しています（kxx+kyyも含みます）。")
        occupied.update((b, field) for field in targets)
        if not isinstance(values, list) or not 1 <= len(values) <= MAX_SWEEP_CASES:
            raise InputError(f"パラメータ{index+1}: 候補値は1～{MAX_SWEEP_CASES}個にしてください。")
        for v in values:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) > 1e12:
                raise InputError("剛性の候補値は有限の数値（絶対値1e12以下）にしてください。")
            if key in ("kxx", "kyy", "kxx_kyy") and v <= 0:
                raise InputError("直接剛性の候補値は正数にしてください。")
        normalized.append(dict(bearing=b, coefficient=key, values=list(values)))
    lengths = [len(p["values"]) for p in normalized]
    count = math.prod(lengths) if mode == "cartesian" else max(lengths)
    if count > MAX_SWEEP_CASES:
        raise InputError(f"組合せは{count}ケースです。一度の上限は{MAX_SWEEP_CASES}ケースです。")
    if mode == "paired" and any(n not in (1, count) for n in lengths):
        raise InputError("同じ順番の組合せでは候補数をそろえてください。1個の値は全ケースで共通です。")
    combos = (itertools.product(*(p["values"] for p in normalized)) if mode == "cartesian"
              else ([p["values"][0 if len(p["values"]) == 1 else i] for p in normalized] for i in range(count)))
    def generate():
        for index, combo in enumerate(combos):
            case = copy.deepcopy(base)
            changes = []
            for p, value in zip(normalized, combo):
                keys = ("kxx", "kyy") if p["coefficient"] == "kxx_kyy" else (p["coefficient"],)
                for field in keys:
                    case["bearings"][p["bearing"]][field] = value
                changes.append(dict(bearing=p["bearing"], node=base["bearings"][p["bearing"]]["node"],
                                    coefficient=p["coefficient"], value=value))
            yield dict(index=index + 1, model=case, parameters=changes)
    return generate() if lazy else list(generate())
