import re
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ai, report
from .db import conn, create_team, init_db, seed_sample

app = FastAPI(title="Task Tracking Assistant")
STATIC = Path(__file__).resolve().parent.parent / "static"

STATUSES = ["To Do", "In Progress", "Blocked", "Done"]
PRIORITIES = ["Low", "Medium", "High"]
# text fields typed by people: any language in, English stored, original kept
TEXT_FIELDS = ["title", "blocker", "remarks"]
EMPLOYEE_EDITABLE = {"status", "progress", "blocker", "remarks"}


_DEVANAGARI = re.compile(r"[\u0900-\u097F]")


def repair_existing():
    """Rows saved while AI was off/failing may hold Hindi/Marathi in the English columns; convert them now."""
    if not ai.enabled():
        return
    with conn() as c:
        rows = c.execute("SELECT id,title,blocker,remarks FROM tasks").fetchall()
    fixed = 0
    for r in rows:
        for f in TEXT_FIELDS:
            cur = (r[f] or "").strip()
            if cur and _DEVANAGARI.search(cur):
                en, ok = ai.to_english(cur)
                if ok and en and en != cur:
                    with conn() as c:
                        c.execute(f"UPDATE tasks SET {f}=? WHERE id=?", (en, r["id"]))
                    fixed += 1
    if fixed:
        print(f"[ai] converted {fixed} old text field(s) to English")


@app.on_event("startup")
def _startup():
    init_db()
    print("[ai] provider:", ai.describe(), "| enabled" if ai.enabled() else "| DISABLED (no key found in .env)")
    threading.Thread(target=repair_existing, daemon=True).start()


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


def require_manager(u):
    if u["role"] != "manager":
        raise HTTPException(403, "Managers only")


def employee_in_team(c, emp_id, team_id):
    e = c.execute("SELECT * FROM users WHERE id=? AND team_id=? AND role='employee'", (emp_id, team_id)).fetchone()
    if not e:
        raise HTTPException(404, "No such employee in your team")
    return e


@app.get("/api/config")
def config():
    with conn() as c:
        teams = []
        for t in c.execute("SELECT * FROM teams ORDER BY id"):
            members = [dict(u) for u in c.execute(
                "SELECT id,name,role,position FROM users WHERE team_id=? ORDER BY role DESC, id", (t["id"],))]
            teams.append({"id": t["id"], "name": t["name"], "members": members})
    return {"teams": teams, "statuses": STATUSES, "priorities": PRIORITIES,
            "languages": {"en": "English", "mr": "मराठी", "hi": "हिंदी", "hinglish": "Hinglish"},
            "ai_enabled": ai.enabled()}


class Member(BaseModel):
    name: str = Field("", max_length=80)
    position: str = Field("", max_length=80)


class TeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    leader_name: str = Field(min_length=1, max_length=80)
    leader_position: str = Field("Team Lead", max_length=80)
    members: list[Member] = []


@app.post("/api/teams")
def add_team(t: TeamIn, x_user_id: Optional[int] = Header(None)):
    """First team can be created by anyone (initial setup). After that only a manager can add teams."""
    with conn() as c:
        if c.execute("SELECT COUNT(*) FROM teams").fetchone()[0]:
            require_manager(current_user(x_user_id))
        members = [(m.name.strip(), m.position.strip()) for m in t.members if m.name.strip()]
        tid, lid, _ = create_team(c, t.name.strip(), t.leader_name.strip(), t.leader_position.strip(), members)
    return {"team_id": tid, "leader_id": lid}


@app.post("/api/sample-team")
def sample_team():
    with conn() as c:
        if c.execute("SELECT COUNT(*) FROM teams").fetchone()[0]:
            raise HTTPException(409, "A team already exists")
        return {"team_id": seed_sample(c)}


