"""
speed_matcher.py — DTG GPS ↔ 제한속도 맵매칭 모듈
==================================================
02_data_analysis.py 와 04_irac_v_framework.py 에서 import하여 사용

매칭 로직 (4단계 Cascade):
  1단계: 전국도로안전표지표준데이터 → GPS 최근접 표지판 (반경 500m)
  2단계: 고속도로 구간별 제한속도 → 노선명+구간 매칭
  3단계: 도로유형별 법정 기본속도 (시행규칙 제19조)
  4단계: 화물차 차종 보정 (고속도로 80km/h, 자동차전용도로 80km/h)
"""

import math
import pandas as pd
from config import load_korean_csv, SPEED_DIR

# ── 시행규칙 제19조 법정 기본속도 ──
STATUTORY_SPEED = {
    'residential':     50,   # 주거·상업·공업지역
    'general_2lane':   60,   # 그 외 일반도로 (편도 1차로)
    'general_4lane':   80,   # 편도 2차로 이상
    'auto_expressway': 90,   # 자동차전용도로
    'expressway':     100,   # 고속도로 (승용차 기준)
}

# 화물차 차종 보정 (적재중량 1.5톤 초과)
CARGO_SPEED_OVERRIDE = {
    'expressway':      80,   # 고속도로 화물차 80km/h
    'auto_expressway': 80,   # 자동차전용도로 화물차 80km/h
}


