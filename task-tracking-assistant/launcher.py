"""TaskFlow exe entry point. Starts the server for the whole Wi-Fi/LAN, behind a shared password.
  TaskFlow.exe                  start (opens the browser on this PC)
  TaskFlow.exe --port 8000      choose the port
  TaskFlow.exe --set-password   change the login password and exit
Data (tracker.db, .env, taskflow_config.json) lives NEXT TO the exe, so updating = replace the exe."""
import argparse
import os
import socket
import sys
import threading
import webbrowser

os.environ["TASKFLOW_AUTH"] = "1"

from backend import auth  # noqa: E402
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

    if a.set_password:
        import getpass
        pw = getpass.getpass("New password: ")
        if len(pw) < 6 or pw != getpass.getpass("Repeat: "):
            sys.exit("Passwords differ or are shorter than 6 characters. Nothing changed.")
        auth.set_password(pw)
        sys.exit("Password changed. Restart TaskFlow.exe.")

    first = auth.ensure_password()
    import uvicorn
    from backend.main import app
    print("=" * 56)
    print(" TaskFlow is running. Data folder:", DATA_DIR)
    for ip in lan_ips():
        print(f"  Team link:  http://{ip}:{a.port}")
    print("  This PC:    http://localhost:%d" % a.port)
    if first:
        print(f"\n  FIRST RUN password: {first}\n  (also saved in FIRST_RUN_PASSWORD.txt - share it, then delete the file)")
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
