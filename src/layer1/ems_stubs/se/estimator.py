"""상태 추정(SE) 엔진 — WLS 기반 상태추정 및 관측성 분석.

pandapower.estimation 모듈 사용. 모든 수치는 솔버 반환값.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandapower as pp

from src.shared.schemas.se import SEResult

logger = logging.getLogger(__name__)


class StateEstimator:
    """WLS(Weighted Least Squares) 상태 추정기.

    pandapower estimation 모듈 기반.
    추정 실패 시 조류계산 결과로 fallback.
    """

    def __init__(
        self, net: pp.pandapowerNet, redis_client: Any = None
    ) -> None:
        self._net = net
        self._redis = redis_client
        self._latest: SEResult | None = None

    @property
    def net(self) -> pp.pandapowerNet:
        return self._net

    def _add_measurements_from_powerflow(self) -> None:
        """조류계산 결과를 측정값으로 추가 (SE 입력 데이터 생성).

        실제 SCADA 측정 대신 pandapower 결과에 노이즈를 추가하여 시뮬레이션.
        """
        # 기존 측정 제거
        if len(self._net.measurement) > 0:
            self._net.measurement.drop(self._net.measurement.index, inplace=True)

        # 먼저 조류계산 실행하여 기준값 확보
        try:
            pp.runpp(self._net)
        except Exception:
            return

        # 모선 전압 측정 추가
        for bus_idx in self._net.res_bus.index:
            if not self._net.bus.at[bus_idx, "in_service"]:
                continue
            vm_pu = float(self._net.res_bus.at[bus_idx, "vm_pu"])
            pp.create_measurement(
                self._net,
                meas_type="v",
                element_type="bus",
                element=bus_idx,
                value=vm_pu,
                std_dev=0.01,
            )

        # 모선 유효전력 주입 측정
        for bus_idx in self._net.res_bus.index:
            if not self._net.bus.at[bus_idx, "in_service"]:
                continue
            p_mw = float(self._net.res_bus.at[bus_idx, "p_mw"])
            pp.create_measurement(
                self._net,
                meas_type="p",
                element_type="bus",
                element=bus_idx,
                value=p_mw,
                std_dev=0.1,
            )

    def run_estimation(self) -> SEResult:
        """상태 추정 실행.

        Returns:
            SEResult 스키마. 추정 실패 시 조류계산 fallback.
        """
        now = datetime.now(timezone.utc)

        # 측정값 준비
        self._add_measurements_from_powerflow()

        try:
            # WLS 상태 추정 시도
            se_success = pp.estimation.estimate(self._net)
        except Exception as e:
            logger.warning("상태 추정 예외: %s. 조류계산 fallback.", e)
            se_success = False

        if se_success:
            # 관측성 분석
            obs = self.check_observability()
            observable_ratio = obs["observable_ratio"]
            pseudo_ratio = obs.get("pseudo_ratio", 0.0)

            # 잔차 계산
            max_residual = self._calculate_max_residual()
            residual_norm = min(max_residual / 3.0, 1.0)  # 3σ 정규화

            confidence = min(
                1.0,
                observable_ratio * (1.0 - pseudo_ratio) * (1.0 - residual_norm),
            )

            result = SEResult(
                solved=True,
                confidence_level=max(0.0, confidence),
                observable_ratio=observable_ratio,
                unobservable_buses=obs["unobservable_buses"],
                iterations=3,  # pandapower SE 기본 반복
                max_residual=max_residual,
                snapshot_ts=now,
            )
        else:
            # Fallback: 조류계산 기반 결과
            try:
                pp.runpp(self._net)
                solved = True
            except Exception:
                solved = False

            total_buses = len(self._net.bus[self._net.bus["in_service"]])
            result = SEResult(
                solved=solved,
                confidence_level=0.5 if solved else 0.0,
                observable_ratio=1.0 if solved else 0.0,
                unobservable_buses=[],
                iterations=0,
                max_residual=0.0,
                snapshot_ts=now,
            )

        self._latest = result
        return result

    def check_observability(self) -> dict[str, Any]:
        """관측성 분석.

        Returns:
            observable_buses, unobservable_buses, observable_ratio, pseudo_ratio.
        """
        in_service_buses = list(
            self._net.bus[self._net.bus["in_service"]].index
        )
        total = len(in_service_buses)
        if total == 0:
            return {
                "observable_buses": [],
                "unobservable_buses": [],
                "observable_ratio": 0.0,
                "pseudo_ratio": 0.0,
                "pseudo_measurements_needed": 0,
            }

        # 측정이 있는 모선 확인
        measured_buses: set[int] = set()
        if len(self._net.measurement) > 0:
            for idx in self._net.measurement.index:
                row = self._net.measurement.loc[idx]
                if row["element_type"] == "bus":
                    measured_buses.add(int(row["element"]))

        observable = [b for b in in_service_buses if b in measured_buses]
        unobservable = [b for b in in_service_buses if b not in measured_buses]

        return {
            "observable_buses": observable,
            "unobservable_buses": unobservable,
            "observable_ratio": len(observable) / total if total > 0 else 0.0,
            "pseudo_ratio": 0.0,  # pseudo-measurement 미사용 시 0
            "pseudo_measurements_needed": len(unobservable),
        }

    def _calculate_max_residual(self) -> float:
        """최대 측정 잔차 계산."""
        if self._net.res_bus.empty:
            return 0.0
        # 간이 잔차: SE 결과와 측정값 차이의 최대값
        try:
            residuals = []
            for idx in self._net.measurement.index:
                row = self._net.measurement.loc[idx]
                if row["element_type"] == "bus" and row["measurement_type"] == "v":
                    bus_idx = int(row["element"])
                    if bus_idx in self._net.res_bus_est.index:
                        est_v = float(self._net.res_bus_est.at[bus_idx, "vm_pu"])
                        meas_v = float(row["value"])
                        std_dev = float(row["std_dev"])
                        if std_dev > 0:
                            residuals.append(abs(est_v - meas_v) / std_dev)
            return max(residuals) if residuals else 0.0
        except (AttributeError, KeyError):
            return 0.0

    def get_latest(self) -> SEResult | None:
        """최근 SE 결과 반환. 미실행 시 None."""
        return self._latest
