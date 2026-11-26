"""올팍 나우 pipeline: fetch → parse → baseline forecast → web/data/forecast.json.

Usage:
  CULTURE_API_KEY=... python pipeline/olpark.py fetch      # all pages → data/raw.json
  python pipeline/olpark.py demo                            # synthetic raw (marked demo) for UI work
  python pipeline/olpark.py forecast [--start YYYY-MM-DD]   # data/raw.json → web/data/forecast.json
  python pipeline/olpark.py test                            # self-check
"""
import json, os, sys, random, statistics, time, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw.json"
EVENTS = ROOT / "data" / "events.json"  # [{"date":"YYYY-MM-DD","name":"...","start":19}] upcoming shows
OUT = ROOT / "web" / "data" / "forecast.json"
API = "https://api.kcisa.kr/openapi/API_CPM_009/request"  # culture.go.kr id=675 (data.go.kr 15164822)
HOURS = range(8, 24)
NUM = ("주차대수", "방문객", "기온", "풍향", "강수량", "습도", "공연관람객수")


def parse_item(item):
    """One API item → flat row. DESCRIPTION = '주차대수:..,방문객:.., 기온:..,휴일:..';
    TITLE = '공연명:<name, may hold commas>,공연관람객수:N' (older preview rows packed it all in DESCRIPTION)."""
    row = {"ts": item["ISSUED_DATE"], "공연명": "", "공연관람객수": 0.0}
    title = item.get("TITLE") or ""
    if title.startswith("공연명:"):
        name, _, n = title[4:].rpartition(",공연관람객수:")
        row["공연명"], row["공연관람객수"] = name.strip(), float(n or 0)
    for part in (item.get("DESCRIPTION") or "").split(","):
        k, _, v = part.partition(":")
        k, v = k.strip(), v.strip()
        if k in NUM:
            row[k] = float(v) if v else None
        elif k:
            row[k] = v
    return row


def get(url, tries=5):
    """API allows 1 request / 5 s: wait before each call, back off on 429.
    XML, not JSON: the JSON output drops the CDATA DESCRIPTION (parking + weather)."""
    for i in range(tries):
        time.sleep(5.5 * (i + 1))
        try:
            return ET.fromstring(urllib.request.urlopen(url, timeout=60).read())
        except urllib.error.HTTPError as e:
            if e.code != 429 or i == tries - 1:
                raise
            print(f"429, retry {i + 1}", file=sys.stderr)


def fetch(key, rows=100):
    # ponytail: 100-row pages (~80 calls, ~8 min). A 1000-row page came back with DESCRIPTION
    # empty on every row while 3-row pages were fine; raise rows only after checking it holds.
    items, page = [], 1
    while True:
        q = urllib.parse.urlencode({"serviceKey": key, "numOfRows": rows, "pageNo": page})
        doc = get(f"{API}?{q}")
        batch = [{c.tag: c.text for c in it} for it in doc.iter("item")]
        if batch and not any(i.get("DESCRIPTION") for i in batch):
            sys.exit(f"page {page}: DESCRIPTION (주차대수·날씨) empty in every row — stopping. Try a smaller numOfRows.")
        items += batch
        total = int(doc.findtext(".//totalCount"))
        print(f"page {page}: {len(items)}/{total}", file=sys.stderr)
        if not batch or len(items) >= total:
            return items
        page += 1


def demo_items(days=365, seed=7):
    """Synthetic rows in the API's shape, for building the UI before the key works. Never ship as real."""
    rnd, out, start = random.Random(seed), [], date(2025, 1, 1)
    for d in range(days):
        day = start + timedelta(d)
        show = rnd.random() < (0.35 if day.weekday() >= 5 else 0.12)
        for h in range(24):
            base = 600 + 400 * (day.weekday() >= 5) + 800 * (12 <= h <= 17)  # 2025 real-data scale
            if show and 16 <= h <= 19:
                base += 1500
            cars = max(0, int(rnd.gauss(base, base * 0.15)))
            desc = (f"주차대수:{cars},방문객:{cars*3}, 기온:{rnd.uniform(-5,30):.1f}, 풍향:1.0, 강수량:, "
                    f"습도:50,휴일:,공연명:{'DEMO 공연' if show else ''},공연관람객수:{9000 if show else 0}")
            out.append({"ISSUED_DATE": f"{day} {h:02d}:00:00", "DESCRIPTION": desc})
    return out


