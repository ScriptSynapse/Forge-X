"""FORGE-X entry point.

Development:  flask --app run run      (or: python run.py)
"""
import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "0").lower() in {"1", "true", "yes", "on"}
    # 127.0.0.1 keeps the development server off the local network.
    app.run(host="127.0.0.1", port=5000, debug=debug)
