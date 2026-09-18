#!/usr/bin/env python3
"""Tiny OpenAI-compatible server used only by the clean-install CI smoke test."""

from __future__ import annotations

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SMOKE_TEXT = "AVO_HERMES_SMOKE_OK"
MODEL = "local-open-model"


class Handler(BaseHTTPRequestHandler):
    server_version = "AvoOpenAISmoke/1.0"

    def log_message(self, format: str, *args) -> None:
        sys.stderr.write("smoke-server: " + format % args + "\n")

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.rstrip("/") in {"/v1/models", "/models"}:
            self._json(
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": MODEL,
                            "object": "model",
                            "created": int(time.time()),
                            "owned_by": "avo-ci",
                        }
                    ],
                },
            )
            return
        if self.path.startswith("/v1/models/"):
            self._json(
                200,
                {
                    "id": MODEL,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "avo-ci",
                },
            )
            return
        self._json(404, {"error": {"message": f"unknown path {self.path}"}})

    def do_POST(self) -> None:
        if self.path.rstrip("/") not in {"/v1/chat/completions", "/chat/completions"}:
            self._json(404, {"error": {"message": f"unknown path {self.path}"}})
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            request = json.loads(raw)
        except json.JSONDecodeError:
            self._json(400, {"error": {"message": "invalid JSON"}})
            return

        model = str(request.get("model") or MODEL)
        created = int(time.time())
        if request.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            chunks = [
                {
                    "id": "chatcmpl-avo-smoke",
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": SMOKE_TEXT},
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "chatcmpl-avo-smoke",
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {"index": 0, "delta": {}, "finish_reason": "stop"}
                    ],
                    "usage": {
                        "prompt_tokens": 5,
                        "completion_tokens": 4,
                        "total_tokens": 9,
                    },
                },
            ]
            for chunk in chunks:
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return

        self._json(
            200,
            {
                "id": "chatcmpl-avo-smoke",
                "object": "chat.completion",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": SMOKE_TEXT,
                            "refusal": None,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 4,
                    "total_tokens": 9,
                },
            },
        )


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18080
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
