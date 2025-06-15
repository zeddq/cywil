#!/usr/bin/env python3
"""
HTTP client for testing the AI Paralegal API endpoints
"""

import requests
import json
import argparse
import sys
from typing import Optional, Dict, Any

class ParalegalAPIClient:
    """Client for interacting with the AI Paralegal API"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        
    def chat(self, message: str, thread_id: Optional[str] = None, case_id: Optional[str] = None) -> Dict[str, Any]:
        """Send a chat message"""
        payload = {
            "message": message,
            "thread_id": thread_id,
            "case_id": case_id
        }
        
        response = self.session.post(
            f"{self.base_url}/chat",
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        
        response.raise_for_status()
        return response.json()
    
    def query_documents(self, query: str) -> Dict[str, Any]:
        """Query the document database"""
        response = self.session.post(
            f"{self.base_url}/query",
            params={"query": query},
            headers={"Content-Type": "application/json"}
        )
        
        response.raise_for_status()
        return response.json()
    
    def create_case(self, case_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new legal case"""
        response = self.session.post(
            f"{self.base_url}/cases",
            json=case_data,
            headers={"Content-Type": "application/json"}
        )
        
        response.raise_for_status()
        return response.json()
    
    def list_cases(self, status: Optional[str] = None) -> Dict[str, Any]:
        """List all cases"""
        params = {"status": status} if status else {}
        
        response = self.session.get(
            f"{self.base_url}/cases",
            params=params
        )
        
        response.raise_for_status()
        return response.json()
    
    def get_case(self, case_id: str) -> Dict[str, Any]:
        """Get detailed information about a case"""
        response = self.session.get(f"{self.base_url}/cases/{case_id}")
        response.raise_for_status()
        return response.json()
    
    def health_check(self) -> Dict[str, Any]:
        """Check API health"""
        response = self.session.get(f"{self.base_url}/health")
        response.raise_for_status()
        return response.json()

def test_chat_api(client: ParalegalAPIClient, message: str, case_id: Optional[str] = None):
    """Test the chat API"""
    print(f"\n{'='*60}")
    print(f"Testing Chat API")
    print(f"Message: {message}")
    if case_id:
        print(f"Case ID: {case_id}")
    print(f"{'='*60}")
    
    try:
        response = client.chat(message, case_id=case_id)
        print(f"\nStatus: {response['status']}")
        print(f"Thread ID: {response['thread_id']}")
        print(f"\nResponse:\n{response['response']}")
        return response
    except Exception as e:
        print(f"Error: {e}")
        return None

def test_query_api(client: ParalegalAPIClient, query: str):
    """Test the query API"""
    print(f"\n{'='*60}")
    print(f"Testing Query API")
    print(f"Query: {query}")
    print(f"{'='*60}")
    
    try:
        response = client.query_documents(query)
        print(f"\nQuery: {response.get('query', 'N/A')}")
        print(f"Results: {json.dumps(response.get('results', {}), indent=2, ensure_ascii=False)}")
        return response
    except Exception as e:
        print(f"Error: {e}")
        return None

def run_examples(client: ParalegalAPIClient):
    """Run example API calls"""
    print("Running API examples...")
    
    # Test health check
    print("\n1. Health Check")
    try:
        health = client.health_check()
        print(f"Status: {health['status']}")
        print(f"Services: {json.dumps(health['services'], indent=2)}")
    except Exception as e:
        print(f"Health check failed: {e}")
        return
    
    # Test chat API
    examples = [
        "Jakie są terminy na wniesienie apelacji?",
        "Przygotuj wezwanie do zapłaty za fakturę na 25000 zł",
        "Jakie dokumenty są wymagane do złożenia pozwu?",
        "Oblicz termin przedawnienia dla zobowiązania z 10 stycznia 2023"
    ]
    
    for i, example in enumerate(examples, 2):
        print(f"\n{i}. Chat API Test")
        test_chat_api(client, example)
    
    # Test query API
    print(f"\n{len(examples) + 2}. Query API Test")
    test_query_api(client, "umowa kupna sprzedaży")
    
    # Test case management
    print(f"\n{len(examples) + 3}. Case Management Test")
    try:
        # Create a test case
        case_data = {
            "case_number": "TEST/2025/001",
            "title": "Test Case - Invoice Payment",
            "description": "Test case for API demonstration",
            "case_type": "debt_collection",
            "client_name": "Test Client",
            "client_contact": {"email": "test@example.com", "phone": "+48123456789"},
            "opposing_party": "Test Debtor",
            "amount_in_dispute": 45000.0
        }
        
        case = client.create_case(case_data)
        print(f"Created case: {case['case_number']} (ID: {case['id']})")
        
        # Test chat with case context
        test_chat_api(
            client, 
            "Jakie są następne kroki w tej sprawie?", 
            case_id=case['id']
        )
        
    except Exception as e:
        print(f"Case management test failed: {e}")

def interactive_mode(client: ParalegalAPIClient):
    """Run interactive mode"""
    print("AI Paralegal API Interactive Mode")
    print("Type 'quit' or 'exit' to end the session")
    print("Available commands:")
    print("  chat <message>     - Send chat message")
    print("  query <query>      - Query documents")
    print("  cases            - List cases")
    print("  health             - Health check")
    print("-" * 50)
    
    thread_id = None
    
    while True:
        try:
            user_input = input("\n> ").strip()
            
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("Goodbye!")
                break
            
            if not user_input:
                continue
            
            parts = user_input.split(' ', 1)
            command = parts[0].lower()
            
            if command == 'chat':
                if len(parts) < 2:
                    print("Usage: chat <message>")
                    continue
                
                message = parts[1]
                response = client.chat(message, thread_id=thread_id)
                thread_id = response.get('thread_id')
                print(f"\n{response['response']}")
                
            elif command == 'query':
                if len(parts) < 2:
                    print("Usage: query <query>")
                    continue
                
                query = parts[1]
                response = client.query_documents(query)
                print(f"\nResults: {json.dumps(response.get('results', {}), indent=2, ensure_ascii=False)}")
                
            elif command == 'cases':
                cases = client.list_cases()
                print(f"\nCases: {json.dumps(cases, indent=2, ensure_ascii=False)}")
                
            elif command == 'health':
                health = client.health_check()
                print(f"\nHealth: {json.dumps(health, indent=2, ensure_ascii=False)}")
                
            else:
                print(f"Unknown command: {command}")
                print("Available commands: chat, query, cases, health")
                
        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}")

def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(description="AI Paralegal API Test Client")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of the API"
    )
    parser.add_argument(
        "-c", "--chat",
        help="Send a chat message"
    )
    parser.add_argument(
        "-q", "--query",
        help="Query documents"
    )
    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Run in interactive mode"
    )
    parser.add_argument(
        "--examples",
        action="store_true",
        help="Run example API calls"
    )
    parser.add_argument(
        "--case-id",
        help="Case ID for context"
    )
    
    args = parser.parse_args()
    
    client = ParalegalAPIClient(args.base_url)
    
    if args.examples:
        run_examples(client)
    elif args.chat:
        test_chat_api(client, args.chat, args.case_id)
    elif args.query:
        test_query_api(client, args.query)
    elif args.interactive:
        interactive_mode(client)
    else:
        parser.print_help()
        print("\nQuick start:")
        print(f"  python test_api.py -c 'Jakie są terminy apelacji?'")
        print(f"  python test_api.py -q 'umowa sprzedaży'")
        print(f"  python test_api.py -i")
        print(f"  python test_api.py --examples")

if __name__ == "__main__":
    main()
