#!/usr/bin/env python3
"""
Script to run Alembic migrations for the AI Paralegal POC.
This handles database schema migrations and updates.
"""

import subprocess
import sys
import os
from pathlib import Path

# Change to the project root directory
project_root = Path(__file__).parent
os.chdir(project_root)


def run_command(cmd):
    """Run a shell command and print output."""
    print(f"\n➤ Running: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(f"Error: {result.stderr}", file=sys.stderr)
    
    return result.returncode


def main():
    """Main function to run migrations."""
    print("AI Paralegal POC - Database Migration Runner")
    print("=" * 50)
    
    # First, check current migration status
    print("\n1. Checking current migration status...")
    returncode = run_command("alembic current")
    
    if returncode != 0:
        print("\n⚠️  Database might not be initialized. Creating initial tables...")
        # Run the init_database.py script first
        run_command("python init_database.py")
        
        # Check again
        run_command("alembic current")
    
    # Generate a new migration if there are model changes
    print("\n2. Checking for model changes...")
    returncode = run_command('alembic revision --autogenerate -m "Auto-generated migration"')
    
    if returncode == 0:
        print("✅ New migration created!")
    else:
        print("ℹ️  No new changes detected or migration creation failed.")
    
    # Apply all pending migrations
    print("\n3. Applying pending migrations...")
    returncode = run_command("alembic upgrade head")
    
    if returncode == 0:
        print("\n✅ All migrations applied successfully!")
    else:
        print("\n❌ Migration failed! Check the error messages above.")
        sys.exit(1)
    
    # Show final migration status
    print("\n4. Final migration status:")
    run_command("alembic current")
    
    print("\n✅ Migration process complete!")


if __name__ == "__main__":
    main()