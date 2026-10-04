"""Running behind Cloudflare Tunnel.

cloudflared forwards every request from 127.0.0.1, so without this the app
would see the same IP for every visitor and the per-IP login limit would
lock everyone out together. Cloudflare puts the visitor's address in the
CF-Connecting-IP header, and the scheme (https) in X-Forwarded-Proto.

These headers are trusted ONLY when TRUST_CLOUDFLARE=1, and that is only
safe when the app listens on 127.0.0.1 (serve.py's default), so that the
local cloudflared is the only thing that can reach it. Otherwise anyone
could send a fake header and pick their own "IP address".
"""
import ipaddress

from werkzeug.middleware.proxy_fix import ProxyFix


class CloudflareClientIP:
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        candidate = (environ.get("HTTP_CF_CONNECTING_IP") or "").strip()
        try:
            environ["REMOTE_ADDR"] = str(ipaddress.ip_address(candidate))
        except ValueError:
            pass                                  # missing or malformed: keep the real socket address
        return self.wsgi_app(environ, start_response)


def trust_cloudflare(app):
    # x_proto=1: believe X-Forwarded-Proto (https) from the one proxy in front of us.
    app.wsgi_app = CloudflareClientIP(ProxyFix(app.wsgi_app, x_proto=1))
