import { Fragment, useState, type ReactNode } from 'react'
import { HoverCard } from '@mantine/core'
import type { ItemInfo, ItemMap, RankResult } from '../api/client'
import { QUALITY_COLORS, bindingText, iconUrl, slotLine, speedText, splitMoney } from '../lib/wow'
import classes from './ItemTooltip.module.css'

const qualityColor = (quality: number) => QUALITY_COLORS[quality] ?? QUALITY_COLORS[1]

/** A CDN icon that disappears if it cannot load (offline, or an icon Wowhead does not have). */
function Icon({ icon, size, className }: { icon: string | null; size: 'small' | 'large'; className: string }) {
  const [failed, setFailed] = useState(false)
  if (!icon || failed) return null
  return <img className={className} src={iconUrl(icon, size)} alt="" onError={() => setFailed(true)} />
}

function Coins({ copper }: { copper: number }) {
  return (
    <span className={classes.coins}>
      {splitMoney(copper).map(({ unit, amount }, i) => (
        <Fragment key={unit}>
          {i > 0 && ' '}
          <span className={classes.coin} data-unit={unit} title={unit}>
            {amount}
          </span>
        </Fragment>
      ))}
    </span>
  )
}

/** The item's tooltip lines in in-game order (stats, armor and damage are not in the data yet). */
function ItemLines({ item }: { item: ItemInfo }) {
  const binding = bindingText(item.bonding)
  const slot = slotLine(item)
  const speed = speedText(item)
  return (
    <>
      <div className={classes.title} style={{ color: qualityColor(item.quality) }}>
        {item.name}
      </div>
      {binding && <div>{binding}</div>}
      {slot && (
        <div className={classes.split}>
          <span>{slot.left}</span>
          {slot.right && <span>{slot.right}</span>}
        </div>
      )}
      {speed && <div className={classes.right}>{speed}</div>}
      {item.required_level > 1 && <div>Requires Level {item.required_level}</div>}
      {item.required_skill && (
        <div>
          Requires {item.required_skill} ({item.required_skill_rank})
        </div>
      )}
      {item.description && <div className={classes.flavor}>"{item.description}"</div>}
      {item.sell_price > 0 && (
        <div>
          Sell Price: <Coins copper={item.sell_price} />
        </div>
      )}
      {item.ah_price != null && (
        <div>
          Auction: <Coins copper={item.ah_price} />
        </div>
      )}
    </>
  )
}

function TooltipFrame({ icon, children }: { icon: string | null; children: ReactNode }) {
  return (
    <div className={classes.frame}>
      <Icon icon={icon} size="large" className={classes.bigIcon} />
      <div className={classes.tooltip}>{children}</div>
    </div>
  )
}

export function ItemTooltip({ item }: { item: ItemInfo }) {
  return (
    <TooltipFrame icon={item.icon}>
      <ItemLines item={item} />
    </TooltipFrame>
  )
}

/** Like a recipe item in game: recipe name, profession and reagents, then the crafted item's tooltip. */
export function RecipeTooltip({
  name,
  profession,
  reagents,
  output,
  items,
}: {
  name: string
  profession: string
  reagents: RankResult['reagents']
  output: ItemInfo | undefined
  items: ItemMap
}) {
  const reagentList = reagents
    .map(({ item_id, count }) => {
      const reagent = items[item_id]?.name ?? `Item ${item_id}`
      return count > 1 ? `${reagent} (${count})` : reagent
    })
    .join(', ')
  return (
    <TooltipFrame icon={output?.icon ?? null}>
      <div className={classes.title}>{name}</div>
      <div>{profession}</div>
      <div className={classes.reagents}>Reagents: {reagentList}</div>
      {output && (
        <div className={classes.section}>
          <ItemLines item={output} />
        </div>
      )}
    </TooltipFrame>
  )
}

/** Hover `children` to show `tooltip` beside it. */
export function Hover({ tooltip, children }: { tooltip: ReactNode; children: ReactNode }) {
  return (
    <HoverCard
      openDelay={0}
      closeDelay={0}
      transitionProps={{ duration: 0 }}
      position="right-start"
      offset={8}
      withinPortal
    >
      <HoverCard.Target>
        <span className={classes.target}>{children}</span>
      </HoverCard.Target>
      <HoverCard.Dropdown className={classes.dropdown}>{tooltip}</HoverCard.Dropdown>
    </HoverCard>
  )
}

/** An item name in its quality colour with a small icon; hover for the tooltip. `name` is the fallback
 * when the item has no details (e.g. a database from before tooltips were ingested). */
export function ItemLink({ item, name }: { item: ItemInfo | undefined; name?: string }) {
  if (!item) return <>{name}</>
  return (
    <Hover tooltip={<ItemTooltip item={item} />}>
      <span className={classes.link} data-quality={item.quality}>
        <Icon icon={item.icon} size="small" className={classes.smallIcon} />
        {item.name}
      </span>
    </Hover>
  )
}
