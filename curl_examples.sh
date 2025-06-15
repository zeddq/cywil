#!/bin/bash

# Curl examples for testing the AI Paralegal API
# Base URL - change this if running on a different host/port
BASE_URL="http://localhost:8000"

echo "AI Paralegal API - Curl Examples"
echo "================================="

# Health check
echo ""
echo "1. Health Check"
echo "---------------"
echo "curl -X GET $BASE_URL/health"
curl -X GET "$BASE_URL/health" | jq .

# Basic chat query
echo ""
echo "2. Basic Chat Query"
echo "-------------------"
echo "curl -X POST $BASE_URL/chat -H 'Content-Type: application/json' -d '{\"message\": \"Jakie są terminy na wniesienie apelacji?\"}'"
curl -X POST "$BASE_URL/chat" \
  -H "Content-Type: application/json" \
  -d '{"message": "Jakie są terminy na wniesienie apelacji?"}' | jq .

# Document query
echo ""
echo "3. Document Query"
echo "-----------------"
echo "curl -X POST '$BASE_URL/query?query=umowa%20sprzedaży'"
curl -X POST "$BASE_URL/query?query=umowa%20sprzedaży" | jq .

# Create a case
echo ""
echo "4. Create Case"
echo "----------------"
CASE_DATA='{
  "case_number": "CURL/2025/001",
  "title": "Test Case via Curl",
  "description": "Test case created via curl",
  "case_type": "contract_dispute",
  "client_name": "Test Client",
  "client_contact": {
    "email": "client@example.com",
    "phone": "+48123456789"
  },
  "opposing_party": "Test Opposing Party",
  "amount_in_dispute": 50000.0
}'

echo "curl -X POST $BASE_URL/cases -H 'Content-Type: application/json' -d '$CASE_DATA'"
CASE_RESPONSE=$(curl -s -X POST "$BASE_URL/cases" \
  -H "Content-Type: application/json" \
  -d "$CASE_DATA")

echo "$CASE_RESPONSE" | jq .

# Extract case ID for next request
CASE_ID=$(echo "$CASE_RESPONSE" | jq -r '.id')

# Chat with case context
if [ "$CASE_ID" != "null" ] && [ "$CASE_ID" != "" ]; then
  echo ""
  echo "5. Chat with Case Context"
  echo "---------------------------"
  echo "curl -X POST $BASE_URL/chat -H 'Content-Type: application/json' -d '{\"message\": \"Jakie są następne kroki w tej sprawie?\", \"case_id\": \"$CASE_ID\"}'"
  curl -X POST "$BASE_URL/chat" \
    -H "Content-Type: application/json" \
    -d "{\"message\": \"Jakie są następne kroki w tej sprawie?\", \"case_id\": \"$CASE_ID\"}" | jq .
fi

# List cases
echo ""
echo "6. List Cases"
echo "---------------"
echo "curl -X GET $BASE_URL/cases"
curl -X GET "$BASE_URL/cases" | jq .

# Get specific case
if [ "$CASE_ID" != "null" ] && [ "$CASE_ID" != "" ]; then
  echo ""
  echo "7. Get Specific Case"
  echo "----------------------"
  echo "curl -X GET $BASE_URL/cases/$CASE_ID"
  curl -X GET "$BASE_URL/cases/$CASE_ID" | jq .
fi

# Create deadline
if [ "$CASE_ID" != "null" ] && [ "$CASE_ID" != "" ]; then
  echo ""
  echo "8. Create Deadline"
  echo "------------------"
  DEADLINE_DATA="{
    \"case_id\": \"$CASE_ID\",
    \"deadline_type\": \"response_deadline\",
    \"description\": \"Respond to initial complaint\",
    \"due_date\": \"2025-07-15T10:00:00\",
    \"legal_basis\": \"art. 205 KPC\",
    \"reminder_days_before\": 3
  }"
  
  echo "curl -X POST $BASE_URL/deadlines -H 'Content-Type: application/json' -d '$DEADLINE_DATA'"
  curl -X POST "$BASE_URL/deadlines" \
    -H "Content-Type: application/json" \
    -d "$DEADLINE_DATA" | jq .
fi

# Get upcoming deadlines
echo ""
echo "9. Get Upcoming Deadlines"
echo "-------------------------"
echo "curl -X GET '$BASE_URL/deadlines/upcoming?days=30'"
curl -X GET "$BASE_URL/deadlines/upcoming?days=30" | jq .

echo ""
echo "================================="
echo "Curl examples completed!"
echo ""
echo "To run individual commands, copy and paste them from above."
echo "Make sure the API is running on $BASE_URL"
