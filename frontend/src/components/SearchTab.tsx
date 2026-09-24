import { Alert, Group, Loader, NumberInput, Select, Stack, Switch, Text } from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { z } from 'zod'
import type { CharacterGroup, Selection } from '../api/client'
import { useCharacters, useRank, useSelectRealm, useStatus } from '../api/queries'
import { goldToCopper } from '../lib/money'
import { useStoredState } from '../lib/storage'
import { ResultsTable } from './ResultsTable'

const asNumber = (v: number | string, fallback: number) => (typeof v === 'number' ? v : fallback)

// Realms may contain spaces but never tabs.
const toKey = (s: Selection) => `${s.realm}\t${s.faction}`
const fromKey = (key: string): Selection => {
  const [realm = '', faction = ''] = key.split('\t')
  return { realm, faction }
}

function Results({ includeUnlearned, minGold, top }: { includeUnlearned: boolean; minGold: number; top: number }) {
  const rank = useRank(includeUnlearned, goldToCopper(minGold), top)
  if (rank.isPending) return <Loader />
  if (rank.isError) return <Alert color="red">{rank.error.message}</Alert>
  if (!rank.data.results.length) {
    return <Alert>No profitable recipes found for these characters with the current prices.</Alert>
  }
  return <ResultsTable results={rank.data.results} items={rank.data.items} />
}

function CharacterList({ group }: { group: CharacterGroup }) {
  return (
    <Stack gap={2}>
      {group.characters.map((c) => (
        <Text key={c.name} size="sm">
          <b>{c.name}</b>{' '}
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

export function SearchTab() {
  const status = useStatus()
  const characters = useCharacters()
  const select = useSelectRealm()
  const [includeUnlearned, setIncludeUnlearned] = useStoredState(
    'wowprofit.search.includeUnlearned',
    z.boolean(),
    false,
  )
  const [minGold, setMinGold] = useStoredState('wowprofit.search.minGold', z.number(), 0)
  const [top, setTop] = useStoredState('wowprofit.search.top', z.int().min(1).max(500), 25)
  const [debouncedMinGold] = useDebouncedValue(minGold, 300)

  if (status.isPending) return <Loader />
  if (status.isError) return <Alert color="red">{status.error.message}</Alert>
  if (status.data.recipes === 0) {
    return (
      <Alert color="red">
        No recipes in {status.data.db_path}. Download game data on the Manage tab (or run `wowprofit ingest`).
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
      <Group align="flex-end" wrap="wrap">
        <Select
          label="Realm and faction"
          placeholder="No characters"
          data={groups.map((g) => ({ value: toKey(g), label: `${g.realm} (${g.faction})` }))}
          value={selection ? toKey(selection) : null}
          onChange={(key) => key && select.mutate(fromKey(key))}
          allowDeselect={false}
          style={{ flex: 3, minWidth: 260 }}
        />
        <NumberInput
          label="Min profit (gold)"
          value={minGold}
          onChange={(v) => setMinGold(asNumber(v, 0))}
          step={0.5}
          decimalScale={4}
          style={{ flex: 1, minWidth: 140 }}
        />
        <NumberInput
          label="Show top"
          value={top}
          onChange={(v) => setTop(asNumber(v, 25))}
          min={1}
          max={500}
          step={5}
          allowDecimal={false}
          clampBehavior="strict"
          style={{ flex: 1, minWidth: 120 }}
        />
      </Group>
      <Switch
        label="Include recipes not learned yet"
        description="Every recipe of these characters' professions, not just the ones they know."
        checked={includeUnlearned}
        onChange={(e) => setIncludeUnlearned(e.currentTarget.checked)}
      />
      {group && <CharacterList group={group} />}
      {status.data.prices === 0 && (
        <Alert color="yellow">No prices yet. Scan the auction house with Auctionator, then /reload.</Alert>
      )}
      {status.data.selection ? (
        <Results includeUnlearned={includeUnlearned} minGold={debouncedMinGold} top={top} />
      ) : (
        <Alert>No characters yet. Install the Alt Army addon, log in, or set its file on the Manage tab.</Alert>
      )}
    </Stack>
  )
}
