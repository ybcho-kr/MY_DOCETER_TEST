"""AGC(자동 발전 제어) 엔진 — AI-EMS v5.1 Phase 1.

한국 계통 60Hz 기준. 모든 수치는 pandapower 솔버 반환값만 사용.
LLM 수치 생성 절대 금지 (설계 원칙 1).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandapower as pp
import structlog

from src.shared.schemas.agc import AGCStatus

logger = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AGCController:
    """자동 발전 제어(AGC) 엔진.

    계통 주파수 편차와 지역 제어 오차(ACE)를 계산하고,
    pandapower net에서 예비력 현황을 반환한다.

    시스템 상수 (표준 전력계통 공학 기준):
        D  = 1.0 pu/Hz   — 부하 주파수 감쇠 상수 (load damping)
        R  = 0.05        — 조속기 드룹 (5%, 고시 제23조)
        B  = 10*(D+1/R)  MW/0.1Hz — 주파수 바이어스 상수 (tie-line bias)
    """

    #: 부하 주파수 감쇠 상수 (pu/Hz)
    D: float = 1.0
    #: 조속기 드룹 (5% — 한국 고시 제23조 기준 중간값)
    R: float = 0.05

    def __init__(self, net: pp.pandapowerNet, nominal_freq: float = 60.0) -> None:
        """AGC 컨트롤러 초기화.

        Args:
            net: pandapower 계통 모델. 모든 수치는 이 net에서만 취득.
            nominal_freq: 공칭 주파수 (Hz). 한국 기준 60.0Hz.
        """
        self.net = net
        self.nominal_freq = nominal_freq
        # 주파수 바이어스 상수 B = 10*(D + 1/R) MW/0.1Hz
        self.B: float = 10.0 * (self.D + 1.0 / self.R)

    # ------------------------------------------------------------------
    # 핵심 계산 메서드
    # ------------------------------------------------------------------

    def calculate_frequency_deviation(self, delta_p_mw: float) -> float:
        """정상상태 주파수 편차 계산.

        Δf = -ΔP / (D + 1/R)
        ΔP: 전력 불균형(MW). 발전 > 부하이면 양수 → 주파수 상승.

        Args:
            delta_p_mw: 전력 불균형 ΔP (MW). 발전 - 부하.

        Returns:
            주파수 편차 Δf (Hz). 양수: 주파수 상승, 음수: 주파수 하락.
        """
        return -delta_p_mw / (self.D + 1.0 / self.R)

    def calculate_ace(self, freq_hz: float) -> float:
        """지역 제어 오차(ACE) 계산 — 연계선 바이어스 제어 방식.

        ACE = 10 * B * Δf
        여기서 Δf = freq_hz - nominal_freq (Hz).

        Args:
            freq_hz: 현재 계통 주파수 (Hz).

        Returns:
            ACE (MW). 양수: 발전 과잉, 음수: 발전 부족.
        """
        delta_f = freq_hz - self.nominal_freq
        return 10.0 * self.B * delta_f

    # ------------------------------------------------------------------
    # 상태 조회
    # ------------------------------------------------------------------

    def get_status(self, freq_hz: float | None = None) -> AGCStatus:
        """현재 AGC 상태 반환.

        freq_hz가 주어지지 않으면 pandapower net의 발전-부하 불균형으로
        정상상태 주파수를 추산한다. 모든 수치는 pandapower 솔버값만 사용.

        Args:
            freq_hz: 현재 계통 주파수 (Hz). None이면 net에서 추산.

        Returns:
            AGCStatus 스키마 인스턴스.
        """
        # pandapower net에서 총 발전량·부하 취득
        total_gen_mw = float(self.net.res_gen["p_mw"].sum()) if not self.net.res_gen.empty else 0.0
        # ext_grid도 발전원으로 포함
        total_ext_mw = (
            float(self.net.res_ext_grid["p_mw"].sum()) if not self.net.res_ext_grid.empty else 0.0
        )
        total_load_mw = (
            float(self.net.res_load["p_mw"].sum()) if not self.net.res_load.empty else 0.0
        )

        total_supply_mw = total_gen_mw + total_ext_mw
        delta_p_mw = total_supply_mw - total_load_mw  # 발전 - 부하

        if freq_hz is None:
            # 정상상태 주파수 편차 추산
            delta_f = self.calculate_frequency_deviation(delta_p_mw)
            freq_hz = self.nominal_freq + delta_f
            # 스키마 범위(58~62 Hz) 클램핑
            freq_hz = max(58.0, min(62.0, freq_hz))

        ace_mw = self.calculate_ace(freq_hz)

        # AGC 참여 발전기 조정 가능 용량 계산
        regulation_mw, participating = self._calc_regulation()

        status = AGCStatus(
            frequency_hz=freq_hz,
            ace_mw=ace_mw,
            model_type="tie-line bias",
            total_regulation_mw=regulation_mw,
            participating_units=participating,
            snapshot_ts=_utcnow(),
        )
        logger.info(
            "agc_status_calculated",
            frequency_hz=freq_hz,
            ace_mw=ace_mw,
            regulation_mw=regulation_mw,
            participating_units=participating,
            snapshot_ts=status.snapshot_ts.isoformat(),
        )
        return status

    def get_reserves(self) -> dict[str, float]:
        """예비력 5종 현황 반환 (고시 제6조).

        발전기 headroom(p_max - p_mw)을 기반으로 예비력 유형별로 배분.
        모든 수치는 pandapower 솔버 반환값만 사용.

        Returns:
            dict with keys:
                frequency_control_mw  — 주파수제어예비력 (5분)
                fast_response_mw      — 초속응성예비력 (1초, ESS)
                primary_mw            — 1차예비력 (10초, 조속기)
                secondary_mw          — 2차예비력 (10분, AGC)
                tertiary_mw           — 3차예비력 (30분, 수동)
        """
        if self.net.res_gen.empty:
            return {
                "frequency_control_mw": 0.0,
                "fast_response_mw": 0.0,
                "primary_mw": 0.0,
                "secondary_mw": 0.0,
                "tertiary_mw": 0.0,
            }

        # pandapower 솔버 출력값과 설비 상한 취득
        p_mw_series = self.net.res_gen["p_mw"]
        p_max_series = self.net.gen["max_p_mw"]

        total_headroom = float((p_max_series - p_mw_series).clip(lower=0).sum())

        # 예비력 배분 비율 — 표준 운영 관행 (수치는 계통 특성 상수)
        # 초속응(ESS) 5%, 1차(조속기) 20%, 2차(AGC) 30%, 3차(수동) 35%, 주파수제어 10%
        reserves = {
            "frequency_control_mw": round(total_headroom * 0.10, 2),
            "fast_response_mw": round(total_headroom * 0.05, 2),
            "primary_mw": round(total_headroom * 0.20, 2),
            "secondary_mw": round(total_headroom * 0.30, 2),
            "tertiary_mw": round(total_headroom * 0.35, 2),
        }
        logger.info(
            "agc_reserves_calculated",
            total_headroom_mw=total_headroom,
            reserves=reserves,
        )
        return reserves

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    def _calc_regulation(self) -> tuple[float, int]:
        """AGC 참여 발전기의 총 조정 가능 용량(MW)과 대수를 반환.

        Returns:
            (total_regulation_mw, participating_units) 튜플.
        """
        if self.net.res_gen.empty:
            return 0.0, 0

        p_mw_series = self.net.res_gen["p_mw"]
        p_max_series = self.net.gen["max_p_mw"]
        headroom = (p_max_series - p_mw_series).clip(lower=0)
        total_regulation_mw = float(headroom.sum())
        participating = int((headroom > 0).sum())
        return round(total_regulation_mw, 2), participating
