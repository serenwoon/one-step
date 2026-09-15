#!/usr/bin/env python3
"""
Vercel rewrites용 vercel.json 생성 스크립트.

공개 백엔드 주소(ONE_STEP_BACKEND_URL)가 있으면 vercel.json을 생성한다.
없으면 "미설정" 상태임을 출력하고 생성을 건너뛴다.

공개 배포 대상으로는 HTTPS 외부 주소만 허용한다.
localhost, 127.0.0.1, 내부 호스트명은 거부한다.
주소의 끝 슬래시는 정리한다.
기존 vercel.json이 있으면 rewrites/headers 등 기존 항목을 보존하고,
/ask rewrite만 갱신한다.
"""
import argparse
import ipaddress
import json
import os
import re
import sys
import urllib.parse

SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir))
TEMPLATE_PATH = os.path.join(PROJECT_ROOT, "vercel.json.template")
PREVIEW_TEMPLATE_PATH = os.path.join(PROJECT_ROOT, "preview", "vercel.json.template")

ALLOWED_SCHEMES = ("https",)


def _normalized_url(raw: str) -> str:
    url = raw.strip()
    if url.endswith("/"):
        url = url[:-1]
    return url


def _parse_url(url: str):
    parsed = urllib.parse.urlparse(url)
    return parsed


def _host_is_loopback(host: str) -> bool:
    # urlparse().hostname에는 포트와 대괄호가 이미 제거되어 있다.
    host = host.lower().rstrip(".")
    if host in ("localhost", "localhost.localdomain") or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return not ip.is_global or ip.is_multicast


