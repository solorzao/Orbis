"use client";

import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import {
  fetchEntity,
  toDossier,
  type ApiEntityDossier,
  type EntityDossier,
  type EntityRef,
  type EntityType,
} from "@/lib/entities";

interface Answer {
  entity: EntityRef;
  dossier: EntityDossier | null;
  notFound: boolean;
  error: boolean;
}

const isNotFound = (err: unknown) => err instanceof ApiError && err.status === 404;

/**
 * The tracked person's or organisation's dossier (/api/entities), or none.
 * A name without a type (a thread's key entities) is tried as a person, then
 * as an organisation. An unknown name is `notFound` (a 404), not an error. A
 * new name aborts the last request; only the name asked for is returned.
 */
export function useEntity(entity: EntityRef | null): {
  dossier: EntityDossier | null;
  loading: boolean;
  notFound: boolean;
  error: boolean;
} {
  const [answer, setAnswer] = useState<Answer | null>(null);

  useEffect(() => {
    if (entity === null) return;
    const controller = new AbortController();
    const { signal } = controller;
    const types: EntityType[] = entity.type ? [entity.type] : ["person", "org"];
    const load = async (): Promise<ApiEntityDossier | null> => {
      for (const type of types) {
        try {
          return await fetchEntity({ type, name: entity.name, signal });
        } catch (err) {
          if (!isNotFound(err)) throw err;
        }
      }
      return null;
    };
    load()
      .then((api) => {
        if (signal.aborted) return;
        setAnswer({
          entity,
          dossier: api ? toDossier(api) : null,
          notFound: api === null,
          error: false,
        });
      })
      .catch(() => {
        if (!signal.aborted) setAnswer({ entity, dossier: null, notFound: false, error: true });
      });
    return () => controller.abort();
  }, [entity]);

  if (entity === null) return { dossier: null, loading: false, notFound: false, error: false };
  if (answer?.entity !== entity) {
    return { dossier: null, loading: true, notFound: false, error: false };
  }
  return {
    dossier: answer.dossier,
    loading: false,
    notFound: answer.notFound,
    error: answer.error,
  };
}
