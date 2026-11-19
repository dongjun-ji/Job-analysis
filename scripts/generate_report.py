"""매일 아침 채용공고를 찾아 HTML 리포트를 만드는 스크립트.

흐름: 프롬프트 준비 → Claude API(웹 검색·웹 페이지 열기) → JSON 결과 → HTML 렌더링 → 기록 저장
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent.parent
KST = ZoneInfo("Asia/Seoul")
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
MAX_SEARCHES = int(os.environ.get("MAX_SEARCHES", "20"))
MAX_FETCHES = int(os.environ.get("MAX_FETCHES", "20"))
HISTORY_DAYS = 7
MAX_CONTINUATIONS = 10

# 비용 추정용 단가 (USD). 모델을 바꾸면 함께 바꾼다.
PRICE_INPUT_PER_MTOK = float(os.environ.get("PRICE_INPUT", "2"))
PRICE_OUTPUT_PER_MTOK = float(os.environ.get("PRICE_OUTPUT", "10"))
PRICE_PER_SEARCH = 0.01


# ---------- 기록 ----------

def load_history() -> list[dict]:
    path = ROOT / "data" / "history.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save_history(history: list[dict]) -> None:
    path = ROOT / "data" / "history.json"
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def recent_urls(history: list[dict], today: date) -> set[str]:
    cutoff = today - timedelta(days=HISTORY_DAYS)
    urls = set()
    for day in history:
        if date.fromisoformat(day["date"]) >= cutoff and day["date"] != today.isoformat():
            urls.update(job["url"] for job in day["jobs"])
    return urls


def history_text(history: list[dict], today: date) -> str:
    cutoff = today - timedelta(days=HISTORY_DAYS)
    lines = []
    for day in history:
        if date.fromisoformat(day["date"]) >= cutoff and day["date"] != today.isoformat():
            for job in day["jobs"]:
                lines.append(f"- {day['date']} | {job['company']} | {job['title']} | {job['url']}")
    return "\n".join(lines) or "(없음)"


# ---------- Claude 호출 ----------

def build_prompt(today: date, history: list[dict]) -> str:
    profile = os.environ.get("PROFILE") or (ROOT / "config" / "profile.md").read_text(encoding="utf-8")
    template = (ROOT / "config" / "prompt.md").read_text(encoding="utf-8")
    return (
        template.replace("{{TODAY}}", today.isoformat())
        .replace("{{PROFILE}}", profile)
        .replace("{{HISTORY}}", history_text(history, today))
    )


def call_claude(prompt: str) -> tuple[str, dict]:
    import anthropic

    client = anthropic.Anthropic()
    tools = [
        {
            "type": "web_search_20260318",
            "name": "web_search",
            "max_uses": MAX_SEARCHES,
            "user_location": {"type": "approximate", "country": "KR", "timezone": "Asia/Seoul"},
        },
        {"type": "web_fetch_20260318", "name": "web_fetch", "max_uses": MAX_FETCHES},
    ]
    messages = [{"role": "user", "content": prompt}]
    usage = {"input_tokens": 0, "output_tokens": 0, "web_search_requests": 0, "web_fetch_requests": 0}

    for _ in range(MAX_CONTINUATIONS):
        response = client.messages.create(
            model=MODEL, max_tokens=32000, messages=messages, tools=tools
        )
        u = response.usage
        usage["input_tokens"] += (u.input_tokens or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0)
        usage["output_tokens"] += u.output_tokens or 0
        stu = getattr(u, "server_tool_use", None)
        if stu:
            usage["web_search_requests"] += getattr(stu, "web_search_requests", 0) or 0
            usage["web_fetch_requests"] += getattr(stu, "web_fetch_requests", 0) or 0

        if response.stop_reason == "pause_turn":
            # 검색이 길어지면 API가 잠시 멈춘다. 받은 내용을 그대로 돌려보내 이어서 진행한다.
            messages.append({"role": "assistant", "content": response.content})
            continue

        text = "".join(block.text for block in response.content if block.type == "text")
        return text, usage

    raise RuntimeError("Claude 응답이 끝나지 않았습니다 (pause_turn 반복).")


def extract_json(text: str) -> dict:
    blocks = re.findall(r"```json\s*(\{.*?\})\s*```", text, flags=re.S)
    candidate = blocks[-1] if blocks else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(candidate)


# ---------- 가공 ----------

def score_class(total: int) -> str:
    if total >= 70:
        return "s-high"
    if total >= 55:
        return "s-mid"
    return "s-low"


def enrich(report: dict, today: date, seen_urls: set[str]) -> dict:
    for job in report.get("jobs", []):
        s = job.get("scores", {})
        job["total"] = sum(int(s.get(k, 0) or 0) for k in ("experience", "qualification", "domain", "conditions"))
        job["score_class"] = score_class(job["total"])
        job["is_repeat"] = job.get("url") in seen_urls
        job["d_day"] = None
        iso = job.get("deadline_iso")
        if iso:
            try:
                days = (date.fromisoformat(iso) - today).days
                if 0 <= days <= 7:
                    job["d_day"] = days
            except ValueError:
                pass
    report["jobs"] = sorted(report.get("jobs", []), key=lambda j: j.get("priority", 99))

    jobs = report["jobs"]
    deadlines = sorted(j["deadline_iso"] for j in jobs if j.get("deadline_iso"))
    report["kpis"] = {
        "new_count": sum(1 for j in jobs if not j["is_repeat"]),
        "top_score": max((j["total"] for j in jobs), default="-"),
        "nearest_deadline": date.fromisoformat(deadlines[0]).strftime("%m/%d") if deadlines else "-",
    }
    return report


def estimate_cost(usage: dict) -> float:
    return round(
        usage["input_tokens"] / 1e6 * PRICE_INPUT_PER_MTOK
        + usage["output_tokens"] / 1e6 * PRICE_OUTPUT_PER_MTOK
        + usage["web_search_requests"] * PRICE_PER_SEARCH,
        3,
    )


# ---------- 렌더링 ----------

def render(report: dict, today: date, usage: dict, history_checked: bool,
           archive_dates: list[str], prefix: str = "") -> str:
    env = Environment(
        loader=FileSystemLoader(ROOT / "templates"),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("report.html")
    return template.render(
        r=report,
        date_label=f"{today.year}년 {today.month}월 {today.day}일 ({WEEKDAYS[today.weekday()]})",
        usage=usage,
        cost=estimate_cost(usage),
        model=MODEL,
        history_checked=history_checked,
        archive_dates=archive_dates,
        prefix=prefix,
        generated_at=datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", help="API를 부르지 않고 이 JSON 파일로 렌더링만 한다")
    args = parser.parse_args()

    today = datetime.now(KST).date()
    history = load_history()
    seen = recent_urls(history, today)

    if args.sample:
        report = json.loads(Path(args.sample).read_text(encoding="utf-8"))
        usage = {"input_tokens": 0, "output_tokens": 0, "web_search_requests": 0, "web_fetch_requests": 0}
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("ANTHROPIC_API_KEY가 없습니다.", file=sys.stderr)
            return 1
        text, usage = call_claude(build_prompt(today, history))
        try:
            report = extract_json(text)
        except (json.JSONDecodeError, ValueError):
            print("JSON을 읽지 못했습니다. 응답 원문:\n" + text, file=sys.stderr)
            return 1

    report = enrich(report, today, seen)

    docs = ROOT / "docs"
    (docs / "archive").mkdir(parents=True, exist_ok=True)
    dates = {p.stem for p in (docs / "archive").glob("*.html")}
    if not args.sample:
        dates.add(today.isoformat())
    archive_dates = sorted(dates, reverse=True)[:14]
    common = dict(usage=usage, history_checked=bool(history), archive_dates=archive_dates)
    (docs / "index.html").write_text(render(report, today, **common), encoding="utf-8")
    if not args.sample:
        (docs / "archive" / f"{today.isoformat()}.html").write_text(
            render(report, today, prefix="../", **common), encoding="utf-8"
        )

    if not args.sample:
        history = [d for d in history if d["date"] != today.isoformat()]
        history.insert(0, {
            "date": today.isoformat(),
            "model": MODEL,
            "usage": usage,
            "cost_usd": estimate_cost(usage),
            "jobs": [
                {k: j.get(k) for k in ("company", "title", "total", "deadline_text", "url")}
                for j in report["jobs"]
            ],
        })
        save_history(history)

    print(f"완료: 공고 {len(report['jobs'])}건, 추정 비용 ${estimate_cost(usage)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
