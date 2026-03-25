"""네트워크 빌더 — pandapower 기반 계통 모델 생성.

MDP Phase 1: IEEE 14-bus 테스트 케이스 사용.
Phase 2+: 한국 실계통 .raw 파일 변환.
"""
from __future__ import annotations

import pandapower as pp
import pandapower.networks as pn


def create_ieee14_network() -> pp.pandapowerNet:
    """IEEE 14-bus 테스트 네트워크 생성.

    MDP 단계에서 파이프라인 검증용으로 사용.
    모든 수치는 pandapower 내장 케이스에서 제공 — LLM 생성 금지.
    """
    net = pn.case14()
    # pandapower case14는 bus index가 0부터 시작
    # 스위치가 없으면 토폴로지 프로세서 테스트용으로 추가
    if len(net.switch) == 0:
        # 선로 0번에 차단기(CB) 추가 — 기본 닫힘 상태
        pp.create_switch(
            net,
            bus=net.line.at[0, "from_bus"],
            element=0,
            et="l",
            closed=True,
            type="CB",
            name="CB_LINE_0",
        )
        # 선로 1번에도 차단기 추가
        pp.create_switch(
            net,
            bus=net.line.at[1, "from_bus"],
            element=1,
            et="l",
            closed=True,
            type="CB",
            name="CB_LINE_1",
        )
    return net


def create_network_from_raw(raw_path: str) -> pp.pandapowerNet:
    """PSS/E .raw 파일에서 pandapower 네트워크 변환 (Phase 2+).

    Args:
        raw_path: .raw 파일 경로.

    Returns:
        pandapower 네트워크.

    Raises:
        FileNotFoundError: .raw 파일이 존재하지 않을 때.
        NotImplementedError: v35 포맷 등 미지원 포맷일 때.
    """
    from pandapower.converter import from_psse

    net = from_psse(raw_path)
    return net
