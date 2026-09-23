#!/usr/bin/env python
"""실무 전달본을 만든다. 판정 결과 파일만 읽는다 — LLM 을 부르지 않는다.

  python <저장소>/src/handover.py <결과.json>
  python <저장소>/src/handover.py <결과.json> -o 전달본.json

판정과 갈라 둔 이유는 다시 만들 수 있게 하기 위해서다. 문구나 담는 항목이 마음에
안 들면 이것만 다시 돌리면 된다. 판정을 다시 돌리면 호출 수천 번이고, 그때마다
판정이 조금씩 흔들려 앞서 보낸 것과 숫자가 달라진다.

**PYTHONPATH 도 설치도 필요 없다.** run.py 와 같은 이유다 - 이 파일이 src/ 에
있는 것만으로 옆의 ragdiag/ 가 import 된다. 로직은 `ragdiag/features/handover`
에 있고 여기서는 파일만 읽고 쓴다.

run.py 의 venv 전환을 그대로 쓴다. 설정에 paths.venv 를 적어 두고 activate 를
잊었을 때, 진입점마다 다르게 굴면 "저건 되는데 이건 안 된다" 가 된다.
"""

import argparse
import json
import sys
from pathlib import Path

from run import switch_venv


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="판정 결과 파일을 실무 전달용 JSON 으로 바꾼다 (LLM 호출 없음)")
    p.add_argument("result", help="src/run.py 가 낸 결과 JSON")
    p.add_argument("-o", "--out", help="낼 파일 (기본: <결과 이름>_handover.json)")
    args = p.parse_args(argv)

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

    from ragdiag.features import handover

    out = handover.build(result, source=source.name)
    target = Path(args.out) if args.out else source.with_name(source.stem + "_handover.json")
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{target}")
    info = out["대상"]
    print(f"  분석한 턴 {info['분석한 턴']} · "
          f"실패 {info['실패로 판정']} · 정상 {info['정상으로 판정']}")
    print("  [부서별] 실패 많은 순")
    for entry in out["부서별"][:5]:
        top = entry["많은_순"][0] if entry["많은_순"] else {"type": "-", "건수": 0}
        print(f"      {entry['부서']:14} {entry['실패']:4}/{entry['분석한_턴']:<4} "
              f"({entry['실패율']:.0%})  가장 많은 것 {top['type']} {top['건수']}건")
    if len(out["부서별"]) > 5:
        print(f"      … 그 밖에 {len(out['부서별']) - 5}개 부서")
    print("  [분류]")
    for group in out["분류"]:
        print(f"  {group['type']} {group['이름']}  {group['건수']}건")
        for case in group["세부"]:
            print(f"      {case['case']:8} {case['이름']:24} {case['건수']}건")
    if "미분류" in out:
        print(f"  미분류  {out['미분류']['건수']}건")
    return 0


if __name__ == "__main__":
    switch_venv(sys.argv[1:])
    raise SystemExit(main())
