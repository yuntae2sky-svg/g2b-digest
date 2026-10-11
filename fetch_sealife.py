#!/usr/bin/env python3
"""귀어귀촌종합센터(sealife.go.kr) 공지사항 1페이지 수집 -> sealife.md, sealife_state.json.
검증: 진단 HTML로 표 구조 확인(제목/날짜/글번호). 미검증: 2페이지 이상 조회, 실서버 반복 호출 안정성.
robots.txt: /board/ 는 허용(2026-10-11 확인). 요청은 1회(실패 시 최대 3회 재시도)."""
import json, os, re, sys, time, urllib.request
from datetime import datetime, timedelta, timezone, date

KST = timezone(timedelta(hours=9))
URL = "https://www.sealife.go.kr/board/notice/list.do"
VIEW = "https://www.sealife.go.kr/board/notice/view.do?selectedId={}"
# 수산 전문기관 공지이므로 양식 관련 어휘를 넓게 허용 (사용자 결정: 관련기관 한정 허용)
KEYWORDS = ["양식", "순환여과", "스마트", "RAS", "사육수조", "수산"]
STATE = "sealife_state.json"
OUT = "sealife.md"
RAS_WORD = re.compile(r"(?<![A-Za-z])RAS(?![A-Za-z])")


def fetch():
    last = None
    for i in range(3):
        try:
            req = urllib.request.Request(URL, headers={"User-Agent": "g2b-digest/1.0 (personal research)"})
            return urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
        except Exception as e:
            last = f"{type(e).__name__} {e}"
            time.sleep(5 * (i + 1))
    raise RuntimeError(last)


def parse(html):
    rows = []
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        t = re.search(r"fnView\('(\d+)'\)[^>]*>(.*?)</a>", r, re.S)
        d = re.search(r"(\d{2})-(\d{2})-(\d{2})", r)
        if not (t and d):
            continue
        title = re.sub(r"\s+", " ", re.sub(r"<.*?>", "", t.group(2))).strip()
        posted = date(2000 + int(d.group(1)), int(d.group(2)), int(d.group(3)))
        rows.append({"id": t.group(1), "title": title, "posted": posted.isoformat()})
    return rows


def deadline(title, posted):
    m = re.search(r"~\s*(\d{1,2})\.\s*(\d{1,2})", title)
    if not m:
        return None
    p = date.fromisoformat(posted)
    try:
        dl = date(p.year, int(m.group(1)), int(m.group(2)))
        if dl < p - timedelta(days=30):
            dl = date(p.year + 1, dl.month, dl.day)
        return dl.isoformat()
    except ValueError:
        return None


def match(title):
    for k in KEYWORDS:
        if k == "RAS":
            if RAS_WORD.search(title):
                return True
        elif k in title:
            return True
    return False


def main(html=None, today=None):
    now = datetime.now(KST)
    today = today or now.date()
    try:
        state = json.load(open(STATE, encoding="utf-8"))
        first_run = False
    except Exception:
        state, first_run = {}, True
    err = None
    try:
        rows = parse(html if html is not None else fetch())
        if not rows:
            err = "목록 파싱 결과 0건 - 사이트 구조 변경 또는 차단 가능성"
    except Exception as e:
        rows, err = [], f"접속 실패: {e}"
    new, open_, soon = [], [], []
    if not err:
        for r in rows:
            if not match(r["title"]):
                continue
            dl = deadline(r["title"], r["posted"])
            if r["id"] not in state:
                state[r["id"]] = {"first_seen": today.isoformat(), "title": r["title"], "posted": r["posted"], "deadline": dl}
                if not first_run:
                    new.append(r["id"])
            st = state[r["id"]]
            st["deadline"] = dl
        # 유효 목록: 마감 미경과, 또는 마감 미확인이면 게시 30일 이내
        for i, st in state.items():
            dl = st.get("deadline")
            if dl:
                days = (date.fromisoformat(dl) - today).days
                if days < 0:
                    continue
                (soon if days <= 3 else open_).append((i, st, days))
            elif (today - date.fromisoformat(st["posted"])).days <= 30:
                open_.append((i, st, None))
        json.dump(state, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)
    out = [f"# 귀어귀촌종합센터 공지 ({now:%Y-%m-%d %H:%M} KST 생성)", ""]
    if err:
        out += [f"## ⚠ 수집 오류: {err}", ""]
    if first_run and not err:
        out += ["(첫 실행: 현재 게시 중인 건을 기준선으로 등록. '신규'는 다음 실행부터 표시)", ""]

    def line(i, st, days=None):
        dl = st.get("deadline")
        tag = f"마감 {dl} (D-{days})" if dl else "마감 미확인(제목에 없음, 본문/첨부 확인 필요)"
        return f"- {st['title']} | 게시 {st['posted']} | {tag} | {VIEW.format(i)}"

    out += [f"## 신규 ({len(new)}건)"] + [line(i, state[i]) for i in new] + [""]
    out += [f"## 마감임박 D-3 이내 ({len(soon)}건)"] + [line(*x) for x in sorted(soon, key=lambda x: x[2])] + [""]
    out += [f"## 접수중/유효 ({len(open_)}건)"] + [line(*x) for x in sorted(open_, key=lambda x: (x[1].get('deadline') or '9'))]
    open(OUT, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(f"신규 {len(new)} / 임박 {len(soon)} / 유효 {len(open_)} / 오류 {'있음' if err else '없음'}")


if __name__ == "__main__":
    main()
