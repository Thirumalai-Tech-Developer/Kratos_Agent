import React, { useState } from 'react';
import { Play, Info, Volume2, VolumeX, Sparkles, Star, Plus, Check } from 'lucide-react';

export default function HeroBanner({
  anime,
  onPlay,
  onOpenDetails,
  onToggleMyList,
  isInMyList
}) {
  const [isMuted, setIsMuted] = useState(true);

  if (!anime) return null;

  return (
    <div className="relative w-full h-[75vh] sm:h-[82vh] lg:h-[90vh] text-white select-none">
      
      {/* Background Poster / Banner with Smooth Gradients */}
      <div className="absolute inset-0 overflow-hidden">
        <img
          src={anime.banner_image || anime.poster_image}
          alt={anime.title}
          className="w-full h-full object-cover object-center filter brightness-[0.85] scale-105 transition-transform duration-1000 ease-out"
        />
        
        {/* Cinematic Netflix Vignette & Gradients */}
        <div className="absolute inset-0 bg-gradient-to-r from-[#141414] via-[#141414]/60 to-transparent w-full md:w-3/4" />
        <div className="absolute inset-0 bg-gradient-to-t from-[#141414] via-[#141414]/20 to-transparent" />
        <div className="absolute top-0 inset-x-0 h-32 bg-gradient-to-b from-[#141414]/90 to-transparent" />
      </div>

      {/* Billboard Content */}
      <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-full flex flex-col justify-end pb-24 sm:pb-32 lg:pb-36 z-20">
        <div className="max-w-2xl space-y-4">
          
          {/* Top Badge: Netflix Top 10 or Featured */}
          <div className="flex items-center gap-2">
            <span className="bg-[#E50914] text-white text-[11px] sm:text-xs font-black px-2 py-0.5 rounded tracking-wider uppercase flex items-center gap-1 shadow-md">
              <Sparkles className="w-3 h-3 fill-current" />
              #1 in Anime Today
            </span>
            <span className="text-xs font-medium text-gray-300 backdrop-blur-md bg-black/40 px-2 py-0.5 rounded border border-gray-700">
              {anime.studio || 'MAPPA'}
            </span>
          </div>

          {/* Title */}
          <div>
            <h1 className="text-3xl sm:text-5xl lg:text-6xl font-black tracking-tight drop-shadow-[0_4px_12px_rgba(0,0,0,0.9)] leading-tight text-white">
              {anime.title}
            </h1>
            {anime.japanese_title && (
              <p className="text-xs sm:text-sm text-gray-400 font-medium tracking-wide mt-1">
                {anime.japanese_title}
              </p>
            )}
          </div>

          {/* Metadata Badges */}
          <div className="flex flex-wrap items-center gap-2.5 sm:gap-3 text-xs sm:text-sm font-semibold text-gray-200">
            <span className="text-emerald-400 font-bold drop-shadow">
              {anime.match_score || 98}% Match
            </span>
            <span className="flex items-center gap-1 text-amber-400">
              <Star className="w-3.5 h-3.5 fill-current" />
              {anime.rating || 9.4}
            </span>
            <span className="text-gray-400">{anime.release_year || 2024}</span>
            <span className="border border-gray-500/80 px-1.5 py-0.5 rounded text-[11px] bg-black/40">
              {anime.age_rating || 'TV-MA'}
            </span>
            <span className="border border-gray-500/80 px-1.5 py-0.5 rounded text-[11px] bg-black/40">
              {anime.season_count || '2 Seasons'}
            </span>
            <span className="border border-red-500/80 text-red-400 px-1.5 py-0.5 rounded text-[11px] font-bold bg-black/40">
              {anime.quality || '4K Ultra HD'}
            </span>
          </div>

          {/* Synopsis */}
          <p className="text-xs sm:text-sm lg:text-base text-gray-200 line-clamp-3 leading-relaxed drop-shadow-[0_2px_4px_rgba(0,0,0,0.8)]">
            {anime.synopsis}
          </p>

          {/* Action Buttons */}
          <div className="flex items-center gap-3 pt-2">
            
            {/* Play Button */}
            <button
              onClick={() => onPlay(anime)}
              className="flex items-center gap-2 px-5 sm:px-7 py-2.5 sm:py-3 rounded bg-white text-black font-bold text-sm sm:text-base hover:bg-white/90 active:scale-95 transition-all shadow-xl hover:shadow-[0_0_20px_rgba(255,255,255,0.4)]"
            >
              <Play className="w-5 h-5 fill-current text-black" />
              <span>Play</span>
            </button>

            {/* More Info Button */}
            <button
              onClick={() => onOpenDetails(anime)}
              className="flex items-center gap-2 px-5 sm:px-7 py-2.5 sm:py-3 rounded bg-gray-500/40 hover:bg-gray-500/60 backdrop-blur-md text-white font-bold text-sm sm:text-base transition-all border border-gray-400/30 active:scale-95 shadow-lg"
            >
              <Info className="w-5 h-5" />
              <span>More Info</span>
            </button>

            {/* Quick My List Add/Remove */}
            <button
              onClick={() => onToggleMyList(anime.id)}
              className={`p-2.5 sm:p-3 rounded-full border border-gray-400/50 backdrop-blur-md transition-all active:scale-95 ${
                isInMyList ? 'bg-white text-black border-white' : 'bg-black/40 text-white hover:border-white'
              }`}
              title={isInMyList ? 'Remove from My List' : 'Add to My List'}
            >
              {isInMyList ? <Check className="w-5 h-5" /> : <Plus className="w-5 h-5" />}
            </button>
          </div>

        </div>
      </div>

      {/* Right Edge: Mute Toggle & Maturity Rating Bar */}
      <div className="absolute right-0 bottom-24 sm:bottom-32 lg:bottom-36 flex items-center gap-3 pr-4 sm:pr-8 z-20">
        <button
          onClick={() => setIsMuted(!isMuted)}
          className="p-2.5 rounded-full border border-gray-500/60 bg-black/40 backdrop-blur-md text-gray-300 hover:text-white hover:border-white transition-all shadow-lg"
          title={isMuted ? 'Unmute preview' : 'Mute preview'}
        >
          {isMuted ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}
        </button>

        <div className="bg-[#141414]/70 backdrop-blur-md border-l-4 border-gray-400 py-1 px-3 text-xs sm:text-sm font-bold text-gray-200 uppercase tracking-wider">
          {anime.age_rating || '16+'}
        </div>
      </div>

    </div>
  );
}
