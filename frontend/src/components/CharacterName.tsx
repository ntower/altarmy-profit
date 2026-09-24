import { createContext, useContext } from 'react'
import classes from './CharacterName.module.css'

/** Character name -> class file (e.g. PALADIN), for colouring names wherever results mention them. */
export const CharacterClasses = createContext<Readonly<Record<string, string>>>({})

/** A character's name in their class colour; `classFile` overrides the `CharacterClasses` lookup. */
export function CharacterName({ name, classFile }: { name: string; classFile?: string }) {
  const known = useContext(CharacterClasses)
  return (
    <span className={classes.name} data-class={classFile ?? known[name]}>
      {name}
    </span>
  )
}
