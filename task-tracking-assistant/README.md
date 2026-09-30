# Task Tracking Assistant (demo)

Excel-sheet-style task tracker. Manager gets an **Overview** tab plus one **sheet tab per employee**.
People type tasks / blockers / remarks in **English, Hindi, Marathi or Hinglish** — stored in English
(original text kept) and shown in any of the four languages via the language dropdown.
Manager can download a **weekly or monthly Excel report**.

## Run

```bash
cd task-tracking-assistant
pip install -r requirements.txt
cp .env.example .env        # paste your free Groq key from https://console.groq.com/keys
uvicorn backend.main:app --reload
```
Open http://localhost:8000. Without a Groq key the app still works; text is just not translated.

The demo has no login: use the **Logged in as** dropdown to switch between the manager and employees.
Employees see only their own sheet and can only update status, progress, blocker and remarks.
Sample data is seeded on first run into `tracker.db` (delete it to reset).

## API
`GET /api/config` · `GET /api/overview` · `GET /api/employees/{id}/tasks?lang=` · `POST /api/tasks` ·
`PATCH /api/tasks/{id}` · `DELETE /api/tasks/{id}` · `GET /api/report?period=weekly|monthly`
(all send `X-User-Id` to identify the acting user)
