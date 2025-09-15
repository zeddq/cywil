#!/usr/bin/env python3
import pytest
if __name__ != "__main__":
    pytest.skip("API client tests require running server and database", allow_module_level=True)

"""
Unified client for testing the AI Paralegal API, CLI, and retrieving logs.
"""

import requests
import json
import argparse
import sys
import asyncio
from typing import Optional, Dict, Any, List
import logging
from datetime import datetime, timedelta

# Database imports for audit log retrieval
from sqlalchemy import select, desc, and_
from app.core.database_manager import DatabaseManager
from app.models import Note, Case, FormTemplate

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- API Client ---

class ParalegalAPIClient:
    """Client for interacting with the AI Paralegal API"""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.token = None

    def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Generic request handler"""
        url = f"{self.base_url}/{endpoint}"
        
        # Add authorization header if token is available
        if self.token and 'headers' in kwargs:
            kwargs['headers']['Authorization'] = f'Bearer {self.token}'
        elif self.token:
            kwargs['headers'] = {'Authorization': f'Bearer {self.token}'}
            
        logger.info(f"Making HTTP {method} request to {url}")
        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            # Handle cases where response might be empty
            if response.text:
                return response.json()
            return {}
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            if e.response is not None:
                logger.error(f"Response body: {e.response.text}")
            raise

    def chat(self, message: str, thread_id: Optional[str] = None, case_id: Optional[str] = None) -> Dict[str, Any]:
        """Send a chat message"""
        payload = {"message": message, "thread_id": thread_id, "case_id": case_id}
        return self._request("POST", "chat", json=payload, headers={"Content-Type": "application/json"})

    def query_documents(self, query: str) -> Dict[str, Any]:
        """Query the document database"""
        return self._request("POST", "query", params={"query": query}, headers={"Content-Type": "application/json"})

    def create_case(self, case_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new legal case"""
        return self._request("POST", "cases", json=case_data, headers={"Content-Type": "application/json"})

    def list_cases(self, status: Optional[str] = None) -> Dict[str, Any]:
        """List all cases"""
        params = {"status": status} if status else {}
        return self._request("GET", "cases", params=params)

    def get_case(self, case_id: str) -> Dict[str, Any]:
        """Get detailed information about a case"""
        return self._request("GET", f"cases/{case_id}")

    def health_check(self) -> Dict[str, Any]:
        """Check API health"""
        return self._request("GET", "health")
    
    # Authentication methods
    def register(self, email: str, password: str, full_name: str, secret_key: str) -> Dict[str, Any]:
        """Register a new user with secret key"""
        payload = {
            "email": email,
            "password": password,
            "full_name": full_name,
            "secret_key": secret_key
        }
        return self._request("POST", "api/auth/register", json=payload, headers={"Content-Type": "application/json"})
    
    def login(self, email: str, password: str) -> Dict[str, Any]:
        """Login and set token"""
        data = {
            "username": email,  # OAuth2 expects 'username'
            "password": password
        }
        response = self._request("POST", "api/auth/login", data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        if 'access_token' in response:
            self.token = response['access_token']
        return response
    
    def logout(self) -> Dict[str, Any]:
        """Logout and clear token"""
        response = self._request("POST", "api/auth/logout")
        self.token = None
        return response
    
    def get_current_user(self) -> Dict[str, Any]:
        """Get current user info"""
        return self._request("GET", "api/auth/me")
    
    def generate_registration_key(self) -> Dict[str, Any]:
        """Generate a new registration key (admin only)"""
        return self._request("POST", "api/auth/admin/registration-keys/generate")
    
    def get_registration_status(self) -> Dict[str, Any]:
        """Get registration configuration status (admin only)"""
        return self._request("GET", "api/auth/admin/registration-keys/status")

# --- Log Retriever ---

class AuditLogRetriever:
    """Retrieve and display AI interaction audit logs from the database"""

    async def _get_interactions(self, afilter: Optional[Any] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Generic interaction retrieval from database"""
        async with AsyncSessionLocal() as session:
            query = (
                select(Note, Case)
                .join(Case, Note.case_id == Case.id, isouter=True)
                .where(Note.note_type == "ai_interaction")
                .order_by(desc(Note.created_at))
                .limit(limit)
            )
            if afilter is not None:
                query = query.where(afilter)
            
            result = await session.execute(query)
            interactions = []
            for note, case in result:
                try:
                    content = json.loads(note.content) if note.content else {}
                    interactions.append({
                        "id": str(note.id),
                        "created_at": note.created_at.isoformat() if note.created_at else None,
                        "case_id": str(note.case_id) if note.case_id else None,
                        "reference_number": case.reference_number if case else None,
                        "case_title": case.title if case else None,
                        "thread_id": content.get("thread_id", ""),
                        "last_query": content.get("last_query", ""),
                        "last_response": content.get("last_response", ""),
                        "content": content,
                    })
                except json.JSONDecodeError:
                    logger.warning(f"Could not parse JSON for note {note.id}")
            return interactions

    async def get_all_interactions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get all AI interactions"""
        return await self._get_interactions(limit=limit)

    async def get_case_interactions(self, case_id: str) -> List[Dict[str, Any]]:
        """Get interactions for a specific case"""
        return await self._get_interactions(afilter=(Note.case_id == case_id))

    async def get_recent_interactions(self, hours: int) -> List[Dict[str, Any]]:
        """Get interactions from the last N hours"""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        return await self._get_interactions(afilter=(Note.created_at >= cutoff))  # type: ignore[reportOptionalOperand]
    
    async def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics of AI interactions"""
        all_interactions = await self.get_all_interactions(limit=10000)
        recent_24h = [i for i in all_interactions if datetime.fromisoformat(i['created_at']) > datetime.utcnow() - timedelta(hours=24)]
        recent_7d = [i for i in all_interactions if datetime.fromisoformat(i['created_at']) > datetime.utcnow() - timedelta(days=7)]

        cases = {}
        for interaction in all_interactions:
            case = interaction.get('reference_number', 'No Case')
            cases[case] = cases.get(case, 0) + 1
        
        return {
            "total_interactions": len(all_interactions),
            "interactions_last_24h": len(recent_24h),
            "interactions_last_7d": len(recent_7d),
            "interactions_by_case": dict(sorted(cases.items(), key=lambda item: item[1], reverse=True)[:10]),
        }

    def format_interaction(self, interaction: Dict[str, Any], verbose: bool = False) -> str:
        """Format an interaction for display"""
        lines = [
            "=" * 80,
            f"Interaction ID: {interaction['id']}",
            f"Date/Time: {interaction['created_at']}",
            f"Case: {interaction.get('reference_number', 'N/A')} - {interaction.get('case_title', 'N/A')}",
            f"Thread ID: {interaction.get('thread_id', 'N/A')}",
            "-" * 40,
            "USER QUERY:",
            interaction.get('last_query', 'No query recorded'),
            "-" * 40,
            "AI RESPONSE:",
            interaction.get('last_response', 'No response recorded'),
        ]
        if verbose:
            lines.extend(["-" * 40, "FULL CONTENT:", json.dumps(interaction['content'], indent=2, ensure_ascii=False)])
        lines.append("=" * 80 + "\n")
        return "\n".join(lines)


# --- Test Functions ---

def test_chat_api(client: ParalegalAPIClient, message: str, case_id: Optional[str] = None):
    """Test the chat API"""
    print(f"\n{'='*60}\nTesting Chat API\nMessage: {message}" + (f"\nCase ID: {case_id}" if case_id else "") + f"\n{'='*60}")
    try:
        response = client.chat(message, case_id=case_id)
        print(json.dumps(response, indent=2, ensure_ascii=False))
        return response
    except Exception as e:
        print(f"Error: {e}")

def test_query_api(client: ParalegalAPIClient, query: str):
    """Test the query API"""
    print(f"\n{'='*60}\nTesting Query API\nQuery: {query}\n{'='*60}")
    try:
        response = client.query_documents(query)
        print(json.dumps(response, indent=2, ensure_ascii=False))
        return response
    except Exception as e:
        print(f"Error: {e}")

def test_registration_with_key(client: ParalegalAPIClient, secret_key: str = "default-registration-key-change-in-production"):
    """Test user registration with secret key"""
    print(f"\n{'='*60}\nTesting Registration with Secret Key\n{'='*60}")
    
    test_user = {
        "email": f"test_{datetime.now().strftime('%Y%m%d%H%M%S')}@example.com",
        "password": "TestPassword123!",
        "full_name": "Test User",
        "secret_key": secret_key
    }
    
    try:
        response = client.register(**test_user)
        print("✅ Registration successful!")
        print(json.dumps(response, indent=2))
        return response
    except Exception as e:
        print(f"❌ Registration failed: {e}")
        return None

def test_auth_flow(client: ParalegalAPIClient):
    """Test complete authentication flow"""
    print("\n--- Testing Authentication Flow ---")
    
    # 1. Register a new user
    print("\n1. Registering new user with secret key...")
    user_data = test_registration_with_key(client)
    if not user_data:
        print("Skipping rest of auth flow due to registration failure")
        return
    
    # 2. Login with the new user
    print("\n2. Logging in...")
    try:
        login_response = client.login(
            email=user_data['email'],
            password="TestPassword123!"  # Using the password from registration
        )
        print("✅ Login successful!")
        print(f"Token: {login_response['access_token'][:20]}...")
    except Exception as e:
        print(f"❌ Login failed: {e}")
        return
    
    # 3. Get current user info
    print("\n3. Getting current user info...")
    try:
        current_user = client.get_current_user()
        print("✅ Got user info:")
        print(json.dumps(current_user, indent=2))
    except Exception as e:
        print(f"❌ Failed to get user info: {e}")
    
    # 4. Logout
    print("\n4. Logging out...")
    try:
        client.logout()
        print("✅ Logged out successfully")
    except Exception as e:
        print(f"❌ Logout failed: {e}")

def test_admin_registration_keys(client: ParalegalAPIClient):
    """Test admin registration key management"""
    print("\n--- Testing Admin Registration Key Management ---")
    
    # First, login as admin
    print("\n1. Logging in as admin...")
    try:
        client.login("zeddq1@gmail.com", "ahciwd123")
        print("✅ Admin login successful")
    except Exception as e:
        print(f"❌ Admin login failed: {e}")
        print("Note: This test requires an admin user to exist")
        return
    
    # Check registration status
    print("\n2. Checking registration status...")
    try:
        status = client.get_registration_status()
        print("✅ Registration status:")
        print(json.dumps(status, indent=2))
    except Exception as e:
        print(f"❌ Failed to get status: {e}")
    
    # Generate new registration key
    print("\n3. Generating new registration key...")
    try:
        new_key = client.generate_registration_key()
        print("✅ Generated new key:")
        print(json.dumps(new_key, indent=2))
        print("\n💡 To use this key, add it to REGISTRATION_SECRET_KEYS environment variable")
    except Exception as e:
        print(f"❌ Failed to generate key: {e}")

def run_api_examples(client: ParalegalAPIClient):
    """Run a sequence of example API calls"""
    print("--- Running API Examples ---")
    try:
        print("\n1. Health Check")
        health = client.health_check()
        print(json.dumps(health, indent=2, ensure_ascii=False))

        print("\n2. Authentication Tests")
        test_auth_flow(client)
        
        print("\n3. Admin Registration Key Tests")
        test_admin_registration_keys(client)

        print("\n4. Create Case")
        case_data = {
            "reference_number": f"TEST/{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "title": "Test Case - API Example", "description": "A test case created via the API.",
            "case_type": "litigation", "client_name": "Example Corp",
        }
        case = client.create_case(case_data)
        case_id = case['id']
        print(json.dumps(case, indent=2, ensure_ascii=False))

        print("\n5. Chat with Case Context")
        test_chat_api(client, "Jakie są następne kroki w tej sprawie?", case_id=case_id)
        
        print("\n6. List Cases")
        cases = client.list_cases()
        print(json.dumps(cases, indent=2, ensure_ascii=False))
        
        print("\n7. Document Query")
        test_query_api(client, "odpowiedzialność cywilna")

    except Exception as e:
        print(f"API example run failed: {e}")

def interactive_mode(client: ParalegalAPIClient):
    """Run interactive mode for chat, query, etc."""
    print("--- AI Paralegal Interactive Mode ---")
    print("Commands: chat <msg>, query <q>, cases, health, quit")
    thread_id = None
    while True:
        try:
            user_input = input("\n> ").strip()
            if user_input.lower() in ['quit', 'exit', 'q']: break
            if not user_input: continue

            cmd, *args = user_input.split(' ', 1)
            arg = args[0] if args else ""

            if cmd == 'chat':
                if not arg: print("Usage: chat <message>"); continue
                response = client.chat(arg, thread_id=thread_id)
                thread_id = response.get('thread_id')
                print(f"\n{response.get('response', 'No response')}")
            elif cmd == 'query':
                if not arg: print("Usage: query <query>"); continue
                response = client.query_documents(arg)
                print(json.dumps(response.get('results', {}), indent=2, ensure_ascii=False))
            elif cmd == 'cases':
                print(json.dumps(client.list_cases(), indent=2, ensure_ascii=False))
            elif cmd == 'health':
                print(json.dumps(client.health_check(), indent=2, ensure_ascii=False))
            else:
                print(f"Unknown command: {cmd}")
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"\nError: {e}")
    print("Goodbye!")


def demo_conversation_flow(client: ParalegalAPIClient):
    """Demonstrate a conversation flow with multiple queries"""
    print("--- Demonstrating Conversation Flow ---")
    thread_id = None
    queries = [
        "Jakie są terminy na wniesienie apelacji?",
        "A jak wygląda sytuacja gdy nie zażądano uzasadnienia?",
        "Czy można przywrócić termin do wniesienia apelacji?"
    ]
    for i, query in enumerate(queries, 1):
        print(f"\nQuery {i}: {query}")
        try:
            response = client.chat(query, thread_id=thread_id)
            thread_id = response.get('thread_id')
            print(f"Thread ID: {thread_id}")
            print(f"Response: {response.get('response', 'No response')}")
        except Exception as e:
            print(f"Error: {e}")
            break
    print(f"\n--- Conversation Demo Finished (Thread ID: {thread_id}) ---")


async def run_log_retrieval(args: argparse.Namespace):
    """Handle all log retrieval sub-commands"""
    await init_db()
    retriever = AuditLogRetriever()
    interactions = []
    
    if args.command == "logs-all":
        interactions = await retriever.get_all_interactions(limit=args.limit)
    elif args.command == "logs-case":
        interactions = await retriever.get_case_interactions(args.case_id)
    elif args.command == "logs-recent":
        interactions = await retriever.get_recent_interactions(hours=args.hours)
    elif args.command == "logs-summary":
        summary = await retriever.get_summary()
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return

    if not interactions:
        print("No interactions found matching the criteria.")
        return

    if args.json:
        print(json.dumps(interactions, indent=2, ensure_ascii=False))
    else:
        for interaction in interactions:
            print(retriever.format_interaction(interaction, verbose=args.verbose))

async def list_templates(args: argparse.Namespace):
    """List all available templates from the database"""
    await init_db()
    
    templates_data = []
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(FormTemplate).order_by(FormTemplate.name))
        templates = result.scalars().all()
        
        for t in templates:
            templates_data.append({
                'id': t.id,
                'name': t.name,
                'category': t.category,
                'summary': t.summary,
                'variables': t.variables,
                'usage_count': t.usage_count,
                'last_used': t.last_used.isoformat() if t.last_used else None,
                'content': t.content
            })

    if not templates_data:
        print("No templates found in the database.")
        return

    if args.json:
        print(json.dumps(templates_data, indent=2, ensure_ascii=False))
    else:
        print(f"{'Name':<40} {'Category':<20} {'Variables':<30} {'Usage Count':<12}")
        print(f"{'-'*40} {'-'*20} {'-'*30} {'-'*12}")
        for t in templates_data:
            variables_str = ", ".join(map(str, t.get('variables', [])))[:30]
            print(f"{t['name'][:40]:<40} {t['category'][:20]:<20} {variables_str:<30} {t['usage_count']:<12}")

# --- Main CLI ---

def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(description="Unified CLI for AI Paralegal System.", formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8000", help="Base URL for the API")
    
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands")

    # API testing commands
    subparsers.add_parser("examples", help="Run a series of example API calls")
    subparsers.add_parser("interactive", help="Run in interactive API testing mode")
    subparsers.add_parser("demo-conversation", help="Run a demo conversation flow")
    
    p_chat = subparsers.add_parser("chat", help="Send a single chat message")
    p_chat.add_argument("message", help="The message to send")
    p_chat.add_argument("--case-id", help="Case ID for context")

    p_query = subparsers.add_parser("query", help="Query the document database")
    p_query.add_argument("query", help="The query string")
    
    # Authentication commands
    p_register = subparsers.add_parser("register", help="Register a new user with secret key")
    p_register.add_argument("email", help="Email address")
    p_register.add_argument("password", help="Password")
    p_register.add_argument("full_name", help="Full name")
    p_register.add_argument("--secret-key", default="default-registration-key-change-in-production", help="Registration secret key")
    
    p_login = subparsers.add_parser("login", help="Login a user")
    p_login.add_argument("email", help="Email address")
    p_login.add_argument("password", help="Password")
    
    subparsers.add_parser("test-auth", help="Test complete authentication flow")
    subparsers.add_parser("test-registration-keys", help="Test admin registration key management")

    # Log retrieval commands
    p_logs_all = subparsers.add_parser("logs-all", help="Get all AI interaction logs from DB")
    p_logs_all.add_argument("--limit", type=int, default=50, help="Max records to retrieve")
    p_logs_all.add_argument("-v", "--verbose", action="store_true", help="Show full JSON content")
    p_logs_all.add_argument("--json", action="store_true", help="Output as JSON")
    
    p_logs_case = subparsers.add_parser("logs-case", help="Get interaction logs for a specific case")
    p_logs_case.add_argument("case_id", help="The case ID to filter by")
    p_logs_case.add_argument("-v", "--verbose", action="store_true", help="Show full JSON content")
    p_logs_case.add_argument("--json", action="store_true", help="Output as JSON")

    p_logs_recent = subparsers.add_parser("logs-recent", help="Get recent interaction logs")
    p_logs_recent.add_argument("hours", type=int, nargs="?", default=24, help="Get logs from the last N hours (default: 24)")
    p_logs_recent.add_argument("-v", "--verbose", action="store_true", help="Show full JSON content")
    p_logs_recent.add_argument("--json", action="store_true", help="Output as JSON")

    subparsers.add_parser("logs-summary", help="Show summary statistics of AI interactions")

    # Template listing
    p_list_templates = subparsers.add_parser("list-templates", help="List all available document templates from DB")
    p_list_templates.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()
    client = ParalegalAPIClient(base_url=args.base_url)

    if args.command == "examples":
        run_api_examples(client)
    elif args.command == "interactive":
        interactive_mode(client)
    elif args.command == "demo-conversation":
        demo_conversation_flow(client)
    elif args.command == "chat":
        test_chat_api(client, args.message, args.case_id)
    elif args.command == "query":
        test_query_api(client, args.query)
    elif args.command == "register":
        try:
            response = client.register(args.email, args.password, args.full_name, args.secret_key)
            print("✅ Registration successful!")
            print(json.dumps(response, indent=2))
        except Exception as e:
            print(f"❌ Registration failed: {e}")
    elif args.command == "login":
        try:
            response = client.login(args.email, args.password)
            print("✅ Login successful!")
            print(f"Token: {response['access_token'][:20]}...")
        except Exception as e:
            print(f"❌ Login failed: {e}")
    elif args.command == "test-auth":
        test_auth_flow(client)
    elif args.command == "test-registration-keys":
        test_admin_registration_keys(client)
    elif args.command.startswith("logs-"):
        asyncio.run(run_log_retrieval(args))
    elif args.command == "list-templates":
        asyncio.run(list_templates(args))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
