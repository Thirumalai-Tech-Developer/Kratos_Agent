# 🍿 Animeflix - Premium Netflix-Style Anime Platform & Admin Studio

> A high-performance full-stack web application for streaming anime, built with a Netflix-inspired UI/UX, complete anime catalog management, interactive video player, SQLite database, and administrative controls.

---

## 🌟 Key Features

### 🎬 1. Netflix-Inspired UI & Streaming Experience
- **Cinematic Dark Theme**: Signature `#141414` background, Netflix Red (`#E50914`) accents, dynamic gradient vignettes, and responsive layout.
- **Hero Billboard Banner**: Dynamic featured spotlight anime (e.g., *Solo Leveling*) with high-res backdrop, age rating badges, match scores, audio/studio tags, synopsis, interactive "Play" & "More Info" buttons, and sound toggle.
- **Interactive Sliding Carousels**:
  - **Trending Now**: Hottest releases of the week.
  - **Top 10 in Anime Today**: Styled with giant custom numbered rankings (1–10).
  - **Continue Watching**: Real-time progress bars tracking user playback percentage.
  - **My List**: Interactive watch list with persistent bookmarking.
  - **Genre Rows**: *Action & Shonen*, *Dark Fantasy & Supernatural*, *Sci-Fi & Cyberpunk*, *Slice of Life & Comedy*, and *Critically Acclaimed (95%+ Match)*.
- **Netflix Card Hover Preview**: Smooth zoom expansion cards displaying preview metadata, match %, age rating, duration, quick action buttons (*Play*, *My List*, *Thumbs Up / Like*, *Details Chevron*).
- **Anime Details Modal**:
  - Full backdrop banner with quick play and like/bookmark toggles.
  - Interactive **Episodes List** with episode thumbnails, duration, episode numbers, descriptions, and direct play buttons.
  - **More Like This**: Smart genre-based recommendation engine.
  - Complete audio, subtitle, studio, and age rating details.
- **Custom Netflix Video Player Modal**:
  - Fullscreen, theatre mode, and floating views.
  - Scrub bar with real-time hover time preview, buffer status, and keyboard shortcuts (Space/K for Play/Pause, F for Fullscreen, M for Mute, Arrow keys for 10s skip).
  - **Skip Intro** dynamic button (pops up during intro timestamps).
  - **Next Episode** transition and Episode Drawer selector.
  - Audio and Subtitle track selector (Sub/Dub).
  - Playback speed controller (0.5x, 0.75x, 1x, 1.25x, 1.5x, 2x).
- **Search & Filter System**: Real-time instant search by title, Japanese title, synopsis, and studio, plus audio filter (All / Sub / Dub) and genre pills.
- **Profile Switcher**: Switch between active anime avatars (*Monkey D. Luffy*, *Satoru Gojo*, *Nezuko Kamado*, *Tanjiro Kamado*, *Admin Manager*).

---

### 👑 2. Studio Admin Portal & Catalog Management (Full CRUD)
- **Admin Authentication**: Secure PIN / password gate (default: `animeflix2025` or `admin`).
- **Dashboard Analytics**:
  - Live metric cards: Total Titles, Total Episodes, User Bookmarks / My List Saves, Platform Views.
  - **Genre Distribution Bar**: Visual proportion of anime across categories.
  - **Leaderboard**: Highest rated anime ranked with community scores.
- **Anime Catalog Table**:
  - Live search and filter across existing database records.
  - **Add New Anime**: Full form with image previews, auto slug generation, multi-genre selection, audio/subtitle tags, studio selection, season counts, and showcase toggles (*Featured Billboard*, *Trending*, *Top 10 Rank*).
  - **Edit Anime**: Pre-filled update modal with real-time database sync.
  - **Delete Anime**: Safe removal with confirmation modal.
- **Episode Manager**: Add, edit, or delete episodes for any anime in the catalog.
- **Genre Manager**: Create and organize custom genre categories.
- **One-Click Reseed**: Instant button to reset and reload 18+ high-definition iconic anime titles (*Attack on Titan*, *Jujutsu Kaisen*, *Demon Slayer*, *Solo Leveling*, *One Piece*, *Death Note*, *Fullmetal Alchemist*, *Cyberpunk Edgerunners*, *Frieren*, *Bleach: TYBW*, *Spy x Family*, *Steins;Gate*, *Vinland Saga*, *Mob Psycho 100*, *Hunter x Hunter*, etc.).

---

## 🛠️ Technology Stack

| Layer | Technology |
|---|---|
| **Frontend** | React 19, Vite, Tailwind CSS, Lucide Icons |
| **Backend** | Node.js, Express REST API |
| **Database** | SQLite 3 via `better-sqlite3` (WAL mode enabled) |
| **Styling** | Netflix design system, CSS animations, Tailwind |

---

## 🚀 Getting Started

### 1. Install Dependencies
```bash
# In project root:
npm install

# In client folder:
cd client && npm install
```

### 2. Start Backend & Frontend

#### Option A: Unified Full-Stack Server (Serves built client + API)
```bash
# Build frontend and start Express server:
npm run build
npm start
# -> Open http://localhost:5000 in your browser!
```

#### Option B: Development Mode (Hot-Reloading)
```bash
# Terminal 1 - Backend Server:
npm run server
# -> API running on http://localhost:5000

# Terminal 2 - Frontend Client:
npm run client
# -> Client running on http://localhost:3000
```

---

## 🔑 Admin Credentials
- **Admin Password**: `animeflix2025` (or `admin`)
- Accessible via the **"Admin Access"** button in the top navigation bar or the profile dropdown.

---

## 📡 REST API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/api/anime` | `GET` | List all anime with filters (`search`, `genre`, `category`, `sort`, `limit`) |
| `/api/anime/:id` | `GET` | Single anime details + episodes + recommendations |
| `/api/anime` | `POST` | Create new anime (*Admin*) |
| `/api/anime/:id` | `PUT` | Update anime (*Admin*) |
| `/api/anime/:id` | `DELETE` | Delete anime (*Admin*) |
| `/api/genres` | `GET` | List all genres with anime count |
| `/api/genres` | `POST` | Create a new genre (*Admin*) |
| `/api/stats` | `GET` | Admin dashboard analytics & stats |
| `/api/mylist` | `GET` | Fetch current user's saved list |
| `/api/mylist/toggle` | `POST` | Add/remove anime from My List |
| `/api/likes` | `GET` | Fetch user like states |
| `/api/likes/toggle` | `POST` | Like / Dislike an anime |
| `/api/continue-watching` | `GET` | Fetch watch history and progress |
| `/api/watch-progress` | `POST` | Save playback progress percentage |
| `/api/admin/login` | `POST` | Authenticate admin password |
| `/api/seed/reset` | `POST` | Reseed catalog to default anime library |

---

## 🧪 Testing

Run the automated integration test suite:
```bash
node run_tests.js
```
All 10 automated test suites verify API endpoints, database operations, admin authentication, CRUD lifecycle, and watch history tracking.
