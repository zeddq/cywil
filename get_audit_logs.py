#!/usr/bin/env python3
"""
Script to retrieve and display audit logs/conversation history from the AI Paralegal system
"""

import asyncio
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
import argparse
from sqlalchemy import select, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, init_db
from app.models import Note, Case
from app.config import settings

class AuditLogRetriever:
    """Retrieve and display AI interaction audit logs"""
    
    async def get_all_ai_interactions(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get all AI interactions from the database"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Note, Case)
                .join(Case, Note.case_id == Case.id, isouter=True)
                .where(Note.note_type == "ai_interaction")
                .order_by(desc(Note.created_at))
                .limit(limit)
            )
            
            interactions = []
            for note, case in result:
                try:
                    content = json.loads(note.content) if note.content else {}
                    interactions.append({
                        "id": str(note.id),
                        "created_at": note.created_at.isoformat() if note.created_at else None,
                        "case_id": str(note.case_id) if note.case_id else None,
                        "case_number": case.case_number if case else None,
                        "case_title": case.title if case else None,
                        "content": content,
                        "last_query": content.get("last_query", ""),
                        "last_response": content.get("last_response", ""),
                        "thread_id": content.get("thread_id", "")
                    })
                except json.JSONDecodeError:
                    print(f"Warning: Could not parse JSON for note {note.id}")
                    
            return interactions
    
    async def get_case_interactions(self, case_id: str) -> List[Dict[str, Any]]:
        """Get all AI interactions for a specific case"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Note)
                .where(and_(
                    Note.case_id == case_id,
                    Note.note_type == "ai_interaction"
                ))
                .order_by(desc(Note.created_at))
            )
            
            interactions = []
            for note in result.scalars():
                try:
                    content = json.loads(note.content) if note.content else {}
                    interactions.append({
                        "id": str(note.id),
                        "created_at": note.created_at.isoformat() if note.created_at else None,
                        "content": content,
                        "last_query": content.get("last_query", ""),
                        "last_response": content.get("last_response", ""),
                        "thread_id": content.get("thread_id", "")
                    })
                except json.JSONDecodeError:
                    print(f"Warning: Could not parse JSON for note {note.id}")
                    
            return interactions
    
    async def get_recent_conversations(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get recent conversations within specified hours"""
        from datetime import datetime, timedelta
        
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Note, Case)
                .join(Case, Note.case_id == Case.id, isouter=True)
                .where(and_(
                    Note.note_type == "ai_interaction",
                    Note.created_at >= cutoff_time
                ))
                .order_by(desc(Note.created_at))
            )
            
            interactions = []
            for note, case in result:
                try:
                    content = json.loads(note.content) if note.content else {}
                    interactions.append({
                        "id": str(note.id),
                        "created_at": note.created_at.isoformat() if note.created_at else None,
                        "case_number": case.case_number if case else None,
                        "content": content,
                        "last_query": content.get("last_query", ""),
                        "last_response": content.get("last_response", ""),
                        "thread_id": content.get("thread_id", "")
                    })
                except json.JSONDecodeError:
                    print(f"Warning: Could not parse JSON for note {note.id}")
                    
            return interactions
    
    def format_interaction(self, interaction: Dict[str, Any], verbose: bool = False) -> str:
        """Format an interaction for display"""
        output = []
        output.append("=" * 80)
        output.append(f"Interaction ID: {interaction['id']}")
        output.append(f"Date/Time: {interaction['created_at']}")
        
        if interaction.get('case_number'):
            output.append(f"Case: {interaction['case_number']} - {interaction.get('case_title', 'N/A')}")
        
        if interaction.get('thread_id'):
            output.append(f"Thread ID: {interaction['thread_id']}")
        
        output.append("-" * 40)
        output.append(f"USER QUERY:")
        output.append(interaction.get('last_query', 'No query recorded'))
        output.append("-" * 40)
        output.append(f"AI RESPONSE:")
        output.append(interaction.get('last_response', 'No response recorded'))
        
        if verbose and interaction.get('content'):
            output.append("-" * 40)
            output.append("FULL CONTENT:")
            output.append(json.dumps(interaction['content'], indent=2, ensure_ascii=False))
        
        output.append("=" * 80)
        output.append("")
        
        return "\n".join(output)

async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Retrieve AI Paralegal audit logs and conversation history")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Get all AI interactions"
    )
    parser.add_argument(
        "--case-id",
        help="Get interactions for a specific case ID"
    )
    parser.add_argument(
        "--recent",
        type=int,
        metavar="HOURS",
        help="Get interactions from the last N hours"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of records to retrieve (default: 50)"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show full interaction content"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of formatted text"
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Show summary statistics"
    )
    
    args = parser.parse_args()
    
    # Initialize database
    await init_db()
    
    retriever = AuditLogRetriever()
    
    if args.summary:
        # Get summary statistics
        all_interactions = await retriever.get_all_ai_interactions(limit=1000)
        recent_24h = await retriever.get_recent_conversations(hours=24)
        recent_7d = await retriever.get_recent_conversations(hours=24*7)
        
        print("AI PARALEGAL AUDIT LOG SUMMARY")
        print("=" * 50)
        print(f"Total AI interactions recorded: {len(all_interactions)}")
        print(f"Interactions in last 24 hours: {len(recent_24h)}")
        print(f"Interactions in last 7 days: {len(recent_7d)}")
        
        # Count by case
        cases = {}
        for interaction in all_interactions:
            case = interaction.get('case_number', 'No Case')
            cases[case] = cases.get(case, 0) + 1
        
        print(f"\nInteractions by case:")
        for case, count in sorted(cases.items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f"  {case}: {count}")
        
        return
    
    # Get interactions based on arguments
    if args.case_id:
        interactions = await retriever.get_case_interactions(args.case_id)
        print(f"Found {len(interactions)} interactions for case {args.case_id}")
    elif args.recent:
        interactions = await retriever.get_recent_conversations(hours=args.recent)
        print(f"Found {len(interactions)} interactions in the last {args.recent} hours")
    else:
        interactions = await retriever.get_all_ai_interactions(limit=args.limit)
        print(f"Found {len(interactions)} total AI interactions (limit: {args.limit})")
    
    if not interactions:
        print("No interactions found matching the criteria.")
        return
    
    # Output results
    if args.json:
        print(json.dumps(interactions, indent=2, ensure_ascii=False))
    else:
        for interaction in interactions:
            print(retriever.format_interaction(interaction, verbose=args.verbose))

if __name__ == "__main__":
    asyncio.run(main())
