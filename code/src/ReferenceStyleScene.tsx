import React from 'react';
import {DirectedReferenceScene} from './reference/DirectedReferenceScene';
import {LegacyReferenceStyleScene} from './reference/LegacyReferenceStyleScene';

export const ReferenceStyleScene: React.FC<{block: any}> = ({block}) =>
  block.referenceStyle.renderer_version >= 2 ? <DirectedReferenceScene block={block}/> : <LegacyReferenceStyleScene block={block}/>;
