import React, { useState, useEffect } from 'react';
import { 
  X, 
  Play, 
  Plus, 
  Check, 
  ThumbsUp, 
  Star, 
  Sparkles, 
  Volume2, 
  Film, 
  Calendar, 
  Layers, 
  Tv, 
  CheckCircle2 
} from 'lucide-react';

export default function AnimeDetailsModal({
  anime,
  onClose,
  onPlay,
  onToggleMyList,
  isInMyList,
  onToggleLike,
  userLike,
  onSelectRecommendedAnime
}) {
  const [activeTab, setActiveTab] = useState('episodes'); // 'episodes' | 'more' | 'about'
  const [recommendations, setRecommendations] = useState([]);
  const [loadingRecs, setLoadingRecs] = useState(false);

  useEffect(() => {
    if (!anime) return;
    // Fetch full anime details with recommendations
    const fetchDetails = async () => {
      try {
        setLoadingRecs(true);
        const res = await fetch(`/api/anime/${anime.id}`);
        const data = await res.json();
        if (data.success && data.data.recommendations) {
          setRecommendations(data.data.recommendations);
        }
      } catch (err) {
        console.error('Error fetching details:', err);
      } finally {
        setLoadingRecs(false);
      }
    };
    fetchDetails();
  }, [anime]);

  if (!anime) return null;

  const episodes = (anime.episodes && anime.episodes.length > 0) ? anime.episodes : [
    {
      id: 1,
      episode_number: 1,
      title: 'Episode 1: The Beginning',
      duration: '24m',
      description: anime.synopsis || 'The adventure begins.'
    }
  ];

  return (
    <div className="fixed inset-0 z-[90] bg-black/80 backdrop-blur-sm flex items-center justify-center p-2 sm:p-4 md:p-6 overflow-y-auto">
      <div 
        className="relative bg-[#181818] rounded-xl max-w-4xl w-full text-white shadow-2xl overflow-hidden border border-gray-800 my-auto animate-fade-in"
        onClick={(e) => e.stopPropagation()}
      >
        
        {/* Close Button */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 z-50 w-9 h-9 rounded-full bg-[#181818]/80 hover:bg-white/20 text-white flex items-center justify-center backdrop-blur-md transition-colors"
        >
          <X className="w-5 h-5" />
        </button>

        {/* Hero Backdrop Banner */}
        <div className="relative aspect-[16/9] sm:aspect-[21/9] w-full overflow-hidden">
          <img
            src={anime.banner_image || anime.poster_image}
            alt={anime.title}
            className="w-full h-full object-cover filter brightness-[0.85]"
          />
          <div className="absolute inset-0 bg-gradient-to-t from-[#181818] via-[#181818]/40 to-transparent" />

          {/* Banner Content Overlay */}
          <div className="absolute bottom-6 inset-x-6 sm:inset-x-8 flex flex-col justify-end">
            <div className="flex items-center gap-2 mb-2">
              <span className="bg-[#E50914] text-white text-[10px] font-black px-2 py-0.5 rounded tracking-wider uppercase">
                {anime.quality || '4K Ultra HD'}
              </span>
              <span className="text-xs text-gray-300 font-semibold bg-black/50 px-2 py-0.5 rounded border border-gray-700">
                {anime.studio || 'MAPPA'}
              </span>
            </div>

            <h1 className="text-2xl sm:text-4xl font-black text-white drop-shadow-md">
              {anime.title}
            </h1>
            {anime.japanese_title && (
              <p className="text-xs sm:text-sm text-gray-300 font-medium">{anime.japanese_title}</p>
            )}

            {/* Quick Action Buttons */}
            <div className="flex items-center gap-3 mt-4">
              <button
                onClick={() => onPlay(anime, episodes[0])}
                className="flex items-center gap-2 px-6 py-2.5 rounded bg-white text-black font-bold text-sm hover:bg-white/90 active:scale-95 transition-all shadow-lg"
              >
                <Play className="w-4 h-4 fill-current ml-0.5" />
                <span>Play</span>
              </button>

              <button
                onClick={() => onToggleMyList(anime.id)}
                className={`p-2.5 rounded-full border transition-all active:scale-95 ${
                  isInMyList ? 'bg-white text-black border-white' : 'border-gray-400 bg-black/40 text-white hover:border-white'
                }`}
                title={isInMyList ? 'Remove from My List' : 'Add to My List'}
              >
                {isInMyList ? <Check className="w-4 h-4" /> : <Plus className="w-4 h-4" />}
              </button>

              <button
                onClick={() => onToggleLike(anime.id, userLike === 1 ? 0 : 1)}
                className={`p-2.5 rounded-full border transition-all active:scale-95 ${
                  userLike === 1 ? 'border-emerald-500 text-emerald-400 bg-emerald-500/20' : 'border-gray-400 bg-black/40 text-white hover:border-white'
                }`}
                title="Like"
              >
                <ThumbsUp className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>

        {/* Modal Body */}
        <div className="p-6 sm:p-8 space-y-6">
          
          {/* Metadata Grid */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 pb-6 border-b border-gray-800">
            
            {/* Left 2 Cols: Synopsis & Tags */}
            <div className="md:col-span-2 space-y-3">
              <div className="flex flex-wrap items-center gap-3 text-xs sm:text-sm font-semibold">
                <span className="text-emerald-400 font-bold">{anime.match_score || 98}% Match</span>
                <span className="text-gray-400">{anime.release_year || 2024}</span>
                <span className="border border-gray-600 px-1.5 py-0.5 rounded text-[11px]">{anime.age_rating || 'TV-MA'}</span>
                <span className="border border-gray-600 px-1.5 py-0.5 rounded text-[11px]">{anime.season_count || '1 Season'}</span>
                <span className="flex items-center gap-1 text-amber-400">
                  <Star className="w-3.5 h-3.5 fill-current" />
                  {anime.rating || 9.0} / 10
                </span>
              </div>

              <p className="text-sm text-gray-200 leading-relaxed">
                {anime.synopsis}
              </p>
            </div>

            {/* Right 1 Col: Key Info Card */}
            <div className="bg-white/5 rounded-lg p-4 space-y-2 text-xs border border-gray-800">
              <div>
                <span className="text-gray-400">Studio: </span>
                <span className="text-white font-semibold">{anime.studio || 'MAPPA'}</span>
              </div>
              <div>
                <span className="text-gray-400">Audio: </span>
                <span className="text-white font-semibold">{anime.audio_languages || 'Japanese, English'}</span>
              </div>
              <div>
                <span className="text-gray-400">Subtitles: </span>
                <span className="text-white font-semibold">{anime.subtitles || 'English, Spanish'}</span>
              </div>
              <div>
                <span className="text-gray-400">Genres: </span>
                <div className="flex flex-wrap gap-1.5 mt-1">
                  {anime.genres && anime.genres.map(g => (
                    <span key={g.id || g.slug || g} className="bg-white/10 px-2 py-0.5 rounded text-[11px] text-gray-200">
                      {g.name || g}
                    </span>
                  ))}
                </div>
              </div>
            </div>

          </div>

          {/* Navigation Tabs */}
          <div className="flex items-center gap-6 border-b border-gray-800 text-sm font-bold">
            <button
              onClick={() => setActiveTab('episodes')}
              className={`pb-3 transition-colors relative ${activeTab === 'episodes' ? 'text-white' : 'text-gray-400 hover:text-white'}`}
            >
              <span>Episodes ({episodes.length})</span>
              {activeTab === 'episodes' && (
                <div className="absolute bottom-0 inset-x-0 h-0.5 bg-[#E50914]" />
              )}
            </button>

            <button
              onClick={() => setActiveTab('more')}
              className={`pb-3 transition-colors relative ${activeTab === 'more' ? 'text-white' : 'text-gray-400 hover:text-white'}`}
            >
              <span>More Like This</span>
              {activeTab === 'more' && (
                <div className="absolute bottom-0 inset-x-0 h-0.5 bg-[#E50914]" />
              )}
            </button>
          </div>

          {/* Tab 1: Episodes List */}
          {activeTab === 'episodes' && (
            <div className="space-y-3">
              {episodes.map((ep, idx) => (
                <div
                  key={ep.id || idx}
                  onClick={() => onPlay(anime, ep)}
                  className="p-3 sm:p-4 rounded-lg bg-[#202020] hover:bg-[#282828] border border-gray-800 flex items-center gap-4 cursor-pointer transition-all group"
                >
                  <span className="text-base sm:text-lg font-black text-gray-500 group-hover:text-white w-6 text-center">
                    {ep.episode_number || idx + 1}
                  </span>

                  <div className="w-24 sm:w-32 aspect-video bg-black rounded overflow-hidden relative shrink-0">
                    <img
                      src={ep.thumbnail || anime.banner_image || anime.poster_image}
                      alt={ep.title}
                      className="w-full h-full object-cover"
                    />
                    <div className="absolute inset-0 bg-black/40 group-hover:bg-black/10 transition-colors flex items-center justify-center">
                      <div className="w-7 h-7 rounded-full bg-white/80 group-hover:bg-[#E50914] text-black group-hover:text-white flex items-center justify-center shadow transition-all">
                        <Play className="w-3.5 h-3.5 fill-current ml-0.5" />
                      </div>
                    </div>
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-2">
                      <h4 className="text-xs sm:text-sm font-bold text-white group-hover:text-[#E50914] truncate transition-colors">
                        {ep.title}
                      </h4>
                      <span className="text-xs text-gray-400 shrink-0 font-medium">
                        {ep.duration || '24m'}
                      </span>
                    </div>
                    <p className="text-xs text-gray-400 line-clamp-2 mt-1 leading-relaxed">
                      {ep.description || `Episode ${ep.episode_number || idx + 1} of ${anime.title}.`}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Tab 2: More Like This (Recommendations) */}
          {activeTab === 'more' && (
            <div>
              {recommendations.length > 0 ? (
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
                  {recommendations.map((rec) => (
                    <div
                      key={rec.id}
                      onClick={() => onSelectRecommendedAnime(rec)}
                      className="bg-[#202020] rounded-lg overflow-hidden border border-gray-800 hover:border-gray-600 transition-all cursor-pointer group"
                    >
                      <div className="aspect-video relative overflow-hidden">
                        <img
                          src={rec.banner_image || rec.poster_image}
                          alt={rec.title}
                          className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                        />
                        <div className="absolute top-2 right-2 bg-black/70 px-1.5 py-0.5 rounded text-[10px] font-bold text-gray-200">
                          {rec.quality || 'HD'}
                        </div>
                      </div>
                      <div className="p-3 space-y-2">
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-emerald-400 font-bold">{rec.match_score}% Match</span>
                          <span className="text-gray-400">{rec.release_year}</span>
                        </div>
                        <h4 className="text-xs font-bold text-white truncate">{rec.title}</h4>
                        <p className="text-[11px] text-gray-400 line-clamp-2">{rec.synopsis}</p>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-10 text-gray-400 text-sm">
                  {loadingRecs ? 'Finding recommendations...' : 'No similar anime recommendations found.'}
                </div>
              )}
            </div>
          )}

        </div>

      </div>
    </div>
  );
}
