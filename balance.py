"""Permissible residual unbalance for a selected rigid rotor (JIS B 0905:1992)."""

import math
from itertools import accumulate

from model import InputError


JIS_GRADES = (0.4, 1, 2.5, 6.3, 16, 40, 100, 250, 630, 1600, 4000)


def _number(value, label, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not minimum <= value <= maximum:
        raise InputError(f"{label}は {minimum:g} ～ {maximum:g} の範囲で入力してください。")
    return value


def _indices(settings, key, size):
    indices = settings.get(key, [])
    if not isinstance(indices, list) or len(indices) > size or any(
        type(i) is not int or not 0 <= i < size for i in indices
    ) or len(set(indices)) != len(indices):
        raise InputError("対象要素を選び直してください。")
    return sorted(indices)


def _shaft_mass_and_center(shaft, density, left_mm):
    # Simpson integration is exact for the area (quadratic) and its first moment (cubic).
    def area(outer, inner):
        return math.pi / 4 * (outer - inner) * (outer + inner)

    outer_left, outer_right = shaft["od_mm"], shaft["odr_mm"]
    inner_left, inner_right = shaft["id_mm"], shaft["idr_mm"]
    left = area(outer_left, inner_left)
    middle = area((outer_left + outer_right) / 2, (inner_left + inner_right) / 2)
    right = area(outer_right, inner_right)
    weighted_area = left + 4 * middle + right
    length = shaft["length_mm"]
    mass = density * (length * weighted_area / 6) * 1e-9
    center = left_mm + length * (2 * middle + right) / weighted_area
    return mass, center


def _allocate(total, center, bearings, positions, static_position):
    support_left, support_right = bearings
    left, right = positions
    span = support_right - support_left
    separation = right - left
    h_left, h_right = abs(center - left), abs(center - right)
    eps = span * 1e-12
    centered = span / 3 - eps <= center - support_left <= 2 * span / 3 + eps
    straddles_center = left < center < right
    details = {"bearing_span_mm": span, "correction_span_mm": separation,
               "center_to_i_mm": h_left, "center_to_ii_mm": h_right}

    if (centered and straddles_center and support_left <= left < right <= support_right
            and separation >= span / 3 - eps
            and 0.3 - 1e-12 <= h_left / separation <= 0.7 + 1e-12):
        return "5.2 (1) / 式 (3), (4)", [total * h_right / separation, total * h_left / separation], details

    if centered and left < support_left and right > support_right:
        scaled = total * span / separation
        return "5.2 (2) / 式 (6), (7)", [scaled * h_right / separation, scaled * h_left / separation], details

    if separation < span / 3 - eps:
        static_position = _number(static_position, "静・準静不釣合いの修正面III [mm]", -1e9, 1e9)
        far_bearing = max(abs(static_position - support_left), abs(static_position - support_right))
        couple = total * (3 / 8) * span / separation
        static = total * span / (4 * far_bearing)
        details.update(static_plane_mm=static_position, couple_phase_deg=180, far_bearing_mm=far_bearing)
        return "5.2 (3) / 式 (8), (9)", [couple, couple, static], details

    # The minimum absolute value in equations (10)-(13) is the tighter of
    # the two bearing limits, using the larger absolute denominator at each bearing.
    k = min(0.7, max(0.3, (support_right - center) / span))
    ratio = min(2, max(0.5, h_left / h_right)) if h_right else 2
    left_limit = total * k * span / (abs(support_right - left) + ratio * abs(support_right - right))
    right_limit = total * (1 - k) * span / (abs(left - support_left) + ratio * abs(right - support_left))
    first = min(left_limit, right_limit)
    details.update(k=k, ratio=ratio)
    return "5.2 (4) / 式 (10)–(14)", [first, ratio * first], details


def calculate_balance(model, settings):
    """Calculate limits using a validated RotorLab model and independently selected components."""
    if not isinstance(settings, dict):
        raise InputError("釣合い計算条件を入力してください。")
    shafts, disks = model["shafts"], model["disks"]
    shaft_indices = _indices(settings, "shaft_indices", len(shafts))
    disk_indices = _indices(settings, "disk_indices", len(disks))
    if not shaft_indices and not disk_indices:
        raise InputError("対象の軸要素または円板を1つ以上選んでください。")
    grade = settings.get("grade")
    if isinstance(grade, bool) or grade not in JIS_GRADES:
        raise InputError("JISの釣合い良さの等級を選んでください。")
    rpm = _number(settings.get("max_rpm"), "実用最高回転速度 [rpm]", 1, 200000)
    plane_count = settings.get("plane_count")
    if type(plane_count) is not int or plane_count not in (1, 2):
        raise InputError("1面または2面の釣合わせを選んでください。")

    nodes = list(accumulate((shaft["length_mm"] for shaft in shafts), initial=0))
    density = {item["id"]: item["rho"] for item in model["materials"]}
    components = [
        _shaft_mass_and_center(shafts[i], density[shafts[i].get("material_id") or model["default_material_id"]], nodes[i])
        for i in shaft_indices
    ]
    components.extend((disks[i]["mass_kg"], nodes[disks[i]["node"]]) for i in disk_indices)
    mass = math.fsum(m for m, _ in components)
    center = math.fsum(m * z for m, z in components) / mass
    specific = 1000 * grade / (math.tau * rpm / 60)
    total = specific * mass
    first = _number(settings.get("plane_i_mm"), "修正面Iの位置 [mm]", -1e9, 1e9)
    positions = [first]
    details = {}
    if plane_count == 1:
        clause, limits = "5.1", [total]
    else:
        bearing_a = _number(settings.get("bearing_a_mm"), "使用時の軸受Aの位置 [mm]", -1e9, 1e9)
        bearing_b = _number(settings.get("bearing_b_mm"), "使用時の軸受Bの位置 [mm]", -1e9, 1e9)
        second = _number(settings.get("plane_ii_mm"), "修正面IIの位置 [mm]", -1e9, 1e9)
        if bearing_b - bearing_a < 1e-6 or second - first < 1e-6:
            raise InputError("軸受A→Bと修正面I→IIを軸方向の昇順で、異なる位置に指定してください。")
        positions.append(second)
        clause, limits, details = _allocate(total, center, (bearing_a, bearing_b), positions, settings.get("plane_iii_mm"))
        if "static_plane_mm" in details:
            positions.append(details["static_plane_mm"])

    return {"standard": "JIS B 0905:1992", "clause": clause, "mass_kg": mass, "center_mm": center,
            "specific_um": specific, "total_g_mm": total, "details": details,
            "planes": [{"name": name, "position_mm": position, "limit_g_mm": limit}
                       for name, position, limit in zip(("I", "II", "III"), positions, limits)]}
