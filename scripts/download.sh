#!/usr/bin/env bash
# Zenodo DOI 10.5281/zenodo.17122442 데이터 다운로드 스크립트
# "A Multi-Model Dataset for BOSCH Plasma-Etching", CC BY 4.0
# 저작자: Sayyed, Seifert, Zieger, Schwarzenberg, Deshmukh, Haase, Langer
#         (Chemnitz University of Technology, Fraunhofer ENAS)
set -euo pipefail

BASE_URL="https://zenodo.org/records/17122442/files"
DATA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/data"
mkdir -p "$DATA_DIR"

# 작은 파일 (합계 10 MB 미만). OES 관련 대용량 Day_*.nc는 받지 않는다.
SMALL_FILES=(
  "Readme.pdf"
  "Dictionary_process.nc"
  "Process_data.nc"
  "Lot_status.xlsx"
  "Si_Oxide_etch_89_points.csv"
  "Si_Oxide_etch_9_points.csv"
  "Wafer_layout.pdf"
)

for f in "${SMALL_FILES[@]}"; do
  dest="$DATA_DIR/$f"
  if [ -f "$dest" ]; then
    echo "이미 존재함, 건너뜀: $f"
    continue
  fi
  echo "다운로드: $f"
  curl -fL --retry 3 -o "$dest" "${BASE_URL}/${f}?download=1"
done

# OES 스펙트럼 (Day_*.nc, 합계 약 7.9 GB). 기본으로는 받지 않는다.
#   ./scripts/download.sh --oes   로 명시할 때만 받는다.
if [ "${1:-}" = "--oes" ]; then
  OES_FILES=(
    "Dictionary_OES.nc"
    "Day_2024_07_02.nc" "Day_2024_07_05.nc" "Day_2024_07_09.nc" "Day_2024_07_11.nc"
    "Day_2024_07_19.nc" "Day_2024_08_01.nc" "Day_2024_08_05.nc" "Day_2024_08_07.nc"
    "Day_2024_08_21.nc" "Day_2024_08_22.nc"
  )
  for f in "${OES_FILES[@]}"; do
    dest="$DATA_DIR/$f"
    if [ -f "$dest" ]; then
      echo "이미 존재함, 건너뜀: $f"
      continue
    fi
    echo "다운로드(OES): $f"
    curl -fL --retry 3 -o "$dest" "${BASE_URL}/${f}?download=1"
  done
fi

echo "완료. data/ 디렉토리 확인:"
ls -la "$DATA_DIR"
