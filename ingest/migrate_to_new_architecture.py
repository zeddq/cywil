#!/usr/bin/env python3
"""
Migration script to transition from old ingest pipelines to new service architecture.
This script helps with the transition phase and validates the migration.
"""

import os
import sys
import asyncio
import argparse
import json
from pathlib import Path
from typing import Dict, List, Any, Optional
import logging

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from app.core.config_service import get_config
from app.core.database_manager import DatabaseManager
from app.core.logger_manager import get_logger
from app.services.statute_ingestion_service import StatuteIngestionService
from app.services.supreme_court_ingest_service import SupremeCourtIngestService
from app.services.embedding_service import EmbeddingService
from ingest.refactored_ingest_pipeline import RefactoredIngestOrchestrator


logger = get_logger(__name__)


class MigrationHelper:
    """
    Helper class for migrating from old ingest system to new service architecture.
    """
    
    def __init__(self):
        self.config = get_config()
        self.old_data_paths = {
            "chunks": Path("data/chunks"),
            "pdfs": Path("data/pdfs"),
            "jsonl": Path("data/jsonl"),
            "embeddings": Path("data/embeddings")
        }
        self.orchestrator: Optional[RefactoredIngestOrchestrator] = None
    
    async def initialize(self):
        """Initialize the migration helper"""
        # self.orchestrator = RefactoredIngestOrchestrator()
        #   await self.orchestrator.initialize()
        logger.info("Migration helper initialized")
    
    async def shutdown(self):
        """Shutdown the migration helper"""
        if self.orchestrator:
            await self.orchestrator.shutdown()
        logger.info("Migration helper shutdown")
    
    def check_old_data_structure(self) -> Dict[str, Any]:
        """Check the old data structure and report what's available"""
        logger.info("Checking old data structure...")
        
        structure = {}
        
        for data_type, path in self.old_data_paths.items():
            if path.exists():
                structure[data_type] = {
                    "exists": True,
                    "path": str(path),
                    "files": []
                }
                
                # List files in directory
                for file_path in path.iterdir():
                    if file_path.is_file():
                        structure[data_type]["files"].append({
                            "name": file_path.name,
                            "size": file_path.stat().st_size,
                            "modified": file_path.stat().st_mtime
                        })
            else:
                structure[data_type] = {
                    "exists": False,
                    "path": str(path)
                }
        
        return structure
    
    def check_new_data_structure(self) -> Dict[str, Any]:
        """Check the new data structure"""
        logger.info("Checking new data structure...")
        
        structure = {}
        
        # Check new storage paths
        storage_paths = {
            "base_dir": self.config.storage.base_dir,
            "chunks_dir": self.config.storage.get_path(self.config.storage.chunks_dir),
            "pdfs_dir": self.config.storage.get_path(self.config.storage.pdfs_dir),
            "jsonl_dir": self.config.storage.get_path(self.config.storage.jsonl_dir),
            "embeddings_dir": self.config.storage.get_path(self.config.storage.embeddings_dir)
        }
        
        for path_name, path in storage_paths.items():
            structure[path_name] = {
                "exists": path.exists(),
                "path": str(path),
                "files": []
            }
            
            if path.exists():
                try:
                    for file_path in path.iterdir():
                        if file_path.is_file():
                            structure[path_name]["files"].append({
                                "name": file_path.name,
                                "size": file_path.stat().st_size,
                                "modified": file_path.stat().st_mtime
                            })
                except Exception as e:
                    structure[path_name]["error"] = str(e)
        
        return structure
    
    async def migrate_data_structure(self, copy_files: bool = True) -> Dict[str, Any]:
        """Migrate data from old structure to new structure"""
        logger.info("Starting data structure migration...")
        
        migration_results = {
            "operations": [],
            "errors": []
        }
        
        # Create new directories
        for dir_name in [self.config.storage.chunks_dir, self.config.storage.pdfs_dir, 
                        self.config.storage.jsonl_dir, self.config.storage.embeddings_dir]:
            new_path = self.config.storage.get_path(dir_name)
            if not new_path.exists():
                new_path.mkdir(parents=True, exist_ok=True)
                migration_results["operations"].append(f"Created directory: {new_path}")
        
        # Copy files if requested
        if copy_files:
            copy_mappings = [
                (self.old_data_paths["chunks"], self.config.storage.get_path(self.config.storage.chunks_dir)),
                (self.old_data_paths["pdfs"], self.config.storage.get_path(self.config.storage.pdfs_dir)),
                (self.old_data_paths["jsonl"], self.config.storage.get_path(self.config.storage.jsonl_dir)),
                (self.old_data_paths["embeddings"], self.config.storage.get_path(self.config.storage.embeddings_dir))
            ]
            
            for old_path, new_path in copy_mappings:
                if old_path.exists():
                    if old_path == new_path:
                        migration_results["operations"].append(f"Skipping copy from {old_path} to {new_path} because they are the same")
                        continue
                    try:
                        await self._copy_files_async(old_path, new_path)
                        migration_results["operations"].append(f"Copied files from {old_path} to {new_path}")
                    except Exception as e:
                        error_msg = f"Error copying from {old_path} to {new_path}: {str(e)}"
                        migration_results["errors"].append(error_msg)
                        logger.error(error_msg)
        
        return migration_results
    
    async def _copy_files_async(self, source_dir: Path, dest_dir: Path):
        """Copy files from source to destination directory"""
        import shutil
        
        loop = asyncio.get_event_loop()
        
        for file_path in source_dir.iterdir():
            if file_path.is_file():
                dest_file = dest_dir / file_path.name
                await loop.run_in_executor(None, shutil.copy2, file_path, dest_file)
    
    async def validate_migration(self) -> Dict[str, Any]:
        """Validate that the migration was successful"""
        logger.info("Validating migration...")
        
        validation_results = {
            "service_health": {},
            "data_consistency": {},
            "functionality_tests": {}
        }
        
        # Check service health
        if self.orchestrator:
            health = await self.orchestrator.health_check()
            validation_results["service_health"] = health
        
        # Check data consistency
        old_structure = self.check_old_data_structure()
        new_structure = self.check_new_data_structure()
        
        validation_results["data_consistency"] = {
            "old_structure": old_structure,
            "new_structure": new_structure,
            "migration_complete": self._compare_structures(old_structure, new_structure)
        }
        
        # Run functionality tests
        if self.orchestrator:
            try:
                ingestion_validation = await self.orchestrator.validate_ingestion()
                validation_results["functionality_tests"] = ingestion_validation
            except Exception as e:
                validation_results["functionality_tests"] = {
                    "error": str(e),
                    "status": "failed"
                }
        
        return validation_results
    
    def _compare_structures(self, old_structure: Dict[str, Any], new_structure: Dict[str, Any]) -> Dict[str, Any]:
        """Compare old and new data structures"""
        comparison = {
            "directories_migrated": 0,
            "files_migrated": 0,
            "issues": []
        }
        
        # Check each directory
        for old_key, old_data in old_structure.items():
            if old_data["exists"] and old_data["files"]:
                # Find corresponding new directory
                new_key = None
                if old_key == "chunks":
                    new_key = "chunks_dir"
                elif old_key == "pdfs":
                    new_key = "pdfs_dir"
                elif old_key == "jsonl":
                    new_key = "jsonl_dir"
                elif old_key == "embeddings":
                    new_key = "embeddings_dir"
                
                if new_key and new_key in new_structure:
                    new_data = new_structure[new_key]
                    if new_data["exists"]:
                        comparison["directories_migrated"] += 1
                        
                        # Check files
                        old_files = {f["name"] for f in old_data["files"]}
                        new_files = {f["name"] for f in new_data["files"]}
                        
                        migrated_files = old_files.intersection(new_files)
                        missing_files = old_files - new_files
                        
                        comparison["files_migrated"] += len(migrated_files)
                        
                        if missing_files:
                            comparison["issues"].append(f"Missing files in {new_key}: {missing_files}")
                    else:
                        comparison["issues"].append(f"New directory {new_key} does not exist")
        
        return comparison
    
    async def run_comparison_test(self) -> Dict[str, Any]:
        """Run a comparison test between old and new implementations"""
        logger.info("Running comparison test...")
        
        # This would compare results from old vs new implementations
        # For now, just return the validation results
        return await self.validate_migration()
    
    def generate_migration_report(self, validation_results: Dict[str, Any]) -> str:
        """Generate a migration report"""
        report_lines = [
            "# Migration Report",
            f"Generated at: {asyncio.get_event_loop().time()}",
            "",
            "## Service Health",
        ]
        
        if "service_health" in validation_results:
            for service, health in validation_results["service_health"].items():
                status = health.get("status", "unknown")
                message = health.get("message", "No message")
                report_lines.append(f"- {service}: {status} - {message}")
        
        report_lines.extend([
            "",
            "## Data Consistency",
        ])
        
        if "data_consistency" in validation_results:
            consistency = validation_results["data_consistency"]
            migration_complete = consistency.get("migration_complete", {})
            
            report_lines.append(f"- Directories migrated: {migration_complete.get('directories_migrated', 0)}")
            report_lines.append(f"- Files migrated: {migration_complete.get('files_migrated', 0)}")
            
            issues = migration_complete.get("issues", [])
            if issues:
                report_lines.append("- Issues:")
                for issue in issues:
                    report_lines.append(f"  - {issue}")
        
        report_lines.extend([
            "",
            "## Functionality Tests",
        ])
        
        if "functionality_tests" in validation_results:
            tests = validation_results["functionality_tests"]
            if "validation_summary" in tests:
                summary = tests["validation_summary"]
                report_lines.append(f"- Statutes available: {summary.get('statutes_available', False)}")
                report_lines.append(f"- Court rulings available: {summary.get('court_rulings_available', False)}")
                report_lines.append(f"- Embeddings available: {summary.get('embeddings_available', False)}")
        
        return "\n".join(report_lines)


