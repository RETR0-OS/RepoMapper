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
    // Cards are 160 wide and sit on two rows, so neighbours on one row are two
    // steps apart. A step below 80 makes them overlap, and the card on top then
    // takes the click of the card below it. Pan and zoom show any extra width.
    const step = Math.max(110, Math.min(215, 780 / Math.max(1, nodes.length - 1)));
    return Object.fromEntries(nodes.map((node, index) => [node.id, {
      x: 110 + index * step,
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
  // 37 is the vertical middle of a node card, which is 74 tall.
  const sx = source.x + 80;
  const sy = source.y + 37;
  const tx = target.x - 80;
  const ty = target.y + 37;
  const bend = Math.max(35, Math.abs(tx - sx) * 0.45);
  return `M ${sx} ${sy} C ${sx + bend} ${sy}, ${tx - bend} ${ty}, ${tx} ${ty}`;
}

export function computeTraversalLayout(
  tracks: Array<Array<{ nodeIds: string[]; trackIndex: number; stepIndex: number }>>,
  nodes: readonly { id: string }[]
): NodePositions {
  const positions: NodePositions = {};
  const nodeTrackMap = new Map<string, { trackIndex: number; stepIndex: number }>();

  for (const track of tracks) {
    for (const step of track) {
      for (const nodeId of step.nodeIds) {
        if (!nodeTrackMap.has(nodeId)) {
          nodeTrackMap.set(nodeId, { trackIndex: step.trackIndex, stepIndex: step.stepIndex });
        }
      }
    }
  }

  for (const node of nodes) {
    const placement = nodeTrackMap.get(node.id);
    if (placement) {
      positions[node.id] = {
        x: 120 + placement.stepIndex * 220,
        y: 200 + placement.trackIndex * 180
      };
    }
  }

  return positions;
}
