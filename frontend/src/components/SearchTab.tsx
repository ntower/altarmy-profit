import { useMemo, useState } from 'react'
import {
  Accordion,
  Alert,
  Button,
  Checkbox,
  Flex,
  Group,
  Loader,
  NumberInput,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Text,
} from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { z } from 'zod'
import type { CharacterGroup, Selection } from '../api/client'
import {
  type Exit,
  type RankParams,
  useAhBlocked,
  useCharacters,
  useDataVersion,
  useRank,
  useSelectRealm,
  useSetAhBlocked,
  useStatus,
} from '../api/queries'
import { goldToCopper } from '../lib/money'
import { useStoredState } from '../lib/storage'
import { CharacterName } from './CharacterName'
import { ResultsTable } from './ResultsTable'

/** Results per page: the first request asks for this many, and each "Show more" for this many more. */
const PAGE = 50

const EXITS: { value: Exit; label: string }[] = [
  { value: 'vendor', label: 'Vendor' },
  { value: 'disenchant', label: 'Disenchant' },
  { value: 'ah', label: 'Auction house' },
]
const ALL_EXITS: Exit[] = EXITS.map((e) => e.value)
const SECTIONS = ['advanced', 'characters'] as const
const NONE_OPEN: (typeof SECTIONS)[number][] = []

const bound = z.number().nullable()
/** NumberInput reports an empty field as ''; that means no bound. */
const toBound = (v: number | string) => (typeof v === 'number' ? v : null)
const scaled = (v: number | null, f: (v: number) => number) => (v === null ? null : f(v))

// Realms may contain spaces but never tabs.
const toKey = (s: Selection) => `${s.realm}\t${s.faction}`
const fromKey = (key: string): Selection => {
  const [realm = '', faction = ''] = key.split('\t')
  return { realm, faction }
}

type Filters = Omit<RankParams, 'top'>

function Results({ filters }: { filters: Filters }) {
  // Back to one page whenever the filters change.
  const [page, setPage] = useState({ filters, top: PAGE })
  const top = page.filters === filters ? page.top : PAGE
  const rank = useRank({ ...filters, top })
  const version = useDataVersion()
  const ahBlockedList = useAhBlocked().data
  const ahBlocked = useMemo(() => new Set(ahBlockedList?.items.map((i) => i.item_id)), [ahBlockedList])
  const { mutate: setAhBlocked } = useSetAhBlocked()
  if (rank.isPending) return <Loader />
  if (rank.isError) return <Alert color="red">{rank.error.message}</Alert>
  const { results, total } = rank.data
  if (!results.length) {
    return <Alert>No recipes match these filters for these characters with the current prices.</Alert>
  }
  return (
    <Stack>
      <ResultsTable
        results={results}
        items={rank.data.items}
        classes={rank.data.classes}
        params={{
          includeUnlearned: filters.includeUnlearned,
          includeTrivial: filters.includeTrivial,
          exits: filters.exits,
          version,
        }}
        ahBlocked={ahBlocked}
        onSetAhBlocked={(itemId, blocked) => setAhBlocked({ itemId, blocked })}
      />
      {total > results.length && (
        <Group justify="center">
          <Text size="sm" c="dimmed">
            Showing {results.length} of {total}
          </Text>
          <Button
            variant="light"
            loading={rank.isPlaceholderData}
            onClick={() => setPage({ filters, top: top + PAGE })}
          >
            Show more
          </Button>
        </Group>
      )}
    </Stack>
  )
}

function CharacterList({ group }: { group: CharacterGroup }) {
  return (
    <Stack gap={2}>
      {group.characters.map((c) => (
        <Text key={c.name} size="sm">
          <b>
            <CharacterName name={c.name} classFile={c.class_file} />
          </b>{' '}
          <Text span c="dimmed" size="sm">
            {c.level}
            {c.professions.length ? ': ' : ''}
            {c.professions.map((p) => `${p.name} ${p.rank}/${p.max_rank}`).join(', ')}
          </Text>
        </Text>
      ))}
    </Stack>
  )
}

type RangeProps = {
  name: string // e.g. "cost (gold)"
  min: number | null
  max: number | null
  onMin: (v: number | null) => void
  onMax: (v: number | null) => void
  step: number
}

function Range({ name, min, max, onMin, onMax, step }: RangeProps) {
  return (
    <Group grow gap="xs" align="flex-start">
      <NumberInput
        label={`Min ${name}`}
        value={min ?? ''}
        onChange={(v) => onMin(toBound(v))}
        step={step}
        decimalScale={4}
      />
      <NumberInput
        label={`Max ${name}`}
        placeholder="No max"
        value={max ?? ''}
        onChange={(v) => onMax(toBound(v))}
        step={step}
        decimalScale={4}
      />
    </Group>
  )
}

