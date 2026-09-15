#!/usr/bin/env python3
"""
다시, 한 걸음(one-step) — 서비스 프로필 초기화 (템플릿 기반 새 프로필 생성)

실행:
    python3 deploy/init_service_profile.py [대상 프로필 디렉터리]

동작:
- deploy/profile-template/config.yaml을 읽는다.
- MCP 서버 one-step-policy의 cwd를 실제 프로젝트 루트로 바꾼다.
  (템플릿 기본값 /opt/one-step은 배포용 placeholder)
- MCP 서버 명령(command)을指定된 Python 실행 파일로 바꿀 수 있다.
- 대상 디렉터리에 config.yaml만 작성한다.
  기존 프로필(deploy/ServiceProfile/ 등)은 건드리지 않는다.
- 프로필 디렉터리 자체는 새로 만들며, DB·로그·캐시·대화 기록은 복사하지 않는다.

용도:
- 새 환경에서 서비스 프로필을 처음 만들 때 사용한다.
- 템플릿만 복사한 뒤에는 정책 MCP 서버(policy_mcp_server.py)와
  policy_fetch.py가 cwd 경로(프로젝트 루트)에 실제로 있어야 한다.
"""

import argparse
import json
import os
import sys

# 이 스크립트와 같은 배포 폴더의 템플릿을 읽는다.
SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir))
TEMPLATE_PATH = os.path.join(SCRIPT_DIR, "profile-template", "config.yaml")


def _read_template(path):
    if not os.path.isfile(path):
        raise FileNotFoundError(f"템플릿이 없습니다: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _make_config(template_text, project_root, python_cmd):
    """
    템플릿의 placeholder 경로를 실제 설치 경로로 바꾼다.

    지금은 다음 두 흐름을 맞춘다.
    - mcp_servers.one-step-policy.cwd: 프로젝트 루트
    - mcp_servers.one-step-policy.command: 실제 python 인터프리터
    """
    # 템플릿 예시 경로는 /opt/one-step이다. 실제 프로젝트 루트 하나로 통일한다.
    out = template_text

    # YAML의 플레이스홀더 주석을 실제 경로 설명으로 바꾼다.
    out = out.replace(
        "# /opt/one-step은 서버의 실제 프로젝트 설치 경로에 맞춰 변경한다.",
        f"# {project_root}는 서버의 실제 프로젝트 설치 경로에 맞춰 변경한다.",
    )

    out = out.replace("    cwd: /opt/one-step", f"    cwd: {json.dumps(project_root, ensure_ascii=False)}")

    out = out.replace("    command: python3", f"    command: {json.dumps(python_cmd, ensure_ascii=False)}")

    return out


def main():
    parser = argparse.ArgumentParser(
        description="서비스 프로필 템플릿을 복사해 새 프로필의 config.yaml을 만든다."
    )
    parser.add_argument(
        "target_dir",
        nargs="?",
        default=None,
        help="새 프로필 디렉터리 경로 (기본값: ./deploy/ServiceProfile-new)",
    )
    parser.add_argument(
        "--python-cmd",
        default=None,
        help="MCP 서버에서 사용할 Python 명령 (기본값: sys.executable)",
    )
    args = parser.parse_args()

    python_cmd = args.python_cmd or sys.executable
    target_dir = args.target_dir or os.path.join(PROJECT_ROOT, "deploy", "ServiceProfile-new")

    template_text = _read_template(TEMPLATE_PATH)
    config_text = _make_config(template_text, PROJECT_ROOT, python_cmd)

    os.makedirs(target_dir, exist_ok=True)

    dest = os.path.join(target_dir, "config.yaml")
    if os.path.exists(dest):
        print(f"이미 있습니다: {dest} (덮어쓰지 않습니다)", file=sys.stderr)
        return 1

    with open(dest, "x", encoding="utf-8") as f:
        f.write(config_text)

    print(f"새 프로필 config.yaml 생성: {dest}")
    print(f"  프로젝트 루트(cwd): {PROJECT_ROOT}")
    print(f"  MCP 명령(command): {python_cmd}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
