// "Clean up", like the Finder's: every node goes to the nearest free cell of
// the canvas grid, one node per cell. The grid is the workflow's own layout
// (backend domain/workflow.py: columns 560 apart from x = 120, the global
// assets column, rows 600 apart from y = 60), so workflow nodes that are in
// place stay put and everything else lines up with them.

const GRID = { x0: 120, y0: 60, dx: 560, dy: 600 } as const;

interface Placed {
  id: string;
  position: { x: number; y: number };
}

export interface Move {
  id: string;
  from: { x: number; y: number };
  to: { x: number; y: number };
}

const key = (col: number, row: number) => `${col},${row}`;

/** Where each node goes: the free cell nearest to it. Nodes nearest their
    own cell claim it first, so a node already in place never moves; the
    rest take the closest cell still free, searching outwards ring by ring.
    Only nodes that actually move are returned. Linear in the number of
    nodes (plus a short search for crowded spots). */
export function cleanUpMoves(nodes: Placed[], grid = GRID): Move[] {
  const at = (n: Placed) => ({
    col: (n.position.x - grid.x0) / grid.dx,
    row: (n.position.y - grid.y0) / grid.dy,
  });
  const order = nodes
    .map((node) => {
      const { col, row } = at(node);
      const c = Math.round(col);
      const r = Math.round(row);
      return { node, col, row, off: Math.hypot(col - c, row - r) };
    })
    .sort((a, b) => a.off - b.off || a.row - b.row || a.col - b.col);

  const taken = new Set<string>();
  const moves: Move[] = [];
  for (const { node, col, row } of order) {
    const cell = nearestFree(col, row, taken);
    taken.add(key(cell.col, cell.row));
    const to = { x: grid.x0 + cell.col * grid.dx, y: grid.y0 + cell.row * grid.dy };
    if (to.x !== node.position.x || to.y !== node.position.y) {
      moves.push({ id: node.id, from: node.position, to });
    }
  }
  return moves;
}

/** The free cell closest to (col, row), in cell units. Cells left of the
    first column or above the first row are allowed too: nothing forces
    the canvas to start at the origin. */
function nearestFree(col: number, row: number, taken: Set<string>) {
  const c0 = Math.round(col);
  const r0 = Math.round(row);
  if (!taken.has(key(c0, r0))) return { col: c0, row: r0 };
  for (let ring = 1; ; ring += 1) {
    let best: { col: number; row: number; d: number } | null = null;
    for (let c = c0 - ring; c <= c0 + ring; c += 1) {
      for (let r = r0 - ring; r <= r0 + ring; r += 1) {
        // Only the ring's edge: the inside was searched already.
        if (Math.max(Math.abs(c - c0), Math.abs(r - r0)) !== ring) continue;
        if (taken.has(key(c, r))) continue;
        const d = Math.hypot(c - col, r - row);
        if (!best || d < best.d) best = { col: c, row: r, d };
      }
    }
    if (best) return { col: best.col, row: best.row };
  }
}
