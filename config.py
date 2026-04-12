"""
config.py — 프로젝트 전체 공유 설정
======================================
모든 노트북에서 from config import * 으로 사용
"""
import os, pathlib, json

# ── 디렉토리 ──
PROJECT_ROOT = pathlib.Path('.').resolve()
DTG_DIR   = pathlib.Path('data/01_DTG_RAW')
SPEED_DIR = pathlib.Path('data/02_SPEED_LIMIT')
LAW_DIR   = pathlib.Path('data/03_LAW_DATA')
STAT_DIR  = pathlib.Path('data/04_ACCIDENT_STAT')
REF_DIR   = pathlib.Path('data/05_REFERENCE')
JSON_DIR  = LAW_DIR / 'json'
PENALTY_DIR = LAW_DIR / 'penalty_tables'
SCENARIO_DIR = pathlib.Path('data/scenarios')
KG_DIR    = pathlib.Path('data/kg')
RESULTS_DIR = pathlib.Path('results')
FIGURES_DIR = pathlib.Path('figures')

ALL_DIRS = [DTG_DIR, SPEED_DIR, LAW_DIR, STAT_DIR, REF_DIR,
            JSON_DIR, PENALTY_DIR, SCENARIO_DIR, KG_DIR,
            RESULTS_DIR/'stage1', RESULTS_DIR/'stage2',
            RESULTS_DIR/'stage3', RESULTS_DIR/'stage4',
            RESULTS_DIR/'evaluation', FIGURES_DIR, pathlib.Path('utils')]

# ── 한글 CSV 로더 ──
def load_korean_csv(filepath, nrows=None):
    import pandas as pd
    for enc in ['utf-8','cp949','euc-kr','utf-8-sig']:
        try: return pd.read_csv(filepath, encoding=enc, nrows=nrows)
        except (UnicodeDecodeError, UnicodeError): continue
    raise ValueError(f'Cannot read {filepath}')

# ── JSON 헬퍼 ──
def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(data, path):
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f'✅ 저장: {path}')

# ── LLM 모델 ──
LLM_MODEL = 'claude-sonnet-4-20250514'

# ── 과속 6단계 SGT (Source of Ground Truth) ──
# ★ 법령 버전 고정: 도로교통법(법률 제21016호, 2026.01.01 시행) 기준
# - 제156조제1호: 제한속도 초과 일반 (20만원 이하 벌금/구류/과료) → L1~L4
# - 제154조제9호: 80km/h 초과 (30만원 이하 벌금/구류)             → L5
# - 제153조제2항제2호: 100km/h 초과 (100만원 이하 벌금/구류)       → L6
# - 제151조의2제2호: 100km/h 초과 3회 이상 (1년 이하 징역/500만원 이하 벌금) → 가중
# 범칙금 차등: 도로교통법 시행령(대통령령 제35947호, 2026.01.02 시행) 별표 8 기준
# 벌점 기준: 도로교통법 시행규칙(행정안전부령 제00610호, 2026.02.24 시행) 별표 28 기준
# ★ 법령 개정 시 본 테이블 및 KG를 함께 갱신해야 합니다.
SEVERITY_TABLE = {
    'level_1': {'label':'경미','speed_over_min':0,'speed_over_max':20,
                'description':'20km/h 이하 초과',
                'fine_passenger':30000,'fine_van_etc':30000,'demerit_points':0,
                'legal_basis':'제156조제1호','criminal':False},
    'level_2': {'label':'주의','speed_over_min':20,'speed_over_max':40,
                'description':'20~40km/h 초과',
                'fine_passenger':60000,'fine_van_etc':70000,'demerit_points':15,
                'legal_basis':'제156조제1호','criminal':False},
    'level_3': {'label':'경고','speed_over_min':40,'speed_over_max':60,
                'description':'40~60km/h 초과',
                'fine_passenger':90000,'fine_van_etc':100000,'demerit_points':30,
                'legal_basis':'제156조제1호','criminal':False},
    'level_4': {'label':'위험','speed_over_min':60,'speed_over_max':80,
                'description':'60~80km/h 초과',
                'fine_passenger':120000,'fine_van_etc':130000,'demerit_points':60,
                'legal_basis':'제156조제1호','criminal':False,
                'note':'벌점 60점=면허정지'},
    # ★ level_5·level_6: 형사처벌 구간 — 범칙금(fine)이 아닌 벌금(criminal_penalty) 적용
    # M2 Penalty Accuracy 평가 시 fine_van_etc=None이므로 범칙금 정확도 산출 대상 아님.
    # 논문 Limitation 섹션에 "시행령 별표 8의 범칙금은 행정처분(L1~L4)에만 적용,
    # 형사처벌(L5~L6)은 법원 양형에 따르므로 M2 산출 제외" 명기 필요.
    'level_5': {'label':'매우위험','speed_over_min':80,'speed_over_max':100,
                'description':'80~100km/h 초과',
                'fine_passenger':None,'fine_van_etc':None,
                'criminal_penalty':'30만원 이하 벌금·구류','demerit_points':80,
                'legal_basis':'제154조제9호','criminal':True},
    'level_6': {'label':'극히위험','speed_over_min':100,'speed_over_max':9999,
                'description':'100km/h 초과',
                'fine_passenger':None,'fine_van_etc':None,
                'criminal_penalty':'100만원 이하 벌금·구류','demerit_points':None,
                'legal_basis':'제153조제2항제2호','criminal':True,
                'note':'3회이상→제151조의2제2호: 1년이하 징역/500만원이하 벌금'},
}

