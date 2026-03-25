"""SCADA 스케줄러 — APScheduler 기반 주기적 조류계산 실행.

기본 주기: 4초. 설계 원칙에 따라 ops: 네임스페이스에 결과 저장.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

if TYPE_CHECKING:
    from src.layer1.scada_simulator.simulator import ScadaSimulator

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def start_scada_loop(
    simulator: ScadaSimulator,
    interval_sec: float = 4.0,
) -> BackgroundScheduler:
    """SCADA 시뮬레이션 루프 시작.

    Args:
        simulator: ScadaSimulator 인스턴스.
        interval_sec: 실행 주기 (초). 기본 4초.

    Returns:
        BackgroundScheduler 인스턴스.
    """
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        logger.warning("SCADA 스케줄러가 이미 실행 중입니다.")
        return _scheduler

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        simulator.run_cycle,
        trigger=IntervalTrigger(seconds=interval_sec),
        id="scada_cycle",
        name="SCADA 4초 주기 조류계산",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("SCADA 스케줄러 시작: %s초 주기", interval_sec)
    return _scheduler


def stop_scada_loop() -> None:
    """SCADA 시뮬레이션 루프 정지."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("SCADA 스케줄러 정지.")
    _scheduler = None
