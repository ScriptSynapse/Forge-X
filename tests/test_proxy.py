"""Hosting behind Cloudflare Tunnel: client IP and scheme handling (no MySQL needed)."""
from flask import Flask, jsonify, request

from app.proxy import trust_cloudflare


def make_app():
    app = Flask(__name__)

    @app.get("/who")
    def who():
        return jsonify(ip=request.remote_addr, secure=request.is_secure)

    return app


def test_cloudflare_headers_are_used_when_trusted():
    app = make_app()
    trust_cloudflare(app)
    data = app.test_client().get("/who", headers={"CF-Connecting-IP": "203.0.113.7", "X-Forwarded-Proto": "https"},
                                 environ_base={"REMOTE_ADDR": "127.0.0.1"}).get_json()
    assert data == {"ip": "203.0.113.7", "secure": True}


def test_malformed_header_keeps_the_socket_address():
    app = make_app()
    trust_cloudflare(app)
    data = app.test_client().get("/who", headers={"CF-Connecting-IP": "not-an-ip; DROP TABLE"},
                                 environ_base={"REMOTE_ADDR": "127.0.0.1"}).get_json()
    assert data["ip"] == "127.0.0.1"


def test_headers_are_ignored_when_not_trusted():
    data = make_app().test_client().get("/who", headers={"CF-Connecting-IP": "203.0.113.7"},
                                        environ_base={"REMOTE_ADDR": "127.0.0.1"}).get_json()
    assert data["ip"] == "127.0.0.1"
