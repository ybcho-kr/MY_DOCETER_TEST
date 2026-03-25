"""RAG 에이전트 — 도메인 지식 검색 (HOTL).

glossary.json, voltage_limits.json, frequency_limits.json, n1_criteria.json에서
키워드 기반 검색을 수행한다.

벡터DB(Chroma) 연동은 Phase 3+ 이후 구현 예정.
현재 Phase 1/2에서는 JSON 파일 기반 키워드 매칭.

설계 원칙:
  4. Evidence chain 필수
  5. snapshot_ts 필수
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional, Tuple

from src.layer2.agents.base import BaseAgent
from src.shared.domain import (
    get_frequency_limits,
    get_glossary,
    get_n1_criteria,
    get_voltage_limits,
)
from src.shared.schemas.agent import AgentContext, AIResponse, EvidenceStep, StructuredFact


# 검색 카테고리 키워드
_VOLTAGE_KEYWORDS = {
    "전압", "voltage", "pu", "kv", "전압기준", "전압한계", "운용범위",
    "과전압", "저전압", "조정목표", "345kv", "154kv", "66kv", "22.9kv",
}
_FREQUENCY_KEYWORDS = {
    "주파수", "frequency", "hz", "60hz", "주파수기준", "주파수한계",
    "주파수유지", "주파수이탈", "ace", "agc", "59.7", "59.5", "59.8",
}
_N1_KEYWORDS = {
    "n-1", "n1", "상정고장", "contingency", "예비", "탈락", "탈락기준",
    "n-1기준", "n-2", "고장기준", "고시 제15조", "고시15조",
}


def _normalize_query(query: str) -> str:
    """질의를 소문자 + 공백 정규화하여 반환."""
    return re.sub(r"\s+", " ", query.lower().strip())


def _contains_any(text: str, keywords: set) -> bool:
    """text에 keywords 중 하나라도 포함되는지 확인 (대소문자 무시)."""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def _search_glossary(query: str, glossary_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """glossary.json 키워드 검색.

    term_ko, term_en, definition 필드에서 질의 키워드를 매칭한다.
    최대 5건 반환.

    Args:
        query: 사용자 질의.
        glossary_data: glossary.json 로드 결과.

    Returns:
        매칭된 용어 항목 목록.
    """
    terms = glossary_data.get("terms", [])
    query_lower = query.lower()
    results = []

    # 토큰 단위 검색
    tokens = set(re.split(r"[\s,./\-]+", query_lower))
    tokens = {t for t in tokens if len(t) > 1}

    for term in terms:
        score = 0
        term_ko = str(term.get("term_ko", "")).lower()
        term_en = str(term.get("term_en", "")).lower()
        definition = str(term.get("definition", "")).lower()
        abbrevs = [str(a).lower() for a in term.get("abbreviations", [])]

        # 정확 매칭 (높은 점수)
        if query_lower in term_ko or query_lower in term_en:
            score += 10
        # 토큰 매칭
        for token in tokens:
            if token in term_ko:
                score += 3
            if token in term_en:
                score += 2
            if token in definition:
                score += 1
            if any(token in a for a in abbrevs):
                score += 4

        if score > 0:
            results.append((score, term))

    # 점수 내림차순 정렬 후 상위 5건 반환
    results.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in results[:5]]


def _search_voltage_limits(query: str, data: Dict[str, Any]) -> List[Tuple[str, Any]]:
    """voltage_limits.json에서 쿼리에 맞는 기준값 검색.

    Args:
        query: 사용자 질의.
        data: voltage_limits.json 로드 결과.

    Returns:
        [(설명, 값)] 튜플 목록.
    """
    results: List[Tuple[str, Any]] = []
    query_lower = query.lower()

    vs = data.get("voltage_standards", {})
    levels = vs.get("levels", {}) if isinstance(vs, dict) else {}

    for kv_key, limits in levels.items():
        if kv_key.lower() in query_lower or "전압" in query_lower or "voltage" in query_lower:
            results.append((f"전압기준 {kv_key}", limits))

    # 전압 조정목표/운용범위 공통 설명 추가
    if results or _contains_any(query, _VOLTAGE_KEYWORDS):
        general = vs.get("description", "")
        if general:
            results.insert(0, ("전압 기준 개요", general))

    return results[:5]


def _search_frequency_limits(query: str, data: Dict[str, Any]) -> List[Tuple[str, Any]]:
    """frequency_limits.json에서 쿼리에 맞는 기준값 검색.

    Args:
        query: 사용자 질의.
        data: frequency_limits.json 로드 결과.

    Returns:
        [(설명, 값)] 튜플 목록.
    """
    results: List[Tuple[str, Any]] = []

    if not _contains_any(query, _FREQUENCY_KEYWORDS):
        return results

    # 최상위 키 순회
    for key, value in data.items():
        if key == "version" or key == "last_updated" or key == "description":
            continue
        results.append((key, value))

    return results[:5]


def _search_n1_criteria(query: str, data: Dict[str, Any]) -> List[Tuple[str, Any]]:
    """n1_criteria.json에서 쿼리에 맞는 N-1 기준 검색.

    Args:
        query: 사용자 질의.
        data: n1_criteria.json 로드 결과.

    Returns:
        [(설명, 값)] 튜플 목록.
    """
    results: List[Tuple[str, Any]] = []

    if not _contains_any(query, _N1_KEYWORDS):
        return results

    # n1_definition
    if "n1_definition" in data:
        results.append(("N-1 정의 (고시 제15조)", data["n1_definition"]))
    # violation_criteria
    if "violation_criteria" in data:
        results.append(("N-1 위반 판정 기준", data["violation_criteria"]))
    # contingency_tiers
    if "contingency_tiers" in data:
        results.append(("예비 분석 등급(Tier)", data["contingency_tiers"]))

    return results[:5]


class RAGAgent(BaseAgent):
    """도메인 지식 검색 에이전트 (HOTL).

    glossary.json, voltage_limits.json, frequency_limits.json, n1_criteria.json에서
    키워드 기반 검색을 수행하고 근거를 evidence_chain에 기록한다.

    Phase 3+에서 Chroma 벡터DB + BGE-M3 임베딩으로 업그레이드 예정.
    """

    name: str = "rag"
    description: str = "도메인 지식 검색 에이전트 — 용어사전 및 기준값 JSON 키워드 검색"
    mode: Literal["HITL", "HOTL"] = "HOTL"

    def __init__(self) -> None:
        """RAG 에이전트 초기화 — 도메인 JSON 파일 로드."""
        self._glossary = get_glossary()
        self._voltage_limits = get_voltage_limits()
        self._frequency_limits = get_frequency_limits()
        self._n1_criteria = get_n1_criteria()

    async def run(self, context: AgentContext) -> AIResponse:
        """RAG 에이전트 실행.

        1. 사용자 질의에서 키워드 추출
        2. glossary.json 검색
        3. 기준값 JSON 검색 (voltage, frequency, N-1)
        4. 결과 + evidence_chain 반환

        Args:
            context: 에이전트 컨텍스트.

        Returns:
            AIResponse — evidence_chain 포함.
        """
        import time

        query = context.user_query
        evidence: List[EvidenceStep] = []
        facts: List[StructuredFact] = []
        sections: List[str] = []
        warnings: List[str] = []

        # ── 1. glossary.json 검색 ──────────────────────────────────────
        t0 = time.perf_counter()
        gloss_results = _search_glossary(query, self._glossary)
        gloss_ms = (time.perf_counter() - t0) * 1000.0

        evidence.append(
            self._make_evidence(
                tool_name="glossary_search",
                input_params={"query": query, "source": "src/shared/domain/glossary.json"},
                output_summary=f"{len(gloss_results)}건 매칭",
                duration_ms=gloss_ms,
            )
        )

        if gloss_results:
            term_lines = []
            for term in gloss_results:
                ko = term.get("term_ko", "")
                en = term.get("term_en", "")
                defn = term.get("definition", "")
                term_lines.append(f"  - {ko} ({en}): {defn[:120]}{'...' if len(defn) > 120 else ''}")
                facts.append(
                    self._make_fact(
                        key=f"glossary_{term.get('id', 'unknown')}",
                        value={"term_ko": ko, "term_en": en, "definition": defn[:200]},
                        source=f"glossary.json::{term.get('id', '')}",
                    )
                )
            sections.append("[용어 검색 결과]\n" + "\n".join(term_lines))

        # ── 2. voltage_limits.json 검색 ──────────────────────────────
        t1 = time.perf_counter()
        volt_results = _search_voltage_limits(query, self._voltage_limits)
        volt_ms = (time.perf_counter() - t1) * 1000.0

        if volt_results:
            evidence.append(
                self._make_evidence(
                    tool_name="voltage_limits_search",
                    input_params={"query": query, "source": "src/shared/domain/voltage_limits.json"},
                    output_summary=f"{len(volt_results)}건 매칭",
                    duration_ms=volt_ms,
                )
            )
            volt_lines = []
            for desc, val in volt_results:
                val_str = str(val)[:150]
                volt_lines.append(f"  - {desc}: {val_str}")
                facts.append(
                    self._make_fact(
                        key=f"voltage_limit_{desc.replace(' ', '_')}",
                        value=val,
                        source="voltage_limits.json",
                    )
                )
            sections.append("[전압 기준]\n" + "\n".join(volt_lines))

        # ── 3. frequency_limits.json 검색 ────────────────────────────
        t2 = time.perf_counter()
        freq_results = _search_frequency_limits(query, self._frequency_limits)
        freq_ms = (time.perf_counter() - t2) * 1000.0

        if freq_results:
            evidence.append(
                self._make_evidence(
                    tool_name="frequency_limits_search",
                    input_params={"query": query, "source": "src/shared/domain/frequency_limits.json"},
                    output_summary=f"{len(freq_results)}건 매칭",
                    duration_ms=freq_ms,
                )
            )
            freq_lines = []
            for desc, val in freq_results:
                val_str = str(val)[:150]
                freq_lines.append(f"  - {desc}: {val_str}")
                facts.append(
                    self._make_fact(
                        key=f"freq_limit_{desc.replace(' ', '_')}",
                        value=val,
                        source="frequency_limits.json",
                    )
                )
            sections.append("[주파수 기준]\n" + "\n".join(freq_lines))

        # ── 4. n1_criteria.json 검색 ─────────────────────────────────
        t3 = time.perf_counter()
        n1_results = _search_n1_criteria(query, self._n1_criteria)
        n1_ms = (time.perf_counter() - t3) * 1000.0

        if n1_results:
            evidence.append(
                self._make_evidence(
                    tool_name="n1_criteria_search",
                    input_params={"query": query, "source": "src/shared/domain/n1_criteria.json"},
                    output_summary=f"{len(n1_results)}건 매칭",
                    duration_ms=n1_ms,
                )
            )
            n1_lines = []
            for desc, val in n1_results:
                val_str = str(val)[:200]
                n1_lines.append(f"  - {desc}: {val_str}")
                facts.append(
                    self._make_fact(
                        key=f"n1_{desc.replace(' ', '_')}",
                        value=val,
                        source="n1_criteria.json",
                    )
                )
            sections.append("[N-1 기준 (고시 제15조)]\n" + "\n".join(n1_lines))

        # evidence가 없으면 최소 1개 보장 (glossary 검색은 항상 실행)
        if not evidence:
            evidence.append(
                self._make_evidence(
                    tool_name="glossary_search",
                    input_params={"query": query, "source": "src/shared/domain/glossary.json"},
                    output_summary="매칭 없음",
                    duration_ms=0.0,
                )
            )

        # ── 응답 조립 ────────────────────────────────────────────────
        if sections:
            answer = f"'{query}'에 대한 도메인 지식 검색 결과:\n\n" + "\n\n".join(sections)
            confidence = min(0.95, 0.6 + len(sections) * 0.1)
        else:
            answer = (
                f"'{query}'에 대한 검색 결과를 찾지 못했습니다.\n"
                "더 구체적인 키워드 (예: '전압', '주파수', 'N-1', '상태추정')로 다시 시도해 주세요."
            )
            confidence = 0.3
            warnings.append("검색 결과 없음 — 키워드를 구체화해 주세요.")

        return self._build_response(
            answer=answer,
            facts=facts,
            evidence=evidence,
            confidence=confidence,
            warnings=warnings,
        )
