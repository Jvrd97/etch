# Habit Tracker Frontend

Modern, responsive web application for tracking habits built with Next.js 16, Bun, and TailwindCSS.

## Features

- 📊 **Dashboard** - Overview of your tracking stats
- 📁 **Categories** - Create and manage custom tracking categories with dynamic fields
- 📝 **Entries** - Log daily data for your categories
- 📖 **Journal** - Write daily journal entries with mood tracking
- 🎨 **Modern UI** - Clean, responsive design with TailwindCSS
- ⚡ **Fast** - Built with Next.js App Router and Bun runtime

## Tech Stack

- **Framework**: Next.js 16 (App Router)
- **Runtime**: Bun
- **Language**: TypeScript
- **Styling**: TailwindCSS 4.x
- **Icons**: Lucide React
- **API Client**: Native Fetch API

## Getting Started

### Prerequisites

- Bun 1.3+ installed
- Backend API running on http://localhost:8000

### Development

```bash
# Install dependencies
bun install

# Run development server
bun dev

# Open browser
# http://localhost:3000
```

### Tests

```bash
# Unit tests and hook tests (happy-dom is preloaded via bunfig.toml)
bun test
```

### Production Build

```bash
# Build for production
bun run build

# Start production server
bun start
```

### Docker

```bash
# Build and run with Docker Compose
docker-compose up --build frontend

# Access at http://localhost:3000
```

## Project Structure

```
frontend/
├── app/
│   ├── page.tsx              # Dashboard
│   ├── categories/page.tsx   # Categories management
│   ├── entries/page.tsx      # Entries tracking
│   ├── journal/page.tsx      # Journal entries
│   ├── layout.tsx            # Root layout
│   └── globals.css           # Global styles
├── components/
│   ├── Navigation.tsx        # Main navigation
│   ├── LoadingSpinner.tsx    # Loading indicator
│   └── ErrorAlert.tsx        # Error messages
├── lib/
│   └── api.ts                # API client & types
└── public/                   # Static assets
```

## API Integration

The browser always calls the app's own origin under `/api/v1`; the Next server
proxies those requests to the backend (`rewrites` in `next.config.ts`). That way
a phone on the LAN hits the same URL as the desktop.

```env
# Baked into the client bundle at build time. Default: /api/v1 (same origin).
NEXT_PUBLIC_API_URL=/api/v1

# Server-side only: where the Next server forwards /api/v1/*.
API_PROXY_TARGET=http://localhost:8000

# Dev-only: comma-separated extra hosts allowed to load /_next/* assets.
DEV_ORIGINS=192.168.1.10,my-laptop.local
```

All API calls are handled through the `lib/api.ts` module with:
- Type-safe interfaces
- Error handling
- Automatic JSON serialization

## Features in Detail

### Categories
- Create categories with custom fields
- Support for multiple field types (text, number, date, select, etc.)
- Color coding for visual organization
- Edit and delete capabilities

### Entries
- Quick data entry forms
- Dynamic fields based on selected category
- Filter by category
- Date-based tracking

### Journal
- Rich text journal entries
- Mood tracking with emojis
- Tag support
- Full CRUD operations

### Dashboard
- Quick stats overview
- Recent activity feed
- Quick action buttons
- Category and entry counts

## Environment Variables

- `NEXT_PUBLIC_API_URL` — API base path baked into the client bundle at build
  time (default: `/api/v1`, i.e. same origin as the app). Set an absolute URL
  only when the browser must bypass the Next proxy.
- `API_PROXY_TARGET` — server-side only, backend origin the Next server forwards
  `/api/v1/*` to (default: `http://localhost:8000`). Never `NEXT_PUBLIC_*`: the
  browser must not see this host.
- `DEV_ORIGINS` — dev-only, comma-separated list of extra origins allowed to load
  `/_next/*` assets (default: empty). Add your LAN IP to develop from a phone.

## License

MIT
