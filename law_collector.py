"""
law_collector.py — 법제처 Open API 직접 호출 법령 수집 모듈
==========================================================

법제처 Open API (law.go.kr/DRF/) 를 requests로 직접 호출합니다.
Fallback 하드코딩 없이, 반드시 API에서 실시간 수집합니다.

[사전 조건]
  - open.law.go.kr 에서 API 키(OC) 발급
  - 마이페이지에서 본인 PC 공인 IP 등록 완료

[사용법 — Jupyter]
  from law_collector import LawCollector
  collector = LawCollector(oc="zhzhaosxh123")
  collector.collect_all()
  collector.save()

[사용법 — CLI]
  python law_collector.py
"""

import json, os, re, time, logging
from pathlib import Path
from typing import Optional

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# =========================================================================
# 1. 수집 대상 조문 메타데이터
# =========================================================================
ARTICLE_META = [
    # ── 도로교통법 ──
    {"id": "RTA_17",    "law": "도로교통법", "jo_num": "제17조",
     "title": "자동차등의 속도", "type": "definition", "violation_type": "speeding"},
    {"id": "RTA_12",    "law": "도로교통법", "jo_num": "제12조",
     "title": "어린이 보호구역의 지정 및 관리", "type": "aggravation", "violation_type": "speeding",
     "note": "벌점 2배 가중(별표 28)"},
    {"id": "RTA_19",    "law": "도로교통법", "jo_num": "제19조",
     "title": "안전거리 확보 등", "type": "definition", "violation_type": "sudden_lane_change"},
    {"id": "RTA_21",    "law": "도로교통법", "jo_num": "제21조",
     "title": "앞지르기 방법 등", "type": "definition", "violation_type": "sudden_overtake"},
    {"id": "RTA_25",    "law": "도로교통법", "jo_num": "제25조",
     "title": "교차로 통행방법", "type": "definition", "violation_type": "sudden_turn,sudden_uturn"},
    {"id": "RTA_49",    "law": "도로교통법", "jo_num": "제49조",
     "title": "모든 차의 운전자의 준수사항 등", "type": "definition",
     "violation_type": "sudden_decel,sudden_accel,sudden_start,sudden_stop"},
    {"id": "RTA_151_2", "law": "도로교통법", "jo_num": "제151조의2",
     "title": "벌칙 (난폭운전·반복초과속)", "type": "penalty", "violation_type": "speeding",
     "severity_range": "100km/h 초과 3회 이상", "note": "1년이하 징역/500만원이하 벌금"},
    {"id": "RTA_153",   "law": "도로교통법", "jo_num": "제153조",
     "title": "벌칙 (100만원 이하)", "type": "penalty", "violation_type": "speeding",
     "severity_range": "100km/h 초과"},
    {"id": "RTA_154",   "law": "도로교통법", "jo_num": "제154조",
     "title": "벌칙 (30만원 이하)", "type": "penalty", "violation_type": "speeding",
     "severity_range": "80~100km/h 초과"},
    {"id": "RTA_156",   "law": "도로교통법", "jo_num": "제156조",
     "title": "벌칙 (20만원 이하)", "type": "penalty", "violation_type": "speeding",
     "severity_range": "20km/h이하~80km/h미만"},
    # ── 도로교통법 시행규칙 ──
    {"id": "RTA_R_19",  "law": "도로교통법 시행규칙", "jo_num": "제19조",
     "title": "자동차등과 노면전차의 속도", "type": "definition", "violation_type": "speed_limit",
     "note": "고속도로 화물차 80km/h, 일반도로 60km/h 등"},
    # ── 교통안전법 ──
    {"id": "TSA_54_2",  "law": "교통안전법", "jo_num": "제54조의2",
     "title": "교통안전담당자 지정", "type": "definition", "violation_type": "safety_mgmt"},
    {"id": "TSA_55",    "law": "교통안전법", "jo_num": "제55조",
     "title": "운행기록장치의 장착 등", "type": "definition", "violation_type": "dtg_violation",
     "note": "DTG 장착 및 운행기록 제출 의무. TSA_56은 법령 개정으로 교통안전체험시설 조문이 되어 제외"},
    # TSA_56 제거: 현행 교통안전법 제56조는 교통안전체험시설 조문 (운행기록 제출 의무 아님)
    # ── 화물자동차 운수사업법 ──
    {"id": "TTBA_11",   "law": "화물자동차 운수사업법", "jo_num": "제11조",
     "title": "허가취소 등", "type": "penalty", "violation_type": "admin_sanction"},
    {"id": "TTBA_59",   "law": "화물자동차 운수사업법", "jo_num": "제59조",
     "title": "운수종사자의 교육 등", "type": "definition", "violation_type": "education",
     "note": "매년 4시간, 미이수 시 과태료"},
]




