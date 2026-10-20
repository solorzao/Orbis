"use client";

interface EntityPillsProps {
  /** People and organisations, most named first. */
  entities: readonly { name: string; n: number }[];
  /** Follow one across the globe (the entity tracker, PR 17b). Without it the pills are inert. */
  onTrack?: (name: string) => void;
}

/**
 * "Key entities" as pills (mockup .chips): plain labels until something can
 * track them, then buttons that do. A list either way.
 */
export default function EntityPills({ entities, onTrack }: EntityPillsProps) {
  if (entities.length === 0) return null;
  return (
    <ul className="chips entity-pills" aria-label="Key entities">
      {entities.map((e) => (
        <li key={e.name}>
          {onTrack ? (
            <button
              type="button"
              className="pill"
              aria-label={`Track ${e.name}`}
              onClick={() => onTrack(e.name)}
            >
              {e.name}
            </button>
          ) : (
            <span className="pill">{e.name}</span>
          )}
        </li>
      ))}
    </ul>
  );
}
