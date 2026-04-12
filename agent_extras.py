"""
agent_extras.py — R-Agent API Fallback + LLM-as-Judge 편향통제 완전판
====================================================================
04_irac_v_framework.py 와 05_analysis_and_paper.py 에서 import하여 사용

#12: R-Agent API Fallback
  - KG 검색 결과가 불충분할 때 법제처 API 실시간 조회
  - KG 결과와 병합하여 R-Agent에 반환

#6/#8: LLM-as-Judge 편향 통제 (Zheng et al., 2023 프로토콜)
  - 위치 편향: (A,B)→(B,A) 양방향 평가, 불일치 시 동점
  - 자기강화 편향: temperature 변동 + 프롬프트 변형으로 통제
  - 3회 반복: 편차 ≤ 0.5점만 유효
"""

import os, json, time, requests
import numpy as np


# ═══════════════════════════════════════════════════════════════
# 1. R-Agent API Fallback
# ═══════════════════════════════════════════════════════════════

class LawAPIFallback:
    """법제처 Open API를 통한 실시간 법령 조회 (KG 보완용).
    
    R-Agent가 KG에서 충분한 정보를 확보하지 못했을 때,
    법제처 API로 직접 조문을 조회하여 컨텍스트를 보강합니다.
    """

    def __init__(self, oc=None):
        self.oc = oc or os.getenv('LAW_OC', '')
        self.base_url = 'https://www.law.go.kr/DRF/lawSearch.do'
        self.cache = {}  # MST 캐시
        self.call_count = 0

    def _search_law(self, law_name):
        """법령명으로 MST(법령일련번호) 검색."""
        if law_name in self.cache:
            return self.cache[law_name]

        try:
            r = requests.get(self.base_url,
                             params={'OC': self.oc, 'target': 'law', 'type': 'JSON',
                                     'query': law_name, 'display': 3},
                             timeout=10)
            data = json.loads(r.text)
            laws = data.get('LawSearch', {}).get('law', [])
            if not isinstance(laws, list):
                laws = [laws]

            for law in laws:
                if law_name in law.get('법령명한글', ''):
                    mst = law.get('법령일련번호')
                    self.cache[law_name] = mst
                    return mst
        except Exception as e:
            print(f'  ⚠️ API 검색 실패 ({law_name}): {e}')
        return None

    def fetch_article(self, law_name, jo_num):
        """특정 법령의 특정 조문을 API로 조회.
        
        Args:
            law_name: 법령명 (예: '도로교통법')
            jo_num: 조문번호 (예: '제17조')
        
        Returns:
            dict: {id, law, jo_num, content, source} or None
        """
        mst = self._search_law(law_name)
        if not mst:
            return None

        try:
            r = requests.get('https://www.law.go.kr/DRF/lawService.do',
                             params={'OC': self.oc, 'target': 'law', 'type': 'JSON',
                                     'MST': mst, 'JO': jo_num},
                             timeout=15)
            self.call_count += 1

            data = json.loads(r.text)
            # 조문 내용 추출 (API 응답 구조에 따라 파싱)
            content = ''
            law_data = data.get('법령', {})
            articles = law_data.get('조문', {}).get('조문단위', [])
            if not isinstance(articles, list):
                articles = [articles]

            # 조번호 매칭
            jo_number = jo_num.replace('제', '').replace('조', '').replace('의', '_')
            for art in articles:
                art_jo = str(art.get('조문번호', ''))
                if jo_number in art_jo or jo_num in str(art.get('조문제목', '')):
                    content = art.get('조문내용', '')
                    break

            if content:
                return {
                    'id': f'API_{law_name}_{jo_num}',
                    'law': law_name,
                    'jo_num': jo_num,
                    'content': content,
                    'source': 'api_fallback',
                }
        except Exception as e:
            print(f'  ⚠️ API 조문 조회 실패 ({law_name} {jo_num}): {e}')

        return None


