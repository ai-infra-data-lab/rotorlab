"""Reproducible solver-only capacity measurements (not browser/startup timing)."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import time

from engine import analyze, analyze_sweep
from test_capacity import refined_model


def peak_working_set_mb():
    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ('peak_ws', 'ws', 'peak_paged', 'paged',
                                               'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile')]
    counters = Counters();counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return round(counters.peak_ws/1024**2, 1)


def main():
    records = []
    for elements, points, modes, cases in ((64, 21, 12, 1), (128, 3, 32, 1), (128, 21, 32, 1),
                                          (6, 1001, 6, 1), (6, 2, 6, 256)):
        d = refined_model(elements);d['analysis'].update(points=points, modes=modes)
        start = time.perf_counter()
        if cases == 1:
            result = analyze(d)
            peak = result['peak_um'];success = 1
        else:
            spec = dict(parameters=[dict(bearing=0, coefficient='kxx_kyy',
                                         values=[5e5+1.5e6*i/(cases-1) for i in range(cases)])])
            result = analyze_sweep(d, spec)
            peak = max(c['result']['peak_um'] for c in result['cases'] if c['status']=='ok')
            success = result['success']
        elapsed = time.perf_counter()-start
        payload = len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8'))
        record = dict(elements=elements, requested_points=points, modes=modes, cases=cases,
                      success=success, seconds=round(elapsed, 3), json_bytes=payload,
                      process_peak_working_set_mb=peak_working_set_mb(), peak_um=peak)
        print(json.dumps(record), flush=True);records.append(record)
    path = Path('artifacts/capacity-benchmark.json');path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(records, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
