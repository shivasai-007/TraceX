import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY } from 'd3-force'

/**
 * Interactive fund-flow graph.
 *
 * Built directly on SVG plus a d3-force simulation rather than a graph
 * library, for two reasons that matter here: the investigator needs to see
 * direction and amount on every edge (most off-the-shelf components hide
 * one or both), and the node styling has to carry meaning -- focus wallet,
 * known entity, mixer -- rather than being decorative.
 *
 * Interaction: drag to reposition a node, drag the background to pan,
 * scroll to zoom, click a node to inspect it. Motion is limited to the
 * layout settling and is skipped entirely under prefers-reduced-motion.
 */

const WIDTH = 900
const HEIGHT = 560

function shortAddr(addr) {
  if (!addr) return ''
  return addr.length > 16 ? `${addr.slice(0, 8)}…${addr.slice(-6)}` : addr
}

function nodeAppearance(node) {
  if (node.isFocus) return { fill: 'var(--node-focus)', r: 13, stroke: 'var(--node-focus)' }
  if (node.entityType === 'mixer') return { fill: 'var(--node-mixer)', r: 10, stroke: 'var(--node-mixer)' }
  if (node.kind === 'known_entity') return { fill: 'var(--node-entity)', r: 10, stroke: 'var(--node-entity)' }
  return { fill: 'var(--node-wallet)', r: 7, stroke: 'var(--graph-edge)' }
}

