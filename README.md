# Job-analysis · AI 데일리 채용 브리프

매일 아침 9시 전후, GitHub Actions가 내 경력에 맞는 채용공고를 찾아 적합도를 평가하고 지원 전략 리포트를 HTML로 만들어 줍니다.

리포트 페이지: https://dongjun-ji.github.io/Job-analysis/

## 왜 만들었나

이직을 준비하면서 매일 아침 채용 사이트 여러 곳을 돌며 공고를 골랐습니다. [하루에 걸리던 시간]이 들었는데, 공고를 고르는 기준은 매일 같았습니다. 희망 직무, 근무지, 경력 요건, 그리고 내 경험과 얼마나 맞는지였죠. 기준이 정해져 있는 반복 업무라면 자동화할 수 있다고 봤습니다.


## 어떻게 동작하나

```
GitHub Actions (매일 08:52 KST)
  └─ scripts/generate_report.py
       1. 프로필 + 판단 기준 + 최근 7일 추천 이력으로 프롬프트 구성
       2. Claude API 호출 (웹 검색으로 공고 탐색 → 웹 페이지 열기로 원문 확인)
       3. JSON 결과를 받아 점수 합계, 마감 D-day, 재추천 여부를 코드로 계산
       4. HTML 템플릿에 채워 docs/index.html 생성
       5. data/history.json에 기록 → 다음 날 중복 추천 방지
  └─ 결과를 커밋 → GitHub Pages로 공개
```

AI와 코드의 역할을 나눴습니다.

| 코드가 하는 일 | AI가 하는 일 |
| --- | --- |
| 매일 정해진 시간에 실행 | 공고 검색과 원문 확인 |
| 최근 추천 이력 전달, 재추천 표시 | 공고 요건과 내 경험 비교 |
| 점수 합계, 색 구분, 마감 D-day 계산 | 항목별 점수와 근거 작성 |
| HTML 생성, 기록 저장, 비용 집계 | TOP 3 지원 전략과 오늘 할 일 |

계산처럼 정답이 있는 일은 코드가 맡아서, AI가 숫자를 틀리게 더하거나 날짜를 잘못 세는 일이 없게 했습니다.

## 평가 기준

적합도 100점 = 직무 경험 일치도 40 + 필수 자격 충족도 30 + 산업·도메인 적합도 20 + 근무 조건 적합도 10

- 직무명만 같다고 추천하지 않고, 실제 업무와 자격요건을 경험과 대조합니다.
- 확인하지 못한 정보는 "확인 필요"로 남기고, 프로필에 없는 경험은 쓰지 않게 했습니다.
- 마감됐거나, 계약직이거나, 경력 요건 차이가 큰 공고는 제외합니다.

## 운영 지표

리포트 하단에 매일 웹 검색 횟수, 토큰 사용량, 추정 비용을 기록합니다. 누적 기록은 `data/history.json`에 있습니다.

## 직접 실행하기

1. 저장소를 포크합니다.
2. Settings → Secrets and variables → Actions에 `ANTHROPIC_API_KEY`를 등록합니다.
3. `config/profile.md`를 자기 프로필로 바꿉니다. 공개하고 싶지 않다면 같은 내용을 `PROFILE` 시크릿에 넣으면 그쪽이 우선합니다.
4. Settings → Pages에서 Branch를 `main`, 폴더를 `/docs`로 설정합니다.
5. Actions 탭 → Daily Job Report → Run workflow로 바로 실행해 볼 수 있습니다.

API 없이 화면만 확인하려면:

```bash
pip install -r requirements.txt
python scripts/generate_report.py --sample data/sample_report.json
```

## 파일 구성

```
.github/workflows/daily-report.yml  매일 실행 스케줄
scripts/generate_report.py           전체 흐름
config/prompt.md                     검색 조건과 평가 기준
config/profile.md                    지원자 프로필
templates/report.html                리포트 디자인
data/history.json                    날짜별 추천 기록
docs/                                GitHub Pages로 공개되는 리포트
```
