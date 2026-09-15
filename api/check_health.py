from http.server import BaseHTTPRequestHandler
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skills.send_check.check_draft import load_skill_text, _non_trigger_hint


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        skill = load_skill_text()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(
            json.dumps(
                {
                    "ok": True,
                    "runtime": "vercel-python",
                    "sendCheck": {
                        "skillLoaded": bool(skill),
                        "skillPath": str(
                            Path(__file__).resolve().parent.parent
                            / "skills"
                            / "send_check"
                            / "SKILL.md"
                        ),
                        "skillLength": len(skill) if skill else 0,
                    },
                },
                ensure_ascii=False,
            ).encode()
        )