async def main():
    """Main entry point for the migration script"""
    parser = argparse.ArgumentParser(
        description="Migrate from old ingest system to new service architecture"
    )
    parser.add_argument(
        "--check-old",
        action="store_true",
        help="Check old data structure"
    )
    parser.add_argument(
        "--check-new",
        action="store_true",
        help="Check new data structure"
    )
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Run migration process"
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate migration"
    )
    parser.add_argument(
        "--copy-files",
        action="store_true",
        help="Copy files during migration"
    )
    parser.add_argument(
        "--report",
        help="Generate migration report to file"
    )
    
    args = parser.parse_args()
    
    helper = MigrationHelper()
    
    try:
        await helper.initialize()
        
        if args.check_old:
            structure = helper.check_old_data_structure()
            print("\nOld Data Structure:")
            print(json.dumps(structure, indent=2, default=str))
        
        if args.check_new:
            structure = helper.check_new_data_structure()
            print("\nNew Data Structure:")
            print(json.dumps(structure, indent=2, default=str))
        
        if args.migrate:
            results = await helper.migrate_data_structure(copy_files=args.copy_files)
            print("\nMigration Results:")
            print(json.dumps(results, indent=2, default=str))
        
        if args.validate:
            validation = await helper.validate_migration()
            print("\nValidation Results:")
            print(json.dumps(validation, indent=2, default=str))
            
            if args.report:
                report = helper.generate_migration_report(validation)
                with open(args.report, "w") as f:
                    f.write(report)
                print(f"\nMigration report written to: {args.report}")
        
        if not any([args.check_old, args.check_new, args.migrate, args.validate]):
            print("No action specified. Use --help for options.")
    
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        return 1
    
    finally:
        await helper.shutdown()
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
