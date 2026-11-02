import { TransitionScene, type Placement } from './TransitionSequencePreview'
export function TransitionPlacementPreview(props: Placement & { height?: number }) {
  return <TransitionScene placement={props} height={props.height} segments={[
    { url: props.startUrl, startS: 0, endS: 0 },
    { url: props.targetUrl, startS: 0, endS: 0 },
  ]} />
}
