import React from 'react';
import {Composition} from 'remotion';
import '../src/font.css';
import {Caption} from '../src/Caption';
import {useCurrentFrame} from 'remotion';
import {PcTipsScene} from '../src/PcTipsScene';
const Intro:React.FC=()=> <PcTipsScene block={{layout:'pc_intro',durationFrames:60,part:12,accent:'#66e1ff',media:{src:'setup.png',kind:'image'}}}/>;
const Demo:React.FC=()=> {
 const frame=useCurrentFrame();
 const block={layout:'pc_demo',startFrame:0,durationFrames:90,part:12,accent:'#66e1ff',title:'وصل للنص اللي نسخته بسرعة',label:'Windows 10',step_number:1,step_count:2,captionY:.82,
  media:{src:'screen.mp4',kind:'video',durationFrames:30}};
 const words=['افتح','القائمة','واختار','النص'].map((word,i)=>({word,start:i*.5,end:(i+1)*.5,startFrame:i*15,endFrame:i===3?90:(i+1)*15}));
 return <><PcTipsScene block={block}/><Caption currentFrame={frame} timeline={{blocks:[block],words,captionsInGameBlocks:true} as any}/></>;
};
import {registerRoot} from 'remotion';
registerRoot(()=> <><Composition id="PcIntroFixture" component={Intro} durationInFrames={60} fps={30} width={1080} height={1920}/><Composition id="PcDemoFixture" component={Demo} durationInFrames={90} fps={30} width={1080} height={1920}/></>);
