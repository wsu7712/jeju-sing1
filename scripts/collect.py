"""제주 1인 세대 살핌판 · 자료 모으기 (GitHub Actions에서 실행)

행정안전부_법정동별(행정동 통반단위) 성/연령별 주민등록 1인세대수 오픈API를 불러
제주 읍면동별 · 성별 · 나이대별 1인 세대 수로 합친 뒤 data/single.json 에 달별로 쌓습니다.

- 인증키는 GitHub Settings > Secrets > Actions 의 PUBLIC_API_KEY 에만 둡니다.
- 결과 파일과 오류 문구에는 키를 넣지 않습니다(*** 로 가림).
- 주민등록 통계는 한 달에 한 번 바뀌므로, 이미 받은 달이면 아무것도 바꾸지 않습니다.

주소 · 요청변수 · 응답 칸 이름은 공공데이터포털 상세 페이지(15108085) 기준으로 맞췄습니다(11/5).
"""
import json, os, sys, time, urllib.parse, urllib.request
from datetime import date

CONFIG = {
    "endpoint": "https://apis.data.go.kr/1741000/stdgSexdAgeOneHh/selectStdgSexdAgeOneHh",
    "params": {
        "srchFrYm": "{ym}",           # 조회 시작 연월 (2022년 10월부터)
        "srchToYm": "{ym}",           # 조회 끝 연월 (석 달 안)
        "regSeCd": "1",               # 1 = 전체 (거주자 + 거주불명자 + 재외국민)
        "type": "JSON",
        "numOfRows": "100",           # 한 쪽에 100줄까지
    },
    # 자료가 없다(NODATA)고 하면 다음 묶음으로 다시 물어봄. 처음 성공한 묶음을 씀.
    # stdgCd: 제주도 5000000000, 제주시 5011000000, 서귀포시 5013000000 / lv: 3 읍면동, 4 통반
    "tries": [
        {"codes": ["5011000000", "5013000000"], "lv": "3"},   # 11/5 실제로 되는 조합
        {"codes": ["5000000000"], "lv": "3"},
        {"codes": ["5011000000", "5013000000"], "lv": "4"},
        {"codes": ["5000000000"], "lv": "4"},
    ],
    "fields": {
        "city": "sggNm",              # 시군구 이름 (제주시, 서귀포시)
        "dong": "dongNm",             # 행정동 이름 (읍면동), 없으면 stdgNm
        "dong_alt": "stdgNm",
        # 응답 칸 이름 → 화면 나이대. 남자 male{N}AgeHhCnt, 여자 feml{N}AgeHhCnt
        "age_cols": {"0": "20세 미만", "10": "20세 미만", "20": "20대", "30": "30대", "40": "40대", "50": "50대", "60": "60대", "70": "70대", "80": "80세 이상", "90": "80세 이상", "100": "80세 이상"},
    },
}
AGES = ["20세 미만", "20대", "30대", "40대", "50대", "60대", "70대", "80세 이상"]
OUT = "data/single.json"
KEEP_MONTHS = 25
KEY = os.environ.get("PUBLIC_API_KEY", "")


def hide(text):
    return str(text).replace(KEY, "***") if KEY else str(text)


