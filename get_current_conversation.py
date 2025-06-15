#!/usr/bin/env python3
"""
Script to retrieve current conversation history from the running AI Paralegal API
"""

import requests
import json
import argparse
from typing import Dict, Any

class ConversationRetriever:
    """Retrieve current conversation from the API"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
    
    def get_conversation_history(self, thread_id: str = None) -> Dict[str, Any]:
        """Get conversation history from a specific thread"""
        # This would need a new API endpoint to be implemented
        # For now, we'll show how to make sequential queries to see the conversation flow
        
        print(f"Note: The current API doesn't expose full conversation history.")
        print(f"To see conversation flow, you can make multiple queries with the same thread_id.")
        print(f"Each response includes the thread_id for continuity.")
        
        return {
            "info": "Full conversation history requires API endpoint implementation",
            "suggestion": "Use get_audit_logs.py to retrieve stored interactions from the database"
        }
    
    def test_conversation_flow(self):
        """Demonstrate a conversation flow with multiple queries"""
        print("Demonstrating conversation flow...")
        print("=" * 60)
        
        thread_id = None
        queries = [
            "Jakie są terminy na wniesienie apelacji?",
            "A jak wygląda sytuacja gdy nie zażądano uzasadnienia?",
            "Czy można przywrócić termin do wniesienia apelacji?"
        ]
        
        for i, query in enumerate(queries, 1):
            print(f"\nQuery {i}: {query}")
            print("-" * 40)
            
            try:
                payload = {
                    "message": query,
                    "thread_id": thread_id
                }
                
                response = self.session.post(
                    f"{self.base_url}/chat",
                    json=payload,
                    headers={"Content-Type": "application/json"}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    thread_id = data.get('thread_id')
                    print(f"Thread ID: {thread_id}")
                    print(f"Response: {data.get('response', 'No response')}")
                else:
                    print(f"Error: {response.status_code} - {response.text}")
                    
            except Exception as e:
                print(f"Error: {e}")
        
        print("\n" + "=" * 60)
        print(f"Conversation thread ID: {thread_id}")
        print("Use get_audit_logs.py to retrieve the stored conversation from the database.")

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Retrieve current conversation from AI Paralegal API")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of the API"
    )
    parser.add_argument(
        "--thread-id",
        help="Thread ID to retrieve conversation for"
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run a demo conversation flow"
    )
    
    args = parser.parse_args()
    
    retriever = ConversationRetriever(args.base_url)
    
    if args.demo:
        retriever.test_conversation_flow()
    elif args.thread_id:
        result = retriever.get_conversation_history(args.thread_id)
        print(json.dumps(result, indent=2))
    else:
        print("AI Paralegal Conversation Retriever")
        print("=" * 40)
        print("Options:")
        print("  --demo           Run a demo conversation")
        print("  --thread-id ID   Get conversation for thread")
        print("")
        print("Note: For stored conversations, use get_audit_logs.py")
        print("")
        print("Example usage:")
        print(f"  python {__file__} --demo")
        print(f"  python get_audit_logs.py --all")
        print(f"  python get_audit_logs.py --recent 24")

if __name__ == "__main__":
    main()