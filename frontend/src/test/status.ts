import type { Characters, Status } from '../api/client'

/** A synced status: game data, prices, and Alt Army characters with Classic Beta PvE (Horde) selected. */
export const status = (over: Partial<Status> = {}): Status => ({
  db_path: 'data/altarmy-profit.db',
  build: '1.60.1.69913',
  items: 3,
  recipes: 1,
  prices: 2,
  characters: 3,
  last_auctionator_import: '2026-09-24 10:00:00',
  last_altarmy_sync: '2026-09-24 10:01:00',
  last_auctionator_sync: '2026-09-24 10:01:00',
  altarmy_path: 'C:\\WoW\\_classic_beta_\\WTF\\Account\\A\\SavedVariables\\AltArmy_TBC.lua',
  auctionator_path: 'C:\\WoW\\_classic_beta_\\WTF\\Account\\A\\SavedVariables\\Auctionator.lua',
  auctionator_realm: 'ClassicBetaPvE',
  selection: { realm: 'Classic Beta PvE', faction: 'Horde' },
  auction_house_id: 1,
  data_version: 1,
  price_version: 0,
  warnings: [],
  ...over,
})

export const characters: Characters = {
  groups: [
    {
      realm: 'Classic Beta PvE',
      faction: 'Horde',
      characters: [
        {
          name: 'Tailor Guy',
          class_file: 'MAGE',
          level: 20,
          professions: [
            { name: 'Cooking', rank: 1, max_rank: 75, recipes: 0 },
            { name: 'Tailoring', rank: 50, max_rank: 75, recipes: 1 },
          ],
        },
      ],
    },
    {
      realm: 'Dreamscythe',
      faction: 'Horde',
      characters: [
        { name: 'Frell', class_file: 'WARLOCK', level: 70, professions: [] },
        { name: 'Newbie', class_file: '', level: 0, professions: [] },
      ],
    },
  ],
  selection: { realm: 'Classic Beta PvE', faction: 'Horde' },
}
