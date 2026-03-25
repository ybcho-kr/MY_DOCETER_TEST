"""SCADA 스케줄러 — APScheduler 기반 주기적 조류계산 실행.

기본 주기: 4초. 설계 원칙에 따라 ops: 네임스페이스에 결과 저장.

에러 처리 정책:
  - 조류계산 수렴 실패 → FAILED 플래그 저장, 이전 스냅샷 유지, 루프 지속
  - APScheduler 내부 예외 → structlog로 기록 후 루프 지속 (스케줄러 종료 안 함)
  - Redis 접속 오류 → 경고 로그 후 다음 주기에 재시도
"""
from __future__ import annotations

import traceback
from typing import TYPE_CHECKING

try:
    import structlog
    _logger = structlog.get_logger(__name__)
    _USE_STRUCTLOG = True
except ImportError:
    import logging
    _logger = logging.getLogger(__name__)  # type: ignore[assignment]
    _USE_STRUCTLOG = False

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

if TYPE_CHECKING:
    from src.layer1.scada_simulator.simulator import ScadaSimulator

_scheduler: BackgroundScheduler | None = None

# 연속 실패 임계값 — 이 횟수 초과 시 CRITICAL 레벨 로그
_CONSECUTIVE_FAIL_THRESHOLD = 5


def _log(level: str, event: str, **kw: object) -> None:
    """structlog/logging 통합 로그 헬퍼."""
    if _USE_STRUCTLOG:
        getattr(_logger, level)(event, **kw)
    else:
        msg = event + " " + " ".join(f"{k}={v}" for k, v in kw.items())
        getattr(_logger, level)(msg)


class _ScadaJobContext:
    """스케줄러 잡 컨텍스트 — 연속 실패 횟수 추적."""

    def __init__(self, simulator: "ScadaSimulator") -> None:
        self._simulator = simulator
        self._consecutive_failures: int = 0
        self._total_cycles: int = 0

    def run_once(self) -> None:
        """1주기 실행. 예외 발생 시 로그 후 계속 진행."""
        self._total_cycles += 1
        try:
            result = self._simulator.run_cycle()

            if result.converged:
                self._consecutive_failures = 0
                _log(
                    "info",
                    "SCADA 주기 완료",
                    cycle=self._total_cycles,
                    converged=True,
                    max_vm_pu=round(result.max_vm_pu, 4),
                    min_vm_pu=round(result.min_vm_pu, 4),
                    max_loading_pct=round(result.max_loading_pct, 2),
                    snapshot_ts=result.snapshot_ts.isoformat(),
                )
            else:
                self._consecutive_failures += 1
                _log(
                    "warning",
                    "SCADA 주기 수렴 실패 — 이전 스냅샷 유지",
                    cycle=self._total_cycles,
                    consecutive_failures=self._consecutive_failures,
                    snapshot_ts=result.snapshot_ts.isoformat(),
                )
                if self._consecutive_failures >= _CONSECUTIVE_FAIL_THRESHOLD:
                    _log(
                        "critical",
                        "SCADA 연속 수렴 실패 임계값 초과 — 운영자 확인 필요",
                        consecutive_failures=self._consecutive_failures,
                        threshold=_CONSECUTIVE_FAIL_THRESHOLD,
                    )

        except Exception as exc:  # noqa: BLE001
            self._consecutive_failures += 1
            _log(
                "error",
                "SCADA 주기 예외 발생 — 루프 계속",
                cycle=self._total_cycles,
                error=str(exc),
                traceback=traceback.format_exc(),
            )


def start_scada_loop(
    simulator: "ScadaSimulator",
    interval_sec: float = 4.0,
) -> BackgroundScheduler:
    """SCADA 시뮬레이션 루프 시작.

    이미 실행 중인 스케줄러가 있으면 해당 인스턴스를 그대로 반환.
    interval_sec은 1초 이상이어야 한다.

    Args:
        simulator: ScadaSimulator 인스턴스.
        interval_sec: 실행 주기 (초). 기본 4초. 최소 1초.

    Returns:
        BackgroundScheduler 인스턴스.

    Raises:
        ValueError: interval_sec < 1 인 경우.
    """
    global _scheduler

    if interval_sec < 1.0:
        raise ValueError(f"interval_sec는 1.0 이상이어야 합니다. 전달값: {interval_sec}")

    if _scheduler is not None and _scheduler.running:
        _log("warning", "SCADA 스케줄러가 이미 실행 중 — 기존 인스턴스 반환")
        return _scheduler

    ctx = _ScadaJobContext(simulator)

    _scheduler = BackgroundScheduler(
        job_defaults={
            "coalesce": True,           # 누적된 잡은 1번만 실행
            "max_instances": 1,         # 중복 실행 방지
            "misfire_grace_time": 10,   # 10초 지연 허용
        }
    )
    _scheduler.add_job(
        ctx.run_once,
        trigger=IntervalTrigger(seconds=interval_sec),
        id="scada_cycle",
        name="SCADA 4초 주기 조류계산",
        replace_existing=True,
    )
    _scheduler.start()
    _log(
        "info",
        "SCADA 스케줄러 시작",
        interval_sec=interval_sec,
        coalesce=True,
        max_instances=1,
    )
    return _scheduler


def stop_scada_loop() -> None:
    """SCADA 시뮬레이션 루프 정지.

    스케줄러가 실행 중이지 않으면 아무 동작도 하지 않음.
    """
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _log("info", "SCADA 스케줄러 정지 완료")
    else:
        _log("debug", "SCADA 스케줄러 정지 요청 — 이미 정지 상태")
    _scheduler = None


def get_scheduler_status() -> dict[str, object]:
    """스케줄러 현재 상태를 반환한다.

    Returns:
        running: 실행 여부, job_count: 등록된 잡 수.
    """
    if _scheduler is None:
        return {"running": False, "job_count": 0}
    return {
        "running": _scheduler.running,
        "job_count": len(_scheduler.get_jobs()),
    }
