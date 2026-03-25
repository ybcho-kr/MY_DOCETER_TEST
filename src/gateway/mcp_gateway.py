"""MCP Gateway — AI Agent ↔ EMS Digital Twin 표준화 허브.

설계 원칙:
  2. ops/study 네임스페이스 격리 — AI는 ops: 절대 write 불가
  4. Evidence chain 필수 — 모든 Tool 호출에 대해 자동 생성
  5. snapshot_ts 필수 — Provenance 로그에 기준 시각 포함

보안 정책:
  - BLOCKED_WRITE_TOOLS 목록의 Tool → 항상 403 차단
  - namespace='ops'에서 write 의도 Tool → 403 차단
  - namespace='study'에서 write Tool → 허용 (TTL 1800s 자동 삭제)
  - 모든 Tool 호출 JSONL Provenance 로그 기록
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, Field

from src.shared.schemas.agent import EvidenceStep

logger = structlog.get_logger(__name__)

# Provenance 로그 저장 경로 (환경 변수로 오버라이드 가능)
_PROVENANCE_LOG_PATH: str = os.environ.get(
    "MCP_PROVENANCE_LOG",
    str(Path(__file__).parent.parent.parent / "logs" / "mcp_provenance.jsonl"),
)


def _utcnow() -> datetime:
    """현재 UTC 시각을 반환한다."""
    return datetime.now(timezone.utc)


class MCPToolCallRequest(BaseModel):
    """MCP Tool 호출 요청 스키마."""

    tool_name: str = Field(description="호출할 Tool 이름.")
    params: dict[str, Any] = Field(default_factory=dict, description="Tool 입력 파라미터.")
    namespace: str = Field(default="ops", description="요청 네임스페이스 ('ops' 또는 'study').")
    agent_id: str = Field(default="unknown_agent", description="요청한 에이전트 ID.")


class MCPToolCallResponse(BaseModel):
    """MCP Tool 호출 응답 스키마."""

    tool_name: str = Field(description="호출된 Tool 이름.")
    result: dict[str, Any] = Field(description="Tool 반환 결과.")
    evidence: EvidenceStep = Field(description="자동 생성된 Evidence chain 단계.")
    snapshot_ts: datetime = Field(
        default_factory=_utcnow,
        description="응답 기준 시각 (UTC).",
    )


class MCPAccessDeniedError(PermissionError):
    """ops: 네임스페이스에서 write 시도 시 발생하는 예외 (HTTP 403 해당)."""

    def __init__(self, tool_name: str, namespace: str) -> None:
        super().__init__(
            f"[403 Forbidden] ops: 네임스페이스 write 차단 — "
            f"tool='{tool_name}', namespace='{namespace}'. "
            f"설계 원칙 2: AI는 ops: write 절대 불가."
        )
        self.tool_name = tool_name
        self.namespace = namespace


class MCPToolNotFoundError(KeyError):
    """등록되지 않은 Tool 호출 시 발생하는 예외 (HTTP 404 해당)."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(f"[404 Not Found] 등록되지 않은 Tool: '{tool_name}'")
        self.tool_name = tool_name


