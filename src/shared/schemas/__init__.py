"""
AI-EMS v5.1 공유 Pydantic v2 스키마 패키지.
모든 API 입출력은 이 패키지의 스키마를 사용해야 한다.
"""
from __future__ import annotations

# common
from src.shared.schemas.common import ErrorResponse, Timestamp

# grid
from src.shared.schemas.grid import (
    BusVoltage,
    GenDispatch,
    LineLoading,
    TopologyVersion,
)

# se (State Estimation)
from src.shared.schemas.se import SEResult

# tp (Topology Processing / Power Flow)
from src.shared.schemas.tp import (
    ContingencyCase,
    ContingencyResult,
    PowerFlowResult,
    VSAResult,
)

# agc (Automatic Generation Control)
from src.shared.schemas.agc import AGCStatus

# alarm
from src.shared.schemas.alarm import (
    Alarm,
    AlarmSeverity,
    AlarmSummary,
    AlarmType,
)

# study
from src.shared.schemas.study import ShortCircuitResult, StudyResult

# agent
from src.shared.schemas.agent import (
    AgentContext,
    AIResponse,
    EvidenceStep,
    StructuredFact,
)

__all__ = [
    # common
    "Timestamp",
    "ErrorResponse",
    # grid
    "BusVoltage",
    "LineLoading",
    "GenDispatch",
    "TopologyVersion",
    # se
    "SEResult",
    # tp
    "PowerFlowResult",
    "ContingencyCase",
    "ContingencyResult",
    "VSAResult",
    # agc
    "AGCStatus",
    # alarm
    "AlarmType",
    "AlarmSeverity",
    "Alarm",
    "AlarmSummary",
    # study
    "StudyResult",
    "ShortCircuitResult",
    # agent
    "StructuredFact",
    "EvidenceStep",
    "AgentContext",
    "AIResponse",
]