AGGRAVATING_FACTORS = {
    'school_zone': {'name':'어린이보호구역','demerit_multiplier':2.0,
                    'fine_basis':'시행령 별표 10','legal_basis':'시행령 별표 7·10'},
    'repeat_100km': {'name':'100km/h초과 3회이상',
                     'escalation':'제151조의2제2호',
                     'penalty':'1년이하 징역/500만원이하 벌금'},
}

# ── 위반유형→조문 매핑 ──
VIOLATION_MAPPING = {
    'speeding':           {'name_kr':'과속','etas_threshold':'제한속도+20km/h',
                           'definition_articles':['RTA_17'],'penalty_articles':['RTA_156','RTA_154','RTA_153','RTA_151_2'],
                           'aggravation':['RTA_12'],'has_severity_levels':True},
    'prolonged_speeding': {'name_kr':'장기과속','etas_threshold':'제한속도+20km/h, 3분이상',
                           'definition_articles':['RTA_17'],'penalty_articles':['RTA_156','RTA_154','RTA_153'],'has_severity_levels':True},
    'sudden_accel':       {'name_kr':'급가속','etas_threshold':'초당 8km/h이상',
                           'definition_articles':['RTA_49'],'penalty_articles':['RTA_156'],'has_severity_levels':False},
    'sudden_start':       {'name_kr':'급출발','etas_threshold':'5km/h이하→초당10km/h이상',
                           'definition_articles':['RTA_49'],'penalty_articles':['RTA_156'],'has_severity_levels':False},
    'sudden_decel':       {'name_kr':'급감속','etas_threshold':'초당 14km/h이상 감속',
                           'definition_articles':['RTA_49'],'penalty_articles':['RTA_156'],'has_severity_levels':False},
    'sudden_stop':        {'name_kr':'급정지','etas_threshold':'초당 14km/h이상→5km/h이하',
                           'definition_articles':['RTA_49'],'penalty_articles':['RTA_156'],'has_severity_levels':False},
    'sudden_lane_change': {'name_kr':'급진로변경','etas_threshold':'30km/h이상, 6~10도/sec',
                           'definition_articles':['RTA_19'],'penalty_articles':['RTA_156'],'has_severity_levels':False},
    'sudden_overtake':    {'name_kr':'급앞지르기','etas_threshold':'급차로변경+가속3km/h/s',
                           'definition_articles':['RTA_19','RTA_21'],'penalty_articles':['RTA_156'],'has_severity_levels':False},
    'sudden_turn':        {'name_kr':'급회전','etas_threshold':'20~30km/h이상',
                           'definition_articles':['RTA_25'],'penalty_articles':['RTA_156'],'has_severity_levels':False},
    'sudden_uturn':       {'name_kr':'급유턴','etas_threshold':'15~25km/h이상',
                           'definition_articles':['RTA_25'],'penalty_articles':['RTA_156'],'has_severity_levels':False},
}

def get_severity_level(speed_over):
    """초과속도 → 심각도 단계 반환."""
    if speed_over is None or speed_over <= 0:
        return None, None
    for lv, info in SEVERITY_TABLE.items():
        if info['speed_over_min'] < speed_over <= info['speed_over_max']:
            return lv, info
    return 'level_6', SEVERITY_TABLE['level_6']