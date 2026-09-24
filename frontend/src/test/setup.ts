import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
})

// Browser APIs Mantine uses that jsdom lacks.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
})

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
window.ResizeObserver = ResizeObserverStub
window.HTMLElement.prototype.scrollIntoView = () => {}

// What React Flow needs from the browser (see its testing guide): zoom transforms, element sizes, SVG bounds.
class DOMMatrixReadOnlyStub {
  m22: number
  constructor(transform?: string) {
    const scale = transform?.match(/scale\(([\d.]+)\)/)?.[1]
    this.m22 = scale === undefined ? 1 : Number(scale)
  }
}
Object.defineProperty(window, 'DOMMatrixReadOnly', { writable: true, value: DOMMatrixReadOnlyStub })
Object.defineProperties(window.HTMLElement.prototype, {
  offsetHeight: {
    get(this: HTMLElement) {
      return parseFloat(this.style.height) || 1
    },
  },
  offsetWidth: {
    get(this: HTMLElement) {
      return parseFloat(this.style.width) || 1
    },
  },
})
Object.assign(window.SVGElement.prototype, { getBBox: () => ({ x: 0, y: 0, width: 0, height: 0 }) })
