import React, { useState, useRef, useEffect } from 'react';
import { 
  Play, 
  Pause, 
  ArrowLeft, 
  RotateCcw, 
  RotateCw, 
  Volume2, 
  VolumeX, 
  Maximize, 
  Minimize, 
  SkipForward, 
  ListVideo, 
  MessageSquare, 
  Gauge,
  Sparkles,
  Check
} from 'lucide-react';

export default function VideoPlayerModal({
  anime,
  initialEpisode = null,
  onClose,
  onProgressUpdate
}) {
  const videoRef = useRef(null);
  const playerContainerRef = useRef(null);
  const controlsTimeoutRef = useRef(null);

  const [isPlaying, setIsPlaying] = useState(true);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(0.8);
  const [isMuted, setIsMuted] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showControls, setShowControls] = useState(true);
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  const [selectedSub, setSelectedSub] = useState('English');
  const [selectedAudio, setSelectedAudio] = useState('Japanese [Original]');
  
  // Drawers & popups
  const [showEpisodesDrawer, setShowEpisodesDrawer] = useState(false);
  const [showAudioMenu, setShowAudioMenu] = useState(false);
  const [showSpeedMenu, setShowSpeedMenu] = useState(false);

  // Current active episode
  const episodes = (anime && anime.episodes && anime.episodes.length > 0) ? anime.episodes : [
    {
      id: 1,
      episode_number: 1,
      title: 'Episode 1: The Awakening',
      duration: '24m',
      description: 'The journey begins in the world of legends.'
    }
  ];

  const [currentEpisodeIndex, setCurrentEpisodeIndex] = useState(() => {
    if (initialEpisode) {
      const idx = episodes.findIndex(e => e.id === initialEpisode.id || e.episode_number === initialEpisode.episode_number);
      return idx >= 0 ? idx : 0;
    }
    return 0;
  });

  const currentEpisode = episodes[currentEpisodeIndex] || episodes[0];

  // Auto-hide controls after inactivity
  const handleMouseMove = () => {
    setShowControls(true);
    if (controlsTimeoutRef.current) clearTimeout(controlsTimeoutRef.current);
    controlsTimeoutRef.current = setTimeout(() => {
      if (isPlaying && !showEpisodesDrawer && !showAudioMenu && !showSpeedMenu) {
        setShowControls(false);
      }
    }, 3000);
  };

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        if (showEpisodesDrawer || showAudioMenu || showSpeedMenu) {
          setShowEpisodesDrawer(false);
          setShowAudioMenu(false);
          setShowSpeedMenu(false);
        } else {
          onClose();
        }
      } else if (e.key === ' ' || e.key === 'k') {
        e.preventDefault();
        togglePlay();
      } else if (e.key === 'f') {
        toggleFullscreen();
      } else if (e.key === 'm') {
        toggleMute();
      } else if (e.key === 'ArrowLeft') {
        seekRelative(-10);
      } else if (e.key === 'ArrowRight') {
        seekRelative(10);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isPlaying, showEpisodesDrawer, showAudioMenu, showSpeedMenu]);

  // Video time updates
  const handleTimeUpdate = () => {
    if (videoRef.current) {
      const curr = videoRef.current.currentTime;
      const dur = videoRef.current.duration || 1;
      setCurrentTime(curr);
      setDuration(dur);

      // Periodically report progress to backend
      if (Math.floor(curr) % 5 === 0 && onProgressUpdate) {
        const percent = Math.round((curr / dur) * 100);
        onProgressUpdate(anime.id, currentEpisode.id || currentEpisode.episode_number, percent);
      }
    }
  };

  const togglePlay = () => {
    if (videoRef.current) {
      if (videoRef.current.paused) {
        videoRef.current.play();
        setIsPlaying(true);
      } else {
        videoRef.current.pause();
        setIsPlaying(false);
      }
    }
  };

  const seekRelative = (seconds) => {
    if (videoRef.current) {
      videoRef.current.currentTime = Math.max(0, Math.min(videoRef.current.duration || 0, videoRef.current.currentTime + seconds));
    }
  };

  const handleSeekChange = (e) => {
    const targetTime = parseFloat(e.target.value);
    if (videoRef.current) {
      videoRef.current.currentTime = targetTime;
      setCurrentTime(targetTime);
    }
  };

  const handleVolumeChange = (e) => {
    const newVol = parseFloat(e.target.value);
    setVolume(newVol);
    if (videoRef.current) {
      videoRef.current.volume = newVol;
      setIsMuted(newVol === 0);
    }
  };

  const toggleMute = () => {
    if (videoRef.current) {
      if (isMuted) {
        videoRef.current.muted = false;
        videoRef.current.volume = volume || 0.8;
        setIsMuted(false);
      } else {
        videoRef.current.muted = true;
        setIsMuted(true);
      }
    }
  };

  const toggleFullscreen = () => {
    if (!playerContainerRef.current) return;
    if (!document.fullscreenElement) {
      playerContainerRef.current.requestFullscreen().catch(err => console.log(err));
      setIsFullscreen(true);
    } else {
      document.exitFullscreen().catch(err => console.log(err));
      setIsFullscreen(false);
    }
  };

  const changeSpeed = (speed) => {
    setPlaybackSpeed(speed);
    if (videoRef.current) {
      videoRef.current.playbackRate = speed;
    }
    setShowSpeedMenu(false);
  };

  const playNextEpisode = () => {
    if (currentEpisodeIndex < episodes.length - 1) {
      setCurrentEpisodeIndex(currentEpisodeIndex + 1);
      setCurrentTime(0);
      setIsPlaying(true);
    }
  };

  const formatTime = (timeInSeconds) => {
    if (isNaN(timeInSeconds)) return '00:00';
    const mins = Math.floor(timeInSeconds / 60);
    const secs = Math.floor(timeInSeconds % 60);
    return `${mins < 10 ? '0' : ''}${mins}:${secs < 10 ? '0' : ''}${secs}`;
  };

  const streamUrl = currentEpisode.video_url || anime.video_url || 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4';

  return (
    <div 
      ref={playerContainerRef}
      onMouseMove={handleMouseMove}
      className="fixed inset-0 z-[100] bg-black flex items-center justify-center select-none overflow-hidden"
    >
      {/* HTML5 Video Element */}
      <video
        ref={videoRef}
        src={streamUrl}
        className="w-full h-full object-contain cursor-pointer"
        autoPlay
        playsInline
        onTimeUpdate={handleTimeUpdate}
        onLoadedMetadata={handleTimeUpdate}
        onEnded={playNextEpisode}
        onClick={togglePlay}
      />

      {/* Top Header Controls */}
      <div className={`absolute top-0 inset-x-0 p-4 sm:p-6 bg-gradient-to-b from-black/90 via-black/50 to-transparent transition-opacity duration-300 z-50 flex items-center justify-between ${
        showControls ? 'opacity-100' : 'opacity-0 pointer-events-none'
      }`}>
        <div className="flex items-center gap-4">
          <button
            onClick={onClose}
            className="p-2 rounded-full bg-black/40 hover:bg-white/20 text-white transition-all backdrop-blur-md"
            title="Back to Browse (Esc)"
          >
            <ArrowLeft className="w-6 h-6" />
          </button>
          <div>
            <h2 className="text-sm sm:text-base font-bold text-white flex items-center gap-2">
              <span>{anime.title}</span>
              <span className="text-gray-400 font-normal">|</span>
              <span className="text-[#E50914] font-semibold">{currentEpisode.title}</span>
            </h2>
            <p className="text-xs text-gray-400 hidden sm:block">
              Season 1: Episode {currentEpisode.episode_number} • {anime.quality || '4K Ultra HD'}
            </p>
          </div>
        </div>

        {/* Top Right Badges */}
        <div className="flex items-center gap-2">
          <span className="bg-[#E50914] text-white text-[10px] font-black px-2 py-0.5 rounded tracking-wider uppercase">
            ANIMEFLIX STREAM
          </span>
        </div>
      </div>

      {/* Center Skip Intro Button (Visible around 5s - 35s) */}
      {currentTime > 5 && currentTime < 40 && (
        <div className="absolute right-8 bottom-28 z-40 animate-fade-in">
          <button
            onClick={() => seekRelative(25)}
            className="flex items-center gap-2 px-4 py-2 rounded bg-black/70 hover:bg-black/90 border border-gray-500 text-white font-bold text-xs backdrop-blur-md transition-all shadow-xl hover:scale-105 active:scale-95"
          >
            <Sparkles className="w-4 h-4 text-[#E50914]" />
            <span>Skip Intro</span>
          </button>
        </div>
      )}

      {/* Bottom Controls Bar */}
      <div className={`absolute bottom-0 inset-x-0 p-4 sm:p-6 bg-gradient-to-t from-black/95 via-black/70 to-transparent transition-opacity duration-300 z-50 ${
        showControls ? 'opacity-100' : 'opacity-0 pointer-events-none'
      }`}>
        
        {/* Timeline / Progress Bar */}
        <div className="relative mb-3 group/progress">
          <input
            type="range"
            min={0}
            max={duration || 100}
            value={currentTime}
            onChange={handleSeekChange}
            className="w-full h-1.5 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-[#E50914] hover:h-2.5 transition-all"
          />
        </div>

        {/* Control Buttons row */}
        <div className="flex items-center justify-between">
          
          {/* Left Controls: Play, Rewind, Fast Forward, Volume */}
          <div className="flex items-center gap-3 sm:gap-5">
            <button
              onClick={togglePlay}
              className="text-white hover:text-[#E50914] transition-colors p-1"
              title={isPlaying ? 'Pause (Space)' : 'Play (Space)'}
            >
              {isPlaying ? <Pause className="w-6 h-6 fill-current" /> : <Play className="w-6 h-6 fill-current" />}
            </button>

            <button
              onClick={() => seekRelative(-10)}
              className="text-gray-300 hover:text-white transition-colors p-1"
              title="Rewind 10s (Left Arrow)"
            >
              <RotateCcw className="w-5 h-5" />
            </button>

            <button
              onClick={() => seekRelative(10)}
              className="text-gray-300 hover:text-white transition-colors p-1"
              title="Fast Forward 10s (Right Arrow)"
            >
              <RotateCw className="w-5 h-5" />
            </button>

            {/* Next Episode Button */}
            {currentEpisodeIndex < episodes.length - 1 && (
              <button
                onClick={playNextEpisode}
                className="text-gray-300 hover:text-white transition-colors p-1"
                title="Next Episode"
              >
                <SkipForward className="w-5 h-5" />
              </button>
            )}

            {/* Volume Control */}
            <div className="flex items-center gap-2 group/volume">
              <button
                onClick={toggleMute}
                className="text-gray-300 hover:text-white transition-colors p-1"
                title={isMuted ? 'Unmute (M)' : 'Mute (M)'}
              >
                {isMuted || volume === 0 ? <VolumeX className="w-5 h-5 text-red-500" /> : <Volume2 className="w-5 h-5" />}
              </button>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={isMuted ? 0 : volume}
                onChange={handleVolumeChange}
                className="w-16 sm:w-24 h-1 bg-gray-600 rounded appearance-none accent-white cursor-pointer opacity-80 group-hover/volume:opacity-100"
              />
            </div>

            {/* Time Stamp */}
            <div className="text-xs font-semibold text-gray-300">
              <span>{formatTime(currentTime)}</span>
              <span className="mx-1 text-gray-500">/</span>
              <span>{formatTime(duration)}</span>
            </div>
          </div>

          {/* Right Controls: Audio/Sub, Speed, Episode Drawer, Fullscreen */}
          <div className="flex items-center gap-3 sm:gap-4">
            
            {/* Playback Speed Switcher */}
            <div className="relative">
              <button
                onClick={() => { setShowSpeedMenu(!showSpeedMenu); setShowAudioMenu(false); setShowEpisodesDrawer(false); }}
                className="flex items-center gap-1 text-xs font-bold text-gray-300 hover:text-white px-2 py-1 rounded bg-white/10 hover:bg-white/20 transition-all"
                title="Playback Speed"
              >
                <Gauge className="w-4 h-4" />
                <span>{playbackSpeed}x</span>
              </button>

              {showSpeedMenu && (
                <div className="absolute right-0 bottom-10 w-28 bg-[#181818] border border-gray-800 rounded-md shadow-2xl py-1 z-50 animate-fade-in">
                  {[0.5, 0.75, 1, 1.25, 1.5, 2].map((spd) => (
                    <button
                      key={spd}
                      onClick={() => changeSpeed(spd)}
                      className={`w-full text-left px-3 py-1.5 text-xs flex items-center justify-between hover:bg-white/10 ${
                        playbackSpeed === spd ? 'text-[#E50914] font-bold' : 'text-gray-300'
                      }`}
                    >
                      <span>{spd}x</span>
                      {playbackSpeed === spd && <Check className="w-3 h-3 text-[#E50914]" />}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Subtitles & Audio Selector */}
            <div className="relative">
              <button
                onClick={() => { setShowAudioMenu(!showAudioMenu); setShowSpeedMenu(false); setShowEpisodesDrawer(false); }}
                className="text-gray-300 hover:text-white p-1 transition-colors"
                title="Audio & Subtitles"
              >
                <MessageSquare className="w-5 h-5" />
              </button>

              {showAudioMenu && (
                <div className="absolute right-0 bottom-10 w-64 bg-[#181818] border border-gray-800 rounded-lg shadow-2xl p-3 z-50 animate-fade-in">
                  <div className="grid grid-cols-2 gap-3 text-xs">
                    <div>
                      <h4 className="font-bold text-gray-400 uppercase tracking-wider mb-2 text-[10px]">Audio</h4>
                      {['Japanese [Original]', 'English [Dub]', 'German'].map(aud => (
                        <button
                          key={aud}
                          onClick={() => setSelectedAudio(aud)}
                          className={`w-full text-left py-1 text-xs hover:text-white ${selectedAudio === aud ? 'text-[#E50914] font-bold' : 'text-gray-400'}`}
                        >
                          {aud}
                        </button>
                      ))}
                    </div>
                    <div>
                      <h4 className="font-bold text-gray-400 uppercase tracking-wider mb-2 text-[10px]">Subtitles</h4>
                      {['Off', 'English', 'Spanish', 'French', 'German'].map(sub => (
                        <button
                          key={sub}
                          onClick={() => setSelectedSub(sub)}
                          className={`w-full text-left py-1 text-xs hover:text-white ${selectedSub === sub ? 'text-[#E50914] font-bold' : 'text-gray-400'}`}
                        >
                          {sub}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Episode List Drawer Button */}
            <button
              onClick={() => { setShowEpisodesDrawer(!showEpisodesDrawer); setShowAudioMenu(false); setShowSpeedMenu(false); }}
              className={`p-1 transition-colors ${showEpisodesDrawer ? 'text-[#E50914]' : 'text-gray-300 hover:text-white'}`}
              title="Episode Drawer"
            >
              <ListVideo className="w-5 h-5" />
            </button>

            {/* Fullscreen Toggle */}
            <button
              onClick={toggleFullscreen}
              className="text-gray-300 hover:text-white p-1 transition-colors"
              title={isFullscreen ? 'Exit Fullscreen (F)' : 'Fullscreen (F)'}
            >
              {isFullscreen ? <Minimize className="w-5 h-5" /> : <Maximize className="w-5 h-5" />}
            </button>
          </div>

        </div>
      </div>

      {/* Episode Drawer Sidebar */}
      {showEpisodesDrawer && (
        <div className="absolute top-0 right-0 bottom-0 w-80 sm:w-96 bg-[#181818]/95 border-l border-gray-800 backdrop-blur-md p-4 z-50 animate-fade-in flex flex-col">
          <div className="flex items-center justify-between pb-3 border-b border-gray-800">
            <h3 className="text-sm font-bold text-white">Episodes ({episodes.length})</h3>
            <button 
              onClick={() => setShowEpisodesDrawer(false)}
              className="text-gray-400 hover:text-white text-xs font-semibold"
            >
              Close
            </button>
          </div>

          <div className="flex-1 overflow-y-auto space-y-2 py-3">
            {episodes.map((ep, idx) => (
              <div
                key={ep.id || idx}
                onClick={() => {
                  setCurrentEpisodeIndex(idx);
                  setCurrentTime(0);
                  setIsPlaying(true);
                  setShowEpisodesDrawer(false);
                }}
                className={`p-2.5 rounded-md cursor-pointer flex gap-3 transition-colors ${
                  currentEpisodeIndex === idx ? 'bg-white/20 border border-[#E50914]' : 'hover:bg-white/10'
                }`}
              >
                <div className="w-20 h-12 bg-black/40 rounded overflow-hidden shrink-0 relative">
                  <img
                    src={ep.thumbnail || anime.banner_image}
                    alt={ep.title}
                    className="w-full h-full object-cover"
                  />
                  {currentEpisodeIndex === idx && (
                    <div className="absolute inset-0 bg-black/50 flex items-center justify-center">
                      <Play className="w-4 h-4 fill-[#E50914] text-[#E50914]" />
                    </div>
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <h4 className="text-xs font-bold text-white truncate">{ep.episode_number}. {ep.title}</h4>
                  <p className="text-[10px] text-gray-400 line-clamp-2 mt-0.5">{ep.description}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

    </div>
  );
}
