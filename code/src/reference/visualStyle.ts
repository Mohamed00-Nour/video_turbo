export const darkColor = (color: string) => {
  const rgb=[1,3,5].map(i=>parseInt(color.slice(i,i+2),16)/255);
  return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722 < .46;
};

export const scenePalette = (s: any, block: any) => {
  const background=block.scene_tone==='contrast' ? (s.contrast_background || (darkColor(s.background)?'#F3F3EF':'#141615')) : block.scene_tone==='accent' ? s.accent : s.background;
  const dark=darkColor(background);
  const ink=block.scene_tone==='base' || !block.scene_tone ? s.ink : dark?'#F5F5F2':'#151615';
  return {background,ink,dark,accent:block.scene_tone==='accent'?ink:s.accent,muted:dark?'#A8ABA5':'#62645F',panel:dark?'#202220':'#FFFFFF'};
};
