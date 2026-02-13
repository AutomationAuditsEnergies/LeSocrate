# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Le Socrate** is an interactive web application for synchronized audio course delivery with real-time Q&A features. It consists of:
- **Frontend**: React + Vite (port 5173)
- **Backend**: Flask + SocketIO (port 5000)
- **Database**: SQLite
- **Real-time**: WebSocket communication via Socket.IO

## Development Commands

### Frontend (React + Vite)
```bash
cd frontend
npm install          # Install dependencies
npm run dev          # Start dev server on port 5173
npm run build        # Build for production
npm run lint         # Run ESLint
npm run preview      # Preview production build
```

### Backend (Flask + SocketIO)
```bash
cd backend
pip install -r requirements.txt    # Install dependencies
python run.py                       # Start server on port 5000
```

The backend uses **eventlet** for async WebSocket handling. Always start with `python run.py` (not `flask run`) to properly initialize SocketIO with eventlet.

## Architecture

### Frontend Structure

```
frontend/src/
├── pages/              # Route pages (Index, Video, Admin, TestSlides, etc.)
├── components/
│   ├── slides/
│   │   ├── templates/  # Slide template components (6 different types)
│   │   └── styles/     # CSS files for each template
│   └── ...            # Other components (ProtectedAdminRoute, etc.)
└── App.jsx            # Main router configuration
```

### Backend Structure

```
backend/
├── run.py                    # Application entry point (uses eventlet)
├── main_app.py              # Flask app initialization & blueprint registration
├── routes/                  # API route blueprints
│   ├── auth_routes.py       # Authentication endpoints
│   ├── video_routes.py      # Course/video status endpoints
│   ├── admin_routes.py      # Admin panel endpoints
│   └── debug_routes.py      # Debug endpoints
├── socketio_handlers/       # SocketIO event handlers
├── services/                # Business logic
├── database/                # SQLite database management
└── utils/                   # Logging and utilities
```

### API Communication

Frontend communicates with backend via:
1. **REST API**: All routes under `/api/*` (proxied by Vite)
2. **WebSocket**: Socket.IO for real-time features (chat, participants)

**Proxy Configuration** (vite.config.js):
- `/api` → `http://localhost:5000`
- `/socket.io` → `http://localhost:5000` (WebSocket)

**CORS**: Backend allows `http://localhost:5173` and `http://localhost:3000` with credentials.

## Slide Templates System

The application has a **presentation slide generation system** with 6 template types:

### Template Types
1. **PlayfulTemplate** - 3 cards with images + decorative doodles (CSS)
2. **ReflectionTemplate** - Yellow clipboard panel with text (CSS)
3. **CaseStudyTemplate** - 3 colored cards with numbered badges (CSS)
4. **FacilitatorTemplate** - 4-step process with icons and arrows (CSS)
5. **ChartTemplate** - Text column + SVG area chart (CSS)
6. **StatsTemplate** - Statistics banner + 3 text columns (Tailwind CSS)

### Template Architecture

**Location**: `frontend/src/components/slides/templates/*.jsx`

Each template:
- Is a React component that accepts props for dynamic content
- Has its own CSS file in `frontend/src/components/slides/styles/*.css` (except StatsTemplate which uses Tailwind)
- Exports a single default component
- Accepts common props: `badge`, `brandName` (for header)

**Example Usage**:
```jsx
<PlayfulTemplate
  title="Slide Title"
  cards={[...]}
  badge="TP-CRCD"
  brandName="Sales Hacking"
/>
```

**Testing Page**: `/test-slides` route displays all templates with navigation controls.

### Template Renderer Pattern

Templates are mapped by type in `TestSlides.jsx`:
```jsx
switch (slide.type) {
  case 'playful': return <PlayfulTemplate {...slide.data} />;
  case 'reflection': return <ReflectionTemplate {...slide.data} />;
  // ... etc
}
```

When adding new templates:
1. Create component in `templates/` directory
2. Create CSS in `styles/` directory (or use Tailwind)
3. Import in `TestSlides.jsx`
4. Add case to `renderSlide()` switch statement
5. Add sample data to `slides` array

## Key Conventions

### Authentication & Sessions

- Backend uses Flask sessions (cookie-based)
- Credentials must be included in fetch requests: `credentials: 'include'`
- Two session types: User sessions (`/api/auth/login`) and Admin sessions (`/api/admin/login`)
- Protected routes check session state server-side

### Admin Access

- Username: `admin`
- Password: `secret123`
- Admin routes require admin session and are protected by `ProtectedAdminRoute` component

### Course Audio System

The backend manages a **playlist of audio files** (`COURS_PLAYLIST` in config) with:
- Scheduled start time
- Automatic playback progression based on current time
- Support for course blocks and breaks
- Time simulation for debugging

Key endpoint: `GET /api/video/status` returns current audio, offset, and course status.