@app.post("/api/members")
def add_member(m: Member, x_user_id: Optional[int] = Header(None)):
    u = current_user(x_user_id)
    require_manager(u)
    if not m.name.strip():
        raise HTTPException(422, "Name required")
    with conn() as c:
        uid = c.execute("INSERT INTO users(name,role,team_id,position) VALUES(?,?,?,?)",
                        (m.name.strip(), "employee", u["team_id"], m.position.strip())).lastrowid
    return {"id": uid}


@app.delete("/api/members/{emp_id}")
def remove_member(emp_id: int, x_user_id: Optional[int] = Header(None)):
    u = current_user(x_user_id)
    require_manager(u)
    with conn() as c:
        employee_in_team(c, emp_id, u["team_id"])
        c.execute("DELETE FROM remarks WHERE task_id IN (SELECT id FROM tasks WHERE employee_id=?)", (emp_id,))
        c.execute("DELETE FROM tasks WHERE employee_id=?", (emp_id,))
        c.execute("DELETE FROM users WHERE id=?", (emp_id,))
    return {"ok": True}


@app.get("/api/overview")
def overview(lang: str = "en", x_user_id: Optional[int] = Header(None)):
    u = current_user(x_user_id)
    require_manager(u)
    out = []
    with conn() as c:
        for e in c.execute("SELECT * FROM users WHERE role='employee' AND team_id=? ORDER BY id", (u["team_id"],)).fetchall():
            tasks = task_view(c.execute("SELECT * FROM tasks WHERE employee_id=? ORDER BY deadline", (e["id"],)), lang)
            open_t = [t for t in tasks if t["status"] != "Done"]
            blocked = [t for t in open_t if t["blocker_en"] or t["status"] == "Blocked"]
            soon = (date.today() + timedelta(days=2)).isoformat()
            attention = [{"title": t["title"], "reason": "Overdue" if t["overdue"] else "Blocked" if t in blocked else "Due " + t["deadline"]}
                         for t in open_t if t["overdue"] or t in blocked or (t["deadline"] and t["deadline"] <= soon)]
            out.append({
                "attention": attention, "risk": 3 * sum(t["overdue"] for t in tasks) + 2 * len(blocked) + len(attention),
                "id": e["id"], "name": e["name"], "position": e["position"], "total": len(tasks),
                "done": sum(t["status"] == "Done" for t in tasks),
                "in_progress": sum(t["status"] == "In Progress" for t in tasks),
                "blocked": sum(t["status"] == "Blocked" for t in tasks),
                "overdue": sum(t["overdue"] for t in tasks),
                "avg_progress": round(sum(t["progress"] for t in tasks) / len(tasks)) if tasks else 0,
                "current_work": [{"title": t["title"], "progress": t["progress"], "deadline": t["deadline"], "overdue": t["overdue"]}
                                 for t in open_t if t["status"] == "In Progress"],
                "blockers": [{"title": t["title"], "blocker": t["blocker"]} for t in blocked],
                "open_tasks": [{"title": t["title"], "status": t["status"], "progress": t["progress"], "deadline": t["deadline"],
                                "overdue": t["overdue"], "blocker": t["blocker"], "remark": t["remarks"]} for t in open_t],
            })
    out.sort(key=lambda e: (-e["risk"], e["id"]))  # most at-risk people first
    return out


@app.get("/api/employees/{emp_id}/tasks")
def employee_tasks(emp_id: int, lang: str = "en", x_user_id: Optional[int] = Header(None)):
    u = current_user(x_user_id)
    if u["role"] != "manager" and u["id"] != emp_id:
        raise HTTPException(403, "You can only see your own sheet")
    with conn() as c:
        employee_in_team(c, emp_id, u["team_id"])
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
    u = current_user(x_user_id)
    require_manager(u)
    if t.priority not in PRIORITIES:
        raise HTTPException(422, "Bad priority")
    ts = now()
    title_en, ok1 = ai.to_english(t.title)
    ok2 = True
    with conn() as c:
        employee_in_team(c, t.employee_id, u["team_id"])
        cur = c.execute(
            """INSERT INTO tasks(employee_id,title,title_orig,priority,deadline,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?)""",
            (t.employee_id, title_en, t.title, t.priority, t.deadline or None, ts, ts))
        if t.remarks.strip():
            ok2 = add_remark(c, cur.lastrowid, u["id"], t.remarks.strip())
    return {"id": cur.lastrowid, "translated": ok1 and ok2}


