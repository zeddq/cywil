#!/usr/bin/env python3
"""
Script to fix the document hierarchy in the existing chunks.
Updates the chunking logic to properly reflect Polish legal document structure:
1. Część (Part) - highest level
2. Dział (Division)
3. Rozdział (Chapter)
4. Artykuł (Article) - lowest level
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pdf2chunks_fixed import PolishStatuteParser, StatuteChunker
from pdf2chunks import PolishStatuteParser as OldParser
import logging
from pathlib import Path
import json

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def compare_parsers(pdf_path: str):
    """Compare output of old and new parsers to show the difference"""
    
    logger.info(f"Comparing parsers on {pdf_path}")
    
    # Parse with old parser
    old_parser = OldParser("KC")
    old_chunks = old_parser.parse_pdf(pdf_path)
    
    # Parse with new parser
    new_parser = PolishStatuteParser("KC")
    new_chunks = new_parser.parse_pdf(pdf_path)
    
    logger.info(f"Old parser found {len(old_chunks)} chunks")
    logger.info(f"New parser found {len(new_chunks)} chunks")
    
    # Show hierarchy differences
    print("\n=== HIERARCHY COMPARISON ===")
    print("\nOld Parser Structure:")
    old_sections = set()
    for chunk in old_chunks[:10]:  # Show first 10
        if chunk.section:
            old_sections.add(chunk.section)
        if 'chapter' in chunk.metadata:
            print(f"  Article {chunk.article}: Chapter={chunk.metadata.get('chapter')}, Book={chunk.metadata.get('book')}")
    
    print("\nNew Parser Structure:")
    new_sections = set()
    for chunk in new_chunks[:10]:  # Show first 10
        if chunk.section:
            new_sections.add(chunk.section)
        hierarchy = chunk.metadata.get('hierarchy', {})
        print(f"  Article {chunk.article}: {chunk.section or 'No section'}")
        print(f"    Part: {hierarchy.get('part')} {hierarchy.get('part_name') or ''}")
        print(f"    Division: {hierarchy.get('division')} {hierarchy.get('division_name') or ''}")
        print(f"    Chapter: {hierarchy.get('chapter')} {hierarchy.get('chapter_name') or ''}")
    
    print("\nUnique sections found:")
    print("Old:", sorted(old_sections)[:5], "..." if len(old_sections) > 5 else "")
    print("New:", sorted(new_sections)[:5], "..." if len(new_sections) > 5 else "")

def update_existing_chunks():
    """Update existing chunks in the database with corrected hierarchy"""
    
    try:
        from app.database import SessionLocal
        from app.models import StatuteChunk
        from sqlalchemy import select
        
        logger.info("Updating existing chunks in database...")
        
        with SessionLocal() as db:
            # Get all existing chunks
            chunks = db.query(StatuteChunk).all()
            logger.info(f"Found {len(chunks)} chunks to update")
            
            # Group by article for efficient processing
            articles_map = {}
            for chunk in chunks:
                article_key = f"{chunk.code}_{chunk.article}"
                if article_key not in articles_map:
                    articles_map[article_key] = []
                articles_map[article_key].append(chunk)
            
            # Update hierarchy metadata
            updated_count = 0
            for article_key, article_chunks in articles_map.items():
                for chunk in article_chunks:
                    old_metadata = chunk.metadata or {}
                    
                    # Convert old structure to new hierarchy
                    new_hierarchy = {
                        "part": None,
                        "part_name": None,
                        "division": None,
                        "division_name": None,
                        "chapter": old_metadata.get('chapter'),  # Keep existing chapter
                        "chapter_name": None,
                        "book": old_metadata.get('book'),
                        "title": None
                    }
                    
                    # Parse section string to extract proper hierarchy
                    if chunk.section:
                        section_parts = chunk.section.split(' > ')
                        for part in section_parts:
                            if 'CZĘŚĆ' in part.upper():
                                new_hierarchy['part'] = part
                            elif 'DZIAŁ' in part:
                                new_hierarchy['division'] = part
                            elif 'Rozdział' in part:
                                new_hierarchy['chapter'] = part
                    
                    # Update metadata
                    old_metadata['hierarchy'] = new_hierarchy
                    chunk.metadata = old_metadata
                    updated_count += 1
            
            # Commit changes
            db.commit()
            logger.info(f"Successfully updated {updated_count} chunks")
            
    except ImportError:
        logger.warning("Database models not available. Showing comparison only.")
    except Exception as e:
        logger.error(f"Error updating chunks: {e}")

def main():
    """Main function"""
    
    # Path to KC PDF (example)
    kc_path = "data/pdfs/kodeks_cywilny.pdf"
    kpc_path = "data/pdfs/kodeks_postepowania_cywilnego.pdf"
    
    # Check which files exist
    if Path(kc_path).exists():
        print("\n=== Kodeks Cywilny (KC) ===")
        compare_parsers(kc_path)
    elif Path(kpc_path).exists():
        print("\n=== Kodeks Postępowania Cywilnego (KPC) ===")
        compare_parsers(kpc_path)
    else:
        logger.warning("No PDF files found to process")
        print("\nTo use this script:")
        print("1. Place PDF files in data/pdfs/")
        print("2. Run: python ingest/fix_hierarchy.py")
        
        # Show example of correct hierarchy
        print("\n=== Example of Correct Hierarchy ===")
        print("Polish Legal Document Structure:")
        print("1. CZĘŚĆ OGÓLNA (General Part)")
        print("   2. DZIAŁ I: Przepisy wstępne (Division I: Introductory Provisions)")
        print("      3. Rozdział I: Zakres obowiązywania (Chapter I: Scope of Application)")
        print("         4. Art. 1. (Article 1)")
        print("         4. Art. 2. (Article 2)")
        print("      3. Rozdział II: ... (Chapter II: ...)")
        print("   2. DZIAŁ II: ... (Division II: ...)")
        print("1. CZĘŚĆ SZCZEGÓLNA (Special Part)")
        print("   2. DZIAŁ I: ... (Division I: ...)")
        print("      3. Rozdział I: ... (Chapter I: ...)")
        print("         4. Art. 415. (Article 415)")
    
    # Optionally update existing chunks
    response = input("\nDo you want to update existing chunks in the database? (y/N): ")
    if response.lower() == 'y':
        update_existing_chunks()

if __name__ == "__main__":
    main()
