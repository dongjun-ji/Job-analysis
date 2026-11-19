# Job-analysis · AI 데일리 채용 브리프

매일 아침 내 경력에 맞는 채용공고를 찾아 적합도를 평가하고, 지원 전략 리포트를 HTML 페이지로 자동 발행합니다.

리포트 페이지: https://dongjun-ji.github.io/Job-analysis/

## 왜 만들었나

이직을 준비하면서 매일 아침 채용 사이트 여러 곳을 돌며 공고를 골랐습니다. [하루에 걸리던 시간]이 들었는데, 공고를 고르는 기준은 매일 같았습니다. 희망 직무, 근무지, 경력 요건, 그리고 내 경험과 얼마나 맞는지였죠. 기준이 정해져 있는 반복 업무라면 자동화할 수 있다고 봤습니다.

## 어떻게 동작하나

```
[매일 08:52 KST] Claude 예약 작업
   ├─ config/prompt.md(판단 기준), config/profile.md(프로필), data/history.json(최근 추천) 읽기
   ├─ 웹 검색으로 공고 탐색 → 원문 페이지 열어 자격요건·마감 확인
   └─ 분석 결과를 data/reports/YYYY-MM-DD.json으로 커밋·푸시
                 │
                 ▼  (push 이벤트로 자동 실행)
[GitHub Actions] .github/workflows/daily-report.yml
   ├─ 데이터 형식 검증 (필수 항목, 점수 범위) → 오류면 빌드 실패
   ├─ 점수 합계, 마감 D-day, 재추천 여부 계산
   ├─ templates/report.html로 HTML 생성 → docs/
   └─ data/history.json 갱신 후 커밋 → GitHub Pages 발행
```

AI와 코드의 역할을 나눴습니다.

| 코드가 하는 일 | AI가 하는 일 |
| --- | --- |
| AI 출력 형식 검증 (항목 누락, 점수 범위) | 공고 검색과 원문 확인 |
| 점수 합계, 색 구분, 마감 D-day 계산 | 공고 요건과 내 경험 비교 |
| 최근 7일 추천 이력으로 재추천 표시 | 항목별 점수와 근거 작성 |
| HTML 생성, 기록 저장, 페이지 발행 | TOP 3 지원 전략과 오늘 할 일 |

계산처럼 정답이 있는 일은 코드가 맡아서, AI가 숫자를 틀리게 더하거나 날짜를 잘못 세는 일이 없게 했습니다. AI가 범위를 벗어난 점수를 내면 검증 단계에서 빌드가 멈추고 전날 페이지가 그대로 유지됩니다.

## 평가 기준

적합도 100점 = 직무 경험 일치도 40 + 필수 자격 충족도 30 + 산업·도메인 적합도 20 + 근무 조건 적합도 10

- 직무명만 같다고 추천하지 않고, 실제 업무와 자격요건을 경험과 대조합니다.
- 확인하지 못한 정보는 "확인 필요"로 남기고, 프로필에 없는 경험은 쓰지 않게 했습니다.
- 마감됐거나, 계약직이거나, 경력 요건 차이가 큰 공고는 제외하고, 제외 사유도 리포트 하단에 남깁니다.

## 비용

GitHub Actions와 Pages는 공개 저장소에서 무료입니다. 분석은 Claude 구독에 포함된 예약 작업으로 돌려 별도 API 비용이 들지 않습니다.

## 화면만 확인하기

```bash
pip install -r requirements.txt
python scripts/generate_report.py --sample   # data/sample_report.json으로 docs/index.html 생성
```

## 파일 구성

```
.github/workflows/daily-report.yml  리포트 데이터가 올라오면 빌드·발행
scripts/generate_report.py           검증 → 계산 → HTML 생성 → 기록
config/prompt.md                     검색 조건과 평가 기준 (AI가 읽는 지침)
config/profile.md                    지원자 프로필
templates/report.html                리포트 디자인
data/reports/                        날짜별 분석 결과 (AI 출력)
data/history.json                    날짜별 추천 기록
docs/                                GitHub Pages로 공개되는 리포트
```
