"""TaskFlow exe entry point. Starts the server for the whole Wi-Fi/LAN, behind a shared password.
  TaskFlow.exe                  start (opens the browser on this PC)
  TaskFlow.exe --port 8000      choose the port
  TaskFlow.exe --set-password   change the web login password and exit
Always asks the start password first (START_PASSWORD in backend/startgate.py).
Data (tracker.db, .env, taskflow_config.json) lives NEXT TO the exe, so updating = replace the exe."""
import argparse
import os
import socket
import sys
import threading
import webbrowser

os.environ["TASKFLOW_AUTH"] = "1"

from backend import auth, startgate  # noqa: E402
from backend.paths import DATA_DIR  # noqa: E402


def lan_ips():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(i for i in ips if not i.startswith("127."))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--set-password", action="store_true")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()

    startgate.ask()  # 1) password to start the exe (set in backend/startgate.py)

    def choose_web_password():
        import getpass
        while True:
            pw = getpass.getpass("New web login password for TaskFlow users (min 6 characters): ")
            if len(pw) >= 6 and pw == getpass.getpass("Repeat it: "):
                return pw
            print("Too short or not matching, try again.")

    if a.set_password:  # change the web login password later
        auth.set_password(choose_web_password())
        input("Web password changed. Press Enter to close, then start TaskFlow.exe again.")
        sys.exit(0)

    first = False
    if not auth.has_password():  # 2) first run on this server: you choose the web password
        pw = os.environ.get("TASKFLOW_PASSWORD") or choose_web_password()
        auth.set_password(pw)
        first = True
    import uvicorn
    from backend.main import app
    print("=" * 56)
    print(" TaskFlow is running. Data folder:", DATA_DIR)
    for ip in lan_ips():
        print(f"  Team link:  http://{ip}:{a.port}")
    print("  This PC:    http://localhost:%d" % a.port)
    from backend import ai
    print("  AI: " + (ai.describe() if ai.enabled() else "OFF (no .env next to the exe) - TaskFlow still works without AI"))
    if first:
        print("  Web login password saved. Share it with your team.")
    print(" If others cannot connect, allow the port in Windows Firewall.")
    print("=" * 56)
    if not a.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{a.port}")).start()
    uvicorn.run(app, host="0.0.0.0", port=a.port, log_level="warning")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        input("\nTaskFlow stopped because of the error above. Press Enter to close.")
