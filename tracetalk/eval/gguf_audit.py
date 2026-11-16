#!/usr/bin/env python3
"""Read a GGUF file's header as data, without loading it into any model: magic, version, what it says it is, its chat template, every text field that
holds an address, and whether the tensors it declares fill the file exactly. Nothing in the file is run. -> exit 2 when something does not add up."""
import struct
import sys

TYPES = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}
SIZES = {"B": 1, "b": 1, "H": 2, "h": 2, "I": 4, "i": 4, "f": 4, "?": 1, "Q": 8, "q": 8, "d": 8}


def main(path):
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            print("GGUF 파일이 아닙니다.")
            return 2
        version = struct.unpack("<I", f.read(4))[0]
        tensors, fields = struct.unpack("<QQ", f.read(16))
        print(f"GGUF v{version}, 텐서 {tensors}개, 메타데이터 {fields}개")
        if version not in (2, 3) or tensors > 100000 or fields > 100000:
            print("머리말 값이 이상합니다.")
            return 2

        def text():
            size = struct.unpack("<Q", f.read(8))[0]
            if size > 200_000_000:
                raise ValueError("글자 길이가 이상합니다.")
            return f.read(size).decode("utf-8", errors="replace")

        def value(kind):
            if kind == 8:
                return text()
            if kind == 9:
                inner, count = struct.unpack("<IQ", f.read(12))
                if inner == 8:
                    return [text() for _ in range(count)]
                f.seek(SIZES[TYPES[inner]] * count, 1)
                return f"(수 {count}개)"
            return struct.unpack("<" + TYPES[kind], f.read(SIZES[TYPES[kind]]))[0]

        meta = {}
        for _ in range(fields):
            key = text()
            kind = struct.unpack("<I", f.read(4))[0]
            meta[key] = value(kind)
        strings = []
        for key, val in meta.items():
            if isinstance(val, list):
                print(f"  {key}: 글자 목록 {len(val)}개, 예 {val[:3]}")
                strings += [] if "tokens" in key or "merges" in key else val
            elif key == "tokenizer.chat_template":
                print(f"  {key}:\n----\n{val}\n----")
            else:
                print(f"  {key}: {val}")
                if isinstance(val, str):
                    strings.append(val)
        odd = [s[:120] for s in strings if "http" in s or "://" in s or "<script" in s]
        print("주소가 든 글자 칸:", odd or "없음")
        end = 0
        for _ in range(tensors):
            name = text()
            dims = struct.unpack("<I", f.read(4))[0]
            f.seek(8 * dims + 4, 1)
            offset = struct.unpack("<Q", f.read(8))[0]
            end = max(end, offset)
            if not name.isascii():
                print("텐서 이름이 이상합니다:", name[:40])
                return 2
        start = f.tell()
        f.seek(0, 2)
        size = f.tell()
        print(f"텐서 표 끝 {start} · 마지막 텐서 시작 {start + end} · 파일 크기 {size}")
        if start + end >= size:
            print("텐서가 파일 밖을 가리킵니다.")
            return 2
    print("머리말 점검 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
