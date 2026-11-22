"""Apply gas-turbine operating speed, disk data, and bearing coefficient tables."""
from bisect import bisect_right
import math

from engine import analyze
from gas_turbine_cycle_app.design_exchange import cycle_source, number
from model import validate_model


COEFFICIENTS = ("kxx", "kyy", "kxy", "kyx", "cxx", "cyy", "cxy", "cyx")


def bearing_coefficients(rows, speed):
    if not rows:
        raise ValueError("軸受係数表を指定してください。")
    rpms = [number(row["rpm"], "係数表の回転数", 0.) for row in rows]
    if any(b <= a for a,b in zip(rpms,rpms[1:])) or not rpms[0] <= speed <= rpms[-1]:
        raise ValueError("軸受係数表を回転数順に並べ、運転回転数を範囲内に含めてください。")
    coefficients = [{key: number(row[key], key) for key in COEFFICIENTS} for row in rows]
    index = bisect_right(rpms,speed)
    if speed == rpms[index-1]:
        return coefficients[index-1]
    weight = (speed-rpms[index-1])/(rpms[index]-rpms[index-1])
    return {key: coefficients[index-1][key]*(1-weight)+coefficients[index][key]*weight for key in COEFFICIENTS}


def evaluate(case, setup):
    speed = case["input"]["parameters"]["shaft_speed_rpm"]
    cases = {}
    for name, variant in setup["cases"].items():
        model = validate_model(variant["model"])
        model["name"] = name
        model["analysis"]["operating_rpm"] = speed
        positions = [0.]
        for shaft in model["shafts"]:
            positions.append(positions[-1]+shaft["length_mm"])
        disks = []
        for disk in variant["disks"]:
            x = number(disk["x_mm"], "回転部品の軸上位置", 0.)
            node = next((index for index,value in enumerate(positions)
                         if math.isclose(value,x,rel_tol=0,abs_tol=1e-6)), None)
            if node is None:
                raise ValueError("回転部品の軸上位置に一致するRotorLab節点を設定してください。")
            disks.append({"node":node, **{key:disk[key] for key in ("mass_kg","Id_kgm2","Ip_kgm2")}})
        model["disks"] = disks
        supply = variant.get("oil_supply")
        tables = variant["bearing_tables"]
        if (len(tables) != len(model["bearings"])
                or {row["bearing_index"] for row in tables} != set(range(len(model["bearings"])))):
            raise ValueError("全軸受に係数表を1つずつ設定してください。")
        oil_inputs = []
        for table in tables:
            idx = table["bearing_index"]
            source = table["source"]
            if not isinstance(source,str) or not source.strip():
                raise ValueError("軸受係数表の出典を指定してください。")
            model["bearings"][idx].update(bearing_coefficients(table["rows"],speed), source=source)
            if supply:
                feed = supply["bearings"][table["bearing_id"]]
                oil_inputs.append({"bearing_index":idx,"bearing_id":table["bearing_id"],
                                   "temperature_c":supply["temperature_c"],**feed})
        report = analyze(validate_model(model),include_shapes=False)
        criticals = report["critical_speeds"]
        nearest = min(criticals,key=lambda x:abs(x["rpm"]-speed)) if criticals else None
        at = report["operating_index"]
        cases[name] = {"model":report["model"], "analysis":report, "oil_supply":oil_inputs,
                       "operating_rpm":speed, "nearest_critical":nearest,
                       "separation_margin_fraction":None if nearest is None else abs(nearest["rpm"]-speed)/speed,
                       "operating_amplitude_um":max(report["amplitude_x_um"][at],report["amplitude_y_um"][at])}
    if not cases:
        raise ValueError("比較するロータ案を指定してください。")
    return {"format":"cycle-rotor-dynamics-handoff","schema_version":1,"source_cycle":cycle_source(case),
            "bearing_coefficients":"fixed_at_operating_rpm_for_each_speed_scan","cases":cases}
