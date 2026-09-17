import argparse


def main():
    parser = argparse.ArgumentParser(prog="frontdesk", description="Customer-support agent demo.")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="run the web app")
    serve.add_argument("--port", type=int, default=8001)
    commands.add_parser("reset", help="restore the demo database")
    args = parser.parse_args()

    if args.command == "reset":
        from . import db

        db.reset()
        print("Demo database restored.")
    else:
        import uvicorn

        uvicorn.run("frontdesk.server:app", host="127.0.0.1", port=args.port)