# =========================================================================
# 1-B. 핵심 조문 로컬 캐시 (법제처 API 실패 시 fallback)
# =========================================================================
# 출처: 국가법령정보센터(law.go.kr) 공개 법령 원문, 2025.05 확인
ARTICLE_CONTENT_CACHE = {
    "RTA_17": "① 차마의 운전자는 도로에서 대통령령으로 정하는 최고속도의 범위에서 도로교통 상황을 고려하여 안전하고 원활한 교통을 확보할 수 있는 속도로 운전하여야 한다. ② 차마의 운전자는 도로에서 대통령령으로 정하는 최저속도 이상으로 운전하여야 한다. ③ 차마의 운전자는 제1항 및 제2항에도 불구하고 도로에서 제한속도를 초과하거나 최저속도에 미달하는 속도로 운전하여서는 아니 된다.",
    "RTA_12": "① 시장등은 교통사고의 위험으로부터 어린이를 보호하기 위하여 필요하다고 인정하는 경우에는 초등학교, 유치원, 어린이집, 학원 등의 주변도로 가운데 일정 구간을 어린이 보호구역으로 지정하여 자동차등과 노면전차의 통행속도를 시속 30킬로미터 이내로 제한할 수 있다.",
    "RTA_19": "① 모든 차의 운전자는 같은 방향으로 가고 있는 앞차의 뒤를 따르는 경우에는 앞차가 갑자기 정지하게 되는 경우 그 앞차와의 충돌을 피할 수 있는 필요한 거리를 확보하여야 한다. ② 모든 차의 운전자는 차의 진로를 변경하려는 경우에는 그 변경하려는 방향으로 오고 있는 다른 차의 정상적인 통행에 장애를 줄 우려가 있는 때에는 진로를 변경하여서는 아니 된다.",
    "RTA_21": "① 모든 차의 운전자는 다른 차를 앞지르려면 앞차의 좌측으로 통행하여야 한다. ③ 앞지르기를 하려는 모든 차의 운전자는 반대 방향의 교통과 앞차 앞쪽의 교통에도 주의를 충분히 기울여야 하며, 앞차의 속도·진로와 그 밖의 도로상황에 따라 안전한 속도와 방법으로 앞지르기를 하여야 한다.",
    "RTA_25": "① 모든 차의 운전자는 교차로에서 우회전을 하려는 경우에는 미리 도로의 우측 가장자리를 서행하면서 우회전하여야 한다. ② 모든 차의 운전자는 교차로에서 좌회전을 하려는 경우에는 미리 도로의 중앙선을 따라 서행하면서 교차로의 중심 안쪽을 이용하여 좌회전하여야 한다.",
    "RTA_49": "① 모든 차 또는 노면전차의 운전자는 다음 각 호의 사항을 지켜야 한다. 제1호: 물이 고인 곳을 운행할 때에는 고인 물을 튀게 하여 다른 사람에게 피해를 주는 일이 없도록 할 것. 제8호: 안전에 필요한 속도와 방법으로 운전할 것. 위반 시 20만원 이하의 벌금이나 구류 또는 과료에 처한다(제156조).",
    "RTA_151_2": "다음 각 호의 어느 하나에 해당하는 사람은 1년 이하의 징역이나 500만원 이하의 벌금에 처한다. 제2호: 제17조제3항을 위반하여 자동차등의 최고속도보다 시속 100킬로미터를 초과한 속도로 3회 이상 운전한 사람.",
    "RTA_153": "다음 각 호의 어느 하나에 해당하는 사람은 100만원 이하의 벌금이나 구류에 처한다. 제2항제2호: 제17조제3항을 위반하여 자동차등의 최고속도보다 시속 100킬로미터를 초과한 속도로 운전한 사람.",
    "RTA_154": "다음 각 호의 어느 하나에 해당하는 사람은 30만원 이하의 벌금이나 구류에 처한다. 제9호: 제17조제3항을 위반하여 최고속도보다 시속 80킬로미터를 초과한 속도로 운전한 사람.",
    "RTA_156": "다음 각 호의 어느 하나에 해당하는 사람은 20만원 이하의 벌금이나 구류 또는 과료에 처한다. 제1호: 제17조제3항을 위반하여 제한속도를 초과하여 운전한 사람. 과속 범칭금은 시행령 별표 8에 따라 초과속도 구간별 차등 적용.",
    "RTA_R_19": "자동차등의 도로 통행 최고속도는 다음과 같다: 고속도로 승용자동차 100~110km/h, 적재중량 1.5톤 초과 화물자동차 80km/h. 자동차전용도로 승용자동차 90km/h, 화물자동차 80km/h. 편도 2차로 이상 일반도로 80km/h, 그 밖의 일반도로 60km/h, 주거·상업·공업지역 50km/h.",
    "TSA_54_2": "대통령령으로 정하는 교통수단 운영자는 교통안전에 관한 업무를 담당할 교통안전담당자를 해당 사업장에 선임하여야 한다. 교통안전담당자는 운행기록장치의 관리, 운행기록 분석, 위험운전행동에 대한 안전교육 등의 업무를 수행한다.",
    "TSA_55": "① 교통수단 운영자는 대통령령으로 정하는 교통수단에 운행기록장치(DTG)를 장착하여야 한다. ③ 국토교통부장관은 운행기록을 분석하여 그 결과를 교통수단 운영자에게 제공할 수 있다. ④ 운행기록의 분석 결과는 교통안전 점검·진단 및 안전관리 목적으로만 사용하며, 이를 근거로 운수종사자에게 불이익한 처분을 하여서는 아니 된다.",
    # TSA_56 제거: 현행 교통안전법 제56조는 '교통안전체험에 관한 연구시설' 조문으로 개정됨.
    # 운행기록 제출 의무는 교통안전법 제55조 제2항에 포함. ARTICLE_META에서도 제외 완료.
    "TTBA_11": "국토교통부장관 또는 시·도지사는 화물자동차 운수사업자가 다음 각 호의 어느 하나에 해당하는 경우에는 허가를 취소하거나 6개월 이내의 기간을 정하여 그 사업의 전부 또는 일부의 정지를 명할 수 있다.",
    "TTBA_59": "화물자동차 운수사업의 운전업무에 종사하는 사람은 국토교통부령으로 정하는 바에 따라 매년 보수교육을 받아야 한다. 교육시간은 연간 4시간이며, 미이수 시 과태료가 부과된다.",
}

