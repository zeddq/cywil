#!/usr/bin/env python3
"""
MCP Configuration Integration Script

This script extracts MCP server configurations from /Users/cezary/.claude.json
and integrates them into the global MCP configuration file while avoiding duplicates
and maintaining proper JSON structure.
"""

import json
import sys
import os
from pathlib import Path


def load_json_file(file_path):
    """Load and parse a JSON file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: File not found: {file_path}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {file_path}: {e}")
        return None
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return None


def save_json_file(file_path, data):
    """Save data to a JSON file with proper formatting."""
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error writing to {file_path}: {e}")
        return False


def validate_mcp_server_config(name, config):
    """Validate an MCP server configuration."""
    if not isinstance(config, dict):
        return False, f"Server '{name}' configuration must be an object"

    if "command" not in config:
        return False, f"Server '{name}' is missing required 'command' field"

    if not isinstance(config["command"], str):
        return False, f"Server '{name}' command must be a string"

    if "args" in config and not isinstance(config["args"], list):
        return False, f"Server '{name}' args must be an array"

    if "env" in config and not isinstance(config["env"], dict):
        return False, f"Server '{name}' env must be an object"

    return True, "Valid"


def merge_mcp_configurations():
    """Main function to merge MCP configurations."""

    # File paths
    source_file = "/Users/cezary/.claude.json"
    target_file = "../../../../Users/cezary/Library/Application Support/Cursor/User/globalStorage/rooveterinaryinc.roo-cline/settings/mcp_settings.json"

    print("MCP Configuration Integration")
    print("=" * 40)

    # Load source configuration
    print(f"Loading source configuration from: {source_file}")
    source_config = load_json_file(source_file)
    if source_config is None:
        print("Failed to load source configuration. Exiting.")
        return False

    # Load target configuration
    print(f"Loading target configuration from: {target_file}")
    target_config = load_json_file(target_file)
    if target_config is None:
        print("Failed to load target configuration. Exiting.")
        return False

    # Extract MCP servers from source
    if "mcpServers" not in source_config:
        print("No 'mcpServers' section found in source configuration.")
        return False

    source_servers = source_config["mcpServers"]
    print(f"Found {len(source_servers)} servers in source configuration:")
    for name in source_servers.keys():
        print(f"  - {name}")

    # Ensure target has mcpServers section
    if "mcpServers" not in target_config:
        target_config["mcpServers"] = {}

    target_servers = target_config["mcpServers"]
    print(f"Found {len(target_servers)} servers in target configuration")

    # Merge configurations
    merged_count = 0
    skipped_count = 0
    validation_errors = []

    print("\nMerging configurations...")

    for server_name, server_config in source_servers.items():
        # Check for duplicates
        if server_name in target_servers:
            print(f"  ⚠️  Skipping '{server_name}' - already exists in target")
            skipped_count += 1
            continue

        # Validate server configuration
        is_valid, validation_msg = validate_mcp_server_config(
            server_name, server_config
        )
        if not is_valid:
            print(f"  ❌ Skipping '{server_name}' - {validation_msg}")
            validation_errors.append(f"{server_name}: {validation_msg}")
            continue

        # Add to target configuration
        target_servers[server_name] = server_config
        print(f"  ✅ Added '{server_name}'")
        merged_count += 1

    # Summary
    print(f"\nMerge Summary:")
    print(f"  Servers added: {merged_count}")
    print(f"  Servers skipped (duplicates): {skipped_count}")
    print(f"  Validation errors: {len(validation_errors)}")

    if validation_errors:
        print(f"\nValidation Errors:")
        for error in validation_errors:
            print(f"  - {error}")

    # Save merged configuration
    if merged_count > 0:
        print(f"\nSaving merged configuration to: {target_file}")
        if save_json_file(target_file, target_config):
            print("✅ Configuration successfully integrated!")
            print(f"Total servers in global configuration: {len(target_servers)}")

            # Display final server list
            print("\nFinal server list:")
            for name in sorted(target_servers.keys()):
                print(f"  - {name}")

            return True
        else:
            print("❌ Failed to save merged configuration")
            return False
    else:
        print("No new servers were added. Target configuration unchanged.")
        return True


if __name__ == "__main__":
    success = merge_mcp_configurations()
    sys.exit(0 if success else 1)
