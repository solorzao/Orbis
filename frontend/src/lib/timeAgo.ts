/** How long ago a story was published: "just now", "12m ago", "3h ago", "2d ago". */
export function timeAgo(dateString: string, now = Date.now()): string {
  const seconds = Math.floor((now - new Date(dateString).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}