### SocketIO Events

**Client → Server**:
- `user_connected` - Register user
- `get_participants` - Request participant list
- `send_question` - Send question to RAG system

**Server → Client**:
- `participants_update` - Participant count changed
- `new_message` - New chat message (question or answer)
- `force_logout` - Admin triggered disconnect

### Timezone Handling

All dates/times use **Europe/Paris timezone**. Format: `YYYY-MM-DD HH:MM:SS`.

## Styling Approaches

- **Tailwind CSS v4**: Available globally (configured in vite.config.js)
- **CSS Modules**: Traditional CSS files for slide templates
- **Mixed**: StatsTemplate uses Tailwind, others use CSS files
- **Font Loading**: Google Fonts (Fredoka, Poppins) via `@import` in CSS

When creating new slides, you can choose either approach based on preference.

## Database

SQLite database stores:
- User connection logs (arrival, departure, duration)
- Course configuration (start time)
- Session data

Location: `backend/database/` directory

## Automatic Slide Generation System (v3)

The application includes an **AI-powered slide generation system** that creates presentation slides from audio courses.

### Architecture: Hierarchical Multi-Pass Pipeline

```
Audio (Azure CDN)
       ↓
┌──────────────────────────────────┐
│  1. TRANSCRIPTION (Whisper)      │
│  Split into 10-min chunks        │
└──────────────────────────────────┘
       ↓
┌──────────────────────────────────┐
│  2. EVENT MAPPING (GPT-4)        │
│  Identify pedagogical events     │
│  per chunk with timecodes        │
└──────────────────────────────────┘
       ↓
┌──────────────────────────────────┐
│  3. INTER-BLOCK FUSION           │
│  Merge events cut at boundaries  │
│  Restore semantic continuity     │
└──────────────────────────────────┘
       ↓
┌──────────────────────────────────┐
│  4. SLIDESHOW PLANNING (GPT-4)   │
│  Decide which events need slides │
│  Choose templates                │
└──────────────────────────────────┘
       ↓
┌──────────────────────────────────┐
│  5. MINIMAL CONTENT GENERATION   │
│  Title: 5 words MAX              │
│  Content: 1-2 sentences MAX      │
└──────────────────────────────────┘
```

### Event Types

| Type | Description | Generates Slide? |
|------|-------------|------------------|
| `story` | Anecdote, history | Yes |
| `definition` | Term explanation | Yes |
| `concept` | Abstract idea | Yes |
| `example` | Concrete illustration | Yes |
| `process` | Steps, method | Yes |
| `comparison` | Parallel analysis | Yes |
| `data` | Statistics, numbers | Yes |
| `recap` | Summary | Sometimes |
| `transition` | Topic change | No |
| `filler` | Hesitation, digression | No |

### Backend Services

**Location**: `backend/services/`

| File | Purpose |
|------|---------|
| `event_mapper.py` | Analyzes chunks, identifies events with timecodes |
| `timeline_fusion.py` | Merges events across chunk boundaries |
| `slideshow_planner.py` | Decides slides, generates minimal content |
| `slide_generation_service.py` | Orchestrates the full pipeline |

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/slides/generate-v3` | POST | Run v3 pipeline (hierarchical) |
| `/api/slides/generate` | POST | Legacy v1 pipeline |
| `/api/slides/data` | GET | Get generated slides + timeline + stats |
| `/api/slides/status` | GET | Service status |
| `/api/slides/clear` | POST | Clear generated slides |

**Request body for generate-v3:**
```json
{
  "audio_id": 1,
  "max_duration": 300
}
```

**Response:**
```json
{
  "status": "success",
  "slides_count": 2,
  "slides": [...],
  "stats": {
    "audio_duration": 300,
    "chunks_processed": 1,
    "events_detected": 5,
    "events_after_fusion": 4,
    "slides_generated": 2
  },
  "timeline": [...]
}
```

### Frontend Page

**Route**: `/generated-slides`
**Component**: `frontend/src/pages/GeneratedSlides.jsx`

Features:
- Generate slides with v3 pipeline
- View statistics (duration, events, slides)
- Browse timeline of detected events
- Navigate through generated slides
- View source transcription

### Dependencies

- **OpenAI API**: Whisper (transcription) + GPT-4 (analysis)
- **pydub**: Audio segmentation
- **requests**: Direct API calls (avoids eventlet/trio conflict)

### Environment Variables

```bash
# backend/.env
OPENAI_API_KEY=sk-proj-...
```

## API Reference

Full API documentation is in `API_ROUTES.md` at the root of the repository. Key routes:
- Authentication: `/api/auth/*`
- Course status: `/api/video/status`, `/api/cours-status`
- Admin panel: `/api/admin/*`
- Debug tools: `/api/debug/*`
- Slide generation: `/api/slides/*`

Refer to `API_ROUTES.md` for complete request/response schemas.