def add_remark(c, task_id, author_id, text):
    """Append to a task's remark thread (stored in English) and mirror the latest into tasks.remarks."""
    en, ok = ai.to_english(text)
    ts = now()
    c.execute("INSERT INTO remarks(task_id,author_id,text,text_orig,created_at) VALUES(?,?,?,?,?)",
              (task_id, author_id, en, text, ts))
    c.execute("UPDATE tasks SET remarks=?, remarks_orig=?, updated_at=? WHERE id=?", (en, text, ts, task_id))
    return ok


def task_for(c, u, task_id):
    t = c.execute("SELECT t.*, u.team_id FROM tasks t JOIN users u ON u.id=t.employee_id WHERE t.id=?", (task_id,)).fetchone()
    if not t or t["team_id"] != u["team_id"]:
        raise HTTPException(404, "No such task")
    if u["role"] != "manager" and t["employee_id"] != u["id"]:
        raise HTTPException(403, "Not your task")
    return t


@app.get("/api/tasks/{task_id}/remarks")
def list_remarks(task_id: int, lang: str = "en", x_user_id: Optional[int] = Header(None)):
    u = current_user(x_user_id)
    with conn() as c:
        task_for(c, u, task_id)
        rows = [dict(r) for r in c.execute(
            """SELECT r.id,r.text,r.created_at,r.author_id,COALESCE(a.name,'Earlier note') AS author,a.role AS author_role
               FROM remarks r LEFT JOIN users a ON a.id=r.author_id WHERE r.task_id=? ORDER BY r.id""", (task_id,))]
    if lang != "en" and rows:
        for r, txt in zip(rows, ai.translate_many([r["text"] for r in rows], lang)):
            r["text"] = txt
    return rows


class RemarkIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


@app.post("/api/tasks/{task_id}/remarks")
def post_remark(task_id: int, r: RemarkIn, x_user_id: Optional[int] = Header(None)):
    u = current_user(x_user_id)
    if not r.text.strip():
        raise HTTPException(422, "Remark is empty")
    with conn() as c:
        task_for(c, u, task_id)
        ok = add_remark(c, task_id, u["id"], r.text.strip())
    return {"ok": True, "translated": ok}


