#!/usr/bin/env python3
"""
Complete ingestion pipeline for Polish civil law statutes
"""

import os
import sys
from pathlib import Path
import logging
import argparse
from datetime import datetime
import json
from typing import Dict, List, Optional

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from ingest.pdf2chunks import process_statute_pdf
from ingest.embed import process_and_embed_statutes, create_hybrid_search_index
from app.core.config_service import get_config
from app.models import StatuteChunk
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

# Get configuration
config = get_config()

class StatuteIngestionPipeline:
    """Orchestrates the complete statute ingestion process"""
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize pipeline with configuration
        
        Args:
            config: Optional configuration override
        """
        if config is None:

            raise ValueError("Config is required")


        self.config = {
            "qdrant_host": config.qdrant.host,
            "qdrant_port": config.qdrant.port,
            "qdrant_api_key": config.qdrant.api_key.get_secret_value() if config.qdrant.api_key else None,
            "collection_name": config.qdrant.collection_statutes,
            "chunks_dir": str(config.storage.get_path(config.storage.chunks_dir)),
            "pdfs_dir": str(config.storage.get_path(config.storage.pdfs_dir))
        }
        
        # Create directories
        Path(self.config["chunks_dir"]).mkdir(parents=True, exist_ok=True)
        Path(self.config["pdfs_dir"]).mkdir(parents=True, exist_ok=True)
        
        # Database setup

        
        if config is None:

        
            raise ValueError("Config is required for database setup")
        self.engine = create_engine(config.postgres.sync_url)
        self.Session = sessionmaker(bind=self.engine)
    
    def download_statutes(self) -> Dict[str, str]:
        """
        Download latest versions of KC and KPC
        
        Returns:
            Dictionary mapping code type to file path
        """
        # URLs for official statute sources
        sources = {
            "KC": {
                "url": "https://isap.sejm.gov.pl/isap.nsf/download.xsp/WDU19640160093/U/D19640093Lj.pdf",
                "filename": "kodeks_cywilny.pdf"
            },
            "KPC": {
                "url": "https://isap.sejm.gov.pl/isap.nsf/download.xsp/WDU19640430296/U/D19640296Lj.pdf",
                "filename": "kodeks_postepowania_cywilnego.pdf"
            }
        }
        
        downloaded = {}
        
        for code, info in sources.items():
            output_path = Path(self.config["pdfs_dir"]) / "statutes" / info["filename"]
            
            if output_path.exists():
                logger.info(f"{code} PDF already exists at {output_path}")
                downloaded[code] = str(output_path)
            else:
                logger.info(f"Downloading {code} from {info['url']}")
                # In production, implement actual download
                # For now, assume PDFs are manually placed
                logger.warning(f"Please manually download {code} to {output_path}")
                
                if output_path.exists():
                    downloaded[code] = str(output_path)
        
        return downloaded
    
    def process_pdf(self, pdf_path: str, code_type: str) -> Dict:
        """
        Process a single PDF file
        
        Args:
            pdf_path: Path to PDF file
            code_type: Type of code (KC or KPC)
            
        Returns:
            Processing statistics
        """
        logger.info(f"Processing {code_type} from {pdf_path}")
        
        # Parse and chunk
        chunks, stats = process_statute_pdf(
            pdf_path,
            code_type,
            self.config["chunks_dir"]
        )
        
        # Save to database
        self._save_chunks_to_db(chunks, code_type)
        
        return stats
    
    def _save_chunks_to_db(self, chunks: List[Dict], code_type: str):
        """Save chunks to PostgreSQL database"""
        session = self.Session()
        
        try:
            for chunk in chunks:
                metadata = chunk.get("metadata", {})
                
                db_chunk = StatuteChunk(
                    code=code_type,
                    article=metadata.get("article", ""),
                    paragraph=metadata.get("paragraph"),
                    text=chunk["text"],
                    embedding_id=chunk["chunk_id"],
                    metadata=metadata
                )
                
                session.add(db_chunk)
            
            session.commit()
            logger.info(f"Saved {len(chunks)} chunks to database")
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error saving chunks: {e}")
            raise
        finally:
            session.close()
    
    def embed_chunks(self, code_type: str) -> Dict:
        """
        Generate and store embeddings for chunks
        
        Args:
            code_type: Type of code (KC or KPC)
            
        Returns:
            Embedding statistics
        """
        chunks_file = Path(self.config["chunks_dir"]) / f"{code_type}_chunks.json"
        
        if not chunks_file.exists():
            raise FileNotFoundError(f"Chunks file not found: {chunks_file}")
        
        # Process embeddings
        stats = process_and_embed_statutes(
            str(chunks_file),
            collection_name=self.config["collection_name"],
            qdrant_host=self.config["qdrant_host"],
            qdrant_port=self.config["qdrant_port"]
        )
        
        return stats
    
    def run_full_pipeline(self) -> Dict:
        """
        Run the complete ingestion pipeline
        
        Returns:
            Complete pipeline statistics
        """
        start_time = datetime.now()
        results = {
            "start_time": start_time.isoformat(),
            "statutes": {}
        }
        
        # Download statutes
        logger.info("Checking for statute PDFs...")
        pdf_paths = self.download_statutes()
        
        if not pdf_paths:
            logger.error("No PDFs found. Please download statute PDFs first.")
            return results
        
        # Process each statute
        for code_type, pdf_path in pdf_paths.items():
            logger.info(f"\n{'='*50}")
            logger.info(f"Processing {code_type}")
            logger.info(f"{'='*50}")
            
            try:
                # Parse and chunk
                chunk_stats = self.process_pdf(pdf_path, code_type)
                
                # Generate embeddings
                embed_stats = self.embed_chunks(code_type)
                
                # Store results
                results["statutes"][code_type] = {
                    "chunk_stats": chunk_stats,
                    "embed_stats": embed_stats,
                    "status": "success"
                }
                
            except Exception as e:
                logger.error(f"Error processing {code_type}: {e}")
                results["statutes"][code_type] = {
                    "status": "error",
                    "error": str(e)
                }
        
        # Create search indexes
        logger.info("\nCreating hybrid search indexes...")
        create_hybrid_search_index(
            collection_name=self.config["collection_name"],
            qdrant_host=self.config["qdrant_host"],
            qdrant_port=self.config["qdrant_port"],
            qdrant_api_key=self.config["qdrant_api_key"]
        )
        
        # Calculate total time
        end_time = datetime.now()
        results["end_time"] = end_time.isoformat()
        results["total_duration"] = str(end_time - start_time)
        
        # Save results
        results_file = Path(self.config["chunks_dir"]) / "ingestion_results.json"
        with open(results_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        logger.info(f"\n{'='*50}")
        logger.info("Pipeline completed!")
        logger.info(f"Total duration: {results['total_duration']}")
        logger.info(f"Results saved to: {results_file}")
        
        return results
    
    def validate_ingestion(self) -> Dict:
        """
        Validate the ingestion results
        
        Returns:
            Validation results
        """
        # from app.tools import search_statute  # TODO: Fix import path or create tools module
        import asyncio
        
        validation = {
            "timestamp": datetime.now().isoformat(),
            "tests": []
        }
        
        # Test queries
        test_queries = [
            {
                "query": "umowa kupna sprzedaży",
                "code": "KC",
                "expected_articles": ["535", "536", "537"]
            },
            {
                "query": "pozew w postępowaniu upominawczym",
                "code": "KPC",
                "expected_articles": ["499", "505"]
            },
            {
                "query": "odpowiedzialność deliktowa",
                "code": "KC",
                "expected_articles": ["415", "416", "417"]
            }
        ]
        
        # Run test queries
        for test in test_queries:
            try:
                # TODO: Uncomment when search_statute is available
                # results = asyncio.run(
                #     search_statute(
                #         test["query"],
                #         top_k=5,
                #         code=test["code"]
                #     )
                # )
                results = []  # Placeholder
                print(f"Results: {results}")
                
                found_articles = [r["article"] for r in results]
                expected_found = any(
                    art in found_articles 
                    for art in test["expected_articles"]
                )
                
                validation["tests"].append({
                    "query": test["query"],
                    "code": test["code"],
                    "status": "pass" if expected_found else "fail",
                    "found_articles": found_articles[:3],
                    "expected_any_of": test["expected_articles"]
                })
                
            except Exception as e:
                validation["tests"].append({
                    "query": test["query"],
                    "code": test["code"],
                    "status": "error",
                    "error": str(e)
                })
        
        # Summary
        passed = sum(1 for t in validation["tests"] if t["status"] == "pass")
        total = len(validation["tests"])
        validation["summary"] = {
            "total_tests": total,
            "passed": passed,
            "failed": total - passed,
            "success_rate": f"{(passed/total)*100:.1f}%" if total > 0 else "0%"
        }
        
        return validation

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Ingest Polish civil law statutes"
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only run validation tests"
    )
    parser.add_argument(
        "--qdrant-host",
        default="localhost",
        help="Qdrant server host"
    )
    parser.add_argument(
        "--qdrant-port",
        type=int,
        default=6333,
        help="Qdrant server port"
    )
    
    args = parser.parse_args()
    
    # Configure pipeline
    config_dict = {
        "qdrant_host": config.qdrant.host,
        "qdrant_port": config.qdrant.port,
        "qdrant_api_key": config.qdrant.api_key.get_secret_value() if config.qdrant.api_key else None,
        "collection_name": config.qdrant.collection_statutes,
        "chunks_dir": str(config.storage.get_path(config.storage.chunks_dir)),
        "pdfs_dir": "data/pdfs"
    }
    
    pipeline = StatuteIngestionPipeline(config_dict)
    
    if args.validate_only:
        # Run validation only
        logger.info("Running validation tests...")
        validation = pipeline.validate_ingestion()
        
        print("\nValidation Results:")
        print(f"Success Rate: {validation['summary']['success_rate']}")
        print(f"Passed: {validation['summary']['passed']}/{validation['summary']['total_tests']}")
        
        for test in validation["tests"]:
            status_icon = "✓" if test["status"] == "pass" else "✗"
            print(f"\n{status_icon} Query: '{test['query']}' ({test['code']})")
            if test["status"] == "pass":
                print(f"  Found articles: {', '.join(test['found_articles'])}")
            elif test["status"] == "error":
                print(f"  Error: {test['error']}")
    else:
        # Run full pipeline
        results = pipeline.run_full_pipeline()
        
        # Print summary
        print("\nIngestion Summary:")
        for code, stats in results["statutes"].items():
            print(f"\n{code}:")
            if stats["status"] == "success":
                print(f"  Chunks: {stats['chunk_stats']['total_chunks']}")
                print(f"  Embeddings: {stats['embed_stats']['embeddings_generated']}")
            else:
                print(f"  Status: {stats['status']}")
                print(f"  Error: {stats.get('error', 'Unknown')}")

if __name__ == "__main__":
    main()
