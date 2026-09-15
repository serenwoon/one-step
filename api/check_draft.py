# -*- coding: utf-8 -*-
"""send-check 전용 점검 API.

기존 /ask는 그대로 두고, 보내기 직전 초안 점검만 이 엔드포인트로 처리한다.
정책 컨텍스트는 기존 검색 카드에서 선택한 실제 정책 정보를 전달한다.
"""
from http.server import BaseHTTPRequestHandler
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skills.send_check.check_draft import (
    check_draft,
    preserve_draft,
    _non_trigger_hint,
    load_skill_text,
)


class handler(BaseHTTPRequestHandler):
    def respond(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        skill = load_skill_text()
        if skill is None:
            self.respond(500, {"ok": False, "error": "SKILL.md를 읽지 못했습니다."})
            return
        self.respond(
            200,
            {
                "ok": True,
                "runtime": "vercel-python",
                "skill": {
                    "loaded": True,
                    "path": str(Path(__file__).resolve().parent.parent / "skills" / "send_check" / "SKILL.md"),
                    "length": len(skill),
                },
            },
        )

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 200000:
                raise ValueError("요청이 너무 크거나 비어 있어요.")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("요청 형식을 확인해 주세요.")

            draft = data.get("draft", "")
            keyword = data.get("keyword", "")
            policy_choice = data.get("policyChoice", "")
            policy_context = data.get("policyContext")
            conversation = data.get("conversation")

            # 비발동 1차 힌트만 먼저 본다. 이것으로 초안을 거절하지 않는다.
            hint = _non_trigger_hint(draft) if isinstance(draft, str) else None

            result = check_draft(
                keyword=keyword,
                policy_choice=policy_choice,
                draft=draft,
                policy_context=policy_context,
                conversation=conversation,
                action=data.get("action", "check"),
                profile=data.get("profile"),
            )

            # 초안은 항상 보존한다. 자격 확정이나 전송은 하지 않는다.
            preserved = preserve_draft(
                keyword, policy_choice, draft, policy_context
            )

            self.respond(
                200,
                {
                    **result,
                    "preservedDraft": preserved,
                    "nonTriggerHint": hint,
                },
            )
        except ValueError as e:
            self.respond(400, {"error": str(e)})
        except Exception:
            self.respond(500, {"error": "점검 처리 중 문제가 생겼어요. 다시 시도해 주세요."})
