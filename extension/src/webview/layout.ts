import type { GraphNode, ViewMode } from "../types.js";

export interface Point {
  x: number;
  y: number;
}

export type NodePositions = Record<string, Point>;

function grid(nodes: readonly GraphNode[], columns: number, startX: number, startY: number, gapX: number, gapY: number): NodePositions {
  return Object.fromEntries(nodes.map((node, index) => [node.id, {
    x: startX + (index % columns) * gapX,
    y: startY + Math.floor(index / columns) * gapY
  }]));
}

export function computeLayout(nodes: readonly GraphNode[], mode: ViewMode): NodePositions {
  if (nodes.length === 0) {
    return {};
  }
  if (["trace", "observe", "preserve"].includes(mode)) {
    return Object.fromEntries(nodes.map((node, index) => [node.id, {
      x: 110 + index * Math.min(215, 780 / Math.max(1, nodes.length - 1)),
      y: 260 + ((index % 2) * 120 - 60)
    }]));
  }
  if (mode === "explore") {
    const [center, ...rest] = nodes;
    const positions: NodePositions = center ? { [center.id]: { x: 470, y: 270 } } : {};
    rest.forEach((node, index) => {
      const angle = (Math.PI * 2 * index) / Math.max(1, rest.length) - Math.PI / 2;
      positions[node.id] = { x: 470 + Math.cos(angle) * 300, y: 270 + Math.sin(angle) * 190 };
    });
    return positions;
  }
  return grid(nodes, Math.min(3, Math.max(1, Math.ceil(Math.sqrt(nodes.length)))), 110, 100, 310, 195);
}

export function edgePath(source: Point, target: Point): string {
  const sx = source.x + 80;
  const sy = source.y + 28;
  const tx = target.x - 80;
  const ty = target.y + 28;
  const bend = Math.max(35, Math.abs(tx - sx) * 0.45);
  return `M ${sx} ${sy} C ${sx + bend} ${sy}, ${tx - bend} ${ty}, ${tx} ${ty}`;
}
