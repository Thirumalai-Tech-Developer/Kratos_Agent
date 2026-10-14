import React, { useState, useEffect } from 'react';
import Navbar, { PROFILES } from './components/Navbar';
import HeroBanner from './components/HeroBanner';
import AnimeRow from './components/AnimeRow';
import AnimeCard from './components/AnimeCard';
import AnimeDetailsModal from './components/AnimeDetailsModal';
import VideoPlayerModal from './components/VideoPlayerModal';
import AdminModal from './components/AdminModal';
import Toast from './components/Toast';
import { 
  Flame, 
  Sparkles, 
  TrendingUp, 
  Bookmark, 
  Clock, 
  Star, 
  ShieldCheck, 
  Film, 
  Tv, 
  RotateCcw,
  SlidersHorizontal
} from 'lucide-react';

export default function App() {
  // Navigation and filtering
  const [currentView, setCurrentView] = useState('home'); // 'home' | 'series' | 'movies' | 'popular' | 'mylist'
  const [selectedGenre, setSelectedGenre] = useState('all');
  const [audioFilter, setAudioFilter] = useState('All');
  const [searchQuery, setSearchQuery] = useState('');
  const [currentProfile, setCurrentProfile] = useState(PROFILES[0]);

  // Data
  const [animeList, setAnimeList] = useState([]);
  const [genres, setGenres] = useState([]);
  const [myList, setMyList] = useState([]);
  const [myListMap, setMyListMap] = useState({});
  const [likesMap, setLikesMap] = useState({});
  const [watchHistory, setWatchHistory] = useState([]);
  const [loading, setLoading] = useState(true);

  // Modals
  const [selectedAnime, setSelectedAnime] = useState(null);
  const [playingAnime, setPlayingAnime] = useState(null);
  const [playingEpisode, setPlayingEpisode] = useState(null);
  const [isAdminModalOpen, setIsAdminModalOpen] = useState(false);
  const [isAdminLoggedIn, setIsAdminLoggedIn] = useState(false);
  const [toast, setToast] = useState(null);

  const showToast = (message, type = 'info') => {
    setToast({ message, type });
  };

  // Fetch initial catalog, genres, and user list
  const fetchAllData = async () => {
    try {
      setLoading(true);
      const [animeRes, genresRes, myListRes, likesRes, historyRes] = await Promise.all([
        fetch('/api/anime'),
        fetch('/api/genres'),
        fetch('/api/mylist'),
        fetch('/api/likes'),
        fetch('/api/continue-watching')
      ]);

      const animeData = await animeRes.json();
      const genresData = await genresRes.json();
      const myListData = await myListRes.json();
      const likesData = await likesRes.json();
      const historyData = await historyRes.json();

      if (animeData.success) setAnimeList(animeData.data);
      if (genresData.success) setGenres(genresData.data);
      if (myListData.success) {
        setMyList(myListData.data);
        const map = {};
        myListData.data.forEach(item => { map[item.id] = true; });
        setMyListMap(map);
      }
      if (likesData.success) setLikesMap(likesData.data);
      if (historyData.success) setWatchHistory(historyData.data);
    } catch (err) {
      console.error('Error fetching Animeflix data:', err);
      showToast('Could not load anime catalog. Please ensure backend is running.', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAllData();
  }, []);

  // Handle My List Toggle
  const handleToggleMyList = async (animeId) => {
    try {
      const res = await fetch('/api/mylist/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ anime_id: animeId })
      });
      const data = await res.json();
      if (data.success) {
        setMyListMap(prev => ({ ...prev, [animeId]: data.inList }));
        showToast(data.message, 'success');
        
        // Refresh my list
        const listRes = await fetch('/api/mylist');
        const listData = await listRes.json();
        if (listData.success) setMyList(listData.data);
      }
    } catch (err) {
      showToast('Error updating My List', 'error');
    }
  };

  // Handle Like Toggle
  const handleToggleLike = async (animeId, liked) => {
    try {
      const res = await fetch('/api/likes/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ anime_id: animeId, liked })
      });
      const data = await res.json();
      if (data.success) {
        setLikesMap(prev => ({ ...prev, [animeId]: data.liked }));
        if (data.liked === 1) showToast('Added to your Likes!', 'success');
      }
    } catch (err) {
      console.error('Error toggling like:', err);
    }
  };

  // Handle Video Watch Progress
  const handleProgressUpdate = async (animeId, episodeId, progressPercent) => {
    try {
      await fetch('/api/watch-progress', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ anime_id: animeId, episode_id: episodeId, progress_percent: progressPercent })
      });
    } catch (err) {
      // silent background update
    }
  };

  // Open Video Player
  const handlePlayAnime = (anime, episode = null) => {
    setPlayingAnime(anime);
    setPlayingEpisode(episode || (anime.episodes && anime.episodes[0]) || null);
  };

  // Featured Anime for Banner
  const featuredAnime = animeList.find(a => a.is_featured) || animeList[0];

  // Rows Data
  const trendingAnime = animeList.filter(a => a.is_trending);
  const top10Anime = animeList.filter(a => a.top_10_rank !== null).sort((a, b) => a.top_10_rank - b.top_10_rank);
  const actionAnime = animeList.filter(a => a.genres && a.genres.some(g => (g.name || g) === 'Action' || (g.slug || g) === 'action'));
  const darkFantasyAnime = animeList.filter(a => a.genres && a.genres.some(g => (g.name || g) === 'Dark Fantasy' || (g.slug || g) === 'dark-fantasy'));
  const sciFiAnime = animeList.filter(a => a.genres && a.genres.some(g => (g.name || g) === 'Sci-Fi' || (g.slug || g) === 'Cyberpunk'));
  const comedyAnime = animeList.filter(a => a.genres && a.genres.some(g => (g.name || g) === 'Comedy' || (g.slug || g) === 'Slice of Life'));
  const criticallyAcclaimed = [...animeList].sort((a, b) => b.rating - a.rating);

  // Filtered List for Specific Views
  let displayedGridList = animeList;
  if (currentView === 'mylist') {
    displayedGridList = myList;
  } else if (currentView === 'popular') {
    displayedGridList = animeList.filter(a => a.is_popular || a.is_trending);
  } else if (currentView === 'series') {
    displayedGridList = animeList.filter(a => a.season_count && !a.season_count.toLowerCase().includes('movie'));
  } else if (currentView === 'movies') {
    displayedGridList = animeList.filter(a => a.season_count && a.season_count.toLowerCase().includes('movie'));
  }

  if (selectedGenre !== 'all') {
    displayedGridList = displayedGridList.filter(a => 
      a.genres && a.genres.some(g => (g.slug || g.name || g).toLowerCase() === selectedGenre.toLowerCase())
    );
  }

  if (audioFilter !== 'All') {
    displayedGridList = displayedGridList.filter(a => 
      audioFilter === 'Dub' 
        ? (a.audio_languages && a.audio_languages.toLowerCase().includes('english'))
        : true
    );
  }

  if (searchQuery.trim()) {
    displayedGridList = animeList.filter(a =>
      a.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (a.japanese_title && a.japanese_title.toLowerCase().includes(searchQuery.toLowerCase())) ||
      (a.synopsis && a.synopsis.toLowerCase().includes(searchQuery.toLowerCase())) ||
      (a.studio && a.studio.toLowerCase().includes(searchQuery.toLowerCase()))
    );
  }

  const isGridView = currentView !== 'home' || selectedGenre !== 'all' || Boolean(searchQuery.trim());

  return (
    <div className="min-h-screen bg-[#141414] text-white flex flex-col selection:bg-[#E50914] selection:text-white">
      
      {/* Toast Notification */}
      <Toast toast={toast} onClose={() => setToast(null)} />

      {/* Navigation Bar */}
      <Navbar
        currentView={currentView}
        setCurrentView={setCurrentView}
        selectedGenre={selectedGenre}
        setSelectedGenre={setSelectedGenre}
        genres={genres}
        searchQuery={searchQuery}
        setSearchQuery={setSearchQuery}
        audioFilter={audioFilter}
        setAudioFilter={setAudioFilter}
        currentProfile={currentProfile}
        setCurrentProfile={setCurrentProfile}
        onOpenAdmin={() => setIsAdminModalOpen(true)}
        isAdminLoggedIn={isAdminLoggedIn}
        onSelectAnime={(anime) => setSelectedAnime(anime)}
        animeList={animeList}
      />

      {/* Main Content Area */}
      <main className="flex-1 pb-20">
        {loading ? (
          <div className="h-screen flex flex-col items-center justify-center space-y-4">
            <div className="w-12 h-12 border-4 border-[#E50914] border-t-transparent rounded-full animate-spin" />
            <p className="text-sm font-bold text-gray-400 tracking-wider uppercase">Loading Animeflix Catalog...</p>
          </div>
        ) : isGridView ? (
          
          /* Grid View for Search / My List / Category Browse */
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-28 sm:pt-32">
            {/* Grid Header */}
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between pb-6 mb-6 border-b border-gray-800 gap-4">
              <div>
                <h1 className="text-2xl sm:text-3xl font-black text-white capitalize flex items-center gap-2">
                  {searchQuery ? (
                    <span>Search results for "{searchQuery}"</span>
                  ) : currentView === 'mylist' ? (
                    <span className="flex items-center gap-2">
                      <Bookmark className="w-7 h-7 text-[#E50914]" />
                      My List ({displayedGridList.length})
                    </span>
                  ) : (
                    <span>{currentView === 'home' ? 'All Anime' : currentView}</span>
                  )}
                  {selectedGenre !== 'all' && (
                    <span className="text-sm text-gray-400 font-normal">
                      • {selectedGenre}
                    </span>
                  )}
                </h1>
                <p className="text-xs text-gray-400 mt-1">
                  Showing {displayedGridList.length} titles available to stream
                </p>
              </div>

              {/* View Reset Button if filtered */}
              {(selectedGenre !== 'all' || searchQuery || currentView !== 'home') && (
                <button
                  onClick={() => { setCurrentView('home'); setSelectedGenre('all'); setSearchQuery(''); }}
                  className="text-xs font-semibold text-[#E50914] hover:underline flex items-center gap-1 cursor-pointer"
                >
                  <RotateCcw className="w-3.5 h-3.5" />
                  <span>Reset filters</span>
                </button>
              )}
            </div>

            {/* Grid Content */}
            {displayedGridList.length > 0 ? (
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4 sm:gap-6">
                {displayedGridList.map((anime) => (
                  <AnimeCard
                    key={anime.id}
                    anime={anime}
                    onPlay={handlePlayAnime}
                    onOpenDetails={(a) => setSelectedAnime(a)}
                    onToggleMyList={handleToggleMyList}
                    isInMyList={Boolean(myListMap[anime.id])}
                    onToggleLike={handleToggleLike}
                    userLike={likesMap[anime.id] || 0}
                  />
                ))}
              </div>
            ) : (
              <div className="text-center py-20 max-w-md mx-auto space-y-4">
                <div className="w-16 h-16 rounded-full bg-white/5 mx-auto flex items-center justify-center text-gray-500">
                  <Film className="w-8 h-8" />
                </div>
                <h3 className="text-lg font-bold text-white">No Anime Found</h3>
                <p className="text-xs sm:text-sm text-gray-400">
                  {currentView === 'mylist'
                    ? 'Your list is currently empty. Explore titles on the home page and click "+" to add them here!'
                    : 'We could not find any anime matching your current search or filters.'}
                </p>
                <button
                  onClick={() => { setCurrentView('home'); setSelectedGenre('all'); setSearchQuery(''); }}
                  className="px-5 py-2.5 rounded-lg bg-[#E50914] text-white text-xs font-bold hover:bg-[#b80710] transition-colors"
                >
                  Browse Animeflix Catalog
                </button>
              </div>
            )}
          </div>

        ) : (

          /* Default Netflix Home Experience */
          <div className="space-y-6 sm:space-y-8">
            
            {/* Hero Billboard */}
            <HeroBanner
              anime={featuredAnime}
              onPlay={handlePlayAnime}
              onOpenDetails={(a) => setSelectedAnime(a)}
              onToggleMyList={handleToggleMyList}
              isInMyList={Boolean(featuredAnime && myListMap[featuredAnime.id])}
            />

            {/* Negative margin on first row to overlap billboard seamlessly */}
            <div className="-mt-16 sm:-mt-24 lg:-mt-32 relative z-30 space-y-6 sm:space-y-8">
              
              {/* Row 1: Continue Watching (if items exist) */}
              {watchHistory.length > 0 && (
                <AnimeRow
                  title={`Continue Watching for ${currentProfile.name}`}
                  subtitle="Pick up right where you left off"
                  icon={<Clock className="w-5 h-5" />}
                  animeList={watchHistory}
                  showProgress={true}
                  onPlay={handlePlayAnime}
                  onOpenDetails={(a) => setSelectedAnime(a)}
                  onToggleMyList={handleToggleMyList}
                  myListMap={myListMap}
                  onToggleLike={handleToggleLike}
                  likesMap={likesMap}
                />
              )}

              {/* Row 2: Trending Now */}
              <AnimeRow
                title="Trending Now"
                subtitle="Most watched series this week"
                icon={<Flame className="w-5 h-5" />}
                animeList={trendingAnime}
                onPlay={handlePlayAnime}
                onOpenDetails={(a) => setSelectedAnime(a)}
                onToggleMyList={handleToggleMyList}
                myListMap={myListMap}
                onToggleLike={handleToggleLike}
                likesMap={likesMap}
              />

              {/* Row 3: Top 10 in Anime Today (Numbered badges) */}
              <AnimeRow
                title="Top 10 in Anime Today"
                subtitle="Daily updated platform rankings"
                icon={<Sparkles className="w-5 h-5" />}
                animeList={top10Anime}
                isTop10={true}
                onPlay={handlePlayAnime}
                onOpenDetails={(a) => setSelectedAnime(a)}
                onToggleMyList={handleToggleMyList}
                myListMap={myListMap}
                onToggleLike={handleToggleLike}
                likesMap={likesMap}
              />

              {/* Row 4: My List (if user has items) */}
              {myList.length > 0 && (
                <AnimeRow
                  title="My List"
                  subtitle="Saved series & movies"
                  icon={<Bookmark className="w-5 h-5" />}
                  animeList={myList}
                  onPlay={handlePlayAnime}
                  onOpenDetails={(a) => setSelectedAnime(a)}
                  onToggleMyList={handleToggleMyList}
                  myListMap={myListMap}
                  onToggleLike={handleToggleLike}
                  likesMap={likesMap}
                />
              )}

              {/* Row 5: Action & Shonen Hits */}
              <AnimeRow
                title="Action & Shonen Hits"
                subtitle="High-octane fights and epic sagas"
                animeList={actionAnime}
                onPlay={handlePlayAnime}
                onOpenDetails={(a) => setSelectedAnime(a)}
                onToggleMyList={handleToggleMyList}
                myListMap={myListMap}
                onToggleLike={handleToggleLike}
                likesMap={likesMap}
              />

              {/* Row 6: Dark Fantasy & Thrillers */}
              <AnimeRow
                title="Dark Fantasy & Supernatural"
                subtitle="Gripping mysteries, demons, and psychological depth"
                animeList={darkFantasyAnime}
                onPlay={handlePlayAnime}
                onOpenDetails={(a) => setSelectedAnime(a)}
                onToggleMyList={handleToggleMyList}
                myListMap={myListMap}
                onToggleLike={handleToggleLike}
                likesMap={likesMap}
              />

              {/* Row 7: Sci-Fi & Cyberpunk */}
              <AnimeRow
                title="Sci-Fi & Cyberpunk"
                subtitle="Futuristic worlds, time travel, and high-tech intrigue"
                animeList={sciFiAnime}
                onPlay={handlePlayAnime}
                onOpenDetails={(a) => setSelectedAnime(a)}
                onToggleMyList={handleToggleMyList}
                myListMap={myListMap}
                onToggleLike={handleToggleLike}
                likesMap={likesMap}
              />

              {/* Row 8: Slice of Life & Comedy */}
              <AnimeRow
                title="Slice of Life & Comedy"
                subtitle="Heartwarming tales, laughs, and wholesome bonds"
                animeList={comedyAnime}
                onPlay={handlePlayAnime}
                onOpenDetails={(a) => setSelectedAnime(a)}
                onToggleMyList={handleToggleMyList}
                myListMap={myListMap}
                onToggleLike={handleToggleLike}
                likesMap={likesMap}
              />

              {/* Row 9: Critically Acclaimed (95%+ Match) */}
              <AnimeRow
                title="Critically Acclaimed Hits"
                subtitle="Highest community rated masterpieces"
                icon={<Star className="w-5 h-5 text-amber-400" />}
                animeList={criticallyAcclaimed}
                onPlay={handlePlayAnime}
                onOpenDetails={(a) => setSelectedAnime(a)}
                onToggleMyList={handleToggleMyList}
                myListMap={myListMap}
                onToggleLike={handleToggleLike}
                likesMap={likesMap}
              />

            </div>

          </div>
        )}
      </main>

      {/* Netflix Style Footer */}
      <footer className="bg-[#101010] border-t border-gray-900 text-gray-500 text-xs py-12">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 space-y-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-xl font-black text-[#E50914] uppercase tracking-wider">
                ANIME<span className="text-white">FLIX</span>
              </span>
              <span className="text-[11px] bg-white/10 px-2 py-0.5 rounded text-gray-300 font-semibold">
                v2.5 Full-Stack
              </span>
            </div>

            <button
              onClick={() => setIsAdminModalOpen(true)}
              className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-white transition-colors"
            >
              <ShieldCheck className="w-4 h-4 text-[#E50914]" />
              <span>Studio Admin Access</span>
            </button>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-[11px]">
            <div className="space-y-2">
              <p className="hover:underline cursor-pointer">Audio Description</p>
              <p className="hover:underline cursor-pointer">Help Center</p>
              <p className="hover:underline cursor-pointer">Gift Cards</p>
            </div>
            <div className="space-y-2">
              <p className="hover:underline cursor-pointer">Media Center</p>
              <p className="hover:underline cursor-pointer">Investor Relations</p>
              <p className="hover:underline cursor-pointer">Jobs & Careers</p>
            </div>
            <div className="space-y-2">
              <p className="hover:underline cursor-pointer">Terms of Use</p>
              <p className="hover:underline cursor-pointer">Privacy Statement</p>
              <p className="hover:underline cursor-pointer">Legal Notices</p>
            </div>
            <div className="space-y-2">
              <p className="hover:underline cursor-pointer">Corporate Information</p>
              <p className="hover:underline cursor-pointer">Contact Animeflix</p>
              <p className="hover:underline cursor-pointer">Speed Test</p>
            </div>
          </div>

          <div className="pt-4 border-t border-gray-900 flex flex-col sm:flex-row items-center justify-between text-gray-600 gap-2">
            <p>© 2025 Animeflix, Inc. Built with React, Vite, Express & SQLite.</p>
            <p>Admin Key: <code className="text-gray-400">animeflix2025</code></p>
          </div>
        </div>
      </footer>

      {/* Anime Details Modal */}
      {selectedAnime && (
        <AnimeDetailsModal
          anime={selectedAnime}
          onClose={() => setSelectedAnime(null)}
          onPlay={handlePlayAnime}
          onToggleMyList={handleToggleMyList}
          isInMyList={Boolean(myListMap[selectedAnime.id])}
          onToggleLike={handleToggleLike}
          userLike={likesMap[selectedAnime.id] || 0}
          onSelectRecommendedAnime={(anime) => setSelectedAnime(anime)}
        />
      )}

      {/* Video Player Modal */}
      {playingAnime && (
        <VideoPlayerModal
          anime={playingAnime}
          initialEpisode={playingEpisode}
          onClose={() => {
            setPlayingAnime(null);
            setPlayingEpisode(null);
            // Refresh history
            fetch('/api/continue-watching').then(r => r.json()).then(d => {
              if (d.success) setWatchHistory(d.data);
            });
          }}
          onProgressUpdate={handleProgressUpdate}
        />
      )}

      {/* Admin Management Modal */}
      <AdminModal
        isOpen={isAdminModalOpen}
        onClose={() => setIsAdminModalOpen(false)}
        isAdminLoggedIn={isAdminLoggedIn}
        onLoginSuccess={() => setIsAdminLoggedIn(true)}
        onLogout={() => setIsAdminLoggedIn(false)}
        onDataChanged={fetchAllData}
        showToast={showToast}
      />

    </div>
  );
}
