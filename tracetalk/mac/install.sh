#!/usr/bin/env bash
# 처음 한 번 (v16, Apple silicon 맥, 인터넷 필요): 설치물(setup.sh) → 모델 두 조각 합치기(release/) → 모델 등록. 모두 _mac_runtime/ 한
# 폴더 안에 들어가고, 이미 된 단계는 건너뛴다. 끝나면 bash mac/start.sh 로 켠다.
set -euo pipefail
cd "$(dirname "$0")/.."
bash mac/setup.sh
bash mac/get_model.sh release
mkdir -p runs
bash mac/serve.sh > runs/serve_install.log 2>&1 &
SERVE=$!
trap 'kill "$SERVE" 2>/dev/null || true' EXIT
curl -s --retry 30 --retry-connrefused --retry-delay 1 -o /dev/null http://127.0.0.1:11435/api/version \
    || { echo "모델 서버가 뜨지 않았습니다: runs/serve_install.log"; exit 1; }
bash mac/import_student.sh
echo "== 설치 끝. 켜기: bash mac/start.sh"
