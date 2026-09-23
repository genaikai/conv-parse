#!/usr/bin/env python
"""실무 전달본을 만든다. 판정 결과 파일만 읽는다 — LLM 을 부르지 않는다.

    python tools/handover.py output/2026-09-23_conv_eval_all.json
    python tools/handover.py <결과.json> -o 전달본.json

판정과 갈라 둔 이유는 다시 만들 수 있게 하기 위해서다. 문구나 담는 항목이 마음에
안 들면 이 스크립트만 다시 돌리면 된다. 판정을 다시 돌리면 호출 수천 번이고,
그때마다 판정이 조금씩 흔들려 앞서 보낸 것과 숫자가 달라진다.

`src/` 밖에 두는 이유는 규격 §1.4 가 아니다 - 이건 실행 환경에서도 돌아야 한다.
다만 판정 파이프라인의 일부가 아니라 결과를 다시 담는 도구라서 tools/ 가 맞다.
로직 자체는 `ragdiag/features/handover` 에 있고 여기서는 파일만 읽고 쓴다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from ragdiag.features import handover  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(
        description="판정 결과 파일을 실무 전달용 JSON 으로 바꾼다 (LLM 호출 없음)")
    p.add_argument("result", help="src/run.py 가 낸 결과 JSON")
    p.add_argument("-o", "--out", help="낼 파일 (기본: <결과 이름>_handover.json)")
    args = p.parse_args()

    source = Path(args.result)
    if not source.exists():
        print(f"파일이 없습니다: {source}", file=sys.stderr)
        return 2
    try:
        result = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"JSON 을 읽지 못했습니다: {e}", file=sys.stderr)
        return 2
    if "analysis_results" not in result:
        print("analysis_results 가 없습니다. src/run.py 의 결과 파일이 맞습니까?",
              file=sys.stderr)
        return 2

    out = handover.build(result, source=source.name)
    target = Path(args.out) if args.out else source.with_name(source.stem + "_handover.json")
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{target}")
    target_info = out["대상"]
    print(f"  분석한 턴 {target_info['분석한 턴']} · "
          f"실패 {target_info['실패로 판정']} · 정상 {target_info['정상으로 판정']}")
    for group in out["분류"]:
        print(f"  {group['type']} {group['이름']}  {group['건수']}건")
        for case in group["세부"]:
            print(f"      {case['case']:8} {case['이름']:24} {case['건수']}건")
    if "미분류" in out:
        print(f"  미분류  {out['미분류']['건수']}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
