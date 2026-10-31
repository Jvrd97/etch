# 📊 Habit Tracker - Complete Full Stack Application

> A powerful, modern habit tracking application with dynamic categories, flexible fields, and journal functionality

## 🎯 Overview

Habit Tracker is a full-stack application that allows you to create personalized tracking categories with custom fields, log daily entries, and maintain a personal journal. Built with modern technologies for performance and scalability.

## ✨ Key Features

### Backend (FastAPI + PostgreSQL)
- ✅ **RESTful API** with automatic OpenAPI documentation
- ✅ **Dynamic Categories** - Create custom tracking categories
- ✅ **Flexible Fields** - Define custom fields (text, number, date, select, etc.)
- ✅ **Entries System** - Log daily data with custom field values
- ✅ **Journal** - Personal diary with mood tracking and tags
- ✅ **Async/Await** - High-performance async operations
- ✅ **PostgreSQL 16** - Robust data persistence
- ✅ **Alembic Migrations** - Database version control
- ✅ **49 Comprehensive Tests** - Full test coverage

### Frontend (Next.js + Bun + TailwindCSS)
- ✅ **Modern UI** - Clean, responsive design
- ✅ **Dashboard** - Overview of all tracking statistics
- ✅ **Category Management** - Create/edit categories with dynamic fields
- ✅ **Entry Forms** - Quick data entry with validation
- ✅ **Journal Interface** - Rich journal entries with mood tracking
- ✅ **Real-time Updates** - Instant data refresh
- ✅ **TypeScript** - Full type safety
- ✅ **Fast Runtime** - Built with Bun for optimal performance

## 🏗️ Architecture

```
habit-tracker/
├── docker-compose.yml              # Docker orchestration
├── services/
│   ├── backend/                    # FastAPI Backend
│   │   ├── app/
│   │   │   ├── api/               # API endpoints
│   │   │   ├── models/            # SQLAlchemy models
│   │   │   ├── schemas/           # Pydantic schemas
│   │   │   ├── crud/              # Database operations
│   │   │   └── core/              # Configuration
│   │   ├── tests/                 # Test suite (49 tests)
│   │   ├── alembic/               # Database migrations
│   │   └── requirements.txt
│   └── frontend/                  # Next.js Frontend
│       ├── app/                   # Pages (App Router)
│       ├── components/            # React components
│       ├── lib/                   # API client & utilities
│       └── package.json
└── README.md
```

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose
- (Optional) Bun 1.3+ for local frontend development
- (Optional) Python 3.10+ for local backend development

### Start Everything with Docker

```bash
# Clone the repository
cd habit-tracker

# Start all services
docker-compose up --build

# In another terminal, run migrations
docker-compose exec backend alembic upgrade head

# Access the applications
# Frontend: http://localhost:3000
# Backend API: http://localhost:8000
# API Docs: http://localhost:8000/docs
```

That's it! You now have:
- ✅ PostgreSQL database running
- ✅ Backend API with auto-reload
- ✅ Frontend with hot module replacement

### Development Without Docker

#### Backend
```bash
cd services/backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# Set up database (requires PostgreSQL running)
export DATABASE_URL="postgresql://user:pass@localhost:5432/habit_tracker"
alembic upgrade head

# Run server
uvicorn app.main:app --reload

# Run tests
pytest tests/ -v
```

#### Frontend
```bash
cd services/frontend

# Install dependencies with Bun
bun install

# Run development server
bun dev

# Build for production
bun run build
bun start
```

## 📖 Usage Guide

### 1. Create a Category

Navigate to **Categories** and click **"New Category"**:

```json
{
  "name": "Sleep",
  "description": "Track sleep quality",
  "color": "#3B82F6",
  "fields": [
    {
      "name": "Duration (hours)",
      "field_type": "number",
      "is_required": true
    },
    {
      "name": "Quality",
      "field_type": "select",
      "options": "poor,average,excellent"
    }
  ]
}
```