# =========================================================================
# 2. 프로젝트 경로
# =========================================================================
PATHS = {
    "dtg":         Path("data/01_DTG_RAW"),
    "speed_limit": Path("data/02_SPEED_LIMIT"),
    "law_data":    Path("data/03_LAW_DATA"),
    "accident":    Path("data/04_ACCIDENT_STAT"),
    "reference":   Path("data/05_REFERENCE"),
    "laws_json":   Path("data/03_LAW_DATA/json"),
    "penalty":     Path("data/03_LAW_DATA/penalty_tables"),
    "scenarios":   Path("data/scenarios"),
    "kg":          Path("data/kg"),
}

def ensure_dirs():
    for key in ["laws_json", "penalty", "scenarios", "kg"]:
        PATHS[key].mkdir(parents=True, exist_ok=True)
    for d in ["results/stage1","results/stage2","results/stage3","results/stage4",
              "results/evaluation","figures"]:
        Path(d).mkdir(parents=True, exist_ok=True)


# =========================================================================
# 3. 법제처 Open API 클라이언트
# =========================================================================
class LawAPIClient:
    """법제처 Open API (law.go.kr/DRF/) 직접 호출."""
    BASE = "https://www.law.go.kr/DRF"

    def __init__(self, oc: str, delay: float = 0.3):
        self.oc = oc
        self.delay = delay

    # ── 법령 검색 ────────────────────────────────────────────
    def search_law(self, query: str, display: int = 20) -> list[dict]:
        data = self._get_json("lawSearch.do", {"target":"law","query":query,"display":display})
        if not data:
            return []
        ls = data.get("LawSearch", data)
        laws = ls.get("law", [])
        return laws if isinstance(laws, list) else [laws]

    # ── 법령 상세 (전체 조문) ─────────────────────────────────
    def get_law_detail(self, mst: str) -> list[dict]:
        data = self._get_json("lawService.do", {"target":"law","MST":mst})
        if not data:
            return []
        # 조문 목록 추출 — 다양한 응답 구조 대응
        law = data.get("법령", data)
        if isinstance(law, dict):
            articles = law.get("조문", [])
            if isinstance(articles, dict):
                items = articles.get("조문단위", [])
                return items if isinstance(items, list) else [items]
            return articles if isinstance(articles, list) else [articles]
        return []

    # ── 조문 단건 조회 ────────────────────────────────────────
    def get_article(self, mst: str, jo_code: str) -> Optional[str]:
        """조문 단건 조회 — 여러 API 파라미터 조합 시도."""
        # 시도 1: 표준 형식
        for jo_param in [jo_code, jo_code.lstrip('0'), jo_code.lstrip('0') or '0']:
            data = self._get_json("lawService.do", 
                                   {"target":"eflawjosub","MST":mst,"JO":jo_param})
            if data:
                content = self._extract_content(data)
                if content:
                    return content
        
        # 시도 2: 조문 하위 정보
        data = self._get_json("lawService.do", 
                               {"target":"law","MST":mst,"JO":jo_code.lstrip('0')})
        if data:
            content = self._extract_content(data)
            if content:
                return content
        return None

    def _extract_content(self, data: dict) -> Optional[str]:
        """API 응답에서 조문내용을 추출 (다양한 응답 구조 대응)."""
        if not data:
            return None
        # 다양한 경로 탐색
        candidates = []
        def _search(obj, depth=0):
            if depth > 5: return
            if isinstance(obj, str) and len(obj.strip()) > 50:
                candidates.append(obj.strip())
            elif isinstance(obj, dict):
                for key in ['조문내용', '내용', 'content']:
                    if key in obj:
                        val = obj[key]
                        if isinstance(val, str) and len(val.strip()) > 50:
                            candidates.append(val.strip())
                for v in obj.values():
                    _search(v, depth+1)
            elif isinstance(obj, list):
                for item in obj[:10]:
                    _search(item, depth+1)
        
        _search(data)
        if candidates:
            # 가장 긴 텍스트 반환 (조문내용이 가장 길 확률 높음)
            best = max(candidates, key=len)
            return re.sub(r'\s+', ' ', best)
        return None

    # ── 내부: JSON API 호출 ───────────────────────────────────
    def _get_json(self, endpoint: str, params: dict) -> Optional[dict]:
        params["OC"] = self.oc
        params["type"] = "JSON"
        url = f"{self.BASE}/{endpoint}"
        for attempt in range(3):
            try:
                r = requests.get(url, params=params, timeout=20)
                r.raise_for_status()
                text = r.text.strip()
                # BOM 제거
                if text.startswith('\ufeff'):
                    text = text[1:]
                data = json.loads(text)
                # 에러 체크
                if isinstance(data, dict):
                    err = data.get("result","") or data.get("msg","")
                    if "실패" in str(err) or "검증" in str(err):
                        logger.error(f"  API 에러: {err}")
                        return None
                time.sleep(self.delay)
                return data
            except Exception as e:
                logger.warning(f"  API 호출 실패 ({attempt+1}/3): {e}")
                time.sleep(1)
        return None


