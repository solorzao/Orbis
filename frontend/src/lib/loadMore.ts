// "Load more" paging for a cell's story list in the news panel.

/** Stories fetched when a panel opens. */
export const FIRST_PAGE_LIMIT = 10;
/** Stories fetched per "Load more". */
export const LOAD_MORE_LIMIT = 20;
/** Per "Load more" while in-panel filters are on: they filter what is loaded. */
export const FILTERED_LOAD_MORE_LIMIT = 50; // the endpoint's maximum

/**
 * The next page to request, at the panel's `nextOffset`: the rows received so
 * far, which can be more than the stories kept (see applyPage).
 */
export function nextPage(nextOffset: number, filtered: boolean): { offset: number; limit: number } {
  return { offset: nextOffset, limit: filtered ? FILTERED_LOAD_MORE_LIMIT : LOAD_MORE_LIMIT };
}

/**
 * The stories loaded with a new page added, minus any already loaded: a batch
 * ingested after the click can still be stamped inside the panel's window,
 * shifting later pages down onto stories already shown (and React keys them
 * by id).
 */
export function appendPage<T extends { id: string }>(loaded: T[], page: T[]): T[] {
  const seen = new Set(loaded.map((story) => story.id));
  return [...loaded, ...page.filter((story) => !seen.has(story.id))];
}

/**
 * The panel point's `count` once a page of `received` stories (of `limit`
 * asked for) has arrived, bringing the stories loaded to `loaded`. That
 * includes the first page.
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

/**
 * A panel's stories, count and next offset once the page asked for at
 * `offset` with `limit` has arrived. The offset advances by the rows
 * received, duplicates included: they sit at those positions of the cell's
 * list, so a page of nothing but duplicates still moves Load more on.
 */
export function applyPage<T extends { id: string }>(
  panel: { articles: T[]; count: number },
  page: T[],
  offset: number,
  limit: number,
): { articles: T[]; count: number; nextOffset: number } {
  const articles = appendPage(panel.articles, page);
  return {
    articles,
    count: countAfterPage(panel.count, articles.length, page.length, limit),
    nextOffset: offset + page.length,
  };
}