class QuickTask(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    employee_id: int


@app.post("/api/tasks/quick")
def quick_task(q: QuickTask, x_user_id: Optional[int] = Header(None)):
    """One plain sentence in; AI pulls out the task name, deadline (if said), priority and assignee (if a member is named)."""
    u = current_user(x_user_id)
    require_manager(u)
    with conn() as c:
        employee_in_team(c, q.employee_id, u["team_id"])
        members = [dict(m) for m in c.execute(
            "SELECT id,name FROM users WHERE team_id=? AND role='employee'", (u["team_id"],))]
    p, parsed = ai.parse_task(q.text, date.today().isoformat(), [m["name"] for m in members])
    emp_id = q.employee_id
    who = (p.get("assignee") or "").strip().lower()
    if who:
        hit = [m for m in members if m["name"].lower() == who or m["name"].lower().split()[0] == who.split()[0]]
        if len(hit) == 1:
            emp_id = hit[0]["id"]
    title_en, ok = ai.to_english(p["title"])
    deadline = p.get("deadline")
    try:
        deadline = date.fromisoformat(deadline).isoformat() if deadline else None
    except ValueError:
        deadline = None
    pri = p.get("priority") if p.get("priority") in PRIORITIES else "Medium"
    ts = now()
    with conn() as c:
        cur = c.execute(
            """INSERT INTO tasks(employee_id,title,title_orig,priority,deadline,remarks,remarks_orig,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)""", (emp_id, title_en, q.text, pri, deadline, "", "", ts, ts))
    return {"id": cur.lastrowid, "employee_id": emp_id, "title": title_en, "deadline": deadline,
            "priority": pri, "ai": parsed, "translated": ok}


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
        t = c.execute("SELECT t.*, u.team_id FROM tasks t JOIN users u ON u.id=t.employee_id WHERE t.id=?",
                      (task_id,)).fetchone()
        if not t or t["team_id"] != u["team_id"]:
            raise HTTPException(404, "No such task")
        if changes.get("employee_id") is not None:
            employee_in_team(c, changes["employee_id"], u["team_id"])
        if u["role"] != "manager":
            if t["employee_id"] != u["id"]:
                raise HTTPException(403, "Not your task")
            if set(changes) - EMPLOYEE_EDITABLE:
                raise HTTPException(403, "Employees can only update status, progress, blocker and remarks")
        if changes.get("status") and changes["status"] not in STATUSES:
            raise HTTPException(422, "Bad status")
        if changes.get("priority") and changes["priority"] not in PRIORITIES:
            raise HTTPException(422, "Bad priority")
        sets, vals, translated = [], [], True
        if (changes.get("remarks") or "").strip():
            translated = add_remark(c, task_id, u["id"], changes["remarks"].strip())
        changes.pop("remarks", None)
        for k, v in changes.items():
            if k in TEXT_FIELDS:
                if k == "title" and not (v or "").strip():
                    raise HTTPException(422, "Title required")
                en, ok = ai.to_english(v)
                translated = translated and ok
                sets += [f"{k}=?", f"{k}_orig=?"]
                vals += [en, v]
            else:
                sets.append(f"{k}=?")
                vals.append(v or None if k == "deadline" else v)
        if changes.get("status") == "Done":
            sets.append("progress=?"); vals.append(100)
        if sets:
            c.execute(f"UPDATE tasks SET {','.join(sets)}, updated_at=? WHERE id=?", vals + [now(), task_id])
    return {"ok": True, "translated": translated}


PRIO_RANK = {"High": 0, "Medium": 1, "Low": 2}


def _facts_and_fallback(c, people, today):
    """Plain-text facts for the LLM plus a rule-based English summary used when AI is off or fails.
    Order everywhere: finished-everything people first, then ongoing work, then the rest; High priority first."""
    facts, finished = [f"Today: {today}"], []
    tot = done = overdue = 0
    ongoing, remaining, blockers, late = [], [], [], []
    multi = len(people) > 1
    for p in people:
        tasks = [dict(t) for t in c.execute("SELECT * FROM tasks WHERE employee_id=?", (p["id"],))]
        tasks.sort(key=lambda t: (PRIO_RANK.get(t["priority"], 1), t["deadline"] or "9999"))
        n_done = sum(t["status"] == "Done" for t in tasks)
        all_done = bool(tasks) and n_done == len(tasks)
        facts.append(f"\n{p['name']} ({p['position'] or 'team member'}): {len(tasks)} tasks, {n_done} done"
                     + (" -> HAS COMPLETED ALL TASKS" if all_done else ""))
        if all_done:
            finished.append(p["name"])
        for grp, label in (("In Progress", "ONGOING"), ("Open", "REMAINING"), ("Done", "COMPLETED")):
            sel = [t for t in tasks if (t["status"] == "Done") == (grp == "Done") and (grp != "In Progress" or t["status"] == "In Progress")
                   and (grp != "Open" or t["status"] in ("To Do", "Blocked"))]
            for t in sel:
                od = bool(t["deadline"]) and t["deadline"] < today and t["status"] != "Done"
                facts.append(f"- [{label}] [{t['priority']} priority] {t['title']}; {t['status']}; {t['progress']}%; due {t['deadline'] or 'n/a'}"
                             + ("; OVERDUE" if od else "") + (f"; blocker: {t['blocker']}" if t["blocker"] else "")
                             + (f"; remarks: {t['remarks']}" if t["remarks"] else ""))
        who = f"{p['name']}: " if multi else ""
        for t in tasks:
            od = bool(t["deadline"]) and t["deadline"] < today and t["status"] != "Done"
            tot += 1; done += t["status"] == "Done"; overdue += od
            if t["status"] == "Done":
                continue
            r = PRIO_RANK.get(t["priority"], 1)
            line = f"{who}{t['title']} [{t['priority']}]"
            if t["status"] == "In Progress":
                ongoing.append((r, f"{line} ({t['progress']}%)"))
            else:
                remaining.append((r, f"{line} ({t['status']})"))
            if t["blocker"]:
                blockers.append((r, f"{who}{t['title']} [{t['priority']}] - {t['blocker']}"))
            if od:
                late.append((r, f"{who}{t['title']} [{t['priority']}] (due {t['deadline']})"))
    if not tot:
        return "\n".join(facts), "• No tasks yet."
    ongoing, remaining, blockers, late = ([x for _, x in sorted(g, key=lambda i: i[0])] for g in (ongoing, remaining, blockers, late))
    lines = []
    if finished:
        lines.append(("• " + ", ".join(finished) + (" have" if len(finished) > 1 else " has") + " completed all tasks.")
                     if multi else "• Completed all tasks.")
        if not multi:
            return "\n".join(facts), "\n".join(lines)

    def section(label, items):
        if items:
            lines.append(f"• {label}:")
            lines.extend(f"   – {x}" for x in items)
    section("Ongoing (high priority first)", ongoing or ["Nothing in progress right now"])
    section("Remaining (high priority first)", remaining)
    section("Blockers", blockers)
    section("Overdue", late)
    lines.append(f"• Overall: {done} of {tot} tasks done ({round(100 * done / tot)}%)")
    return "\n".join(facts), "\n".join(lines)


@app.post("/api/summary")
def summary(employee_id: Optional[int] = None, lang: str = "en", x_user_id: Optional[int] = Header(None)):
    """AI summary of one person's tasks/blockers, or (manager only, no employee_id) the whole team."""
    u = current_user(x_user_id)
    with conn() as c:
        if employee_id is None:
            require_manager(u)
            people = c.execute("SELECT * FROM users WHERE role='employee' AND team_id=? ORDER BY id", (u["team_id"],)).fetchall()
            scope = "the whole team's work"
        else:
            if u["role"] != "manager" and u["id"] != employee_id:
                raise HTTPException(403, "You can only summarize your own work")
            people = [employee_in_team(c, employee_id, u["team_id"])]
            scope = f"one team member's work ({people[0]['name']})"
        facts, fallback = _facts_and_fallback(c, people, date.today().isoformat())
    if not ai.enabled():
        return {"summary": fallback, "ai": False, "lang": "en"}
    try:
        return {"summary": ai.summarize(facts, lang, scope), "ai": True, "lang": lang}
    except Exception as e:
        print("summary failed:", e)
        return {"summary": fallback, "ai": False, "lang": "en"}


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: int, x_user_id: Optional[int] = Header(None)):
    u = current_user(x_user_id)
    require_manager(u)
    with conn() as c:
        c.execute("DELETE FROM remarks WHERE task_id=? AND task_id IN (SELECT t.id FROM tasks t JOIN users x ON x.id=t.employee_id WHERE x.team_id=?)",
                  (task_id, u["team_id"]))
        c.execute("DELETE FROM tasks WHERE id=? AND employee_id IN (SELECT id FROM users WHERE team_id=?)",
                  (task_id, u["team_id"]))
    return {"ok": True}


@app.get("/api/report")
def download_report(period: str = "weekly", x_user_id: Optional[int] = Header(None), user: Optional[int] = None):
    # `user` query param lets a plain browser download link identify the caller (no login in demo)
    u = current_user(x_user_id or user)
    require_manager(u)
    if period not in ("weekly", "monthly"):
        raise HTTPException(422, "period must be weekly or monthly")
    data, name = report.build(period, u["team_id"])
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")
