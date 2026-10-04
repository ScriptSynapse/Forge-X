"""Download FORGE-X's front-end libraries into app/static/vendor/ (run once).

Why local copies instead of CDN links?
  * The app works offline in a lab or during a viva demonstration.
  * The Content Security Policy can allow scripts from our own server only.

Usage (from the project folder, with the virtual environment active):
    python tools/fetch_vendor.py

Every file's SHA-256 is printed and saved to app/static/vendor/SHA256SUMS.txt,
so you can show exactly which library versions the project ships.

Licences: Bootstrap and Bootstrap Icons (MIT), Chart.js (MIT),
IBM Plex fonts via Fontsource (SIL Open Font License 1.1).
"""
import hashlib
import sys
import urllib.request
from pathlib import Path

CDN = "https://cdn.jsdelivr.net/npm"
VENDOR = Path(__file__).resolve().parent.parent / "app" / "static" / "vendor"

FILES = {
    "bootstrap/bootstrap.min.css":            f"{CDN}/bootstrap@5.3.3/dist/css/bootstrap.min.css",
    "bootstrap/bootstrap.bundle.min.js":      f"{CDN}/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js",
    "bootstrap-icons/bootstrap-icons.min.css": f"{CDN}/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css",
    "bootstrap-icons/fonts/bootstrap-icons.woff2": f"{CDN}/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff2",
    "bootstrap-icons/fonts/bootstrap-icons.woff":  f"{CDN}/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff",
    "chartjs/chart.umd.js":                   f"{CDN}/chart.js@4.4.1/dist/chart.umd.js",
}
for weight in (400, 500, 600, 700):
    name = f"ibm-plex-sans-latin-{weight}-normal.woff2"
    FILES[f"fonts/{name}"] = f"{CDN}/@fontsource/ibm-plex-sans@5/files/{name}"
for weight in (400, 500):
    name = f"ibm-plex-mono-latin-{weight}-normal.woff2"
    FILES[f"fonts/{name}"] = f"{CDN}/@fontsource/ibm-plex-mono@5/files/{name}"


def download(url, target):
    request = urllib.request.Request(url, headers={"User-Agent": "FORGE-X vendor fetch"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read()
    if not data:
        raise ValueError("empty response")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return hashlib.sha256(data).hexdigest(), len(data)


def main():
    failures, sums = [], []
    for relative, url in FILES.items():
        target = VENDOR / relative
        try:
            digest, size = download(url, target)
        except Exception as exc:  # report every failure, keep going
            failures.append((relative, exc))
            print(f"  FAILED  {relative}: {exc}")
            continue
        sums.append(f"{digest}  {relative}")
        print(f"  ok      {relative}  ({size:,} bytes)  sha256 {digest[:16]}…")

    if sums:
        (VENDOR / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")

    print()
    if failures:
        print(f"{len(failures)} file(s) failed. Check your internet connection and run the script again.")
        print("Pages still work without them, but styling, icons or fonts will be missing.")
        sys.exit(1)
    print(f"All {len(sums)} files saved to {VENDOR}")


if __name__ == "__main__":
    main()
