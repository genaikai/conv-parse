#!/usr/bin/env bash
#
# {BB} → {AA} 이식 스크립트. 실행 위치에 따라 두 모드로 동작한다.
#
#   개발 ({BB} 저장소 루트에서)   bash scripts/sync.sh <tag>
#       → 태그의 archive 를 임시로 풀어 점검만 한다. push 전에 돌린다
#
#   운영 ({AA} 루트에서)           bash .staging/{BB}/scripts/sync.sh <tag>
#       → 이식(교체·VERSION·디렉터리)을 하고 같은 점검을 한 번 더 한다
#
# {AA}·{BB} 의 실제 이름은 프로젝트마다 다르다. {BB} 는 이 스크립트의 위치에서 유도하고
# ({AA}/.staging/{BB}/scripts/sync.sh), {AA} 는 실행 위치(cwd)라 이름이 필요 없다.
#
# 이 스크립트는 실행 도중 checkout 으로 자기 자신을 바꿀 수 있으므로, 본문 전체를
# main() 으로 감싸 파싱이 먼저 끝나게 한다. (bash 는 스크립트를 조금씩 읽어가며 실행한다)

set -euo pipefail

SELF_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
REPO_DIR=$(dirname "$SELF_DIR")
NAME=$(basename "$REPO_DIR")
STAGING=".staging/$NAME"
DEST="$NAME"

DATA_EXT='csv|tsv|parquet|xlsx|xls|pkl|pickle|npy|npz|h5|feather|sqlite'
# 이식 표면에 남아서는 안 되는 것들 — .gitattributes 의 export-ignore 로 빼야 한다
FORBIDDEN=(.git .gitattributes .github .claude .cursor .mcp.json CLAUDE.md AGENTS.md
           tools requirements-dev.txt docs/insights)

# 자기 본문의 지문. checkout 이 자신을 갈아치웠는지 보는 데 쓴다.
sum_self() { cksum < "${BASH_SOURCE[0]}"; }

log()  { printf '[sync] %s\n' "$*"; }
warn() { printf '[sync] ⚠ %s\n' "$*" >&2; }
die()  { printf '[sync] ✗ %s\n' "$*" >&2; exit 1; }

# YAML 의 키를 점 경로로 뽑는다. 2칸 들여쓰기 매핑을 가정하며, 새 키 알림 용도의 근사치다.
yaml_keys() {
  awk '
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*$/ { next }
    /^[[:space:]]*-/ { next }
    {
      line = $0
      match(line, /^[[:space:]]*/); indent = RLENGTH
      sub(/^[[:space:]]*/, "", line)
      if (line ~ /^[A-Za-z0-9_.-]+[[:space:]]*:/) {
        key = line; sub(/[[:space:]]*:.*/, "", key)
        lvl = int(indent / 2)
        path[lvl] = key
        out = path[0]
        for (i = 1; i <= lvl; i++) out = out "." path[i]
        print out
      }
    }
  ' "$1" | sort -u
}

# C9 예외. scripts/sync-allow.txt 의 문구를 담고 있는 줄을 걸러낸다.
#
#   - **고정 문구다. 정규식이 아니다** (grep -F). `.*` 로 전부 열 수 없다
#   - 여덟 바이트 미만은 거부한다. 짧은 조각은 뜻하지 않은 줄까지 열어버린다.
#     글자가 아니라 바이트로 세는 것은 awk 의 length() 가 로케일 없이는 바이트를
#     세기 때문이다. 글자로 재려면 UTF-8 로케일이 있어야 하는데, 없는 환경에서
#     조용히 바이트로 떨어지면 가드가 **약해지는** 쪽으로 틀린다. 바이트 수는
#     언제나 글자 수 이상이라 이쪽으로 세면 틀려도 엄격해지는 쪽이다
#     (여덟 바이트 = 한글 세 글자 · 영문 여덟 글자)
#   - 파일이 없으면 아무것도 안 거른다. 예외를 쓰지 않는 프로젝트가 기본이다
#
# 이 파일은 프로젝트가 만든다. 스캐폴드는 자리만 안다.
c9_allowed() {
  local f="$REPO_DIR/scripts/sync-allow.txt" pat
  if [[ ! -f "$f" ]]; then cat; return; fi
  pat=$(grep -vE '^[[:space:]]*(#|$)' "$f" || true)
  local short
  short=$(printf '%s\n' "$pat" | awk 'length($0) > 0 && length($0) < 8')
  if [[ -n "$short" ]]; then
    warn "sync-allow.txt 에 너무 짧은 문구가 있어 무시한다 (8바이트 이상만):"
    printf '      %s\n' "$short" >&2
  fi
  pat=$(printf '%s\n' "$pat" | awk 'length($0) >= 8')
  if [[ -z "$pat" ]]; then cat; return; fi
  grep -vF -f <(printf '%s\n' "$pat") || true
}

