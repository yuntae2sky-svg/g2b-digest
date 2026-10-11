#!/usr/bin/env python3
"""나라장터 입찰공고/낙찰 일일 수집 -> latest.md 생성.

환경변수: G2B_KEY (공공데이터포털 일반 인증키, Decoding/Encoding 어느 쪽이든 가능)
오퍼레이션명·파라미터·응답필드는 조달청 참고문서(입찰공고정보서비스 1.2, 낙찰정보서비스 1.2)로 검증함.
미검증: 실제 호출 성공 여부, numOfRows 허용 최대값(문서에 명시 없음, 100으로 페이징).
오류는 숨기지 않고 latest.md에 그대로 기록한다.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
KEY = urllib.parse.unquote(os.environ.get("G2B_KEY", ""))
KEYWORDS = ["순환여과", "스마트양식", "RAS", "양식장", "수처리", "사육수조", "친환경양식"]
BID_LOOKBACK_HOURS = 30   # 공고: 06:30 실행 기준 전일분 + 겹침 여유
AWARD_LOOKBACK_DAYS = 7   # 낙찰: 최근 7일 누적
CATEGORIES = {"물품": "Thng", "용역": "Servc", "공사": "Cnstwk"}
BID_BASE = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfo{c}PPSSrch"
AWARD_BASE = "https://apis.data.go.kr/1230000/as/ScsbidInfoService/getScsbidListSttus{c}PPSSrch"
SEEN_FILE = "seen.json"

errors = []


def call(url, params):
    params = {"ServiceKey": KEY, "type": "json", "numOfRows": 100, **params}
    full = url + "?" + urllib.parse.urlencode(params)
    items, page = [], 1
    while True:
        req = urllib.request.Request(full + f"&pageNo={page}", headers={"User-Agent": "g2b-digest/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = json.loads(r.read().decode("utf-8"))
        except Exception as e:  # 네트워크/파싱 오류는 기록 후 계속
            errors.append(f"{url.rsplit('/', 1)[-1]} {params.get('bidNtceNm')}: {type(e).__name__} {e}")
            return items
        resp = body.get("response", {})
        header = resp.get("header", {})
        if header.get("resultCode") not in ("00", None):
            errors.append(f"{url.rsplit('/', 1)[-1]}: {header.get('resultCode')} {header.get('resultMsg')}")
            return items
        b = resp.get("body", {})
        got = b.get("items") or []
        if isinstance(got, dict):
            got = got.get("item", [])
        items += got
        if page * 100 >= int(b.get("totalCount", 0) or 0):
            return items
        page += 1


def fmt(dt):
    return dt.strftime("%Y%m%d%H%M")


def money(v):
    try:
        return f"{int(float(v)):,}원"
    except (TypeError, ValueError):
        return "-"


def main():
    if not KEY:
        sys.exit("G2B_KEY 환경변수가 없습니다.")
    now = datetime.now(KST)
    try:
        seen = json.load(open(SEEN_FILE, encoding="utf-8"))
    except Exception:
        seen = {}
    cutoff = (now - timedelta(days=14)).strftime("%Y%m%d")
    seen = {k: v for k, v in seen.items() if v >= cutoff}

    bids, awards = {}, {}
    for cat, code in CATEGORIES.items():
        for kw in KEYWORDS:
            for it in call(BID_BASE.format(c=code), {
                "inqryDiv": 1, "bidNtceNm": kw,
                "inqryBgnDt": fmt(now - timedelta(hours=BID_LOOKBACK_HOURS)), "inqryEndDt": fmt(now)}):
                no = it.get("bidNtceNo")
                if no and no not in seen:
                    bids.setdefault(no, {**it, "_cat": cat, "_kw": set()})["_kw"].add(kw)
            # 낙찰: 참고문서 기준 inqryDiv 1=공고게시일시, 2=개찰일시 → 개찰일 기준 7일 누적
            for it in call(AWARD_BASE.format(c=code), {
                "inqryDiv": 2, "bidNtceNm": kw,
                "inqryBgnDt": fmt(now - timedelta(days=AWARD_LOOKBACK_DAYS)), "inqryEndDt": fmt(now)}):
                no = it.get("bidNtceNo")
                if no:
                    awards.setdefault(no, {**it, "_cat": cat, "_kw": set()})["_kw"].add(kw)

    for no in bids:
        seen[no] = now.strftime("%Y%m%d")
    json.dump(seen, open(SEEN_FILE, "w", encoding="utf-8"), ensure_ascii=False)

    out = [f"# 나라장터 입찰·낙찰 요약 ({now:%Y-%m-%d %H:%M} KST 생성)", ""]
    if errors:
        out += ["## ⚠ 수집 오류 (결과가 불완전할 수 있음)"] + [f"- {e}" for e in sorted(set(errors))] + [""]
    out += [f"## 신규 입찰공고 ({len(bids)}건)"]
    for no, it in sorted(bids.items(), key=lambda x: x[1].get("bidClseDt") or ""):
        out.append(f"- [{it['_cat']}] {it.get('bidNtceNm')} | 공고기관 {it.get('ntceInsttNm')} | "
                   f"추정가격 {money(it.get('presmptPrce') or it.get('asignBdgtAmt'))} | 마감 {it.get('bidClseDt')} | "
                   f"{it.get('bidNtceDtlUrl') or it.get('bidNtceUrl') or '-'} (키워드: {', '.join(sorted(it['_kw']))})")
    out += ["", f"## 최근 {AWARD_LOOKBACK_DAYS}일 낙찰 ({len(awards)}건)"]
    for no, it in sorted(awards.items(), key=lambda x: x[1].get("rlOpengDt") or "", reverse=True):
        out.append(f"- [{it['_cat']}] {it.get('bidNtceNm')} | 낙찰자 {it.get('bidwinnrNm')} | "
                   f"낙찰금액 {money(it.get('sucsfbidAmt'))} (낙찰률 {it.get('sucsfbidRate') or '-'}%) | "
                   f"개찰 {it.get('rlOpengDt')} | 공고기관 {it.get('ntceInsttNm')}")
    open("latest.md", "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(f"공고 {len(bids)}건 / 낙찰 {len(awards)}건 / 오류 {len(errors)}건")


if __name__ == "__main__":
    main()
