# 올팍 나우 (OlPark Now)

올림픽공원 주차 혼잡을 7일 앞까지 시간대별로 예보하고, 방문객에게는 도착 시각·대중교통·퇴장 요령을, 운영자에게는 인력·임시주차장 배치 권고를 보여 주는 웹 서비스입니다. 2026년도 한국체육산업개발 공공데이터 활용 경진대회 출품작입니다.

## 데이터

| 데이터 | 출처 | 쓰임 |
| --- | --- | --- |
| 올림픽공원 2025 차량입출차·공연·날씨 연계 데이터 | 문화공공데이터광장 API_CPM_009 (공공데이터포털 15164822) | 시간대별 학습 데이터 (`data/raw.json`) |
| 올림픽공원 공연 일정 | 올림픽공원 공식 홈페이지 공연 일정 | 예보 대상일의 공연 여부·시작 시각 (`data/events.json`) |

## 구조

- `pipeline/olpark.py` — 수집·정제·예측. Python 표준 라이브러리만 사용합니다.
- `web/index.html` — 정적 화면 하나. `web/data/forecast.json`을 읽습니다.
- `.github/workflows/daily.yml` — 매일 06:00(KST)에 공연 일정을 다시 읽고 예보를 만든 뒤 GitHub Pages에 배포합니다. 서버와 운영비가 없습니다.

## 실행

```bash
python3 pipeline/olpark.py test        # 자체 점검
python3 pipeline/olpark.py schedule    # 공연 일정 → data/events.json
python3 pipeline/olpark.py forecast    # 예보 → web/data/forecast.json
python3 -m http.server 8765 -d web     # http://localhost:8765
```

연계 데이터를 새로 받으려면 문화공공데이터광장 서비스키가 필요합니다.

```bash
CULTURE_API_KEY=... python3 pipeline/olpark.py fetch
```

## 모델과 정확도

요일 구분(평일 / 주말·공휴일) × 시간대 × 공연 여부별 평균 주차 대수입니다. 수집 오류일(일 최고 1,000대 미만 또는 기록 20시간 미만)을 제외하고 학습합니다. 1~7월로 학습해 10~12월로 검증한 평균 오차는 306대로, "지난주 같은 시간" 기준(350대)보다 낮습니다.
