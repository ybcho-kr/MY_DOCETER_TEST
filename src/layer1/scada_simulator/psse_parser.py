"""PSS/E v33 .raw 파일 직접 파서 — pandapower 3.x 호환.

pandapower 3.x에서 from_psse()가 제거됨에 따라
PSS/E v33 포맷의 .raw 파일을 직접 파싱하여
pandapower 네트워크를 생성하는 모듈.

지원 섹션:
  - BUS (모선)
  - LOAD (부하)
  - FIXED SHUNT (고정 분로)
  - GENERATOR (발전기)
  - BRANCH (송전선)
  - TRANSFORMER (2권선 변압기, 3권선 변압기는 근사)
  - SWITCHED SHUNT (투입형 분로, binit 기반)

설계 원칙:
  - 모든 수치는 .raw 파일 원본 값 사용 (LLM 생성 금지)
  - 파싱 실패 레코드: SKIP + 경고 로그 (치명적 오류 아님)
  - 인코딩: latin-1 (EUC-KR 포함 PSS/E 표준)
  - 3권선 변압기: Star equivalent(2권선×3)로 근사 — Phase 2에서 trafo3w로 교체
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pandapower as pp

logger = logging.getLogger(__name__)

# PSS/E v33 버스 타입 → pandapower 의미
# 1=PQ(부하모선), 2=PV(발전모선), 3=Slack, 4=isolated
_BUS_TYPE_MAP: dict[int, str] = {
    1: "b",   # PQ
    2: "b",   # PV
    3: "b",   # Slack
    4: "b",   # isolated (비서비스)
}


def _strip_comment(line: str) -> str:
    """PSS/E 라인에서 '/' 이후 주석 제거."""
    idx = line.find("/")
    if idx >= 0:
        return line[:idx].strip()
    return line.strip()


def _parse_sections(raw_path: Path) -> dict[str, list[str]]:
    """PSS/E .raw 파일을 섹션별로 분리한다.

    PSS/E v33 파일 구조:
      - Line 1: 헤더 (버전, 기준용량 등)
      - Line 2~3: 제목 라인 2개
      - Line 4~: BUS 데이터 (첫 번째 섹션, 명시적 BEGIN 없음)
      - "0 / END OF BUS DATA, BEGIN LOAD DATA" 형태로 섹션 전환

    Args:
        raw_path: .raw 파일 경로.

    Returns:
        섹션명 → 라인 리스트 dict.
        섹션명 예: 'BUS', 'LOAD', 'GENERATOR', 'BRANCH', 'TRANSFORMER', ...
    """
    # PSS/E는 latin-1 인코딩 사용 (한글 bus 이름은 bytes로 포함)
    with open(raw_path, encoding="latin-1", errors="replace") as f:
        raw_lines = f.readlines()

    sections: dict[str, list[str]] = {}
    # PSS/E v33: 첫 3라인은 헤더/제목, 4번째 라인부터 BUS 데이터
    current_section = "BUS"
    sections[current_section] = []
    header_lines_skipped = 0

    for line in raw_lines:
        stripped = line.strip()

        # 처음 3라인 (헤더 + 제목 2개) 건너뜀
        if header_lines_skipped < 3:
            header_lines_skipped += 1
            continue

        # 섹션 전환 마커: "0 / END OF ... DATA, BEGIN ... DATA"
        end_match = re.search(
            r"END\s+OF\s+([\w\s\-]+?)\s+DATA.*BEGIN\s+([\w\s\-]+?)\s+DATA",
            stripped,
            re.IGNORECASE,
        )
        if end_match:
            next_section = end_match.group(2).strip().upper()
            # 공백 및 특수문자 정리
            next_section = re.sub(r"[\s\-]+", "_", next_section)
            current_section = next_section
            sections.setdefault(current_section, [])
            continue

        # 마지막 섹션 종료: "0 / END OF ... DATA" (BEGIN 없음)
        if re.search(r"END\s+OF\s+\w", stripped, re.IGNORECASE) and "BEGIN" not in stripped.upper():
            continue

        # "0" 단독 라인 (일부 PSS/E 버전의 섹션 구분자)
        if stripped == "0":
            continue

        # 빈 라인 또는 주석 라인 건너뜀
        if not stripped or stripped.startswith("@"):
            continue

        # 일반 데이터 라인
        sections.setdefault(current_section, []).append(stripped)

    return sections


def _parse_float(s: str, default: float = 0.0) -> float:
    """문자열을 float으로 파싱. 실패 시 default 반환."""
    try:
        return float(s.strip())
    except (ValueError, AttributeError):
        return default


def _parse_int(s: str, default: int = 0) -> int:
    """문자열을 int로 파싱. 실패 시 default 반환."""
    try:
        return int(s.strip())
    except (ValueError, AttributeError):
        return default


def _build_buses(
    net: pp.pandapowerNet,
    lines: list[str],
    sn_mva: float,
) -> dict[int, int]:
    """BUS 섹션을 파싱하여 pandapower 모선을 생성한다.

    PSS/E v33 BUS 레코드 형식 (콤마 구분):
      I, NAME, BASKV, IDE, AREA, ZONE, OWNER, VM, VA, NVHI, NVLO, EVHI, EVLO

    Args:
        net: pandapower 네트워크 (in-place 수정).
        lines: BUS 섹션 라인 리스트.
        sn_mva: 계통 기준 용량 (MVA).

    Returns:
        psse_bus_id → pandapower_bus_index 매핑 dict.
    """
    bus_map: dict[int, int] = {}

    for line in lines:
        line = _strip_comment(line)
        if not line or line.startswith("0"):
            continue
        parts = line.split(",")
        if len(parts) < 3:
            continue
        try:
            psse_id = _parse_int(parts[0])
            name_raw = parts[1].strip().strip("'").strip()
            # PSS/E name에서 latin-1 → EUC-KR 복구 시도
            try:
                name = name_raw.encode("latin-1").decode("euc-kr").strip()
            except (UnicodeDecodeError, UnicodeEncodeError):
                name = name_raw.strip()
            if not name:
                name = f"Bus_{psse_id}"

            base_kv = _parse_float(parts[2]) if len(parts) > 2 else 1.0
            ide = _parse_int(parts[3]) if len(parts) > 3 else 1
            vm = _parse_float(parts[7]) if len(parts) > 7 else 1.0

            # IDE=4: isolated (비서비스)
            in_service = ide != 4

            pp_idx = pp.create_bus(
                net,
                vn_kv=base_kv,
                name=name,
                type="b",
                in_service=in_service,
                max_vm_pu=1.1,
                min_vm_pu=0.9,
                index=None,
            )
            bus_map[psse_id] = pp_idx

            # 슬랙 버스: ext_grid 생성 (IDE=3)
            if ide == 3:
                pp.create_ext_grid(
                    net,
                    bus=pp_idx,
                    vm_pu=vm,
                    name=f"Slack_{name}",
                    in_service=True,
                )

        except Exception as exc:  # noqa: BLE001
            logger.debug("BUS 파싱 오류 (건너뜀): line=%r, error=%s", line[:60], exc)

    logger.info("BUS 파싱 완료: %d개 모선 생성", len(bus_map))
    return bus_map


def _build_loads(
    net: pp.pandapowerNet,
    lines: list[str],
    bus_map: dict[int, int],
) -> None:
    """LOAD 섹션을 파싱하여 pandapower 부하를 생성한다.

    PSS/E v33 LOAD 레코드:
      I, ID, STATUS, AREA, ZONE, PL, QL, IP, IQ, YP, YQ, OWNER, SCALE, INTRPT

    Args:
        net: pandapower 네트워크 (in-place 수정).
        lines: LOAD 섹션 라인 리스트.
        bus_map: psse_bus_id → pp_bus_index 매핑.
    """
    count = 0
    for line in lines:
        line = _strip_comment(line)
        if not line or line.startswith("0"):
            continue
        parts = line.split(",")
        if len(parts) < 6:
            continue
        try:
            psse_id = _parse_int(parts[0])
            status = _parse_int(parts[2])
            pl_mw = _parse_float(parts[5])    # 유효 부하 (MW)
            ql_mvar = _parse_float(parts[6]) if len(parts) > 6 else 0.0  # 무효 부하
            # ZIP 부하 (IP, IQ, YP, YQ)는 현재 정전력 부하만 사용 (Phase 1)

            if psse_id not in bus_map:
                continue
            pp_bus = bus_map[psse_id]

            pp.create_load(
                net,
                bus=pp_bus,
                p_mw=pl_mw,
                q_mvar=ql_mvar,
                in_service=(status == 1),
                name=f"Load_{psse_id}_{parts[1].strip().strip(chr(39))}",
            )
            count += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug("LOAD 파싱 오류 (건너뜀): line=%r, error=%s", line[:60], exc)

    logger.info("LOAD 파싱 완료: %d개 부하 생성", count)


def _build_fixed_shunts(
    net: pp.pandapowerNet,
    lines: list[str],
    bus_map: dict[int, int],
) -> None:
    """FIXED SHUNT 섹션을 파싱하여 pandapower shunt를 생성한다.

    PSS/E v33 FIXED SHUNT 레코드:
      I, ID, STATUS, GL, BL

    Args:
        net: pandapower 네트워크 (in-place 수정).
        lines: FIXED_SHUNT 섹션 라인 리스트.
        bus_map: psse_bus_id → pp_bus_index 매핑.
    """
    count = 0
    for line in lines:
        line = _strip_comment(line)
        if not line or line.startswith("0"):
            continue
        parts = line.split(",")
        if len(parts) < 4:
            continue
        try:
            psse_id = _parse_int(parts[0])
            status = _parse_int(parts[2])
            gl = _parse_float(parts[3])   # 컨덕턴스 (MW at V=1pu)
            bl = _parse_float(parts[4]) if len(parts) > 4 else 0.0  # 서셉턴스 (Mvar at V=1pu)

            if psse_id not in bus_map:
                continue
            pp_bus = bus_map[psse_id]

            # pandapower shunt: p_mw = 손실(컨덕턴스), q_mvar = 주입(서셉턴스 부호 반전)
            if abs(gl) > 1e-9 or abs(bl) > 1e-9:
                pp.create_shunt(
                    net,
                    bus=pp_bus,
                    p_mw=gl,
                    q_mvar=-bl,  # PSS/E BL은 capacitive+ → pandapower q_mvar는 inductive+
                    in_service=(status == 1),
                    name=f"FixedShunt_{psse_id}",
                )
                count += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug("FIXED SHUNT 파싱 오류 (건너뜀): line=%r, error=%s", line[:60], exc)

    logger.info("FIXED SHUNT 파싱 완료: %d개 shunt 생성", count)


def _build_generators(
    net: pp.pandapowerNet,
    lines: list[str],
    bus_map: dict[int, int],
) -> None:
    """GENERATOR 섹션을 파싱하여 pandapower 발전기를 생성한다.

    PSS/E v33 GENERATOR 레코드:
      I, ID, PG, QG, QT, QB, VS, IREG, MBASE, ZR, ZX, RT, XT, GTAP, STAT,
      RMPCT, PT, PB, O1, F1, ...

    Args:
        net: pandapower 네트워크 (in-place 수정).
        lines: GENERATOR 섹션 라인 리스트.
        bus_map: psse_bus_id → pp_bus_index 매핑.
    """
    count = 0
    for line in lines:
        line = _strip_comment(line)
        if not line or line.startswith("0"):
            continue
        parts = line.split(",")
        if len(parts) < 7:
            continue
        try:
            psse_id = _parse_int(parts[0])
            pg_mw = _parse_float(parts[2])   # 유효 발전 (MW)
            qg_mvar = _parse_float(parts[3]) # 무효 발전 (Mvar)
            qt_mvar = _parse_float(parts[4]) # 최대 무효 (Mvar)
            qb_mvar = _parse_float(parts[5]) # 최소 무효 (Mvar)
            vs_pu = _parse_float(parts[6])   # 전압 설정치 (pu)
            stat = _parse_int(parts[14]) if len(parts) > 14 else 1
            pt_mw = _parse_float(parts[16]) if len(parts) > 16 else pg_mw  # 최대 유효
            pb_mw = _parse_float(parts[17]) if len(parts) > 17 else 0.0    # 최소 유효

            if psse_id not in bus_map:
                continue
            pp_bus = bus_map[psse_id]

            # ext_grid로 이미 생성된 슬랙 버스의 발전기는 추가 생성 생략
            existing_ext = net.ext_grid[net.ext_grid["bus"] == pp_bus]
            if not existing_ext.empty:
                # 슬랙 발전기 — ext_grid로 대신 처리됨
                continue

            # 최대 무효가 설정되지 않으면 기본값
            if qt_mvar <= qb_mvar:
                qt_mvar = max(abs(qg_mvar) * 2, 9999.0)
                qb_mvar = -qt_mvar

            pp.create_gen(
                net,
                bus=pp_bus,
                p_mw=pg_mw,
                vm_pu=vs_pu if vs_pu > 0.5 else 1.0,
                name=f"Gen_{psse_id}_{parts[1].strip().strip(chr(39))}",
                in_service=(stat == 1),
                max_q_mvar=qt_mvar,
                min_q_mvar=qb_mvar,
                max_p_mw=pt_mw,
                min_p_mw=pb_mw,
            )
            count += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug("GENERATOR 파싱 오류 (건너뜀): line=%r, error=%s", line[:60], exc)

    logger.info("GENERATOR 파싱 완료: %d개 발전기 생성", count)


def _build_branches(
    net: pp.pandapowerNet,
    lines: list[str],
    bus_map: dict[int, int],
    sn_mva: float,
) -> None:
    """BRANCH 섹션을 파싱하여 pandapower 선로 또는 임피던스 요소를 생성한다.

    PSS/E v33 BRANCH 레코드:
      I, J, CKT, R, X, B, RATEA, RATEB, RATEC, GI, BI, GJ, BJ, ST, MET, LEN, O1, F1, ...

    특수 케이스:
      - X < 0 (직렬 콘덴서): pandapower impedance 요소로 생성 (pu 기반)
      - X = 0이고 R = 0: 가상 선로(tie-line). 최소 임피던스 부여.

    Args:
        net: pandapower 네트워크 (in-place 수정).
        lines: BRANCH 섹션 라인 리스트.
        bus_map: psse_bus_id → pp_bus_index 매핑.
        sn_mva: 계통 기준 용량 (MVA).
    """
    count_line = 0
    count_impedance = 0

    for line in lines:
        line = _strip_comment(line)
        if not line or line.startswith("0"):
            continue
        parts = line.split(",")
        if len(parts) < 6:
            continue
        try:
            i_id = _parse_int(parts[0])
            j_id = _parse_int(parts[1])
            r_pu = _parse_float(parts[3])
            x_pu = _parse_float(parts[4])
            b_pu = _parse_float(parts[5])
            rate_a = _parse_float(parts[6]) if len(parts) > 6 else 0.0  # MVA 용량
            st = _parse_int(parts[13]) if len(parts) > 13 else 1

            if i_id not in bus_map or j_id not in bus_map:
                continue
            pp_from = bus_map[i_id]
            pp_to = bus_map[j_id]

            name = f"Line_{i_id}_{j_id}_{parts[2].strip().strip(chr(39))}"

            # 직렬 콘덴서 (X < 0): pandapower impedance 요소로 처리
            if x_pu < 0:
                # impedance는 pu 기반으로 직접 입력
                pp.create_impedance(
                    net,
                    from_bus=pp_from,
                    to_bus=pp_to,
                    rft_pu=r_pu,
                    xft_pu=x_pu,  # 음수 허용
                    sn_mva=sn_mva,
                    in_service=(st == 1),
                    name=f"SeriesCapacitor_{i_id}_{j_id}",
                )
                count_impedance += 1
                continue

            # 기준 전압 (from bus 기준)
            vn_kv = float(net.bus.at[pp_from, "vn_kv"])
            if vn_kv <= 0:
                vn_kv = 1.0

            # pu → ohm 변환: Z_base = Vn^2 / Sn
            z_base = (vn_kv ** 2) / sn_mva
            r_ohm = r_pu * z_base
            x_ohm = x_pu * z_base

            # 충전 서셉턴스: B[S] = b_pu / z_base → C[nF]
            b_s = b_pu / z_base if z_base > 0 else 0.0
            c_nf = b_s / (2.0 * 3.14159265 * 60.0) * 1e9

            # 전류 용량: rate_a [MVA] → max_i_ka
            if rate_a > 0:
                max_i_ka = rate_a / (vn_kv * 3.0 ** 0.5)
            else:
                max_i_ka = 9999.0 / (vn_kv * 3.0 ** 0.5)

            # X=0, R=0인 경우: 최소 임피던스 부여 (수렴 안정성)
            if abs(x_ohm) < 1e-9 and abs(r_ohm) < 1e-9:
                x_ohm = 1e-6

            # X=0이면 최소값 설정 (수치 안정성)
            if abs(x_ohm) < 1e-9:
                x_ohm = 1e-9

            # 길이는 1km로 고정 (임피던스를 ohm/km로 넘기기 위해)
            pp.create_line_from_parameters(
                net,
                from_bus=pp_from,
                to_bus=pp_to,
                length_km=1.0,
                r_ohm_per_km=r_ohm,
                x_ohm_per_km=x_ohm,
                c_nf_per_km=max(c_nf, 0.0),  # 음수 방지
                max_i_ka=max_i_ka,
                in_service=(st == 1),
                name=name,
            )
            count_line += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug("BRANCH 파싱 오류 (건너뜀): line=%r, error=%s", line[:60], exc)

    logger.info(
        "BRANCH 파싱 완료: 선로 %d개, 임피던스(직렬콘덴서 등) %d개 생성",
        count_line, count_impedance,
    )


def _build_transformers(
    net: pp.pandapowerNet,
    lines: list[str],
    bus_map: dict[int, int],
    sn_mva: float,
) -> None:
    """TRANSFORMER 섹션을 파싱하여 pandapower 변압기를 생성한다.

    PSS/E v33 2권선 변압기는 4라인으로 구성:
      Line 1: I, J, K, CKT, CW, CZ, CM, MAG1, MAG2, NMETR, NAME, STAT, ...
      Line 2: R1-2, X1-2, SBASE1-2
      Line 3: WINDV1, NOMV1, ANG1, RATA1, RATB1, RATC1, COD1, CONT1, ...
      Line 4: WINDV2, NOMV2

    3권선 변압기(K != 0)는 star-equivalent로 근사.

    Args:
        net: pandapower 네트워크 (in-place 수정).
        lines: TRANSFORMER 섹션 라인 리스트.
        bus_map: psse_bus_id → pp_bus_index 매핑.
        sn_mva: 계통 기준 용량 (MVA).
    """
    count_2w = 0
    count_3w = 0
    i = 0

    while i < len(lines):
        line1 = _strip_comment(lines[i])
        if not line1 or line1.startswith("0") or line1.startswith("@"):
            i += 1
            continue

        parts1 = line1.split(",")
        if len(parts1) < 3:
            i += 1
            continue

        try:
            i_bus = _parse_int(parts1[0])
            j_bus = _parse_int(parts1[1])
            k_bus = _parse_int(parts1[2])
            stat = _parse_int(parts1[11]) if len(parts1) > 11 else 1

            is_3winding = (k_bus != 0)

            # 다음 3라인 읽기
            if i + 3 >= len(lines):
                i += 1
                break

            line2 = _strip_comment(lines[i + 1])
            line3 = _strip_comment(lines[i + 2])
            line4 = _strip_comment(lines[i + 3]) if not is_3winding else ""

            parts2 = line2.split(",")
            parts3 = line3.split(",")
            parts4 = line4.split(",") if not is_3winding else []

            if is_3winding:
                # 3권선: 5번째 라인(line 4, line 5) 추가
                # 현재는 2권선 근사 처리 (H-M 권선만 생성)
                # TODO Phase 2: pp.create_transformer3w_from_parameters
                r_pu = _parse_float(parts2[0]) if parts2 else 0.0
                x_pu = _parse_float(parts2[1]) if len(parts2) > 1 else 0.001
                sbase = _parse_float(parts2[2]) if len(parts2) > 2 else sn_mva
                rata = _parse_float(parts3[3]) if len(parts3) > 3 else sbase

                if i_bus in bus_map and j_bus in bus_map:
                    pp_hv = bus_map[i_bus]
                    pp_mv = bus_map[j_bus]
                    vn_hv = float(net.bus.at[pp_hv, "vn_kv"])
                    vn_mv = float(net.bus.at[pp_mv, "vn_kv"])

                    # x_pu → vk_percent (%)
                    if sbase > 0 and sbase != sn_mva:
                        x_pu_sys = x_pu * (sn_mva / sbase)
                    else:
                        x_pu_sys = x_pu
                    vk_pct = max(abs(x_pu_sys) * 100.0, 0.1)
                    vkr_pct = abs(r_pu * (sn_mva / sbase if sbase > 0 else 1.0)) * 100.0
                    sn_mva_t = rata if rata > 0 else sn_mva

                    pp.create_transformer_from_parameters(
                        net,
                        hv_bus=pp_hv,
                        lv_bus=pp_mv,
                        sn_mva=sn_mva_t,
                        vn_hv_kv=vn_hv,
                        vn_lv_kv=vn_mv,
                        vkr_percent=vkr_pct,
                        vk_percent=vk_pct,
                        pfe_kw=0.0,
                        i0_percent=0.0,
                        in_service=(stat == 1),
                        name=f"Trafo3W_approx_{i_bus}_{j_bus}_{k_bus}",
                    )
                    count_3w += 1

                i += 5  # 3-winding: line1 + 4 data lines
                continue

            # 2권선 변압기
            r_pu = _parse_float(parts2[0]) if parts2 else 0.0
            x_pu = _parse_float(parts2[1]) if len(parts2) > 1 else 0.001
            sbase12 = _parse_float(parts2[2]) if len(parts2) > 2 else sn_mva

            # Line 3: WINDV1, NOMV1, ANG1, RATA1, RATB1, RATC1, ...
            rata = _parse_float(parts3[3]) if len(parts3) > 3 else sbase12
            windv1 = _parse_float(parts3[0]) if parts3 else 1.0
            nomv1 = _parse_float(parts3[1]) if len(parts3) > 1 else 0.0  # 0이면 bus vn_kv 사용

            # Line 4: WINDV2, NOMV2
            windv2 = _parse_float(parts4[0]) if parts4 else 1.0
            nomv2 = _parse_float(parts4[1]) if len(parts4) > 1 else 0.0

            if i_bus not in bus_map or j_bus not in bus_map:
                i += 4
                continue

            pp_hv = bus_map[i_bus]
            pp_lv = bus_map[j_bus]
            vn_hv = float(net.bus.at[pp_hv, "vn_kv"])
            vn_lv = float(net.bus.at[pp_lv, "vn_kv"])

            # pandapower에서 vn_hv_kv/vn_lv_kv는 실제 연결 버스의 vn_kv와 동일하게 설정.
            # PSS/E nomv(권선 정격전압)가 bus vn_kv와 다른 경우 off-nominal 탭이 발생.
            # tap_nom_percent = (nomv/bus_kv - 1) * 100 으로 처리하면 좋지만
            # 현재는 bus vn_kv 기준으로 단순화 (Phase 1 MDP).
            # windv1(탭 위치 pu) 반영: tap_pos 계산
            hv_kv = vn_hv
            lv_kv = vn_lv

            # HV/LV 정렬
            if hv_kv < lv_kv:
                pp_hv, pp_lv = pp_lv, pp_hv
                hv_kv, lv_kv = lv_kv, hv_kv
                windv1, windv2 = windv2, windv1
                nomv1, nomv2 = nomv2, nomv1

            # impedance를 sbase12 기준에서 sn_mva 기준으로 변환
            if sbase12 > 0 and abs(sbase12 - sn_mva) > 1.0:
                scale = sn_mva / sbase12
                r_pu_sys = r_pu * scale
                x_pu_sys = x_pu * scale
            else:
                r_pu_sys = r_pu
                x_pu_sys = x_pu

            # vk_percent: 최소 0.1%, 최대 99% 범위로 클리핑 (수렴 안정성)
            vk_pct = min(max(abs(x_pu_sys) * 100.0, 0.1), 99.0)
            vkr_pct = min(abs(r_pu_sys) * 100.0, 99.0)
            sn_mva_t = rata if rata > 0 else sn_mva

            pp.create_transformer_from_parameters(
                net,
                hv_bus=pp_hv,
                lv_bus=pp_lv,
                sn_mva=sn_mva_t,
                vn_hv_kv=hv_kv,
                vn_lv_kv=lv_kv,
                vkr_percent=vkr_pct,
                vk_percent=vk_pct,
                pfe_kw=0.0,
                i0_percent=0.0,
                shift_degree=0.0,
                in_service=(stat == 1),
                name=f"Trafo_{i_bus}_{j_bus}_{parts1[3].strip().strip(chr(39)) if len(parts1) > 3 else ''}",
            )
            count_2w += 1
            i += 4

        except Exception as exc:  # noqa: BLE001
            logger.debug("TRANSFORMER 파싱 오류 (건너뜀): i=%d, error=%s", i, exc)
            i += 1

    logger.info(
        "TRANSFORMER 파싱 완료: 2권선 %d개, 3권선(근사) %d개 생성",
        count_2w, count_3w,
    )


def _build_switched_shunts(
    net: pp.pandapowerNet,
    lines: list[str],
    bus_map: dict[int, int],
    sn_mva: float,
) -> None:
    """SWITCHED SHUNT 섹션을 파싱하여 pandapower shunt를 생성한다.

    PSS/E v33 SWITCHED SHUNT 레코드:
      I, MODSW, ADJM, STAT, VSWHI, VSWLO, SWREM, RMPCT, RMIDNT, BINIT,
      N1, B1, N2, B2, ...

    BINIT: 초기 투입 서셉턴스 (Mvar at V=1pu, 양수=용량성)

    Args:
        net: pandapower 네트워크 (in-place 수정).
        lines: SWITCHED_SHUNT 섹션 라인 리스트.
        bus_map: psse_bus_id → pp_bus_index 매핑.
        sn_mva: 계통 기준 용량 (MVA) — 미사용 (Mvar 단위로 직접 사용).
    """
    count = 0
    for line in lines:
        line = _strip_comment(line)
        if not line or line.startswith("0"):
            continue
        parts = line.split(",")
        if len(parts) < 2:
            continue
        try:
            psse_id = _parse_int(parts[0])
            stat = _parse_int(parts[3]) if len(parts) > 3 else 1
            binit = _parse_float(parts[9]) if len(parts) > 9 else 0.0  # Mvar

            if abs(binit) < 1e-9 or psse_id not in bus_map:
                continue

            pp_bus = bus_map[psse_id]
            # pandapower: q_mvar 양수=inductive, 음수=capacitive
            # PSS/E: BINIT 양수=capacitive → pandapower q_mvar 음수
            pp.create_shunt(
                net,
                bus=pp_bus,
                p_mw=0.0,
                q_mvar=-binit,  # PSS/E capacitive(+) → pandapower capacitive(-) 부호 변환
                in_service=(stat == 1),
                name=f"SwShunt_{psse_id}",
            )
            count += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug("SWITCHED SHUNT 파싱 오류 (건너뜀): line=%r, error=%s", line[:60], exc)

    logger.info("SWITCHED SHUNT 파싱 완료: %d개 shunt 생성", count)


def parse_raw_v33(raw_path: str | Path) -> pp.pandapowerNet:
    """PSS/E v33 .raw 파일을 파싱하여 pandapower 네트워크를 반환한다.

    pandapower 3.x에서 from_psse()가 제거되어 직접 파서 구현.
    IEEE 기준: PSS/E 33 User Manual 참조.

    Args:
        raw_path: .raw 파일 경로 (절대 경로 권장).

    Returns:
        pandapower 네트워크 (from_parameters 방식 생성).

    Raises:
        FileNotFoundError: .raw 파일이 존재하지 않을 때.
        ValueError: 파일 포맷이 PSS/E v33이 아닐 때.
        RuntimeError: 파싱 중 치명적 오류 발생 시.
    """
    path = Path(raw_path)
    if not path.exists():
        raise FileNotFoundError(f".raw 파일 없음: {raw_path}")

    # 헤더에서 버전 확인
    with open(path, encoding="latin-1", errors="replace") as f:
        first_line = f.readline().strip()

    # 기준 용량 (MVA)과 주파수 파싱
    # 헤더 형식: "I, SBASE, REV, XFRRAT, NXFRAT, BASFRQ / comment"
    # 주석('/' 이후) 먼저 제거 후 파싱
    try:
        first_line_clean = _strip_comment(first_line)  # '/' 이후 제거
        header_parts = first_line_clean.split(",")
        sn_mva = _parse_float(header_parts[1]) if len(header_parts) > 1 else 100.0
        raw_version = _parse_int(header_parts[2]) if len(header_parts) > 2 else 33
        hz = _parse_float(header_parts[5]) if len(header_parts) > 5 else 60.0
        if hz <= 0:
            hz = 60.0  # 한국 전력 표준 주파수
    except Exception:
        sn_mva, raw_version, hz = 100.0, 33, 60.0

    if raw_version not in (29, 30, 31, 32, 33, 34):
        logger.warning(
            "PSS/E 버전 %d는 공식 지원 버전(29~34)이 아닙니다. 파싱을 계속 시도합니다.",
            raw_version,
        )

    logger.info(
        "PSS/E .raw 파싱 시작: path=%s, version=%d, sn_mva=%.1f, hz=%.1f",
        path.name, raw_version, sn_mva, hz,
    )

    # pandapower 네트워크 생성
    net = pp.create_empty_network(sn_mva=sn_mva, f_hz=hz)

    # 섹션별 파싱
    sections = _parse_sections(path)

    # 1. 모선
    bus_lines = sections.get("BUS", [])
    if not bus_lines:
        raise RuntimeError(".raw 파일에서 BUS 섹션을 찾지 못했습니다.")
    bus_map = _build_buses(net, bus_lines, sn_mva)

    if not bus_map:
        raise RuntimeError("BUS 섹션 파싱 결과 모선이 0개입니다.")

    # 2. 부하
    _build_loads(net, sections.get("LOAD", []), bus_map)

    # 3. 고정 분로
    _build_fixed_shunts(net, sections.get("FIXED_SHUNT", []), bus_map)

    # 4. 발전기
    _build_generators(net, sections.get("GENERATOR", []), bus_map)

    # 5. 선로
    _build_branches(net, sections.get("BRANCH", []), bus_map, sn_mva)

    # 6. 변압기
    _build_transformers(net, sections.get("TRANSFORMER", []), bus_map, sn_mva)

    # 7. Switched Shunt
    _build_switched_shunts(net, sections.get("SWITCHED_SHUNT", []), bus_map, sn_mva)

    # 슬랙(ext_grid)이 없으면 경고
    if net.ext_grid.empty:
        logger.warning(
            "ext_grid(슬랙 버스)가 없습니다. "
            "IDE=3 버스가 없거나 파싱 오류 가능성. "
            "수동으로 ext_grid를 추가해야 합니다."
        )

    # 직렬 콘덴서(임피던스 요소) 비활성화: pandapower NR에서 수렴 문제 유발
    # Phase 2에서 올바른 직렬 콘덴서 처리로 교체 예정
    if not net.impedance.empty:
        n_impedance = len(net.impedance)
        net.impedance["in_service"] = False
        logger.warning(
            "직렬 콘덴서(impedance 요소) %d개 비활성화 — Phase 2에서 처리 예정.",
            n_impedance,
        )

    # 고립 모선 비활성화 (연결되지 않은 버스)
    _deactivate_isolated_buses(net)

    # 같은 버스의 중복 발전기 병합 (Jacobian 특이값 방지)
    _merge_generators_on_same_bus(net)

    logger.info(
        "PSS/E 파싱 완료: buses=%d, loads=%d, gens=%d, lines=%d, trafos=%d, shunts=%d",
        len(net.bus), len(net.load), len(net.gen) + len(net.ext_grid),
        len(net.line), len(net.trafo), len(net.shunt),
    )

    # 슬랙(ext_grid)이 없으면 경고
    if net.ext_grid.empty:
        logger.warning(
            "ext_grid(슬랙 버스)가 없습니다. "
            "IDE=3 버스가 없거나 파싱 오류 가능성. "
            "수동으로 ext_grid를 추가해야 합니다."
        )

    return net


def _deactivate_isolated_buses(net: pp.pandapowerNet) -> None:
    """연결되지 않은 고립 모선을 비활성화한다.

    pandapower topology 모듈로 연결 컴포넌트를 탐색하여
    주 컴포넌트에 속하지 않는 버스를 in_service=False로 처리.

    Args:
        net: pandapower 네트워크 (in-place 수정).
    """
    try:
        import networkx as nx  # noqa: PLC0415
        import pandapower.topology as top  # noqa: PLC0415

        mg = top.create_nxgraph(net)
        components = list(nx.connected_components(mg))
        if len(components) <= 1:
            return

        main_comp = max(components, key=len)
        n_deactivated = 0
        for bus_idx in net.bus.index:
            if bus_idx not in main_comp and bool(net.bus.at[bus_idx, "in_service"]):
                net.bus.at[bus_idx, "in_service"] = False
                n_deactivated += 1

        if n_deactivated > 0:
            logger.warning(
                "고립 모선 %d개 비활성화 (주 컴포넌트: %d개 버스).",
                n_deactivated, len(main_comp),
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("고립 모선 탐지 실패 (건너뜀): %s", exc)


def _merge_generators_on_same_bus(net: pp.pandapowerNet) -> None:
    """동일 버스에 여러 발전기가 연결된 경우 첫 번째 발전기로 병합한다.

    pandapower의 NR 조류계산에서 같은 버스에 복수의 PV 발전기가 있으면
    Jacobian 특이값 문제가 발생할 수 있다.
    유효전력·무효전력 한계를 합산하고 나머지를 제거한다.

    Args:
        net: pandapower 네트워크 (in-place 수정).
    """
    from collections import Counter  # noqa: PLC0415

    bus_gen_count = Counter(int(b) for b in net.gen.bus.values)
    merged_count = 0

    for bus, count in bus_gen_count.items():
        if count <= 1:
            continue
        gen_idxs = list(net.gen[net.gen.bus == bus].index)
        if len(gen_idxs) < 2:
            continue

        total_p = float(net.gen.loc[gen_idxs, "p_mw"].sum())
        total_max_q = float(net.gen.loc[gen_idxs, "max_q_mvar"].sum())
        total_min_q = float(net.gen.loc[gen_idxs, "min_q_mvar"].sum())
        vm_pu = float(net.gen.at[gen_idxs[0], "vm_pu"])

        net.gen.at[gen_idxs[0], "p_mw"] = total_p
        net.gen.at[gen_idxs[0], "max_q_mvar"] = total_max_q
        net.gen.at[gen_idxs[0], "min_q_mvar"] = total_min_q
        net.gen.at[gen_idxs[0], "vm_pu"] = vm_pu
        net.gen.drop(gen_idxs[1:], inplace=True)
        merged_count += len(gen_idxs) - 1

    if merged_count > 0:
        logger.info(
            "동일 버스 발전기 병합: %d개 제거 (남은 발전기: %d개).",
            merged_count, len(net.gen),
        )
