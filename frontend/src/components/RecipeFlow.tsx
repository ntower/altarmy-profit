import { useMemo } from 'react'
import { useComputedColorScheme } from '@mantine/core'
import { Controls, Handle, Position, ReactFlow, type NodeProps, type NodeTypes } from '@xyflow/react'
import type { ItemMap, RankResult } from '../api/client'
import { buildFlow, type ItemFlowNode, type SellFlowNode } from '../lib/flow'
import { formatMoney } from '../lib/money'
import { DisenchantHover, ItemLink } from './ItemTooltip'
import classes from './RecipeFlow.module.css'

const MAX_HEIGHT = 480
const PADDING = 32

const BUY_FROM: Record<string, string> = { ah: 'on the AH', vendor: 'from a vendor' }

const SELL_TEXT: Record<string, string> = {
  ah: 'Sell on the AH',
  vendor: 'Sell to a vendor',
  disenchant: 'Disenchant, sell the materials',
}

function ItemNode({ data, items }: NodeProps<ItemFlowNode> & { items: ItemMap }) {
  const { itemId, name, quantity, cost, via, crafts, made, source, isLeaf } = data
  const spare = made - quantity
  return (
    <div className={classes.node}>
      {!isLeaf && <Handle type="target" position={Position.Left} className={classes.handle} />}
      <div className={classes.title}>
        <span className="nodrag nopan">
          <ItemLink item={items[itemId]} name={name} />
        </span>
        <span>{quantity}x</span>
      </div>
      <div className={classes.detail}>
        {via
          ? `Craft ${crafts}x ${via}${spare > 0 ? ` (${spare} spare)` : ''}`
          : `Buy ${BUY_FROM[source] ?? source} · ${formatMoney(-cost)}`}
      </div>
      <Handle type="source" position={Position.Right} className={classes.handle} />
    </div>
  )
}

function SellNode({
  data: { exit, revenue, profit },
  result,
  items,
}: NodeProps<SellFlowNode> & { result: RankResult; items: ItemMap }) {
  const text = SELL_TEXT[exit] ?? `Sell via ${exit}`
  return (
    <div className={`${classes.node} ${classes.sell}`}>
      <Handle type="target" position={Position.Left} className={classes.handle} />
      <div className={classes.title}>
        {exit === 'disenchant' ? (
          <span className="nodrag nopan">
            <DisenchantHover result={result} items={items}>
              {text}
            </DisenchantHover>
          </span>
        ) : (
          <span>{text}</span>
        )}
      </div>
      <div className={classes.detail}>
        +{formatMoney(revenue)} · profit{' '}
        <span style={{ color: `var(--mantine-color-${profit < 0 ? 'red' : 'teal'}-text)` }}>
          {formatMoney(profit)}
        </span>
      </div>
    </div>
  )
}

/** A recipe's reagent tree as a left-to-right flow chart: bought reagents, crafts, then the sale. */
export function RecipeFlow({ result, items }: { result: RankResult; items: ItemMap }) {
  const colorScheme = useComputedColorScheme('light')
  const flow = useMemo(() => buildFlow(result), [result])
  const nodeTypes = useMemo<NodeTypes>(
    () => ({
      item: (props: NodeProps<ItemFlowNode>) => <ItemNode {...props} items={items} />,
      sell: (props: NodeProps<SellFlowNode>) => <SellNode {...props} result={result} items={items} />,
    }),
    [result, items],
  )
  return (
    <div style={{ height: Math.min(flow.height + PADDING * 2, MAX_HEIGHT) }}>
      <ReactFlow
        nodes={flow.nodes}
        edges={flow.edges}
        nodeTypes={nodeTypes}
        colorMode={colorScheme}
        style={{ background: 'transparent' }}
        fitView
        fitViewOptions={{ padding: `${PADDING}px`, maxZoom: 1 }}
        minZoom={0.3}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        zoomOnScroll={false}
        preventScrolling={false}
        proOptions={{ hideAttribution: true }}
      >
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}
