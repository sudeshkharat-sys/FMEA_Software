import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "tracker.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('manager','employee'))
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
CREATE TABLE IF NOT EXISTS translations(
  text TEXT NOT NULL, lang TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(text, lang)
);
"""


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with conn() as c:
        c.executescript(SCHEMA)
        if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            seed(c)


def seed(c):
    c.executemany(
        "INSERT INTO users(id,name,role) VALUES(?,?,?)",
        [(1, "Manager", "manager"), (2, "Sudesh", "employee"),
         (3, "Priya", "employee"), (4, "Rahul", "employee")],
    )
    today = date.today()
    d = lambda n: (today + timedelta(days=n)).isoformat()
    now = datetime.now().isoformat(timespec="seconds")
    # (emp, title_en, title_orig, priority, deadline, status, progress, blocker_en, blocker_orig, remarks_en, remarks_orig)
    rows = [
        (2, "PFMEA card integration", "PFMEA card integration", "High", d(2), "In Progress", 70,
         "Chakan Excel format is failing", "Chakan Excel format fail ho raha hai", "UI is done, backend working", "UI ho gaya, backend chal raha hai"),
        (2, "Test with sample files", "सॅम्पल फाईल्ससह टेस्टिंग करा", "Medium", d(4), "To Do", 0, "", "", "", ""),
        (2, "Deploy to server", "Server var deploy karne", "Low", d(9), "To Do", 0,
         "Waiting for deployment access", "डिप्लॉयमेंट access ची वाट पाहत आहे", "", ""),
        (3, "Prepare weekly quality report", "साप्ताहिक क्वालिटी रिपोर्ट तयार करा", "High", d(1), "In Progress", 40, "", "", "Data collected, formatting pending", "डेटा जमा झाला, फॉरमॅटिंग बाकी है"),
        (3, "Update control plan sheet", "Control plan sheet update karna", "Medium", d(-1), "In Progress", 50, "", "", "", ""),
        (3, "Supplier audit checklist", "सप्लायर ऑडिट चेकलिस्ट", "Low", d(6), "Done", 100, "", "", "Completed and shared", "पूर्ण करके शेअर किया"),
        (4, "Fix traceability barcode scan", "बारकोड स्कॅन मधील बग दुरुस्त करा", "High", d(3), "Blocked", 30,
         "Scanner hardware not available", "स्कॅनर हार्डवेअर उपलब्ध नाही", "", ""),
        (4, "Line 2 data entry", "Line 2 ka data entry", "Medium", d(5), "In Progress", 60, "", "", "", ""),
    ]
    c.executemany(
        """INSERT INTO tasks(employee_id,title,title_orig,priority,deadline,status,progress,
           blocker,blocker_orig,remarks,remarks_orig,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [r + (now, now) for r in rows],
    )
