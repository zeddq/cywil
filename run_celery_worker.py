#!/usr/bin/env python3
"""
Script to run Celery worker for local development with configurable queues
"""
import os
import sys
import subprocess
import argparse

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    """Run Celery worker with appropriate settings"""

    parser = argparse.ArgumentParser(
        description="Run Celery worker for AI Paralegal POC"
    )
    parser.add_argument(
        "--queues",
        default="default,high_priority",
        help="Comma-separated list of queues to process (default: default,high_priority)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=2,
        help="Number of concurrent worker processes (default: 2)",
    )
    parser.add_argument(
        "--loglevel",
        default="info",
        choices=["debug", "info", "warning", "error", "critical"],
        help="Logging level (default: info)",
    )
    parser.add_argument("--hostname", help="Set custom hostname for the worker")
    parser.add_argument(
        "--max-tasks-per-child",
        type=int,
        help="Maximum number of tasks a worker can execute before being recycled",
    )
    parser.add_argument(
        "--beat", action="store_true", help="Also run the Celery beat scheduler"
    )
    parser.add_argument(
        "--flower", action="store_true", help="Also run Flower monitoring on port 5555"
    )

    args = parser.parse_args()

    # Set environment variables if not already set
    if not os.getenv("REDIS_URL"):
        os.environ["REDIS_URL"] = "redis://localhost:6379/0"

    # Build the command
    cmd = [
        "celery",
        "-A",
        "app.worker.celery_app",
        "worker",
        f"--loglevel={args.loglevel}",
        f"--concurrency={args.concurrency}",
        f"--queues={args.queues}",
    ]

    if args.hostname:
        cmd.append(f"--hostname={args.hostname}")
    else:
        cmd.append(f"--hostname={args.queues.split(',')[0]}@%h")

    if args.max_tasks_per_child:
        cmd.append(f"--max-tasks-per-child={args.max_tasks_per_child}")

    print("=" * 60)
    print("AI Paralegal POC - Celery Worker")
    print("=" * 60)
    print(f"Redis URL: {os.getenv('REDIS_URL')}")
    print(f"Queues: {args.queues}")
    print(f"Concurrency: {args.concurrency}")
    print(f"Log Level: {args.loglevel}")
    print("=" * 60)
    print(f"Starting Celery worker...")
    print(f"Command: {' '.join(cmd)}")
    print("=" * 60)

    processes = []

    try:
        # Start the worker
        worker_process = subprocess.Popen(cmd)
        processes.append(worker_process)

        # Optionally start beat scheduler
        if args.beat:
            print("Starting Celery beat scheduler...")
            beat_cmd = [
                "celery",
                "-A",
                "app.worker.celery_app",
                "beat",
                f"--loglevel={args.loglevel}",
            ]
            beat_process = subprocess.Popen(beat_cmd)
            processes.append(beat_process)

        # Optionally start Flower
        if args.flower:
            print("Starting Flower monitoring on http://localhost:5555")
            flower_cmd = [
                "celery",
                "-A",
                "app.worker.celery_app",
                "flower",
                "--port=5555",
                "--basic_auth=admin:admin",
            ]
            flower_process = subprocess.Popen(flower_cmd)
            processes.append(flower_process)

        # Wait for all processes
        for process in processes:
            process.wait()

    except KeyboardInterrupt:
        print("\nShutting down Celery components...")
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait()
        sys.exit(0)
    except Exception as e:
        print(f"Error running Celery: {e}")
        for process in processes:
            process.terminate()
        sys.exit(1)


if __name__ == "__main__":
    main()
