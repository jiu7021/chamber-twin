#!/usr/bin/env python3
"""OES 대용량 파일(Day_*.nc)을 이어받기와 크기 검증으로 내려받는다.

download.sh 의 단순 `[ -f ] && skip` 방식은 중간에 끊긴 파일을 완성본으로
착각한다. 실제로 exit 18(partial file)로 끊겨 808 MB 짜리 미완성 파일이 남았다.

여기서는 Zenodo API 로 정확한 바이트 수를 받아와, 크기가 맞을 때까지
`curl -C -` 로 이어받는다. 크기가 맞는 파일만 완료로 본다.

    python3 scripts/oes_download.py [--jobs N]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RECORD = "17122442"
API = f"https://zenodo.org/api/records/{RECORD}"
BASE = f"https://zenodo.org/records/{RECORD}/files"
DATA = Path(__file__).resolve().parent.parent / "data"
MAX_TRY = 8


def sizes() -> dict[str, int]:
    # venv 파이썬의 urllib 은 시스템 루트 인증서를 못 찾아 SSL 검증에 실패한다.
    # curl 은 정상 동작하므로 API 조회도 curl 로 한다.
    out = subprocess.run(["curl", "-fsSL", "--retry", "3", API],
                         capture_output=True, text=True, check=True).stdout
    rec = json.loads(out)
    return {f["key"]: f["size"] for f in rec["files"]
            if f["key"].startswith("Day_") or f["key"] == "Dictionary_OES.nc"}


def fetch(name: str, want: int) -> tuple[str, bool, int]:
    dest = DATA / name
    for attempt in range(1, MAX_TRY + 1):
        have = dest.stat().st_size if dest.exists() else 0
        if have == want:
            return name, True, have
        if have > want:                      # 손상. 처음부터 다시.
            dest.unlink()
            have = 0
        subprocess.run(
            ["curl", "-fL", "-C", "-", "-sS", "--retry", "3", "--retry-delay", "5",
             "-o", str(dest), f"{BASE}/{name}?download=1"],
            check=False)
        have = dest.stat().st_size if dest.exists() else 0
        print(f"  {name}  시도 {attempt}: {have/1e6:.0f} / {want/1e6:.0f} MB", flush=True)
    return name, dest.exists() and dest.stat().st_size == want, have


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=1, help="동시 다운로드 수")
    args = ap.parse_args()

    DATA.mkdir(exist_ok=True)
    want = sizes()
    todo = {k: v for k, v in sorted(want.items())
            if not ((DATA / k).exists() and (DATA / k).stat().st_size == v)}
    done_mb = sum(v for k, v in want.items() if k not in todo) / 1e6
    print(f"전체 {len(want)}개 / 완료 {len(want)-len(todo)}개 ({done_mb:.0f} MB)")
    if not todo:
        print("이미 모두 완료")
        return
    print(f"받을 것 {len(todo)}개 ({sum(todo.values())/1e6:.0f} MB), 동시 {args.jobs}개\n")

    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        results = list(ex.map(lambda kv: fetch(*kv), todo.items()))

    bad = [n for n, ok, _ in results if not ok]
    print("\n완료" if not bad else f"\n실패: {bad}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
