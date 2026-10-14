import React, { useState } from 'react';
import { Play, Plus, Check, ThumbsUp, ChevronDown, Star } from 'lucide-react';

export default function AnimeCard({
  anime,
  onPlay,
  onOpenDetails,
  onToggleMyList,
  isInMyList,
  onToggleLike,
  userLike,
  isTop10 = false,
  rank = 1,
  showProgress = false
}) {
  const [isHovered, setIsHovered] = useState(false);

  if (!anime) return null;

  const genresDisplay = anime.genres && anime.genres.length > 0 
    ? anime.genres.slice(0, 3).map(g => g.name || g).join(' • ')
    : 'Anime • Action';

  return (
    <div 
      className="relative shrink-0 group transition-all duration-300"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {/* Top 10 Stylized Number Display */}
      {isTop10 && (
        <div className="flex items-end">
          <span className="top10-number -mr-4 z-10 select-none">
            {rank}
          </span>
        </div>
      )}

      {/* Main Poster Card */}
      <div 
        onClick={() => onOpenDetails(anime)}
        className="cursor-pointer relative rounded-md overflow-hidden bg-[#202020] aspect-[16/9] w-48 sm:w-56 md:w-64 lg:w-72 shadow-lg transition-transform duration-300 group-hover:scale-105 group-hover:z-30 group-hover:shadow-[0_8px_30px_rgba(0,0,0,0.9)] border border-transparent group-hover:border-gray-700"
      >
        <img
          src={anime.banner_image || anime.poster_image}
          alt={anime.title}
          className="w-full h-full object-cover filter brightness-[0.9] group-hover:brightness-105 transition-all duration-500"
          loading="lazy"
        />

        {/* Quality Badge Overlay */}
        <div className="absolute top-2 right-2 bg-black/60 backdrop-blur-md px-1.5 py-0.5 rounded text-[10px] font-bold text-gray-200 border border-gray-700">
          {anime.quality || 'HD'}
        </div>

        {/* Title overlay in normal mode */}
        <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/20 to-transparent flex flex-col justify-end p-2.5">
          <h3 className="text-xs sm:text-sm font-bold text-white drop-shadow truncate">
            {anime.title}
          </h3>
          <div className="flex items-center gap-1.5 text-[10px] text-gray-300 font-medium">
            <span className="text-emerald-400 font-semibold">{anime.match_score}% Match</span>
            <span>•</span>
            <span>{anime.release_year}</span>
          </div>
        </div>

        {/* Progress bar for continue watching */}
        {showProgress && anime.watch_progress !== undefined && (
          <div className="absolute bottom-0 inset-x-0 h-1 bg-gray-700">
            <div 
              className="h-full bg-[#E50914]" 
              style={{ width: `${Math.min(100, Math.max(5, anime.watch_progress))}%` }}
            />
          </div>
        )}

        {/* Hover Quick Action Card Overlay (Netflix signature) */}
        {isHovered && (
          <div className="absolute inset-0 bg-[#181818]/95 p-3 flex flex-col justify-between animate-fade-in z-40">
            {/* Top info */}
            <div>
              <h4 className="text-xs sm:text-sm font-black text-white truncate">
                {anime.title}
              </h4>
              <p className="text-[10px] text-gray-400 line-clamp-2 mt-0.5 leading-snug">
                {anime.synopsis}
              </p>
            </div>

            {/* Middle metadata */}
            <div className="space-y-1.5 my-1">
              <div className="flex items-center gap-1.5 text-[11px] font-bold">
                <span className="text-emerald-400">{anime.match_score}% Match</span>
                <span className="border border-gray-600 px-1 py-0.2 rounded text-[9px] text-gray-300">
                  {anime.age_rating || '16+'}
                </span>
                <span className="text-gray-400 text-[10px]">{anime.season_count || '1 Season'}</span>
              </div>
              <div className="text-[10px] text-gray-300 font-medium truncate">
                {genresDisplay}
              </div>
            </div>

            {/* Action buttons */}
            <div className="flex items-center justify-between pt-1 border-t border-gray-800">
              <div className="flex items-center gap-1.5">
                {/* Play button */}
                <button
                  onClick={(e) => { e.stopPropagation(); onPlay(anime); }}
                  className="w-7 h-7 rounded-full bg-white text-black flex items-center justify-center hover:bg-white/90 active:scale-95 transition-all shadow"
                  title="Play"
                >
                  <Play className="w-3.5 h-3.5 fill-current ml-0.5" />
                </button>

                {/* My List toggle */}
                <button
                  onClick={(e) => { e.stopPropagation(); onToggleMyList(anime.id); }}
                  className={`w-7 h-7 rounded-full border flex items-center justify-center transition-all active:scale-95 ${
                    isInMyList ? 'bg-[#E50914] border-[#E50914] text-white' : 'border-gray-500 bg-black/40 text-gray-200 hover:border-white'
                  }`}
                  title={isInMyList ? 'Remove from My List' : 'Add to My List'}
                >
                  {isInMyList ? <Check className="w-3.5 h-3.5" /> : <Plus className="w-3.5 h-3.5" />}
                </button>

                {/* Like button */}
                <button
                  onClick={(e) => { e.stopPropagation(); onToggleLike(anime.id, userLike === 1 ? 0 : 1); }}
                  className={`w-7 h-7 rounded-full border flex items-center justify-center transition-all active:scale-95 ${
                    userLike === 1 ? 'border-emerald-500 text-emerald-400 bg-emerald-500/20' : 'border-gray-500 bg-black/40 text-gray-200 hover:border-white'
                  }`}
                  title="I like this"
                >
                  <ThumbsUp className="w-3.5 h-3.5" />
                </button>
              </div>

              {/* More info chevron */}
              <button
                onClick={(e) => { e.stopPropagation(); onOpenDetails(anime); }}
                className="w-7 h-7 rounded-full border border-gray-500 bg-black/40 text-gray-200 hover:border-white flex items-center justify-center transition-all"
                title="Episode details & more"
              >
                <ChevronDown className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
