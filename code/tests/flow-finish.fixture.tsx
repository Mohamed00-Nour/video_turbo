import React, {useLayoutEffect} from 'react';
import {Composition, registerRoot, useCurrentFrame} from 'remotion';
import {MainVideo} from '../src/MainVideo';
import {flowHandoffFrames} from '../src/flow/FlowScenes';

const blocks=[0,30,60].map(startFrame=>({type:'section',layout:'flow_clip',title:'Flow test',startFrame,durationFrames:30,
  captions:true,captionY:.8,flowFinishing:{headlines:true,headline_font:'serif',headline_motion:'blur_slide',depth_motif:'asterisk',depth_opacity:.53,depth_blur:16,transition:'blur',show_grid:true,overlay:true},flowAccent:'#8500BD',flowFinish:true,media:{src:'fixture.mp4',durationFrames:30},offset_seconds:0}));
const phrases=[['First','animated','caption','phrase'],['\u0639\u0645\u0644\u064a\u0629','Juice','Jacking','\u062e\u0637\u064a\u0631\u0629'],['Final','animated','caption','phrase']];
const words=phrases.flatMap((phrase,i)=>phrase.map((word,j)=>({word,startFrame:i*30+j*6,endFrame:i*30+(j+1)*6,start:(i*30+j*6)/30,end:(i*30+(j+1)*6)/30})));
const timeline={blocks,words,fps:30,totalFrames:90,captionsInGameBlocks:true};
const Fixture:React.FC<{disabled?:boolean;different?:boolean;unanalysed?:boolean}>=({disabled=false,different=false,unanalysed=false})=>{
  const frame=useCurrentFrame();
  useLayoutEffect(()=>{
    const visible=(selector:string)=>Array.from(document.querySelectorAll<HTMLElement>(selector)).filter(e=>e.getBoundingClientRect().width>0 && getComputedStyle(e).visibility!=='hidden');
    const caption=visible('[data-flow-caption]')[0];
    const headline=visible('[data-flow-display]')[0];
    console.log('FLOW_CHECK:'+JSON.stringify({frame,disabled,different,unanalysed,
      scenes:visible('[data-flow-scene]').map(e=>({start:Number(e.dataset.flowScene),held:e.dataset.flowHeld,opacity:Number(e.style.opacity),blur:e.style.filter})),
      headline:headline?{text:headline.textContent,opacity:Number(headline.style.opacity),blur:headline.style.filter,font:headline.style.fontFamily,fontStyle:headline.style.fontStyle,color:headline.style.color,top:headline.getBoundingClientRect().top,bottom:headline.getBoundingClientRect().bottom}:null,
      corners:visible('[data-corner]').map(e=>({corner:e.dataset.corner,opacity:Number(e.style.opacity),bounds:{x:e.getBoundingClientRect().x,y:e.getBoundingClientRect().y,width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height}})),
      depth:visible('[data-flow-depth] [data-depth]').map(e=>[e.style.top,e.style.right,e.style.left,e.style.rotate]),
      caption:caption?{opacity:Number(caption.style.opacity),blur:caption.style.filter,width:caption.getBoundingClientRect().width,
        words:Array.from(caption.querySelectorAll('span')).map(e=>({text:e.textContent,scale:(e as HTMLElement).style.scale})),
        english:Array.from(caption.querySelectorAll('bdi[dir="ltr"]')).map(e=>({text:e.textContent,positions:Array.from(e.querySelectorAll('span')).map(s=>s.getBoundingClientRect().x)}))}:null}));
  },[frame,disabled,different,unanalysed]);
  const data=disabled?{...timeline,blocks:blocks.map(b=>({...b,flowFinish:false}))}:different?{...timeline,blocks:blocks.map(b=>({...b,flowAccent:'#D60921',flowPalette:{background:'#111111',ink:'#ffffff'},flowFinishing:{headlines:true,headline_font:'sans',headline_motion:'fade',headline_color:'ink',depth_motif:'none',transition:'cut'}}))}:unanalysed?{...timeline,blocks:blocks.map(b=>({...b,flowFinishing:undefined}))}:timeline;
  return <MainVideo timeline={data as any}/>;
};
const Root:React.FC=()=>{
  for(const fps of [24,30,60]) for(const a of [1,2,3,5,30]) for(const b of [1,2,3,5,30]){
    const overlap=flowHandoffFrames({durationFrames:a},{durationFrames:b},fps);
    if(!Number.isInteger(overlap) || overlap<0 || overlap>Math.min(a,b)/3) throw new Error('Unbounded Flow overlap');
  }
  return <>
    <Composition id="FlowFixture" component={Fixture} durationInFrames={90} fps={30} width={1080} height={1920}/>
    <Composition id="OtherReference" component={Fixture} defaultProps={{different:true}} durationInFrames={90} fps={30} width={1080} height={1920}/>
    <Composition id="UnanalysedReference" component={Fixture} defaultProps={{unanalysed:true}} durationInFrames={90} fps={30} width={1080} height={1920}/>
    <Composition id="DisabledFlow" component={Fixture} defaultProps={{disabled:true}} durationInFrames={90} fps={30} width={1080} height={1920}/>
  </>;
};
registerRoot(Root);
