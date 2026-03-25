"""SCA(단락전류 분석) 계산 엔진 — pandapower calc_sc() 기반.

IEC 60909 표준에 따른 3상/1선 지락 단락전류 계산.
모든 수치는 pandapower 솔버 반환값만 사용 — LLM 수치 생성 절대 금지.

참고:
  - IEC 60909: 단락전류 계산 국제 표준
  - ikss_ka: 초기 대칭 단락전류 (Initial symmetrical short-circuit current)
  - skss_mva: 초기 대칭 단락용량 (Initial symmetrical short-circuit power)
  - 전압 계수 c: 1.1 (최대, 3상 단락) / 1.0 (최소)
  - pandapower calc_sc()는 ext_grid/gen에 단락전류 임피던스 파라미터 필수
"""
from __future__ import annotations

import copy
import logging
import math
from datetime import datetime, timezone
from typing import Literal

import pandapower as pp
import pandapower.shortcircuit as sc

from src.shared.schemas.study import ShortCircuitResult

logger = logging.getLogger(__name__)

#: pandapower calc_sc()의 fault 인수 → ShortCircuitResult fault_type 매핑
_PP_FAULT_TYPE_MAP: dict[str, str] = {
    "3ph": "3ph",     # 3상 단락
    "slg": "1ph",     # 1선 지락 (Single Line to Ground) — 영상 임피던스 필요
    "llg": "2ph-g",   # 2선 지락 (Line to Line to Ground)
    "ll": "2ph",      # 2선 단락 (Line to Line)
}

#: 3상 단락 지원 여부 (Phase 1 기본)
_3PH_SUPPORTED_FAULTS: frozenset[str] = frozenset({"3ph"})

#: 비대칭 고장(영상 임피던스 필요) 유형
_UNBALANCED_FAULTS: frozenset[str] = frozenset({"slg", "llg", "ll"})

#: 기본 단락전류 임피던스 파라미터 — IEEE 14-bus 범용 근사값
#: 실제 운영에서는 설비 실측 데이터 사용 필수
_DEFAULT_S_SC_MAX_MVA: float = 1000.0   # 외부 계통 최대 단락용량
_DEFAULT_S_SC_MIN_MVA: float = 1000.0   # 외부 계통 최소 단락용량
_DEFAULT_RX_MAX: float = 0.1            # 최대 단락전류 시 r/x 비
_DEFAULT_RX_MIN: float = 0.1            # 최소 단락전류 시 r/x 비
_DEFAULT_XDSS_PU: float = 0.12          # 발전기 서브트랜지언트 리액턴스 (표준값)
_DEFAULT_COS_PHI: float = 0.8           # 발전기 역률 (표준값)
_DEFAULT_X0X_MAX: float = 3.0           # 영상/정상 임피던스 비 (변압기 접지형)
_DEFAULT_X0X_MIN: float = 3.0
_DEFAULT_R0X0_MAX: float = 0.1
_DEFAULT_R0X0_MIN: float = 0.1


def _prepare_sc_net(net: pp.pandapowerNet) -> pp.pandapowerNet:
    """단락전류 계산을 위한 계통 모델 준비 (deepcopy + 파라미터 설정).

    pandapower calc_sc()는 ext_grid에 s_sc_max_mva, gen에 vn_kv/xdss_pu 필수.
    계통 모델에 해당 파라미터가 없으면 기본값을 자동으로 설정한다.

    Args:
        net: 원본 pandapower 계통 모델 (수정하지 않음).

    Returns:
        단락전류 계산용으로 준비된 deepcopy 모델.
    """
    net_sc = copy.deepcopy(net)

    # ── ext_grid 단락 임피던스 설정 ─────────────────────────────
    if "s_sc_max_mva" not in net_sc.ext_grid.columns or net_sc.ext_grid["s_sc_max_mva"].isna().any():
        net_sc.ext_grid["s_sc_max_mva"] = _DEFAULT_S_SC_MAX_MVA
        logger.debug("ext_grid.s_sc_max_mva 기본값 설정: %.0f MVA", _DEFAULT_S_SC_MAX_MVA)

    if "s_sc_min_mva" not in net_sc.ext_grid.columns or net_sc.ext_grid["s_sc_min_mva"].isna().any():
        net_sc.ext_grid["s_sc_min_mva"] = _DEFAULT_S_SC_MIN_MVA

    if "rx_max" not in net_sc.ext_grid.columns or net_sc.ext_grid["rx_max"].isna().any():
        net_sc.ext_grid["rx_max"] = _DEFAULT_RX_MAX

    if "rx_min" not in net_sc.ext_grid.columns or net_sc.ext_grid["rx_min"].isna().any():
        net_sc.ext_grid["rx_min"] = _DEFAULT_RX_MIN

    # ── gen 단락 임피던스 설정 ────────────────────────────────────
    if len(net_sc.gen) > 0:
        # vn_kv: 연결 버스의 공칭 전압에서 자동 설정
        if "vn_kv" not in net_sc.gen.columns or net_sc.gen["vn_kv"].isna().any():
            for idx in net_sc.gen.index:
                bus_id = net_sc.gen.at[idx, "bus"]
                net_sc.gen.at[idx, "vn_kv"] = float(net_sc.bus.at[bus_id, "vn_kv"])

        # sn_mva: max_p_mw 기반 추정 (역률 0.85 가정)
        if "sn_mva" not in net_sc.gen.columns or net_sc.gen["sn_mva"].isna().any():
            for idx in net_sc.gen.index:
                max_p = float(net_sc.gen.at[idx, "max_p_mw"])
                net_sc.gen.at[idx, "sn_mva"] = max_p / _DEFAULT_COS_PHI

        # xdss_pu: 서브트랜지언트 리액턴스 (IEC 60909 발전기 모델 필수)
        if "xdss_pu" not in net_sc.gen.columns or net_sc.gen["xdss_pu"].isna().any():
            net_sc.gen["xdss_pu"] = _DEFAULT_XDSS_PU

        if "rdss_ohm" not in net_sc.gen.columns or net_sc.gen["rdss_ohm"].isna().any():
            net_sc.gen["rdss_ohm"] = 0.0

        if "cos_phi" not in net_sc.gen.columns or net_sc.gen["cos_phi"].isna().any():
            net_sc.gen["cos_phi"] = _DEFAULT_COS_PHI

    return net_sc


