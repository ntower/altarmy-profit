import { Fragment, useState } from 'react'
import { List, Stack, Table, Text, UnstyledButton } from '@mantine/core'
import type { RankResult } from '../api/client'
import { formatMoney, formatRoi } from '../lib/money'

const COLUMNS = ['', 'Profit', 'ROI', 'Recipe', 'Profession', 'Output', 'Cost', 'Revenue', 'Sell via']

function Details({ result }: { result: RankResult }) {
  return (
    <Stack gap="xs" py="xs">
      <div>
        <Text fw={600} size="sm">
          Chain
        </Text>
        {result.chain.length ? (
          <List size="sm">
            {result.chain.map((line) => (
              <List.Item key={line}>{line}</List.Item>
            ))}
          </List>
        ) : (
          <Text size="sm">buy all reagents</Text>
        )}
      </div>
      <div>
        <Text fw={600} size="sm">
          Sell options (per item)
        </Text>
        <List size="sm">
          {result.exits.map((e) => (
            <List.Item key={e.kind}>
              {e.kind}: {formatMoney(e.value)}
            </List.Item>
          ))}
        </List>
      </div>
    </Stack>
  )
}

export function ResultsTable({ results }: { results: RankResult[] }) {
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
              <Table.Th key={c}>{c}</Table.Th>
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
                  <Table.Td>{r.recipe}</Table.Td>
                  <Table.Td>{r.profession}</Table.Td>
                  <Table.Td>
                    {r.output_count}x {r.output_name}
                  </Table.Td>
                  <Table.Td ff="monospace">{formatMoney(r.cost)}</Table.Td>
                  <Table.Td ff="monospace">{formatMoney(r.revenue)}</Table.Td>
                  <Table.Td>{r.best_exit}</Table.Td>
                </Table.Tr>
                {expanded && (
                  <Table.Tr>
                    <Table.Td />
                    <Table.Td colSpan={COLUMNS.length - 1}>
                      <Details result={r} />
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
