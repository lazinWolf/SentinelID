"""Local dashboard and resumable original-event replay."""

import argparse
import json

from .ingestion import ROOT


def main():
    parser = argparse.ArgumentParser(description="SentinelID original-event behavioral pipeline")
    commands = parser.add_subparsers(dest="command", required=True)
    acquisition = commands.add_parser(
        "setup", help="Download and verify the deployed data and model"
    )
    acquisition.add_argument("--accept-data-license", action="store_true")
    acquisition.add_argument("--model-only", action="store_true")
    acquisition.add_argument(
        "--sources", nargs="+", choices=["device", "logon", "email", "file", "http"]
    )
    experiment = commands.add_parser(
        "experiment", help="Run isolated corrected optional-module experiments"
    )
    experiment.add_argument("--config", required=True)
    experiment.add_argument("--resume", action="store_true")
    experiment.add_argument(
        "--stop-after-days",
        type=int,
        help="Checkpoint each configuration after this many additional days",
    )
    commands.add_parser("status", help="Show persisted progress and the selected model")
    verify = commands.add_parser(
        "verify", help="Verify the deployed model and required source files"
    )
    verify.add_argument(
        "--sources", action="store_true", help="Also hash all original CSV and LDAP files"
    )
    web = commands.add_parser("serve", help="Serve the local investigation dashboard")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8767)
    replay = commands.add_parser("replay", help="Process originals into separate application state")
    replay.add_argument("--new", action="store_true", help="Preserve prior runs and start another")
    replay.add_argument("--events", type=int, help="Limit additional events for this invocation")
    replay.add_argument("--checkpoint-on-pending", action="store_true")
    args = parser.parse_args()

    try:
        if args.command == "setup":
            from .setup import setup

            setup(
                sources=args.sources,
                model_only=args.model_only,
                accept_data_license=args.accept_data_license,
            )
        elif args.command == "experiment":
            from .experiments import run

            if args.stop_after_days is not None and args.stop_after_days < 1:
                raise ValueError("--stop-after-days must be positive")
            run(args.config, args.resume, args.stop_after_days)
        elif args.command == "status":
            from .store import WorkloadStore

            result = WorkloadStore().summary()
            models = json.loads((ROOT / "config.json").read_text())["deployment"]
            result["selected_model"] = models["scorer"]
            result["application_database"] = str(WorkloadStore().path)
            print(json.dumps(result, indent=2))
        elif args.command == "verify":
            from .pipeline import verify_model

            result = verify_model(originals=args.sources)
            print(
                json.dumps(
                    {
                        "selected": result["deployment"]["scorer"],
                        "model_checksum": "verified",
                        "original_sources": "checksums verified" if args.sources else "present",
                    },
                    indent=2,
                )
            )
        elif args.command == "serve":
            from .server import serve

            serve(args.host, args.port)
        else:
            from .pipeline import WorkloadReplay

            if args.events is not None and args.events < 1:
                raise ValueError("--events must be positive")
            worker = WorkloadReplay(new=args.new)
            try:
                remaining = args.events
                while worker.status != "completed" and (remaining is None or remaining > 0):
                    before = worker.cursor
                    result = worker.step(
                        100_000 if remaining is None else min(100_000, remaining),
                        args.checkpoint_on_pending,
                    )
                    print(json.dumps(result["run"]), flush=True)
                    if remaining is not None:
                        remaining -= worker.cursor - before
                    if worker.checkpoint_requested:
                        checkpoint = {
                            "run_id": worker.run_id,
                            "cursor": worker.cursor,
                            "unfinished_day": str(worker.stream.day),
                            "unfinished_records": sum(
                                d.events for d in worker.stream.buckets.values()
                            ),
                            "pending_identities": len(worker.queue.pending),
                            "pending_decision": worker.pending_decision,
                        }
                        path = worker.store.path.parent / "checkpoint.json"
                        path.write_text(json.dumps(checkpoint, indent=2))
                        print(json.dumps(checkpoint, indent=2))
                        break
            finally:
                worker.close()
    except (ValueError, OSError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
