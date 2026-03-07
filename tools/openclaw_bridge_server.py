#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer


class H(BaseHTTPRequestHandler):
    def _send(self, code: int, payload: dict):
        b = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == '/health':
            return self._send(200, {'ok': True})
        return self._send(404, {'ok': False, 'error': 'not_found'})

    def do_POST(self):
        if self.path != '/generate':
            return self._send(404, {'ok': False, 'error': 'not_found'})
        try:
            ln = int(self.headers.get('Content-Length') or 0)
            raw = self.rfile.read(ln).decode('utf-8', 'ignore') if ln > 0 else '{}'
            body = json.loads(raw or '{}')
            msg = str(body.get('message') or '').strip()
            if not msg:
                return self._send(400, {'ok': False, 'error': 'empty_message'})

            sess = f"ulbridge-{uuid.uuid4().hex[:10]}"
            cmd = [
                'openclaw', 'agent', '--local', '--agent', 'bridge',
                '--session-id', sess,
                '--message', msg,
                '--json', '--timeout', '120'
            ]
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=170)
            if p.returncode != 0:
                return self._send(502, {'ok': False, 'error': (p.stderr or p.stdout or 'bridge_failed')[:500]})

            out = json.loads((p.stdout or '').strip() or '{}')
            payloads = out.get('payloads') or []
            txt = ''
            if payloads and isinstance(payloads[0], dict):
                txt = str(payloads[0].get('text') or '').strip()
            if not txt:
                return self._send(502, {'ok': False, 'error': 'empty_bridge_reply'})
            return self._send(200, {'ok': True, 'text': txt})
        except Exception as e:
            return self._send(500, {'ok': False, 'error': str(e)[:220]})


if __name__ == '__main__':
    srv = HTTPServer(('0.0.0.0', 18991), H)
    srv.serve_forever()
