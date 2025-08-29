#!/usr/bin/env python3
"""
Test script for the o3-enhanced preprocessing pipeline
"""

import asyncio
import sys
from pathlib import Path
import logging
from preprocess_sn_o3 import preprocess_sn_rulings, process_batch

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_single_file():
    """Test processing a single PDF file"""
    # Adjust this path to point to an actual PDF file
    test_pdf = Path("data/pdfs/sn-rulings/123_05.pdf")
    
    if not test_pdf.exists():
        logger.error(f"Test PDF not found: {test_pdf}")
        logger.info("Please provide a valid PDF path")
        return
    
    logger.info(f"Testing single file processing: {test_pdf}")
    
    try:
        records = await preprocess_sn_rulings(test_pdf)
        logger.info(f"Successfully processed {len(records)} paragraphs")
        
        # Display sample output
        if records:
            logger.info("\nSample output (first paragraph):")
            first_record = records[0]
            logger.info(f"Section: {first_record['section']}")
            logger.info(f"Text preview: {first_record['text'][:200]}...")
            logger.info(f"Entities found: {len(first_record['entities'])}")
            
            if first_record['entities']:
                logger.info("\nSample entities:")
                for entity in first_record['entities'][:3]:
                    logger.info(f"  - {entity['text']} ({entity['label']})")
    
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)

async def test_batch_processing():
    """Test batch processing of multiple PDFs"""
    pdf_dir = Path("data/pdfs/sn-rulings")
    
    if not pdf_dir.exists():
        logger.error(f"PDF directory not found: {pdf_dir}")
        return
    
    pdf_files = list(pdf_dir.glob("*.pdf"))[:3]  # Limit to 3 files for testing
    
    if not pdf_files:
        logger.error(f"No PDF files found in {pdf_dir}")
        return
    
    logger.info(f"Testing batch processing of {len(pdf_files)} files")
    
    try:
        records = await process_batch(pdf_files)
        if records is not None and len(records) > 0:
            logger.info(f"Successfully processed {len(records)} total paragraphs")
        elif records is not None:
            logger.info("Successfully processed 0 total paragraphs")
        else:
            logger.warning("process_batch returned None")
        
    except Exception as e:
        logger.error(f"Batch test failed: {e}", exc_info=True)

if __name__ == "__main__":
    logger.info("Starting o3-enhanced preprocessing pipeline test")
    
    # Test single file processing
    asyncio.run(test_single_file())
    
    # Uncomment to test batch processing
    # asyncio.run(test_batch_processing())
    
    logger.info("Test completed")
