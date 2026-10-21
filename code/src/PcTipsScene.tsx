import React from 'react';
import {Img, OffthreadVideo, interpolate, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';

export const PcTipsScene: React.FC<{block: any}> = ({block}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const intro = block.layout === 'pc_intro';
  const accent = block.accent || '#66e1ff';
  const duration = Math.max(1, block.durationFrames);
  const appearance = interpolate(frame, [0, Math.min(10, duration - 1) || 1], [0, 1], {extrapolateRight: 'clamp'});
  const progress = frame / Math.max(1, duration - 1);
  const part = String(block.part).padStart(2, '0');
  const trim = Math.round((block.offset_seconds || 0) * fps);
  const sourceFrames = (block.media?.durationFrames || duration) - trim;
  // Fit the whole recorded action into its narration window, including its result.
  const playbackRate = Math.max(1 / 16, Math.min(16, sourceFrames / duration));
  return <div data-pc-scene={intro ? 'intro' : 'demo'} style={{position: 'absolute', inset: 0, overflow: 'hidden',
    background: '#0a1018', color: '#f7fafc', fontFamily: 'Arial, sans-serif'}}>
    {intro ? <>
      {block.media && <Img src={staticFile(block.media.src)} style={{width: '100%', height: '100%', objectFit: 'cover',
        scale: String(1.025 + progress * .055), translate: `0px ${-progress * 12}px`}}/>}
      <div style={{position: 'absolute', inset: 0, background: 'linear-gradient(180deg,#02070e10 20%,#02070e33 45%,#02070ef5 90%)'}}/>
      <div style={{position: 'absolute', left: 84, right: 84, bottom: 235, opacity: appearance,
        translate: `0px ${(1 - appearance) * 28}px`}}>
        <div style={{display: 'flex', alignItems: 'center', gap: 18, marginBottom: 32}}>
          <span style={{height: 3, width: 62, background: accent}}/>
          <span style={{fontSize: 25, letterSpacing: 7, fontWeight: 600}}>MAKE YOUR PC WORK FOR YOU</span>
        </div>
        <div data-pc-title style={{fontSize: 105, lineHeight: .98, letterSpacing: -5, fontWeight: 900}}>
          PC TIPS<br/><span style={{color: accent}}>&amp; TRICKS</span>
        </div>
        <div data-pc-part style={{marginTop: 40, fontSize: 34, letterSpacing: 8, fontWeight: 700}}>PART {part}</div>
      </div>
      <div style={{position: 'absolute', bottom: 135, left: 84, width: 912, height: 2, background: '#ffffff35'}}>
        <div style={{height: '100%', width: `${progress * 100}%`, background: accent}}/>
      </div>
    </> : <>
      <div style={{position: 'absolute', inset: 0, background: `radial-gradient(ellipse at 90% 10%, ${accent}24, transparent 65%)`}}/>
      <div style={{position: 'absolute', left: 72, right: 72, top: 115, display: 'flex', justifyContent: 'space-between',
        fontSize: 26, fontWeight: 700, letterSpacing: 3, color: '#c5d0dc'}}>
        <span>PC TIPS &amp; TRICKS</span><span style={{color: accent}}>PART {part}</span>
      </div>
      <div dir="auto" style={{position: 'absolute', left: 75, right: 75, top: 225, fontFamily: 'Lalezar, Arial, sans-serif',
        fontSize: 66, lineHeight: 1.25, textAlign: 'center', opacity: appearance}}>{block.title}</div>
      <div style={{position: 'absolute', left: 54, right: 54, top: 465, height: 920, borderRadius: 24,
        overflow: 'hidden', background: '#141d28', border: '2px solid #ffffff30', boxShadow: '0 28px 70px #0006'}}>
        <div style={{position: 'absolute', inset: 0, scale: String(block.zoom || 1)}}>
          {block.media && <OffthreadVideo src={staticFile(block.media.src)} muted startFrom={trim} playbackRate={playbackRate}
            style={{height: '100%', width: '100%', objectFit: block.fit || 'contain'}}/>}
        </div>
        {block.highlight && <div style={{position:'absolute',left:`${block.highlight.x}%`,top:`${block.highlight.y}%`,
          width:`${block.highlight.width}%`,height:`${block.highlight.height}%`,border:`5px solid ${accent}`,borderRadius:12}}/>}
      </div>
      <div style={{position: 'absolute', left: 72, right: 72, top: 1445, display: 'flex', justifyContent: 'space-between',
        alignItems: 'center', fontSize: 26, color: '#b4c3d2'}}>
        <span>{block.label}</span><span style={{fontSize: 25, color: accent}}>STEP {block.step_number || 1} / {block.step_count || 1}</span>
      </div>
      <div style={{position: 'absolute', left: 72, right: 72, bottom: 165, height: 3, background: '#ffffff1f'}}>
        <div style={{height: '100%', width: `${progress * 100}%`, background: accent}}/>
      </div>
    </>}
  </div>;
};
