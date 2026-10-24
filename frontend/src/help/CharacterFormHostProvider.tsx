import { useMemo, type ReactNode } from 'react'
import { CharacterFormHostContext, useI18n, type FieldImageDialogControl } from '@anima/player-ui'
import { ImageGenDialog } from '../components/ImageGenDialog'
import { useHelp } from './HelpContext'

/** Keep admin help and generation at the app boundary, outside the shared forms. */
export function CharacterFormHostProvider({ children }: { children: ReactNode }) {
  const { setTopic, setHelp } = useHelp()
  const { t } = useI18n()
  const host = useMemo(() => ({ setTopic, setHelp,
      renderImageDialog: (ctl: FieldImageDialogControl) => (
        <ImageGenDialog
          open
          title={t('Generate profile image')}
          defaultPrompt={ctl.prompt}
          occasion="profile"
          occasionCharacter={ctl.character}
          sourceImageUrl={ctl.sourceImageUrl}
          defaultUseSource={false}
          sourceReferenceLabel={t('Use current portrait as reference')}
          onSubmit={ctl.onSubmit}
          onClose={ctl.onClose}
        />
      ),
  }), [setTopic, setHelp, t])
  return (
    <CharacterFormHostContext.Provider value={host}>
      {children}
    </CharacterFormHostContext.Provider>
  )
}
