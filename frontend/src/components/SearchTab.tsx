import { useState } from 'react'
import { Alert, Group, Loader, MultiSelect, NumberInput, Stack } from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { useProfessions, useRank, useStatus } from '../api/queries'
import { goldToCopper } from '../lib/money'
import { ResultsTable } from './ResultsTable'

const asNumber = (v: number | string, fallback: number) => (typeof v === 'number' ? v : fallback)

function Results({ professions, minGold, top }: { professions: string[]; minGold: number; top: number }) {
  const rank = useRank(professions, goldToCopper(minGold), top)
  if (rank.isPending) return <Loader />
  if (rank.isError) return <Alert color="red">{rank.error.message}</Alert>
  if (!rank.data.results.length) {
    return <Alert>No profitable recipes found for these professions with the current prices.</Alert>
  }
  return <ResultsTable results={rank.data.results} />
}

export function SearchTab() {
  const status = useStatus()
  const professions = useProfessions()
  const [picked, setPicked] = useState<string[]>([])
  const [minGold, setMinGold] = useState(0)
  const [top, setTop] = useState(25)
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

  return (
    <Stack>
      <Group align="flex-end" wrap="wrap">
        <MultiSelect
          label="Professions"
          placeholder={picked.length ? undefined : 'Pick professions'}
          data={professions.data ?? []}
          value={picked}
          onChange={setPicked}
          searchable
          clearable
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
      {status.data.prices === 0 && <Alert color="yellow">No prices yet. Import them on the Manage tab.</Alert>}
      {picked.length ? (
        <Results professions={picked} minGold={debouncedMinGold} top={top} />
      ) : (
        <Alert>Pick the professions you have.</Alert>
      )}
    </Stack>
  )
}
