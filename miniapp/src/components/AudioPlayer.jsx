import { useEffect, useRef, useState } from 'react';
import { fetchAudioTracks } from '../lib/api';

const OFF_STORAGE_KEY = 'cm_audio_off';
const VOLUME_STORAGE_KEY = 'cm_audio_volume';
const DEFAULT_VOLUME = 0.5;

function readStoredOff() {
  return localStorage.getItem(OFF_STORAGE_KEY) === '1';
}

function readStoredVolume() {
  const stored = Number(localStorage.getItem(VOLUME_STORAGE_KEY));
  return Number.isFinite(stored) && stored >= 0 && stored <= 1 ? stored : DEFAULT_VOLUME;
}

// "807488_zinali_sunshine-in-the-dawn-mist.mp3" -> "Zinali Sunshine In The Dawn Mist".
// Strips a leading numeric id_ prefix (common on royalty-free download sites)
// and the extension, turns separators into spaces, title-cases what's left.
function prettifyTrackName(filename) {
  const withoutExt = filename.replace(/\.[^./]+$/, '');
  const withoutId = withoutExt.replace(/^\d+_/, '');
  const spaced = withoutId.replace(/[-_]+/g, ' ').trim();
  return spaced.replace(/\b\w/g, (c) => c.toUpperCase()) || filename;
}

/**
 * Lives at the App root (see App.jsx) — mounted once, never inside a tab
 * page, so switching between "Задачки"/"Дебютный тренажёр" never
 * remounts it and never interrupts playback.
 */
export default function AudioPlayer() {
  const [tracks, setTracks] = useState([]);
  const [status, setStatus] = useState('loading'); // loading | ready | empty | error
  const [isPlaying, setIsPlaying] = useState(false);
  const [isOff, setIsOff] = useState(() => readStoredOff());
  const [volume, setVolume] = useState(() => readStoredVolume());
  const [isExpanded, setIsExpanded] = useState(false);
  const audioRef = useRef(null);

  useEffect(() => {
    fetchAudioTracks()
      .then((list) => {
        if (!list || list.length === 0) {
          setStatus('empty');
          return;
        }
        setTracks(list);
        setStatus('ready');
      })
      .catch(() => setStatus('error'));
  }, []);

  useEffect(() => {
    if (audioRef.current) audioRef.current.volume = volume;
  }, [volume, status]);

  // Nothing in public/audio yet, or the list failed to load — stay
  // completely out of the way rather than showing a broken player.
  if (status !== 'ready') return null;

  const trackUrl = `/audio/${tracks[0]}`;
  const trackName = prettifyTrackName(tracks[0]);

  function togglePlay() {
    const audio = audioRef.current;
    if (!audio || isOff) return;
    if (isPlaying) {
      audio.pause();
    } else {
      audio.play().catch(() => {});
    }
  }

  // Deliberately separate from pause: this is what gets remembered, so a
  // future app open doesn't try to autoplay again until the user turns
  // sound back on themselves.
  function toggleOff() {
    const next = !isOff;
    setIsOff(next);
    localStorage.setItem(OFF_STORAGE_KEY, next ? '1' : '0');
    const audio = audioRef.current;
    if (!audio) return;
    if (next) {
      audio.pause();
    } else {
      audio.play().catch(() => {});
    }
  }

  function handleVolumeChange(event) {
    const next = Number(event.target.value);
    setVolume(next);
    localStorage.setItem(VOLUME_STORAGE_KEY, String(next));
  }

  return (
    <div className="fixed bottom-20 right-4 z-20">
      {/* muted mirrors isOff directly so "off" is a real audio shutoff, not
          just a UI state layered on top of an audio element that's still
          making sound. autoPlay only fires when not off — browsers may
          still block it without a prior user gesture, which just leaves
          isPlaying false until the user presses play themselves. */}
      <audio
        ref={audioRef}
        src={trackUrl}
        loop
        muted={isOff}
        autoPlay={!isOff}
        onPlay={() => setIsPlaying(true)}
        onPause={() => setIsPlaying(false)}
      />

      {!isExpanded ? (
        <button
          type="button"
          onClick={() => setIsExpanded(true)}
          aria-label="Развернуть плеер"
          className="flex h-11 w-11 items-center justify-center rounded-full border border-border bg-bg-elevated text-lg shadow-elevated"
        >
          {isOff ? '🔇' : isPlaying ? '🔊' : '🎵'}
        </button>
      ) : (
        <div className="w-60 space-y-3 rounded-md border border-border bg-bg-elevated p-3 shadow-elevated">
          <div className="flex items-center justify-between gap-2">
            <p className="min-w-0 flex-1 truncate font-mono text-xs text-ink-muted">{trackName}</p>
            <button
              type="button"
              onClick={() => setIsExpanded(false)}
              aria-label="Свернуть плеер"
              className="shrink-0 text-ink-muted"
            >
              ✕
            </button>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={togglePlay}
              disabled={isOff}
              aria-label={isPlaying ? 'Пауза' : 'Воспроизвести'}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-terracotta text-on-accent disabled:opacity-40"
            >
              {isPlaying ? '⏸' : '▶'}
            </button>

            <input
              type="range"
              min="0"
              max="1"
              step="0.01"
              value={volume}
              onChange={handleVolumeChange}
              disabled={isOff}
              aria-label="Громкость"
              className="flex-1 accent-terracotta disabled:opacity-40"
            />

            <button
              type="button"
              onClick={toggleOff}
              aria-label={isOff ? 'Включить звук' : 'Выключить звук'}
              title={isOff ? 'Включить звук' : 'Выключить звук'}
              className="shrink-0 text-lg"
            >
              {isOff ? '🔇' : '🔊'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
