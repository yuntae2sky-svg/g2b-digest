#!/usr/bin/env python3
"""해양수산부(mof.go.kr) 공지사항/입찰/고시공고 1페이지 수집 -> mof.md, mof_state.json.
검증: 진단 HTML(2026-10-11)로 표 구조 확인. 상세 링크 형식은 페이지 내 주석 URL(/doc/ko/selectDoc.do?docSeq=&menuSeq=&bbsSeq=)에서 가져옴(링크 실제 열림은 미검증).
robots.txt: 검색 페이지 하나만 차단, 목록은 허용. 게시판당 1회 요청, 실패 시 최대 3회 재시도."""
import html as H, json, re, sys, time, urllib.request
from datetime import datetime, timedelta, timezone, date

KST = timezone(timedelta(hours=9))
BOARDS = {"공지사항": 375, "입찰": 379, "고시/공고": 877}
LIST_URL = "https://www.mof.go.kr/index.do?menuSeq={}"
KEYWORDS = ["양식", "순환여과", "스마트", "RAS", "사육수조", "친환경", "수산", "어촌", "귀어"]
STATE, OUT = "mof_state.json", "mof.md"
KEEP_DAYS = 14  # 마감일을 모르는 건은 최초 발견 후 14일간 유효 목록에 표시
RAS_WORD = re.compile(r"(?<![A-Za-z])RAS(?![A-Za-z])")


def fetch(url):
    last = None
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "g2b-digest/1.0 (personal research)"})
            return urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
        except Exception as e:
            last = f"{type(e).__name__} {e}"
            time.sleep(5 * (i + 1))
    raise RuntimeError(last)


def parse(page, menu):
    m = re.search(r"selectDoc\.do\?docSeq='\s*\+\s*docSeq\s*\+\s*'&listUpdtDt=[^&]*&menuSeq=(\d+)&bbsSeq=(\d+)", page)
    menu_seq, bbs = (m.group(1), m.group(2)) if m else (str(menu), None)
    rows = []
    body = re.search(r"<tbody.*?</tbody>", page, re.S)
    for r in re.findall(r"<tr.*?</tr>", body.group(0) if body else "", re.S):
        t = re.search(r"fn_selectDoc\('(\d+)'\)[^>]*title=\"\[게시글 바로가기\]\s*(.*?)\"", r, re.S)
        d = re.search(r'class="t-date">\s*(\d{4})\.(\d{2})\.(\d{2})', r)
        if not (t and d):
            continue
        dept = re.search(r'class="ts">\s*(.*?)\s*</td>', r, re.S)
        rows.append({"id": t.group(1), "title": H.unescape(re.sub(r"\s+", " ", t.group(2))).strip(),
                     "posted": date(int(d.group(1)), int(d.group(2)), int(d.group(3))).isoformat(),
                     "dept": re.sub(r"\s+", " ", re.sub(r"<.*?>", "", dept.group(1))).strip() if dept else "",
                     "menu": menu_seq, "bbs": bbs})
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
    title = title.replace("해양수산부", "")  # 기관명 자체에 '수산'이 있어 전 게시글이 걸리는 것을 방지
    return any((RAS_WORD.search(title) if k == "RAS" else k in title) for k in KEYWORDS)


def link(st):
    return f"https://www.mof.go.kr/doc/ko/selectDoc.do?docSeq={st['id']}&menuSeq={st['menu']}&bbsSeq={st['bbs']}"


def main(pages=None, today=None):
    now = datetime.now(KST)
    today = today or now.date()
    try:
        state, first_run = json.load(open(STATE, encoding="utf-8")), False
    except Exception:
        state, first_run = {}, True
    errs, new, open_, soon = [], [], [], []
    for name, menu in BOARDS.items():
        try:
            rows = parse(pages[name] if pages else fetch(LIST_URL.format(menu)), menu)
            if not rows:
                errs.append(f"{name}: 목록 파싱 0건 - 구조 변경 또는 차단 가능성")
        except Exception as e:
            rows = []
            errs.append(f"{name}: 접속 실패 {e}")
        for r in rows:
            if not match(r["title"]):
                continue
            key = f"{r['bbs']}-{r['id']}"
            if key not in state:
                state[key] = {**r, "board": name, "first_seen": today.isoformat()}
                if not first_run:
                    new.append(key)
            state[key]["deadline"] = deadline(r["title"], r["posted"])
    for key, st in state.items():
        dl = st.get("deadline")
        if dl:
            days = (date.fromisoformat(dl) - today).days
            if days < 0:
                continue
            (soon if days <= 3 else open_).append((key, st, days))
        elif (today - date.fromisoformat(st["first_seen"])).days <= KEEP_DAYS:
            open_.append((key, st, None))
    if len(errs) < len(BOARDS):  # 전부 실패했을 때는 상태 파일을 건드리지 않음
        json.dump(state, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)
    def line(key, st, days=None):
        dl = st.get("deadline")
        tag = f"마감 {dl} (D-{days})" if dl else "마감 미확인(본문/첨부 확인 필요)"
        return f"- [{st['board']}] {st['title']} | {st['dept']} | 게시 {st['posted']} | {tag} | {link(st)}"
    out = [f"# 해양수산부 게시판 ({now:%Y-%m-%d %H:%M} KST 생성)", ""]
    if errs:
        out += ["## ⚠ 수집 오류 (결과가 불완전할 수 있음)"] + [f"- {e}" for e in errs] + [""]
    if first_run:
        out += ["(첫 실행: 현재 게시된 건을 기준선으로 등록. '신규'는 다음 실행부터 표시)", ""]
    out += [f"## 신규 ({len(new)}건)"] + [line(k, state[k]) for k in new] + [""]
    out += [f"## 마감임박 D-3 이내 ({len(soon)}건)"] + [line(*x) for x in sorted(soon, key=lambda x: x[2])] + [""]
    out += [f"## 유효 ({len(open_)}건)"] + [line(*x) for x in sorted(open_, key=lambda x: x[1]["posted"], reverse=True)]
    open(OUT, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(f"신규 {len(new)} / 임박 {len(soon)} / 유효 {len(open_)} / 오류 {len(errs)}")


if __name__ == "__main__":
    main()
