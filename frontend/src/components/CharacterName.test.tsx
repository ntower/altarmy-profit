import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '../test/utils'
import { CharacterClasses, CharacterName } from './CharacterName'

describe('CharacterName', () => {
  it('tags the name with its class from context, or an explicit class', () => {
    renderWithProviders(
      <CharacterClasses.Provider value={{ Frell: 'WARLOCK' }}>
        <CharacterName name="Frell" />
        <CharacterName name="Tailor Guy" classFile="MAGE" />
        <CharacterName name="Stranger" />
      </CharacterClasses.Provider>,
    )
    expect(screen.getByText('Frell')).toHaveAttribute('data-class', 'WARLOCK')
    expect(screen.getByText('Tailor Guy')).toHaveAttribute('data-class', 'MAGE')
    expect(screen.getByText('Stranger')).not.toHaveAttribute('data-class')
  })
})
