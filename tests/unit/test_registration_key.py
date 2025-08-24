#!/usr/bin/env python3
import pytest
if __name__ != "__main__":
    pytest.skip("Registration key tests require running API server", allow_module_level=True)

"""Test script for registration with secret key functionality."""

import requests
import json
import os
from datetime import datetime

# Configuration
BASE_URL = "http://localhost:8000/api"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin123"

def login_as_admin():
    """Login as admin and return the access token."""
    print("🔐 Logging in as admin...")
    response = requests.post(
        f"{BASE_URL}/auth/login",
        data={
            "username": "zeddq1@gmail.com",
            "password": "ahciwd123"
        }
    )
    if response.status_code == 200:
        token = response.json()["access_token"]
        print("✅ Admin login successful")
        return token
    else:
        print(f"❌ Admin login failed: {response.json()}")
        return None

def generate_registration_key(token):
    """Generate a new registration key."""
    print("\n🔑 Generating new registration key...")
    response = requests.post(
        f"{BASE_URL}/auth/admin/registration-keys/generate",
        headers={"Authorization": f"Bearer {token}"}
    )
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Generated key: {data['key']}")
        return data['key']
    else:
        print(f"❌ Failed to generate key: {response.json()}")
        return None

def check_registration_status(token):
    """Check registration configuration status."""
    print("\n📊 Checking registration status...")
    response = requests.get(
        f"{BASE_URL}/auth/admin/registration-keys/status",
        headers={"Authorization": f"Bearer {token}"}
    )
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Registration enabled: {data['registration_enabled']}")
        print(f"✅ Number of active keys: {data['number_of_active_keys']}")
        print(f"✅ Masked keys: {data['masked_keys']}")
        print(f"ℹ️  Note: {data['note']}")
    else:
        print(f"❌ Failed to get status: {response.json()}")

def test_registration_with_valid_key(secret_key):
    """Test registration with a valid secret key."""
    print(f"\n✅ Testing registration with valid key...")
    test_user = {
        "email": f"test_{datetime.now().strftime('%Y%m%d%H%M%S')}@example.com",
        "password": "TestPassword123!",
        "full_name": "Test User",
        "secret_key": secret_key
    }
    
    response = requests.post(f"{BASE_URL}/auth/register", json=test_user)
    if response.status_code == 200:
        user_data = response.json()
        print(f"✅ Registration successful!")
        print(f"   - User ID: {user_data['id']}")
        print(f"   - Email: {user_data['email']}")
        print(f"   - Role: {user_data['role']}")
        return user_data
    else:
        print(f"❌ Registration failed: {response.json()}")
        return False

def test_registration_with_invalid_key():
    """Test registration with an invalid secret key."""
    print(f"\n❌ Testing registration with invalid key...")
    test_user = {
        "email": f"invalid_{datetime.now().strftime('%Y%m%d%H%M%S')}@example.com",
        "password": "TestPassword123!",
        "full_name": "Invalid Test User",
        "secret_key": "invalid-key-12345"
    }
    
    response = requests.post(f"{BASE_URL}/auth/register", json=test_user)
    if response.status_code == 403:
        print(f"✅ Registration correctly rejected: {response.json()['detail']}")
        return True
    else:
        print(f"❌ Unexpected response: {response.status_code} - {response.json()}")
        return False

def test_registration_without_key():
    """Test registration without providing a secret key."""
    print(f"\n❌ Testing registration without key...")
    test_user = {
        "email": f"nokey_{datetime.now().strftime('%Y%m%d%H%M%S')}@example.com",
        "password": "TestPassword123!",
        "full_name": "No Key Test User"
    }
    
    response = requests.post(f"{BASE_URL}/auth/register", json=test_user)
    if response.status_code == 422:
        print(f"✅ Registration correctly rejected: Missing required field")
        return True
    else:
        print(f"❌ Unexpected response: {response.status_code} - {response.text}")
        return False

def main():
    """Run all tests."""
    print("🚀 Starting Registration Key Tests")
    print(f"📍 Testing against: {BASE_URL}")
    print("-" * 50)
    
    # First check if we're using the default key
    print("\n⚠️  Using default registration key for testing")
    print("ℹ️  In production, set REGISTRATION_SECRET_KEYS environment variable")
    
    # Test with default key
    default_key = "default-registration-key-change-in-production"
    
    # Run tests
    tests_passed = 0
    total_tests = 3
    
    test_user = {
        "email": "",
        "password": "",
        "full_name": "",
        "secret_key": ""
    }
    try:
        test_user = test_registration_with_valid_key(default_key)
        if test_user:
            tests_passed += 1
        
        if test_registration_with_invalid_key():
            tests_passed += 1
        
        if test_registration_without_key():
            tests_passed += 1
        
        # Admin tests (optional - only if admin exists)
        admin_token = login_as_admin()
        if admin_token:
            check_registration_status(admin_token)
            new_key = generate_registration_key(admin_token)
            if new_key:
                print(f"\n💡 To use this key, add it to REGISTRATION_SECRET_KEYS environment variable")
    except Exception as e:
        print(f"❌ Error: {e}")
        return False
    finally:
        print("\n" + "=" * 50)
        print(f"🏁 Test Summary: {tests_passed}/{total_tests} tests passed")
        # remove test user created in the test_registration_with_valid_key function
        if test_user and isinstance(test_user, dict) and 'id' in test_user:
            print(f"🔍 Deleting test user: {test_user}")
            response = requests.delete(f"{BASE_URL}/auth/admin/users/{test_user['id']}", headers={"Authorization": f"Bearer {admin_token}"})
            print(f"🔍 Response status code: {response.status_code}")
            if response.status_code == 204:
                print(f"✅ Test user deleted successfully")
            else:
                print(f"❌ Failed to delete test user: {response.json()}")
        else:
            print(f"🔍 No test user to delete (registration may have failed)")  
    
    if tests_passed == total_tests:
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed")

if __name__ == "__main__":
    main()