def _prepare_sc_net_unbalanced(net_sc: pp.pandapowerNet) -> None:
    """비대칭 고장(slg/llg/ll) 계산을 위한 영상 임피던스 파라미터 추가 설정.

    1선 지락/2선 지락/2선 단락은 영상(zero-sequence) 임피던스 필요.
    ext_grid와 line에 추가 파라미터 설정.

    Args:
        net_sc: _prepare_sc_net()으로 준비된 모델 (in-place 수정).
    """
    # ext_grid 영상 임피던스 설정
    if "x0x_max" not in net_sc.ext_grid.columns or net_sc.ext_grid["x0x_max"].isna().any():
        net_sc.ext_grid["x0x_max"] = _DEFAULT_X0X_MAX

    if "x0x_min" not in net_sc.ext_grid.columns or net_sc.ext_grid["x0x_min"].isna().any():
        net_sc.ext_grid["x0x_min"] = _DEFAULT_X0X_MIN

    if "r0x0_max" not in net_sc.ext_grid.columns or net_sc.ext_grid["r0x0_max"].isna().any():
        net_sc.ext_grid["r0x0_max"] = _DEFAULT_R0X0_MAX

    if "r0x0_min" not in net_sc.ext_grid.columns or net_sc.ext_grid["r0x0_min"].isna().any():
        net_sc.ext_grid["r0x0_min"] = _DEFAULT_R0X0_MIN

    # 선로 영상 임피던스 설정 (없으면 정상 임피던스의 3배 기본값 사용)
    if len(net_sc.line) > 0:
        if "r0_ohm_per_km" not in net_sc.line.columns or net_sc.line["r0_ohm_per_km"].isna().any():
            net_sc.line["r0_ohm_per_km"] = net_sc.line["r_ohm_per_km"] * 3.0

        if "x0_ohm_per_km" not in net_sc.line.columns or net_sc.line["x0_ohm_per_km"].isna().any():
            net_sc.line["x0_ohm_per_km"] = net_sc.line["x_ohm_per_km"] * 3.0

        if "c0_nf_per_km" not in net_sc.line.columns or net_sc.line["c0_nf_per_km"].isna().any():
            net_sc.line["c0_nf_per_km"] = net_sc.line.get("c_nf_per_km", 0.0) * 0.3

    # 변압기 영상 임피던스 설정
    if len(net_sc.trafo) > 0:
        if "vk0_percent" not in net_sc.trafo.columns or net_sc.trafo["vk0_percent"].isna().any():
            net_sc.trafo["vk0_percent"] = net_sc.trafo["vk_percent"]

        if "vkr0_percent" not in net_sc.trafo.columns or net_sc.trafo["vkr0_percent"].isna().any():
            net_sc.trafo["vkr0_percent"] = net_sc.trafo["vkr_percent"]

        if "vector_group" not in net_sc.trafo.columns or net_sc.trafo["vector_group"].isna().any():
            net_sc.trafo["vector_group"] = "Dyn"  # 델타-스타 접지 (한국 표준)

        # mag0_percent: 영상 자화 임피던스 비율 (변압기 vk0 대비, pandapower 3.x 필수)
        # 100%이면 자화 임피던스가 영상 단락 임피던스와 동일
        if "mag0_percent" not in net_sc.trafo.columns or net_sc.trafo["mag0_percent"].isna().any():
            net_sc.trafo["mag0_percent"] = 100.0

        if "mag0_rx" not in net_sc.trafo.columns or net_sc.trafo["mag0_rx"].isna().any():
            net_sc.trafo["mag0_rx"] = 0.0

        # si0_hv_partial: HV측 영상 임피던스 분배 비율 (0~1)
        # Dyn 결선에서 표준값 0.9 (HV측 90%, LV측 10%)
        if "si0_hv_partial" not in net_sc.trafo.columns or net_sc.trafo["si0_hv_partial"].isna().any():
            net_sc.trafo["si0_hv_partial"] = 0.9

    # gen 영상 임피던스 설정
    if len(net_sc.gen) > 0:
        if "x2_pu" not in net_sc.gen.columns or net_sc.gen["x2_pu"].isna().any():
            # 역상 리액턴스 ≈ 서브트랜지언트 리액턴스 × 0.8 (근사)
            net_sc.gen["x2_pu"] = net_sc.gen["xdss_pu"] * 0.8

        if "x0_pu" not in net_sc.gen.columns or net_sc.gen["x0_pu"].isna().any():
            # 영상 리액턴스 ≈ 서브트랜지언트 리액턴스 × 0.5 (근사)
            net_sc.gen["x0_pu"] = net_sc.gen["xdss_pu"] * 0.5


