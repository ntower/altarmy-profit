import { Fragment, useState, type ReactNode } from 'react'
import { List, SegmentedControl, Stack, Table, Text, UnstyledButton } from '@mantine/core'
import type { ItemMap, RankResult } from '../api/client'
import { formatMoney, formatRoi } from '../lib/money'
import { DisenchantHover, Hover, ItemLink, RecipeTooltip } from './ItemTooltip'
import { RecipeFlow } from './RecipeFlow'
import classes from './ResultsTable.module.css'

const COLUMNS = ['', 'Profit', 'ROI', 'Recipe', 'Profession', 'Crafter', 'Output', 'Cost', 'Revenue', 'Sell via']
/** Widths (px) for columns that should not just fit their content: crafter lists wrap, money gets room. */
const COLUMN_WIDTHS: Readonly<Record<string, number>> = { Crafter: 219, Cost: 133, Revenue: 133 }

type Step = RankResult['steps'][number]

const signedMoney = (copper: number) => (copper > 0 ? '+' : '') + formatMoney(copper)

/** A step as one or more instruction lines; disenchanting splits into disenchant, then sell the mats. */
function describe(
  { action, item_id, name, quantity, value, via }: Step,
  result: RankResult,
  items: ItemMap,
): ReactNode[] {
  const item = <ItemLink item={items[item_id]} name={name} />
  switch (action) {
    case 'buy':
      return [
        <>
          Purchase {quantity}x {item} {via === 'vendor' ? 'from a vendor' : 'on the AH'} ({signedMoney(value)})
        </>,
      ]
    case 'craft':
      return [
        <>
          Craft {quantity}x {item}
        </>,
      ]
    case 'sell':
      if (via === 'disenchant')
        return [
          <>
            Disenchant {quantity > 1 ? `${quantity}x ` : ''}
            {item}
          </>,
          <>
            <DisenchantHover result={result} items={items}>
              Sell materials
            </DisenchantHover>{' '}
            ({signedMoney(value)})
          </>,
        ]
      return [
        <>
          Sell {quantity}x {item} {via === 'ah' ? 'on the AH' : 'to a vendor'} ({signedMoney(value)})
        </>,
      ]
  }
}

function StepList({ result, items }: { result: RankResult; items: ItemMap }) {
  return (
    <List type="ordered" size="sm">
      {result.steps
        .flatMap((step) => describe(step, result, items))
        .map((line, i) => (
          <List.Item key={i}>{line}</List.Item>
        ))}
    </List>
  )
}

type View = 'flow' | 'steps'

function Details({ result, items }: { result: RankResult; items: ItemMap }) {
  const [view, setView] = useState<View>('flow')
  return (
    <Stack gap="xs" py="xs">
      <SegmentedControl
        size="xs"
        w="fit-content"
        value={view}
        onChange={(v) => setView(v as View)}
        data={[
          { value: 'flow', label: 'Flow' },
          { value: 'steps', label: 'Steps' },
        ]}
      />
      {view === 'flow' ? <RecipeFlow result={result} items={items} /> : <StepList result={result} items={items} />}
    </Stack>
  )
}

export function ResultsTable({ results, items }: { results: RankResult[]; items: ItemMap }) {
  const [open, setOpen] = useState<ReadonlySet<number>>(new Set())
  const toggle = (id: number) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  return (
    <Table.ScrollContainer minWidth={800}>
      <Table striped highlightOnHover stickyHeader>
        <Table.Thead>
          <Table.Tr>
            {COLUMNS.map((c) => (
              <Table.Th key={c} w={COLUMN_WIDTHS[c]}>
                {c}
              </Table.Th>
            ))}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {results.map((r) => {
            const expanded = open.has(r.recipe_id)
            return (
              <Fragment key={r.recipe_id}>
                <Table.Tr onClick={() => toggle(r.recipe_id)} style={{ cursor: 'pointer' }}>
                  <Table.Td>
                    <UnstyledButton
                      aria-expanded={expanded}
                      aria-label={`Details for ${r.recipe}`}
                      onClick={(e) => {
                        e.stopPropagation()
                        toggle(r.recipe_id)
                      }}
                    >
                      {expanded ? '▾' : '▸'}
                    </UnstyledButton>
                  </Table.Td>
                  <Table.Td c={r.profit < 0 ? 'red' : 'teal'} ff="monospace">
                    {formatMoney(r.profit)}
                  </Table.Td>
                  <Table.Td>{formatRoi(r.roi)}</Table.Td>
                  <Table.Td>
                    <Hover
                      tooltip={
                        <RecipeTooltip
                          name={r.recipe}
                          profession={r.profession}
                          reagents={r.reagents}
                          output={items[r.output_item_id]}
                          items={items}
                        />
                      }
                    >
                      {r.recipe}
                    </Hover>
                  </Table.Td>
                  <Table.Td>{r.profession}</Table.Td>
                  <Table.Td>
                    {r.crafters.length ? (
                      r.crafters.join(', ')
                    ) : (
                      <Text span size="sm" c="dimmed">
                        not learned
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    {r.output_count}x <ItemLink item={items[r.output_item_id]} name={r.output_name} />
                  </Table.Td>
                  <Table.Td ff="monospace">{formatMoney(r.cost)}</Table.Td>
                  <Table.Td ff="monospace">{formatMoney(r.revenue)}</Table.Td>
                  <Table.Td>{r.best_exit}</Table.Td>
                </Table.Tr>
                {expanded && (
                  <Table.Tr className={classes.details}>
                    <Table.Td />
                    <Table.Td colSpan={COLUMNS.length - 1}>
                      <Details result={r} items={items} />
                    </Table.Td>
                  </Table.Tr>
                )}
              </Fragment>
            )
          })}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  )
}
