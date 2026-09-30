from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ai, report
from .db import conn, init_db

app = FastAPI(title="Task Tracking Assistant")
STATIC = Path(__file__).resolve().parent.parent / "static"

STATUSES = ["To Do", "In Progress", "Blocked", "Done"]
PRIORITIES = ["Low", "Medium", "High"]
# text fields typed by people: any language in, English stored, original kept
TEXT_FIELDS = ["title", "blocker", "remarks"]
EMPLOYEE_EDITABLE = {"status", "progress", "blocker", "remarks"}


@app.on_event("startup")
def _startup():
    init_db()


def current_user(uid: Optional[int]):
    with conn() as c:
        u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        raise HTTPException(401, "Unknown user")
    return u


def now():
    return datetime.now().isoformat(timespec="seconds")


def task_view(rows, lang):
    """Rows -> dicts with title/blocker/remarks translated to lang (English is stored as-is)."""
    rows = [dict(r) for r in rows]
    if lang != "en":
        texts = [r[f] for r in rows for f in TEXT_FIELDS]
        out = iter(ai.translate_many(texts, lang))
        for r in rows:
            for f in TEXT_FIELDS:
                r[f + "_en"] = r[f]
                r[f] = next(out)
    else:
        for r in rows:
            for f in TEXT_FIELDS:
                r[f + "_en"] = r[f]
    for r in rows:
        r["overdue"] = bool(r["deadline"]) and r["deadline"] < date.today().isoformat() and r["status"] != "Done"
    return rows


@app.get("/api/config")
def config():
    with conn() as c:
        users = [dict(u) for u in c.execute("SELECT * FROM users ORDER BY id")]
    return {"users": users, "statuses": STATUSES, "priorities": PRIORITIES,
            "languages": {"en": "English", "mr": "मराठी", "hi": "हिंदी", "hinglish": "Hinglish"},
            "ai_enabled": ai.enabled()}


@app.get("/api/overview")
def overview(lang: str = "en", x_user_id: Optional[int] = Header(None)):
    if current_user(x_user_id)["role"] != "manager":
        raise HTTPException(403, "Managers only")
    out = []
    with conn() as c:
        for e in c.execute("SELECT * FROM users WHERE role='employee' ORDER BY id").fetchall():
            tasks = task_view(c.execute("SELECT * FROM tasks WHERE employee_id=? ORDER BY deadline", (e["id"],)), lang)
            open_t = [t for t in tasks if t["status"] != "Done"]
            blocked = [t for t in open_t if t["blocker_en"] or t["status"] == "Blocked"]
            out.append({
                "id": e["id"], "name": e["name"], "total": len(tasks),
                "done": sum(t["status"] == "Done" for t in tasks),
                "in_progress": sum(t["status"] == "In Progress" for t in tasks),
                "blocked": sum(t["status"] == "Blocked" for t in tasks),
                "overdue": sum(t["overdue"] for t in tasks),
                "avg_progress": round(sum(t["progress"] for t in tasks) / len(tasks)) if tasks else 0,
                "current_work": [t["title"] for t in open_t if t["status"] == "In Progress"][:3],
                "blockers": [f'{t["title"]}: {t["blocker"]}' if t["blocker"] else t["title"] for t in blocked],
            })
    return out


@app.get("/api/employees/{emp_id}/tasks")
def employee_tasks(emp_id: int, lang: str = "en", x_user_id: Optional[int] = Header(None)):
    u = current_user(x_user_id)
    if u["role"] != "manager" and u["id"] != emp_id:
        raise HTTPException(403, "You can only see your own sheet")
    with conn() as c:
        rows = c.execute("SELECT * FROM tasks WHERE employee_id=? ORDER BY "
                         "CASE status WHEN 'Done' THEN 1 ELSE 0 END, deadline, id", (emp_id,)).fetchall()
    return task_view(rows, lang)


class NewTask(BaseModel):
    employee_id: int
    title: str = Field(min_length=1)
    priority: str = "Medium"
    deadline: Optional[str] = None
    remarks: str = ""


@app.post("/api/tasks")
def add_task(t: NewTask, x_user_id: Optional[int] = Header(None)):
    if current_user(x_user_id)["role"] != "manager":
        raise HTTPException(403, "Managers only")
    if t.priority not in PRIORITIES:
        raise HTTPException(422, "Bad priority")
    ts = now()
    with conn() as c:
        cur = c.execute(
            """INSERT INTO tasks(employee_id,title,title_orig,priority,deadline,remarks,remarks_orig,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (t.employee_id, ai.to_english(t.title), t.title, t.priority, t.deadline or None,
             ai.to_english(t.remarks), t.remarks, ts, ts))
    return {"id": cur.lastrowid}


class TaskPatch(BaseModel):
    title: Optional[str] = None
    priority: Optional[str] = None
    deadline: Optional[str] = None
    status: Optional[str] = None
    progress: Optional[int] = Field(None, ge=0, le=100)
    blocker: Optional[str] = None
    remarks: Optional[str] = None
    employee_id: Optional[int] = None


@app.patch("/api/tasks/{task_id}")
def patch_task(task_id: int, p: TaskPatch, x_user_id: Optional[int] = Header(None)):
    u = current_user(x_user_id)
    changes = p.model_dump(exclude_unset=True)
    with conn() as c:
        t = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not t:
            raise HTTPException(404, "No such task")
        if u["role"] != "manager":
            if t["employee_id"] != u["id"]:
                raise HTTPException(403, "Not your task")
            if set(changes) - EMPLOYEE_EDITABLE:
                raise HTTPException(403, "Employees can only update status, progress, blocker and remarks")
        if changes.get("status") and changes["status"] not in STATUSES:
            raise HTTPException(422, "Bad status")
        if changes.get("priority") and changes["priority"] not in PRIORITIES:
            raise HTTPException(422, "Bad priority")
        sets, vals = [], []
        for k, v in changes.items():
            if k in TEXT_FIELDS:
                if k == "title" and not (v or "").strip():
                    raise HTTPException(422, "Title required")
                sets += [f"{k}=?", f"{k}_orig=?"]
                vals += [ai.to_english(v), v]
            else:
                sets.append(f"{k}=?")
                vals.append(v or None if k == "deadline" else v)
        if changes.get("status") == "Done":
            sets.append("progress=?"); vals.append(100)
        if sets:
            c.execute(f"UPDATE tasks SET {','.join(sets)}, updated_at=? WHERE id=?", vals + [now(), task_id])
    return {"ok": True}


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: int, x_user_id: Optional[int] = Header(None)):
    if current_user(x_user_id)["role"] != "manager":
        raise HTTPException(403, "Managers only")
    with conn() as c:
        c.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    return {"ok": True}


@app.get("/api/report")
def download_report(period: str = "weekly", x_user_id: Optional[int] = Header(None), user: Optional[int] = None):
    # `user` query param lets a plain browser download link identify the caller (no login in demo)
    if current_user(x_user_id or user)["role"] != "manager":
        raise HTTPException(403, "Managers only")
    if period not in ("weekly", "monthly"):
        raise HTTPException(422, "period must be weekly or monthly")
    data, name = report.build(period)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
