#!/usr/bin/env python
"""eval.jsonl 입력 조립의 진입점.

  python <저장소>/src/assemble.py select --eval-jsonl eval.jsonl --filter-data filter.json --out selected.jsonl
  (사내 lookup: selected.jsonl + csv → records.jsonl — docs/assemble.md)
  python <저장소>/src/assemble.py check selected.jsonl records.jsonl
  python <저장소>/src/run.py --conv-data records.jsonl --turns selected.jsonl --output-dir outputs

run.py 와 같은 이유로 여기 있다 - 이 파일이 src/ 에 있으면 옆의 ragdiag/ 가 그대로 import 된다.
"""

import sys

if __name__ == "__main__":
    from run import switch_venv

    switch_venv(sys.argv[1:])

    from ragdiag.assemble import main

    raise SystemExit(main())