# 트리 안을 훑되 자기 자신(scripts/sync.sh)은 제외하고, 경로를 트리 기준 상대 경로로 줄인다.
scan() {  # scan <dir> <regex>
  grep -rInE "$2" "$1" 2>/dev/null | grep -v "^$1/scripts/sync\.sh:" | sed "s|^$1/||" || true
}

# 이식 표면 점검. 인자로 받은 디렉터리는 "실제로 운영 환경에 도착할 것"이어야 한다.
# 두 모드가 이 함수를 공유하므로 검사 기준이 한 벌뿐이다.
inspect_tree() {
  local d="$1" bad=0 hits f

  for f in "${FORBIDDEN[@]}"; do
    if [[ -e "$d/$f" ]]; then
      warn "이식 표면에 남아있음: $f   → .gitattributes 에 '$f export-ignore' 추가"
      bad=1
    fi
  done

  hits=$(find "$d" -type f | grep -Ei "\.($DATA_EXT)\$" | sed "s|^$d/||" || true)
  if [[ -n "$hits" ]]; then
    warn "데이터 파일:"; printf '%s\n' "$hits" >&2; bad=1
  fi

  hits=$(scan "$d" '^[[:space:]]*(import|from)[[:space:]]+(anthropic|openai)')
  if [[ -n "$hits" ]]; then
    warn "운영 환경에서 쓸 수 없는 API import (C8):"; printf '%s\n' "$hits" >&2; bad=1
  fi

  if [[ -f "$d/requirements.txt" ]]; then
    hits=$(grep -inE '^[[:space:]]*(anthropic|openai|claude)' "$d/requirements.txt" || true)
    if [[ -n "$hits" ]]; then
      warn "requirements.txt 에 개발 전용 패키지:"; printf '%s\n' "$hits" >&2; bad=1
    fi
  fi

  hits=$(scan "$d" '/(Users|home)/[A-Za-z0-9._-]+')
  if [[ -n "$hits" ]]; then
    warn "개인 머신 절대 경로 (§1.3 위반이기도 하다 — 인자로 빼라):"; printf '%s\n' "$hits" >&2; bad=1
  fi

  # RFC 2606 이 실제로 존재할 수 없게 예약해 둔 도메인은 뺀다. 민감정보를 찾는
  # 프로그램이라면 이메일 꼴의 표본이 있어야 자기 규칙을 시험할 수 있는데, 전부
  # 막으면 그 표본을 둘 자리가 없어져 규칙이 죽었는지 알 수 없게 된다.
  # 줄이 아니라 주소 단위로 지운 뒤 다시 본다 — 줄로 거르면 예약 주소와 실제
  # 주소가 한 줄에 있을 때 둘 다 놓친다.
  hits=$(scan "$d" 'Co-Authored-By|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' | awk '
    {
      line = $0
      gsub(/[A-Za-z0-9._%+-]+@(example\.(com|net|org)|[A-Za-z0-9.-]*\.(example|invalid|test))/, "", line)
      if (line ~ /Co-Authored-By/ || line ~ /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z][A-Za-z]/) print
    }')
  if [[ -n "$hits" ]]; then
    warn "이메일·커밋 트레일러:"; printf '%s\n' "$hits" >&2; bad=1
  fi

  # 사본은 평범한 프로그램으로 보여야 한다 (C9). 코드 주석·독스트링에 워크플로
  # 어휘가 남으면 파일 단위 제외로는 못 뺀다 — 코드는 가야 하기 때문이다.
  #
  # 도메인 어휘가 이 목록과 겹치는 프로젝트가 있다. 문서 반출 심사를 다루는
  # 프로그램의 합성 데이터에는 "외부 반출은 보안심의를 거친다" 가 들어가고,
  # 그건 워크플로가 아니라 그 프로그램이 판정하는 대상이다. 그런 프로젝트는
  # scripts/sync-allow.txt 에 문구를 적어 그 줄만 뺀다 (형식은 아래 c9_allowed).
  local raw exempt
  raw=$(scan "$d" '개발 장비|운영 장비|운영 환경|이식|반입|스캐폴드|규격|인사이트|반출|\{AA\}|\{BB\}|규격 §|sync\.sh|\.staging')
  hits=$(printf '%s' "$raw" | c9_allowed)
  exempt=$(( $(printf '%s' "$raw" | grep -c . || true) - $(printf '%s' "$hits" | grep -c . || true) ))
  # 예외로 넘긴 줄은 **반드시 화면에 센다.** 조용히 넘기면 목록이 자라도 아무도
  # 모르고, 그때부터 이 점검은 통과 도장일 뿐이다.
  [[ $exempt -gt 0 ]] && log "C9: $exempt 줄을 예외로 넘김 (scripts/sync-allow.txt)"
  if [[ -n "$hits" ]]; then
    warn "사본에 워크플로 어휘가 남아있음 (C9):"; printf '%s\n' "$hits" >&2; bad=1
  fi

  return $bad
}