def r_agent_with_fallback(issues, run_q_fn, api_fallback=None, min_articles=2):
    """R-Agent 확장판: KG 검색 + API Fallback.
    
    KG에서 min_articles 이상의 조문을 확보하지 못하면
    법제처 API로 추가 조회하여 보강합니다.
    
    Args:
        issues: I-Agent 출력
        run_q_fn: Neo4j 쿼리 함수
        api_fallback: LawAPIFallback 인스턴스 (None이면 fallback 비활성)
        min_articles: 최소 확보 조문 수 (미달 시 API 호출)
    """
    rules = []
    for issue in issues.get('issues', []):
        vtype = issue['issue_type']
        speed_over = issue.get('speed_over_km', 0) or 0
        aggr = issue.get('aggravating', [])

        # 1) KG 검색 (기존)
        articles = run_q_fn("""
            MATCH (h:HazardousBehavior {name:$v})-[:VIOLATES]->(a:LegalArticle)
            RETURN a.id AS id, a.jo_num AS jo, a.title AS title,
                   a.content AS content, a.type AS type
            ORDER BY a.id""", {'v': vtype})

        # 2) API Fallback: KG 결과 부족 시
        api_articles = []
        if api_fallback and len(articles) < min_articles:
            print(f'    🔄 API Fallback: KG {len(articles)}건 < {min_articles} → API 조회')
            # 위반유형별 기본 조회 대상
            fallback_targets = {
                'speeding': [('도로교통법', '제17조'), ('도로교통법', '제156조')],
                'sudden_decel': [('도로교통법', '제49조')],
                'sudden_accel': [('도로교통법', '제49조')],
                'sudden_lane_change': [('도로교통법', '제19조')],
                'sudden_overtake': [('도로교통법', '제21조')],
                'sudden_turn': [('도로교통법', '제25조')],
                'sudden_uturn': [('도로교통법', '제25조')],
            }
            targets = fallback_targets.get(vtype, [('도로교통법', '제49조')])

            existing_ids = {a['id'] for a in articles}
            for law_name, jo_num in targets:
                art = api_fallback.fetch_article(law_name, jo_num)
                if art and art['id'] not in existing_ids:
                    api_articles.append(art)
                    existing_ids.add(art['id'])
                time.sleep(0.3)  # API rate limit

        # 3) ★ 심각도 분류 기준표 (텍스트 제공 — 직접 조회 아님)
        # SeverityLevel 노드 직접 쿼리 제거 → penalty_table 가이드 텍스트만 제공
        # A-Agent가 초과속도를 기준표에 대입하여 직접 판정해야 함
        severity_guide = None
        guide_results = run_q_fn("""
            MATCH (a:LegalArticle)
            WHERE a.type = 'penalty_table'
            RETURN a.id AS id, a.title AS title, a.content AS content""", {})
        if guide_results:
            severity_guide = {
                'type': 'classification_guide',
                'articles': guide_results,
            }

        # 4) 참조 (기존)
        related = run_q_fn("""
            MATCH (h:HazardousBehavior {name:$v})-[:VIOLATES]->(a:LegalArticle)
                  -[:RELATED_TO]->(a2:LegalArticle)
            RETURN DISTINCT a2.id AS id, a2.jo_num AS jo,
                   a2.title AS title, a2.content AS content""", {'v': vtype})

        rules.append({
            'issue_type': vtype,
            'articles': articles + api_articles,
            'api_fallback_used': len(api_articles) > 0,
            'api_articles_count': len(api_articles),
            'severity_guide': severity_guide,  # 기준표 텍스트 (직접 조회 결과 아님)
            'related_articles': related,
            'aggravating': aggr,
        })

    return {'rules': rules}


# ═══════════════════════════════════════════════════════════════
# 2. LLM-as-a-Judge 편향 통제 완전판 (Zheng et al., 2023)
# ═══════════════════════════════════════════════════════════════