SCHEDULE_URL = "https://www.ksponco.or.kr/olympicpark/eventInfo/eventInfoList?mid=a20301010100"
# ponytail: small halls (<~1,500 seats) left out of the "show day" flag; their crowds barely move parking.
BIG_VENUES = ("KSPO DOME", "티켓링크 라이브 아레나", "핸드볼경기장", "올림픽홀", "옥외")
WEEKDAYS = "월화수목금토일"
TIME_RE = r"(오후|오전)?\s*(\d{1,2})\s*(?:시|(PM|pm|AM|am)|:(\d{2}))"


def to_hour(m):
    h = int(m.group(2))
    if (m.group(1) == "오후" or (m.group(3) or "").lower() == "pm") and h < 12:
        h += 12
    return h if 9 <= h <= 23 else None


def first_hour(seg):
    import re
    for m in re.finditer(TIME_RE, seg):
        h = to_hour(m)
        if h: return h
    return None


def parse_hour(text, day):
    """Show start hour on `day` from free text like '금 오후 7시 / 토 오후 6시' or '11월 28일(토) 6PM'.
    None = no show that weekday (text names show days and this isn't one)."""
    import re
    dates = list(re.finditer(r"(\d{1,2})월\s*(\d{1,2})일", text))
    for i, m in enumerate(dates):
        if (int(m.group(1)), int(m.group(2))) == (day.month, day.day):
            end = dates[i + 1].start() if i + 1 < len(dates) else len(text)
            seg = re.sub(r"\d{4}년\s*$", "", text[m.end():end].split("/")[0])
            return first_hour(seg) or 18
    named = {}
    for seg in text.split("/"):
        m = re.match(r"\s*\(?([월화수목금토일]+)\)?\s", seg)
        if m:
            for c in m.group(1):
                named.setdefault(c, first_hour(seg[m.end():]))
    if named:
        return named.get(WEEKDAYS[day.weekday()]) and named[WEEKDAYS[day.weekday()]] or None
    return first_hour(text) or 18


def parse_schedule(page):
    """Official event list page → one entry per show day."""
    import re, html as H
    out = []
    for blk in re.findall(r'<a href="[^"]*evtSeq=(\d+)"[^>]*class="item">([\s\S]*?)</a>', page):
        seq, b = blk
        g = lambda cls: H.unescape(re.sub(r"<[^>]+>", "", (re.search(rf'class="{cls}">([\s\S]*?)</', b) or [None, ""])[1])).strip()
        venue, title, rng, when = g("place"), g("title"), g("date"), g("time")
        m = re.match(r"(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})", rng)
        if not (m and title):
            continue
        d0, d1 = (date.fromisoformat(x) for x in m.groups())
        for i in range(min((d1 - d0).days, 60) + 1):
            day = d0 + timedelta(i)
            h = parse_hour(when, day)
            if h:
                out.append({"date": day.isoformat(), "name": title, "venue": venue, "start": h,
                            "big": any(v in venue for v in BIG_VENUES),
                            "url": f"https://www.ksponco.or.kr/olympicpark/eventInfo/eventInfoView.es?mid=a20301010100&evtSeq={seq}"})
    return out


ARTIST_STOP = {"concert", "tour", "world", "live", "in", "seoul", "the", "fan", "con", "solo", "special", "finale",
               "콘서트", "단독", "서울", "전국투어", "투어", "공연", "기념", "주년", "팬콘서트", "팬미팅", "x"}


def artist_tokens(name):
    import re
    return {t for t in re.findall(r"[A-Za-z]{2,}|[가-힣]{2,}", name.lower()) if t not in ARTIST_STOP}


def past_shows(name, rows):
    """2025 days whose show name shares an artist token with `name` → actual peak cars and hour."""
    want = artist_tokens(name)
    byday = {}
    for r in rows:
        byday.setdefault(r["dt"].date(), []).append(r)
    hits = []
    for d, rs in sorted(byday.items()):
        names = {x["공연명"] for x in rs if x["공연명"]}
        if names and any(want & artist_tokens(n) for n in names):
            top = max(rs, key=lambda x: x["주차대수"])
            hits.append({"date": d.isoformat(), "show": " / ".join(sorted(names)), "peak": round(top["주차대수"]), "peak_hour": top["dt"].hour})
    return hits


def daykey(dt, holiday=False):
    return "weekend" if dt.weekday() >= 5 or holiday else "weekday"


def build_table(rows):
    """Mean cars per (weekday/weekend, hour, show day). Holidays count as weekend.
    ponytail: mean table, no weather term; LightGBM with 기온·강수 features is the upgrade."""
    show_days = {r["dt"].date() for r in rows if r["공연명"]}
    t = {}
    for r in rows:
        t.setdefault((daykey(r["dt"], bool(r.get("휴일"))), r["dt"].hour, r["dt"].date() in show_days), []).append(r["주차대수"])
    return {k: statistics.mean(v) for k, v in t.items()}


