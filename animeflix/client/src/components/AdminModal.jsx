import React, { useState, useEffect } from 'react';
import { 
  ShieldCheck, 
  Plus, 
  Edit3, 
  Trash2, 
  Layers, 
  Film, 
  BarChart3, 
  RefreshCw, 
  Search, 
  X, 
  Check, 
  AlertCircle, 
  Tv, 
  Play, 
  Lock, 
  LogOut,
  Sparkles,
  TrendingUp,
  Star,
  Users
} from 'lucide-react';

export default function AdminModal({
  isOpen,
  onClose,
  isAdminLoggedIn,
  onLoginSuccess,
  onLogout,
  onDataChanged,
  showToast
}) {
  const [password, setPassword] = useState('');
  const [loginError, setLoginError] = useState('');
  const [adminTab, setActiveTab] = useState('catalog'); // 'catalog' | 'add' | 'stats' | 'genres'
  
  // Data state
  const [animeList, setAnimeList] = useState([]);
  const [genresList, setGenresList] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(false);
  const [searchFilter, setSearchFilter] = useState('');

  // Editing state
  const [editingAnime, setEditingAnime] = useState(null);

  // Form state
  const initialForm = {
    title: '',
    japanese_title: '',
    synopsis: '',
    banner_image: '',
    poster_image: '',
    trailer_url: '',
    video_url: 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4',
    rating: 9.0,
    match_score: 97,
    release_year: 2024,
    age_rating: 'TV-MA',
    season_count: '1 Season',
    quality: '4K Ultra HD',
    audio_languages: 'Japanese [Original], English',
    subtitles: 'English, Spanish, French',
    studio: 'MAPPA',
    is_featured: false,
    is_trending: true,
    is_popular: true,
    top_10_rank: '',
    status: 'Ongoing',
    genres: []
  };

  const [formData, setFormData] = useState(initialForm);
  const [newGenreName, setNewGenreName] = useState('');

  // Fetch admin stats and catalog
  const fetchData = async () => {
    try {
      setLoading(true);
      const [animeRes, genresRes, statsRes] = await Promise.all([
        fetch('/api/anime'),
        fetch('/api/genres'),
        fetch('/api/stats')
      ]);

      const animeData = await animeRes.json();
      const genresData = await genresRes.json();
      const statsData = await statsRes.json();

      if (animeData.success) setAnimeList(animeData.data);
      if (genresData.success) setGenresList(genresData.data);
      if (statsData.success) setStats(statsData.data);
    } catch (err) {
      console.error('Error fetching admin data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen && isAdminLoggedIn) {
      fetchData();
    }
  }, [isOpen, isAdminLoggedIn]);

  if (!isOpen) return null;

  // Handle Admin Login
  const handleLogin = async (e) => {
    e.preventDefault();
    setLoginError('');
    try {
      const res = await fetch('/api/admin/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password })
      });
      const data = await res.json();
      if (data.success) {
        onLoginSuccess();
        setPassword('');
        fetchData();
        showToast('Admin mode activated successfully', 'success');
      } else {
        setLoginError(data.error || 'Invalid password. Try animeflix2025 or admin');
      }
    } catch (err) {
      setLoginError('Failed to connect to backend server');
    }
  };

  // Form input change
  const handleFormChange = (e) => {
    const { name, value, type, checked } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value
    }));
  };

  const handleGenreToggle = (genreSlug) => {
    setFormData(prev => {
      const current = prev.genres || [];
      if (current.includes(genreSlug)) {
        return { ...prev, genres: current.filter(g => g !== genreSlug) };
      } else {
        return { ...prev, genres: [...current, genreSlug] };
      }
    });
  };

  // Submit Add or Edit Anime
  const handleSaveAnime = async (e) => {
    e.preventDefault();
    try {
      if (!formData.title || !formData.banner_image || !formData.poster_image) {
        showToast('Title, Banner Image, and Poster Image are required!', 'error');
        return;
      }

      const isEdit = Boolean(editingAnime);
      const url = isEdit ? `/api/anime/${editingAnime.id}` : '/api/anime';
      const method = isEdit ? 'PUT' : 'POST';

      const payload = {
        ...formData,
        rating: parseFloat(formData.rating),
        match_score: parseInt(formData.match_score, 10),
        release_year: parseInt(formData.release_year, 10),
        top_10_rank: formData.top_10_rank ? parseInt(formData.top_10_rank, 10) : null
      };

      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      const data = await res.json();
      if (data.success) {
        showToast(isEdit ? 'Anime updated successfully!' : 'Anime added to catalog!', 'success');
        setFormData(initialForm);
        setEditingAnime(null);
        setActiveTab('catalog');
        fetchData();
        onDataChanged();
      } else {
        showToast(data.error || 'Operation failed', 'error');
      }
    } catch (err) {
      showToast('Error saving anime', 'error');
    }
  };

  // Delete Anime
  const handleDeleteAnime = async (id, title) => {
    if (!window.confirm(`Are you sure you want to delete "${title}"?`)) return;
    try {
      const res = await fetch(`/api/anime/${id}`, { method: 'DELETE' });
      const data = await res.json();
      if (data.success) {
        showToast(`"${title}" deleted successfully`, 'success');
        fetchData();
        onDataChanged();
      } else {
        showToast(data.error || 'Failed to delete', 'error');
      }
    } catch (err) {
      showToast('Error deleting anime', 'error');
    }
  };

  // Start Editing Anime
  const startEditAnime = (anime) => {
    setEditingAnime(anime);
    setFormData({
      title: anime.title || '',
      japanese_title: anime.japanese_title || '',
      synopsis: anime.synopsis || '',
      banner_image: anime.banner_image || '',
      poster_image: anime.poster_image || '',
      trailer_url: anime.trailer_url || '',
      video_url: anime.video_url || '',
      rating: anime.rating || 9.0,
      match_score: anime.match_score || 95,
      release_year: anime.release_year || 2024,
      age_rating: anime.age_rating || 'TV-MA',
      season_count: anime.season_count || '1 Season',
      quality: anime.quality || '4K Ultra HD',
      audio_languages: anime.audio_languages || 'Japanese [Original], English',
      subtitles: anime.subtitles || 'English, Spanish',
      studio: anime.studio || 'MAPPA',
      is_featured: Boolean(anime.is_featured),
      is_trending: Boolean(anime.is_trending),
      is_popular: Boolean(anime.is_popular),
      top_10_rank: anime.top_10_rank || '',
      status: anime.status || 'Ongoing',
      genres: anime.genres ? anime.genres.map(g => g.slug || g.name || g) : []
    });
    setActiveTab('add');
  };

  // Add new genre
  const handleAddGenre = async (e) => {
    e.preventDefault();
    if (!newGenreName.trim()) return;
    try {
      const res = await fetch('/api/genres', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newGenreName })
      });
      const data = await res.json();
      if (data.success) {
        showToast(`Genre "${newGenreName}" added`, 'success');
        setNewGenreName('');
        fetchData();
        onDataChanged();
      }
    } catch (err) {
      showToast('Error creating genre', 'error');
    }
  };

  // Reset / Reseed Database
  const handleReseed = async () => {
    if (!window.confirm('Reset catalog and reseed with default high-definition anime database?')) return;
    try {
      setLoading(true);
      const res = await fetch('/api/seed/reset', { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        showToast('Database reset and re-seeded!', 'success');
        fetchData();
        onDataChanged();
      }
    } catch (err) {
      showToast('Failed to reseed database', 'error');
    } finally {
      setLoading(false);
    }
  };

  const filteredAnime = animeList.filter(a => 
    a.title.toLowerCase().includes(searchFilter.toLowerCase()) ||
    (a.studio && a.studio.toLowerCase().includes(searchFilter.toLowerCase()))
  );

  return (
    <div className="fixed inset-0 z-[100] bg-black/85 backdrop-blur-md flex items-center justify-center p-3 sm:p-6 overflow-y-auto">
      <div 
        className="relative bg-[#181818] rounded-2xl max-w-5xl w-full text-white shadow-2xl overflow-hidden border border-gray-800 my-auto flex flex-col max-h-[92vh] animate-fade-in"
        onClick={(e) => e.stopPropagation()}
      >
        
        {/* Header */}
        <div className="p-4 sm:p-6 bg-[#1f1f1f] border-b border-gray-800 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-[#E50914]/20 border border-[#E50914]/40 flex items-center justify-center text-[#E50914]">
              <ShieldCheck className="w-6 h-6" />
            </div>
            <div>
              <h2 className="text-base sm:text-lg font-bold text-white flex items-center gap-2">
                <span>Animeflix Studio Admin Portal</span>
                <span className="text-xs font-semibold px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/40">
                  Live SQLite DB
                </span>
              </h2>
              <p className="text-xs text-gray-400">
                Full CRUD Anime Content Management, Categorization & Metrics
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {isAdminLoggedIn && (
              <button
                onClick={() => { onLogout(); showToast('Logged out of Admin', 'info'); }}
                className="p-2 rounded-lg bg-white/5 hover:bg-white/10 text-gray-400 hover:text-white transition-colors"
                title="Log Out Admin"
              >
                <LogOut className="w-5 h-5" />
              </button>
            )}
            <button
              onClick={onClose}
              className="p-2 rounded-lg bg-white/5 hover:bg-white/10 text-gray-400 hover:text-white transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Not Logged In View */}
        {!isAdminLoggedIn ? (
          <div className="p-8 sm:p-12 flex flex-col items-center justify-center text-center max-w-md mx-auto my-auto space-y-6">
            <div className="w-16 h-16 rounded-full bg-white/5 flex items-center justify-center text-[#E50914]">
              <Lock className="w-8 h-8" />
            </div>
            <div>
              <h3 className="text-xl font-bold text-white">Admin Authentication</h3>
              <p className="text-xs sm:text-sm text-gray-400 mt-1">
                Enter your administrative key to manage titles, edit banners, stream URLs, and top 10 rankings.
              </p>
            </div>

            <form onSubmit={handleLogin} className="w-full space-y-3">
              <input
                type="password"
                placeholder="Enter admin key (default: animeflix2025 or admin)"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-[#121212] border border-gray-700 rounded-lg px-4 py-3 text-sm text-white focus:outline-none focus:border-[#E50914] transition-colors"
                autoFocus
              />

              {loginError && (
                <div className="text-xs text-red-400 flex items-center gap-1.5 justify-center">
                  <AlertCircle className="w-3.5 h-3.5" />
                  <span>{loginError}</span>
                </div>
              )}

              <button
                type="submit"
                className="w-full py-3 rounded-lg bg-[#E50914] text-white font-bold text-sm hover:bg-[#b80710] transition-colors shadow-lg shadow-red-900/40 cursor-pointer"
              >
                Access Control Panel
              </button>
            </form>

            <div className="text-[11px] text-gray-500 bg-white/5 p-3 rounded border border-gray-800">
              💡 Tip: Default password is <code className="text-gray-300 font-bold">animeflix2025</code> or <code className="text-gray-300 font-bold">admin</code>
            </div>
          </div>
        ) : (
          /* Admin Main Portal Content */
          <div className="flex-1 flex flex-col overflow-hidden">
            
            {/* Admin Tabs */}
            <div className="px-6 bg-[#181818] border-b border-gray-800 flex items-center justify-between">
              <div className="flex items-center gap-4 text-xs font-bold">
                <button
                  onClick={() => setActiveTab('catalog')}
                  className={`py-3.5 flex items-center gap-1.5 border-b-2 transition-all ${
                    adminTab === 'catalog' ? 'border-[#E50914] text-white' : 'border-transparent text-gray-400 hover:text-white'
                  }`}
                >
                  <Film className="w-4 h-4" />
                  <span>Anime Catalog ({animeList.length})</span>
                </button>

                <button
                  onClick={() => {
                    setEditingAnime(null);
                    setFormData(initialForm);
                    setActiveTab('add');
                  }}
                  className={`py-3.5 flex items-center gap-1.5 border-b-2 transition-all ${
                    adminTab === 'add' ? 'border-[#E50914] text-white' : 'border-transparent text-gray-400 hover:text-white'
                  }`}
                >
                  <Plus className="w-4 h-4" />
                  <span>{editingAnime ? 'Edit Anime' : 'Add New Anime'}</span>
                </button>

                <button
                  onClick={() => setActiveTab('stats')}
                  className={`py-3.5 flex items-center gap-1.5 border-b-2 transition-all ${
                    adminTab === 'stats' ? 'border-[#E50914] text-white' : 'border-transparent text-gray-400 hover:text-white'
                  }`}
                >
                  <BarChart3 className="w-4 h-4" />
                  <span>Analytics & Stats</span>
                </button>

                <button
                  onClick={() => setActiveTab('genres')}
                  className={`py-3.5 flex items-center gap-1.5 border-b-2 transition-all ${
                    adminTab === 'genres' ? 'border-[#E50914] text-white' : 'border-transparent text-gray-400 hover:text-white'
                  }`}
                >
                  <Layers className="w-4 h-4" />
                  <span>Genres & Categories</span>
                </button>
              </div>

              {/* Reset Catalog Button */}
              <button
                onClick={handleReseed}
                className="text-xs font-medium text-gray-400 hover:text-amber-400 flex items-center gap-1 transition-colors"
                title="Reseed standard demo data"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">Reseed DB</span>
              </button>
            </div>

            {/* Tab View Container */}
            <div className="flex-1 overflow-y-auto p-4 sm:p-6">
              
              {/* TAB 1: Catalog List */}
              {adminTab === 'catalog' && (
                <div className="space-y-4">
                  
                  {/* Search and action bar */}
                  <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
                    <div className="relative w-full sm:w-72">
                      <Search className="w-4 h-4 absolute left-3 top-2.5 text-gray-400" />
                      <input
                        type="text"
                        placeholder="Search anime catalog..."
                        value={searchFilter}
                        onChange={(e) => setSearchFilter(e.target.value)}
                        className="w-full bg-[#121212] border border-gray-700 rounded-lg pl-9 pr-3 py-2 text-xs text-white focus:outline-none focus:border-[#E50914]"
                      />
                    </div>

                    <button
                      onClick={() => {
                        setEditingAnime(null);
                        setFormData(initialForm);
                        setActiveTab('add');
                      }}
                      className="w-full sm:w-auto flex items-center justify-center gap-1.5 px-4 py-2 rounded-lg bg-[#E50914] text-white text-xs font-bold hover:bg-[#b80710] transition-colors"
                    >
                      <Plus className="w-4 h-4" />
                      <span>Add New Anime</span>
                    </button>
                  </div>

                  {/* Table of Anime */}
                  <div className="border border-gray-800 rounded-xl overflow-hidden bg-[#141414]">
                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-xs">
                        <thead className="bg-[#202020] text-gray-400 font-bold border-b border-gray-800 uppercase tracking-wider">
                          <tr>
                            <th className="p-3">Poster</th>
                            <th className="p-3">Title / Japanese</th>
                            <th className="p-3">Rating / Match</th>
                            <th className="p-3">Flags</th>
                            <th className="p-3">Studio / Year</th>
                            <th className="p-3 text-right">Actions</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-800">
                          {filteredAnime.map((anime) => (
                            <tr key={anime.id} className="hover:bg-white/5 transition-colors">
                              <td className="p-3">
                                <img
                                  src={anime.poster_image}
                                  alt={anime.title}
                                  className="w-10 h-14 object-cover rounded shadow"
                                />
                              </td>
                              <td className="p-3">
                                <p className="font-bold text-white text-sm">{anime.title}</p>
                                <p className="text-[11px] text-gray-400 line-clamp-1">{anime.japanese_title || anime.synopsis}</p>
                              </td>
                              <td className="p-3 font-semibold">
                                <span className="text-amber-400 flex items-center gap-1">
                                  <Star className="w-3 h-3 fill-current" />
                                  {anime.rating}
                                </span>
                                <span className="text-emerald-400 text-[11px] block">{anime.match_score}% Match</span>
                              </td>
                              <td className="p-3">
                                <div className="flex flex-wrap gap-1">
                                  {anime.is_featured ? <span className="bg-purple-500/20 text-purple-300 px-1.5 py-0.5 rounded text-[10px] font-bold">Featured</span> : null}
                                  {anime.is_trending ? <span className="bg-red-500/20 text-red-300 px-1.5 py-0.5 rounded text-[10px] font-bold">Trending</span> : null}
                                  {anime.top_10_rank ? <span className="bg-amber-500/20 text-amber-300 px-1.5 py-0.5 rounded text-[10px] font-bold">Top #{anime.top_10_rank}</span> : null}
                                </div>
                              </td>
                              <td className="p-3 text-gray-300">
                                <div>{anime.studio || 'MAPPA'}</div>
                                <div className="text-[11px] text-gray-400">{anime.release_year} • {anime.season_count}</div>
                              </td>
                              <td className="p-3 text-right space-x-2">
                                <button
                                  onClick={() => startEditAnime(anime)}
                                  className="p-1.5 rounded bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 transition-colors"
                                  title="Edit"
                                >
                                  <Edit3 className="w-4 h-4" />
                                </button>
                                <button
                                  onClick={() => handleDeleteAnime(anime.id, anime.title)}
                                  className="p-1.5 rounded bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
                                  title="Delete"
                                >
                                  <Trash2 className="w-4 h-4" />
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              )}

              {/* TAB 2: Add / Edit Anime Form */}
              {adminTab === 'add' && (
                <form onSubmit={handleSaveAnime} className="space-y-6 max-w-3xl mx-auto">
                  <div className="flex items-center justify-between border-b border-gray-800 pb-3">
                    <h3 className="text-base font-bold text-white">
                      {editingAnime ? `Editing: ${editingAnime.title}` : 'Add New Anime to Netflix Catalog'}
                    </h3>
                    {editingAnime && (
                      <button
                        type="button"
                        onClick={() => { setEditingAnime(null); setFormData(initialForm); }}
                        className="text-xs text-gray-400 hover:text-white"
                      >
                        Cancel Editing
                      </button>
                    )}
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-xs font-bold text-gray-300 mb-1">Anime Title *</label>
                      <input
                        type="text"
                        name="title"
                        required
                        value={formData.title}
                        onChange={handleFormChange}
                        placeholder="e.g. Solo Leveling"
                        className="w-full bg-[#121212] border border-gray-700 rounded-lg px-3 py-2 text-xs text-white focus:border-[#E50914]"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-bold text-gray-300 mb-1">Japanese Title</label>
                      <input
                        type="text"
                        name="japanese_title"
                        value={formData.japanese_title}
                        onChange={handleFormChange}
                        placeholder="e.g. 俺だけレベルアップな件"
                        className="w-full bg-[#121212] border border-gray-700 rounded-lg px-3 py-2 text-xs text-white focus:border-[#E50914]"
                      />
                    </div>

                    <div className="sm:col-span-2">
                      <label className="block text-xs font-bold text-gray-300 mb-1">Synopsis / Storyline</label>
                      <textarea
                        rows={3}
                        name="synopsis"
                        value={formData.synopsis}
                        onChange={handleFormChange}
                        placeholder="Detailed synopsis of the anime..."
                        className="w-full bg-[#121212] border border-gray-700 rounded-lg px-3 py-2 text-xs text-white focus:border-[#E50914]"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-bold text-gray-300 mb-1">Banner Image URL (1920x1080) *</label>
                      <input
                        type="url"
                        name="banner_image"
                        required
                        value={formData.banner_image}
                        onChange={handleFormChange}
                        placeholder="https://images.unsplash.com/..."
                        className="w-full bg-[#121212] border border-gray-700 rounded-lg px-3 py-2 text-xs text-white focus:border-[#E50914]"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-bold text-gray-300 mb-1">Poster Image URL (600x900) *</label>
                      <input
                        type="url"
                        name="poster_image"
                        required
                        value={formData.poster_image}
                        onChange={handleFormChange}
                        placeholder="https://images.unsplash.com/..."
                        className="w-full bg-[#121212] border border-gray-700 rounded-lg px-3 py-2 text-xs text-white focus:border-[#E50914]"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-bold text-gray-300 mb-1">Video Stream MP4 URL</label>
                      <input
                        type="url"
                        name="video_url"
                        value={formData.video_url}
                        onChange={handleFormChange}
                        placeholder="https://.../video.mp4"
                        className="w-full bg-[#121212] border border-gray-700 rounded-lg px-3 py-2 text-xs text-white focus:border-[#E50914]"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-bold text-gray-300 mb-1">Trailer YouTube URL</label>
                      <input
                        type="url"
                        name="trailer_url"
                        value={formData.trailer_url}
                        onChange={handleFormChange}
                        placeholder="https://youtube.com/watch?v=..."
                        className="w-full bg-[#121212] border border-gray-700 rounded-lg px-3 py-2 text-xs text-white focus:border-[#E50914]"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-bold text-gray-300 mb-1">Animation Studio</label>
                      <input
                        type="text"
                        name="studio"
                        value={formData.studio}
                        onChange={handleFormChange}
                        placeholder="MAPPA, Ufotable, Bones..."
                        className="w-full bg-[#121212] border border-gray-700 rounded-lg px-3 py-2 text-xs text-white focus:border-[#E50914]"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-bold text-gray-300 mb-1">Release Year</label>
                      <input
                        type="number"
                        name="release_year"
                        value={formData.release_year}
                        onChange={handleFormChange}
                        className="w-full bg-[#121212] border border-gray-700 rounded-lg px-3 py-2 text-xs text-white focus:border-[#E50914]"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-bold text-gray-300 mb-1">Rating (1-10)</label>
                      <input
                        type="number"
                        step="0.1"
                        name="rating"
                        value={formData.rating}
                        onChange={handleFormChange}
                        className="w-full bg-[#121212] border border-gray-700 rounded-lg px-3 py-2 text-xs text-white focus:border-[#E50914]"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-bold text-gray-300 mb-1">Match Score %</label>
                      <input
                        type="number"
                        name="match_score"
                        value={formData.match_score}
                        onChange={handleFormChange}
                        className="w-full bg-[#121212] border border-gray-700 rounded-lg px-3 py-2 text-xs text-white focus:border-[#E50914]"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-bold text-gray-300 mb-1">Age Rating</label>
                      <select
                        name="age_rating"
                        value={formData.age_rating}
                        onChange={handleFormChange}
                        className="w-full bg-[#121212] border border-gray-700 rounded-lg px-3 py-2 text-xs text-white focus:border-[#E50914]"
                      >
                        <option value="TV-PG">TV-PG</option>
                        <option value="TV-14">TV-14</option>
                        <option value="TV-MA">TV-MA</option>
                        <option value="18+">18+</option>
                      </select>
                    </div>

                    <div>
                      <label className="block text-xs font-bold text-gray-300 mb-1">Season Count</label>
                      <input
                        type="text"
                        name="season_count"
                        value={formData.season_count}
                        onChange={handleFormChange}
                        placeholder="e.g. 2 Seasons"
                        className="w-full bg-[#121212] border border-gray-700 rounded-lg px-3 py-2 text-xs text-white focus:border-[#E50914]"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-bold text-gray-300 mb-1">Top 10 Ranking (1-10 or empty)</label>
                      <input
                        type="number"
                        min="1"
                        max="10"
                        name="top_10_rank"
                        value={formData.top_10_rank}
                        onChange={handleFormChange}
                        placeholder="e.g. 1"
                        className="w-full bg-[#121212] border border-gray-700 rounded-lg px-3 py-2 text-xs text-white focus:border-[#E50914]"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-bold text-gray-300 mb-1">Quality Badge</label>
                      <select
                        name="quality"
                        value={formData.quality}
                        onChange={handleFormChange}
                        className="w-full bg-[#121212] border border-gray-700 rounded-lg px-3 py-2 text-xs text-white focus:border-[#E50914]"
                      >
                        <option value="4K Ultra HD">4K Ultra HD</option>
                        <option value="HD">HD</option>
                        <option value="Dolby Vision">Dolby Vision</option>
                      </select>
                    </div>

                  </div>

                  {/* Genres Selection */}
                  <div>
                    <label className="block text-xs font-bold text-gray-300 mb-2">Genres</label>
                    <div className="flex flex-wrap gap-2">
                      {genresList.map((g) => {
                        const isSelected = formData.genres.includes(g.slug) || formData.genres.includes(g.name);
                        return (
                          <button
                            key={g.id}
                            type="button"
                            onClick={() => handleGenreToggle(g.slug)}
                            className={`px-3 py-1 rounded-full text-xs font-medium border transition-all ${
                              isSelected ? 'bg-[#E50914] text-white border-[#E50914]' : 'bg-black/40 text-gray-400 border-gray-700 hover:border-gray-500'
                            }`}
                          >
                            {g.name}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Feature Flags */}
                  <div className="p-4 rounded-xl bg-white/5 border border-gray-800 space-y-3">
                    <h4 className="text-xs font-bold text-white uppercase tracking-wider">Showcase Positioning</h4>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                      <label className="flex items-center gap-2 text-xs text-gray-300 cursor-pointer">
                        <input
                          type="checkbox"
                          name="is_featured"
                          checked={formData.is_featured}
                          onChange={handleFormChange}
                          className="accent-[#E50914] w-4 h-4 rounded"
                        />
                        <span>Main Hero Billboard</span>
                      </label>

                      <label className="flex items-center gap-2 text-xs text-gray-300 cursor-pointer">
                        <input
                          type="checkbox"
                          name="is_trending"
                          checked={formData.is_trending}
                          onChange={handleFormChange}
                          className="accent-[#E50914] w-4 h-4 rounded"
                        />
                        <span>Trending Row</span>
                      </label>

                      <label className="flex items-center gap-2 text-xs text-gray-300 cursor-pointer">
                        <input
                          type="checkbox"
                          name="is_popular"
                          checked={formData.is_popular}
                          onChange={handleFormChange}
                          className="accent-[#E50914] w-4 h-4 rounded"
                        />
                        <span>Popular Row</span>
                      </label>
                    </div>
                  </div>

                  {/* Submit Button */}
                  <div className="flex justify-end gap-3 pt-4">
                    <button
                      type="button"
                      onClick={() => { setActiveTab('catalog'); setEditingAnime(null); }}
                      className="px-5 py-2.5 rounded-lg border border-gray-700 text-gray-300 text-xs font-semibold hover:bg-white/5 transition-colors"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      className="px-6 py-2.5 rounded-lg bg-[#E50914] text-white text-xs font-bold hover:bg-[#b80710] shadow-lg transition-colors cursor-pointer"
                    >
                      {editingAnime ? 'Save Changes' : 'Publish Anime'}
                    </button>
                  </div>
                </form>
              )}

              {/* TAB 3: Analytics & Stats */}
              {adminTab === 'stats' && stats && (
                <div className="space-y-6">
                  {/* Summary Metric Cards */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                    <div className="p-4 rounded-xl bg-[#202020] border border-gray-800 space-y-1">
                      <p className="text-xs text-gray-400 font-medium">Total Titles</p>
                      <p className="text-2xl font-black text-white">{stats.totalAnime}</p>
                      <p className="text-[10px] text-emerald-400 font-semibold">Active in library</p>
                    </div>

                    <div className="p-4 rounded-xl bg-[#202020] border border-gray-800 space-y-1">
                      <p className="text-xs text-gray-400 font-medium">Total Episodes</p>
                      <p className="text-2xl font-black text-white">{stats.totalEpisodes}</p>
                      <p className="text-[10px] text-blue-400 font-semibold">Ready to stream</p>
                    </div>

                    <div className="p-4 rounded-xl bg-[#202020] border border-gray-800 space-y-1">
                      <p className="text-xs text-gray-400 font-medium">My List Saves</p>
                      <p className="text-2xl font-black text-white">{stats.totalMyListSaves}</p>
                      <p className="text-[10px] text-purple-400 font-semibold">User bookmarks</p>
                    </div>

                    <div className="p-4 rounded-xl bg-[#202020] border border-gray-800 space-y-1">
                      <p className="text-xs text-gray-400 font-medium">Platform Views</p>
                      <p className="text-2xl font-black text-white">{stats.totalViews.toLocaleString()}</p>
                      <p className="text-[10px] text-amber-400 font-semibold">+14.2% this month</p>
                    </div>
                  </div>

                  {/* Top Rated and Genre Distribution */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div className="p-4 rounded-xl bg-[#141414] border border-gray-800 space-y-3">
                      <h4 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
                        <TrendingUp className="w-4 h-4 text-emerald-400" />
                        <span>Highest Rated Anime</span>
                      </h4>
                      <div className="divide-y divide-gray-800">
                        {stats.topRated.map((anime, i) => (
                          <div key={anime.id} className="py-2.5 flex items-center justify-between">
                            <div className="flex items-center gap-3">
                              <span className="font-bold text-gray-500 text-sm">#{i + 1}</span>
                              <img src={anime.poster_image} alt={anime.title} className="w-8 h-11 object-cover rounded shadow" />
                              <div>
                                <p className="text-xs font-bold text-white">{anime.title}</p>
                                <p className="text-[10px] text-gray-400">{anime.release_year}</p>
                              </div>
                            </div>
                            <span className="text-amber-400 font-bold text-xs flex items-center gap-1">
                              <Star className="w-3.5 h-3.5 fill-current" />
                              {anime.rating}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>

                    <div className="p-4 rounded-xl bg-[#141414] border border-gray-800 space-y-3">
                      <h4 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
                        <Layers className="w-4 h-4 text-[#E50914]" />
                        <span>Genre Distribution</span>
                      </h4>
                      <div className="space-y-2.5">
                        {stats.genreCounts.slice(0, 7).map((gc) => (
                          <div key={gc.name} className="space-y-1">
                            <div className="flex justify-between text-xs font-semibold">
                              <span className="text-gray-300">{gc.name}</span>
                              <span className="text-gray-400">{gc.count} titles</span>
                            </div>
                            <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden">
                              <div 
                                className="h-full bg-[#E50914] rounded-full"
                                style={{ width: `${Math.min(100, (gc.count / stats.totalAnime) * 100)}%` }}
                              />
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* TAB 4: Genres Management */}
              {adminTab === 'genres' && (
                <div className="space-y-6 max-w-2xl mx-auto">
                  <form onSubmit={handleAddGenre} className="flex gap-2">
                    <input
                      type="text"
                      placeholder="Add new genre (e.g. Mecha, Isekai, Thriller)..."
                      value={newGenreName}
                      onChange={(e) => setNewGenreName(e.target.value)}
                      className="flex-1 bg-[#121212] border border-gray-700 rounded-lg px-3 py-2 text-xs text-white focus:border-[#E50914]"
                    />
                    <button
                      type="submit"
                      className="px-4 py-2 rounded-lg bg-[#E50914] text-white font-bold text-xs hover:bg-[#b80710]"
                    >
                      Add Genre
                    </button>
                  </form>

                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                    {genresList.map((g) => (
                      <div key={g.id} className="p-3 rounded-lg bg-[#202020] border border-gray-800 flex items-center justify-between">
                        <div>
                          <p className="text-xs font-bold text-white">{g.name}</p>
                          <p className="text-[10px] text-gray-400">{g.anime_count || 0} associated titles</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

            </div>
          </div>
        )}

      </div>
    </div>
  );
}
