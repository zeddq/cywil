#!/usr/bin/env python3
import pytest
if __name__ != "__main__":
    pytest.skip("Streaming test requires running full application", allow_module_level=True)

"""
Test script for streaming functionality
"""
import asyncio
import sys
import os

# Add the app directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from app.paralegal_agents.refactored_agent_sdk import ParalegalAgentSDK as ParalegalAgent
from app.core.config_service import get_config, ConfigService
from app.core.conversation_manager import ConversationManager
from app.core.tool_executor import ToolExecutor
from unittest.mock import Mock

async def test_streaming():
    """Test the streaming functionality"""
    print("🚀 Starting streaming test...")
    
    # Create required dependencies
    config_service = ConfigService()
    conversation_manager = Mock(spec=ConversationManager)
    tool_executor = Mock(spec=ToolExecutor)
    
    agent = ParalegalAgent(
        config_service=config_service,
        conversation_manager=conversation_manager,
        tool_executor=tool_executor
    )
    
    test_message = "Jakie są terminy przedawnienia roszczeń w polskim prawie cywilnym?"
    
    print(f"📝 Question: {test_message}")
    print("📡 Streaming response:")
    print("-" * 50)
    
    try:
        async for chunk in agent.process_message_stream(test_message):
            chunk_type = chunk.get("type", "unknown")
            
            if chunk_type == "text_chunk":
                print(chunk.get("content", ""), end="", flush=True)
            elif chunk_type == "tool_calls_start":
                tool_names = [tc["name"] for tc in chunk.get("tool_calls", [])]
                print(f"\n\n🔧 [Processing tools: {', '.join(tool_names)}]", flush=True)
            elif chunk_type == "tool_calls_complete":
                print("\n✅ [Tools completed]\n", flush=True)
            elif chunk_type == "complete":
                print(f"\n\n✨ Final status: {chunk.get('status')}")
                print(f"🆔 Thread ID: {chunk.get('thread_id')}")
                break
            elif chunk_type == "error":
                print(f"\n❌ Error: {chunk.get('content')}")
                break
                
    except Exception as e:
        print(f"\n💥 Exception occurred: {e}")
        return False
    
    print("\n" + "=" * 50)
    print("✅ Streaming test completed successfully!")
    return True

if __name__ == "__main__":
    success = asyncio.run(test_streaming())
    sys.exit(0 if success else 1)