### 2. Log an Entry

Go to **Entries** and create a new entry:
- Select your category
- Fill in the custom fields
- Add optional notes
- Save!

### 3. Write in Your Journal

Visit **Journal** to write personal entries:
- Add a title and content
- Select your mood (happy, sad, excited, etc.)
- Add tags for organization
- Save your thoughts

### 4. View Dashboard

The **Dashboard** shows:
- Total categories, entries, and journal entries
- Recent activity
- Quick action buttons

## 🔧 Tech Stack

### Backend
- **FastAPI** - Modern async web framework
- **PostgreSQL 16** - Reliable database
- **SQLAlchemy 2.0** - Async ORM
- **Alembic** - Database migrations
- **Pydantic** - Data validation
- **Pytest** - Testing framework

### Frontend
- **Next.js 16** - React framework with App Router
- **Bun** - Fast JavaScript runtime
- **TypeScript** - Type safety
- **TailwindCSS 4** - Utility-first CSS
- **Lucide React** - Beautiful icons

### DevOps
- **Docker** - Containerization
- **Docker Compose** - Multi-container orchestration

## 📊 API Endpoints

### Categories
- `GET /api/v1/categories` - List all categories
- `POST /api/v1/categories` - Create category
- `GET /api/v1/categories/{id}` - Get category
- `PATCH /api/v1/categories/{id}` - Update category
- `DELETE /api/v1/categories/{id}` - Delete category
- `POST /api/v1/categories/{id}/fields` - Add field

### Entries
- `GET /api/v1/entries` - List entries
- `POST /api/v1/entries` - Create entry
- `GET /api/v1/entries/{id}` - Get entry
- `PATCH /api/v1/entries/{id}` - Update entry
- `DELETE /api/v1/entries/{id}` - Delete entry

### Journal
- `GET /api/v1/journal` - List journal entries
- `POST /api/v1/journal` - Create journal entry
- `GET /api/v1/journal/{id}` - Get journal entry
- `PATCH /api/v1/journal/{id}` - Update journal entry
- `DELETE /api/v1/journal/{id}` - Delete journal entry

Full API documentation: http://localhost:8000/docs

## 🧪 Testing

The backend includes 49 comprehensive tests covering all CRUD operations:

```bash
# Run all tests
docker-compose exec backend pytest tests/ -v

# Run specific test file
docker-compose exec backend pytest tests/test_categories.py -v

# Run with coverage
docker-compose exec backend pytest tests/ --cov=app

# Run on every core (from services/backend): each pytest-xdist worker gets its own database, the DB role needs CREATE DATABASE
make test-fast
```

All tests passing: ✅ 49/49

## 🎨 Screenshots

### Dashboard
- Overview of tracking statistics
- Recent activity feed
- Quick action buttons

### Categories
- Visual category cards with color coding
- Field management
- Edit/delete capabilities

### Entries
- Filter by category
- Dynamic forms based on category fields
- Clean data display

### Journal
- Mood tracking with emojis
- Tag support
- Rich text entries

## 🔐 Security Notes

Current MVP does not include authentication. For production use, implement:
- [ ] JWT authentication
- [ ] User accounts
- [ ] Rate limiting
- [ ] HTTPS
- [ ] CORS restrictions

## 📈 Future Enhancements

- [ ] Data visualization with charts
- [ ] Export data (CSV, JSON)
- [ ] AI-powered insights
- [ ] Mobile app (React Native)
- [ ] Habit streaks and reminders
- [ ] Social features (sharing, challenges)
- [ ] Dark mode
- [ ] PWA support

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests
5. Submit a pull request

## 📝 License

MIT License - see LICENSE file for details

## 🙋 Support

For issues or questions:
- Check the API documentation: http://localhost:8000/docs
- Review the test suite for examples
- Create an issue on GitHub

---

**Built with ❤️ using FastAPI, Next.js, Bun, and PostgreSQL**
