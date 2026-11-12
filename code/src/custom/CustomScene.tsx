import React from 'react';
import {AbsoluteFill, Freeze, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {customScenes} from './registry';
import type {SceneProps} from './kit';

const FONTS = `@font-face{font-family:ReferencePlex;src:url('${staticFile('reference-fonts/ibm-plex-sans-arabic-700.woff2')}');font-weight:700;font-style:normal;}`
  + `@font-face{font-family:ReferenceAmiri;src:url('${staticFile('reference-fonts/Amiri-Bold.ttf')}');font-weight:700;}`;

export const hasCustomScene = (block: any) => Boolean(block?.custom_scene && customScenes[block.custom_scene]);

export const sceneProps = (block: any, fps: number): SceneProps => {
  const s = block.referenceStyle || {};
  const heading = s.heading_font === 'serif' ? 'ReferenceAmiri, Georgia, serif'
    : s.heading_font === 'display' ? 'Lalezar, ReferencePlex, sans-serif' : 'ReferencePlex, Arial, sans-serif';
  return {
    durationInFrames: block.durationFrames,
    fps,
    text: {title: String(block.title || ''), emphasis: String(block.emphasis || ''), label: String(block.label || ''),
      details: Array.isArray(block.details) ? block.details.map(String) : []},
    words: Array.isArray(block.sceneWords) ? block.sceneWords : [],
    palette: {background: s.background || '#f4f4f2', backgroundEnd: s.background_end || s.background || '#e4e4e0',
      ink: s.ink || '#171717', accent: s.accent || '#777777', muted: s.muted || '#666666',
      contrast: s.contrast_background || s.background_end || '#ffffff'},
    fonts: {heading, body: 'ReferencePlex, Arial, sans-serif', italic: Boolean(s.italic)},
    images: Object.fromEntries(Object.entries(block.customImages || {}).map(([id, src]) => [id, staticFile(String(src))])),
    captionTop: Math.round((s.caption_y ?? .76) * 1920) - 40,
  };
};

/** A scene Claude wrote. During the transition after its end it holds its final frame. */
export const CustomSceneFrame: React.FC<{block: any}> = ({block}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const Scene = customScenes[block.custom_scene];
  if (!Scene) return null;
  const props = sceneProps(block, fps);
  const body = <AbsoluteFill style={{overflow: 'hidden', background: props.palette.background}}>
    <style>{FONTS}</style>
    <Scene {...props}/>
  </AbsoluteFill>;
  return frame >= block.durationFrames ? <Freeze frame={block.durationFrames - 1}>{body}</Freeze> : body;
};
