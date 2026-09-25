import { Fragment, useState } from 'react'
import { Alert, Group, Loader, Select, Stack, Table, Text, TextInput, UnstyledButton } from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { z } from 'zod'
import type { AuctionHouse, PriceStats } from '../api/client'
import { usePriceHistory, usePrices, useRealms, useStatus } from '../api/queries'
import { useGameVersion } from '../lib/gameVersion'
import { useSession } from '../lib/session'
import { useStoredState } from '../lib/storage'
import { ItemLink } from './ItemTooltip'
import { Money } from './Money'

const PRICES_AH_KEY = 'altarmy-profit.pricesAuctionHouse'
const storedId = z.number().int().nullable()

function auctionHouseLabel(ah: AuctionHouse): string {
  const realm = ah.realm || 'Unnamed (manual prices)'
  return ah.faction ? `${realm} (${ah.faction})` : realm
}

/** The auction house the user picked, else the selection's, else the first one with prices. */
function useAuctionHouse(realms: readonly AuctionHouse[] | undefined) {
  const gameVersion = useGameVersion()
  const status = useStatus()
  const [picked, setPicked] = useStoredState(`${PRICES_AH_KEY}.${gameVersion}`, storedId, null)
  const known = (id: number | null | undefined) => (id != null && realms?.some((a) => a.id === id) ? id : null)
  const id = known(picked) ?? known(status.data?.auction_house_id) ?? realms?.find((a) => a.prices > 0)?.id ?? null
  return [id, setPicked] as const
}

function History({ auctionHouseId, itemId }: { auctionHouseId: number; itemId: number }) {
  const history = usePriceHistory(auctionHouseId, itemId)
  if (history.isPending) return <Loader size="sm" />
  if (history.isError) return <Alert color="red">{history.error.message}</Alert>
  const { days } = history.data
  if (!days.length) {
    return (
      <Text size="sm" c="dimmed">
        No daily history for this item yet.
      </Text>
    )
  }
  return (
    <Table withTableBorder aria-label="Price history">
      <Table.Thead>
        <Table.Tr>
          <Table.Th>Day</Table.Th>
          <Table.Th ta="right">Low</Table.Th>
          <Table.Th ta="right">High</Table.Th>
          <Table.Th ta="right">Available</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {days.map((d) => (
          <Table.Tr key={d.day}>
            <Table.Td>{d.day}</Table.Td>
            <Table.Td ta="right">
              <Money copper={d.low} />
            </Table.Td>
            <Table.Td ta="right">
              <Money copper={d.high} />
            </Table.Td>
            <Table.Td ta="right">{d.available ?? '—'}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  )
}

/** The median of an item's daily prices over the last 7 days, and on how many days it was scanned. */
function SevenDayMedian({ stats }: { stats: PriceStats | undefined }) {
  if (stats?.median_7d == null) return '—'
  return (
    <Group gap={6} justify="flex-end" wrap="nowrap">
      <Money copper={stats.median_7d} />
      <Text span size="xs" c="dimmed" title="Days with a scan in the last 7">
        {stats.scans_7d}d
      </Text>
    </Group>
  )
}

/** Look up auction house prices by item name; click an item for its daily history. */
export function PricesTab() {
  const { freeMaxLevel } = useSession()
  const realms = useRealms()
  const [auctionHouseId, setAuctionHouseId] = useAuctionHouse(realms.data)
  const [query, setQuery] = useState('')
  const [debounced] = useDebouncedValue(query.trim(), 250)
  const prices = usePrices(auctionHouseId, debounced)
  const [open, setOpen] = useState<number | null>(null)

  if (realms.isError) return <Alert color="red">{realms.error.message}</Alert>
  if (realms.data && !realms.data.length) {
    return <Alert color="gray">No auction house has prices for this game yet.</Alert>
  }
  return (
    <Stack>
      <Group align="flex-end">
        <Select
          label="Auction house"
          data={(realms.data ?? []).map((a) => ({
            value: String(a.id),
            label: `${auctionHouseLabel(a)}: ${a.prices.toLocaleString()} prices`,
          }))}
          value={auctionHouseId === null ? null : String(auctionHouseId)}
          onChange={(v) => v && setAuctionHouseId(Number(v))}
          allowDeselect={false}
          w={360}
        />
        <TextInput
          label="Item"
          placeholder="Search by name"
          value={query}
          onChange={(e) => setQuery(e.currentTarget.value)}
          w={280}
        />
      </Group>
      {prices.data?.gated && (
        <Text size="sm" c="dimmed">
          Guests see prices of items up to level {freeMaxLevel}. Link your account for the rest.
        </Text>
      )}
      {prices.isError && <Alert color="red">{prices.error.message}</Alert>}
      {prices.data && auctionHouseId !== null && (
        <>
          <Table highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Item</Table.Th>
                <Table.Th ta="right">Level</Table.Th>
                <Table.Th ta="right">Auction house</Table.Th>
                <Table.Th ta="right" title="Crafts sell at no more than this, so a lone overpriced listing doesn't count">
                  7-day median
                </Table.Th>
                <Table.Th ta="right">Vendor</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {prices.data.items.map((item) => (
                <Fragment key={item.id}>
                  <Table.Tr>
                    <Table.Td>
                      <Group gap="xs" wrap="nowrap">
                        <ItemLink item={item} name={item.name} />
                        <UnstyledButton
                          fz="xs"
                          c="dimmed"
                          aria-expanded={open === item.id}
                          aria-label={`History of ${item.name}`}
                          onClick={() => setOpen(open === item.id ? null : item.id)}
                        >
                          {open === item.id ? 'hide history' : 'history'}
                        </UnstyledButton>
                      </Group>
                    </Table.Td>
                    <Table.Td ta="right">{item.required_level || ''}</Table.Td>
                    <Table.Td ta="right">{item.ah_price !== null && <Money copper={item.ah_price} />}</Table.Td>
                    <Table.Td ta="right">
                      <SevenDayMedian stats={prices.data.stats[item.id]} />
                    </Table.Td>
                    <Table.Td ta="right">
                      {item.vendor_price !== null ? <Money copper={item.vendor_price} /> : '—'}
                    </Table.Td>
                  </Table.Tr>
                  {open === item.id && (
                    <Table.Tr>
                      <Table.Td colSpan={5}>
                        <History auctionHouseId={auctionHouseId} itemId={item.id} />
                      </Table.Td>
                    </Table.Tr>
                  )}
                </Fragment>
              ))}
            </Table.Tbody>
          </Table>
          <Text size="sm" c="dimmed">
            {prices.data.total > prices.data.items.length
              ? `Showing ${prices.data.items.length} of ${prices.data.total.toLocaleString()} items: narrow the search.`
              : `${prices.data.total.toLocaleString()} items.`}
          </Text>
        </>
      )}
    </Stack>
  )
}
