"""Command-line interface for OPTIMUS."""

import argparse
import sys

from .db import CATEGORIES, DEFAULT_DB, PRIORITIES, STATUSES, TicketError, TicketStore


def build_parser():
    parser = argparse.ArgumentParser(prog="optimus", description="OPTIMUS - a simple IT helpdesk ticket tracker.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to the SQLite database file.")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="Create a new ticket")
    add.add_argument("title")
    add.add_argument("-r", "--requester", required=True, help="Who reported the issue")
    add.add_argument("-c", "--category", default="other", choices=CATEGORIES)
    add.add_argument("-p", "--priority", default="medium", choices=PRIORITIES)
    add.add_argument("-d", "--description", default="")

    ls = sub.add_parser("list", help="List tickets (most urgent first)")
    ls.add_argument("--status", choices=STATUSES)
    ls.add_argument("--priority", choices=PRIORITIES)
    ls.add_argument("--category", choices=CATEGORIES)
    ls.add_argument("--assignee")

    show = sub.add_parser("show", help="Show one ticket in detail")
    show.add_argument("id", type=int)

    st = sub.add_parser("status", help="Change a ticket's status")
    st.add_argument("id", type=int)
    st.add_argument("status", choices=STATUSES)

    asg = sub.add_parser("assign", help="Assign a ticket to a technician")
    asg.add_argument("id", type=int)
    asg.add_argument("assignee")

    sub.add_parser("stats", help="Summary report")

    exp = sub.add_parser("export", help="Export all tickets to CSV")
    exp.add_argument("file")
    return parser


def print_table(tickets):
    if not tickets:
        print("No tickets found.")
        return
    print(f"{'ID':<4} {'PRIORITY':<9} {'STATUS':<12} {'CATEGORY':<9} {'ASSIGNEE':<10} TITLE")
    print("-" * 70)
    for t in tickets:
        print(
            f"{t['id']:<4} {t['priority']:<9} {t['status']:<12} {t['category']:<9} "
            f"{(t['assignee'] or '-'):<10} {t['title']}"
        )


def run(args, store):
    if args.command == "add":
        tid = store.add(args.title, args.requester, args.category, args.priority, args.description)
        print(f"Created ticket #{tid}")
    elif args.command == "list":
        print_table(store.list(args.status, args.priority, args.category, args.assignee))
    elif args.command == "show":
        for key, value in store.get(args.id).items():
            print(f"{key:<12}: {value if value not in (None, '') else '-'}")
    elif args.command == "status":
        store.set_status(args.id, args.status)
        print(f"Ticket #{args.id} is now '{args.status}'")
    elif args.command == "assign":
        store.assign(args.id, args.assignee)
        print(f"Ticket #{args.id} assigned to {args.assignee}")
    elif args.command == "stats":
        s = store.stats()
        print(f"Total tickets: {s['total']}")
        print("By status:   ", ", ".join(f"{k}={v}" for k, v in s["by_status"].items()))
        print("By priority: ", ", ".join(f"{k}={v}" for k, v in s["by_priority"].items()))
        avg = s["avg_resolution_hours"]
        print("Avg resolution time:", f"{avg} hours" if avg is not None else "n/a")
    elif args.command == "export":
        n = store.export_csv(args.file)
        print(f"Exported {n} tickets to {args.file}")


def main(argv=None):
    args = build_parser().parse_args(argv)
    store = TicketStore(args.db)
    try:
        run(args, store)
    except TicketError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    finally:
        store.close()
    return 0
