// "Load more" paging for a cell's story list in the news panel.

/** Stories fetched per "Load more". */
export const LOAD_MORE_LIMIT = 20;
/** Per "Load more" while in-panel filters are on: they filter what is loaded. */
export const FILTERED_LOAD_MORE_LIMIT = 50; // the endpoint's maximum

/** The next page to request: always the stories after those already loaded. */
export function nextPage(loaded: number, filtered: boolean): { offset: number; limit: number } {
  return { offset: loaded, limit: filtered ? FILTERED_LOAD_MORE_LIMIT : LOAD_MORE_LIMIT };
}

/**
 * The panel point's `count` once a page of `received` stories (of `limit`
 * asked for) has arrived, bringing the stories loaded to `loaded`.
 *
 * NewsPanel offers "Load more" while fewer stories are loaded than `count`.
 * A full page means the cell may hold more, so the dot's count stands; a
 * short or empty page means the list is exhausted, so the count becomes the
 * stories loaded, which hides the button.
 */
export function countAfterPage(
  count: number,
  loaded: number,
  received: number,
  limit: number,
): number {
  return received < limit ? loaded : count;
}
