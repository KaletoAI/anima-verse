/** JSON shape adapters for E4 row vectors. No sampling or expected-value logic lives here.
 * rng/jitterRng are finite streams; axisFrom is {line, ring, sides}; occupied is
 * a list of {x,z,r,tag?} additions. Occupancy operations return blocks answers and sample results in order.
 * decorateStroke adds pointCount/xs projections; seeded amplitudes stay inline.
 */
export function rowVectorDispatch(scatter, axis, occupancy, stroke) {
  const stream = (values) => {
    let i = 0;
    return () => {
      if (i === values.length) throw new Error('row RNG stream exhausted');
      return values[i++];
    };
  };
  const grid = (entries) => {
    const g = new occupancy.OccupancyGrid();
    for (const { x, z, r, tag } of entries) g.add(x, z, r, tag);
    return g;
  };
  const options = (input) => {
    const out = { ...input };
    for (const k of ['rng', 'jitterRng']) if (Array.isArray(out[k])) out[k] = stream(out[k]);
    if (out.axisFrom) {
      const { line, ring, sides } = out.axisFrom;
      out.axisAt = axis.areaAxis(line, ring, sides);
      delete out.axisFrom;
    }
    if (Array.isArray(out.occupied)) out.occupied = grid(out.occupied);
    return out;
  };
  return {
    ringEdgeAxis: axis.ringEdgeAxis,
    lineAxis: axis.lineAxis,
    areaAxis: ({ line, ring, sides, at }) => axis.areaAxis(line, ring, sides)(...at),
    ringSelectedEdges: axis.ringSelectedEdges,
    ribbonSelectedEdges: axis.ribbonSelectedEdges,
    polylabel: axis.polylabel,
    ringStations: (ring, opts) => axis.ringStations(ring, options(opts)),
    scatterEdgeInstances: (ring, opts) => axis.scatterEdgeInstances(ring, options(opts)),
    scatterCenterInstance: (ring, opts) => axis.scatterCenterInstance(ring, options(opts)),
    scatterInstances: (opts) => scatter.scatterInstances(options(opts)),
    scatterCellInstances: (opts) => scatter.scatterCellInstances(options(opts)),
    occupancy: (ops, routed = false) => {
      const g = routed ? occupancy.cellOccupancy(new Map()).grid : grid([]);
      const answers = [];
      for (const { op, x, z, r, tag, fn, options: input, ring } of ops) {
        if (op === 'add') g.add(x, z, r, tag);
        else if (op === 'blocks') answers.push(g.blocks(x, z, r, tag));
        else if (op === 'sample') {
          const opts = { ...options(input), occupied: g };
          if (fn === 'scatterInstances') answers.push(scatter.scatterInstances(opts));
          else if (fn === 'scatterCellInstances') answers.push(scatter.scatterCellInstances(opts));
          else if (fn === 'scatterEdgeInstances') answers.push(axis.scatterEdgeInstances(ring, opts));
          else throw new Error(`unknown occupancy sampler: ${fn}`);
        } else throw new Error(`unknown occupancy op: ${op}`);
      }
      return answers;
    },
    strokeStations: (opts) => stroke.strokeStations(options(opts)),
    alongSeed: stroke.alongSeed,
    strokeCentreLine: stroke.strokeCentreLine,
    decorateStroke: (...args) => {
      const result = stroke.decorateStroke(...args);
      return { ...result, pointCount: result.points.length, xs: result.points.map(p => p[0]) };
    },
  };
}