def find(obj, key):
    """응답 안 어디에 있든 key 를 찾아 돌려줌 (응답 껍데기 이름이 바뀌어도 동작하게)."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            got = find(v, key)
            if got is not None:
                return got
    elif isinstance(obj, list):
        for v in obj:
            got = find(v, key)
            if got is not None:
                return got
    return None


def fetch_one(ym, code, lv):
    rows, page = [], 1
    while True:
        q = {k: v.replace("{ym}", ym) for k, v in CONFIG["params"].items()}
        q.update({"serviceKey": KEY, "pageNo": str(page), "stdgCd": code, "lv": lv})
        url = CONFIG["endpoint"] + "?" + urllib.parse.urlencode(q)
        for attempt in range(3):  # 공공데이터 서버가 늦게 답하면 세 번까지 다시 물음
            try:
                with urllib.request.urlopen(url, timeout=90) as r:
                    raw = r.read().decode("utf-8", "replace")
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(5)
        try:
            body = json.loads(raw)
        except ValueError:  # 키 오류 등은 XML 로 올 때가 많음
            raise RuntimeError("JSON 이 아닌 응답: " + raw[:300])
        code_ = str(find(body, "resultCode") or "00")
        msg = str(find(body, "resultMsg") or "")
        if "NODATA" in msg.upper() or code_ == "3":
            return []
        if code_ not in ("00", "0", "0000", "INFO-0"):
            raise RuntimeError("결과 코드 " + code_ + " " + msg)
        items = find(body, "item")
        if items is None:
            items = find(body, "items") or []
        if isinstance(items, dict):
            items = [items]
        rows += items
        total = int(find(body, "totalCount") or len(rows))
        if len(rows) >= total or not items:
            return rows
        page += 1
        time.sleep(0.3)


def fetch_month(ym):
    for t in CONFIG["tries"]:
        rows = []
        for code in t["codes"]:
            rows += fetch_one(ym, code, t["lv"])
        print(ym, "stdgCd", "+".join(t["codes"]), "lv", t["lv"], "→", len(rows), "줄")
        if rows:
            print(ym, "줄 살펴보기: 행정동", len({r.get("dongNm") for r in rows}), "/ 법정동", len({r.get("stdgNm") for r in rows}),
                  "/ 리 이름 있는 줄", sum(1 for r in rows if r.get("liNm")), "/ 합계", sum(int(float(r.get("totHhCnt") or 0)) for r in rows))
            return rows
    return []


def to_dong(rows):
    """줄마다 남녀 · 10세 단위 칸을 화면 나이대로 묶어 읍면동별로 합침."""
    f = CONFIG["fields"]
    out = {}
    for r in rows:
        dong = r.get(f["dong"]) or r.get(f["dong_alt"])
        if not dong:
            continue
        d = out.setdefault(dong, {"city": r.get(f["city"]), "M": [0] * len(AGES), "F": [0] * len(AGES)})
        for n, band in f["age_cols"].items():
            i = AGES.index(band)
            for side, pre in (("M", "male"), ("F", "feml")):
                try:
                    d[side][i] += int(float(r.get(f"{pre}{n}AgeHhCnt") or 0))
                except ValueError:
                    pass
    return out


def months_to_try():
    t = date.today().replace(day=1)
    out = []
    for back in (1, 2, 3):  # 지난달 자료가 아직 없으면 그 전 달, 그 전전 달
        y, m = t.year, t.month - back
        while m <= 0:
            y, m = y - 1, m + 12
        out.append(f"{y}{m:02d}")
    return out


def main():
    if not KEY:
        print("PUBLIC_API_KEY 가 없어 자료를 받지 않았습니다. 지금 있는 자료로 보고서만 만듭니다. (Settings > Secrets and variables > Actions)")
        return
    os.makedirs("data", exist_ok=True)
    try:
        data = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        data = {}
    if data.get("sample"):          # 가상 예시 파일이면 비우고 실제 자료로 시작
        data = {}
    data.setdefault("months", {})
    data.update({"sample": False, "ages": AGES,
                 "source": "행정안전부_법정동별(행정동 통반단위) 성/연령별 주민등록 1인세대수 (공공데이터포털)"})

    changed = False

    def get(ym, why):
        nonlocal changed
        try:
            rows = fetch_month(ym)
        except Exception as e:
            print(ym, why, "받기 실패:", hide(e))
            return False
        if not rows:
            print(ym, why, "아직 자료가 없습니다.")
            return False
        data["months"][ym] = to_dong(rows)
        print(ym, why, "저장:", len(data["months"][ym]), "개 읍면동")
        changed = True
        return True

    # 1) 가장 최근 달: 지난달부터 거슬러 올라가며, 이미 받은 달을 만나면 멈춤
    for ym in months_to_try():
        if ym in data["months"] or get(ym, "최근 달"):
            break
    # 2) 보고서는 지난달 · 작년 같은 달과 비교하므로, 빠져 있으면 받음 (지난번에 실패한 달도 여기서 다시)
    if data["months"]:
        ym = max(data["months"])
        y, m = int(ym[:4]), int(ym[4:])
        last = f"{y}{m - 1:02d}" if m > 1 else f"{y - 1}12"
        for extra, why in ((last, "지난달"), (f"{y - 1}{m:02d}", "작년 같은 달")):
            if extra not in data["months"]:
                get(extra, why)
    if not changed:
        return
    for old in sorted(data["months"])[:-KEEP_MONTHS]:
        del data["months"][old]
    data["fetchedAt"] = date.today().isoformat()
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if KEY and KEY in text:
        sys.exit("결과에 키가 섞여 저장하지 않습니다.")
    open(OUT, "w", encoding="utf-8").write(text)


if __name__ == "__main__":
    main()
