"""Golden Case 검증 — 조류계산 결과 기준값 생성 및 비교.

편차 기준: 전압 ±1% (0.01 pu), 부하율 ±1%.
모든 수치는 pandapower 솔버 반환값 — LLM 생성 금지.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandapower as pp


def create_golden_case(net: pp.pandapowerNet) -> dict[str, Any]:
    """Golden Case 기준값 생성.

    현재 네트워크에서 조류계산을 실행하고 결과를 사전으로 반환.

    Args:
        net: pandapower 네트워크.

    Returns:
        기준값 사전 (bus_vm_pu, line_loading_pct, total_loss_mw).
    """
    pp.runpp(net)

    golden: dict[str, Any] = {
        "bus_vm_pu": {
            str(idx): float(net.res_bus.at[idx, "vm_pu"])
            for idx in net.res_bus.index
        },
        "line_loading_pct": {
            str(idx): float(net.res_line.at[idx, "loading_percent"])
            for idx in net.res_line.index
        },
        "total_loss_mw": float(
            net.res_gen["p_mw"].sum() - net.res_load["p_mw"].sum()
        ),
    }
    return golden


def verify_against_golden(
    net: pp.pandapowerNet,
    golden: dict[str, Any],
    tolerance_pct: float = 1.0,
) -> tuple[bool, list[str]]:
    """Golden Case 대비 검증.

    Args:
        net: pandapower 네트워크 (runpp 실행 전이면 내부에서 실행).
        golden: create_golden_case()로 생성한 기준값.
        tolerance_pct: 허용 편차 (%). 기본 1%.

    Returns:
        (합격 여부, 위반 항목 목록).
    """
    pp.runpp(net)
    violations: list[str] = []
    tol = tolerance_pct / 100.0

    # 모선 전압 비교
    for bus_str, golden_vm in golden["bus_vm_pu"].items():
        bus_idx = int(bus_str)
        if bus_idx not in net.res_bus.index:
            violations.append(f"Bus {bus_idx}: 결과에 없음")
            continue
        actual_vm = float(net.res_bus.at[bus_idx, "vm_pu"])
        if golden_vm > 0 and abs(actual_vm - golden_vm) / golden_vm > tol:
            violations.append(
                f"Bus {bus_idx}: 전압 {actual_vm:.6f} pu vs golden {golden_vm:.6f} pu "
                f"(편차 {abs(actual_vm - golden_vm) / golden_vm * 100:.2f}%)"
            )

    # 선로 부하율 비교
    for line_str, golden_loading in golden["line_loading_pct"].items():
        line_idx = int(line_str)
        if line_idx not in net.res_line.index:
            violations.append(f"Line {line_idx}: 결과에 없음")
            continue
        actual_loading = float(net.res_line.at[line_idx, "loading_percent"])
        if golden_loading > 0 and abs(actual_loading - golden_loading) / golden_loading > tol:
            violations.append(
                f"Line {line_idx}: 부하율 {actual_loading:.2f}% vs golden {golden_loading:.2f}% "
                f"(편차 {abs(actual_loading - golden_loading) / golden_loading * 100:.2f}%)"
            )

    return len(violations) == 0, violations


def save_golden_case(golden: dict[str, Any], path: str | Path) -> None:
    """Golden Case를 JSON 파일로 저장."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(golden, f, indent=2, ensure_ascii=False)


def load_golden_case(path: str | Path) -> dict[str, Any]:
    """JSON 파일에서 Golden Case 로드."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)
