import { Container, Group, Tabs, Title } from '@mantine/core'
import { useAutoUpdateGameData, useSyncNotifications } from './api/queries'
import { GameVersionProvider, GameVersionSwitch } from './components/GameVersionProvider'
import { ManageTab } from './components/ManageTab'
import { SearchTab } from './components/SearchTab'

export function App() {
  return (
    <GameVersionProvider>
      <Shell />
    </GameVersionProvider>
  )
}

function Shell() {
  useAutoUpdateGameData()
  useSyncNotifications()
  return (
    <Container size="xl" py="md">
      <Group justify="space-between" align="center" mb="md">
        <Title order={1}>altarmy-profit</Title>
        <GameVersionSwitch />
      </Group>
      <Tabs defaultValue="search">
        <Tabs.List mb="md">
          <Tabs.Tab value="search">Search</Tabs.Tab>
          <Tabs.Tab value="manage">Manage</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="search">
          <SearchTab />
        </Tabs.Panel>
        <Tabs.Panel value="manage">
          <ManageTab />
        </Tabs.Panel>
      </Tabs>
    </Container>
  )
}