export default function GraphCanvas({ graph, focusAddress, onSelectNode }) {
  const svgRef = useRef(null)
  const simRef = useRef(null)
  const [positions, setPositions] = useState({})
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 })
  const [hovered, setHovered] = useState(null)
  const [selected, setSelected] = useState(null)
  const [dragging, setDragging] = useState(null)
  const panRef = useRef(null)

  const { nodes, edges } = useMemo(() => {
    if (!graph) return { nodes: [], edges: [] }
    return {
      nodes: graph.nodes.map((n) => ({ ...n })),
      edges: graph.edges.map((e) => ({ ...e })),
    }
  }, [graph])

  // Aggregate parallel edges: two wallets may exchange 40 transactions, and
  // 40 overlapping arrows tell an investigator less than one arrow labelled
  // "40 transfers, 12.4 ETH total".
  const aggregatedEdges = useMemo(() => {
    const map = new Map()
    edges.forEach((e) => {
      const key = `${e.source}->${e.target}`
      const existing = map.get(key)
      if (existing) {
        existing.count += 1
        existing.total += Number(e.value) || 0
        existing.txHashes.push(e.txHash)
      } else {
        map.set(key, {
          key,
          source: e.source,
          target: e.target,
          count: 1,
          total: Number(e.value) || 0,
          asset: e.asset,
          txHashes: [e.txHash],
        })
      }
    })
    return [...map.values()]
  }, [edges])

  useEffect(() => {
    if (!nodes.length) return undefined

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const simNodes = nodes.map((n) => ({ ...n }))
    const simLinks = aggregatedEdges.map((e) => ({ ...e }))

    const simulation = forceSimulation(simNodes)
      .force('link', forceLink(simLinks).id((d) => d.id).distance(110).strength(0.55))
      .force('charge', forceManyBody().strength(-420))
      .force('center', forceCenter(WIDTH / 2, HEIGHT / 2))
      .force('collide', forceCollide(28))
      .force('x', forceX(WIDTH / 2).strength(0.04))
      .force('y', forceY(HEIGHT / 2).strength(0.06))

    const commit = () => {
      const next = {}
      simNodes.forEach((n) => {
        next[n.id] = { x: n.x, y: n.y }
      })
      setPositions(next)
    }

    if (reduceMotion) {
      simulation.stop()
      for (let i = 0; i < 260; i += 1) simulation.tick()
      commit()
    } else {
      simulation.on('tick', commit)
    }

    simRef.current = simulation
    return () => simulation.stop()
  }, [nodes, aggregatedEdges])

  const toLocal = useCallback(
    (event) => {
      const rect = svgRef.current.getBoundingClientRect()
      const scaleX = WIDTH / rect.width
      const scaleY = HEIGHT / rect.height
      return {
        x: ((event.clientX - rect.left) * scaleX - transform.x) / transform.k,
        y: ((event.clientY - rect.top) * scaleY - transform.y) / transform.k,
      }
    },
    [transform],
  )

  const handleWheel = useCallback((event) => {
    event.preventDefault()
    setTransform((t) => {
      const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12
      const k = Math.min(3, Math.max(0.35, t.k * factor))
      return { ...t, k }
    })
  }, [])

  const handlePointerDown = (event) => {
    if (event.target === svgRef.current || event.target.dataset.role === 'backdrop') {
      panRef.current = { startX: event.clientX, startY: event.clientY, origin: { ...transform } }
    }
  }

  const handlePointerMove = (event) => {
    if (dragging) {
      const { x, y } = toLocal(event)
      const sim = simRef.current
      if (sim) {
        const node = sim.nodes().find((n) => n.id === dragging)
        if (node) {
          node.fx = x
          node.fy = y
          sim.alphaTarget(0.25).restart()
        }
      }
      return
    }
    if (panRef.current) {
      const dx = event.clientX - panRef.current.startX
      const dy = event.clientY - panRef.current.startY
      setTransform({ ...panRef.current.origin, x: panRef.current.origin.x + dx, y: panRef.current.origin.y + dy })
    }
  }

  const handlePointerUp = () => {
    if (dragging && simRef.current) {
      const node = simRef.current.nodes().find((n) => n.id === dragging)
      if (node) {
        node.fx = null
        node.fy = null
      }
      simRef.current.alphaTarget(0)
    }
    setDragging(null)
    panRef.current = null
  }

  const selectNode = (node) => {
    setSelected(node.id)
    onSelectNode?.(node)
  }

  const connectedTo = useMemo(() => {
    const active = hovered || selected
    if (!active) return null
    const set = new Set([active])
    aggregatedEdges.forEach((e) => {
      if (e.source === active) set.add(e.target)
      if (e.target === active) set.add(e.source)
    })
    return set
  }, [hovered, selected, aggregatedEdges])

  if (!graph || !nodes.length) {
    return (
      <div className="empty" style={{ minHeight: '18rem', display: 'grid', placeContent: 'center' }}>
        <strong>No graph to show yet</strong>
        The fund-flow graph appears once a trace completes.
      </div>
    )
  }

  const activeNode = hovered || selected

  return (
    <div className="graph-wrap">
      <div className="graph-toolbar">
        <div className="row small muted wrap" style={{ gap: '1rem' }}>
          <span className="graph-legend"><i className="dot dot-focus" /> Suspect wallet</span>
          <span className="graph-legend"><i className="dot dot-entity" /> Known entity</span>
          <span className="graph-legend"><i className="dot dot-mixer" /> Mixer</span>
          <span className="graph-legend"><i className="dot dot-wallet" /> Wallet</span>
        </div>
        <div className="row">
          <span className="tiny muted">
            {nodes.length} wallets · {aggregatedEdges.length} flows
          </span>
          <button className="btn btn-sm btn-quiet" onClick={() => setTransform({ x: 0, y: 0, k: 1 })}>
            Reset view
          </button>
        </div>
      </div>

      <svg
        ref={svgRef}
        className="graph-canvas"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={`Fund-flow graph with ${nodes.length} wallets and ${aggregatedEdges.length} transfer relationships`}
        onWheel={handleWheel}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={handlePointerUp}
      >
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--graph-edge)" />
          </marker>
          <marker id="arrow-active" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--graph-edge-active)" />
          </marker>
          <pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse">
            <path d="M 28 0 L 0 0 0 28" fill="none" stroke="var(--graph-grid)" strokeWidth="1" />
          </pattern>
        </defs>

        <rect data-role="backdrop" width={WIDTH} height={HEIGHT} fill="url(#grid)" />

        <g transform={`translate(${transform.x},${transform.y}) scale(${transform.k})`}>
          {aggregatedEdges.map((edge) => {
            const from = positions[edge.source]
            const to = positions[edge.target]
            if (!from || !to) return null
            const isActive = activeNode === edge.source || activeNode === edge.target
            const dx = to.x - from.x
            const dy = to.y - from.y
            const dist = Math.hypot(dx, dy) || 1
            const pad = 16
            const x1 = from.x + (dx / dist) * pad
            const y1 = from.y + (dy / dist) * pad
            const x2 = to.x - (dx / dist) * pad
            const y2 = to.y - (dy / dist) * pad
            const midX = (x1 + x2) / 2
            const midY = (y1 + y2) / 2
            return (
              <g key={edge.key} opacity={connectedTo && !isActive ? 0.18 : 1}>
                <line
                  x1={x1}
                  y1={y1}
                  x2={x2}
                  y2={y2}
                  stroke={isActive ? 'var(--graph-edge-active)' : 'var(--graph-edge)'}
                  strokeWidth={isActive ? 2 : 1.2}
                  markerEnd={isActive ? 'url(#arrow-active)' : 'url(#arrow)'}
                />
                {isActive && (
                  <text x={midX} y={midY - 5} className="graph-edge-label" textAnchor="middle">
                    {edge.total.toFixed(4)} {edge.asset}
                    {edge.count > 1 ? ` · ${edge.count} tx` : ''}
                  </text>
                )}
              </g>
            )
          })}

          {nodes.map((node) => {
            const pos = positions[node.id]
            if (!pos) return null
            const look = nodeAppearance(node)
            const dim = connectedTo && !connectedTo.has(node.id)
            return (
              <g
                key={node.id}
                transform={`translate(${pos.x},${pos.y})`}
                opacity={dim ? 0.2 : 1}
                style={{ cursor: 'pointer' }}
                onPointerDown={(e) => {
                  e.stopPropagation()
                  setDragging(node.id)
                }}
                onPointerEnter={() => setHovered(node.id)}
                onPointerLeave={() => setHovered(null)}
                onClick={() => selectNode(node)}
                tabIndex={0}
                role="button"
                aria-label={`Wallet ${node.id}${node.entityName ? `, identified as ${node.entityName}` : ''}`}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    selectNode(node)
                  }
                }}
              >
                {node.isFocus && <circle r={look.r + 6} fill="none" stroke="var(--node-focus)" strokeWidth="1" opacity="0.35" />}
                <circle
                  r={look.r}
                  fill={look.fill}
                  stroke={selected === node.id ? 'var(--ink)' : look.stroke}
                  strokeWidth={selected === node.id ? 2.5 : 1}
                />
                <text y={look.r + 14} className="graph-node-label" textAnchor="middle">
                  {node.entityName || shortAddr(node.id)}
                </text>
              </g>
            )
          })}
        </g>
      </svg>

      <p className="tiny muted" style={{ margin: 'var(--space-2) 0 0' }}>
        Drag a wallet to reposition it, drag the background to pan, scroll to zoom. Select a wallet to see its
        details. Parallel transfers between the same two wallets are shown as one flow with a transaction count.
      </p>
    </div>
  )
}
