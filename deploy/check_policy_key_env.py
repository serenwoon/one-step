#!/usr/bin/env python3
"""
policy_fetch.py의 API 키 읽기 방식 검증 (외부 API/모델 호출 없음)
- 환경변수가 있으면 .env보다 우선하는지
- 환경변수가 비어 있으면 .env 값이 대체되는지
- 둘 다 없으면 load_api_keys가 빈 dict를 반환하는지
- require가 키 누락 시 sys.exit으로 종료되는지
- 모든 케이스는 임시 디렉터리의 .env 경로를 사용하고, 부모 환경의 실제 키는 제거한 뒤 가짜 값만 사용한다
- 출력에는 케이스 이름과 통과 여부만 남긴다
"""
import os
import sys
import tempfile

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, PROJECT_ROOT)

import policy_fetch

ENV_ON = "ON_YOUTH_API_KEY"
ENV_GOV = "GOV24_API_KEY"


def _clear_keys():
    os.environ.pop(ENV_ON, None)
    os.environ.pop(ENV_GOV, None)


def _set_keys(on=None, gov=None):
    if on is not None:
        os.environ[ENV_ON] = on
    else:
        os.environ.pop(ENV_ON, None)
    if gov is not None:
        os.environ[ENV_GOV] = gov
    else:
        os.environ.pop(ENV_GOV, None)


def _make_env_file(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def run_case(
    name,
    on_env=None,
    gov_env=None,
    env_file_text=None,
    expect_on="",
    expect_gov="",
    expect_load_empty=False,
    expect_require_exit=False,
    require_key=None,
):
    with tempfile.TemporaryDirectory(prefix="one-step-keycheck-") as tmpdir:
        env_path = os.path.join(tmpdir, ".env")
        policy_fetch.ENV_PATH = env_path

        if env_file_text is not None:
            _make_env_file(env_path, env_file_text)

        _clear_keys()
        _set_keys(on_env, gov_env)

        try:
            if expect_require_exit:
                try:
                    policy_fetch.require(key=require_key)
                except SystemExit as e:
                    code = e.code if isinstance(e.code, str) else str(e.code)
                    if require_key not in code:
                        print(f"FAIL: {name} — require 종료 메시지에 키 이름이 없음")
                        return False
                    print(f"OK: {name}")
                    return True
                except Exception as e:
                    print(f"FAIL: {name} — require가 예상치 못한 예외를 냄: {e}")
                    return False
                else:
                    print(f"FAIL: {name} — require가 종료되지 않음")
                    return False

            keys = policy_fetch.load_api_keys()
            if expect_load_empty:
                if keys:
                    print(f"FAIL: {name} — load_api_keys가 비어 있어야 하는데 값이 있음")
                    return False
                print(f"OK: {name}")
                return True

            got_on = keys.get(ENV_ON, "")
            got_gov = keys.get(ENV_GOV, "")
            if got_on != expect_on or got_gov != expect_gov:
                print(f"FAIL: {name}")
                return False
            print(f"OK: {name}")
            return True
        finally:
            pass


def main():
    ENV_FILE_ON_GOV = (
        "# 임시 테스트용 .env\n"
        'ON_YOUTH_API_KEY="env-file-on-key"\n'
        'GOV24_API_KEY="env-file-gov-key"\n'
    )
    ENV_FILE_GOV_ONLY = "GOV24_API_KEY=env-file-gov-only\n"
    ENV_FILE_ON_QUOTED = (
        'ON_YOUTH_API_KEY="quoted-on-key"\n'
        'GOV24_API_KEY="quoted-gov-key"\n'
    )

    results = []

    # 1) 환경변수가 있으면 .env보다 우선
    results.append(run_case(
        "환경변수 우선 (둘 다 있음)",
        on_env="env-var-on-key",
        gov_env="env-var-gov-key",
        env_file_text=ENV_FILE_ON_GOV,
        expect_on="env-var-on-key",
        expect_gov="env-var-gov-key",
    ))

    # 2) 환경변수는 있고 .env에는 다른 값이 있어도 환경변수 우선 (ON만_env, GOV는_env_file)
    results.append(run_case(
        "환경변수 우선 (ON만 있고 GOV는 .env)",
        on_env="env-var-on-key",
        env_file_text=ENV_FILE_ON_GOV,
        expect_on="env-var-on-key",
        expect_gov="env-file-gov-key",
    ))

    # 3) 환경변수가 비어 있으면 .env 대체
    results.append(run_case(
        ".env 대체 (환경변수 비면 .env 사용)",
        on_env="",
        gov_env="",
        env_file_text=ENV_FILE_ON_GOV,
        expect_on="env-file-on-key",
        expect_gov="env-file-gov-key",
    ))

    # 4) .env에서 따옴표 제거 확인
    results.append(run_case(
        ".env 따옴표 제거",
        on_env="",
        gov_env="",
        env_file_text=ENV_FILE_ON_QUOTED,
        expect_on="quoted-on-key",
        expect_gov="quoted-gov-key",
    ))

    # 5) .env로 GOV만 있을 때 ON은 비어 있음
    results.append(run_case(
        ".env 부분 존재 (ON 없음)",
        on_env="",
        gov_env="",
        env_file_text=ENV_FILE_GOV_ONLY,
        expect_on="",
        expect_gov="env-file-gov-only",
    ))

    # 6) 환경변수도 .env도 없으면 load_api_keys가 빈 dict를 반환
    results.append(run_case(
        "키 누락 (.env 없음, 환경변수 없음) — load_api_keys 빈 dict",
        env_file_text=None,
        expect_load_empty=True,
    ))

    # 7) require가 키 누락 시 sys.exit으로 종료 (ON 키 누락)
    results.append(run_case(
        "require 종료 (ON 키 누락)",
        env_file_text=None,
        expect_require_exit=True,
        require_key=ENV_ON,
    ))

    # 8) require가 키 누락 시 sys.exit으로 종료 (GOV 키 누락)
    results.append(run_case(
        "require 종료 (GOV 키 누락)",
        env_file_text=None,
        expect_require_exit=True,
        require_key=ENV_GOV,
    ))

    print()
    for i, ok in enumerate(results, 1):
        print(f"  검증 {i}: {'OK' if ok else 'FAIL'}")

    ok_all = all(ok for _, _ in [(None, v) for v in results])
    if ok_all:
        print("\nOK: 환경변수 우선/.env 대체/키 누락 처리 확인")
        return 0
    print("\nFAILED: 일부 검증 실패")
    return 1


if __name__ == "__main__":
    sys.exit(main())
