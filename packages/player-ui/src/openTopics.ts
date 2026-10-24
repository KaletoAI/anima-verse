import { useEffect, useState } from 'react';
import { apiGet } from './api';
import { usePoll } from './usePolling';
import { SYNC_ENDPOINTS } from './syncEndpoints';

type Messages = { conversations?: Array<{ unread?: number }> };
type Feed = { posts?: Array<{ id: string }> };

/** Posts arrive newest first; the last seen post separates new from read. */
export function unreadCounts(messages: Messages | null, feed: Feed | null, seenId: string | null): { phone: number; instagram: number } {
  const posts = feed?.posts || [];
  const index = posts.findIndex(post => post.id === seenId);
  return {
    phone: (messages?.conversations || []).reduce((sum, conversation) => sum + (conversation.unread || 0), 0),
    instagram: seenId === null ? 0 : index < 0 ? Math.min(posts.length, 99) : index,
  };
}

async function fetchBadges() {
  const messages = await apiGet<Messages>('/play/messages').catch(() => null);
  const feed = await apiGet<Feed>('/instagram/feed?limit=50').catch(() => null);
  return { messages, feed };
}

export function useOpenTopics(instagramOpen: boolean): { phone: number; instagram: number } {
  const [seenId, setSeenId] = useState<string | null>(() => {
    try { return localStorage.getItem('play.ig.seen'); } catch { return null; }
  });
  const { data } = usePoll('play-badges', fetchBadges, SYNC_ENDPOINTS.badges);
  const newest = data?.feed?.posts?.[0]?.id || null;
  useEffect(() => {
    if (!newest || (!instagramOpen && seenId !== null)) return;
    setSeenId(newest);
    try { localStorage.setItem('play.ig.seen', newest); } catch { /* Storage may be unavailable. */ }
  }, [newest, instagramOpen, seenId]);
  // Opening the panel clears its badge immediately, before the storage effect.
  return unreadCounts(data?.messages ?? null, data?.feed ?? null,
    instagramOpen ? newest : seenId);
}
