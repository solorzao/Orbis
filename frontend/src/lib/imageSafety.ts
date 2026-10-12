/**
 * Rules for showing a news site's image unprompted (the hover card's lead
 * image). Images are hotlinked from GDELT's sources, so they load with no
 * referrer, over https only, and anything that isn't a real photo gives way
 * to the topic's glyph.
 */

/**
 * Publisher logos and stand-ins, which say nothing about the story. Matched
 * as words of the URL's path only: not its host ("logo.example.com" serves
 * photos too) or query, nor inside a word ("psicologo").
 */
const LOGO_LIKE = /(?:^|[^a-z])(?:logos?|favicon|placeholder|default[-_]?image)(?![a-z])/i;

/** Narrower than this, an image is an icon or a tracking pixel, not a photo. */
export const MIN_PHOTO_WIDTH = 160;

/** Width over height: outside this, an image is a banner or a strip. */
const PHOTO_ASPECT = { min: 0.5, max: 3 } as const;

/** The image URL to load, or null: https only, and nothing that looks like a logo. */
export function safeImageUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  if (parsed.protocol !== "https:" || LOGO_LIKE.test(parsed.pathname)) return null;
  return parsed.href;
}

/** After it loads: whether an image is photo-shaped (big enough, not a banner). */
export function looksLikePhoto(naturalWidth: number, naturalHeight: number): boolean {
  if (naturalWidth < MIN_PHOTO_WIDTH || naturalHeight <= 0) return false;
  const aspect = naturalWidth / naturalHeight;
  return aspect >= PHOTO_ASPECT.min && aspect <= PHOTO_ASPECT.max;
}

/**
 * Whether the image goes behind a veil: a sensitive lead's image (conflict
 * among any of its tags) may be graphic, so it is blurred until the visitor
 * asks to see it (that image then stays revealed for the session).
 */
export function veilsImage(sensitive: boolean, revealed: boolean): boolean {
  return sensitive && !revealed;
}
