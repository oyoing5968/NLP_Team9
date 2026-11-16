#!/usr/bin/env bash
# 학습된 모델 받기 (model/README.md): GitHub 릴리스의 두 조각을 내려받은 폴더를 주면, 조각 지문을 확인하고 하나로 합쳐 전체 지문을
# 확인한 뒤 _mac_runtime/pkg/tracetalk-student-v1/ 에 Modelfile·MANIFEST와 함께 둔다. 그다음 serve.sh를 켠 채 import_student.sh.
#   bash mac/get_model.sh ~/Downloads        (tracetalk-student-v1.gguf.part-aa, part-ab 가 있는 폴더)
set -euo pipefail
cd "$(dirname "$0")/.."
SRC="${1:?두 조각을 내려받은 폴더를 주세요: bash mac/get_model.sh <폴더>}"
PKG=_mac_runtime/pkg/tracetalk-student-v1
GGUF=tracetalk-student-v1.gguf
if [ -e "$PKG/$GGUF" ]; then echo "== 이미 있음: $PKG/$GGUF (등록: bash mac/import_student.sh)"; exit 0; fi
for part in aa ab; do
    f="$SRC/$GGUF.part-$part"
    [ -f "$f" ] || { echo "조각이 없습니다: $f"; exit 2; }
    want=$(grep " $GGUF.part-$part\$" model/SHA256SUMS | cut -d' ' -f1)
    got=$(shasum -a 256 "$f" | cut -d' ' -f1)
    [ "$want" = "$got" ] || { echo "조각 지문이 다릅니다: $f (다시 받으세요)"; exit 3; }
    echo "   조각 $part 지문 맞음"
done
mkdir -p "$PKG"
cat "$SRC/$GGUF.part-aa" "$SRC/$GGUF.part-ab" > "$PKG/$GGUF.tmp"
want=$(grep " $GGUF\$" model/SHA256SUMS | cut -d' ' -f1)
got=$(shasum -a 256 "$PKG/$GGUF.tmp" | cut -d' ' -f1)
[ "$want" = "$got" ] || { rm -f "$PKG/$GGUF.tmp"; echo "합친 파일의 지문이 다릅니다."; exit 3; }
mv "$PKG/$GGUF.tmp" "$PKG/$GGUF"
cp model/Modelfile model/MANIFEST.json "$PKG/"
echo "== 모델 준비됨: $PKG/$GGUF"
echo "   다음: 터미널 1 bash mac/serve.sh → 터미널 2 bash mac/import_student.sh"
