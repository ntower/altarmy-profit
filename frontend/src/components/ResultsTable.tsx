import { Fragment, useMemo, useState, type ReactNode } from 'react'
import { List, SegmentedControl, Stack, Table, Text, UnstyledButton } from '@mantine/core'
import type { ItemMap, RankResult } from '../api/client'
import { useEvaluations, type EvaluateParams } from '../api/queries'
import { choose, type Choices } from '../lib/choices'
import { formatMoney, formatRoi } from '../lib/money'
import { CharacterClasses, CharacterName } from './CharacterName'
import { DisenchantHover, Hover, ItemLink, RecipeTooltip } from './ItemTooltip'
import { RecipeFlow, type FlowEditing } from './RecipeFlow'
import classes from './ResultsTable.module.css'

const COLUMNS = ['', 'Profit', 'ROI', 'Recipe', 'Profession', 'Crafter', 'Output', 'Cost', 'Revenue', 'Sell via']
/** Sort key per sortable column; numbers sort largest first on the first click, text alphabetically. */
const SORT_KEYS: Readonly<Record<string, (r: RankResult) => number | string>> = {
  Profit: (r) => r.profit,
  ROI: (r) => r.roi,
  Recipe: (r) => r.recipe,
  Profession: (r) => r.profession,
  Crafter: (r) => (r.crafters.length ? r.crafter : ''),
  Output: (r) => r.output_name,
  Cost: (r) => r.cost,
  Revenue: (r) => r.revenue,
  'Sell via': (r) => r.best_exit,
}
const NUMERIC_COLUMNS: ReadonlySet<string> = new Set(['Profit', 'ROI', 'Cost', 'Revenue'])
/** Widths (px) for columns that should not just fit their content: crafter lists wrap, money gets room. */
const COLUMN_WIDTHS: Readonly<Record<string, number>> = { Crafter: 219, Cost: 133, Revenue: 133 }

type Step = RankResult['steps'][number]
type Sort = { column: string; descending: boolean }

/** `results` ordered by `sort`, stably; unsorted keeps the server's order (profit, best first). */
function sorted(results: RankResult[], sort: Sort | null): RankResult[] {
  if (!sort) return results
  const key = SORT_KEYS[sort.column]
  const sign = sort.descending ? -1 : 1
  return results.toSorted((a, b) => {
    const x = key(a)
    const y = key(b)
    const c = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y))
    return sign * c
  })
}

const signedMoney = (copper: number) => (copper > 0 ? '+' : '') + formatMoney(copper)

/** A step as one or more instruction lines, prefixed with who does it; disenchanting splits into disenchant,
 * then sell the mats. */
function describe(step: Step, result: RankResult, items: ItemMap): ReactNode[] {
  const lines = describeAction(step, result, items)
  return step.who
    ? lines.map((l) => (
        <>
          <CharacterName name={step.who} />: {l}
        </>
      ))
    : lines
}

function describeAction(
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
    case 'mail':
      return [
        <>
          Mail {quantity}x {item} to <CharacterName name={via} /> ({signedMoney(value)})
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

/** The characters who know the recipe, the one doing the craft first. */
const byCrafter = (crafters: string[], crafter: string) =>
  crafters.includes(crafter) ? [crafter, ...crafters.filter((c) => c !== crafter)] : crafters

type View = 'flow' | 'steps'

function Details({ result, items, editing }: { result: RankResult; items: ItemMap; editing: FlowEditing }) {
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
      {view === 'flow' ? (
        <RecipeFlow result={result} items={items} editing={editing} />
      ) : (
        <StepList result={result} items={items} />
      )}
    </Stack>
  )
}

const DEFAULT_PARAMS: EvaluateParams = { includeUnlearned: false, exits: ['vendor', 'ah', 'disenchant'] }

export function ResultsTable({
  results,
  items: rankItems,
  classes: characterClasses = {},
  params = DEFAULT_PARAMS,
}: {
  results: RankResult[]
  items: ItemMap
  /** Character name -> class file, for class-coloured names. */
  classes?: Readonly<Record<string, string>>
  /** The search the results came from: a recipe whose plan the user changes is re-costed the same way. */
  params?: EvaluateParams
}) {
  const [open, setOpen] = useState<ReadonlySet<number>>(new Set())
  const toggle = (id: number) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  const [sort, setSort] = useState<Sort | null>(null)
  const sortBy = (column: string) =>
    setSort((prev) =>
      prev?.column === column
        ? { column, descending: !prev.descending }
        : { column, descending: NUMERIC_COLUMNS.has(column) },
    )
  // The user's changes to each recipe's plan, by recipe id; a row shows its changed plan once it is costed.
  const [choices, setChoices] = useState<Readonly<Record<number, Choices>>>({})
  const evaluations = useEvaluations(choices, params)
  const current = useMemo(
    () => results.map((r) => (choices[r.recipe_id] && evaluations[r.recipe_id]?.data?.result) || r),
    [results, choices, evaluations],
  )
  const items = useMemo(
    () => Object.assign({}, rankItems, ...Object.values(evaluations).map((e) => e.data?.items ?? {})) as ItemMap,
    [rankItems, evaluations],
  )
  const rows = useMemo(() => sorted(current, sort), [current, sort])
  const editing = (id: number): FlowEditing => {
    const evaluation = evaluations[id]
    return {
      onChoose: (path, key) => setChoices((prev) => ({ ...prev, [id]: choose(prev[id] ?? {}, path, key) })),
      modified: id in choices,
      onReset: () => setChoices((prev) => Object.fromEntries(Object.entries(prev).filter(([k]) => Number(k) !== id))),
      pending: evaluation?.isFetching ?? false,
      error: evaluation?.error?.message ?? null,
    }
  }

  return (
    <CharacterClasses.Provider value={characterClasses}>
      <Table.ScrollContainer minWidth={800}>
        <Table striped highlightOnHover stickyHeader>
          <Table.Thead>
            <Table.Tr>
              {COLUMNS.map((c) => {
                const active = sort?.column === c
                return (
                  <Table.Th
                    key={c}
                    w={COLUMN_WIDTHS[c]}
                    aria-sort={!(c in SORT_KEYS) ? undefined : !active ? 'none' : sort.descending ? 'descending' : 'ascending'}
                  >
                    {c in SORT_KEYS ? (
                      <UnstyledButton className={classes.sort} aria-label={`Sort by ${c}`} onClick={() => sortBy(c)}>
                        {c}
                        <span className={classes.arrow} data-active={active || undefined}>
                          {active && !sort.descending ? '▲' : '▼'}
                        </span>
                      </UnstyledButton>
                    ) : (
                      c
                    )}
                  </Table.Th>
                )
              })}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((r) => {
              const expanded = open.has(r.recipe_id)
              const modified = r.recipe_id in choices
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
                      {modified && (
                        <Text span c="yellow" ml={4} title="Your changed plan, not the best one" aria-label="Changed plan">
                          ●
                        </Text>
                      )}
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
                        byCrafter(r.crafters, r.crafter).map((c, i) => (
                          <Fragment key={c}>
                            {i > 0 && ', '}
                            <CharacterName name={c} />
                          </Fragment>
                        ))
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
                        <Details result={r} items={items} editing={editing(r.recipe_id)} />
                      </Table.Td>
                    </Table.Tr>
                  )}
                </Fragment>
              )
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </CharacterClasses.Provider>
  )
}
