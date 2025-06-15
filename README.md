# AI Paralegal POC

A proof of concept for an AI-powered paralegal assistant that helps with document analysis, legal research, and case management.

## Project Structure

```
ai-paralegal-poc/
├─ app/                 # FastAPI + Agents SDK orchestrator
│   ├─ routes.py       # API endpoints
│   ├─ tools.py        # Custom tools for the AI agent
│   └─ orchestrator.py # Agent orchestration logic
├─ ingest/
│   ├─ pdf2chunks.py   # PDF document processing
│   └─ embed.py        # Document embedding generation
├─ data/               # Processed documents and embeddings
├─ ui/                 # Frontend interface (optional)
└─ docker-compose.yml  # Container orchestration
```

## Setup

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Start the services:
```bash
docker-compose up -d
```

## Features

- Document processing and chunking
- Semantic search and retrieval
- AI-powered legal analysis
- Case management assistance

## Development

The project uses FastAPI for the backend API and can be extended with either Streamlit or Next.js for the frontend. The AI agent is built using the Agents SDK for orchestration and custom tools.

## License

MIT 
