# Hosting FORGE-X with Cloudflare Tunnel (Windows)

FORGE-X and MySQL keep running on **your Windows machine**. `cloudflared` opens an **outbound-only**, encrypted connection to Cloudflare, and Cloudflare gives the app a public **HTTPS** address.

* No router ports are opened.
* MySQL is never exposed to the internet.
* The site is online only while your PC, MySQL, `serve.py` and `cloudflared` are all running.

**Why not Cloudflare Pages, Workers or D1?** Pages hosts static sites only, Workers don't run a standard Flask + `mysql-connector` server, and D1 is SQLite, which would break the project's MySQL-only requirement.

---

## 1. Prepare FORGE-X for public access

Edit `.env`:

```ini
FLASK_DEBUG=0              # never expose Flask's debugger
SESSION_COOKIE_SECURE=1    # cookies only over HTTPS (Cloudflare provides HTTPS)
TRUST_CLOUDFLARE=1         # use the visitor's real IP from Cloudflare's header
FORGE_X_HOST=127.0.0.1     # only cloudflared on this PC can reach the app
FORGE_X_PORT=8000
```

Install the production server and start FORGE-X (Command Prompt, in the project folder, `.venv` active):

```cmd
pip install -r requirements.txt
python serve.py
```

You should see `FORGE-X is running at http://127.0.0.1:8000`. Leave this window open.

* `serve.py` uses **Waitress**, a production web server. Flask's built-in server is for development only.
* It prints a warning for any unsafe setting.
* It refuses to start if `TRUST_CLOUDFLARE=1` is combined with a public listening address, because anyone could then fake their IP address.

## 2. Install cloudflared

Open a **second** Command Prompt:

```cmd
winget install --id Cloudflare.cloudflared -e
```

Close and reopen the Command Prompt, then check it works with `cloudflared --version`.

## 3a. Quick tunnel: free, no account, temporary address

Best for a demonstration or your viva.

```cmd
cloudflared tunnel --url http://127.0.0.1:8000
```

After a few seconds it prints an address like `https://four-random-words.trycloudflare.com`. Open it from any device.

**Limits:**
* The address changes every time you start the tunnel.
* It stops when you close the window.
* There's no access control: anyone with the link reaches your login page.
* Cloudflare limits how many requests a quick tunnel can handle.

## 3b. Named tunnel: permanent address on your own domain

This needs a domain whose DNS is managed by Cloudflare. A free Cloudflare account is enough; the domain itself usually costs money.

1. In the Cloudflare dashboard, open **Zero Trust → Networks → Tunnels** and choose **Create a tunnel → Cloudflared**. Name it, for example `forge-x`. Menu names may differ slightly as Cloudflare updates its dashboard.
2. Choose **Windows**. Copy the install command it shows, which contains a secret token. Run it in a Command Prompt **opened as Administrator**:
   ```cmd
   cloudflared.exe service install <YOUR-TUNNEL-TOKEN>
   ```
   This installs cloudflared as a Windows service, so the tunnel reconnects automatically after a restart. **Keep the token secret.**
3. Add a **public hostname**, for example `forgex.yourdomain.com`, with **Service** `HTTP` and URL `127.0.0.1:8000`.
4. Open `https://forgex.yourdomain.com`.

## 4. Recommended: put Cloudflare Access in front

FORGE-X has its own login. Even so, a forensic records system shouldn't be reachable by the whole internet. Cloudflare Access adds a check **before** anyone reaches FORGE-X, such as a one-time code sent to an approved email address. It works only with a named tunnel (3b), and Cloudflare's free plan covers a small team.

In **Zero Trust → Access → Applications**:
1. **Add an application → Self-hosted.**
2. Set the hostname to `forgex.yourdomain.com`.
3. Add a policy: **Allow** → **Emails** → the addresses of your team and examiners.
4. Turn on the **One-time PIN** login method.

Visitors who aren't on the list never reach FORGE-X, including its public signup page.

## 5. Security checklist before sharing the link

- [ ] `FLASK_DEBUG=0`, a strong `FORGE_X_SECRET_KEY`, and `SESSION_COOKIE_SECURE=1`
- [ ] `TRUST_CLOUDFLARE=1` and `FORGE_X_HOST=127.0.0.1`
- [ ] **Synthetic data only.** Never put real investigative data on a demo system.
- [ ] MySQL isn't reachable from your network. Windows Firewall blocks inbound port 3306 by default; don't add a rule that allows it.
- [ ] Flask connects as `forge_x_app`, not root (`flask --app run check-db` confirms this)
- [ ] For a named tunnel: Cloudflare Access is limited to your team
- [ ] `flask --app run check-db` shows **All checks passed**

## 6. Evidence files and the upload limit

Cloudflare's free plan rejects request bodies over 100 MB, which is why `EVIDENCE_MAX_MB` defaults to 100. Raising it only helps for local use: uploads through the tunnel would still be cut off at 100 MB. Back up `EVIDENCE_STORAGE_DIR` together with the database.

## 7. Everyday running

| Step | Quick tunnel | Named tunnel |
|---|---|---|
| MySQL | MySQL80 service (starts with Windows) | same |
| FORGE-X | `python serve.py` in one window | same |
| Tunnel | `cloudflared tunnel --url http://127.0.0.1:8000` in a second window | runs as a Windows service |

**Notes:**
* Turning the PC off, or letting it sleep, takes the site offline.
* While hosted, keep developing with `flask --app run run` on port 5000, separately.
* Set `TRUST_CLOUDFLARE=0` and `SESSION_COOKIE_SECURE=0` again if you go back to plain local `http://` use. Otherwise the browser may not keep you logged in.