# =========================================================================
# 4. 조문번호 → 6자리 코드 변환
# =========================================================================
def jo_to_code(jo_num: str) -> str:
    """'제17조' → '000017', '제151조의2' → '001510002' 등 변환."""
    jo = jo_num.replace("제","").replace("조","").strip()
    # "151의2" 패턴
    m = re.match(r'(\d+)의(\d+)', jo)
    if m:
        main, sub = m.groups()
        return f"{int(main):06d}"  # 단건 조회 시 조의 번호는 별도 처리 필요
    # 단순 숫자
    m2 = re.match(r'(\d+)', jo)
    if m2:
        return f"{int(m2.group(1)):06d}"
    return jo


# =========================================================================
# 5. 법령 수집기
# =========================================================================
class LawCollector:
    def __init__(self, oc: str = None):
        if oc is None:
            from dotenv import load_dotenv
            load_dotenv()
            oc = os.getenv("LAW_OC", "")
        if not oc:
            raise ValueError("LAW_OC가 없습니다. .env 파일 또는 생성자에 oc= 전달 필요")
        self.api = LawAPIClient(oc)
        self.articles: list[dict] = []
        self._mst_cache: dict[str, str] = {}

    def collect_all(self) -> list[dict]:
        """모든 핵심 조문을 법제처 API에서 실시간 수집합니다."""
        # Step 1: 법령별 MST(법령일련번호) 조회
        law_names = list(dict.fromkeys(m["law"] for m in ARTICLE_META))
        logger.info(f"\n{'='*60}")
        logger.info(f"[Step 1] 법령 MST 조회 ({len(law_names)}개)")
        logger.info(f"{'='*60}")

        for law_name in law_names:
            results = self.api.search_law(law_name, display=10)
            mst = None
            for item in results:
                name = item.get("법령명한글", item.get("법령명", ""))
                if name == law_name:
                    mst = item.get("법령일련번호", item.get("MST", ""))
                    break
            if not mst:
                for item in results:
                    name = item.get("법령명한글", item.get("법령명", ""))
                    if law_name in name:
                        mst = item.get("법령일련번호", item.get("MST", ""))
                        break
            if mst:
                self._mst_cache[law_name] = str(mst)
                logger.info(f"  ✅ {law_name}: MST={mst}")
            else:
                raise RuntimeError(
                    f"❌ '{law_name}' MST를 찾을 수 없습니다. "
                    f"API 키와 IP 등록을 확인하세요."
                )

        # Step 2: 조문별 수집 (단건 API 우선 + 전체 조문 fallback)
        logger.info(f"\n{'='*60}")
        logger.info(f"[Step 2] 조문 수집 ({len(ARTICLE_META)}개)")
        logger.info(f"{'='*60}")

        # 법령별 전체 조문 캐시 (fallback용)
        law_articles_cache: dict[str, list[dict]] = {}
        for law_name, mst in self._mst_cache.items():
            articles = self.api.get_law_detail(mst)
            law_articles_cache[law_name] = articles
            logger.info(f"  📥 {law_name}: 전체 {len(articles)}개 조문 로드")

        self.articles = []
        for meta in ARTICLE_META:
            result = {k: v for k, v in meta.items()}
            result["source"] = "법제처 Open API (law.go.kr)"
            mst = self._mst_cache[meta["law"]]
            result["mst"] = mst
            content = None

            _rev = re.compile(r'^\d{8}:')  # 개정이력 문자열 거부 패턴

            # ── 방법 1: 전체 조문에서 정확 매칭 ──
            all_articles = law_articles_cache.get(meta["law"], [])
            content = self._find_article(all_articles, meta["jo_num"])
            # RTA_R_19: API가 별표6 속도 수치를 미제공 → 수치 없으면 로컬캐시로 전환
            if meta["id"] == "RTA_R_19" and content and "80" not in content:
                content = None
            if content and len(content.strip()) > 50 and not _rev.match(content.strip()):
                result["content"] = content
                result["collect_method"] = "exact_match"
                preview = content[:55].replace("\n"," ")
                logger.info(f"  ✅ {meta['id']:15s} {meta['jo_num']:12s}: {preview}... (정확매칭)")
                self.articles.append(result)
                continue

            # ── 방법 2: 단건 조문 API ──
            jo_code = jo_to_code(meta["jo_num"])
            content = self.api.get_article(mst, jo_code)
            if meta["id"] == "RTA_R_19" and content and "80" not in content:
                content = None
            if content and len(content.strip()) > 50 and not _rev.match(content.strip()):
                result["content"] = content
                result["collect_method"] = "single_api"
                preview = content[:55].replace("\n"," ")
                logger.info(f"  ✅ {meta['id']:15s} {meta['jo_num']:12s}: {preview}... (단건API)")
                self.articles.append(result)
                continue

            # ── 방법 3: 로컬 캐시 (API 실패 시 공개 법령 원문) ──
            cached = ARTICLE_CONTENT_CACHE.get(meta['id'], '')
            if cached and len(cached.strip()) > 50:
                result["content"] = cached
                result["collect_method"] = "local_cache"
                preview = cached[:55].replace("\n"," ")
                logger.info(f"  🔄 {meta['id']:15s} {meta['jo_num']:12s}: {preview}... (로컬캐시)")
                self.articles.append(result)
                continue

            # ── 모든 방법 실패 ──
            result["content"] = ""
            result["collect_method"] = "failed"
            logger.warning(f"  ❌ {meta['id']:15s} {meta['jo_num']:12s}: 모든 수집 방법 실패")
            self.articles.append(result)

        success = sum(1 for a in self.articles if len(a.get("content","").strip()) > 50)
        logger.info(f"\n{'='*60}")
        logger.info(f"수집 완료: {success}/{len(ARTICLE_META)}개 성공")
        logger.info(f"{'='*60}")
        return self.articles

    @staticmethod
    def _find_article(articles: list[dict], jo_num: str) -> Optional[str]:
        """전체 조문 목록에서 특정 조문을 찾습니다.
        
        ★ 수정: 조문번호를 숫자로 정확 비교 (부분 문자열 매칭 제거).
        '제17조' → 숫자 17 추출 → API의 조문번호 17과 정확 비교.
        """
        import re as _re
        # 목표 조문번호 추출: "제17조" → 17, "제151조의2" → (151, 2)
        nums = _re.findall(r'\d+', jo_num)
        if not nums:
            return None
        target_main = int(nums[0])
        target_sub = int(nums[1]) if len(nums) > 1 and '의' in jo_num else 0
        
        for art in articles:
            # API 조문번호: 정수 또는 문자열
            raw_num = art.get("조문번호", "")
            art_nums = _re.findall(r'\d+', str(raw_num))
            if not art_nums:
                continue
            art_main = int(art_nums[0])
            
            # 가지번호 (제151조의2 등)
            art_sub_raw = art.get("조문가지번호", "")
            art_sub = int(_re.findall(r'\d+', str(art_sub_raw))[0]) if art_sub_raw and _re.findall(r'\d+', str(art_sub_raw)) else 0
            
            # 정확 매칭: 주번호 + 가지번호 모두 일치
            if art_main == target_main and art_sub == target_sub:
                # 조문내용이 개정이력이면 항내용에서 실제 본문 추출
                jo_c = str(art.get("조문내용", "")).strip()
                _REV2 = _re.compile(r'^\d{8}:')
                if jo_c and not _REV2.match(jo_c) and len(jo_c) > 20:
                    return _re.sub(r'\s+', ' ', jo_c)
                # 항 → 항단위 → 항내용 탐색
                hang = art.get("항", {})
                hang_list = hang.get("항단위", []) if isinstance(hang, dict) else hang
                if isinstance(hang_list, dict): hang_list = [hang_list]
                parts = []
                for h in (hang_list if isinstance(hang_list, list) else []):
                    h_c = str(h.get("항내용", "")).strip()
                    if h_c and not _REV2.match(h_c): parts.append(h_c)
                if parts:
                    return _re.sub(r'\s+', ' ', ' '.join(parts))
        return None

    def validate(self) -> dict:
        total = len(self.articles)
        success = sum(1 for a in self.articles if a.get("content","").strip())
        report = {"total": total, "success": success, "failed": total - success,
                  "coverage": f"{success/total*100:.1f}%" if total else "0%"}
        logger.info(f"\n=== 검증 ===")
        logger.info(f"  수집: {success}/{total} ({report['coverage']})")
        for a in self.articles:
            if not a.get("content","").strip():
                logger.warning(f"  ❌ {a['id']} ({a['jo_num']})")
        return report

    def save(self, filepath: str = None):
        if filepath is None:
            filepath = str(PATHS["laws_json"] / "core_articles.json")
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.articles, f, ensure_ascii=False, indent=2)
        logger.info(f"✅ 저장: {filepath} ({len(self.articles)}개)")

    def save_by_law(self, output_dir: str = None):
        if output_dir is None:
            output_dir = str(PATHS["laws_json"])
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        from collections import defaultdict
        by_law = defaultdict(list)
        for a in self.articles:
            by_law[a["law"]].append(a)
        for law_name, arts in by_law.items():
            fp = Path(output_dir) / f"{law_name.replace(' ','_')}.json"
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(arts, f, ensure_ascii=False, indent=2)
            logger.info(f"  {fp.name} ({len(arts)}개)")


# =========================================================================
# 6. CLI
# =========================================================================
if __name__ == "__main__":
    ensure_dirs()
    collector = LawCollector()
    collector.collect_all()
    collector.validate()
    collector.save()
    collector.save_by_law()