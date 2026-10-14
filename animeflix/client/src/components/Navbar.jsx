import React, { useState, useEffect, useRef } from 'react';
import { 
  Search, 
  Bell, 
  ChevronDown, 
  ShieldCheck, 
  Film, 
  Tv, 
  Sparkles, 
  Bookmark, 
  X,
  Play,
  Volume2,
  Settings,
  LogOut,
  SlidersHorizontal,
  Flame
} from 'lucide-react';

export const PROFILES = [
  { id: 'luffy', name: 'Monkey D. Luffy', avatar: 'https://images.unsplash.com/photo-1578632767115-351597cf2477?auto=format&fit=crop&w=120&q=80', badge: '👒' },
  { id: 'gojo', name: 'Satoru Gojo', avatar: 'https://images.unsplash.com/photo-1607604276583-eef5d076aa5f?auto=format&fit=crop&w=120&q=80', badge: '👓' },
  { id: 'nezuko', name: 'Nezuko Kamado', avatar: 'https://images.unsplash.com/photo-1563089145-599997674d42?auto=format&fit=crop&w=120&q=80', badge: '🌸' },
  { id: 'tanjiro', name: 'Tanjiro Kamado', avatar: 'https://images.unsplash.com/photo-1534447677768-be436bb09401?auto=format&fit=crop&w=120&q=80', badge: '🗡️' },
  { id: 'admin', name: 'Admin Manager', avatar: 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=120&q=80', badge: '👑' }
];

export default function Navbar({
  currentView,
  setCurrentView,
  selectedGenre,
  setSelectedGenre,
  genres = [],
  searchQuery,
  setSearchQuery,
  audioFilter,
  setAudioFilter,
  currentProfile,
  setCurrentProfile,
  onOpenAdmin,
  isAdminLoggedIn,
  onSelectAnime,
  animeList = []
}) {
  const [isScrolled, setIsScrolled] = useState(false);
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [isProfileMenuOpen, setIsProfileMenuOpen] = useState(false);
  const [isNotificationsOpen, setIsNotificationsOpen] = useState(false);
  const [isGenreDropdownOpen, setIsGenreDropdownOpen] = useState(false);
  const searchInputRef = useRef(null);
  const searchContainerRef = useRef(null);

  // Detect scroll to apply black background like Netflix
  useEffect(() => {
    const handleScroll = () => {
      if (window.scrollY > 40) {
        setIsScrolled(true);
      } else {
        setIsScrolled(false);
      }
    };
    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  // Handle outside click for search & profile
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (searchContainerRef.current && !searchContainerRef.current.contains(e.target)) {
        if (!searchQuery) {
          setIsSearchOpen(false);
        }
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [searchQuery]);

  const searchResults = searchQuery.trim()
    ? animeList.filter(a => 
        a.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (a.japanese_title && a.japanese_title.toLowerCase().includes(searchQuery.toLowerCase())) ||
        (a.studio && a.studio.toLowerCase().includes(searchQuery.toLowerCase()))
      ).slice(0, 5)
    : [];

  return (
    <header className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 ${
      isScrolled ? 'bg-[#141414]/95 backdrop-blur-md shadow-2xl py-3' : 'bg-gradient-to-b from-black/90 via-black/50 to-transparent py-4'
    }`}>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex items-center justify-between gap-4">
        
        {/* Left Side: Brand Logo & Navigation */}
        <div className="flex items-center gap-6 lg:gap-8">
          {/* Logo */}
          <button 
            onClick={() => { setCurrentView('home'); setSelectedGenre('all'); setSearchQuery(''); }}
            className="flex items-center gap-1.5 focus:outline-none group text-left"
          >
            <span className="text-2xl sm:text-3xl font-black tracking-tighter text-[#E50914] uppercase drop-shadow-[0_2px_10px_rgba(229,9,20,0.4)] group-hover:scale-105 transition-transform">
              ANIME<span className="text-white">FLIX</span>
            </span>
          </button>

          {/* Desktop Navigation Links */}
          <nav className="hidden md:flex items-center gap-5 text-sm font-medium">
            <button
              onClick={() => { setCurrentView('home'); setSelectedGenre('all'); setSearchQuery(''); }}
              className={`transition-colors ${currentView === 'home' && selectedGenre === 'all' && !searchQuery ? 'text-white font-bold' : 'text-gray-300 hover:text-gray-100'}`}
            >
              Home
            </button>
            <button
              onClick={() => { setCurrentView('series'); setSelectedGenre('all'); }}
              className={`transition-colors ${currentView === 'series' ? 'text-white font-bold' : 'text-gray-300 hover:text-gray-100'}`}
            >
              Series
            </button>
            <button
              onClick={() => { setCurrentView('movies'); setSelectedGenre('all'); }}
              className={`transition-colors ${currentView === 'movies' ? 'text-white font-bold' : 'text-gray-300 hover:text-gray-100'}`}
            >
              Movies
            </button>
            <button
              onClick={() => { setCurrentView('popular'); setSelectedGenre('all'); }}
              className={`transition-colors ${currentView === 'popular' ? 'text-white font-bold' : 'text-gray-300 hover:text-gray-100'}`}
            >
              New & Popular
            </button>
            <button
              onClick={() => { setCurrentView('mylist'); setSelectedGenre('all'); }}
              className={`flex items-center gap-1.5 transition-colors ${currentView === 'mylist' ? 'text-white font-bold' : 'text-gray-300 hover:text-gray-100'}`}
            >
              <Bookmark className="w-3.5 h-3.5" />
              My List
            </button>
          </nav>
        </div>

        {/* Middle / Right Controls */}
        <div className="flex items-center gap-3 sm:gap-4">
          
          {/* Genre Filter Dropdown */}
          <div className="relative">
            <button
              onClick={() => setIsGenreDropdownOpen(!isGenreDropdownOpen)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-black/60 border border-gray-700 hover:border-gray-500 text-xs sm:text-sm font-medium text-gray-200 transition-all"
            >
              <SlidersHorizontal className="w-3.5 h-3.5 text-[#E50914]" />
              <span className="capitalize">{selectedGenre === 'all' ? 'Genres' : selectedGenre}</span>
              <ChevronDown className="w-3 h-3 text-gray-400" />
            </button>

            {isGenreDropdownOpen && (
              <div className="absolute left-0 mt-2 w-48 bg-[#181818] border border-gray-800 rounded-md shadow-2xl py-2 z-50 animate-fade-in max-h-72 overflow-y-auto">
                <button
                  onClick={() => { setSelectedGenre('all'); setIsGenreDropdownOpen(false); }}
                  className={`w-full text-left px-4 py-2 text-xs font-semibold hover:bg-white/10 ${selectedGenre === 'all' ? 'text-[#E50914] bg-white/5' : 'text-gray-300'}`}
                >
                  All Genres
                </button>
                {genres.map((g) => (
                  <button
                    key={g.id || g.slug}
                    onClick={() => { setSelectedGenre(g.slug); setIsGenreDropdownOpen(false); }}
                    className={`w-full text-left px-4 py-2 text-xs font-semibold hover:bg-white/10 ${selectedGenre === g.slug ? 'text-[#E50914] bg-white/5' : 'text-gray-300'}`}
                  >
                    {g.name}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Sub / Dub Audio Toggle */}
          <div className="hidden lg:flex items-center bg-black/60 border border-gray-700 rounded p-0.5 text-xs font-semibold">
            <button
              onClick={() => setAudioFilter('All')}
              className={`px-2.5 py-1 rounded transition-colors ${audioFilter === 'All' ? 'bg-[#E50914] text-white' : 'text-gray-400 hover:text-white'}`}
            >
              All
            </button>
            <button
              onClick={() => setAudioFilter('Sub')}
              className={`px-2.5 py-1 rounded transition-colors ${audioFilter === 'Sub' ? 'bg-[#E50914] text-white' : 'text-gray-400 hover:text-white'}`}
            >
              Sub
            </button>
            <button
              onClick={() => setAudioFilter('Dub')}
              className={`px-2.5 py-1 rounded transition-colors ${audioFilter === 'Dub' ? 'bg-[#E50914] text-white' : 'text-gray-400 hover:text-white'}`}
            >
              Dub
            </button>
          </div>

          {/* Search Box */}
          <div ref={searchContainerRef} className="relative">
            <div className={`flex items-center transition-all duration-300 ${
              isSearchOpen || searchQuery ? 'bg-black/90 border border-gray-600 px-2.5 py-1.5 rounded-full w-44 sm:w-64' : 'w-9 h-9'
            }`}>
              <button
                onClick={() => {
                  setIsSearchOpen(true);
                  setTimeout(() => searchInputRef.current?.focus(), 100);
                }}
                className="text-gray-300 hover:text-white transition-colors focus:outline-none"
                aria-label="Search"
              >
                <Search className="w-4 h-4" />
              </button>

              {(isSearchOpen || searchQuery) && (
                <input
                  ref={searchInputRef}
                  type="text"
                  placeholder="Titles, anime, studios..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="bg-transparent text-white text-xs sm:text-sm placeholder-gray-500 ml-2 focus:outline-none w-full"
                />
              )}

              {searchQuery && (
                <button
                  onClick={() => { setSearchQuery(''); setIsSearchOpen(false); }}
                  className="text-gray-400 hover:text-white ml-1 p-0.5"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>

            {/* Quick Live Search Results Dropdown */}
            {searchQuery && searchResults.length > 0 && (
              <div className="absolute right-0 mt-2 w-72 sm:w-80 bg-[#181818] border border-gray-800 rounded-lg shadow-2xl overflow-hidden z-50 animate-fade-in">
                <div className="p-2 border-b border-gray-800 flex justify-between items-center text-xs text-gray-400">
                  <span>Quick Results</span>
                  <span className="text-[#E50914] font-semibold">{searchResults.length} matches</span>
                </div>
                <div className="divide-y divide-gray-800/60 max-h-80 overflow-y-auto">
                  {searchResults.map((anime) => (
                    <div
                      key={anime.id}
                      onClick={() => { onSelectAnime(anime); setSearchQuery(''); setIsSearchOpen(false); }}
                      className="p-2.5 flex items-center gap-3 hover:bg-white/10 cursor-pointer transition-colors group"
                    >
                      <img
                        src={anime.poster_image}
                        alt={anime.title}
                        className="w-10 h-14 object-cover rounded shadow"
                      />
                      <div className="flex-1 min-w-0">
                        <h4 className="text-xs font-bold text-white group-hover:text-[#E50914] truncate transition-colors">
                          {anime.title}
                        </h4>
                        <div className="flex items-center gap-2 mt-1 text-[11px] text-gray-400">
                          <span className="text-emerald-400 font-semibold">{anime.match_score}% Match</span>
                          <span>{anime.release_year}</span>
                          <span className="border border-gray-700 px-1 rounded text-[9px]">{anime.age_rating}</span>
                        </div>
                      </div>
                      <div className="w-7 h-7 rounded-full bg-white/10 flex items-center justify-center text-white group-hover:bg-[#E50914] transition-colors">
                        <Play className="w-3.5 h-3.5 fill-current ml-0.5" />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Notifications Dropdown */}
          <div className="relative">
            <button
              onClick={() => setIsNotificationsOpen(!isNotificationsOpen)}
              className="relative p-1.5 text-gray-300 hover:text-white transition-colors focus:outline-none"
              aria-label="Notifications"
            >
              <Bell className="w-5 h-5" />
              <span className="absolute top-1 right-1 w-2 h-2 bg-[#E50914] rounded-full ring-2 ring-[#141414]" />
            </button>

            {isNotificationsOpen && (
              <div className="absolute right-0 mt-2 w-72 sm:w-80 bg-[#181818] border border-gray-800 rounded-lg shadow-2xl p-3 z-50 animate-fade-in">
                <h4 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2">Notifications</h4>
                <div className="space-y-2">
                  <div className="p-2 rounded bg-white/5 hover:bg-white/10 transition-colors flex gap-2.5 items-start">
                    <Flame className="w-4 h-4 text-[#E50914] shrink-0 mt-0.5" />
                    <div>
                      <p className="text-xs font-semibold text-white">Solo Leveling Season 2 Now Streaming</p>
                      <p className="text-[10px] text-gray-400">Episode 5 is available in 4K Ultra HD.</p>
                    </div>
                  </div>
                  <div className="p-2 rounded bg-white/5 hover:bg-white/10 transition-colors flex gap-2.5 items-start">
                    <Sparkles className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                    <div>
                      <p className="text-xs font-semibold text-white">Frieren Added to Top 10 Today</p>
                      <p className="text-[10px] text-gray-400">Ranked #5 in Worldwide Popular Anime.</p>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Admin Direct Access Button */}
          <button
            onClick={onOpenAdmin}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-bold transition-all ${
              isAdminLoggedIn 
                ? 'bg-amber-500/20 text-amber-300 border border-amber-500/50 hover:bg-amber-500/30' 
                : 'bg-[#E50914] text-white hover:bg-[#b80710] shadow-[0_0_12px_rgba(229,9,20,0.5)]'
            }`}
            title="Admin Dashboard & Anime Management"
          >
            <ShieldCheck className="w-4 h-4" />
            <span className="hidden sm:inline">{isAdminLoggedIn ? 'Admin Active' : 'Admin Access'}</span>
          </button>

          {/* User Profile Switcher */}
          <div className="relative">
            <button
              onClick={() => setIsProfileMenuOpen(!isProfileMenuOpen)}
              className="flex items-center gap-1.5 focus:outline-none group p-1"
            >
              <img
                src={currentProfile.avatar}
                alt={currentProfile.name}
                className="w-8 h-8 rounded-md object-cover border-2 border-transparent group-hover:border-[#E50914] transition-all shadow"
              />
              <ChevronDown className={`w-3.5 h-3.5 text-gray-400 group-hover:text-white transition-transform ${isProfileMenuOpen ? 'rotate-180' : ''}`} />
            </button>

            {isProfileMenuOpen && (
              <div className="absolute right-0 mt-2 w-56 bg-[#181818] border border-gray-800 rounded-lg shadow-2xl py-2 z-50 animate-fade-in">
                <div className="px-3 py-2 border-b border-gray-800">
                  <p className="text-[11px] text-gray-400 uppercase font-semibold">Current Profile</p>
                  <p className="text-xs font-bold text-white flex items-center gap-1.5 mt-0.5">
                    <span>{currentProfile.badge}</span>
                    <span>{currentProfile.name}</span>
                  </p>
                </div>

                <div className="py-1">
                  <p className="px-3 py-1 text-[10px] text-gray-500 uppercase font-bold tracking-wider">Switch Profile</p>
                  {PROFILES.map((profile) => (
                    <button
                      key={profile.id}
                      onClick={() => {
                        setCurrentProfile(profile);
                        setIsProfileMenuOpen(false);
                        if (profile.id === 'admin') {
                          onOpenAdmin();
                        }
                      }}
                      className={`w-full flex items-center gap-2.5 px-3 py-2 text-xs hover:bg-white/10 transition-colors text-left ${
                        currentProfile.id === profile.id ? 'text-[#E50914] font-bold bg-white/5' : 'text-gray-300'
                      }`}
                    >
                      <img src={profile.avatar} alt={profile.name} className="w-6 h-6 rounded object-cover" />
                      <span>{profile.name}</span>
                    </button>
                  ))}
                </div>

                <div className="border-t border-gray-800 pt-1 mt-1">
                  <button
                    onClick={() => { onOpenAdmin(); setIsProfileMenuOpen(false); }}
                    className="w-full flex items-center gap-2 px-3 py-2 text-xs font-semibold text-amber-300 hover:bg-white/10 transition-colors text-left"
                  >
                    <Settings className="w-3.5 h-3.5 text-amber-400" />
                    <span>Admin Settings & CRUD</span>
                  </button>
                </div>
              </div>
            )}
          </div>

        </div>
      </div>
    </header>
  );
}