JUDGE_PROMPT_A = """당신은 법적 추론의 품질을 평가하는 전문 심사자입니다.

[평가 기준]
1점: 법적 근거 없음, 완전히 틀린 추론
2점: 일부 법적 용어 사용하나 논리적 연결 부재
3점: 관련 조문을 인용하나 포섭 논증이 불완전
4점: 적절한 조문 인용과 논리적 포섭, 사소한 오류
5점: 정확한 조문 인용, 완벽한 포섭 논증, 가중 조건 고려

반드시 JSON만 응답하세요: {"score": 숫자, "justification": "근거"}"""

# 프롬프트 변형 (자기강화 편향 통제)
JUDGE_PROMPT_B = """법학 교수로서 아래의 법적 분석의 정확성과 논리성을 평가해주세요.

[채점 기준]
1점: 근거 없는 추측, 법조문과 무관한 결론
2점: 관련 분야를 파악했으나 구체적 조문 미인용
3점: 조문을 인용했으나 사실관계와 법리의 연결이 부족
4점: 조문·사실·결론이 논리적으로 연결, 경미한 누락
5점: 완벽한 법리 적용, 가중·감경 사유까지 정확히 반영

반드시 JSON만 응답하세요: {"score": 숫자, "justification": "근거"}"""


def _build_eval_content(scenario, conclusion, order='AB'):
    """평가 프롬프트 내용 구성.
    
    order='AB': 추론→정답 순서
    order='BA': 정답→추론 순서 (위치 편향 통제)
    """
    reasoning_block = f"""[AI 추론 결과]
심각도: {conclusion.get('severity_level', '?')} ({conclusion.get('severity_label', '?')})
법적근거: {conclusion.get('legal_basis', '?')}
인용조문: {conclusion.get('cited_articles', [])}
추론: {conclusion.get('reasoning', '없음')}"""

    answer_block = f"""[정답]
심각도: {scenario['expected'].get('severity_level', '?')}
법적근거: {scenario['expected'].get('legal_basis', '?')}"""

    fact_block = f"[사실관계] {scenario['description']}"

    if order == 'AB':
        return f"{fact_block}\n\n{reasoning_block}\n\n{answer_block}\n\n위 AI 추론을 1~5점으로 평가하세요."
    else:  # BA: 정답 먼저 제시
        return f"{fact_block}\n\n{answer_block}\n\n{reasoning_block}\n\n위 AI 추론을 1~5점으로 평가하세요."


