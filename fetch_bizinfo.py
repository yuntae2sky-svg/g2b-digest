#!/usr/bin/env python3
"""기업마당(bizinfo.go.kr) 지원사업정보 API -> bizinfo.md, bizinfo_state.json.
환경변수 BIZINFO_KEY (기업마당 발급 인증키). 키는 출력/로그에 쓰지 않는다.
검증: 2026-10-11 실서버 응답(200, JSON {"jsonArray":[...]}) 필드 확인 - pblancNm, pblancId, pblancUrl,
 reqstBeginEndDe('YYYY-MM-DD ~ YYYY-MM-DD'), hashtags, jrsdInsttNm, excInsttNm, creatPnttm.
미검증: searchCnt=0(전체, 약 1,400건) 응답의 안정성. 접속 자체가 실행에 따라 불안정하여 재시도/2회 실행 구조를 둠."""
import json, os, re, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone, date

KST = timezone(timedelta(hours=9))
KEY = os.environ.get("BIZINFO_KEY", "")
API = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"
KEYWORDS = ["양식", "순환여과", "스마트양식", "RAS", "사육수조", "친환경양식", "수산", "SEAFOOD", "어촌", "귀어", "어업", "수협"]
# 농림 분야 용어가 '수산/어촌/어업'에 걸리는 오탐을 막기 위해 매칭 전 제거
STRIP = ["해양수산부", "농수산", "농어촌", "농어업", "수산부산물"]
INST_WORDS = ["수협", "어촌어항", "수산과학", "수산자원", "수산업"]  # 해양수산부 소관 전체는 조선/극지 등 비관련 건이 많아 제외
RULES_VERSION = 2  # 매칭 규칙을 바꾸면 올려서 상태를 초기화(기준선 재등록)
STATE, OUT = "bizinfo_state.json", "bizinfo.md"
KEEP_DAYS = 30
RAS_WORD = re.compile(r"(?<![A-Za-z])RAS(?![A-Za-z])")


def fetch():
    q = urllib.parse.urlencode({"crtfcKey": KEY, "dataType": "json", "searchCnt": 0})
    last = None
    for i in range(3):
        try:
            req = urllib.request.Request(f"{API}?{q}", headers={"User-Agent": "g2b-digest/1.0 (personal research)"})
            body = urllib.request.urlopen(req, timeout=90).read().decode("utf-8", "replace")
            data = json.loads(body)
            items = data.get("jsonArray") if isinstance(data, dict) else None
            if items is None:
                raise ValueError("응답에 jsonArray 없음: " + body[:120].replace(KEY, "***") if KEY else body[:120])
            return items
        except Exception as e:
            last = f"{type(e).__name__} {str(e).replace(KEY, '***') if KEY else e}"
            time.sleep(15 * (i + 1))
    raise RuntimeError(last)


def match(it):
    text = (it.get("pblancNm") or "") + " " + (it.get("hashtags") or "")
    for w in STRIP:
        text = text.replace(w, "")
    if any((RAS_WORD.search(text) if k == "RAS" else k in text) for k in KEYWORDS):
        return True
    inst = (it.get("jrsdInsttNm") or "") + " " + (it.get("excInsttNm") or "")
    return any(w in inst for w in INST_WORDS)


def period(it):
    m = re.search(r"(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})", it.get("reqstBeginEndDe") or "")
    return (m.group(1), m.group(2)) if m else (None, None)


def main(items=None, today=None):
    now = datetime.now(KST)
    today = today or now.date()
    # 오늘 이미 성공적으로 생성했으면 2차 실행은 건너뜀 (FORCE=1이면 무시)
    if items is None and not os.environ.get("FORCE"):
        try:
            body = open(OUT, encoding="utf-8").read()
            ver_ok = json.load(open(STATE, encoding="utf-8")).get("_v") == RULES_VERSION
            if ver_ok and f"{today:%Y-%m-%d}" in body.split("\n")[0] and "⚠" not in body:
                print("오늘자 결과가 이미 있어 건너뜀")
                return
        except Exception:
            pass
    if items is None and not KEY:
        sys.exit("BIZINFO_KEY 환경변수가 없습니다.")
    try:
        state, first_run = json.load(open(STATE, encoding="utf-8")), False
        if state.get("_v") != RULES_VERSION:
            state, first_run = {}, True
    except Exception:
        state, first_run = {}, True
    err = None
    try:
        items = items if items is not None else fetch()
        if len(items) < 50:
            err = f"응답 건수 이상({len(items)}건) - 부분 응답 가능성"
    except Exception as e:
        items, err = [], f"접속 실패: {e}"
    new, soon, open_ = [], [], []
    if not err:
        for it in items:
            pid = it.get("pblancId")
            if not pid or not match(it):
                continue
            b, e = period(it)
            if pid not in state:
                state[pid] = {"first_seen": today.isoformat()}
                if not first_run:
                    new.append(pid)
            state[pid].update({"title": it.get("pblancNm"), "url": it.get("pblancUrl"), "inst": it.get("jrsdInsttNm"),
                               "exec": it.get("excInsttNm"), "begin": b, "end": e, "period": it.get("reqstBeginEndDe")})
        state["_v"] = RULES_VERSION
        json.dump(state, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)
    for pid, st in state.items():
        if pid == "_v":
            continue
        if st.get("end"):
            days = (date.fromisoformat(st["end"]) - today).days
            if days < 0:
                continue
            (soon if days <= 3 else open_).append((pid, st, days))
        elif (today - date.fromisoformat(st["first_seen"])).days <= KEEP_DAYS:
            open_.append((pid, st, None))

    def line(pid, st, days=None):
        tag = f"접수 {st['period']} (D-{days})" if st.get("end") else f"접수기간 {st.get('period') or '미확인(상시/별도 확인)'}"
        return f"- {st['title']} | 소관 {st.get('inst') or '-'} / 수행 {st.get('exec') or '-'} | {tag} | {st.get('url')}"

    out = [f"# 기업마당 지원사업 ({now:%Y-%m-%d %H:%M} KST 생성)", ""]
    if err:
        out += [f"## ⚠ 수집 오류: {err}", "(이전 상태 기준 목록이 아래에 표시될 수 있음)", ""]
    if first_run and not err:
        out += ["(첫 실행: 현재 공고 중 키워드 해당 건을 기준선으로 등록. '신규'는 다음 실행부터 표시)", ""]
    out += [f"## 신규 ({len(new)}건)"] + [line(p, state[p]) for p in new] + [""]
    out += [f"## 마감임박 D-3 이내 ({len(soon)}건)"] + [line(*x) for x in sorted(soon, key=lambda x: x[2])] + [""]
    out += [f"## 접수중 ({len(open_)}건)"] + [line(*x) for x in sorted(open_, key=lambda x: (x[1].get('end') or '9'))]
    open(OUT, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(f"전체 {len(items)}건 중 해당 신규 {len(new)} / 임박 {len(soon)} / 접수중 {len(open_)} / 오류 {'있음' if err else '없음'}")


if __name__ == "__main__":
    main()
