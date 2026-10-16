import React from 'react';

// One absolute clock keeps the depth layers moving through scene handoffs.
export const MovingBackdrop: React.FC<{block:any; frame:number; fps:number; ink:string; accent:string; dark:boolean}> = ({block,frame,fps,ink,accent,dark}) => {
  const s=block.referenceStyle,t=(block.startFrame+frame)/fps;
  const slow=Math.sin(t*.23),cross=Math.cos(t*.19),near=Math.sin(t*.41);
  const path=`M-150 ${1740+slow*90} C${1020+cross*75} ${1910+near*60} ${1310+slow*90} ${940+cross*95} ${700+near*65} ${730+slow*80} S${-180+cross*65} ${950+near*80} ${90+slow*75} ${480+cross*70} S${1220+near*100} ${110+slow*85} 1210 -180`;
  return <div aria-hidden="true" data-moving-backdrop="true" style={{position:'absolute',inset:0,overflow:'hidden',pointerEvents:'none'}}>
    {(block.backdrop==='grid' || block.variant==='device') && <div data-depth="far" style={{position:'absolute',inset:-220,
      opacity:s.grid_opacity ?? .08,backgroundImage:`linear-gradient(${ink} 1px,transparent 1px),linear-gradient(90deg,${ink} 1px,transparent 1px)`,
      backgroundSize:'172px 172px',transform:`translate(${slow*24}px,${cross*35}px) rotate(${near*.6}deg)`,
      maskImage:'radial-gradient(ellipse at center,#000 20%,transparent 80%)'}}/>}
    {block.backdrop==='diagonal' && <div data-depth="far" style={{position:'absolute',inset:-450,
      transform:`translate(${slow*50}px,${cross*36}px) rotate(${-33+near*2}deg)`,
      background:`repeating-linear-gradient(90deg,transparent 0px,transparent 180px,${ink}0a 183px,transparent 240px)`,filter:'blur(12px)'}}/>}
    {(s.ribbon || block.backdrop==='orbits') && <svg data-depth="near" width="1080" height="1920" viewBox="0 0 1080 1920" style={{position:'absolute',inset:0,opacity:.4}}>
      <path data-flow-line="true" d={path} fill="none" stroke={block.scene_tone==='contrast'?accent:ink} strokeWidth={s.ribbon_width ?? 2}/>
      {block.backdrop==='orbits' && <g transform={`translate(${540+slow*38} ${1080+cross*48}) rotate(${t*2.5})`}>
        <ellipse rx="510" ry="400" fill="none" stroke={ink} strokeWidth="1" opacity=".28"/>
        <ellipse rx="600" ry="460" fill="none" stroke={accent} strokeWidth="1" opacity=".15"/>
      </g>}
    </svg>}
    {block.backdrop==='spotlight' && <div data-depth="far" style={{position:'absolute',left:-220,top:430,width:1500,height:1300,
      transform:`translate(${slow*75}px,${cross*60}px) scale(${1+near*.04})`,
      background:`radial-gradient(ellipse,${dark?accent+'12':'#ffffff'} 0%,transparent 63%)`}}/>}
  </div>;
};
