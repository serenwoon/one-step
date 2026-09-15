#!/usr/bin/env python3
"""
다시, 한 걸음(one-step) — 최소 로컬 연결
브라우저가 Solar API를 직접 호출하지 않고, Hermes CLI(프로필 one-step, Solar Pro 4)
를 한 번 거쳐서 답만 돌려준다. 아직은 내 Mac 안에서만 확인한다.
"""
import os
import sys
import json
import shutil
import subprocess
import secrets
import threading
from http.cookies import SimpleCookie, CookieError
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

# Hermes 실행 파일은 환경변수 또는 기본 PATH의 hermes를 쓴다.
HERMES_CMD = os.environ.get("HERMES_CMD") or "hermes"

# 실행 모드
SERVICE_MODE = os.environ.get("ONE_STEP_SERVICE_MODE") == "1"

# Hermes 호출 타임아웃(초). 환경변수로 조절 가능하며, 미설정 시 기존 기본값 180초 유지.
# Vercel 외부 rewrite 첫 바이트 허용 시간(120초)보다 짧게 운영할 때 조절한다.
_REQUEST_TIMEOUT_ENV = os.environ.get("ONE_STEP_REQUEST_TIMEOUT", "").strip()
if _REQUEST_TIMEOUT_ENV:
    try:
        REQUEST_TIMEOUT = int(_REQUEST_TIMEOUT_ENV)
        if REQUEST_TIMEOUT < 1:
            raise ValueError("1 이상 필요")
    except ValueError:
        print(
            f"error: ONE_STEP_REQUEST_TIMEOUT은 1 이상의 정수여야 합니다 (입력값: {_REQUEST_TIMEOUT_ENV!r})",
            file=sys.stderr,
        )
        sys.exit(4)
else:
    REQUEST_TIMEOUT = 180

if SERVICE_MODE:
    # 서비스 모드에서는 프로필 경로를 반드시 지정해야 한다.
    raw_home = os.environ.get("ONE_STEP_HERMES_HOME")
    if not raw_home:
        print(
            "error: ONE_STEP_SERVICE_MODE=1 requires ONE_STEP_HERMES_HOME to be set and non-empty",
            file=sys.stderr,
        )
        sys.exit(2)
    HERMES_HOME = raw_home
else:
    # 로컬 개발 모드: 환경변수 미지정 시 개발용 프로필로 fallback
    HERMES_HOME = os.environ.get("ONE_STEP_HERMES_HOME") or "/Users/JWoon/.hermes/profiles/one-step"

WORK_DIR = os.path.dirname(os.path.abspath(__file__))

# 같은 폴더의 정책 페치를 사용한다.
sys.path.insert(0, WORK_DIR)
import policy_fetch

class ConversationServer(ThreadingHTTPServer):
    """브라우저 쿠키와 Hermes 대화 이름을 서버 안에서 연결한다."""

    def __init__(self, address, handler):
        super().__init__(address, handler)
        self.conversations = {}
        self.conversation_locks = {}
        self.state_lock = threading.Lock()
        # 모델 호출은 최대 4개만 실행하고, 상태 확인은 별도로 응답한다.
        self.request_slots = threading.BoundedSemaphore(4)
        # conversation별 수집 상태: {"age_asked": bool, "age_skipped": bool, "age_value": str|None}
        self.collect_state = {}


