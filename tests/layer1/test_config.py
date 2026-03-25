"""shared/config 모듈 테스트 — AI-EMS v5.1 Phase 1.

Redis 키 패턴, API 경로, 상수값 검증.
"""
from __future__ import annotations

import pytest


class TestNamespacePrefixes:
    """네임스페이스 접두사 상수 검증."""

    def test_ops_prefix(self) -> None:
        """OPS_PREFIX가 'ops:'여야 한다 (설계 원칙 2)."""
        from src.shared.config import OPS_PREFIX
        assert OPS_PREFIX == "ops:", f"OPS_PREFIX={OPS_PREFIX} ≠ 'ops:'"

    def test_study_prefix(self) -> None:
        """STUDY_PREFIX가 'study:'여야 한다."""
        from src.shared.config import STUDY_PREFIX
        assert STUDY_PREFIX == "study:"

    def test_scada_prefix(self) -> None:
        """SCADA_PREFIX가 'scada:'여야 한다."""
        from src.shared.config import SCADA_PREFIX
        assert SCADA_PREFIX == "scada:"

    def test_alarm_prefix(self) -> None:
        """ALARM_PREFIX가 'alarm:'여야 한다."""
        from src.shared.config import ALARM_PREFIX
        assert ALARM_PREFIX == "alarm:"


class TestRedisKeyPatterns:
    """Redis 키 패턴 문자열 형식 검증."""

    def test_bus_voltage_key_format(self) -> None:
        """OPS_BUS_VOLTAGE 패턴이 올바르게 포매팅되어야 한다."""
        from src.shared.config import OPS_BUS_VOLTAGE
        key = OPS_BUS_VOLTAGE.format(bus_id=42)
        assert key == "ops:bus:42:voltage"
        assert key.startswith("ops:")

    def test_line_loading_key_format(self) -> None:
        """OPS_LINE_LOADING 패턴이 올바르게 포매팅되어야 한다."""
        from src.shared.config import OPS_LINE_LOADING
        key = OPS_LINE_LOADING.format(line_id=7)
        assert key == "ops:line:7:loading"

    def test_gen_output_key_format(self) -> None:
        """OPS_GEN_OUTPUT 패턴이 올바르게 포매팅되어야 한다."""
        from src.shared.config import OPS_GEN_OUTPUT
        key = OPS_GEN_OUTPUT.format(gen_id=3)
        assert key == "ops:gen:3:output"

    def test_study_result_key_format(self) -> None:
        """STUDY_RESULT 패턴이 올바르게 포매팅되어야 한다."""
        from src.shared.config import STUDY_RESULT
        key = STUDY_RESULT.format(sid="abc123")
        assert key == "study:abc123:result"
        assert key.startswith("study:")  # ops: 아님 확인

    def test_study_sc_key_format(self) -> None:
        """STUDY_SC_RESULT 패턴이 올바르게 포매팅되어야 한다."""
        from src.shared.config import STUDY_SC_RESULT
        key = STUDY_SC_RESULT.format(sid="test-001")
        assert key == "study:test-001:shortcircuit"

    def test_ops_keys_never_study_prefix(self) -> None:
        """ops: 키가 study: 접두사를 가지지 않아야 한다 (네임스페이스 격리)."""
        from src.shared.config import (
            OPS_BUS_VOLTAGE,
            OPS_LINE_LOADING,
            OPS_GEN_OUTPUT,
            OPS_FREQ_HZ,
            OPS_POWERFLOW_LATEST,
        )
        ops_keys = [
            OPS_BUS_VOLTAGE.format(bus_id=1),
            OPS_LINE_LOADING.format(line_id=1),
            OPS_GEN_OUTPUT.format(gen_id=1),
            OPS_FREQ_HZ,
            OPS_POWERFLOW_LATEST,
        ]
        for key in ops_keys:
            assert not key.startswith("study:"), (
                f"ops: 키가 study: 접두사를 가짐: {key}"
            )


