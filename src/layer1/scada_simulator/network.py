"""네트워크 빌더 — pandapower 기반 계통 모델 생성.

MDP Phase 1: IEEE 14-bus 테스트 케이스 사용.
Phase 2+: 한국 실계통 .raw 파일 변환 (create_network_from_raw).

지원 기능:
  - IEEE 14-bus 테스트 케이스 (MDP 검증용)
  - PSS/E .raw v29~v34 직접 파싱 (psse_parser.py)
    pandapower 3.x에서 from_psse() 제거에 따른 자체 파서 사용
  - Switched Shunt → pandapower shunt 변환
  - 3권선 변압기 → star-equivalent 2권선 근사
  - 한글 bus_name EUC-KR/UTF-8 인코딩 처리
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandapower as pp
import pandapower.networks as pn

from src.layer1.scada_simulator.psse_parser import parse_raw_v33

logger = logging.getLogger(__name__)


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


def _fix_bus_name_encoding(net: pp.pandapowerNet) -> None:
    """bus 이름의 EUC-KR/UTF-8 인코딩 문제를 수정한다.

    PSS/E .raw 파일에서 한글 bus 이름이 깨진 경우 복구 시도.
    복구 실패 시 'Bus_{index}' 형태의 대체 이름 사용.

    Args:
        net: pandapower 네트워크 (in-place 수정).
    """
    if "name" not in net.bus.columns:
        return

    for idx in net.bus.index:
        raw_name = net.bus.at[idx, "name"]
        if not isinstance(raw_name, str):
            continue
        # EUC-KR로 잘못 디코딩된 bytes 시퀀스를 UTF-8로 재해석 시도
        try:
            fixed = raw_name.encode("latin-1").decode("euc-kr")
            net.bus.at[idx, "name"] = fixed
        except (UnicodeEncodeError, UnicodeDecodeError):
            # 이미 UTF-8이거나 복구 불가 → 원본 유지 또는 대체
            try:
                raw_name.encode("utf-8")  # 유효한 UTF-8이면 그대로
            except UnicodeEncodeError:
                net.bus.at[idx, "name"] = f"Bus_{idx}"
                logger.warning(
                    "Bus %d: 이름 인코딩 복구 실패, 'Bus_%d'로 대체.", idx, idx
                )


def _convert_switched_shunts(
    net: pp.pandapowerNet,
    switched_shunts: list[dict[str, Any]],
) -> int:
    """Switched Shunt 레코드를 pandapower shunt 요소로 변환한다.

    PSS/E .raw SWITCHED SHUNT 섹션은 pandapower from_psse()가
    직접 지원하지 않으므로 수동 변환이 필요하다.

    Args:
        net: pandapower 네트워크 (in-place 수정).
        switched_shunts: PSS/E Switched Shunt 레코드 리스트.
            각 항목 예시: {'bus': 1, 'binit': 0.5, 'vswhi': 1.05, 'vswlo': 0.95}

    Returns:
        변환된 shunt 개수.
    """
    converted = 0
    for sw in switched_shunts:
        bus_id: int = int(sw.get("bus", 0))
        # binit: 초기 투입 서셉턴스 (per unit, 기준용량 = net.sn_mva)
        binit_pu: float = float(sw.get("binit", 0.0))
        if binit_pu == 0.0:
            # 차단된 shunt는 무시
            continue

        # pandapower bus index 확인
        if bus_id - 1 not in net.bus.index:
            logger.warning("Switched Shunt: bus %d 없음, 건너뜀.", bus_id)
            continue

        # pu → Mvar 변환 (sn_mva 기준)
        sn_mva = float(net.sn_mva) if hasattr(net, "sn_mva") else 100.0
        q_mvar = binit_pu * sn_mva  # 용량성이면 양수

        pp.create_shunt(
            net,
            bus=bus_id - 1,  # pandapower 0-indexed
            q_mvar=q_mvar,
            p_mw=0.0,
            name=f"SwitchedShunt_Bus{bus_id}",
            in_service=True,
        )
        converted += 1
        logger.debug(
            "Switched Shunt 변환: bus=%d, binit=%.4f pu, q=%.2f Mvar",
            bus_id, binit_pu, q_mvar,
        )
    return converted


def _validate_3w_transformers(net: pp.pandapowerNet) -> None:
    """3권선 변압기(trafo3w) 유효성 검사 및 경고 출력.

    pandapower from_psse()는 PSS/E 3권선 변압기를 trafo3w로 변환하지만
    일부 임피던스 조합에서 수렴 문제가 발생할 수 있다.

    Args:
        net: pandapower 네트워크.
    """
    if not hasattr(net, "trafo3w") or net.trafo3w.empty:
        return

    for idx in net.trafo3w.index:
        name = str(net.trafo3w.at[idx, "name"]) if "name" in net.trafo3w.columns else f"Trafo3W_{idx}"
        hv_bus = int(net.trafo3w.at[idx, "hv_bus"])
        mv_bus = int(net.trafo3w.at[idx, "mv_bus"])
        lv_bus = int(net.trafo3w.at[idx, "lv_bus"])
        in_service = bool(net.trafo3w.at[idx, "in_service"])

        logger.debug(
            "3권선 변압기 확인: idx=%d, name=%s, hv=%d, mv=%d, lv=%d, in_service=%s",
            idx, name, hv_bus, mv_bus, lv_bus, in_service,
        )

        # 영 임피던스 경고 (수렴 문제 원인)
        for col in ("vk_hv_percent", "vk_mv_percent", "vk_lv_percent"):
            if col in net.trafo3w.columns:
                vk = float(net.trafo3w.at[idx, col])
                if vk <= 0.001:
                    logger.warning(
                        "3권선 변압기 %s: %s=%.4f%% — 영 임피던스 위험. 수렴 실패 가능.",
                        name, col, vk,
                    )


def create_network_from_raw(
    raw_path: str,
    switched_shunts: list[dict[str, Any]] | None = None,
    fix_encoding: bool = True,
) -> pp.pandapowerNet:
    """PSS/E .raw 파일에서 pandapower 네트워크 변환.

    한국 실계통 .raw 파일(v29~v34)을 pandapower로 변환한다.
    pandapower 3.x에서 from_psse()가 제거되어 자체 파서(parse_raw_v33)를 사용.

    Args:
        raw_path: .raw 파일 경로 (절대 경로 권장).
        switched_shunts: 추가 PSS/E Switched Shunt 레코드 리스트 (선택적 보완용).
            parse_raw_v33가 .raw 내 SWITCHED SHUNT 섹션을 이미 처리하므로
            일반적으로 None으로 충분.
            예: [{'bus': 1, 'binit': 0.5}, {'bus': 5, 'binit': -0.3}]
        fix_encoding: True이면 bus 이름 EUC-KR/UTF-8 인코딩 수정 시도.

    Returns:
        pandapower 네트워크 (파싱 + 후처리 완료).

    Raises:
        FileNotFoundError: .raw 파일이 존재하지 않을 때.
        RuntimeError: pandapower 변환 중 치명적 오류 발생 시.

    Notes:
        - pandapower 3.x: from_psse() 제거 → psse_parser.parse_raw_v33() 사용
        - v35 이상: v29~v34로 재저장 후 사용 권장
        - FACTS(SVC, STATCOM)는 정적 shunt/generator로 근사
        - 대규모 계통(300+버스)은 lightsim2grid 백엔드 권장
        - 3권선 변압기는 star-equivalent 2권선으로 근사 (Phase 2에서 trafo3w로 교체 예정)
    """
    path = Path(raw_path)
    if not path.exists():
        raise FileNotFoundError(f".raw 파일 없음: {raw_path}")

    logger.info(".raw 파일 로드 시작: %s (pandapower 3.x 자체 파서 사용)", raw_path)

    try:
        net = parse_raw_v33(path)
    except (FileNotFoundError, RuntimeError):
        raise
    except Exception as exc:
        raise RuntimeError(f".raw 변환 실패: {exc}") from exc

    logger.info(
        ".raw 변환 완료: buses=%d, lines=%d, trafos=%d",
        len(net.bus), len(net.line), len(net.trafo),
    )

    # 인코딩 수정 (parse_raw_v33에서 이미 처리하지만 추가 보완)
    if fix_encoding:
        _fix_bus_name_encoding(net)
        logger.debug("Bus 이름 인코딩 2차 수정 완료.")

    # 추가 Switched Shunt 변환 (외부에서 명시적으로 전달된 경우)
    if switched_shunts:
        n_converted = _convert_switched_shunts(net, switched_shunts)
        logger.info("추가 Switched Shunt %d개 변환 완료.", n_converted)

    # 3권선 변압기 검증 (parse_raw_v33에서 star-equivalent로 처리)
    _validate_3w_transformers(net)

    return net
