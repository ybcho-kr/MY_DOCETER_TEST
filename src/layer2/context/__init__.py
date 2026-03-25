"""AgentContext 관리 패키지.

세션 관리, 구조화된 사실 FIFO, Evidence chain 추적을 제공한다.
structured_facts는 최근 20건 FIFO로 관리하며 절대 압축하지 않는다.
"""
from src.layer2.context.session import SessionManager
from src.layer2.context.summarizer import SessionSummarizer

__all__ = [
    "SessionManager",
    "SessionSummarizer",
]
