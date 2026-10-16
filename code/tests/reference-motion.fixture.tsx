import React, {useLayoutEffect} from 'react';
import {Composition, registerRoot, useCurrentFrame, useVideoConfig} from 'remotion';
import {MainVideo} from '../src/MainVideo';
import {Caption} from '../src/Caption';
import {handoffFrames} from '../src/reference/ReferenceScenes';

const style={renderer_version:3,background:'#111111',background_end:'#171717',ink:'#F5F5F2',accent:'#D60921',muted:'#929292',contrast_background:'#F0F0ED',heading_font:'sans',italic:false,float_amplitude:11,float_period:150,card_radius:28,caption_style:'phrase',caption_y:.86,ribbon:true,ribbon_width:1.5,grid_opacity:.08};
const blocks=[
  {startFrame:0,durationFrames:90,variant:'device',backdrop:'grid',motif:'warning',scene_tone:'base',transition_style:'settle',title:'\u0627\u062d\u0645\u064a \u0628\u064a\u0627\u0646\u0627\u062a\u0643'},
  {startFrame:90,durationFrames:90,variant:'steps',backdrop:'orbits',motif:'privacy',scene_tone:'base',transition_style:'settle',title:'Juice Jacking',details:['\u0635\u0648\u0631\u0643','\u0631\u0633\u0627\u064a\u0644\u0643']},
  {startFrame:180,durationFrames:90,variant:'device',backdrop:'diagonal',motif:'protection',scene_tone:'contrast',transition_style:'wipe',title:'Data Blocker'},
  {startFrame:270,durationFrames:60,variant:'type',backdrop:'spotlight',motif:'share',scene_tone:'base',transition_style:'cut',title:'\u0627\u0628\u0639\u062a\u0647 \u0644\u0635\u062d\u0627\u0628\u0643'},
].map(block=>({...block,type:'section',layout:'reference_style',referenceStyle:style,captions:true,details:block.details || []}));
const words=[['\u0639\u0645\u0644\u064a\u0629',90,94],['Juice',94,98],['Jacking',98,102],['\u062e\u0637\u064a\u0631\u0629',102,110]].map(([word,startFrame,endFrame])=>({word,startFrame,endFrame,start:Number(startFrame)/30,end:Number(endFrame)/30}));
const timeline={blocks,words,captionsInGameBlocks:true,totalFrames:330,fps:30};

const Fixture:React.FC<{legacy?:boolean}> = ({legacy=false}) => {
  const frame=useCurrentFrame(),{durationInFrames}=useVideoConfig();
  useLayoutEffect(()=>{
    const scenes=Array.from(document.querySelectorAll<HTMLElement>('[data-reference-scene]')).filter(el=>el.getBoundingClientRect().width>0 && getComputedStyle(el).visibility!=='hidden');
    const record={frame,durationInFrames,legacy,scenes:scenes.map(el=>({start:Number(el.dataset.referenceScene),opacity:Number(el.style.opacity),headlineOpacity:Number((el.querySelector('[data-reference-headline]') as HTMLElement)?.style.opacity),headlineFont:getComputedStyle(el.querySelector('[data-reference-headline]')!).fontFamily,clip:el.style.clipPath,line:el.querySelector('[data-flow-line]')?.getAttribute('d'),depth:Array.from(el.querySelectorAll<HTMLElement>('[data-depth="far"]')).map(layer=>layer.style.transform)})),english:[] as any[]};
    for(const el of Array.from(document.querySelectorAll<HTMLElement>('bdi[dir="ltr"]'))){
      record.english.push({text:el.textContent,direction:getComputedStyle(el).direction,parentDirection:getComputedStyle(el.parentElement!.parentElement!).direction,words:Array.from(el.querySelectorAll('span')).map(span=>({text:span.textContent,x:span.getBoundingClientRect().x,width:span.getBoundingClientRect().width})),width:el.getBoundingClientRect().width});
    }
    console.log('REFERENCE_CHECK:'+JSON.stringify(record));
  },[frame,legacy,durationInFrames]);
  const data=legacy?{...timeline,blocks:blocks.map(b=>({...b,referenceStyle:{...style,renderer_version:2}}))}:timeline;
  return <MainVideo timeline={data as any}/>;
};
const SvgCaptionFixture:React.FC = ()=>{
  const frame=useCurrentFrame();
  useLayoutEffect(()=>{
    const text=document.querySelector('svg text')!;
    console.log('SVG_CHECK:'+JSON.stringify({frame,text:text.textContent,direction:text.getAttribute('direction')}));
  },[frame]);
  return <Caption currentFrame={frame} timeline={{blocks:[{type:'section',layout:'title',startFrame:0,durationFrames:30}],words:[{word:'USB-C',startFrame:0,endFrame:15},{word:'\u0628\u064a\u0627\u0646\u0627\u062a\u0643',startFrame:15,endFrame:30}]} as any}/>;
};
const Root:React.FC=()=>{
  for(const fps of [24,30,60]) for(const a of [1,2,3,10,90]) for(const b of [1,2,3,10,90]){
    const overlap=handoffFrames({durationFrames:a},{durationFrames:b,transition_style:'settle'},fps);
    if(!Number.isInteger(overlap) || overlap<0 || overlap>Math.min(a,b)/3) throw new Error('Unbounded scene overlap');
  }
  return <>
    <Composition id="MotionFixture" component={Fixture} durationInFrames={330} fps={30} width={1080} height={1920}/>
    <Composition id="LegacyFixture" component={Fixture} defaultProps={{legacy:true}} durationInFrames={330} fps={30} width={1080} height={1920}/>
    <Composition id="SvgCaptionFixture" component={SvgCaptionFixture} durationInFrames={30} fps={30} width={1080} height={1920}/>
  </>;
};
registerRoot(Root);