class TestDomainConstants:
    """전력 도메인 상수값 검증 (산업통상자원부고시 제2023-65호)."""

    def test_nominal_frequency(self) -> None:
        """한국 공칭 주파수는 60Hz여야 한다."""
        from src.shared.config import NOMINAL_FREQ_HZ
        assert NOMINAL_FREQ_HZ == 60.0

    def test_freq_normal_deviation(self) -> None:
        """정상 주파수 편차 허용범위는 ±0.2Hz여야 한다 (고시 제4조)."""
        from src.shared.config import FREQ_NORMAL_DEVIATION_HZ
        assert FREQ_NORMAL_DEVIATION_HZ == 0.2

    def test_freq_min_single_fault(self) -> None:
        """단일 고장 최소 허용 주파수는 59.7Hz여야 한다 (고시 제4조)."""
        from src.shared.config import FREQ_MIN_SINGLE_FAULT_HZ
        assert FREQ_MIN_SINGLE_FAULT_HZ == 59.7

    def test_freq_min_cascade(self) -> None:
        """연쇄 고장 최소 허용 주파수는 59.5Hz여야 한다 (고시 제4조)."""
        from src.shared.config import FREQ_MIN_CASCADE_HZ
        assert FREQ_MIN_CASCADE_HZ == 59.5

    def test_voltage_op_limits(self) -> None:
        """전압 운용범위가 0.9~1.1 pu여야 한다 (고시 제3조 ±10%)."""
        from src.shared.config import VOLTAGE_OP_MIN_PU, VOLTAGE_OP_MAX_PU
        assert VOLTAGE_OP_MIN_PU == 0.9
        assert VOLTAGE_OP_MAX_PU == 1.1

    def test_line_overload_thresholds(self) -> None:
        """선로 과부하 임계값이 100%(위험)/80%(경고)여야 한다."""
        from src.shared.config import (
            LINE_OVERLOAD_CRITICAL_PCT,
            LINE_OVERLOAD_WARNING_PCT,
        )
        assert LINE_OVERLOAD_CRITICAL_PCT == 100.0
        assert LINE_OVERLOAD_WARNING_PCT == 80.0
        assert LINE_OVERLOAD_WARNING_PCT < LINE_OVERLOAD_CRITICAL_PCT

    def test_scada_scan_interval(self) -> None:
        """SCADA 주기가 4초여야 한다."""
        from src.shared.config import SCADA_SCAN_INTERVAL_SEC
        assert SCADA_SCAN_INTERVAL_SEC == 4

    def test_study_ttl_1800s(self) -> None:
        """스터디 TTL이 1800초(30분)여야 한다 (설계 원칙)."""
        from src.shared.config import STUDY_TTL_SECONDS
        assert STUDY_TTL_SECONDS == 1800

    def test_alarm_deadband_values(self) -> None:
        """알람 dead-band 값이 양수여야 한다."""
        from src.shared.config import (
            ALARM_DEADBAND_VOLTAGE_PU,
            ALARM_DEADBAND_LOADING_PCT,
            ALARM_DEADBAND_FREQ_HZ,
        )
        assert ALARM_DEADBAND_VOLTAGE_PU > 0
        assert ALARM_DEADBAND_LOADING_PCT > 0
        assert ALARM_DEADBAND_FREQ_HZ > 0


class TestApiPaths:
    """API 경로 상수 검증."""

    def test_tp_paths_start_with_slash(self) -> None:
        """TP API 경로가 '/'로 시작해야 한다."""
        from src.shared.config import (
            TP_POWERFLOW_PATH,
            TP_CONTINGENCY_PATH,
            TP_VSA_PATH,
            TP_VIOLATIONS_PATH,
        )
        for path in (TP_POWERFLOW_PATH, TP_CONTINGENCY_PATH, TP_VSA_PATH, TP_VIOLATIONS_PATH):
            assert path.startswith("/"), f"경로가 '/'로 시작하지 않음: {path}"

    def test_se_paths_start_with_slash(self) -> None:
        """SE API 경로가 '/'로 시작해야 한다."""
        from src.shared.config import SE_RUN_PATH, SE_LATEST_PATH
        assert SE_RUN_PATH.startswith("/")
        assert SE_LATEST_PATH.startswith("/")

    def test_sca_paths_defined(self) -> None:
        """SCA API 경로가 정의되어 있어야 한다."""
        from src.shared.config import SCA_RUN_PATH, SCA_BUS_PATH
        assert "/sca" in SCA_RUN_PATH
        assert "{bus_id}" in SCA_BUS_PATH


class TestSCAConstants:
    """SCA 관련 상수 검증."""

    def test_sca_default_fault_type(self) -> None:
        """SCA 기본 고장 유형이 '3ph'여야 한다."""
        from src.shared.config import SCA_DEFAULT_FAULT_TYPE
        assert SCA_DEFAULT_FAULT_TYPE == "3ph"

    def test_iec60909_voltage_factors(self) -> None:
        """IEC 60909 전압 계수 c_max=1.1, c_min=1.0이어야 한다."""
        from src.shared.config import SCA_VOLTAGE_FACTOR_C_MAX, SCA_VOLTAGE_FACTOR_C_MIN
        assert SCA_VOLTAGE_FACTOR_C_MAX == 1.1
        assert SCA_VOLTAGE_FACTOR_C_MIN == 1.0
        assert SCA_VOLTAGE_FACTOR_C_MAX > SCA_VOLTAGE_FACTOR_C_MIN
