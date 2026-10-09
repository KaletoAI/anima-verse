import { SchemaNode, type SchemaNodeDef, type SchemaProps } from './SchemaNode'
import type { UseCaseDefaults } from './UseCaseStyles'
import type { Json } from './schemaValues'

export type WorldGroup = { id: string; label: string; sections: string[] }
export type WorldSettings = {
  world: string
  groups: WorldGroup[]
  schema: Record<string, SchemaNodeDef>
  values: Json
  shipped: Json
  overrides: string[]
  use_case_defaults: UseCaseDefaults
}
export function WorldSettingsGroup({ group, schema, ...props }: {
  group: WorldGroup
  schema: Record<string, SchemaNodeDef>
} & Omit<SchemaProps, 'node' | 'path'>) {
  return <div className="ga-setup-sections">
    {group.sections.map(key => {
      const node = schema[key]
      return <section className="ga-form" key={key}>
        {!node.is_array && <h2 className="ga-setup-heading">{node.label}</h2>}
        {node.description && <p className="ga-form-hint">{node.description}</p>}
        <SchemaNode {...props} node={node} path={key} />
      </section>
    })}
  </div>
}
