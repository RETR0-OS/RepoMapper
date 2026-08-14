import type { GraphEdge, GraphView } from "../types.js";
import type { Point } from "./layout.js";

export interface Transform {
  x: number;
  y: number;
  scale: number;
}

export const DEFAULT_TRANSFORM: Transform = { x: 0, y: 0, scale: 1 };

export function visibleEdges(view: GraphView, relationKinds: ReadonlySet<string>, showInferred: boolean): GraphEdge[] {
  return view.edges.filter((edge) => relationKinds.has(edge.predicate) && (showInferred || edge.quality === "exact"));
}

export function zoomAtPoint(transform: Transform, pointer: Point, nextScale: number): Transform {
  const scale = Math.min(2.4, Math.max(0.45, nextScale));
  const graphX = (pointer.x - transform.x) / transform.scale;
  const graphY = (pointer.y - transform.y) / transform.scale;
  return {
    scale,
    x: pointer.x - graphX * scale,
    y: pointer.y - graphY * scale
  };
}

export function safeDisplayStateKey(value: string): boolean {
  return /^[a-z0-9:_-]{1,120}$/i.test(value);
}

export function nextSelection(ids: readonly string[], selectedId: string | undefined, direction: 1 | -1): string | undefined {
  if (ids.length === 0) {
    return undefined;
  }
  const current = selectedId ? ids.indexOf(selectedId) : -1;
  const index = current === -1 ? (direction === 1 ? 0 : ids.length - 1) : (current + direction + ids.length) % ids.length;
  return ids[index];
}