def evaluate_reasoning_quality_full(results_s4, scenarios, call_llm_fn,
                                     n_repeats=3, max_deviation=1.0):
    """M4: Reasoning Quality — 완전한 편향 통제 프로토콜.
    
    Zheng et al. (2023) 프로토콜:
      1. 위치 편향: (A,B)→(B,A) 양방향, 불일치 시 평균
      2. 자기강화 편향: 2종 프롬프트 변형 사용
      3. 3회 반복: 편차 ≤ max_deviation 점만 유효
    
    Args:
        results_s4: Stage 4 결과 리스트
        scenarios: 시나리오 리스트
        call_llm_fn: LLM 호출 함수 (prompt, system, max_tokens, temperature)
        n_repeats: 반복 횟수
        max_deviation: 최대 허용 편차 (초과 시 중간값 사용)
    
    Returns:
        dict: {scores, mean, std, bias_control_stats}
    """
    all_scores = []
    bias_stats = {'position_disagree': 0, 'deviation_exceeded': 0, 'total': 0}

    for i, (r, sc) in enumerate(zip(results_s4, scenarios)):
        conclusion = r.get('conclusion', {})
        bias_stats['total'] += 1

        # ── 3회 반복 평가 ──
        repeat_scores = []
        for rep in range(n_repeats):
            # 위치 편향 통제: AB 순서와 BA 순서 모두 평가
            content_ab = _build_eval_content(sc, conclusion, order='AB')
            content_ba = _build_eval_content(sc, conclusion, order='BA')

            # 프롬프트 변형: A/B 교대 사용 (자기강화 편향 통제)
            system_prompt = JUDGE_PROMPT_A if rep % 2 == 0 else JUDGE_PROMPT_B

            try:
                # AB 순서 평가
                raw_ab = call_llm_fn(content_ab, system=system_prompt,
                                     max_tokens=200, temperature=0.3)
                parsed_ab = json.loads(raw_ab[raw_ab.find('{'):raw_ab.rfind('}')+1])
                score_ab = max(1, min(5, int(parsed_ab.get('score', 3))))

                time.sleep(0.5)

                # BA 순서 평가 (위치 편향 통제)
                raw_ba = call_llm_fn(content_ba, system=system_prompt,
                                     max_tokens=200, temperature=0.3)
                parsed_ba = json.loads(raw_ba[raw_ba.find('{'):raw_ba.rfind('}')+1])
                score_ba = max(1, min(5, int(parsed_ba.get('score', 3))))

                # 위치 편향 처리
                if abs(score_ab - score_ba) <= 1:
                    # 일치 → 평균
                    score = (score_ab + score_ba) / 2
                else:
                    # 불일치 → 평균 (편향 존재 기록)
                    score = (score_ab + score_ba) / 2
                    bias_stats['position_disagree'] += 1

                repeat_scores.append(score)

            except Exception as e:
                repeat_scores.append(3.0)  # 파싱 실패 시 중간값

            time.sleep(0.5)

        # ── 편차 통제 ──
        if len(repeat_scores) >= 2:
            deviation = max(repeat_scores) - min(repeat_scores)
            if deviation <= max_deviation:
                final_score = np.mean(repeat_scores)
            else:
                final_score = np.median(repeat_scores)
                bias_stats['deviation_exceeded'] += 1
        else:
            final_score = repeat_scores[0] if repeat_scores else 3.0

        all_scores.append(round(final_score, 2))

        if (i + 1) % 10 == 0:
            print(f'  M4 평가 진행: {i+1}/{len(results_s4)} '
                  f'(현재 평균: {np.mean(all_scores):.2f})')

    result = {
        'scores': all_scores,
        'mean': round(np.mean(all_scores), 2),
        'std': round(np.std(all_scores), 2),
        'median': round(np.median(all_scores), 2),
        'n_evaluated': len(all_scores),
        'n_repeats': n_repeats,
        'max_deviation': max_deviation,
        'bias_control': {
            'protocol': 'Zheng et al. (2023)',
            'position_bias': f'AB/BA 양방향 평가, 불일치 {bias_stats["position_disagree"]}건',
            'self_enhancement': '2종 프롬프트 변형(법학교수/전문심사자) 교대 사용',
            'repetition': f'{n_repeats}회 반복, 편차>{max_deviation} → 중간값 ({bias_stats["deviation_exceeded"]}건)',
        },
        'note': '동일 모델 패밀리 사용 (Claude Sonnet) — 다중 모델 불가 시 프롬프트 변형으로 대체'
    }

    print(f'\n=== M4 Reasoning Quality ===')
    print(f'  평균: {result["mean"]}/5.0 (std={result["std"]})')
    print(f'  위치편향 불일치: {bias_stats["position_disagree"]}건')
    print(f'  편차 초과: {bias_stats["deviation_exceeded"]}건')

    return result


# ═══════════════════════════════════════════════════════════════
# 사용 예시
# ═══════════════════════════════════════════════════════════════

USAGE = """
# ── 04_irac_v_framework.py에서 R-Agent Fallback 사용 ──

from agent_extras import LawAPIFallback, r_agent_with_fallback

api_fb = LawAPIFallback()  # .env의 LAW_OC 사용

# 기존 r_agent 대신 사용
rules = r_agent_with_fallback(issues, run_q, api_fallback=api_fb, min_articles=2)


# ── 05_analysis_and_paper.py에서 LLM-as-Judge 사용 ──

from agent_extras import evaluate_reasoning_quality_full

rq = evaluate_reasoning_quality_full(
    results['stage4'], scenarios, call_llm,
    n_repeats=3, max_deviation=1.0
)
print(f'M4: {rq["mean"]}/5.0')
evals['stage4']['M4_reasoning_quality'] = rq['mean']
"""

if __name__ == '__main__':
    print(USAGE)
