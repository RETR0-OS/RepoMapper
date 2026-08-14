import type { ViewRequestContext } from "./types.js";

const MAX_REVISION_ID_LENGTH = 256;
const MAX_LENS_ID_LENGTH = 200;

function boundedText(value: unknown, maximumLength: number): string | undefined {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed.length > 0 && trimmed.length <= maximumLength && !/[\u0000-\u001f\u007f]/.test(trimmed)
    ? trimmed
    : undefined;
}

export interface PendingCompareContext {
  beforeRevision: string;
  afterRevision?: string;
}

export function pendingCompareContext(value: unknown): PendingCompareContext | undefined {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return undefined;
  const pair = value as Record<string, unknown>;
  const beforeRevision = boundedText(pair.beforeRevision, MAX_REVISION_ID_LENGTH);
  if (!beforeRevision) return undefined;
  if (pair.afterRevision === undefined) return { beforeRevision };
  const afterRevision = boundedText(pair.afterRevision, MAX_REVISION_ID_LENGTH);
  if (!afterRevision || beforeRevision === afterRevision) return undefined;
  return { beforeRevision, afterRevision };
}

export function compareViewContext(value: unknown): ViewRequestContext | undefined {
  const pair = pendingCompareContext(value);
  return pair?.afterRevision ? pair : undefined;
}

export function preserveViewContext(value: unknown): ViewRequestContext | undefined {
  const lens = boundedText(value, MAX_LENS_ID_LENGTH);
  if (!lens || /^preview(?:$|[-_:])/i.test(lens)) return undefined;
  return { lens };
}
