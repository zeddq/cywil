#!/usr/bin/env python3
"""
Simple CLI tool to test the AI Paralegal system
"""

import asyncio
import argparse
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent))

from app.orchestrator import ParalegalAgent
from app.config import settings

async def test_chat(message: str, case_id: str = None):
    """Test the chat functionality"""
    agent = ParalegalAgent()
    
    print(f"\n{'='*60}")
    print(f"Question: {message}")
    print(f"{'='*60}")
    
    try:
        # Process the message
        response = await agent.process_message(message)
        
        print(f"\nResponse:")
        print(f"Status: {response['status']}")
        print(f"Thread ID: {response['thread_id']}")
        print(f"\n{response['response']}")
        
        return response
        
    except Exception as e:
        print(f"Error: {e}")
        return None

async def interactive_mode():
    """Run interactive chat mode"""
    agent = ParalegalAgent()
    thread_id = None
    
    print("AI Paralegal Interactive Mode")
    print("Type 'quit' or 'exit' to end the session")
    print("Type 'help' for available commands")
    print("-" * 50)
    
    while True:
        try:
            user_input = input("\nQ: ").strip()
            
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("Goodbye!")
                break
            
            if user_input.lower() == 'help':
                print("\nAvailable commands:")
                print("- Ask any legal question in Polish")
                print("- 'quit' or 'exit' to end session")
                print("- 'help' to show this message")
                print("\nExample questions:")
                print("- Jakie są terminy na wniesienie apelacji?")
                print("- Przygotuj wezwanie do zapłaty za fakturę na 10000 zł")
                print("- Jakie warunki musi spełnić pozew?")
                continue
            
            if not user_input:
                continue
            
            print("\nProcessing...")
            response = await agent.process_message(user_input, thread_id)
            
            # Update thread_id for conversation continuity
            thread_id = response.get('thread_id')
            
            print(f"\nA: {response['response']}")
            
        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}")

def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(description="AI Paralegal CLI Tool")
    parser.add_argument(
        "-q", "--question",
        help="Ask a single question and exit"
    )
    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Run in interactive mode"
    )
    parser.add_argument(
        "--case-id",
        help="Case ID for context"
    )
    parser.add_argument(
        "--examples",
        action="store_true",
        help="Run example queries"
    )
    
    args = parser.parse_args()
    
    if args.examples:
        # Run example queries
        examples = [
            "Jakie są terminy na wniesienie apelacji w postępowaniu cywilnym?",
            "Przygotuj wezwanie do zapłaty za fakturę na 45,000 zł z kwietnia 2025",
            "Jakie warunki musi spełnić pozew według KPC?",
            "Oblicz termin przedawnienia dla roszczenia z umowy z 15 marca 2023"
        ]
        
        print("Running example queries...")
        for example in examples:
            asyncio.run(test_chat(example, args.case_id))
            
    elif args.question:
        # Single question mode
        asyncio.run(test_chat(args.question, args.case_id))
        
    elif args.interactive:
        # Interactive mode
        asyncio.run(interactive_mode())
        
    else:
        # Show help if no arguments
        parser.print_help()
        print("\nQuick start:")
        print("  python test_cli.py -q 'Jakie są terminy apelacji?'")
        print("  python test_cli.py -i")
        print("  python test_cli.py --examples")

if __name__ == "__main__":
    main()