class MCPGateway:
    """MCP Protocol Gateway — read_only 강제 + Evidence chain 자동 생성.

    ALLOWED_READ_TOOLS: 모든 네임스페이스에서 허용.
    STUDY_WRITE_TOOLS: study: 네임스페이스에서만 허용.
    BLOCKED_WRITE_TOOLS: 모든 호출 차단.

    사용 예:
        gateway = MCPGateway()
        response = await gateway.call_tool("read_bus_voltage", {"bus_id": 1}, namespace="ops")
    """

    # 조회 전용 Tool — 모든 네임스페이스에서 허용
    ALLOWED_READ_TOOLS: list[str] = [
        "read_bus_voltage",
        "read_line_loading",
        "read_gen_output",
        "query_app",
        "search_knowledge",
        "get_alarm_list",
        "get_active_alarms",
        "cluster_alarms",
        "get_powerflow_violations",
        "compare_se",
        "get_agc_status",
        "get_forecast",
        "get_risk_assessment",
        "run_grid_health_check",
        "search_documents",
        "query_db",
        "navigate_to",
        "get_screen_list",
        "highlight_elements",
        "run_acopf",
        "run_n1_contingency",
        "run_vsa",
        "get_topology",
        "get_se_observability",
    ]

    # study: 네임스페이스 전용 write Tool
    STUDY_WRITE_TOOLS: list[str] = [
        "create_study",
        "run_study",
        "run_shortcircuit",
    ]

    # 항상 차단되는 write Tool (ops: 직접 조작 시도)
    BLOCKED_WRITE_TOOLS: list[str] = [
        "write_bus",
        "set_switch",
        "modify_gen",
    ]

    def __init__(self, provenance_log_path: str = _PROVENANCE_LOG_PATH) -> None:
        """MCPGateway 초기화.

        Args:
            provenance_log_path: Provenance JSONL 로그 파일 경로.
        """
        self._provenance_log_path = provenance_log_path
        # 로그 디렉토리 생성 (존재하지 않을 경우)
        Path(provenance_log_path).parent.mkdir(parents=True, exist_ok=True)

    async def call_tool(
        self,
        tool_name: str,
        params: dict[str, Any],
        namespace: str = "ops",
        agent_id: str = "unknown_agent",
    ) -> MCPToolCallResponse:
        """Tool을 호출하고 Evidence chain을 자동 생성한다.

        보안 검사 순서:
          1. BLOCKED_WRITE_TOOLS 목록이면 403 거부
          2. namespace='ops'이고 write Tool이면 403 거부
          3. namespace='study'이고 STUDY_WRITE_TOOLS이면 허용
          4. ALLOWED_READ_TOOLS이면 허용
          5. 그 외 미등록 Tool이면 404 반환

        Args:
            tool_name: 호출할 Tool 이름.
            params: Tool 입력 파라미터.
            namespace: 요청 네임스페이스 ('ops' 또는 'study').
            agent_id: 요청한 에이전트 ID (Provenance 로그용).

        Returns:
            MCPToolCallResponse (result + evidence + snapshot_ts).

        Raises:
            MCPAccessDeniedError: ops: write 시도 또는 BLOCKED_WRITE_TOOLS 호출.
            MCPToolNotFoundError: 등록되지 않은 Tool 호출.
        """
        start_time = time.monotonic()

        # ── 보안 검사 1: 항상 차단 목록 ──────────────────────
        if tool_name in self.BLOCKED_WRITE_TOOLS:
            logger.error(
                "mcp_blocked_write_attempt",
                tool_name=tool_name,
                namespace=namespace,
                agent_id=agent_id,
            )
            raise MCPAccessDeniedError(tool_name=tool_name, namespace=namespace)

        # ── 보안 검사 2: ops: 네임스페이스 write 시도 ─────────
        if namespace == "ops" and tool_name in self.STUDY_WRITE_TOOLS:
            logger.error(
                "mcp_ops_write_blocked",
                tool_name=tool_name,
                namespace=namespace,
                agent_id=agent_id,
            )
            raise MCPAccessDeniedError(tool_name=tool_name, namespace=namespace)

        # ── Tool 등록 여부 확인 ──────────────────────────────
        all_known = set(self.ALLOWED_READ_TOOLS) | set(self.STUDY_WRITE_TOOLS)
        if tool_name not in all_known:
            logger.warning(
                "mcp_tool_not_found",
                tool_name=tool_name,
                agent_id=agent_id,
            )
            raise MCPToolNotFoundError(tool_name=tool_name)

        # ── Tool 실행 (스텁: 실제 Layer 1 API 호출로 교체 예정) ──
        result = await self._execute_tool(tool_name, params, namespace)

        duration_ms = (time.monotonic() - start_time) * 1000

        # ── Evidence chain 자동 생성 ─────────────────────────
        output_summary = self._build_output_summary(tool_name, result)
        evidence = EvidenceStep(
            tool_name=tool_name,
            input_params=params,
            output_summary=output_summary,
            duration_ms=round(duration_ms, 2),
        )

        # ── Provenance 로그 기록 ─────────────────────────────
        self._log_provenance(
            tool_name=tool_name,
            params=params,
            result=result,
            duration_ms=duration_ms,
            agent_id=agent_id,
            namespace=namespace,
        )

        response = MCPToolCallResponse(
            tool_name=tool_name,
            result=result,
            evidence=evidence,
        )
        logger.info(
            "mcp_tool_called",
            tool_name=tool_name,
            namespace=namespace,
            agent_id=agent_id,
            duration_ms=round(duration_ms, 2),
        )
        return response

    def _log_provenance(
        self,
        tool_name: str,
        params: dict[str, Any],
        result: dict[str, Any],
        duration_ms: float,
        agent_id: str = "unknown_agent",
        namespace: str = "ops",
    ) -> None:
        """Provenance 로그를 JSONL 형식으로 append 기록한다.

        {ts, agent_id, tool, params_hash, result_hash, duration_ms, namespace}
        append-only 보장: 'a' 모드로만 쓴다.
        """
        try:
            params_str = json.dumps(params, sort_keys=True, default=str)
            result_str = json.dumps(result, sort_keys=True, default=str)
            record = {
                "ts": _utcnow().isoformat(),
                "agent_id": agent_id,
                "tool": tool_name,
                "namespace": namespace,
                "params_hash": hashlib.sha256(params_str.encode()).hexdigest()[:16],
                "result_hash": hashlib.sha256(result_str.encode()).hexdigest()[:16],
                "duration_ms": round(duration_ms, 2),
            }
            with open(self._provenance_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001
            # Provenance 로그 실패가 Tool 호출을 막아서는 안 됨
            logger.error("mcp_provenance_log_failed", error=str(exc))

    async def _execute_tool(
        self,
        tool_name: str,
        params: dict[str, Any],
        namespace: str,
    ) -> dict[str, Any]:
        """Tool을 실행하고 결과를 반환한다.

        Phase 2 스텁 구현: 실제 Layer 1 API 호출 또는 직접 import로 교체 예정.
        현재는 tool_name과 params를 그대로 반환하는 에코 응답을 생성한다.
        """
        # TODO(Phase 2): httpx를 이용한 Layer 1 API 호출 구현
        # async with httpx.AsyncClient() as client:
        #     resp = await client.post(f"{LAYER1_API_BASE_URL}/mcp/{tool_name}", json=params)
        #     return resp.json()
        return {
            "tool": tool_name,
            "params": params,
            "namespace": namespace,
            "stub": True,
            "snapshot_ts": _utcnow().isoformat(),
        }

    def _build_output_summary(
        self,
        tool_name: str,
        result: dict[str, Any],
    ) -> str:
        """Tool 호출 결과 요약 문자열을 생성한다.

        수치 데이터를 직접 생성하지 않고 result에서 추출한 정보만 사용한다.
        """
        params_repr = str(result.get("params", {}))[:80]
        return (
            f"Tool '{tool_name}' 호출 완료. "
            f"params={params_repr}, "
            f"stub={result.get('stub', False)}"
        )
