import React, { useRef, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import AnimeCard from './AnimeCard';

export default function AnimeRow({
  title,
  subtitle,
  icon,
  animeList = [],
  onPlay,
  onOpenDetails,
  onToggleMyList,
  myListMap = {},
  onToggleLike,
  likesMap = {},
  isTop10 = false,
  showProgress = false
}) {
  const rowRef = useRef(null);
  const [showLeftArrow, setShowLeftArrow] = useState(false);
  const [showRightArrow, setShowRightArrow] = useState(true);

  if (!animeList || animeList.length === 0) return null;

  const handleScroll = (direction) => {
    if (!rowRef.current) return;
    const { scrollLeft, clientWidth, scrollWidth } = rowRef.current;
    const scrollAmount = clientWidth * 0.75;
    const targetScroll = direction === 'left' ? scrollLeft - scrollAmount : scrollLeft + scrollAmount;

    rowRef.current.scrollTo({
      left: targetScroll,
      behavior: 'smooth'
    });
  };

  const onScroll = () => {
    if (!rowRef.current) return;
    const { scrollLeft, clientWidth, scrollWidth } = rowRef.current;
    setShowLeftArrow(scrollLeft > 20);
    setShowRightArrow(scrollLeft < scrollWidth - clientWidth - 20);
  };

  return (
    <div className="relative py-4 group select-none">
      {/* Row Header */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          {icon && <span className="text-[#E50914]">{icon}</span>}
          <div>
            <h2 className="text-lg sm:text-xl font-bold text-white tracking-wide flex items-center gap-2">
              <span>{title}</span>
              {isTop10 && (
                <span className="text-xs bg-[#E50914] text-white px-2 py-0.5 rounded font-black uppercase">
                  Top 10
                </span>
              )}
            </h2>
            {subtitle && <p className="text-xs text-gray-400">{subtitle}</p>}
          </div>
        </div>

        {/* Explore All link / badge */}
        <span className="text-xs font-semibold text-gray-400 group-hover:text-gray-200 transition-colors cursor-pointer hidden sm:inline-block">
          Explore All &gt;
        </span>
      </div>

      {/* Row Slider Container */}
      <div className="relative">
        
        {/* Left Arrow Button */}
        {showLeftArrow && (
          <button
            onClick={() => handleScroll('left')}
            className="absolute left-0 top-0 bottom-0 z-40 w-10 sm:w-12 bg-black/60 hover:bg-black/85 text-white flex items-center justify-center transition-all opacity-0 group-hover:opacity-100 cursor-pointer backdrop-blur-xs"
            aria-label="Scroll left"
          >
            <ChevronLeft className="w-8 h-8 text-white hover:scale-125 transition-transform" />
          </button>
        )}

        {/* Horizontal Items Container */}
        <div
          ref={rowRef}
          onScroll={onScroll}
          className="flex items-center gap-3 sm:gap-4 overflow-x-auto no-scrollbar px-4 sm:px-6 lg:px-8 py-4 scroll-smooth"
        >
          {animeList.map((anime, index) => (
            <AnimeCard
              key={anime.id || index}
              anime={anime}
              rank={index + 1}
              isTop10={isTop10}
              showProgress={showProgress}
              onPlay={onPlay}
              onOpenDetails={onOpenDetails}
              onToggleMyList={onToggleMyList}
              isInMyList={Boolean(myListMap[anime.id])}
              onToggleLike={onToggleLike}
              userLike={likesMap[anime.id] || 0}
            />
          ))}
        </div>

        {/* Right Arrow Button */}
        {showRightArrow && (
          <button
            onClick={() => handleScroll('right')}
            className="absolute right-0 top-0 bottom-0 z-40 w-10 sm:w-12 bg-black/60 hover:bg-black/85 text-white flex items-center justify-center transition-all opacity-0 group-hover:opacity-100 cursor-pointer backdrop-blur-xs"
            aria-label="Scroll right"
          >
            <ChevronRight className="w-8 h-8 text-white hover:scale-125 transition-transform" />
          </button>
        )}

      </div>
    </div>
  );
}
