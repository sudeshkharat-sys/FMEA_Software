"""Password asked every time TaskFlow.exe is started. To change it: edit START_PASSWORD, rebuild the exe.
(It is compiled into the exe, so it only keeps casual users out; real protection is the web login password.)"""
import getpass
import hmac
import sys

START_PASSWORD = "mahindra@123"
MAX_TRIES = 3


def ask():
    """Prompt until correct; exit the program after MAX_TRIES wrong attempts."""
    for left in range(MAX_TRIES, 0, -1):
        try:
            got = getpass.getpass("Start password: ")
        except (EOFError, KeyboardInterrupt):
            sys.exit(1)
        if hmac.compare_digest(got.encode(), START_PASSWORD.encode()):
            return
        print(f"Wrong password. {left - 1} tries left.")
    input("Too many wrong attempts. Press Enter to close.")
    sys.exit(1)
