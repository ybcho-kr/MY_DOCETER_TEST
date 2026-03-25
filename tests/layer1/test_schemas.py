"""
공유 Pydantic v2 스키마 단위 테스트 — AI-EMS v5.1 Phase 1

커버 항목:
- 모든 스키마 정상 생성 검증
- 범위 초과 / 잘못된 타입 검증 실패 테스트
- AlarmType / AlarmSeverity Enum 값 검증
- AIResponse evidence_chain min_length=1 검증
- StudyResult namespace 'study' 고정 검증
- model_dump / model_validate 직렬화·역직렬화 라운드트립 검증
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.shared.schemas.agc import AGCStatus
from src.shared.schemas.agent import (
    AgentContext,
    AIResponse,
    EvidenceStep,
    StructuredFact,
)
from src.shared.schemas.alarm import (
    Alarm,
    AlarmSeverity,
    AlarmSummary,
    AlarmType,
)
from src.shared.schemas.common import ErrorResponse, Timestamp
from src.shared.schemas.grid import (
    BusVoltage,
    GenDispatch,
    LineLoading,
    TopologyVersion,
)
from src.shared.schemas.se import SEResult
from src.shared.schemas.study import ShortCircuitResult, StudyResult
from src.shared.schemas.tp import (
    ContingencyCase,
    ContingencyResult,
    PowerFlowResult,
    VSAResult,
)

_NOW = datetime.now(timezone.utc)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _evidence_step() -> EvidenceStep:
    return EvidenceStep(
        tool_name="read_bus_voltage",
        input_params={"bus_id": 1},
        output_summary="bus 1 voltage_pu=1.02",
        duration_ms=12.5,
    )


# ===========================================================================
# common.py
# ===========================================================================


class TestTimestamp:
    def test_valid(self) -> None:
        ts = Timestamp(source="pandapower")
        assert ts.source == "pandapower"
        assert isinstance(ts.snapshot_ts, datetime)

    def test_explicit_snapshot_ts(self) -> None:
        ts = Timestamp(snapshot_ts=_NOW, source="redis:ops")
        assert ts.snapshot_ts == _NOW

    def test_missing_source_raises(self) -> None:
        with pytest.raises(ValidationError):
            Timestamp()  # type: ignore[call-arg]


class TestErrorResponse:
    def test_valid_minimal(self) -> None:
        err = ErrorResponse(code=404, message="Not found")
        assert err.code == 404
        assert err.detail is None

    def test_valid_with_detail(self) -> None:
        err = ErrorResponse(code=500, message="Internal error", detail="stack trace")
        assert err.detail == "stack trace"

    def test_snapshot_ts_auto(self) -> None:
        err = ErrorResponse(code=200, message="ok")
        assert isinstance(err.snapshot_ts, datetime)

    def test_roundtrip(self) -> None:
        err = ErrorResponse(code=400, message="Bad request", detail="validation error")
        data = err.model_dump()
        restored = ErrorResponse.model_validate(data)
        assert restored.code == err.code
        assert restored.detail == err.detail


# ===========================================================================
# grid.py
# ===========================================================================


class TestBusVoltage:
    def test_valid(self) -> None:
        bv = BusVoltage(
            bus_id=1,
            name="신서울345",
            voltage_pu=1.02,
            voltage_kv=351.9,
            nominal_kv=345.0,
            snapshot_ts=_NOW,
        )
        assert bv.bus_id == 1
        assert bv.in_service is True

    def test_valid_all_nominal_kv(self) -> None:
        for kv in (765.0, 345.0, 154.0, 66.0, 22.9):
            bv = BusVoltage(
                bus_id=1,
                name=f"bus_{kv}",
                voltage_pu=1.0,
                voltage_kv=kv,
                nominal_kv=kv,
                snapshot_ts=_NOW,
            )
            assert bv.nominal_kv == kv

    def test_invalid_nominal_kv(self) -> None:
        with pytest.raises(ValidationError, match="nominal_kv"):
            BusVoltage(
                bus_id=1,
                name="bad_bus",
                voltage_pu=1.0,
                voltage_kv=100.0,
                nominal_kv=100.0,  # 허용되지 않는 전압 등급
                snapshot_ts=_NOW,
            )

    def test_bus_id_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            BusVoltage(
                bus_id=0,  # ge=1 위반
                name="bus0",
                voltage_pu=1.0,
                voltage_kv=345.0,
                nominal_kv=345.0,
                snapshot_ts=_NOW,
            )

    def test_voltage_pu_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            BusVoltage(
                bus_id=1,
                name="bus1",
                voltage_pu=2.5,  # le=2.0 위반
                voltage_kv=862.5,
                nominal_kv=345.0,
                snapshot_ts=_NOW,
            )

    def test_voltage_pu_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            BusVoltage(
                bus_id=1,
                name="bus1",
                voltage_pu=0.0,  # gt=0 위반
                voltage_kv=0.0,
                nominal_kv=345.0,
                snapshot_ts=_NOW,
            )

    def test_roundtrip(self) -> None:
        bv = BusVoltage(
            bus_id=5,
            name="서울154",
            voltage_pu=0.98,
            voltage_kv=150.92,
            nominal_kv=154.0,
            zone=3,
            snapshot_ts=_NOW,
        )
        data = bv.model_dump()
        restored = BusVoltage.model_validate(data)
        assert restored.bus_id == bv.bus_id
        assert restored.zone == 3


class TestLineLoading:
    def test_valid(self) -> None:
        ll = LineLoading(
            line_id=0,
            from_bus=1,
            to_bus=2,
            loading_pct=75.5,
            p_from_mw=100.0,
            q_from_mvar=30.0,
            rating_mva=200.0,
            snapshot_ts=_NOW,
        )
        assert ll.loading_pct == 75.5
        assert ll.in_service is True

    def test_loading_pct_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            LineLoading(
                line_id=0,
                from_bus=1,
                to_bus=2,
                loading_pct=-1.0,  # ge=0 위반
                p_from_mw=100.0,
                q_from_mvar=0.0,
                rating_mva=200.0,
                snapshot_ts=_NOW,
            )

    def test_rating_mva_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            LineLoading(
                line_id=0,
                from_bus=1,
                to_bus=2,
                loading_pct=50.0,
                p_from_mw=100.0,
                q_from_mvar=0.0,
                rating_mva=0.0,  # gt=0 위반
                snapshot_ts=_NOW,
            )

    def test_from_bus_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            LineLoading(
                line_id=0,
                from_bus=0,  # ge=1 위반
                to_bus=2,
                loading_pct=50.0,
                p_from_mw=100.0,
                q_from_mvar=0.0,
                rating_mva=200.0,
                snapshot_ts=_NOW,
            )

    def test_roundtrip(self) -> None:
        ll = LineLoading(
            line_id=10,
            from_bus=3,
            to_bus=7,
            loading_pct=110.0,
            p_from_mw=220.0,
            q_from_mvar=-15.0,
            rating_mva=200.0,
            in_service=True,
            snapshot_ts=_NOW,
        )
        data = ll.model_dump()
        restored = LineLoading.model_validate(data)
        assert restored.loading_pct == 110.0


class TestGenDispatch:
    def test_valid(self) -> None:
        gd = GenDispatch(
            gen_id=0,
            bus_id=1,
            name="신서울#1",
            p_mw=500.0,
            q_mvar=100.0,
            p_max_mw=600.0,
            p_min_mw=150.0,
            vm_pu=1.02,
            gen_type="steam",
            snapshot_ts=_NOW,
        )
        assert gd.gen_type == "steam"
        assert gd.in_service is True

    def test_p_max_mw_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            GenDispatch(
                gen_id=0,
                bus_id=1,
                name="gen1",
                p_mw=0.0,
                q_mvar=0.0,
                p_max_mw=0.0,  # gt=0 위반
                p_min_mw=0.0,
                vm_pu=1.0,
                gen_type="solar",
                snapshot_ts=_NOW,
            )

    def test_vm_pu_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            GenDispatch(
                gen_id=0,
                bus_id=1,
                name="gen1",
                p_mw=100.0,
                q_mvar=0.0,
                p_max_mw=200.0,
                p_min_mw=0.0,
                vm_pu=2.0,  # le=1.5 위반
                gen_type="gas",
                snapshot_ts=_NOW,
            )

    def test_roundtrip(self) -> None:
        gd = GenDispatch(
            gen_id=5,
            bus_id=10,
            name="수력#3",
            p_mw=200.0,
            q_mvar=50.0,
            p_max_mw=300.0,
            p_min_mw=50.0,
            vm_pu=1.03,
            gen_type="hydro",
            snapshot_ts=_NOW,
        )
        data = gd.model_dump()
        restored = GenDispatch.model_validate(data)
        assert restored.gen_id == 5
        assert restored.gen_type == "hydro"


class TestTopologyVersion:
    def test_valid(self) -> None:
        tv = TopologyVersion(
            version=1,
            timestamp=_NOW,
            total_buses=100,
            total_lines=150,
            total_gens=30,
        )
        assert tv.islands == 1  # default

    def test_islands_default(self) -> None:
        tv = TopologyVersion(
            version=0,
            timestamp=_NOW,
            total_buses=10,
            total_lines=12,
            total_gens=5,
        )
        assert tv.islands == 1

    def test_islands_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            TopologyVersion(
                version=0,
                timestamp=_NOW,
                total_buses=10,
                total_lines=12,
                total_gens=5,
                islands=0,  # ge=1 위반
            )

    def test_roundtrip(self) -> None:
        tv = TopologyVersion(
            version=42,
            timestamp=_NOW,
            total_buses=500,
            total_lines=700,
            total_gens=80,
            islands=2,
        )
        data = tv.model_dump()
        restored = TopologyVersion.model_validate(data)
        assert restored.version == 42
        assert restored.islands == 2


# ===========================================================================
# se.py
# ===========================================================================


class TestSEResult:
    def test_valid(self) -> None:
        se = SEResult(
            solved=True,
            confidence_level=0.98,
            observable_ratio=1.0,
            unobservable_buses=[],
            iterations=5,
            max_residual=0.12,
            snapshot_ts=_NOW,
        )
        assert se.solved is True
        assert se.unobservable_buses == []

    def test_with_unobservable_buses(self) -> None:
        se = SEResult(
            solved=False,
            confidence_level=0.5,
            observable_ratio=0.85,
            unobservable_buses=[10, 23, 45],
            iterations=20,
            max_residual=4.5,
            snapshot_ts=_NOW,
        )
        assert len(se.unobservable_buses) == 3

    def test_confidence_level_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            SEResult(
                solved=True,
                confidence_level=1.5,  # le=1.0 위반
                observable_ratio=1.0,
                unobservable_buses=[],
                iterations=3,
                max_residual=0.1,
                snapshot_ts=_NOW,
            )

    def test_max_residual_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            SEResult(
                solved=True,
                confidence_level=0.9,
                observable_ratio=1.0,
                unobservable_buses=[],
                iterations=3,
                max_residual=-0.1,  # ge=0 위반
                snapshot_ts=_NOW,
            )

    def test_roundtrip(self) -> None:
        se = SEResult(
            solved=True,
            confidence_level=0.95,
            observable_ratio=0.99,
            unobservable_buses=[7],
            iterations=8,
            max_residual=0.5,
            snapshot_ts=_NOW,
        )
        data = se.model_dump()
        restored = SEResult.model_validate(data)
        assert restored.confidence_level == 0.95
        assert restored.unobservable_buses == [7]


# ===========================================================================
# tp.py
# ===========================================================================


class TestPowerFlowResult:
    def test_valid(self) -> None:
        pf = PowerFlowResult(
            converged=True,
            iterations=4,
            max_vm_pu=1.05,
            min_vm_pu=0.97,
            max_loading_pct=85.0,
            total_p_gen_mw=5000.0,
            total_p_load_mw=4900.0,
            total_loss_mw=100.0,
            snapshot_ts=_NOW,
        )
        assert pf.converged is True
        assert pf.total_loss_mw == 100.0

    def test_max_loading_pct_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            PowerFlowResult(
                converged=True,
                iterations=4,
                max_vm_pu=1.05,
                min_vm_pu=0.97,
                max_loading_pct=-5.0,  # ge=0 위반
                total_p_gen_mw=5000.0,
                total_p_load_mw=4900.0,
                total_loss_mw=100.0,
                snapshot_ts=_NOW,
            )

    def test_total_loss_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            PowerFlowResult(
                converged=True,
                iterations=4,
                max_vm_pu=1.05,
                min_vm_pu=0.97,
                max_loading_pct=85.0,
                total_p_gen_mw=5000.0,
                total_p_load_mw=4900.0,
                total_loss_mw=-10.0,  # ge=0 위반
                snapshot_ts=_NOW,
            )

    def test_roundtrip(self) -> None:
        pf = PowerFlowResult(
            converged=False,
            iterations=50,
            max_vm_pu=1.2,
            min_vm_pu=0.8,
            max_loading_pct=150.0,
            total_p_gen_mw=3000.0,
            total_p_load_mw=3200.0,
            total_loss_mw=0.0,
            snapshot_ts=_NOW,
        )
        data = pf.model_dump()
        restored = PowerFlowResult.model_validate(data)
        assert restored.converged is False


class TestContingencyCase:
    def test_valid_line(self) -> None:
        cc = ContingencyCase(
            case_id="N1_LINE_001",
            element_type="line",
            element_id=0,
            description="신서울-서울 345kV 1L 탈락",
        )
        assert cc.element_type == "line"

    def test_valid_gen(self) -> None:
        cc = ContingencyCase(
            case_id="N1_GEN_045",
            element_type="gen",
            element_id=45,
            description="신서울#1 발전기 탈락",
        )
        assert cc.element_type == "gen"

    def test_invalid_element_type(self) -> None:
        with pytest.raises(ValidationError):
            ContingencyCase(
                case_id="N1_BUS_001",
                element_type="bus",  # Literal["line","trafo","gen"] 위반
                element_id=1,
                description="invalid",
            )

    def test_element_id_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            ContingencyCase(
                case_id="N1_LINE_001",
                element_type="line",
                element_id=-1,  # ge=0 위반
                description="negative id",
            )


class TestContingencyResult:
    def _make_case(self) -> ContingencyCase:
        return ContingencyCase(
            case_id="N1_LINE_001",
            element_type="line",
            element_id=0,
            description="테스트 탈락 케이스",
        )

    def test_valid_tier1(self) -> None:
        cr = ContingencyResult(
            tier=1,
            contingencies=[self._make_case()],
            violations=[],
            converged_count=1,
            diverged_count=0,
            snapshot_ts=_NOW,
        )
        assert cr.tier == 1
        assert cr.worst_voltage_pu is None

    def test_valid_tier2_with_violations(self) -> None:
        violation = {
            "element_type": "line",
            "element_id": 5,
            "violation_type": "loading",
            "value": 115.0,
            "limit": 100.0,
        }
        cr = ContingencyResult(
            tier=2,
            contingencies=[self._make_case()],
            violations=[violation],
            converged_count=0,
            diverged_count=1,
            worst_voltage_pu=0.88,
            worst_loading_pct=115.0,
            snapshot_ts=_NOW,
        )
        assert cr.worst_loading_pct == 115.0

    def test_invalid_tier(self) -> None:
        with pytest.raises(ValidationError):
            ContingencyResult(
                tier=3,  # Literal[1,2] 위반
                contingencies=[],
                violations=[],
                converged_count=0,
                diverged_count=0,
                snapshot_ts=_NOW,
            )

    def test_roundtrip(self) -> None:
        cr = ContingencyResult(
            tier=1,
            contingencies=[self._make_case()],
            violations=[],
            converged_count=5,
            diverged_count=0,
            snapshot_ts=_NOW,
        )
        data = cr.model_dump()
        restored = ContingencyResult.model_validate(data)
        assert restored.tier == 1
        assert len(restored.contingencies) == 1


class TestVSAResult:
    def test_valid(self) -> None:
        vsa = VSAResult(
            critical_bus_id=5,
            p_margin_mw=800.0,
            q_margin_mvar=400.0,
            nose_point_mw=6500.0,
            snapshot_ts=_NOW,
        )
        assert vsa.critical_bus_id == 5

    def test_nose_point_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            VSAResult(
                critical_bus_id=5,
                p_margin_mw=800.0,
                q_margin_mvar=400.0,
                nose_point_mw=-100.0,  # ge=0 위반
                snapshot_ts=_NOW,
            )

    def test_critical_bus_id_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            VSAResult(
                critical_bus_id=0,  # ge=1 위반
                p_margin_mw=800.0,
                q_margin_mvar=400.0,
                nose_point_mw=6500.0,
                snapshot_ts=_NOW,
            )

    def test_roundtrip(self) -> None:
        vsa = VSAResult(
            critical_bus_id=10,
            p_margin_mw=-50.0,
            q_margin_mvar=-20.0,
            nose_point_mw=4500.0,
            snapshot_ts=_NOW,
        )
        data = vsa.model_dump()
        restored = VSAResult.model_validate(data)
        assert restored.p_margin_mw == -50.0


# ===========================================================================
# agc.py
# ===========================================================================


class TestAGCStatus:
    def test_valid_normal(self) -> None:
        agc = AGCStatus(
            frequency_hz=60.0,
            ace_mw=5.0,
            model_type="tie-line bias",
            total_regulation_mw=500.0,
            participating_units=15,
            snapshot_ts=_NOW,
        )
        assert agc.frequency_hz == 60.0

    def test_frequency_below_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            AGCStatus(
                frequency_hz=57.9,  # ge=58.0 위반
                ace_mw=0.0,
                model_type="flat_frequency",
                total_regulation_mw=100.0,
                participating_units=5,
                snapshot_ts=_NOW,
            )

    def test_frequency_above_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            AGCStatus(
                frequency_hz=62.1,  # le=62.0 위반
                ace_mw=0.0,
                model_type="tie-line bias",
                total_regulation_mw=100.0,
                participating_units=5,
                snapshot_ts=_NOW,
            )

    def test_total_regulation_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            AGCStatus(
                frequency_hz=60.0,
                ace_mw=0.0,
                model_type="tie-line bias",
                total_regulation_mw=-1.0,  # ge=0 위반
                participating_units=5,
                snapshot_ts=_NOW,
            )

    def test_roundtrip(self) -> None:
        agc = AGCStatus(
            frequency_hz=59.85,
            ace_mw=-120.0,
            model_type="tie-line bias",
            total_regulation_mw=800.0,
            participating_units=20,
            snapshot_ts=_NOW,
        )
        data = agc.model_dump()
        restored = AGCStatus.model_validate(data)
        assert restored.frequency_hz == pytest.approx(59.85)
        assert restored.ace_mw == -120.0


# ===========================================================================
# alarm.py — Enum 검증 포함
# ===========================================================================


class TestAlarmTypeEnum:
    def test_all_values_exist(self) -> None:
        assert AlarmType.LIMIT == "LIMIT"
        assert AlarmType.STATE == "STATE"
        assert AlarmType.COMM == "COMM"
        assert AlarmType.QUALITY == "QUALITY"

    def test_from_string(self) -> None:
        assert AlarmType("LIMIT") == AlarmType.LIMIT
        assert AlarmType("STATE") == AlarmType.STATE

    def test_invalid_value_raises(self) -> None:
        with pytest.raises(ValueError):
            AlarmType("INVALID")

    def test_all_members(self) -> None:
        members = {m.value for m in AlarmType}
        assert members == {"LIMIT", "STATE", "COMM", "QUALITY"}


class TestAlarmSeverityEnum:
    def test_all_values_exist(self) -> None:
        assert AlarmSeverity.INFO == "INFO"
        assert AlarmSeverity.WARNING == "WARNING"
        assert AlarmSeverity.CRITICAL == "CRITICAL"
        assert AlarmSeverity.EMERGENCY == "EMERGENCY"

    def test_from_string(self) -> None:
        assert AlarmSeverity("CRITICAL") == AlarmSeverity.CRITICAL
        assert AlarmSeverity("EMERGENCY") == AlarmSeverity.EMERGENCY

    def test_invalid_value_raises(self) -> None:
        with pytest.raises(ValueError):
            AlarmSeverity("SEVERE")

    def test_all_members(self) -> None:
        members = {m.value for m in AlarmSeverity}
        assert members == {"INFO", "WARNING", "CRITICAL", "EMERGENCY"}


class TestAlarm:
    def test_valid(self) -> None:
        alarm = Alarm(
            alarm_id="ALARM-20260325-001",
            alarm_type=AlarmType.LIMIT,
            severity=AlarmSeverity.CRITICAL,
            element_type="bus",
            element_id=1,
            message="신서울345 모선 전압 1.06pu 상한 초과",
            value=1.06,
            threshold=1.05,
            timestamp=_NOW,
        )
        assert alarm.acknowledged is False
        assert alarm.value == 1.06

    def test_valid_without_optional_fields(self) -> None:
        alarm = Alarm(
            alarm_id="ALARM-001",
            alarm_type=AlarmType.STATE,
            severity=AlarmSeverity.WARNING,
            element_type="line",
            element_id=5,
            message="선로 탈락",
            timestamp=_NOW,
        )
        assert alarm.value is None
        assert alarm.threshold is None

    def test_invalid_alarm_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            Alarm(
                alarm_id="ALARM-001",
                alarm_type="SEVERE",  # type: ignore[arg-type]
                severity=AlarmSeverity.WARNING,
                element_type="bus",
                element_id=1,
                message="test",
                timestamp=_NOW,
            )

    def test_invalid_severity_raises(self) -> None:
        with pytest.raises(ValidationError):
            Alarm(
                alarm_id="ALARM-001",
                alarm_type=AlarmType.LIMIT,
                severity="HIGH",  # type: ignore[arg-type]
                element_type="bus",
                element_id=1,
                message="test",
                timestamp=_NOW,
            )

    def test_roundtrip(self) -> None:
        alarm = Alarm(
            alarm_id="ALARM-999",
            alarm_type=AlarmType.COMM,
            severity=AlarmSeverity.INFO,
            element_type="gen",
            element_id=3,
            message="SCADA 통신 복구",
            acknowledged=True,
            timestamp=_NOW,
        )
        data = alarm.model_dump()
        restored = Alarm.model_validate(data)
        assert restored.alarm_type == AlarmType.COMM
        assert restored.acknowledged is True


class TestAlarmSummary:
    def test_valid(self) -> None:
        summary = AlarmSummary(
            total=10,
            by_type={
                AlarmType.LIMIT: 5,
                AlarmType.STATE: 3,
                AlarmType.COMM: 2,
                AlarmType.QUALITY: 0,
            },
            by_severity={
                AlarmSeverity.INFO: 2,
                AlarmSeverity.WARNING: 5,
                AlarmSeverity.CRITICAL: 3,
                AlarmSeverity.EMERGENCY: 0,
            },
            unacknowledged=7,
            snapshot_ts=_NOW,
        )
        assert summary.total == 10

    def test_total_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            AlarmSummary(
                total=-1,  # ge=0 위반
                by_type={},
                by_severity={},
                unacknowledged=0,
                snapshot_ts=_NOW,
            )

    def test_unacknowledged_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            AlarmSummary(
                total=0,
                by_type={},
                by_severity={},
                unacknowledged=-1,  # ge=0 위반
                snapshot_ts=_NOW,
            )

    def test_roundtrip(self) -> None:
        summary = AlarmSummary(
            total=3,
            by_type={AlarmType.LIMIT: 3},
            by_severity={AlarmSeverity.CRITICAL: 3},
            unacknowledged=3,
            snapshot_ts=_NOW,
        )
        data = summary.model_dump()
        restored = AlarmSummary.model_validate(data)
        assert restored.total == 3


# ===========================================================================
# study.py
# ===========================================================================


class TestStudyResult:
    def test_valid(self) -> None:
        sr = StudyResult(
            study_id="STUDY-20260325-001",
            study_type="powerflow",
            completed=True,
            result_summary="조류 계산 수렴. 최대 부하율 85%, 전압 범위 0.97~1.03pu.",
            snapshot_ts=_NOW,
        )
        assert sr.namespace == "study"
        assert sr.warnings == []

    def test_namespace_fixed_to_study(self) -> None:
        """namespace는 반드시 'study' 고정 — AI는 ops: write 불가."""
        sr = StudyResult(
            study_id="STUDY-001",
            study_type="contingency",
            completed=False,
            result_summary="N-1 분석 진행 중",
            namespace="study",
            snapshot_ts=_NOW,
        )
        assert sr.namespace == "study"

    def test_namespace_ops_raises(self) -> None:
        """ops 네임스페이스 설정 시 검증 실패 (설계 원칙 2)."""
        with pytest.raises(ValidationError):
            StudyResult(
                study_id="STUDY-001",
                study_type="powerflow",
                completed=True,
                result_summary="test",
                namespace="ops",  # type: ignore[arg-type]  # Literal["study"] 위반
                snapshot_ts=_NOW,
            )

    def test_invalid_study_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            StudyResult(
                study_id="STUDY-001",
                study_type="transient",  # type: ignore[arg-type]  # Literal 위반
                completed=True,
                result_summary="test",
                snapshot_ts=_NOW,
            )

    def test_all_study_types(self) -> None:
        for stype in ("powerflow", "contingency", "vsa", "shortcircuit"):
            sr = StudyResult(
                study_id=f"STUDY-{stype}",
                study_type=stype,  # type: ignore[arg-type]
                completed=True,
                result_summary=f"{stype} 완료",
                snapshot_ts=_NOW,
            )
            assert sr.study_type == stype

    def test_roundtrip(self) -> None:
        sr = StudyResult(
            study_id="STUDY-XYZ",
            study_type="vsa",
            completed=True,
            result_summary="전압 안정도 여유 800MW",
            warnings=["무효전력 부족 경고"],
            snapshot_ts=_NOW,
        )
        data = sr.model_dump()
        restored = StudyResult.model_validate(data)
        assert restored.study_id == "STUDY-XYZ"
        assert restored.namespace == "study"
        assert len(restored.warnings) == 1


class TestShortCircuitResult:
    def test_valid_3ph(self) -> None:
        scr = ShortCircuitResult(
            bus_id=1,
            fault_type="3ph",
            ikss_ka=25.0,
            skss_mva=14952.0,
            snapshot_ts=_NOW,
        )
        assert scr.fault_type == "3ph"

    def test_all_fault_types(self) -> None:
        for ftype in ("3ph", "slg", "llg", "ll"):
            scr = ShortCircuitResult(
                bus_id=1,
                fault_type=ftype,  # type: ignore[arg-type]
                ikss_ka=10.0,
                skss_mva=5000.0,
                snapshot_ts=_NOW,
            )
            assert scr.fault_type == ftype

    def test_invalid_fault_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            ShortCircuitResult(
                bus_id=1,
                fault_type="2ph",  # type: ignore[arg-type]  # Literal 위반
                ikss_ka=10.0,
                skss_mva=5000.0,
                snapshot_ts=_NOW,
            )

    def test_ikss_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            ShortCircuitResult(
                bus_id=1,
                fault_type="slg",
                ikss_ka=-1.0,  # ge=0 위반
                skss_mva=5000.0,
                snapshot_ts=_NOW,
            )

    def test_bus_id_zero_valid(self) -> None:
        """pandapower는 0-based index 사용 — bus_id=0은 유효해야 한다."""
        # ge=0으로 수정됨: pandapower bus index는 0부터 시작
        result = ShortCircuitResult(
            bus_id=0,
            fault_type="3ph",
            ikss_ka=10.0,
            skss_mva=5000.0,
            snapshot_ts=_NOW,
        )
        assert result.bus_id == 0

    def test_bus_id_negative_raises(self) -> None:
        """bus_id 음수는 여전히 ValidationError여야 한다 (ge=0)."""
        with pytest.raises(ValidationError):
            ShortCircuitResult(
                bus_id=-1,  # ge=0 위반
                fault_type="3ph",
                ikss_ka=10.0,
                skss_mva=5000.0,
                snapshot_ts=_NOW,
            )

    def test_roundtrip(self) -> None:
        scr = ShortCircuitResult(
            bus_id=7,
            fault_type="llg",
            ikss_ka=18.5,
            skss_mva=9000.0,
            snapshot_ts=_NOW,
        )
        data = scr.model_dump()
        restored = ShortCircuitResult.model_validate(data)
        assert restored.bus_id == 7
        assert restored.ikss_ka == pytest.approx(18.5)


# ===========================================================================
# agent.py — Evidence chain min_length=1 검증 포함
# ===========================================================================


class TestStructuredFact:
    def test_valid_with_unit(self) -> None:
        sf = StructuredFact(
            key="bus_voltage",
            value=1.02,
            unit="pu",
            source="mcp://grid/bus_voltage?bus_id=1",
        )
        assert sf.unit == "pu"

    def test_valid_without_unit(self) -> None:
        sf = StructuredFact(
            key="converged",
            value=True,
            source="pandapower:runpp",
        )
        assert sf.unit is None

    def test_roundtrip(self) -> None:
        sf = StructuredFact(
            key="loading_pct",
            value=85.0,
            unit="%",
            source="redis:ops:state:line:5",
        )
        data = sf.model_dump()
        restored = StructuredFact.model_validate(data)
        assert restored.key == "loading_pct"
        assert restored.value == 85.0


class TestEvidenceStep:
    def test_valid(self) -> None:
        es = EvidenceStep(
            tool_name="read_bus_voltage",
            input_params={"bus_id": 1, "snapshot_ts": "2026-03-25T00:00:00Z"},
            output_summary="bus 1: voltage_pu=1.02, nominal_kv=345",
            duration_ms=15.3,
        )
        assert es.duration_ms == pytest.approx(15.3)

    def test_duration_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceStep(
                tool_name="run_powerflow",
                input_params={},
                output_summary="ok",
                duration_ms=-1.0,  # ge=0 위반
            )

    def test_roundtrip(self) -> None:
        es = EvidenceStep(
            tool_name="get_line_loading",
            input_params={"line_id": 10},
            output_summary="line 10: loading_pct=75.5%",
            duration_ms=8.0,
        )
        data = es.model_dump()
        restored = EvidenceStep.model_validate(data)
        assert restored.tool_name == "get_line_loading"


class TestAgentContext:
    def test_valid_ops_hitl(self) -> None:
        ctx = AgentContext(
            session_id="session-abc-123",
            user_query="신서울345 모선 전압 확인해줘",
            namespace="ops",
            mode="HITL",
            snapshot_ts=_NOW,
        )
        assert ctx.namespace == "ops"
        assert ctx.mode == "HITL"

    def test_valid_study_hotl(self) -> None:
        ctx = AgentContext(
            session_id="session-def-456",
            user_query="N-1 예비 분석 실행해줘",
            namespace="study",
            mode="HOTL",
            snapshot_ts=_NOW,
        )
        assert ctx.namespace == "study"

    def test_invalid_namespace_raises(self) -> None:
        with pytest.raises(ValidationError):
            AgentContext(
                session_id="session-xyz",
                user_query="test",
                namespace="admin",  # type: ignore[arg-type]  # Literal 위반
                mode="HOTL",
                snapshot_ts=_NOW,
            )

    def test_invalid_mode_raises(self) -> None:
        with pytest.raises(ValidationError):
            AgentContext(
                session_id="session-xyz",
                user_query="test",
                namespace="ops",
                mode="AUTO",  # type: ignore[arg-type]  # Literal 위반
                snapshot_ts=_NOW,
            )

    def test_roundtrip(self) -> None:
        ctx = AgentContext(
            session_id="session-roundtrip",
            user_query="주파수 현황 알려줘",
            namespace="ops",
            mode="HOTL",
            snapshot_ts=_NOW,
        )
        data = ctx.model_dump()
        restored = AgentContext.model_validate(data)
        assert restored.session_id == "session-roundtrip"


class TestAIResponse:
    def test_valid_minimal(self) -> None:
        """evidence_chain 최소 1개로 정상 생성."""
        resp = AIResponse(
            answer="신서울345 모선 전압은 현재 1.02pu로 정상 범위입니다.",
            evidence_chain=[_evidence_step()],
            confidence=0.95,
            snapshot_ts=_NOW,
        )
        assert len(resp.evidence_chain) == 1
        assert resp.warnings == []
        assert resp.suggestions == []

    def test_valid_with_all_fields(self) -> None:
        resp = AIResponse(
            answer="345kV 선로 부하율 85% 경고.",
            facts=[
                StructuredFact(key="loading_pct", value=85.0, unit="%", source="pandapower")
            ],
            evidence_chain=[
                _evidence_step(),
                EvidenceStep(
                    tool_name="run_powerflow",
                    input_params={},
                    output_summary="수렴. max_loading=85%",
                    duration_ms=250.0,
                ),
            ],
            confidence=0.88,
            snapshot_ts=_NOW,
            warnings=["부하율 경고 기준 80% 초과"],
            suggestions=["무효전력 보상 검토"],
        )
        assert len(resp.evidence_chain) == 2
        assert len(resp.facts) == 1

    def test_evidence_chain_empty_raises(self) -> None:
        """Evidence chain 비어있으면 ValidationError (설계 원칙 4)."""
        with pytest.raises(ValidationError, match="evidence_chain"):
            AIResponse(
                answer="test",
                evidence_chain=[],  # min_length=1 위반
                confidence=0.5,
                snapshot_ts=_NOW,
            )

    def test_confidence_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            AIResponse(
                answer="test",
                evidence_chain=[_evidence_step()],
                confidence=1.5,  # le=1.0 위반
                snapshot_ts=_NOW,
            )

    def test_confidence_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            AIResponse(
                answer="test",
                evidence_chain=[_evidence_step()],
                confidence=-0.1,  # ge=0 위반
                snapshot_ts=_NOW,
            )

    def test_roundtrip(self) -> None:
        resp = AIResponse(
            answer="계통 정상 운영 중.",
            facts=[
                StructuredFact(key="frequency_hz", value=60.01, unit="Hz", source="redis:ops")
            ],
            evidence_chain=[_evidence_step()],
            confidence=0.99,
            snapshot_ts=_NOW,
            warnings=[],
            suggestions=["예비력 현황 확인 권장"],
        )
        data = resp.model_dump()
        restored = AIResponse.model_validate(data)
        assert restored.confidence == pytest.approx(0.99)
        assert len(restored.evidence_chain) == 1
        assert len(restored.suggestions) == 1

    def test_snapshot_ts_auto_utc(self) -> None:
        """snapshot_ts 자동 생성 시 UTC datetime 이어야 함."""
        resp = AIResponse(
            answer="test",
            evidence_chain=[_evidence_step()],
            confidence=0.5,
        )
        assert resp.snapshot_ts.tzinfo is not None


# ===========================================================================
# __init__.py re-export 검증
# ===========================================================================


class TestSchemaPackageExports:
    """src.shared.schemas 패키지에서 모든 클래스 임포트 가능한지 검증."""

    def test_all_exports_importable(self) -> None:
        from src.shared.schemas import (
            AGCStatus,
            AIResponse,
            AgentContext,
            Alarm,
            AlarmSeverity,
            AlarmSummary,
            AlarmType,
            BusVoltage,
            ContingencyCase,
            ContingencyResult,
            ErrorResponse,
            EvidenceStep,
            GenDispatch,
            LineLoading,
            PowerFlowResult,
            SEResult,
            ShortCircuitResult,
            StructuredFact,
            StudyResult,
            Timestamp,
            TopologyVersion,
            VSAResult,
        )
        # 모두 정상 임포트
        classes = [
            AGCStatus, AIResponse, AgentContext, Alarm, AlarmSeverity,
            AlarmSummary, AlarmType, BusVoltage, ContingencyCase, ContingencyResult,
            ErrorResponse, EvidenceStep, GenDispatch, LineLoading, PowerFlowResult,
            SEResult, ShortCircuitResult, StructuredFact, StudyResult, Timestamp,
            TopologyVersion, VSAResult,
        ]
        assert all(cls is not None for cls in classes)
