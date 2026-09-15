"""Vercel Python API. 응답 본문과 비밀 값은 로그에 남기지 않는다."""
from http.server import BaseHTTPRequestHandler
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from solar_service import answer, ServiceError


class handler(BaseHTTPRequestHandler):
    def respond(self, status, payload):
        body=json.dumps(payload,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=200000:
                raise ServiceError(413,'요청이 너무 크거나 비어 있어요.')
            data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict):
                raise ValueError()
            self.respond(200,answer(data))
        except ServiceError as e:
            self.respond(e.status,{'error':str(e)})
        except (ValueError,TypeError):
            self.respond(400,{'error':'요청 형식을 확인해 주세요.'})
        except Exception:
            self.respond(500,{'error':'답변 처리 중 문제가 생겼어요. 다시 시도해 주세요.'})
