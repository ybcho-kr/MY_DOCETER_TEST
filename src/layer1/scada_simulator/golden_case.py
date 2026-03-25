"""Golden Case 검증 — 조류계산 결과 기준값 생성 및 비교.

편차 기준: 전압 ±1% (0.01 pu), 부하율 ±1%.
모든 수치는 pandapower 솔버 반환값 — LLM 생성 금지.

파일 구조 (JSON):
    {
        "meta": {
            "created_at": "2026-03-25T00:00:00Z",
            "network_type": "ieee14 | raw_kr",
            "bus_count": 14,
            "line_count": 20,
            "sn_mva": 100.0
        },
        "bus_vm_pu": {"0": 1.060, ...},
        "line_loading_pct": {"0": 45.2, ...},
        "trafo_loading_pct": {"0": 30.1, ...},
        "total_p_gen_mw": 259.0,
        "total_p_load_mw": 257.5,
        "total_loss_mw": 1.5
    }
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandapower as pp

logger = logging.getLogger(__name__)


def _compute_total_gen(net: pp.pandapowerNet) -> float:
    """발전기 합계 계산 (gen + ext_grid + sgen 포함).

    Args:
        net: runpp() 완료된 pandapower 네트워크.

    Returns:
        전체 발전 유효전력 합계 (MW).
    """
    total = 0.0
    if not net.res_gen.empty:
        total += float(net.res_gen["p_mw"].sum())
    if not net.res_ext_grid.empty:
        total += float(net.res_ext_grid["p_mw"].sum())
    if hasattr(net, "res_sgen") and not net.res_sgen.empty:
        total += float(net.res_sgen["p_mw"].sum())
    return total


def create_golden_case(
    net: pp.pandapowerNet,
    network_type: str = "unknown",
) -> dict[str, Any]:
    """Golden Case 기준값 생성.

    현재 네트워크에서 조류계산을 실행하고 결과를 사전으로 반환.
    변압기 부하율도 함께 저장한다.

    Args:
        net: pandapower 네트워크.
        network_type: 네트워크 종류 식별자 (예: 'ieee14', 'raw_kr').

    Returns:
        기준값 사전.
        필드: meta, bus_vm_pu, line_loading_pct, trafo_loading_pct,
               total_p_gen_mw, total_p_load_mw, total_loss_mw.

    Raises:
        RuntimeError: 조류계산 수렴 실패 시.
    """
    try:
        pp.runpp(net)
    except pp.powerflow.LoadflowNotConverged as exc:
        raise RuntimeError(
            "Golden Case 생성 실패: 조류계산 수렴 실패. "
            "부하 조건이나 초기값을 확인하세요."
        ) from exc

    total_gen = _compute_total_gen(net)
    total_load = float(net.res_load["p_mw"].sum()) if not net.res_load.empty else 0.0
    total_loss = max(0.0, total_gen - total_load)

    # 변압기 부하율 (trafo)
    trafo_loading: dict[str, float] = {}
    if hasattr(net, "res_trafo") and not net.res_trafo.empty:
        for idx in net.res_trafo.index:
            trafo_loading[str(idx)] = float(net.res_trafo.at[idx, "loading_percent"])

    golden: dict[str, Any] = {
        "meta": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "network_type": network_type,
            "bus_count": len(net.bus),
            "line_count": len(net.line),
            "trafo_count": len(net.trafo),
            "sn_mva": float(net.sn_mva) if hasattr(net, "sn_mva") else 100.0,
        },
        "bus_vm_pu": {
            str(idx): float(net.res_bus.at[idx, "vm_pu"])
            for idx in net.res_bus.index
        },
        "line_loading_pct": {
            str(idx): float(net.res_line.at[idx, "loading_percent"])
            for idx in net.res_line.index
        },
        "trafo_loading_pct": trafo_loading,
        "total_p_gen_mw": total_gen,
        "total_p_load_mw": total_load,
        "total_loss_mw": total_loss,
    }
    logger.info(
        "Golden Case 생성 완료: type=%s, buses=%d, lines=%d, loss=%.2f MW",
        network_type, len(net.bus), len(net.line), total_loss,
    )
    return golden


def verify_against_golden(
    net: pp.pandapowerNet,
    golden: dict[str, Any],
    tolerance_pct: float = 1.0,
    skip_on_diverge: bool = True,
) -> tuple[bool, list[str]]:
    """Golden Case 대비 검증.

    버스 전압과 선로 부하율을 기준값과 비교한다.
    변압기 부하율도 비교 대상에 포함한다.

    Args:
        net: pandapower 네트워크 (runpp 실행 전이면 내부에서 실행).
        golden: create_golden_case()로 생성한 기준값.
        tolerance_pct: 허용 편차 (%). 기본 1%. Layer1 CLAUDE.md 기준.
        skip_on_diverge: True이면 수렴 실패 시 (False, ["수렴실패"]) 반환.

    Returns:
        (합격 여부, 위반 항목 목록).
    """
    try:
        pp.runpp(net)
    except pp.powerflow.LoadflowNotConverged:
        logger.warning("Golden Case 검증: 조류계산 수렴 실패.")
        if skip_on_diverge:
            return False, ["조류계산 수렴 실패 — 검증 불가"]
        return False, ["조류계산 수렴 실패"]

    violations: list[str] = []
    tol = tolerance_pct / 100.0

    # 모선 전압 비교
    for bus_str, golden_vm in golden.get("bus_vm_pu", {}).items():
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
    for line_str, golden_loading in golden.get("line_loading_pct", {}).items():
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

    # 변압기 부하율 비교 (선택)
    if hasattr(net, "res_trafo") and not net.res_trafo.empty:
        for trafo_str, golden_tl in golden.get("trafo_loading_pct", {}).items():
            trafo_idx = int(trafo_str)
            if trafo_idx not in net.res_trafo.index:
                violations.append(f"Trafo {trafo_idx}: 결과에 없음")
                continue
            actual_tl = float(net.res_trafo.at[trafo_idx, "loading_percent"])
            if golden_tl > 0 and abs(actual_tl - golden_tl) / golden_tl > tol:
                violations.append(
                    f"Trafo {trafo_idx}: 부하율 {actual_tl:.2f}% vs golden {golden_tl:.2f}% "
                    f"(편차 {abs(actual_tl - golden_tl) / golden_tl * 100:.2f}%)"
                )

    passed = len(violations) == 0
    if passed:
        logger.info("Golden Case 검증 합격: 위반 없음 (허용편차 %.1f%%)", tolerance_pct)
    else:
        logger.warning(
            "Golden Case 검증 불합격: 위반 %d건 (허용편차 %.1f%%)",
            len(violations), tolerance_pct,
        )
    return passed, violations


def save_golden_case(golden: dict[str, Any], path: str | Path) -> None:
    """Golden Case를 JSON 파일로 저장.

    Args:
        golden: create_golden_case() 반환값.
        path: 저장 경로 (확장자 .json 권장).
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(golden, f, indent=2, ensure_ascii=False)
    logger.info("Golden Case 저장: %s", p)


def load_golden_case(path: str | Path) -> dict[str, Any]:
    """JSON 파일에서 Golden Case 로드.

    Args:
        path: 저장된 .json 파일 경로.

    Returns:
        Golden Case 사전.

    Raises:
        FileNotFoundError: 파일이 존재하지 않을 때.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Golden Case 파일 없음: {path}")
    with open(p, encoding="utf-8") as f:
        return json.load(f)
