import { Container, Tabs, Title } from '@mantine/core'
import { useAutoUpdateGameData, useSyncNotifications } from './api/queries'
import { ManageTab } from './components/ManageTab'
import { SearchTab } from './components/SearchTab'

export function App() {
  useAutoUpdateGameData()
  useSyncNotifications()
  return (
    <Container size="xl" py="md">
      <Title order={1} mb="md">
        wow-profit
      </Title>
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
