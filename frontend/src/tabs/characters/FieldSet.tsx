import { type ReactNode } from 'react'

// Framed group of related fields with an uppercase title.
export function FieldSet({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="ga-fieldset">
      <div className="ga-fieldset-title">{title}</div>
      {children}
    </div>
  )
}