def validate_backend_url(raw: str) -> str:
    """공개 백엔드 주소를 검증하고 정규화하여 반환한다.

    실패 시 sys.exit()로 종료한다.
    """
    url = _normalized_url(raw)
    if not url:
        print("오류: 백엔드 주소가 비어 있습니다.", file=sys.stderr)
        sys.exit(2)

    parsed = _parse_url(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        print(
            f"오류: 백엔드 주소는 HTTPS여야 합니다: {url}",
            file=sys.stderr,
        )
        sys.exit(2)

    if not parsed.hostname:
        print(f"오류: 백엔드 주소에 호스트가 없습니다: {url}", file=sys.stderr)
        sys.exit(2)

    hostname = parsed.hostname
    if _host_is_loopback(hostname):
        print(
            f"오류: 공개 배포 대상으로 로컬/루프백 주소를 사용할 수 없습니다: {url}",
            file=sys.stderr,
        )
        sys.exit(2)

    if parsed.port is None:
        # 기본 포트 외 명시적 비표준 포트는 허용하되 경고만 남긴다.
        pass

    return url


def load_existing(path: str) -> dict | None:
    """새 파일은 None을 반환하고. 읽을 수 없는 기존 설정은 오류로 처리한다."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        if os.path.lexists(path):
            raise ValueError(f"기존 설정 경로를 읽을 수 없습니다: {path}")
        return None
    except (OSError, ValueError) as e:
        raise ValueError(f"기존 설정을 읽을 수 없습니다: {path}") from e
    if not isinstance(data, dict):
        raise ValueError(f"기존 설정은 JSON 객체여야 합니다: {path}")
    if "rewrites" in data and not isinstance(data["rewrites"], list):
        raise ValueError(f"기존 rewrites는 배열이어야 합니다: {path}")
    return data


def merge_rewrites(existing: dict | None, backend_url: str) -> list:
    """기존 rewrites를 보존하고 /ask 대상만 갱신한다."""
    if existing is None:
        return [{"source": "/ask", "destination": f"{backend_url}/ask"}]
    rewrites = existing.get("rewrites")
    if not isinstance(rewrites, list):
        return [{"source": "/ask", "destination": f"{backend_url}/ask"}]
    out = []
    seen_ask = False
    for item in rewrites:
        if not isinstance(item, dict):
            out.append(item)
            continue
        source = item.get("source")
        destination = item.get("destination")
        if isinstance(source, str) and source.strip() == "/ask":
            out.append({**item, "destination": f"{backend_url}/ask"})
            seen_ask = True
        else:
            out.append(item)
    if not seen_ask:
        out.append({"source": "/ask", "destination": f"{backend_url}/ask"})
    return out


def build_config(backend_url: str, existing: dict | None) -> dict:
    # rewrites는 /ask로 갱신
    if existing is None:
        rewrites = [{"source": "/ask", "destination": f"{backend_url}/ask"}]
    elif "rewrites" in existing and isinstance(existing["rewrites"], list):
        rewrites = merge_rewrites(existing, backend_url)
    else:
        rewrites = [{"source": "/ask", "destination": f"{backend_url}/ask"}]

    config = {
        "$schema": "https://openapi.vercel.sh/vercel.json",
        "rewrites": rewrites,
    }

    # rewrites를 제외한 모든 기존 키 보존
    if existing:
        for key, value in existing.items():
            if key != "rewrites":
                config[key] = value

    return config


def write_config(path: str, config: dict) -> bool:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Vercel rewrites용 vercel.json을 공개 백엔드 주소로 생성한다."
    )
    parser.add_argument(
        "--backend-url",
        default=None,
        help="공개 백엔드 주소 (예: https://one-step.example.com). "
        "미지정 시 환경변수 ONE_STEP_BACKEND_URL 사용.",
    )
    parser.add_argument(
        "--select",
        choices=("root", "preview"),
        default=None,
        help="생성할 위치 선택: root=프로젝트 루트 vercel.json, "
        "preview=preview/vercel.json. 미지정 시 둘 다 후보이며 "
        "기존 파일이 있으면 그쪽을 우선한다.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="생성할 vercel.json 경로 (--select보다 우선).",
    )
    parser.add_argument(
        "--preview-output",
        action="store_true",
        help="preview/vercel.json도 함께 생성한다 (Root Directory가 preview인 프로젝트용).",
    )
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="이전 명령 호환용 옵션. 기존 설정은 옵션 없이도 항상 보존한다.",
    )
    args = parser.parse_args()

    backend_url_raw = args.backend_url or os.environ.get("ONE_STEP_BACKEND_URL", "").strip()

    if not backend_url_raw:
        print("백엔드 주소 미설정: ONE_STEP_BACKEND_URL 환경변수 또는 --backend-url이 없습니다.")
        print("이 상태에서는 Vercel rewrites 대상이 생성되지 않습니다.")
        print("Vercel 배포 전에 공개 백엔드 주소를 정해 주세요.")
        print("미설정 상태에서는 vercel.json을 생성하지 않습니다.")
        return 1

    backend_url = validate_backend_url(backend_url_raw)

    # 출력 위치 결정
    if args.output:
        outputs = [args.output]
    elif args.select == "root":
        outputs = [os.path.join(PROJECT_ROOT, "vercel.json")]
    elif args.select == "preview":
        outputs = [os.path.join(PROJECT_ROOT, "preview", "vercel.json")]
    else:
        outputs = [
            os.path.join(PROJECT_ROOT, "vercel.json"),
            os.path.join(PROJECT_ROOT, "preview", "vercel.json"),
        ]

    if args.preview_output and args.output is None:
        outputs.append(os.path.join(PROJECT_ROOT, "preview", "vercel.json"))
    outputs = list(dict.fromkeys(outputs))

    # 모든 기존 파일을 먼저 검사해서 깨진 설정이 있으면 쓰기 전에 중단한다.
    try:
        configs = [(path, build_config(backend_url, load_existing(path))) for path in outputs]
        for path, config in configs:
            write_config(path, config)
            print(f"생성 완료: {path}")
            print(f"  rewrite: /ask -> {backend_url}/ask")
    except (ValueError, OSError) as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
