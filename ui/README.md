# AI Paralegal UI

Web interface for the AI Paralegal system - Polish civil law assistant.

## Architecture

Based on CLAUDE.md specifications:
- **Chat UI** - Main conversational interface with the orchestrator agent
- **Case Management** - Track and manage legal cases
- **Document Management** - Upload and view legal documents
- **Deadline Tracking** - Monitor important dates and deadlines

## Tech Stack

- **Next.js 15** - React framework with App Router
- **TypeScript** - Type safety
- **Tailwind CSS** - Styling
- **Axios** - HTTP client
- **Lucide Icons** - Icon set

## Setup

1. Install dependencies:
```bash
npm install
```

2. Configure environment:
```bash
cp .env.example .env
```

3. Run development server:
```bash
npm run dev
```

The UI will be available at http://localhost:3000

## API Integration

The UI connects to the FastAPI backend running on port 8000. API calls are proxied through Next.js rewrites to avoid CORS issues.

## Features

### Implemented
- ✅ Chat interface with message history
- ✅ Citation display for legal references
- ✅ Document attachment support
- ✅ Responsive sidebar navigation
- ✅ API client service

### Planned
- [ ] Case management CRUD operations
- [ ] Document upload with drag & drop
- [ ] Deadline calendar view
- [ ] Real-time notifications
- [ ] Multi-language support (PL/EN)
- [ ] Voice input (Whisper API)

## Project Structure

```
ui/
├── app/              # Next.js app directory
│   ├── layout.tsx    # Root layout
│   ├── page.tsx      # Main page with navigation
│   └── globals.css   # Global styles
├── components/       # React components
│   └── Chat.tsx      # Chat interface component
├── lib/              # Utilities and services
│   ├── api/          # API client
│   └── types/        # TypeScript types
└── public/           # Static assets
```