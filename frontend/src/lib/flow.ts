/** Turns a recipe's reagent tree into a laid-out React Flow graph: inputs on the left, the sale on the right. */
import dagre from '@dagrejs/dagre'
import type { Edge, Node } from '@xyflow/react'
import type { FlowNode, RankResult } from '../api/client'

export const NODE_WIDTH = 220
export const NODE_HEIGHT = 64

export type ItemNodeData = {
  itemId: number
  name: string
  quantity: number
  cost: number
  via: string
  crafts: number
  made: number
  source: string
  isLeaf: boolean
}
export type SellNodeData = { exit: string; revenue: number; profit: number; quantity: number }
export type ItemFlowNode = Node<ItemNodeData, 'item'>
export type SellFlowNode = Node<SellNodeData, 'sell'>

export type Flow = {
  nodes: (ItemFlowNode | SellFlowNode)[]
  edges: Edge[]
  width: number
  height: number
}

/** Ids are tree paths ("r", "r.0", "r.0.1"), so an item used in two branches gets two nodes. */
export function buildFlow({
  tree,
  best_exit,
  revenue,
  profit,
}: Pick<RankResult, 'tree' | 'best_exit' | 'revenue' | 'profit'>): Flow {
  const nodes: Flow['nodes'] = []
  const edges: Edge[] = []
  const edge = (source: string, target: string, quantity: number) =>
    edges.push({ id: `${source}->${target}`, source, target, label: `${quantity}x`, type: 'smoothstep' })

  const visit = (node: FlowNode, id: string) => {
    const { item_id, name, quantity, cost, via, crafts, made, source, inputs } = node
    nodes.push({
      id,
      type: 'item',
      position: { x: 0, y: 0 },
      data: { itemId: item_id, name, quantity, cost, via, crafts, made, source, isLeaf: inputs.length === 0 },
    })
    inputs.forEach((input, i) => {
      visit(input, `${id}.${i}`)
      edge(`${id}.${i}`, id, input.quantity)
    })
  }
  visit(tree, 'r')
  nodes.push({
    id: 'sell',
    type: 'sell',
    position: { x: 0, y: 0 },
    data: { exit: best_exit, revenue, profit, quantity: tree.made },
  })
  edge('r', 'sell', tree.made)

  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', nodesep: 16, ranksep: 56, marginx: 0, marginy: 0 })
  g.setDefaultEdgeLabel(() => ({}))
  for (const n of nodes) g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT })
  for (const e of edges) g.setEdge(e.source, e.target)
  dagre.layout(g)

  for (const n of nodes) {
    const { x, y } = g.node(n.id)
    // dagre gives centres; React Flow wants top-left corners. Fixed sizes let it skip measuring.
    n.position = { x: x - NODE_WIDTH / 2, y: y - NODE_HEIGHT / 2 }
    n.width = NODE_WIDTH
    n.height = NODE_HEIGHT
    // React Flow turns pointer events off on nodes that can't be selected or dragged; item tooltips need them.
    n.style = { pointerEvents: 'all' }
  }
  const { width = 0, height = 0 } = g.graph()
  return { nodes, edges, width, height }
}
