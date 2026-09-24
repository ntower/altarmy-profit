import { createContext, useContext, useMemo, type ReactNode } from 'react'
import { ActionIcon, Button, Group, Loader, Menu, Text, useComputedColorScheme } from '@mantine/core'
import { Controls, Handle, Panel, Position, ReactFlow, type NodeProps, type NodeTypes } from '@xyflow/react'
import type { FlowNode, ItemMap, RankResult } from '../api/client'
import { SELL_PATH } from '../lib/choices'
import { buildFlow, type ItemFlowNode, type MailFlowNode, type SellFlowNode } from '../lib/flow'
import { formatMoney } from '../lib/money'
import { CharacterName } from './CharacterName'
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

/** Picks another source (or exit) at a tree path; absent when the chart is read-only. */
const ChooseContext = createContext<((path: string, key: string) => void) | undefined>(undefined)

type Choice = { key: string; label: ReactNode; amount: string; current: boolean }

/** The button in a node's top-right corner listing its alternatives, best first. */
function ChoiceMenu({ label, path, choices }: { label: string; path: string; choices: Choice[] }) {
  const onChoose = useContext(ChooseContext)
  if (!onChoose || choices.length < 2) return null
  return (
    <Menu position="bottom-end" shadow="md" withinPortal>
      <Menu.Target>
        <ActionIcon className={`nodrag nopan ${classes.menu}`} variant="subtle" size="xs" aria-label={label}>
          ⇄
        </ActionIcon>
      </Menu.Target>
      {/* Portalled in the browser, but inline in tests: either way, clicks in it must not pan the chart. */}
      <Menu.Dropdown className="nodrag nopan">
        {choices.map((c) => (
          <Menu.Item
            key={c.key}
            leftSection={<span className={classes.check}>{c.current ? '✓' : ''}</span>}
            rightSection={
              <Text span size="xs" c="dimmed" ff="monospace">
                {c.amount}
              </Text>
            }
            fw={c.current ? 600 : undefined}
            onClick={() => !c.current && onChoose(path, c.key)}
          >
            {c.label}
          </Menu.Item>
        ))}
      </Menu.Dropdown>
    </Menu>
  )
}

/** A source option as a menu line: crafts name the crafter, and say so when they mail it to `holder`. */
function optionLabel({ source, via, crafter }: FlowNode['options'][number], holder: string): ReactNode {
  if (!via) return `Buy ${BUY_FROM[source] ?? source}`
  return (
    <>
      Craft ({via})
      {crafter && (
        <>
          {' '}
          by <CharacterName name={crafter} />
          {crafter !== holder && holder ? ', mailed' : ''}
        </>
      )}
    </>
  )
}

function ItemNode({ data, items }: NodeProps<ItemFlowNode> & { items: ItemMap }) {
  const { itemId, name, quantity, cost, via, crafts, made, source, crafter, isLeaf, path, options, option, holder } =
    data
  const spare = made - quantity
  return (
    <div className={classes.node}>
      {!isLeaf && <Handle type="target" position={Position.Left} className={classes.handle} />}
      <div className={classes.title}>
        <span className={classes.quantity}>{quantity}x</span>
        <span className={`nodrag nopan ${classes.name}`}>
          <ItemLink item={items[itemId]} name={name} truncate />
        </span>
        <ChoiceMenu
          label={`Change source of ${name}`}
          path={path}
          choices={options.map((o) => ({
            key: o.key,
            label: optionLabel(o, holder),
            amount: formatMoney(-o.cost),
            current: o.key === option,
          }))}
        />
      </div>
      <div className={classes.detail}>
        {via
          ? `Craft ${crafts}x ${via}${spare > 0 ? ` (${spare} spare)` : ''}`
          : `Buy ${BUY_FROM[source] ?? source} · ${formatMoney(-cost)}`}
      </div>
      {crafter && (
        <div className={classes.detail}>
          <CharacterName name={crafter} />
        </div>
      )}
      <Handle type="source" position={Position.Right} className={classes.handle} />
    </div>
  )
}

function MailNode({ data: { to, postage, quantity } }: NodeProps<MailFlowNode>) {
  return (
    <div className={classes.node}>
      <Handle type="target" position={Position.Left} className={classes.handle} />
      <div className={classes.title}>
        <span>
          Mail {quantity}x to <CharacterName name={to} />
        </span>
      </div>
      <div className={classes.detail}>Postage · {formatMoney(-postage)}</div>
      <Handle type="source" position={Position.Right} className={classes.handle} />
    </div>
  )
}

function SellNode({
  data: { exit, revenue, profit, seller, options },
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
        <ChoiceMenu
          label="Change how it is sold"
          path={SELL_PATH}
          choices={options.map((o) => ({
            key: o.kind,
            label: SELL_TEXT[o.kind] ?? `Sell via ${o.kind}`,
            amount: `profit ${formatMoney(o.profit)}`,
            current: o.kind === exit,
          }))}
        />
      </div>
      <div className={classes.detail}>
        +{formatMoney(revenue)} · profit{' '}
        <span style={{ color: `var(--mantine-color-${profit < 0 ? 'red' : 'teal'}-text)` }}>
          {formatMoney(profit)}
        </span>
      </div>
      {exit === 'disenchant' && seller && (
        <div className={classes.detail}>
          <CharacterName name={seller} />
        </div>
      )}
    </div>
  )
}

/** Makes the flow chart editable: nodes with alternatives get a menu of them. */
export type FlowEditing = {
  onChoose: (path: string, key: string) => void
  /** The user changed something: offer Reset. */
  modified: boolean
  onReset: () => void
  /** The changed plan is being re-costed. */
  pending: boolean
  error: string | null
}

/** A recipe's reagent tree as a left-to-right flow chart: bought reagents, crafts, mailing, then the sale. */
export function RecipeFlow({ result, items, editing }: { result: RankResult; items: ItemMap; editing?: FlowEditing }) {
  const colorScheme = useComputedColorScheme('light')
  const flow = useMemo(() => buildFlow(result), [result])
  const nodeTypes = useMemo<NodeTypes>(
    () => ({
      item: (props: NodeProps<ItemFlowNode>) => <ItemNode {...props} items={items} />,
      mail: MailNode,
      sell: (props: NodeProps<SellFlowNode>) => <SellNode {...props} result={result} items={items} />,
    }),
    [result, items],
  )
  return (
    <ChooseContext.Provider value={editing?.onChoose}>
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
          {editing && (editing.modified || editing.error) && (
            <Panel position="top-right" className="nodrag nopan">
              <Group gap="xs">
                {editing.pending && <Loader size="xs" aria-label="Re-costing" />}
                {editing.error && (
                  <Text size="xs" c="red">
                    {editing.error}
                  </Text>
                )}
                <Button size="compact-xs" variant="light" onClick={editing.onReset}>
                  Reset
                </Button>
              </Group>
            </Panel>
          )}
        </ReactFlow>
      </div>
    </ChooseContext.Provider>
  )
}