class ShortCircuitCalculator:
    """단락전류 해석 계산기.

    pandapower shortcircuit 모듈(calc_sc)을 사용하여
    IEC 60909 기반 단락전류를 계산한다.

    설계 원칙:
      - 모든 수치는 pandapower 솔버 반환값만 사용
      - LLM 수치 생성 절대 금지
      - READ-ONLY — 원본 net을 수정하지 않음 (deepcopy 사용)
      - 계통 모델에 단락전류 파라미터가 없으면 IEC 60909 표준 기본값 자동 설정
    """

    def __init__(self, net: pp.pandapowerNet) -> None:
        """초기화.

        Args:
            net: pandapower 계통 모델. 원본은 수정하지 않음.
        """
        self._net = net

    @property
    def net(self) -> pp.pandapowerNet:
        """pandapower 계통 모델 반환 (읽기 전용)."""
        return self._net

    def _get_bus_nominal_kv(self, bus_id: int) -> float:
        """모선 공칭 전압(kV) 반환.

        Args:
            bus_id: pandapower 모선 인덱스.

        Returns:
            공칭 전압 (kV). 모선이 없으면 1.0 반환.
        """
        try:
            return float(self._net.bus.at[bus_id, "vn_kv"])
        except (KeyError, ValueError):
            return 1.0

    def _calc_skss_mva(self, ikss_ka: float, vn_kv: float) -> float:
        """단락용량 계산.

        Skss = √3 × Ikss × Vn

        Args:
            ikss_ka: 초기 대칭 단락전류 (kA).
            vn_kv: 공칭 전압 (kV).

        Returns:
            초기 대칭 단락용량 (MVA).
        """
        return math.sqrt(3.0) * ikss_ka * vn_kv

    def calculate(
        self,
        bus_id: int,
        fault_type: Literal["3ph", "slg", "llg", "ll"] = "3ph",
    ) -> ShortCircuitResult:
        """단일 모선 단락전류 계산.

        pandapower calc_sc()를 실행하여 IEC 60909 기반 단락전류를 계산한다.
        계통 모델에 단락전류 파라미터(s_sc_max_mva, xdss_pu 등)가 없으면
        IEC 60909 표준 기본값을 자동으로 설정한다.

        Args:
            bus_id: 단락 고장 발생 모선 ID (pandapower bus index).
            fault_type: 고장 유형.
                3ph: 3상 단락 (가장 심각),
                slg: 1선 지락 (가장 빈번),
                llg: 2선 지락,
                ll: 2선 단락.

        Returns:
            ShortCircuitResult 스키마.

        Raises:
            ValueError: bus_id가 유효하지 않은 경우.
            RuntimeError: 단락전류 계산 실패 시.
        """
        now = datetime.now(timezone.utc)

        # 모선 유효성 검증
        if bus_id not in self._net.bus.index:
            raise ValueError(
                f"Bus ID {bus_id}가 계통 모델에 존재하지 않습니다. "
                f"유효 범위: {list(self._net.bus.index)}"
            )
        if not self._net.bus.at[bus_id, "in_service"]:
            raise ValueError(f"Bus {bus_id}는 현재 서비스 중지 상태입니다.")

        vn_kv = self._get_bus_nominal_kv(bus_id)

        # 단락전류 계산용 네트워크 준비 (deepcopy + 파라미터 설정)
        net_sc = _prepare_sc_net(self._net)

        # 비대칭 고장 시 영상 임피던스 추가 설정
        if fault_type in _UNBALANCED_FAULTS:
            _prepare_sc_net_unbalanced(net_sc)

        # 기저 조류계산 (단락전류 계산 전 수렴 확인)
        try:
            pp.runpp(net_sc, verbose=False)
        except pp.powerflow.LoadflowNotConverged as exc:
            raise RuntimeError(
                f"단락전류 계산 전 기저 조류계산 실패: {exc}"
            ) from exc

        # pandapower fault 인수 변환
        pp_fault_type = _PP_FAULT_TYPE_MAP.get(fault_type, "3ph")

        try:
            sc.calc_sc(
                net_sc,
                bus=bus_id,         # 특정 모선만 계산 (효율)
                fault=pp_fault_type,
                case="max",          # 최대 단락전류 (IEC 60909 c = 1.1)
            )
        except Exception as exc:
            logger.error(
                "bus_id=%d fault_type=%s 단락전류 계산 실패: %s",
                bus_id,
                fault_type,
                exc,
            )
            raise RuntimeError(
                f"Bus {bus_id} {fault_type} 단락전류 계산 실패: {exc}"
            ) from exc

        # pandapower 결과 추출 (res_bus_sc: ikss_ka 컬럼)
        try:
            ikss_ka = float(net_sc.res_bus_sc.at[bus_id, "ikss_ka"])
        except (AttributeError, KeyError) as exc:
            raise RuntimeError(
                f"Bus {bus_id} 단락전류 결과 추출 실패: {exc}. "
                "pandapower res_bus_sc에 ikss_ka가 없습니다."
            ) from exc

        skss_mva = self._calc_skss_mva(ikss_ka, vn_kv)

        logger.info(
            "단락전류 계산 완료 — bus_id=%d fault_type=%s ikss_ka=%.4f skss_mva=%.2f",
            bus_id,
            fault_type,
            ikss_ka,
            skss_mva,
        )

        return ShortCircuitResult(
            bus_id=bus_id,
            fault_type=fault_type,  # type: ignore[arg-type]
            ikss_ka=ikss_ka,
            skss_mva=skss_mva,
            snapshot_ts=now,
        )

    def calculate_all_buses(
        self,
        fault_type: Literal["3ph", "slg", "llg", "ll"] = "3ph",
    ) -> list[ShortCircuitResult]:
        """전체 모선 단락전류 일괄 계산.

        pandapower calc_sc()는 bus=None이면 전체 버스를 한 번에 계산한다.

        Args:
            fault_type: 고장 유형 (3ph/slg/llg/ll).

        Returns:
            모든 유효 모선의 ShortCircuitResult 목록.

        Raises:
            RuntimeError: 계산 실패 시.
        """
        now = datetime.now(timezone.utc)

        net_sc = _prepare_sc_net(self._net)

        if fault_type in _UNBALANCED_FAULTS:
            _prepare_sc_net_unbalanced(net_sc)

        # 기저 조류계산
        try:
            pp.runpp(net_sc, verbose=False)
        except pp.powerflow.LoadflowNotConverged as exc:
            raise RuntimeError(f"기저 조류계산 실패: {exc}") from exc

        pp_fault_type = _PP_FAULT_TYPE_MAP.get(fault_type, "3ph")

        try:
            sc.calc_sc(
                net_sc,
                bus=None,           # 전체 모선 계산
                fault=pp_fault_type,
                case="max",
            )
        except Exception as exc:
            raise RuntimeError(f"전체 모선 단락전류 계산 실패: {exc}") from exc

        results: list[ShortCircuitResult] = []
        in_service_buses = net_sc.bus[net_sc.bus["in_service"]].index

        for bus_id in in_service_buses:
            try:
                ikss_ka = float(net_sc.res_bus_sc.at[bus_id, "ikss_ka"])
                vn_kv = self._get_bus_nominal_kv(int(bus_id))
                skss_mva = self._calc_skss_mva(ikss_ka, vn_kv)
                results.append(
                    ShortCircuitResult(
                        bus_id=int(bus_id),
                        fault_type=fault_type,  # type: ignore[arg-type]
                        ikss_ka=ikss_ka,
                        skss_mva=skss_mva,
                        snapshot_ts=now,
                    )
                )
            except (KeyError, ValueError) as exc:
                logger.warning("Bus %d 결과 추출 건너뜀: %s", bus_id, exc)

        logger.info(
            "전체 모선 단락전류 계산 완료 — fault_type=%s, 총 %d 모선",
            fault_type,
            len(results),
        )
        return results
