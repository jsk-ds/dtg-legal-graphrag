# IRAC-V GraphRAG: 화물차 DTG 위험운전행동의 법적 심각도 분류 프레임워크

> **IRAC-V GraphRAG Framework for Legal Severity Classification of Hazardous Driving Behaviors in Commercial Vehicle DTG Data**

[![Python](https://img.shields.io/badge/Python-3.12.7-blue.svg)](https://www.python.org/)
[![Neo4j](https://img.shields.io/badge/Neo4j-5.x-green.svg)](https://neo4j.com/)
[![LLM](https://img.shields.io/badge/LLM-Claude%20Sonnet%204-orange.svg)](https://www.anthropic.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 개요

본 프로젝트는 화물차 디지털 운행기록장치(DTG) 데이터에서 탐지된 위험운전행동의 **법적 심각도를 자동으로 분류**하는 IRAC-V GraphRAG 프레임워크입니다.

현행 운행기록분석시스템(eTAS)은 "과속 9회, 급가속 3회"와 같은 **물리적 카운팅**만 제공할 뿐, 해당 위반이 **행정처분(범칙금)에 그치는지 형사처벌(벌금·면허취소) 대상인지**를 판단하지 못합니다. 본 연구는 이 제도적 공백을 메우기 위해:

1. **한국 교통법령 Knowledge Graph** (65개 노드, 78개 엣지)를 구축하고
2. 법학의 **IRAC 논증 구조**를 반영한 **5단계 멀티에이전트 파이프라인**을 설계하여
3. 과속 초과속도에 따른 **6단계 법적 심각도**(level_1~6)를 자동 분류합니다.

## 주요 성과

| 메트릭 | S1: Vanilla LLM | S2: Flat RAG | S3: GraphRAG | **S4: IRAC-V** |
|--------|:---:|:---:|:---:|:---:|
| M3 Severity F1 | 22.4% | 24.2% | 27.1% | **63.3%** |
| M6 Multi-hop Recall | 0.0% | 30.9% | 53.0% | **70.7%** |
| M1 Citation Accuracy | 1.3% | 100.0% | 100.0% | **96.3%** |
| M5 Hallucination Rate | 98.7% | 0.0% | 0.0% | **3.7%** |

- S4의 Bootstrap 95% CI 하한(53.9%) > S1~S3 상한(32.9%) → **통계적으로 유의한 성능 향상**
- N=100건 시나리오 × 3회 반복, temperature=0.0

## 아키텍처

```
DTG 이벤트
    │
    ▼
┌─────────────────────────────────────────────────┐
│                IRAC-V Pipeline                   │
│                                                  │
│  I-Agent ──→ R-Agent ──→ A-Agent ──→ V-Agent    │
│  (Issue)     (Rule)     (Application) (Verify)   │
│  쟁점 추출   KG 검색    법리 포섭     일관성 검증  │
│                                         │        │
│                                    Self-Healing   │
│                                    (최대 2회)     │
│                                         │        │
│                                    C-Agent        │
│                                    (Conclusion)   │
│                                    최종 판정      │
└─────────────────────────────────────────────────┘
    │
    ▼
법적 심각도 (level_1~6) + 인용 조문 + 처분 내용
```

## 프로젝트 구조

```
dtg-legal-graphrag/
│
├── 00_setup.ipynb                    # 환경 설정, API 키 검증
├── 01_data_collection.ipynb          # 법제처 Open API 법령 수집
├── 02_data_analysis.ipynb            # DTG 데이터 EDA, 시나리오 생성
├── 03_legal_kg_construction.ipynb    # Neo4j KG 구축 + FAISS 인덱스
├── 04_irac_v_framework.ipynb        # IRAC-V 4-Stage Ablation Study
├── 05_analysis_and_paper.ipynb       # 결과 분석, 통계 검정, Figure 생성
│
├── config.py                         # 전역 설정 (경로, 심각도 테이블, LLM 모델)
├── agent_extras.py                   # R-Agent API Fallback, M4 LLM-as-Judge
├── law_collector.py                  # 법제처 Open API 래퍼
├── speed_matcher.py                  # GPS 맵매칭, 제한속도 연계
│
├── CODEBOOK.csv                      # DTG 데이터 코드북
├── 사업용차량_Trip단위_위험운전운행데이터_샘플.csv
├── 사업용차량_초단위_운행기록데이터_샘플header.csv
├── 사업용차량_초단위_운행기록데이터_샘플body.csv
├── DT_CAR_BSN_DDRA_202507311033.csv  # 일별 위험운전 집계 (2020-2023)
├── 한국도로공사_고속도로_구간별_제한속도_20250501.csv
├── 전국도로안전표지표준데이터.csv
├── 경찰청_연도별_차종별_교통사고_건수_20241231.csv
├── 교통사고통계_20260324.xlsx
├── 한국교통안전공단.pdf               # eTAS 위험운전행동 기준
│
├── IRAC_정리.html                    # IRAC-V 설계 문서
├── .gitignore
└── README.md
```

## 실행 환경

### 사전 요구사항

| 항목 | 버전 |
|------|------|
| Python | 3.12 |
| Neo4j | 5.28 (Community Edition 또는 AuraDB Free) |
| OS | Windows / macOS / Linux |

### 설치

```bash
git clone https://github.com/jsk-ds/dtg-legal-graphrag.git
cd dtg-legal-graphrag

# 가상환경 생성 (권장)
conda create -n llm python=3.12.7
conda activate llm

# 의존성 설치
pip install anthropic openai neo4j faiss-cpu numpy pandas matplotlib scikit-learn scipy python-dotenv requests openpyxl
```

### API 키 설정

프로젝트 루트에 `.env` 파일을 생성합니다:

```env
# .env
ANTHROPIC_API_KEY=sk-ant-...       # Anthropic Claude API
OPENAI_API_KEY=sk-...              # OpenAI Embedding API
LAW_OC=...                         # 법제처 Open API 인증코드
NEO4J_URI=neo4j+s://...            # Neo4j 연결 URI
NEO4J_USER=neo4j                   # Neo4j 사용자명
NEO4J_PW=...                       # Neo4j 비밀번호
```

API 키 발급처:
- Anthropic: https://console.anthropic.com/
- OpenAI: https://platform.openai.com/
- 법제처: https://open.law.go.kr/ (회원가입 → 인증코드 발급)
- Neo4j AuraDB: https://neo4j.com/cloud/aura-free/

## 실행 순서

노트북을 **순서대로** 실행합니다:

```
00_setup.ipynb          →  환경 검증, 디렉토리 생성
01_data_collection.ipynb →  법령 15개 조문 수집, JSON 저장
02_data_analysis.ipynb   →  DTG EDA, 시나리오 100건 생성
03_legal_kg_construction →  Neo4j KG 구축 (65노드/78엣지), FAISS 인덱스
04_irac_v_framework     →  4-Stage Ablation Study (100건 × 3회 반복)
05_analysis_and_paper   →  Figure/Table 생성, 통계 검정, M4 평가
```

> **04 실행 시 주의**: 100건 × 4 Stage × 3회 반복 = 1,200회 LLM 호출. API 비용이 발생합니다.
> 먼저 `N_REPEAT=1`로 테스트 후 `N_REPEAT=3`으로 확대를 권장합니다.

## Knowledge Graph 구조

| 노드 유형 | 개수 | 설명 |
|-----------|------|------|
| HazardousBehavior | 13 | eTAS 위험운전행동 유형 |
| LegalArticle | 27 | 법령 조문 (도교법, 교통안전법, 화물차법) |
| SeverityLevel | 6 | 과속 심각도 6단계 (level_1~6) |
| Penalty | 17 | 범칙금·벌점·형사처벌 |
| AggravatingFactor | 2 | 가중처벌 조건 (어린이보호구역, 반복과속) |

| 엣지 유형 | 개수 | 의미 |
|-----------|------|------|
| VIOLATES | 31 | 위반행위 → 법령 조문 |
| CLASSIFIED_AS | 12 | 위반행위 → 심각도 등급 |
| RELATED_TO | 14 | 정의 조문 → 벌칙 조문 |
| PENALIZED_BY | 16 | 심각도 → 처벌 내용 |
| DEFINED_BY | 3 | 조문 → 정의 조문 |
| ESCALATES_TO | 2 | 반복 위반 → 상위 등급 |

## 평가 메트릭

| 메트릭 | 명칭 | 정의 |
|--------|------|------|
| M1 | Citation Accuracy | 인용 조문이 KG에 실존하는 비율 |
| M2 | Penalty Accuracy | 범칭금·벌점 예측 정확도 |
| M3 | Severity F1 (macro) | 심각도 등급 분류 F1 (핵심 지표) |
| M4 | Reasoning Quality | LLM-as-Judge 법적 추론 품질 (1~5점) |
| M5 | Hallucination Rate | 미존재 조문 인용 비율 (1−M1) |
| **M6** | **Multi-hop Recall** ★ | **위반→정의→벌칙 경로 완결 비율 (신규 제안)** |

## 법적 심각도 6단계

| 등급 | 초과 속도 | 처분 | 범칙금(화물차) | 벌점 |
|------|-----------|------|---------------|------|
| level_1 | 1~20km/h | 행정 | 3만원 | 없음 |
| level_2 | 21~40km/h | 행정 | 7만원 | 15점 |
| level_3 | 41~60km/h | 행정 | 10만원 | 30점 |
| level_4 | 61~80km/h | 행정 | 13만원 | 60점 |
| level_5 | 81~100km/h | **형사** | 30만원 이하 벌금 | 80점 |
| level_6 | 101km/h~ | **형사(가중)** | 100만원 이하 벌금 | 면허취소 |

※ 도로교통법 시행령 별표 8 기준 (도로교통법 제21016호, 2026.01.01 시행)

## 데이터 출처

| 데이터 | 출처 | 비고 |
|--------|------|------|
| 법령 조문 | 법제처 Open API (open.law.go.kr) | 15개 조문 |
| 시행령 별표 | 국가법령정보센터 (law.go.kr) | 별표 7·8·10 수동 파싱 |
| DTG Trip 데이터 | 한국교통안전공단 eTAS 공공데이터포털 | 100 Trip, 66컬럼 |
| DTG 초단위 데이터 | 한국교통안전공단 eTAS | 1,100행 × 14컬럼 |
| 일별 위험운전 | 한국교통안전공단 eTAS | 28,654행 (2020-2023) |
| 도로안전표지 | 국가공간정보포털 | ~50,000건 |
| 고속도로 제한속도 | 한국도로공사 데이터몰 | 95구간 |
| 교통사고 통계 | 경찰청 TAAS | 2019-2024 |

## 참고 논문

본 프로젝트는 KCI 등재지 투고를 위한 연구 결과물입니다.

**논문 제목**: 화물차 DTG 위험운전행동의 법적 심각도 분류를 위한 IRAC-V GraphRAG 프레임워크

**주요 인용**:
- Edge et al. (2024). From Local to Global: A Graph RAG Approach to Query-Focused Summarization. *arXiv:2404.16130*.
- Zheng et al. (2023). Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena. *NeurIPS 36*.
- 이석준, 이청원 (2012). 사업용 자동차의 DTG 설치 단기 효과분석. *한국ITS학회 논문지*, 11(6).
- 장재민 등 (2017). DTG 자료기반 위험운전자 판별분석. *교통연구*, 24(4).

## 라이선스

MIT License

## 문의

- GitHub Issues: https://github.com/jsk-ds/dtg-legal-graphrag/issues
