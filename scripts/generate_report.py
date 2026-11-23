"""data/reports/에 올라온 분석 결과(JSON)로 HTML 리포트를 만드는 스크립트.

공고 검색과 분석은 Claude 예약 작업이 매일 아침 수행해 JSON으로 올리고,
이 스크립트는 GitHub Actions에서 실행되어 검증 → 계산 → HTML 생성 → 기록 저장을 맡는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "data" / "reports"
HISTORY = ROOT / "data" / "history.json"
DOCS = ROOT / "docs"
KST = ZoneInfo("Asia/Seoul")
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]
HISTORY_DAYS = 7
MAX_JOBS = 6
SCORE_KEYS = {"experience": 40, "qualification": 30, "domain": 20, "conditions": 10}
REQUIRED_JOB_KEYS = ["company", "title", "url", "scores", "priority"]


# ---------- 기록 ----------

def load_history() -> list[dict]:
    if not HISTORY.exists():
        return []
    return json.loads(HISTORY.read_text(encoding="utf-8"))


def recent_urls(history: list[dict], day: date) -> set[str]:
    cutoff = day - timedelta(days=HISTORY_DAYS)
    return {
        job["url"]
        for entry in history
        if cutoff <= date.fromisoformat(entry["date"]) < day
        for job in entry["jobs"]
    }


# ---------- 검증과 계산 ----------

def validate(report: dict) -> list[str]:
    """AI가 만든 데이터에서 형식이 틀린 부분을 찾는다. 문제가 있으면 메시지 목록을 돌려준다."""
    errors = []
    for key in ("briefing", "jobs", "actions", "verdict"):
        if key not in report:
            errors.append(f"'{key}' 항목이 없습니다")
    for i, job in enumerate(report.get("jobs", []), 1):
        for key in REQUIRED_JOB_KEYS:
            if not job.get(key):
                errors.append(f"{i}번째 공고에 '{key}'가 없습니다")
        for key, limit in SCORE_KEYS.items():
            value = job.get("scores", {}).get(key)
            if not isinstance(value, (int, float)) or not 0 <= value <= limit:
                errors.append(f"{i}번째 공고 {key} 점수가 0~{limit} 범위를 벗어났습니다: {value}")
    return errors


def score_class(total: int) -> str:
    if total >= 70:
        return "s-high"
    if total >= 55:
        return "s-mid"
    return "s-low"


def enrich(report: dict, day: date, seen_urls: set[str]) -> dict:
    """합계, 색 구분, 마감 D-day, 재추천 여부처럼 정답이 있는 계산은 코드가 맡는다."""
    for job in report["jobs"]:
        job["total"] = int(sum(job["scores"][k] for k in SCORE_KEYS))
        job["score_class"] = score_class(job["total"])
        job["is_repeat"] = job["url"] in seen_urls
        job["d_day"] = None
        iso = job.get("deadline_iso")
        if iso:
            try:
                days = (date.fromisoformat(iso) - day).days
                if 0 <= days <= 7:
                    job["d_day"] = days
            except ValueError:
                pass
    report["jobs"].sort(key=lambda j: j.get("priority", 99))
    # 화면에는 추천 공고를 최대 6개, TOP 3는 정확히 3개까지만 보여준다.
    report["jobs"] = report["jobs"][:MAX_JOBS]
    report["top3"] = report.get("top3", [])[:3]

    jobs = report["jobs"]
    deadlines = sorted(
        j["deadline_iso"] for j in jobs
        if j.get("deadline_iso") and j["deadline_iso"] >= day.isoformat()
    )
    report["kpis"] = {
        "new_count": sum(1 for j in jobs if not j["is_repeat"]),
        "top_score": max((j["total"] for j in jobs), default="-"),
        "nearest_deadline": date.fromisoformat(deadlines[0]).strftime("%m/%d") if deadlines else "-",
    }
    return report


# ---------- 렌더링 ----------

def run_stats(history: list[dict]) -> dict:
    """리포트가 올라간 날을 세어 누적 운영 일수와 시작일을 구한다."""
    dates = sorted({e["date"] for e in history})
    if not dates:
        return {"days": 0, "start": None, "start_label": "-"}
    start = date.fromisoformat(dates[0])
    return {"days": len(dates), "start": dates[0], "start_label": f"{start.year}.{start.month:02d}.{start.day:02d}"}


README_START, README_END = "<!-- ops:start -->", "<!-- ops:end -->"


def update_readme(stats: dict) -> None:
    """README의 표시 구간 안에 누적 운영 일수를 매일 다시 쓴다."""
    path = ROOT / "README.md"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    if README_START not in text or README_END not in text:
        return
    line = f"{stats['start_label']}부터 매일 운영 중 · 누적 {stats['days']}일"
    head, rest = text.split(README_START, 1)
    _, tail = rest.split(README_END, 1)
    path.write_text(f"{head}{README_START}{line}{README_END}{tail}", encoding="utf-8")


def render(report: dict, day: date, history_checked: bool, archive_dates: list[str],
           stats: dict, prefix: str = "") -> str:
    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(["html"]))
    return env.get_template("report.html").render(
        r=report,
        date_label=f"{day.year}년 {day.month}월 {day.day}일 ({WEEKDAYS[day.weekday()]})",
        ops=report.get("ops", {}),
        stats=stats,
        history_checked=history_checked,
        archive_dates=archive_dates,
        prefix=prefix,
        generated_at=datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
    )


def latest_report() -> Path | None:
    files = sorted(REPORTS.glob("*.json"))
    return files[-1] if files else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", help="렌더링할 JSON 파일 (기본: data/reports/의 가장 최근 파일)")
    parser.add_argument("--sample", action="store_true", help="예시 데이터로 화면만 확인 (기록·아카이브 저장 안 함)")
    args = parser.parse_args()

    if args.sample:
        path = ROOT / "data" / "sample_report.json"
        day = datetime.now(KST).date()
    else:
        path = Path(args.input) if args.input else latest_report()
        if not path or not path.exists():
            print("data/reports/에 리포트 JSON이 아직 없습니다. 건너뜁니다.")
            return 0
        day = date.fromisoformat(path.stem)

    report = json.loads(path.read_text(encoding="utf-8"))
    errors = validate(report)
    if errors:
        print("리포트 데이터 형식 오류:\n- " + "\n- ".join(errors), file=sys.stderr)
        return 1

    history = load_history()
    history_checked = bool([e for e in history if e["date"] != day.isoformat()])
    report = enrich(report, day, recent_urls(history, day))

    if not args.sample:
        history = [e for e in history if e["date"] != day.isoformat()]
        history.insert(0, {
            "date": day.isoformat(),
            "ops": report.get("ops", {}),
            "jobs": [
                {k: j.get(k) for k in ("company", "title", "total", "deadline_text", "url")}
                for j in report["jobs"]
            ],
        })
        history.sort(key=lambda e: e["date"], reverse=True)
    stats = run_stats(history)

    (DOCS / "archive").mkdir(parents=True, exist_ok=True)
    dates = {p.stem for p in (DOCS / "archive").glob("*.html")}
    if not args.sample:
        dates.add(day.isoformat())
    archive_dates = sorted(dates, reverse=True)[:14]
    common = dict(history_checked=history_checked, archive_dates=archive_dates, stats=stats)

    (DOCS / "index.html").write_text(render(report, day, **common), encoding="utf-8")
    if not args.sample:
        (DOCS / "archive" / f"{day.isoformat()}.html").write_text(
            render(report, day, prefix="../", **common), encoding="utf-8"
        )
        HISTORY.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
        update_readme(stats)

    print(f"완료: {day} 공고 {len(report['jobs'])}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
