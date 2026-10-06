# TaskFlow (demo)

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

## Deploy as an exe (LAN, password protected)
1. Build `dist/TaskFlow.exe`: run `build_exe.bat` on Windows, or run the **Build TaskFlow.exe** GitHub Action and download the artifact.
2. Copy that one file to the server folder (e.g. the CyberArk-managed PC) and double-click it. The console prints the team link, e.g. `http://192.168.1.20:8000`.
3. Every start asks the **start password** (`START_PASSWORD` in `backend/startgate.py`; change it there and rebuild). On the first run on a new server it then asks you to choose the **web login password** that your team uses; it is saved in `taskflow_config.json`. Change it later with `TaskFlow.exe --set-password`.
4. Everyone on the same Wi-Fi/LAN opens the link and signs in. Allow the port (8000, or `--port N`) in Windows Firewall if others cannot connect.
5. Put AI keys in a `.env` file **next to the exe** (same format as `.env` above).
6. **Updating:** stop the exe, replace `TaskFlow.exe` with the new one, start it. `tracker.db`, `.env` and the password live next to the exe and are kept.
Running from source (`uvicorn`) has no password; only the exe launcher turns the login on.