class SpeedLimitMatcher:
    """DTG GPS 좌표에 제한속도를 매칭하는 클래스."""

    def __init__(self, sign_csv_path=None, highway_csv_path=None):
        """
        Args:
            sign_csv_path: 전국도로안전표지표준데이터 CSV 경로
            highway_csv_path: 고속도로 구간별 제한속도 CSV 경로
        """
        self.signs_df = None
        self.highway_df = None
        self.match_stats = {'sign': 0, 'highway': 0, 'statutory': 0, 'total': 0}

        # 표지판 데이터 로드
        if sign_csv_path:
            try:
                self.signs_df = load_korean_csv(sign_csv_path)
                # 속도 관련 컬럼 찾기
                speed_col = [c for c in self.signs_df.columns if '제한속도' in c or '주행제한' in c]
                lat_col = [c for c in self.signs_df.columns if '위도' in c]
                lon_col = [c for c in self.signs_df.columns if '경도' in c]

                if speed_col and lat_col and lon_col:
                    self.speed_col = speed_col[0]
                    self.lat_col = lat_col[0]
                    self.lon_col = lon_col[0]
                    # 유효한 데이터만 필터
                    self.signs_df = self.signs_df.dropna(subset=[self.speed_col, self.lat_col, self.lon_col])
                    self.signs_df = self.signs_df[self.signs_df[self.speed_col] > 0]
                    print(f'✅ 표지판 데이터: {len(self.signs_df)}건 (속도:{self.speed_col}, '
                          f'좌표:{self.lat_col}/{self.lon_col})')
                else:
                    print(f'⚠️ 속도/좌표 컬럼 미발견: {self.signs_df.columns.tolist()[:5]}...')
                    self.signs_df = None
            except Exception as e:
                print(f'⚠️ 표지판 데이터 로드 실패: {e}')

        # 고속도로 데이터 로드
        if highway_csv_path:
            try:
                self.highway_df = load_korean_csv(highway_csv_path)
                print(f'✅ 고속도로 데이터: {len(self.highway_df)}건')
            except Exception as e:
                print(f'⚠️ 고속도로 데이터 로드 실패: {e}')

    @staticmethod
    def _haversine(lat1, lon1, lat2, lon2):
        """두 GPS 좌표 간 거리 (미터)."""
        R = 6371000
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlam = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    @staticmethod
    def _parse_dtg_gps(gps_x, gps_y):
        """DTG GPS 좌표 파싱 (정수형 → 소수점).
        
        DTG 데이터의 GPS는 126889400 → 126.8894 형태로 저장됨.
        """
        if gps_x > 1000000:
            lon = gps_x / 1000000
            lat = gps_y / 1000000
        elif gps_x > 10000:
            lon = gps_x / 10000
            lat = gps_y / 10000
        else:
            lon = gps_x
            lat = gps_y
        return lat, lon

    def match_by_sign(self, lat, lon, radius_m=500):
        """1단계: 최근접 표지판 기반 제한속도 매칭.
        
        Args:
            lat, lon: WGS84 좌표
            radius_m: 검색 반경 (미터)
        
        Returns:
            (speed_limit, distance_m) or (None, None)
        """
        if self.signs_df is None:
            return None, None

        best_dist = float('inf')
        best_speed = None

        for _, row in self.signs_df.iterrows():
            s_lat = row[self.lat_col]
            s_lon = row[self.lon_col]
            dist = self._haversine(lat, lon, s_lat, s_lon)
            if dist < best_dist and dist <= radius_m:
                best_dist = dist
                best_speed = row[self.speed_col]

        if best_speed is not None:
            return int(best_speed), round(best_dist, 1)
        return None, None

    def match_by_highway(self, route_name=None):
        """2단계: 고속도로 구간별 제한속도.
        
        Args:
            route_name: 노선명 (예: '경부선')
        
        Returns:
            speed_limit or None
        """
        if self.highway_df is None or route_name is None:
            return None

        speed_col = [c for c in self.highway_df.columns if '제한속도' in c]
        route_col = [c for c in self.highway_df.columns if '노선' in c]

        if speed_col and route_col:
            matched = self.highway_df[self.highway_df[route_col[0]].str.contains(route_name, na=False)]
            if len(matched) > 0:
                return int(matched[speed_col[0]].iloc[0])
        return None

    def match_by_statutory(self, road_type='general_2lane'):
        """3단계: 시행규칙 제19조 법정 기본속도."""
        return STATUTORY_SPEED.get(road_type, 60)

    def apply_cargo_override(self, speed_limit, road_type, vehicle_weight_tons=5.0):
        """4단계: 화물차 차종 보정.
        
        적재중량 1.5톤 초과 화물차: 고속도로/자동차전용도로 80km/h.
        """
        if vehicle_weight_tons > 1.5:
            override = CARGO_SPEED_OVERRIDE.get(road_type)
            if override is not None:
                return min(speed_limit, override)
        return speed_limit

    def match(self, lat=None, lon=None, road_type='general_2lane',
              route_name=None, vehicle_weight_tons=5.0,
              gps_x=None, gps_y=None):
        """4단계 Cascade 매칭.
        
        Returns:
            dict: {speed_limit, source, distance_m, road_type}
        """
        self.match_stats['total'] += 1

        # GPS 좌표 파싱
        if lat is None and gps_x is not None:
            lat, lon = self._parse_dtg_gps(gps_x, gps_y)

        # 1단계: 표지판
        if lat is not None and lon is not None:
            sign_speed, dist = self.match_by_sign(lat, lon)
            if sign_speed is not None:
                self.match_stats['sign'] += 1
                final = self.apply_cargo_override(sign_speed, road_type, vehicle_weight_tons)
                return {'speed_limit': final, 'source': 'sign',
                        'distance_m': dist, 'road_type': road_type,
                        'raw_limit': sign_speed, 'cargo_adjusted': final != sign_speed}

        # 2단계: 고속도로 구간
        if road_type in ('expressway', 'auto_expressway') and route_name:
            hw_speed = self.match_by_highway(route_name)
            if hw_speed is not None:
                self.match_stats['highway'] += 1
                final = self.apply_cargo_override(hw_speed, road_type, vehicle_weight_tons)
                return {'speed_limit': final, 'source': 'highway',
                        'road_type': road_type,
                        'raw_limit': hw_speed, 'cargo_adjusted': final != hw_speed}

        # 3단계: 법정 기본속도
        self.match_stats['statutory'] += 1
        statutory = self.match_by_statutory(road_type)
        final = self.apply_cargo_override(statutory, road_type, vehicle_weight_tons)
        return {'speed_limit': final, 'source': 'statutory',
                'road_type': road_type,
                'raw_limit': statutory, 'cargo_adjusted': final != statutory}

    def match_dtg_dataframe(self, df_body, speed_col='운행속도(KMH)',
                            gps_x_col='시작GPS(X좌표)', gps_y_col='시작GPS(Y좌표)',
                            vehicle_weight_tons=5.0):
        """DTG 초단위 DataFrame 전체에 제한속도 매칭.
        
        Returns:
            DataFrame with added columns: matched_speed_limit, speed_over, severity_level
        """
        from config import get_severity_level

        results = []
        for idx, row in df_body.iterrows():
            gps_x = row.get(gps_x_col)
            gps_y = row.get(gps_y_col)
            actual_speed = row.get(speed_col, 0)

            match = self.match(gps_x=gps_x, gps_y=gps_y,
                               vehicle_weight_tons=vehicle_weight_tons)

            speed_over = actual_speed - match['speed_limit']
            lv, info = get_severity_level(speed_over) if speed_over > 0 else (None, None)

            results.append({
                'idx': idx,
                'actual_speed': actual_speed,
                'speed_limit': match['speed_limit'],
                'speed_over': max(0, speed_over),
                'match_source': match['source'],
                'severity_level': lv,
                'severity_label': info['label'] if info else None,
                'criminal': info['criminal'] if info else False,
            })

        result_df = pd.DataFrame(results)

        print(f'\n=== 맵매칭 결과 ===')
        print(f'  총 레코드: {len(result_df)}건')
        print(f'  매칭 소스: {dict(result_df["match_source"].value_counts())}')
        print(f'  과속 건수: {(result_df["speed_over"] > 0).sum()}건 '
              f'({(result_df["speed_over"] > 0).mean():.1%})')

        if (result_df['speed_over'] > 0).any():
            speeding = result_df[result_df['speed_over'] > 0]
            print(f'  과속 심각도 분포:')
            for lv, cnt in speeding['severity_level'].value_counts().sort_index().items():
                print(f'    {lv}: {cnt}건')

        print(f'\n  매칭률: sign={self.match_stats["sign"]}, '
              f'highway={self.match_stats["highway"]}, '
              f'statutory={self.match_stats["statutory"]}')

        return result_df

    def get_match_report(self):
        """매칭률 보고서 (논문 Limitation 투명 보고용)."""
        total = self.match_stats['total']
        if total == 0:
            return {'total': 0, 'note': '매칭 미수행'}
        return {
            'total': total,
            'sign_matched': self.match_stats['sign'],
            'sign_rate': round(self.match_stats['sign'] / total, 4),
            'highway_matched': self.match_stats['highway'],
            'highway_rate': round(self.match_stats['highway'] / total, 4),
            'statutory_fallback': self.match_stats['statutory'],
            'statutory_rate': round(self.match_stats['statutory'] / total, 4),
            'note': '표지판 미매칭 시 법정 기본속도(시행규칙 제19조) 적용'
        }


# ── 사용 예시 ──
if __name__ == '__main__':
    import glob

    sign_files = sorted(glob.glob(str(SPEED_DIR / '*표지*')))
    hw_files = sorted(glob.glob(str(SPEED_DIR / '*고속*')))

    matcher = SpeedLimitMatcher(
        sign_csv_path=sign_files[0] if sign_files else None,
        highway_csv_path=hw_files[0] if hw_files else None,
    )

    # 단건 테스트
    result = matcher.match(lat=37.5665, lon=126.9780, road_type='general_2lane')
    print(f'\n테스트 (서울시청): {result}')

    result2 = matcher.match(road_type='expressway', vehicle_weight_tons=5.0)
    print(f'테스트 (고속도로 화물차): {result2}')