export function SearchTab() {
  const status = useStatus()
  const characters = useCharacters()
  const select = useSelectRealm()
  const [includeUnlearned, setIncludeUnlearned] = useStoredState(
    'altarmy-profit.search.includeUnlearned',
    z.boolean(),
    false,
  )
  const [includeTrivial, setIncludeTrivial] = useStoredState(
    'altarmy-profit.search.includeTrivial',
    z.boolean(),
    true,
  )
  const [open, setOpen] = useStoredState('altarmy-profit.search.open', z.array(z.enum(SECTIONS)), NONE_OPEN)
  const [exits, setExits] = useStoredState('altarmy-profit.search.exits', z.array(z.enum(ALL_EXITS)), ALL_EXITS)
  // Money in gold and ROI in percent, as typed; converted for the API below.
  const [minCost, setMinCost] = useStoredState('altarmy-profit.search.minCost', bound, 0)
  const [maxCost, setMaxCost] = useStoredState('altarmy-profit.search.maxCost', bound, null)
  // 1 copper: only profitable recipes by default.
  const [minProfit, setMinProfit] = useStoredState('altarmy-profit.search.minProfit', bound, 0.0001)
  const [maxProfit, setMaxProfit] = useStoredState('altarmy-profit.search.maxProfit', bound, null)
  const [minRoi, setMinRoi] = useStoredState('altarmy-profit.search.minRoi', bound, 0)
  const [maxRoi, setMaxRoi] = useStoredState('altarmy-profit.search.maxRoi', bound, null)
  const filters = useMemo<Filters>(
    () => ({
      includeUnlearned,
      includeTrivial,
      exits: ALL_EXITS.filter((e) => exits.includes(e)),
      minCost: scaled(minCost, goldToCopper),
      maxCost: scaled(maxCost, goldToCopper),
      minProfit: scaled(minProfit, goldToCopper),
      maxProfit: scaled(maxProfit, goldToCopper),
      minRoi: scaled(minRoi, (p) => p / 100),
      maxRoi: scaled(maxRoi, (p) => p / 100),
    }),
    [includeUnlearned, includeTrivial, exits, minCost, maxCost, minProfit, maxProfit, minRoi, maxRoi],
  )
  const [debouncedFilters] = useDebouncedValue(filters, 300)

  if (status.isPending) return <Loader />
  if (status.isError) return <Alert color="red">{status.error.message}</Alert>
  if (status.data.recipes === 0) {
    return (
      <Alert color="red">
        No recipes in {status.data.db_path}. Download game data on the Manage tab (or run `altarmy-profit ingest`).
      </Alert>
    )
  }

  const groups = characters.data?.groups ?? []
  // Show the realm being switched to while the server imports its prices.
  const selection = select.isPending ? select.variables : status.data.selection
  const group = groups.find((g) => selection && toKey(g) === toKey(selection))

  return (
    <Stack>
      {status.data.warnings.map((w) => (
        <Alert key={w} color="yellow">
          {w}
        </Alert>
      ))}
      <Flex
        direction={{ base: 'column', sm: 'row' }}
        justify="space-between"
        align={{ base: 'stretch', sm: 'flex-end' }}
        gap="md"
      >
        <Select
          label="Realm and faction"
          placeholder="No characters"
          data={groups.map((g) => ({ value: toKey(g), label: `${g.realm} (${g.faction})` }))}
          value={selection ? toKey(selection) : null}
          onChange={(key) => key && select.mutate(fromKey(key))}
          allowDeselect={false}
          style={{ flex: 1, maxWidth: 420 }}
        />
        <Switch
          label="Include recipes not learned yet"
          description="Every recipe of these characters' professions, not just the ones they know."
          checked={includeUnlearned}
          onChange={(e) => setIncludeUnlearned(e.currentTarget.checked)}
        />
      </Flex>
      <Accordion
        multiple
        variant="separated"
        value={open}
        onChange={(v) => setOpen(SECTIONS.filter((s) => v.includes(s)))}
      >
        <Accordion.Item value="advanced">
          <Accordion.Control>Advanced Options</Accordion.Control>
          <Accordion.Panel>
            <Stack>
              <Checkbox
                label="Include Trivial Recipes"
                description="Uncheck to show only recipes that can still give the crafter a skill point."
                checked={includeTrivial}
                onChange={(e) => setIncludeTrivial(e.currentTarget.checked)}
              />
              <Checkbox.Group
                label="Sell via"
                value={exits}
                onChange={(v) => setExits(ALL_EXITS.filter((e) => v.includes(e)))}
              >
                <Group mt={4}>
                  {EXITS.map((e) => (
                    <Checkbox key={e.value} value={e.value} label={e.label} />
                  ))}
                </Group>
              </Checkbox.Group>
              <SimpleGrid cols={{ base: 1, sm: 3 }}>
                <Range
                  name="cost (gold)"
                  min={minCost}
                  max={maxCost}
                  onMin={setMinCost}
                  onMax={setMaxCost}
                  step={1}
                />
                <Range
                  name="profit (gold)"
                  min={minProfit}
                  max={maxProfit}
                  onMin={setMinProfit}
                  onMax={setMaxProfit}
                  step={0.5}
                />
                <Range name="ROI (%)" min={minRoi} max={maxRoi} onMin={setMinRoi} onMax={setMaxRoi} step={10} />
              </SimpleGrid>
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>
        <Accordion.Item value="characters">
          <Accordion.Control>Characters{group ? ` (${group.characters.length})` : ''}</Accordion.Control>
          <Accordion.Panel>
            {group ? <CharacterList group={group} /> : <Text c="dimmed">No characters imported.</Text>}
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
      {status.data.prices === 0 && (
        <Alert color="yellow">No prices yet. Scan the auction house with Auctionator, then /reload.</Alert>
      )}
      {!status.data.selection ? (
        <Alert>No characters yet. Install the Alt Army addon, log in, or set its file on the Manage tab.</Alert>
      ) : debouncedFilters.exits.length ? (
        <Results filters={debouncedFilters} />
      ) : (
        <Alert>Pick at least one way to sell under Advanced Options.</Alert>
      )}
    </Stack>
  )
}
