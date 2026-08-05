"""
View or reset each mailbox's "last run" checkpoint — the point in time
after which main.py will look for new emails.

Useful after a long gap of not running the pipeline: instead of it trying to
catch up on everything since the last real run (which could be a large,
stale backlog), you can reset the checkpoint to "now" (or any specific
date/time) so it only picks up emails from that point forward.

This only touches the checkpoint file — it does NOT delete anything from
processed_ids.txt, so anything already recorded stays recorded; this just
controls where the *next* run starts looking.
"""

from datetime import datetime, timezone

from core.routing import MAILBOX_ROUTES
from imap_handler.gmail_client import GmailClient

MAILBOXES = list(MAILBOX_ROUTES.keys())


def show_current(client: GmailClient):
    last_run = client._load_last_run()
    if last_run is None:
        print(f"  {client.mailbox}: no checkpoint set — next run defaults to 'last 2 days'")
    else:
        local = last_run.astimezone()
        print(f"  {client.mailbox}: {last_run.isoformat()}  (local: {local:%Y-%m-%d %H:%M %Z})")


def set_checkpoint(client: GmailClient, dt: datetime):
    client._save_last_run(dt)
    local = dt.astimezone()
    print(f"  {client.mailbox}: checkpoint set to {dt.isoformat()}  (local: {local:%Y-%m-%d %H:%M %Z})")
    print(f"    -> next run will only fetch emails sent after this point")


def prompt_datetime():
    raw = input("  Enter date/time (YYYY-MM-DD HH:MM, your local time): ").strip()
    local_dt = datetime.strptime(raw, "%Y-%m-%d %H:%M")
    return local_dt.astimezone(timezone.utc)


def main():
    clients = {m: GmailClient(m) for m in MAILBOXES}

    print("Current checkpoints:")
    for m in MAILBOXES:
        show_current(clients[m])

    print("\nWhat do you want to do?")
    print("  1 - Start fresh from NOW for all mailboxes (ignore everything before this moment)")
    print("  2 - Set a specific date/time for all mailboxes")
    print("  3 - Handle each mailbox individually")
    print("  4 - Cancel, change nothing")
    choice = input("Enter choice: ").strip()

    if choice == "1":
        now = datetime.now(timezone.utc)
        print()
        for m in MAILBOXES:
            set_checkpoint(clients[m], now)

    elif choice == "2":
        print()
        dt = prompt_datetime()
        print()
        for m in MAILBOXES:
            set_checkpoint(clients[m], dt)

    elif choice == "3":
        for m in MAILBOXES:
            print()
            ans = input(f"{m} — (n)ow / (d)ate / (s)kip? ").strip().lower()
            if ans == "n":
                set_checkpoint(clients[m], datetime.now(timezone.utc))
            elif ans == "d":
                dt = prompt_datetime()
                set_checkpoint(clients[m], dt)
            else:
                print(f"  {m}: skipped, unchanged")

    else:
        print("Cancelled — nothing changed.")


if __name__ == "__main__":
    main()
