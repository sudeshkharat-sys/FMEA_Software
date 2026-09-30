# Task Tracking Assistant (demo)

Excel-sheet-style task tracker. Manager gets an **Overview** tab plus one **sheet tab per employee**.
People type tasks / blockers / remarks in **English, Hindi, Marathi or Hinglish** — stored in English
(original text kept) and shown in any of the four languages via the language dropdown.
Manager can download a **weekly or monthly Excel report**.

## First use
1. Open the app: it asks you to **create a team**: team name, the leader/manager (name + position) and the employees (name + position).
   (Or click "Try with sample data".)
2. As the leader, open a person's tab and add tasks. Use the **⚙️ Team** tab to add/remove members, and **+ New team** for more teams.
3. English is the default view. The **Translate** button (top) shows task text in मराठी, हिंदी or Hinglish. **✦ Summarize** (team overview and every profile) gives an AI summary of tasks, progress and blockers in the selected language.
4. Everything (tasks, blockers, remarks) can be typed in English, Hindi, Marathi or Hinglish. It is saved in English and shown in the language picked at the top.
5. **Report ↓** downloads the weekly or monthly report for the current team.

## Run

```bash
cd task-tracking-assistant
pip install -r requirements.txt
cp .env.example .env        # set ONE provider in .env: OpenAI/GPT-4o-mini, Azure OpenAI, or free Groq
uvicorn backend.main:app --reload
```
Open http://localhost:8000. Without an API key the app still works; text is just not translated.

The demo has no login: use the **Logged in as** dropdown to switch between the manager and employees.
Each team is isolated. Employees see only their own sheet and can only update status, progress, blocker and remarks.
Data is stored in `tracker.db` (delete it, with the server stopped, to start over).

## API
`GET /api/config` · `GET /api/overview` · `GET /api/employees/{id}/tasks?lang=` · `POST /api/tasks` ·
`PATCH /api/tasks/{id}` · `DELETE /api/tasks/{id}` · `GET /api/report?period=weekly|monthly`
(all send `X-User-Id` to identify the acting user)
