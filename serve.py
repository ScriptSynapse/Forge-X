"""FORGE-X production server (Waitress). Used for hosting, e.g. behind
Cloudflare Tunnel. For development keep using:  flask --app run run

    python serve.py
"""
import os
import sys

from waitress import serve

from app import create_app


def main():
    app = create_app()
    host = os.getenv("FORGE_X_HOST", "127.0.0.1")
    port = int(os.getenv("FORGE_X_PORT", "8000"))

    warnings = []
    if os.getenv("FLASK_DEBUG", "0").lower() in {"1", "true", "yes", "on"}:
        warnings.append("FLASK_DEBUG is on. Set FLASK_DEBUG=0 before going public.")
    if not app.config["SESSION_COOKIE_SECURE"]:
        warnings.append("SESSION_COOKIE_SECURE=0: set it to 1 when served over HTTPS (Cloudflare provides HTTPS).")
    if not app.config["TRUST_CLOUDFLARE"]:
        warnings.append("TRUST_CLOUDFLARE=0: behind Cloudflare Tunnel every visitor would appear as 127.0.0.1.")
    if host not in ("127.0.0.1", "localhost", "::1"):
        if app.config["TRUST_CLOUDFLARE"]:
            print("REFUSING TO START: TRUST_CLOUDFLARE=1 is only safe when FORGE_X_HOST is 127.0.0.1.")
            sys.exit(1)
        warnings.append(f"Listening on {host}: other machines on your network can reach the app directly.")
    for w in warnings:
        print("WARNING:", w)

    # One worker thread per pooled MySQL connection, so requests never wait for a free connection.
    threads = app.config["MYSQL_POOL_SIZE"]
    print(f"FORGE-X is running at http://{host}:{port} with {threads} threads. Press Ctrl+C to stop.")
    serve(app, host=host, port=port, threads=threads)


if __name__ == "__main__":
    main()
