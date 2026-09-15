#!/usr/bin/env python3
"""실제 CLI 실행으로 설정 보존. 실패 종료. IPv6 주소 거부를 검증한다."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).with_name("prepare_vercel_json.py")


def run(path, *args, url="https://one-step.example.com"):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--backend-url", url, "--output", str(path), *args],
        capture_output=True, text=True, timeout=10,
    )


def main():
    with tempfile.TemporaryDirectory(prefix="one-step-vercel-check-") as directory:
        path = Path(directory) / "vercel.json"
        # 새 파일 생성은 기존 설정 보존 옵션과 관계없이 동작해야 한다.
        for flags in ([], ["--keep-existing"]):
            result = run(path, *flags)
            assert result.returncode == 0, result.stderr
            assert json.loads(path.read_text())["rewrites"][0]["destination"].endswith("/ask")
            path.unlink()
        print("OK: 새 파일 생성")

        data = {"buildCommand": "npm run build", "outputDirectory": "dist", "headers": [],
                "rewrites": [{"source": "/api", "destination": "https://example.com/api"},
                             {"source": "/ask", "destination": "https://old.example.com/ask", "has": []}]}
        path.write_text(json.dumps(data))
        result = run(path)
        assert result.returncode == 0, result.stderr
        updated = json.loads(path.read_text())
        for key in ("buildCommand", "outputDirectory", "headers"):
            assert updated[key] == data[key]
        assert updated["rewrites"][0] == data["rewrites"][0]
        assert updated["rewrites"][1]["has"] == []
        assert updated["rewrites"][1]["destination"] == "https://one-step.example.com/ask"
        print("OK: 옵션 없이 기존 설정 보존과 /ask 갱신")

        for original in (b"{broken", b"[]", b'{"rewrites": {}}'):
            for flags in ([], ["--keep-existing"]):
                path.write_bytes(original)
                result = run(path, *flags)
                assert result.returncode != 0
                assert path.read_bytes() == original
        print("OK: 잘못된 설정 원본 보존과 실패 종료")

        for url in ("https://[::1]", "https://[::1]:443", "https://[fd00::1]",
                    "https://[fe80::1]", "https://[2001:db8::1]", "https://127.0.0.1",
                    "https://192.168.1.1", "https://localhost", "http://example.com"):
            before = path.read_bytes()
            assert run(path, url=url).returncode != 0, url
            assert path.read_bytes() == before
        path.unlink()
        assert run(path, url="https://[2606:4700:4700::1111]").returncode == 0
        print("OK: 로컬·사설 IP 거부와 공개 IPv6 허용")
    print("통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
