import { Component, type ReactNode } from 'react'

interface Props { children: ReactNode }
interface State { error: Error | null }

/** Keeps the HTML overlay usable if WebGL is unavailable (for example in some headless browsers). */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }
  static getDerivedStateFromError(error: Error): State {
    return { error }
  }
  render() {
    if (this.state.error) {
      return (
        <div className="loading">
          The 3D view could not start ({this.state.error.message}). The planning data and panels still work.
        </div>
      )
    }
    return this.props.children
  }
}
