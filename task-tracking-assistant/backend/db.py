import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "tracker.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('manager','employee')),
  team_id INTEGER REFERENCES teams(id), position TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  employee_id INTEGER NOT NULL REFERENCES users(id),
  title TEXT NOT NULL, title_orig TEXT,
  priority TEXT NOT NULL DEFAULT 'Medium',
  deadline TEXT,
  status TEXT NOT NULL DEFAULT 'To Do',
  progress INTEGER NOT NULL DEFAULT 0,
  blocker TEXT DEFAULT '', blocker_orig TEXT DEFAULT '',
  remarks TEXT DEFAULT '', remarks_orig TEXT DEFAULT '',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS remarks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  author_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  text TEXT NOT NULL, text_orig TEXT DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS translations(
  text TEXT NOT NULL, lang TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(text, lang)
);
"""


def backfill_remarks(c):
    """Turn each single-line remark that has no thread yet into the first entry of its thread."""
    c.execute("""INSERT INTO remarks(task_id,author_id,text,text_orig,created_at)
                 SELECT id,NULL,remarks,COALESCE(NULLIF(remarks_orig,''),remarks),updated_at FROM tasks
                 WHERE TRIM(remarks)<>'' AND id NOT IN (SELECT task_id FROM remarks)""")


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with conn() as c:
        c.executescript(SCHEMA)
        cols = {r["name"] for r in c.execute("PRAGMA table_info(users)")}
        if "team_id" not in cols:  # older demo DB: add columns, put existing people in a team
            c.execute("ALTER TABLE users ADD COLUMN team_id INTEGER")
            c.execute("ALTER TABLE users ADD COLUMN position TEXT DEFAULT ''")
        # one-time: turn each old single-line remark into the first entry of its thread
        backfill_remarks(c)
        orphans = c.execute("SELECT COUNT(*) FROM users WHERE team_id IS NULL").fetchone()[0]
        if orphans:
            tid = c.execute("INSERT INTO teams(name,created_at) VALUES('Demo Team',?)",
                            (datetime.now().isoformat(timespec="seconds"),)).lastrowid
            c.execute("UPDATE users SET team_id=? WHERE team_id IS NULL", (tid,))


def create_team(c, name, leader_name, leader_position, members):
    """Insert a team, its leader (role manager) and members (role employee). Returns (team_id, leader_id, member_ids)."""
    tid = c.execute("INSERT INTO teams(name,created_at) VALUES(?,?)",
                    (name, datetime.now().isoformat(timespec="seconds"))).lastrowid
    lid = c.execute("INSERT INTO users(name,role,team_id,position) VALUES(?,?,?,?)",
                    (leader_name, "manager", tid, leader_position)).lastrowid
    mids = [c.execute("INSERT INTO users(name,role,team_id,position) VALUES(?,?,?,?)",
                      (n, "employee", tid, p)).lastrowid for n, p in members]
    return tid, lid, mids


def seed_sample(c):
    tid, _, (sudesh, priya, rahul) = create_team(
        c, "Sample Team", "Anita", "Engineering Manager",
        [("Sudesh", "Software Engineer"), ("Priya", "Quality Engineer"), ("Rahul", "Production Engineer")])
    today = date.today()
    d = lambda n: (today + timedelta(days=n)).isoformat()
    now = datetime.now().isoformat(timespec="seconds")
    # (emp, title_en, title_orig, priority, deadline, status, progress, blocker_en, blocker_orig, remarks_en, remarks_orig)
    rows = [
        (sudesh, "PFMEA card integration", "PFMEA card integration", "High", d(2), "In Progress", 70,
         "Chakan Excel format is failing", "Chakan Excel format fail ho raha hai", "UI is done, backend working", "UI ho gaya, backend chal raha hai"),
        (sudesh, "Test with sample files", "सॅम्पल फाईल्ससह टेस्टिंग करा", "Medium", d(4), "To Do", 0, "", "", "", ""),
        (sudesh, "Deploy to server", "Server var deploy karne", "Low", d(9), "To Do", 0,
         "Waiting for deployment access", "डिप्लॉयमेंट access ची वाट पाहत आहे", "", ""),
        (priya, "Prepare weekly quality report", "साप्ताहिक क्वालिटी रिपोर्ट तयार करा", "High", d(1), "In Progress", 40, "", "", "Data collected, formatting pending", "डेटा जमा झाला, फॉरमॅटिंग बाकी है"),
        (priya, "Update control plan sheet", "Control plan sheet update karna", "Medium", d(-1), "In Progress", 50, "", "", "", ""),
        (priya, "Supplier audit checklist", "सप्लायर ऑडिट चेकलिस्ट", "Low", d(6), "Done", 100, "", "", "Completed and shared", "पूर्ण करके शेअर किया"),
        (rahul, "Fix traceability barcode scan", "बारकोड स्कॅन मधील बग दुरुस्त करा", "High", d(3), "Blocked", 30,
         "Scanner hardware not available", "स्कॅनर हार्डवेअर उपलब्ध नाही", "", ""),
        (rahul, "Line 2 data entry", "Line 2 ka data entry", "Medium", d(5), "In Progress", 60, "", "", "", ""),
    ]
    c.executemany(
        """INSERT INTO tasks(employee_id,title,title_orig,priority,deadline,status,progress,
           blocker,blocker_orig,remarks,remarks_orig,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [r + (now, now) for r in rows],
    )
    backfill_remarks(c)
    return tid