def predict(table, dt, show, holiday=False):
    k = daykey(dt, holiday)
    for key in ((k, dt.hour, show), (k, dt.hour, not show)):
        if key in table:
            return table[key]
    return 0.0


def prep(rows):
    """Drop broken collection days. Daily peaks are bimodal: real days peak >= ~1,750 cars,
    broken ones (month-end partial days, most of Aug–Sep, Nov 8–28, Dec 8–31) stay under 750.
    ponytail: fixed 1,000-car / 20-row cut; ask KSPO about the gaps and re-check when data is reloaded."""
    days = {}
    for r in rows:
        if r.get("주차대수") is not None:
            r = dict(r, dt=datetime.fromisoformat(r["ts"]))
            days.setdefault(r["dt"].date(), []).append(r)
    return [r for rs in days.values() if len(rs) >= 20 and max(x["주차대수"] for x in rs) >= 1000 for r in rs]


def backtest(rows):
    """Train Jan–Jul, test Oct–Dec. Compare with naive 'same hour one week earlier'."""
    train = [r for r in rows if r["dt"].month <= 7]
    test = [r for r in rows if r["dt"].month >= 10 and 8 <= r["dt"].hour <= 23]
    table, show_days = build_table(train), {r["dt"].date() for r in rows if r["공연명"]}
    by_ts = {r["dt"]: r["주차대수"] for r in rows}
    err_m, err_n = [], []
    for r in test:
        p = predict(table, r["dt"], r["dt"].date() in show_days, bool(r.get("휴일")))
        n = by_ts.get(r["dt"] - timedelta(days=7))
        if n is None:
            continue
        err_m.append(abs(p - r["주차대수"])); err_n.append(abs(n - r["주차대수"]))
    mae = lambda e: round(statistics.mean(e))
    return {"test": "2025-10~12", "n": len(err_m), "mae_model": mae(err_m), "mae_naive": mae(err_n),
            "mean_cars": round(statistics.mean(r["주차대수"] for r in test))}


def insights(rows):
    m = lambda xs: round(statistics.mean(xs)) if xs else None
    show_days = {r["dt"].date() for r in rows if r["공연명"]}
    wd = [r for r in rows if daykey(r["dt"], bool(r.get("휴일"))) == "weekday"]
    profile = [{"hour": h,
                "show": m([r["주차대수"] for r in wd if r["dt"].hour == h and r["dt"].date() in show_days]),
                "none": m([r["주차대수"] for r in wd if r["dt"].hour == h and r["dt"].date() not in show_days])}
               for h in range(6, 24)]
    we_day = [r for r in rows if r["dt"].weekday() >= 5 and 10 <= r["dt"].hour <= 18]
    byday = {}
    for r in rows:
        byday.setdefault(r["dt"].date(), []).append(r)
    top = sorted(byday.items(), key=lambda kv: -max(x["주차대수"] for x in kv[1]))[:6]
    return {
        "weekday_profile": profile,
        "rain": {"wet": m([r["주차대수"] for r in we_day if r["강수량"]]), "dry": m([r["주차대수"] for r in we_day if not r["강수량"]])},
        "top_days": [{"date": d.isoformat(), "peak": round(max(x["주차대수"] for x in rs)),
                      "peak_hour": max(rs, key=lambda x: x["주차대수"])["dt"].hour,
                      "show": next((x["공연명"] for x in rs if x["공연명"]), "")} for d, rs in top],
        "shows": len({r["공연명"] for r in rows if r["공연명"]}), "show_days": len(show_days),
    }


def forecast(rows, start, events, days=7):
    """Grades = percentile of history (lot capacity isn't in the data).
    ponytail: swap for real 만차 thresholds from 15164156 (혼잡도 라벨) once joined."""
    rows = prep(rows)
    if not rows:
        sys.exit("no 주차대수 values in data/raw.json — re-run fetch")
    table = build_table(rows)
    cars_all = sorted(r["주차대수"] for r in rows)
    p70, p90 = (cars_all[int(len(cars_all) * q)] for q in (0.7, 0.9))
    ev = {}
    for e in events:
        ev.setdefault(e["date"], []).append(e)
    out = []
    for d in range(days):
        day = start + timedelta(d)
        es = ev.get(day.isoformat(), [])
        big = [e for e in es if e.get("big", True)]
        hours = []
        for h in HOURS:
            cars = round(predict(table, datetime(day.year, day.month, day.day, h), bool(big)))
            hours.append({"hour": h, "cars": cars, "grade": "만차" if cars >= p90 else "혼잡" if cars >= p70 else "원활"})
        out.append({"date": day.isoformat(), "event": " · ".join(e["name"] for e in big) or None,
                    "start": min((e["start"] for e in big), default=None), "hours": hours,
                    "events": [dict(e, history=past_shows(e["name"], rows)) for e in es]})
    return {"generated": datetime.now().isoformat(timespec="minutes"), "thresholds": {"혼잡": p70, "만차": p90},
            "history_rows": len(rows), "days": out, "backtest": backtest(rows), "insights": insights(rows),
            "events_sample": any(e.get("sample") for e in events)}


