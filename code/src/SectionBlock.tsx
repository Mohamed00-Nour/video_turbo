import React from 'react';
import { Img, interpolate, staticFile, useCurrentFrame } from 'remotion';
import { LoopingVideo } from './LoopingVideo';
import { FlashTransition } from './FlashTransition';

type Media = { src: string; kind: string; durationFrames?: number };
export const SectionBlock: React.FC<{ block: any; blur: number }> = ({ block, blur }) => {
  const frame = useCurrentFrame();
  const progress = frame / Math.max(1, block.durationFrames);
  const entrance = interpolate(frame, [4, 18], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const card = (media: Media | null, top: number, height: number, primary = true) => media && (
    <div style={{ position: 'absolute', left: 90, top: top + (1 - entrance) * 60, width: 900, height,
      opacity: entrance, borderRadius: 28, overflow: 'hidden', background: '#131019',
      boxShadow: '0 24px 50px #0009', border: '2px solid #ffffff25' }}>
      <div style={{ width: '100%', height: '100%', transform: `scale(${1 + ((block.zoom ?? 1.04) - 1) * progress})` }}>
        {media.kind === 'image' ? <Img src={staticFile(media.src)} style={{ width: '100%', height: '100%', objectFit: block.fit ?? 'contain' }} /> :
          <LoopingVideo src={media.src} durationFrames={media.durationFrames} offsetSeconds={block.offset_seconds ?? 0}
            style={{ width: '100%', height: '100%', objectFit: block.fit ?? 'contain' }} />}
      </div>
      {primary && block.highlight && <div style={{ position: 'absolute', pointerEvents: 'none',
        left: `${block.highlight.x}%`, top: `${block.highlight.y}%`, width: `${block.highlight.width}%`, height: `${block.highlight.height}%`,
        boxSizing: 'border-box', borderRadius: 14, border: '6px solid #FD40FF', boxShadow: `0 0 ${18 + Math.sin(frame / 8) * 6}px #FD40FF99` }} />}
    </div>
  );
  return <div style={{ position: 'relative', width: 1080, height: 1920, overflow: 'hidden', background: '#000' }}>
    <div style={{ width: '100%', height: '100%', transform: `scale(${1 + .08 * progress})`,
      filter: block.layout === 'background' ? undefined : `blur(${5 * blur}px) brightness(.7)` }}>
      <LoopingVideo src={block.bgVideo} durationFrames={block.bgDurationFrames} offsetSeconds={block.gtaOffset}
        style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
    </div>
    {block.layout === 'single' && card(block.media, 320, 1000)}
    {block.layout === 'split' && <>{card(block.media, 220, 480)}{card(block.secondary_media, 1070, 480, false)}</>}
    {block.layout === 'title' && <div dir="auto" style={{ position: 'absolute', left: 90, right: 90, top: 680,
      textAlign: 'center', opacity: entrance, transform: `translateY(${(1 - entrance) * 40}px)`, color: '#fff',
      fontFamily: 'Lalezar', fontSize: 100, lineHeight: 1.2, textShadow: '0 6px 25px #000',
      padding: '60px 30px', borderRadius: 36, background: '#15101ddb', border: '3px solid #FD40FF' }}>{block.title}</div>}
    {block.label && <div dir="auto" style={{ position: 'absolute', left: 90, right: 90, top: block.layout === 'split' ? 780 : 160,
      color: '#fff', textAlign: 'center', fontFamily: 'Lalezar', fontSize: 60, opacity: entrance,
      textShadow: '0 4px 15px #000', background: '#211729dd', padding: '14px 24px', borderRadius: 20,
      borderBottom: '4px solid #FD40FF' }}>{block.label}</div>}
    <FlashTransition frameInBlock={frame} />
  </div>;
};