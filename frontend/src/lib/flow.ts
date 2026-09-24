/** Turns a recipe's reagent tree into a laid-out React Flow graph: inputs on the left, the sale on the right. */
import dagre from '@dagrejs/dagre'
import type { Edge, Node } from '@xyflow/react'
import type { FlowNode, RankResult } from '../api/client'

export const NODE_WIDTH = 220
export const NODE_HEIGHT = 64
/** Room for a third line: the character who buys or crafts the item. */
export const NAMED_NODE_HEIGHT = 80

export type ItemNodeData = {
  itemId: number
  name: string
  quantity: number
  cost: number
  via: string
  crafts: number
  made: number
  source: string
  crafter: string
  isLeaf: boolean
}
/** `seller`: who sells (or disenchants): the enchanter the output is mailed to, else the crafter. */
export type SellNodeData = { exit: string; revenue: number; profit: number; quantity: number; seller: string }
export type MailNodeData = { to: string; postage: number; quantity: number }
export type ItemFlowNode = Node<ItemNodeData, 'item'>
export type SellFlowNode = Node<SellNodeData, 'sell'>
export type MailFlowNode = Node<MailNodeData, 'mail'>

export type Flow = {
  nodes: (ItemFlowNode | SellFlowNode | MailFlowNode)[]
  edges: Edge[]
  width: number
  height: number
}

/** Ids are tree paths ("r", "r.0", "r.0.1"), so an item used in two branches gets two nodes. When the output
 * has to be mailed to whoever sells it (an enchanter), a mail node sits between the craft and the sale; likewise
 * between an intermediate and the craft using it when another character makes it. */
export function buildFlow({
  tree,
  best_exit,
  revenue,
  profit,
  postage,
  mail_to,
}: Pick<RankResult, 'tree' | 'best_exit' | 'revenue' | 'profit' | 'postage' | 'mail_to'>): Flow {
  const nodes: Flow['nodes'] = []
  const edges: Edge[] = []
  const edge = (source: string, target: string, quantity: number) =>
    edges.push({ id: `${source}->${target}`, source, target, label: `${quantity}x`, type: 'smoothstep' })

  /** A mail node between `from` and `to`: `from`'s crafter sends `quantity` to `recipient`. */
  const mail = (from: string, to: string, recipient: string, postage: number, quantity: number) => {
    const id = `${from}.mail`
    nodes.push({ id, type: 'mail', position: { x: 0, y: 0 }, data: { to: recipient, postage, quantity } })
    edge(from, id, quantity)
    edge(id, to, quantity)
  }

  let named = false
  const visit = (node: FlowNode, id: string) => {
    const { item_id, name, quantity, cost, via, crafts, made, source, crafter, inputs } = node
    if (crafter) named = true
    nodes.push({
      id,
      type: 'item',
      position: { x: 0, y: 0 },
      data: {
        itemId: item_id,
        name,
        quantity,
        cost,
        via,
        crafts,
        made,
        source,
        crafter,
        isLeaf: inputs.length === 0,
      },
    })
    inputs.forEach((input, i) => {
      const child = `${id}.${i}`
      visit(input, child)
      if (input.mail_to) mail(child, id, input.mail_to, input.postage, input.quantity)
      else edge(child, id, input.quantity)
    })
  }
  visit(tree, 'r')
  nodes.push({
    id: 'sell',
    type: 'sell',
    position: { x: 0, y: 0 },
    data: { exit: best_exit, revenue, profit, quantity: tree.made, seller: mail_to || tree.crafter },
  })
  if (mail_to) mail('r', 'sell', mail_to, postage, tree.made)
  else edge('r', 'sell', tree.made)

  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', nodesep: 16, ranksep: 56, marginx: 0, marginy: 0 })
  g.setDefaultEdgeLabel(() => ({}))
  // One height for every node keeps each rank's boxes aligned.
  const nodeHeight = named ? NAMED_NODE_HEIGHT : NODE_HEIGHT
  for (const n of nodes) g.setNode(n.id, { width: NODE_WIDTH, height: nodeHeight })
  for (const e of edges) g.setEdge(e.source, e.target)
  dagre.layout(g)

  for (const n of nodes) {
    const { x, y } = g.node(n.id)
    // dagre gives centres; React Flow wants top-left corners. Fixed sizes let it skip measuring.
    n.position = { x: x - NODE_WIDTH / 2, y: y - nodeHeight / 2 }
    n.width = NODE_WIDTH
    n.height = nodeHeight
    // React Flow turns pointer events off on nodes that can't be selected or dragged; item tooltips need them.
    n.style = { pointerEvents: 'all' }
  }
  const { width = 0, height = 0 } = g.graph()
  return { nodes, edges, width, height }
}
