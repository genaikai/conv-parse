#!/usr/bin/env bash
# 요구 확인기(ragdiag/requests.py)를 재는 외부 데이터셋을 내려받는다.
#
# 우리 골든셋은 양성 표본이 형식 10 · 언어 3 · 길이 3 뿐이고, 그 표현을 보고 쓴
# 정규식이 그 셋에서 100% 를 내는 것은 아무것도 증명하지 않는다. 우리가 손대지
# 않은 한국어 지시문으로 재야 과적합이 드러난다.
#
# allganize/IFEval-Ko — 342건. 한국어 프롬프트에 instruction_id_list 라벨이 붙어
# 있다. Apache-2.0, 인증 없이 받는다.
#
# 실행 환경(에어갭)에서는 못 받는다. 그래서 사본을 tests/data/ 에 함께 커밋하고,
# 이 스크립트는 갱신할 때만 쓴다. 파일이 없으면 tests/test_requests.py 의 외부
# 데이터 테스트만 건너뛰고 나머지는 그대로 돈다.
set -eu
cd "$(dirname "$0")/.."
mkdir -p tests/data

# 검증셋(dev) 과 테스트셋(test) 을 가른다. dev 는 보면서 패턴을 고치는 셋이고,
# test 는 한 번도 안 보고 일반화만 재는 셋이다. 같은 IFEval 원문을 다른 팀이
# 따로 번역해서 한국어 표현이 독립이다 - 특정 번역체에 맞춘 것인지가 드러난다.
python3 - <<'PY'
import json, os, ssl, urllib.request
try:
    import certifi
    ctx = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    ctx = None      # 시스템 인증서가 있으면 그대로 쓴다

# key 필드 이름이 셋마다 다르다. 담는 모양은 셋 다 같게 맞춘다.
SETS = [
    ("tests/data/ifeval_ko.json",
     "allganize%2FIFEval-Ko", "default", "train", "key", "검증"),
    ("tests/data/ifeval_ko_heldout.json",
     "danish-foundation-models%2Fmulti-ifeval", "ko", "test", "key", "검증"),
    ("tests/data/ifeval_ko_dk.json",
     "davidkim205%2Fko-ifeval", "default", "train", "id", "검증"),
    # 이 셋만 테스트용이다. 홀수 key 절반은 패턴을 고칠 때 보지 않는다.
    ("tests/data/ifeval_ko_snu.json",
     "thunder-research-group%2FSNU_Ko-IFEval", "default", "test", "key", "테스트"),
]

# 뒤 둘은 승인이 필요하다. huggingface.co 에서 데이터셋 페이지의 동의 버튼을 누르고
# settings/tokens 에서 read 토큰을 만들어 HF_TOKEN 으로 준다.
TOKEN = os.environ.get("HF_TOKEN", "")
HEADERS = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}

for path, dataset, config, split, keyfield, role in SETS:
    rows, off = [], 0
    while True:
        url = ("https://datasets-server.huggingface.co/rows"
               f"?dataset={dataset}&config={config}&split={split}"
               f"&offset={off}&length=100")
        page = json.load(urllib.request.urlopen(
            urllib.request.Request(url, headers=HEADERS), timeout=90, context=ctx))
        got = [{"key": r["row"][keyfield], "prompt": r["row"]["prompt"],
                "instruction_id_list": r["row"]["instruction_id_list"]}
               for r in page.get("rows", [])]
        rows += got
        off += len(got)
        if not got or off >= page.get("num_rows_total", 0):
            break
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)
    print(f"{role}셋 {len(rows)}건 -> {path}")
PY
