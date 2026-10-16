import React from 'react';

export const textDirection = (text:string): 'rtl'|'ltr' => {
  const letter=text.match(/\p{L}/u)?.[0];
  return letter && /\p{Script=Arabic}/u.test(letter)?'rtl':'ltr';
};

// Keep a consecutive English phrase in a single isolate inside an Arabic line.
// Isolating every English word separately would reverse "Juice Jacking".
export const CaptionWords: React.FC<{words:{word:string}[]; wordStyle:(index:number)=>React.CSSProperties}> = ({words,wordStyle}) => {
  const runs:{direction:'rtl'|'ltr';indices:number[]}[]=[];
  words.forEach((word,index)=>{
    const direction=textDirection(word.word),last=runs[runs.length-1];
    if(last?.direction===direction) last.indices.push(index);
    else runs.push({direction,indices:[index]});
  });
  return <>{runs.map((run,index)=><React.Fragment key={index}>
    {index>0?' ':null}<bdi dir={run.direction} lang={run.direction==='ltr'?'en':undefined} style={{display:'inline-block',maxWidth:'100%',unicodeBidi:'isolate'}}>
      {run.indices.map((i,j)=><React.Fragment key={i}>{j>0?' ':null}<span style={wordStyle(i)}>{words[i].word}</span></React.Fragment>)}
    </bdi>
  </React.Fragment>)}</>;
};
