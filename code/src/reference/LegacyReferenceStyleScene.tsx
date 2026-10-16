import React from 'react';
import { Img, interpolate, staticFile, useCurrentFrame } from 'remotion';
import { LoopingVideo } from '../LoopingVideo';

export const LegacyReferenceStyleScene: React.FC<{block: any}> = ({block}) => {
  const frame = useCurrentFrame();
  const s = block.referenceStyle;
  const duration = block.durationFrames;
  const enter = interpolate(frame, [0, 18], [0, 1], {extrapolateLeft:'clamp',extrapolateRight:'clamp'});
  const exit = interpolate(frame, [Math.max(19,duration-9), Math.max(20,duration-1)], [0,1], {extrapolateLeft:'clamp',extrapolateRight:'clamp'});
  const drift = Math.sin(frame / s.float_period * Math.PI * 2) * s.float_amplitude;
  const progress = frame / Math.max(1,duration-1);
  const font = s.heading_font === 'serif' ? 'ReferenceAmiri' : s.heading_font === 'display' ? 'Lalezar' : 'ReferencePlex';
  const shadow = `0 ${s.shadow_y}px ${s.shadow_blur}px rgba(0,0,0,${s.shadow_opacity})`;
  const rtl = /[\u0600-\u06ff]/.test(block.title + block.emphasis);
  const visual = (media: any, style: React.CSSProperties) => media && <div style={style}>
    {media.kind === 'image' ? <Img src={staticFile(media.src)} style={{width:'100%',height:'100%',objectFit:block.fit || 'contain'}}/> :
      <LoopingVideo src={media.src} durationFrames={media.durationFrames} offsetSeconds={block.offset_seconds || 0} style={{width:'100%',height:'100%',objectFit:block.fit || 'cover'}}/>}
  </div>;
  return <div style={{position:'absolute',inset:0,overflow:'hidden',background:`radial-gradient(ellipse at 50% 38%, ${s.background} 15%, ${s.background_end} 100%)`,color:s.ink}}>
    <style>{`
      @font-face {font-family:ReferencePlex;src:url('${staticFile('reference-fonts/ibm-plex-sans-arabic-700.woff2')}');font-weight:700;}
      @font-face {font-family:ReferenceAmiri;src:url('${staticFile('reference-fonts/Amiri-Bold.ttf')}');font-weight:700;}
    `}</style>
    <div style={{position:'absolute',left:-120,top:650,width:1320,textAlign:'center',fontFamily:font,fontWeight:700,fontSize:330,color:s.ink,opacity:.045,rotate:'-18deg'}} dir="auto">{block.emphasis || block.title}</div>
    {s.ribbon && <svg width="1080" height="1920" viewBox="0 0 1080 1920" style={{position:'absolute',inset:0,translate:`0px ${160+drift*.6}px`}}><path d="M-180 1220 C100 1580 990 1380 1170 920 C1350 470 140 440 -120 840" fill="none" stroke={s.accent} strokeWidth="94" opacity={block.variant==='type'?.16:.9}/></svg>}
    <div style={{position:'absolute',inset:0,opacity:enter*(1-exit),
      translate:s.entrance === 'slide' ? `${(1-enter)*170}px ${s.transition==='lift' ? -exit*120 : 0}px` : `0px ${(s.entrance==='rise'?(1-enter)*120:0)-(s.transition==='lift'?exit*120:0)}px`,
      scale:s.entrance==='zoom' ? .88+.12*enter : 1,
      filter:s.transition==='blur'?`blur(${(1-enter)*10+exit*12}px)`:'none'}}>
      {block.label && <div dir="auto" style={{position:'absolute',top:180,left:100,right:100,textAlign:'center',fontFamily:'ReferencePlex',fontWeight:700,fontSize:30,color:s.muted,letterSpacing:rtl?0:3}}>{block.label}</div>}
      <div dir="auto" style={{position:'absolute',top:block.variant==='type'?560:310,left:90,right:90,textAlign:'center',fontFamily:font,fontWeight:700,fontStyle:s.italic?'italic':'normal',fontSize:block.title.length>55?62:86,lineHeight:1.3,translate:`0px ${-12*progress}px`}}>
        <div>{block.title}</div>
        {block.emphasis && <div style={{color:s.accent,fontSize:block.emphasis.length>28?88:120,lineHeight:1.24,marginTop:20}}>{block.emphasis}</div>}
      </div>
      {block.variant==='hero' && visual(block.media,{position:'absolute',left:140,top:700+drift,width:800,height:790,filter:`drop-shadow(${shadow})`,rotate:`${-7+progress*10}deg`})}
      {block.variant==='card' && visual(block.media,{position:'absolute',left:130,top:720+drift,width:820,height:720,borderRadius:s.card_radius,overflow:'hidden',background:s.background_end,boxShadow:shadow,rotate:`${-5+progress*7}deg`})}
      {block.variant==='collage' && <>
        {visual(block.media,{position:'absolute',left:80,top:710+drift,width:740,height:470,borderRadius:s.card_radius,overflow:'hidden',background:s.background_end,boxShadow:shadow,rotate:`${-8+progress*6}deg`})}
        {visual(block.secondary_media || block.media,{position:'absolute',left:260,top:1080-drift,width:720,height:460,borderRadius:s.card_radius,overflow:'hidden',background:s.background_end,boxShadow:shadow,rotate:`${7-progress*8}deg`})}
      </>}
      {block.variant==='type' && <div style={{position:'absolute',left:420,top:1110+drift,width:240,height:8,background:s.accent,borderRadius:6,scale:enter}}/>}
    </div>
  </div>;
};