require_tag() {
  local repo="$1" tag="$2"
  if ! git -C "$repo" rev-parse -q --verify "refs/tags/$tag^{}" >/dev/null; then
    warn "태그 '$tag' 가 없습니다. 사용 가능한 태그:"
    git -C "$repo" tag -l >&2
    exit 1
  fi
}

# 개발 장비 — archive 결과를 임시로 풀어 점검만 한다
preflight() {
  local tag="$1"
  require_tag "$REPO_DIR" "$tag"
  local sha; sha=$(git -C "$REPO_DIR" rev-parse --short "$tag^{}")
  local tmp; tmp=$(mktemp -d)
  # 값을 지금 확정해 둔다 — 함수를 벗어난 뒤 트랩이 돌 때 $tmp 는 이미 사라지고 없다
  trap "rm -rf '$tmp'" EXIT

  git -C "$REPO_DIR" archive "$tag" | tar -x -C "$tmp"
  log "preflight: $tag ($sha) — $(find "$tmp" -type f | wc -l | tr -d ' ') files"

  if ! inspect_tree "$tmp"; then
    die "preflight FAILED — 위 항목을 고치고 태그를 다시 내세요"
  fi
  log "preflight: OK"
  cat <<EOF

next:
  git push origin $tag
EOF
}

# 운영 환경 — 이식하고 같은 점검을 한 번 더 한다
sync_into_aa() {
  local tag="$1"

  [[ -f .staging/.gitignore ]] || printf '*\n' > .staging/.gitignore

  # 이 스크립트가 만드는 것은 이 스크립트가 막는다. env.yaml 은 실값을 채우라고
  # 만들어 놓고 무시 목록에 안 넣으면, 채운 순간 그대로 커밋된다 - 사람이 잊으면
  # 끝인 자리를 사람에게 맡기지 않는다.
  #
  # env.example.yaml 은 일부러 뺀다. 실값이 없고, 어떤 키가 있는지 남는 편이 낫다.
  local ig
  # venv 는 여기서 만들지 않지만, 작업 폴더에 만드는 사람이 많고 한 번 커밋되면
  # 수천 파일이 히스토리에 박힌다. 되돌리기 가장 비싼 사고라 미리 막는다.
  for ig in '.staging/' 'configs/env.yaml' 'outputs/' 'notebooks/' \
            '.venv/' 'venv/' '__pycache__/'; do
    if [[ ! -f .gitignore ]] || ! grep -qxF "$ig" .gitignore; then
      printf '%s\n' "$ig" >> .gitignore
      log "$(basename "$(pwd -P)")/.gitignore 에 $ig 추가"
    fi
  done

  git -C "$STAGING" fetch --tags --quiet
  require_tag "$STAGING" "$tag"

  # checkout 은 이 스크립트 자신도 갈아치운다. bash 는 이미 읽어들인 옛 본문으로
  # 계속 돌기 때문에, 그대로 두면 "한 번 더 실행해야 새 동작이 나오는" 상태가 된다.
  # 바뀌었으면 새 본문으로 다시 시작한다 - exec 라 이 프로세스가 대체되고 인자와
  # cwd 가 보존된다. 아직 아무것도 바꾸지 않았으므로 잃을 것이 없다.
  local before; before=$(sum_self)
  git -C "$STAGING" -c advice.detachedHead=false checkout --quiet "$tag"
  if [[ -z "${SYNC_RESTARTED:-}" && "$(sum_self)" != "$before" ]]; then
    log "스크립트가 $tag 의 것으로 바뀌었습니다. 새 본문으로 다시 시작합니다"
    SYNC_RESTARTED=1 exec bash "${BASH_SOURCE[0]}" "$tag"
  fi

  local sha; sha=$(git -C "$STAGING" rev-parse --short HEAD)

  [[ ! -e "$DEST/.git" ]] || die "$DEST 에 .git 이 있습니다. clone 인지 확인하고 직접 정리하세요 (자동 삭제하지 않습니다)"

  # 교체 전에 봐 둔다. rm -rf 뒤에 물으면 언제나 없다고 나온다.
  local had_config=0
  [[ -f "$DEST/configs/env.yaml" ]] && had_config=1

  rm -rf "$DEST"; mkdir -p "$DEST"
  git -C "$STAGING" archive "$tag" | tar -x -C "$DEST"
  printf '%s %s\n' "$tag" "$sha" > "$DEST/VERSION"
  log "tag $tag ($sha)"
  log "$DEST/ replaced ($(find "$DEST" -type f | wc -l | tr -d ' ') files)"

  mkdir -p outputs notebooks

  # 설정은 **언제나 {AA} 에 둔다.** $DEST 안에 두면 다음 교체 때 통째로 지워진다.
  # 경로를 상대로 찍으면 어느 configs 인지 알 수 없어서 - 사본에도 configs/ 가
  # 있다 - 전부 절대 경로로 말한다.
  # 예시는 중계 clone 에서 읽는다. 사본에는 configs/ 가 아예 없다 — 런타임에
  # 아무도 안 읽는 폴더라, 두면 "여기 채우면 되나" 하는 오해만 만든다.
  # clone 은 방금 이 태그로 checkout 했으므로 버전도 맞다.
  local ex="$STAGING/configs/env.example.yaml" here; here=$(pwd -P)
  if [[ -f "$ex" ]]; then
    mkdir -p configs

    # 예시를 실값 파일 옆에 둔다. 키 설명이 이 파일 주석에 있어서, 채우는 사람이
    # 사본 안까지 들어가지 않아도 된다.
    #
    # **매번 덮어쓴다.** 실값이 없는 파일이라 잃을 것이 없고, 안 덮으면 저장소에
    # 키가 늘어도 여기 것은 낡은 채 남아 "예시에 없는 키" 를 찾게 만든다.
    cp "$ex" configs/env.example.yaml

    if [[ ! -f configs/env.yaml ]]; then
      # 옛 이름을 쓰던 작업 폴더가 있다. 그대로 두면 채워둔 실값이 무시된 채
      # 빈 env.yaml 로 돌아서, 설정을 고쳤는데 안 먹는 상태가 된다.
      # 자동으로 옮기지 않는다 - 실값이 든 유일한 파일이라 사람이 확인해야 한다.
      if [[ -f configs/local.yaml ]]; then
        warn "$here/configs/local.yaml 이 있습니다. 이름이 env.yaml 로 바뀌었습니다:"
        warn "    mv $here/configs/local.yaml $here/configs/env.yaml"
      fi
      cp "$ex" configs/env.yaml
      log "생성 — 운영 실값을 채우세요: $here/configs/env.yaml"
      log "  키 설명은 옆의 env.example.yaml 에 있습니다"
    else
      log "그대로 둡니다 (실값이 든 파일): $here/configs/env.yaml"
      local missing
      missing=$(comm -23 <(yaml_keys "$ex") <(yaml_keys configs/env.yaml) | tr '\n' ' ')
      missing="${missing%"${missing##*[! ]}"}"
      [[ -z "$missing" ]] || warn "env.example.yaml 에만 있는 키: $missing"
    fi
    # 사본 안에 설정을 만들어 둔 경우. 방금 지워졌다는 사실을 알려야 한다 -
    # 안 그러면 다음 실행에서 "설정을 고쳤는데 안 먹는" 상태가 된다.
    if [[ "$had_config" == 1 ]]; then
      warn "$DEST/configs/env.yaml 이 있었는데 방금 교체로 사라졌습니다."
      warn "    설정은 언제나 $here/configs/env.yaml 에 둡니다."
    fi
  fi

  if ! inspect_tree "$DEST"; then
    rm -rf "$DEST"   # 실수로 커밋되는 것을 막기 위해 사본을 남기지 않는다
    die "점검 FAILED — $DEST 를 제거했습니다. 개발 장비에서 고치고 새 태그를 내세요"
  fi
  log "점검: OK"

  local entry="$DEST/src/run.py"
  if [[ ! -f "$entry" ]]; then
    local pys=("$DEST"/src/*.py)
    if [[ ${#pys[@]} -eq 1 && -f "${pys[0]}" ]]; then entry="${pys[0]}"; else entry="$DEST/src/<entry>.py"; fi
  fi

  cat <<EOF

next:  (전부 $here 에서 — 설정도 실행도 여기가 기준이다)
  source <venv>/bin/activate
  pip install --dry-run -r $DEST/requirements.txt && pip check
  python $entry --dry-run
EOF
}

main() {
  local tag="${1:-}" cwd; cwd=$(pwd -P)
  [[ -n "$tag" ]] || die "태그를 지정하세요:  bash <이 스크립트> <tag>"

  if [[ "$REPO_DIR" == "$cwd" ]]; then
    preflight "$tag"
  elif [[ "$REPO_DIR" == "$cwd/.staging/$NAME" ]]; then
    [[ -d "$STAGING/.git" ]] || die "$STAGING 이 clone 이 아닙니다 (.git 없음)"
    sync_into_aa "$tag"
  else
    die "실행 위치가 맞지 않습니다. 둘 중 하나여야 합니다:
       개발: cd <{BB} 저장소> && bash scripts/sync.sh <tag>
       운영: cd <{AA}>        && bash .staging/$NAME/scripts/sync.sh <tag>
     현재 cwd: $cwd"
  fi
}

main "$@"