def test():
    item = {"ISSUED_DATE": "2025-12-31 14:00:00",
            "DESCRIPTION": "주차대수:19,방문객:57, 기온:-3.4, 풍향:3.6, 강수량:, 습도:27,휴일:,공연명:,공연관람객수:0"}
    r = parse_item(item)
    assert r["주차대수"] == 19 and r["기온"] == -3.4 and r["강수량"] is None and r["공연명"] == "", r
    live = {"ISSUED_DATE": "2025-07-04 19:00:00", "TITLE": "공연명:A, B TOUR IN SEOUL,공연관람객수:10000",
            "DESCRIPTION": "주차대수:457,방문객:2285, 기온:1.2, 풍향:1.6, 강수량:, 습도:66,휴일:신정"}
    r = parse_item(live)
    assert r["공연명"] == "A, B TOUR IN SEOUL" and r["공연관람객수"] == 10000 and r["주차대수"] == 457 and r["휴일"] == "신정", r
    rows = [parse_item(i) for i in demo_items(365)]
    f = forecast(rows, date(2025, 3, 1), [{"date": "2025-03-01", "name": "X", "start": 18}])
    sat, mon = f["days"][0], f["days"][2]
    assert sat["event"] == "X" and len(f["days"]) == 7
    peak = max(h["cars"] for h in sat["hours"])
    assert peak > max(h["cars"] for h in mon["hours"]), "show day should forecast more cars"
    assert any(h["grade"] == "만차" for h in sat["hours"])
    # schedule time parsing (texts copied from the official event list)
    fri, sat_, sun, mon_ = date(2026, 11, 27), date(2026, 11, 28), date(2026, 11, 29), date(2026, 11, 30)
    t = "2026년 11월 27일(금) 오후 7시 2026년 11월 28일(토) 오후 6시 2026년 11월 29일(일) 오후 5시"
    assert (parse_hour(t, fri), parse_hour(t, sat_), parse_hour(t, sun)) == (19, 18, 17)
    t = "2026년 11월 27일(금) 8PM / 2026년 11월 28일(토) 6PM / 2026년 11월 29일(일) 5PM"
    assert (parse_hour(t, fri), parse_hour(t, sun)) == (20, 17)
    t = "금 오후 7시 / 토 오후 6시 / 일 오후 5시"
    assert (parse_hour(t, fri), parse_hour(t, sat_)) == (19, 18)
    t = "수목금 19시 30분 / 토 15시, 19시 / 일 14시 (일자별 공연 시간 변동 있으며, 상세페이지 참고 부탁드립니다. )"
    assert (parse_hour(t, fri), parse_hour(t, sat_), parse_hour(t, mon_)) == (19, 15, None)
    assert artist_tokens("IVE WORLD TOUR [SHOW WHAT I AM]") & artist_tokens("2025 IVE THE 3RD FAN CONCERT")
    print("ok")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"
    if cmd == "test":
        test()
    elif cmd in ("fetch", "demo"):
        items = fetch(os.environ["CULTURE_API_KEY"]) if cmd == "fetch" else demo_items()
        RAW.write_text(json.dumps({"demo": cmd == "demo", "items": items}, ensure_ascii=False))
        print(f"{len(items)} items → {RAW}")
    elif cmd == "schedule":
        page = urllib.request.urlopen(SCHEDULE_URL, timeout=60).read().decode("utf-8", "ignore")
        evs = parse_schedule(page)
        EVENTS.write_text(json.dumps(evs, ensure_ascii=False, indent=1))
        print(f"{len(evs)} show-days → {EVENTS}")
    elif cmd == "forecast":
        raw = json.loads(RAW.read_text())
        start = date.fromisoformat(sys.argv[3]) if "--start" in sys.argv else date.today()
        events = json.loads(EVENTS.read_text()) if EVENTS.exists() else []
        f = forecast([parse_item(i) for i in raw["items"]], start, events)
        f["demo"] = raw["demo"]
        OUT.write_text(json.dumps(f, ensure_ascii=False, indent=1))
        print(f"forecast {start} → {OUT}")
