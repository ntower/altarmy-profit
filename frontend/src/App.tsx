import { Container, Group, Tabs, Title } from '@mantine/core'
import { useAutoUpdateGameData, useSyncNotifications } from './api/queries'
import { AccountStatus, LinkPrompt } from './components/Account'
import { GameVersionProvider, GameVersionSwitch } from './components/GameVersionProvider'
import { ManageTab } from './components/ManageTab'
import { PricesTab } from './components/PricesTab'
import { SearchTab } from './components/SearchTab'
import { useSession } from './lib/session'

export function App() {
  return (
    <GameVersionProvider>
      <Shell />
    </GameVersionProvider>
  )
}

/** Local mode keeps the game data current and toasts what the addon file sync imported. */
function LocalUpkeep() {
  useAutoUpdateGameData()
  useSyncNotifications()
  return null
}

function Shell() {
  const { mode, tier } = useSession()
  const linked = tier === 'linked'
  return (
    <Container size="xl" py="md">
      {mode === 'local' && <LocalUpkeep />}
      <Group justify="space-between" align="center" mb="md">
        <Title order={1}>altarmy-profit</Title>
        <Group>
          {mode === 'hosted' && <AccountStatus />}
          <GameVersionSwitch />
        </Group>
      </Group>
      {!linked && <LinkPrompt />}
      {/* keyed by tier: linking opens the Search tab it unlocks */}
      <Tabs key={tier} defaultValue={linked ? 'search' : 'prices'}>
        <Tabs.List mb="md">
          {linked && <Tabs.Tab value="search">Search</Tabs.Tab>}
          <Tabs.Tab value="prices">Prices</Tabs.Tab>
          {linked && <Tabs.Tab value="manage">Manage</Tabs.Tab>}
        </Tabs.List>
        {linked && (
          <Tabs.Panel value="search">
            <SearchTab />
          </Tabs.Panel>
        )}
        <Tabs.Panel value="prices">
          <PricesTab />
        </Tabs.Panel>
        {linked && (
          <Tabs.Panel value="manage">
            <ManageTab />
          </Tabs.Panel>
        )}
      </Tabs>
    </Container>
  )
}
