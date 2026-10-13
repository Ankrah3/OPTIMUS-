# OPTIMUS — IT Helpdesk Ticket Tracker

A web-based helpdesk system for logging, assigning and tracking IT support tickets, with secure
login and role-based access. Built with **Python, Flask and SQLite**.

**🔗 Live demo: https://optimus-helpdesk.onrender.com** · Log in with the demo accounts shown on the sign-in page.

> The demo runs on a free plan, so the first load after a quiet period can take up to a minute.

I built this to model how a real IT support desk works: tickets are prioritised by urgency,
assigned to technicians, moved through a lifecycle, and summarised on a live dashboard.

<!-- Add screenshots here: ![Dashboard](docs/dashboard.png) -->

## Features
- **Login with roles**
  - **Technician:** create tickets, update status, and assign tickets to themselves only
  - **Admin:** everything above, plus assign to anyone, manage team accounts, and export CSV
- **Dashboard** with live counts: total, open, in progress, resolved, critical, average fix time
- Tickets with category (hardware, software, network, access, security) and priority
- Most-urgent-first ordering (critical → low, oldest first within a priority)
- Status lifecycle: `open` → `in_progress` → `resolved` → `closed`, with reopen support
- Filter by status, priority and category; CSV export for Excel / Power BI
- JSON REST API (so a mobile app can use it later) and a command-line interface

## Security
- Passwords are hashed (never stored in plain text) and must be at least 8 characters
- Sessions use HttpOnly, SameSite cookies (HTTPS-only when hosted) and expire after 8 hours
- Login attempts are rate-limited (5 failures per 5 minutes per user and client)
- Server-side permission checks on every endpoint, not just hidden buttons
- Deleted accounts lose access immediately; the last admin cannot be deleted
- Output is rendered as text, so ticket content cannot inject scripts (XSS)
- Security headers on every response

## Run locally
Requires Python 3.9+.

```bash
git clone https://github.com/Ankrah3/OPTIMUS-.git
cd OPTIMUS-
pip install -r requirements.txt
python -m optimus.web
```

Open **http://127.0.0.1:5000**. On the first run an `admin` account is created and its password is printed once in the terminal.
To choose your own, set `OPTIMUS_ADMIN_PASSWORD` before the first run.

To try it with sample data and demo accounts instead:
```powershell
# Windows (PowerShell)
$env:OPTIMUS_DEMO = "1"; python -m optimus.web
```
```bash
# macOS / Linux
OPTIMUS_DEMO=1 python -m optimus.web
```

Data is stored in `~/.optimus/tickets.db` (override with `OPTIMUS_DB`).

## Configuration
| Variable | Purpose |
|---|---|
| `OPTIMUS_SECRET_KEY` | Signs login sessions. Set a long random value in production. |
| `OPTIMUS_ADMIN_PASSWORD` | Password for the first `admin` account |
| `OPTIMUS_DEMO` | `1` seeds demo accounts and sample tickets |
| `OPTIMUS_DB` | Path to the SQLite database file |

## Deploy online (Render, free)
1. Push this repo to GitHub.
2. On [render.com](https://render.com), choose **New → Blueprint** and select the repo. Render reads `render.yaml`.
3. Deploy, then copy the public URL into the "Live demo" line above.

The free plan sleeps when idle (the first visit after a pause takes about a minute) and its disk is temporary, so demo data resets on restart.

## REST API
All endpoints except `/api/login` require a logged-in session.

| Method | Endpoint | Access | Description |
|---|---|---|---|
| POST | `/api/login`, `/api/logout` | public | Start / end a session |
| GET | `/api/me` | any | Current user |
| GET | `/api/tickets?status=&priority=&category=&assignee=` | any | List tickets |
| POST | `/api/tickets` | any | Create a ticket |
| GET | `/api/tickets/<id>` | any | Get one ticket |
| PATCH | `/api/tickets/<id>` | any* | Update `status` / `assignee` (*technicians: self only) |
| GET | `/api/stats` | any | Summary statistics |
| GET | `/api/export.csv` | admin | Download all tickets |
| GET, POST | `/api/users` | admin | List / create accounts |
| DELETE | `/api/users/<id>` | admin | Delete an account |

Errors return JSON like `{"error": "..."}` with status 400, 401, 403, 404 or 429.

## Command-line version
The same ticket database can be managed from the terminal:

```bash
python -m optimus add "Cannot connect to WiFi" -r Ama -c network -p high
python -m optimus list
python -m optimus stats
```

## Project structure
```
optimus/
  db.py          # ticket storage and validation
  auth.py        # user accounts, password hashing, login throttling
  web.py         # Flask app, permissions and JSON API
  templates/     # login.html and index.html (dashboard, vanilla JS)
  cli.py         # command-line interface
tests/           # 33 automated tests (storage, API, permissions, security)
render.yaml      # one-click deploy configuration
```

## Run the tests
```bash
python -m unittest -v
```

## Roadmap
- [ ] Ticket comments and history
- [ ] SLA tracking (flag tickets open longer than their priority allows)
- [ ] PostgreSQL for persistent hosted data
- [ ] React Native mobile client using the REST API

## Author
**David Ankrah** — B.Sc. Information Technology Management · [GitHub](https://github.com/Ankrah3)

## License
MIT
