import { useI18n } from '../../i18n/I18nProvider'
import { Field } from '../../components/Field'
import type { LocationRef } from '../../lib/refs'
import { FieldSet } from './FieldSet'
import { DailyScheduleGrid } from './DailyScheduleGrid'
import type { ScheduleSlot } from './CharactersTab'

// Sentinel home_location value: character sleeps off the map (not in any room).
const OFFMAP_SLEEP = '__offmap__'

/**
 * "Activity & Home" subtab body: home/sleep location + daily rhythm. The
 * parent loads home_location/schedule and passes them down; the grid is
 * self-managed.
 */
export function ActivityHomeTab({
  selected,
  locations,
  homeLoc,
  savingField,
  saveHome,
  schedule,
  cfg,
  homeLoading,
}: {
  selected: string
  locations: LocationRef[]
  homeLoc: { home_location: string; home_room: string }
  savingField: string
  saveHome: (next: { home_location: string; home_room: string }) => void
  schedule: { enabled: boolean; slots: ScheduleSlot[] }
  cfg: Record<string, unknown>
  homeLoading: boolean
}) {
  const { t } = useI18n()
  return homeLoading ? (
    <div className="ga-loading">{t('Loading…')}</div>
  ) : (
    <div className="ga-form">
      <FieldSet title={t('Home / sleep location')}>
      <div className="ga-form-row">
        <Field
          label={t('Home location')}
          hint={t('Where the character lives and returns to sleep. “Off-map” takes them off the grid while sleeping.')}
        >
          <select
            className="ga-input"
            value={homeLoc.home_location}
            disabled={savingField === 'home_location'}
            onChange={(e) =>
              saveHome({ home_location: e.target.value, home_room: '' })
            }
          >
            <option value="">— {t('none')} —</option>
            <option value={OFFMAP_SLEEP}>{t('Off-map (sleeps away)')}</option>
            {/* Only real living locations — passable transit/terrain locations
                are not homes/sleeping spots. */}
            {locations.filter((l) => !l.passable).map((l) => (
              <option key={l.id} value={l.id}>
                {l.name || l.id}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label={t('Home room')}
          hint={t('Optional room within the home location.')}
        >
          <select
            className="ga-input"
            value={homeLoc.home_room}
            disabled={
              savingField === 'home_location' ||
              homeLoc.home_location === OFFMAP_SLEEP ||
              !homeLoc.home_location
            }
            onChange={(e) =>
              saveHome({ home_location: homeLoc.home_location, home_room: e.target.value })
            }
          >
            <option value="">— {t('any room')} —</option>
            {(locations.find((l) => l.id === homeLoc.home_location)?.rooms || []).map(
              (r) => (
                <option key={r.id} value={r.id || ''}>
                  {r.name || r.id}
                </option>
              ),
            )}
          </select>
        </Field>
      </div>
      </FieldSet>

      <FieldSet title={t('Daily rhythm')}>
      <DailyScheduleGrid
        character={selected}
        locations={locations}
        roles={String(cfg.roles ?? '')
          .split(',')
          .map((r) => r.trim())
          .filter(Boolean)}
        initialEnabled={schedule.enabled}
        initialSlots={schedule.slots}
      />
      </FieldSet>
    </div>
  )
}
