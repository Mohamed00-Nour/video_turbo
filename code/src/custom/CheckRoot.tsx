import React from 'react';
import {Composition, registerRoot} from 'remotion';
import {CustomSceneFrame} from './CustomScene';

// Entry used only to test-render Claude's scenes before a full build.
const Check: React.FC<{block: any}> = ({block}) => <CustomSceneFrame block={block}/>;

registerRoot(() => <Composition id="CustomSceneCheck" component={Check} width={1080} height={1920} fps={30}
  durationInFrames={30} defaultProps={{block: {durationFrames: 30}}}
  calculateMetadata={({props}) => ({durationInFrames: Math.max(1, (props.block?.durationFrames || 30) + 12)})}/>);
