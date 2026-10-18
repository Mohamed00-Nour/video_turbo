export const neutralFlowFinishing={
  headlines:false,headline_font:'sans',headline_motion:'fade',headline_position:'top',
  headline_color:'accent',show_grid:false,overlay:false,depth_motif:'none',depth_opacity:.3,
  depth_blur:16,transition:'cut',transition_seconds:.3,sound:'none',caption_style:'panel',
};
export const getFlowFinishing=(block:any)=>({...neutralFlowFinishing,...block.flowFinishing});