def _validate_service_prereqs() -> list[str]:
    """서비스 모드 시작 전 필수 설정만 확인한다. 값이 아니라 존재 여부만 본다.

    키 값은 절대 출력하지 않고, 실제 모델·정책 API는 호출하지 않는다.
    빠진 항목이 있으면 목록만 반환하고, 호출 쪽은 종료 코드로 처리한다.
    """
    missing = []

    # 1) Hermes 실행 파일
    cmd = HERMES_CMD
    if not cmd or not cmd.strip():
        missing.append("HERMES_CMD (빈 값)")
    else:
        found = shutil.which(cmd.strip())
        if not found:
            missing.append(f"HERMES_CMD='{cmd}' (PATH에서 찾을 수 없음)")

    # 2) 서비스 프로필 config.yaml
    #    main()에서 이미 ONE_STEP_HERMES_HOME을 검증합니다(빈 값이면 sys.exit(2)).
    #    여기서는 프로필 디렉터리 안에 config.yaml이 실제로 존재하는지까지만 봅니다.
    cfg_path = os.path.join(HERMES_HOME.strip(), "config.yaml")
    try:
        with open(cfg_path, "rb"):
            pass
    except OSError as e:
        missing.append(f"config.yaml ({cfg_path}: {e})")

    # 3) Upstage 모델 키
    upstage_key = os.environ.get("UPSTAGE_API_KEY", "").strip()
    if not upstage_key:
        missing.append("UPSTAGE_API_KEY (빈 값)")

    # 4) 정책 API 키
    #    서비스 모드에서는 hermes subprocess에 환경변수로 전파되는 값만 신뢰합니다.
    #    .env 대체는 서버 배포 환경에서 실제 실행 경로와 맞지 않기 때문에, 서비스
    #    모드일 때는 환경변수 기준으로만 존재 여부를 확인합니다. 로컬 개발에서는
    #    .env 보조 읽기를 유지합니다.
    if SERVICE_MODE:
        env_on = os.environ.get("ON_YOUTH_API_KEY", "").strip()
        env_gov = os.environ.get("GOV24_API_KEY", "").strip()
        if not env_on:
            missing.append("ON_YOUTH_API_KEY (빈 값)")
        if not env_gov:
            missing.append("GOV24_API_KEY (빈 값)")
    else:
        keys = policy_fetch.load_api_keys()
        if not keys.get("ON_YOUTH_API_KEY", "").strip():
            missing.append("ON_YOUTH_API_KEY (빈 값)")
        if not keys.get("GOV24_API_KEY", "").strip():
            missing.append("GOV24_API_KEY (빈 값)")

    return missing

class Handler(BaseHTTPRequestHandler):
    # 정책 검색·API 호출 없이, 웹 대화에 이 서비스의 답변 규칙만 전달한다.
    # 실제 정책 조회와 후보 제시·추가 질문은 Hermes(+정책 MCP) 대화 안에서 처리한다.
    ANSWER_RULES = (
        "당신은 '다시, 한 걸음' 서비스의 답변을 돕는 역할이에요. "
        "아래 답변 규칙을 지켜서 답해 주세요.\n\n"
        "【기본 태도】\n"
        "- 이용자가 말하지 않은 사실을 임의로 채우지 마세요. "
        "예: 쉬고 있다고 교육을 안 받았다고 가정하지 말고, 혼자 산다는 말만으로 가구 구성을 정하지 마세요.\n"
        "- 모르는 조건은 모르는 상태로 남기세요. 맞는 부분 / 안 맞는 부분 / 아직 확인 필요한 부분을 구분하세요.\n"
        "- 지원금 수급이나 신청 완료를 보장하지 마세요.\n\n"
        "【정책 답변 방식】\n"
        "- 정책 검색 결과가 있으면 정책명, 지원 내용, 원문 링크를 보여주세요.\n"
        "- 확인된 조건과 아직 확인하지 못한 조건을 구분하세요.\n"
        "- '맞는 부분 / 안 맞는 부분 / 아직 확인 필요한 내용'을 나눠서 보여주세요.\n"
        "- 정보 유형(공식 원문 검토 자료인지, API에서 가져온 자료인지), 공식 출처, 확인 날짜, 지금 모집 중인지 여부를 구분하세요.\n"
        "- 사업 기간만 보고 지금 신청할 수 있다고 하거나, 기관명만 보고 거주 조건이 맞는다고 하지 마세요.\n"
        "- 연령 정보가 서로 다르면 대상이라고 확정하지 말고 원문 확인이 필요하다고 안내하세요.\n"
        "- 현재 조회 범위에서 찾지 못한 것과 실제 정책이 없는 것은 구분하세요. API 검색 결과에 보이지 않는다고 해서 그 지역·목적에 정책이 없다고 단정하지 마세요.\n"
        "- 이용자의 지역·목적과 맞지 않는 결과(예: 다른 지역 정책, 전혀 다른 목적의 사업)는 추천 후보에서 제외하고, 그 검색 결과로는 여기서 본 조건을 판단하기 어렵다고 안내하세요.\n"
        "- 정책 검색 결과가 있거나 없거나, 조회한 범위(어떤 API, 어떤 검색어, 몇 건)와 그 결과로 알 수 있는 것/알 수 없는 것을 함께 밝혀 주세요.\n"
        "- 지금 조회한 범위로 판단이 부족하면, 어느 방향으로 더 찾아보면 좋을지(예: 다른 검색어, 지역 정책, 기관 직접 확인)만 짚어 주세요. 전체 지역 필터와 신청 자격 판정은 이 단계에서 하지 않습니다.\n\\n"
        "【추가 질문】\n"
        "- 추가 질문은 실제 후보를 확인하는 데 필요한 정보가 빠졌을 때만 하나씩만 하세요.\n"
        "- 처음부터 질문을 너무 많이 하지 말고, 첫 후보 전에는 추가 질문을 최대 3회, 이후에는 2회 정도로만 하세요.\n"
        "- 관련 정책이 없으면 없다고 말하세요. 억지로 후보를 채우지 마세요.\n"
        "- 마지막에 오늘 할 수 있는 행동 하나로 이어 주세요.\n\n"
        "【하지 말 것】\n"
        "- 나이를 먼저 묻는 흐름은 넣지 마세요. 이용자가 상황에 나이를 이미 말한 경우에만 그 정보를 활용하세요.\n"
        "- 이용자가 많이 힘들거나 급해 보이면 정책보다 사람 도움처를 먼저 안내하세요. 짧게 공감하고, 상담사처럼 진단하거나 위험도 점수를 매기지 마세요.\n"
        "- 이용자가 이미 알려준 정보를 다시 묻지 마세요.\n\n"
        "【사용자 상황 읽기】\n"
        "- 이용자의 질문이나 상황 설명을 먼저 읽고, 그 내용을 바탕으로 답하세요.\n"
        "- 이용자는 앞서 대화에서 이미 일부 정보를 말했을 수 있어요. 대화 맥락을 확인하고, 이미 나온 정보는 다시 묻지 마세요."
    )

    def _conversation(self):
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
        except CookieError:
            pass
        cookie = cookies.get("one_step_conversation")
        token = cookie.value if cookie else None
        with self.server.state_lock:
            name = self.server.conversations.get(token)
            if name is None:
                token = secrets.token_urlsafe(32)
                name = "one-step-web-" + secrets.token_hex(24)
                self.server.conversations[token] = name
                self.server.conversation_locks[name] = threading.Lock()
                # 새 대화는 처음부터 연령 미확인 상태
                self.server.collect_state[name] = {"age_asked": False, "age_skipped": False, "age_value": None}
            self.conversation_lock = self.server.conversation_locks[name]
        self.conversation_cookie = (
            "one_step_conversation=" + token + "; Path=/; HttpOnly; SameSite=Strict"
        )
        return name

    def do_GET(self):
        if self.path == "/health":
            self._respond(200, {"ok": True, "hermes_cmd": HERMES_CMD})
            return
        if self.path == "/" or self.path == "/index.html":
            self._serve_html()
            return
        self._respond(404, {"error": "not found"})

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def _cors_headers(self):
        origin = self.headers.get("Origin", "")
        allowed = os.environ.get("ONE_STEP_ALLOWED_ORIGINS", "*")
        if allowed == "*" or origin in allowed.split(","):
            self.send_header("Access-Control-Allow-Origin", origin or "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "86400")

    def do_POST(self):
        if self.path == "/ask":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
                query = (data.get("query") or "").strip()
            except Exception:
                self._respond(400, {"error": "invalid json"})
                return
            if not query:
                self._respond(400, {"error": "query is empty"})
                return
            conversation = self._conversation()
            # 사용자 입력 원문을 그대로 두고, 답변 규칙만 앞에 붙여 전달한다.
            ask_query = (
                "다음 답변 규칙을 지켜서 답해 주세요.\n\n"
                + self.ANSWER_RULES
                + "\n\n"
                + "【사용자 상황】\n"
                + query
            )

            # 같은 대화를 동시에 실행하면 기록이 섞일 수 있어 중복 요청은 돌려보낸다.
            if not self.conversation_lock.acquire(blocking=False):
                self._respond(409, {"error": "앞선 답변을 기다린 뒤 다시 보내 주세요."})
                return
            if not self.server.request_slots.acquire(blocking=False):
                self.conversation_lock.release()
                self._respond(503, {"error": "지금 요청이 많아요. 잠시 뒤 다시 시도해 주세요."})
                return

            try:
                cmd = [
                    HERMES_CMD, "chat", "-c", conversation, "--create-if-missing",
                    "-q", ask_query, "--oneshot", "-Q",
                ]
                if SERVICE_MODE:
                    # MCP 서버 이름은 MCP 발견 전에 validate_toolset으로 잡히지 않지만,
                    # config.yaml의 mcp_servers 키 이름이면 cli.py에서 Unknown toolsets 경고 없이 넘어간다.
                    cmd.append("-t")
                    cmd.append("one-step-policy")
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=REQUEST_TIMEOUT,
                    env={**os.environ, "HERMES_HOME": HERMES_HOME},
                    cwd=WORK_DIR,
                )
                stdout = proc.stdout.strip()
                stderr = proc.stderr.strip()
                if proc.returncode != 0 or not stdout:
                    self._respond(500, {"error": "답변을 가져오지 못했어요. 잠시 뒤 다시 시도해 주세요."})
                    return
                self._respond(200, {"reply": stdout})
            except subprocess.TimeoutExpired:
                self._respond(504, {"error": "답변을 가져오는 데 시간이 오래 걸렸어요. 입력하신 내용을 유지한 채 다시 시도해 주세요."})
            except Exception:
                self._respond(500, {"error": "답변을 가져오지 못했어요. 잠시 뒤 다시 시도해 주세요."})
            finally:
                self.server.request_slots.release()
                self.conversation_lock.release()
            return
        self._respond(404, {"error": "not found"})

    def _respond(self, code, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if getattr(self, "conversation_cookie", None):
            self.send_header("Set-Cookie", self.conversation_cookie)
        self.send_header("Cache-Control", "no-store")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(data)

    def _serve_html(self):
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "preview", "index.html")
        try:
            with open(html_path, "rb") as f:
                data = f.read()
        except OSError as e:
            self._respond(500, {"error": f"html read error: {e}"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    if SERVICE_MODE:
        missing = _validate_service_prereqs()
        if missing:
            print("error: 서비스 시작 전 필수 설정이 빠져 있습니다:", file=sys.stderr)
            for item in missing:
                print(f"  - {item}", file=sys.stderr)
            print(
                "위 항목을 환경변수 또는 프로필 경로에 먼저 설정해 주세요.",
                file=sys.stderr,
            )
            sys.exit(3)

    port = int(os.environ.get("ONE_STEP_PORT", "9001"))
    raw_host = os.environ.get("ONE_STEP_HOST", "").strip()
    host = raw_host or "127.0.0.1"
    server = ConversationServer((host, port), Handler)
    print(f"one-step minimal bridge listening on {host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
