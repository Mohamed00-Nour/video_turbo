(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const labels = {youtube:'YouTube',instagram:'Instagram',facebook_page:'Facebook Page'};
  const statuses = {ready:'Updated',pending:'Awaiting refresh',reconnect:'Reconnect account',permission:'Permission needed',unavailable:'Data unavailable',rate_limited:'Try later'};
  const format = value => value === null || value === undefined ? '\u2014' : new Intl.NumberFormat().format(value);
  const stamp = value => value ? new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'short'}).format(new Date(value*1000)) : 'Not refreshed yet';
  const safeLink = value => { try { const parsed = new URL(value); return parsed.protocol === 'https:' ? parsed.href : ''; } catch { return ''; } };
  const sum = posts => { const known = posts.filter(post => post.views !== null && post.views !== undefined); return known.length ? known.reduce((total,post)=>total+post.views,0) : null; };
  const view = {api:null,openPublishing:null,ready:false,busy:false,data:null,signature:'',selected:'',days:7,history:null,historyRequest:0,timer:null,polling:false};
  const dialog = $('analytics-dialog');
  if (!dialog) return;
  $('analytics-panel').innerHTML = `
    <header class="analytics-heading"><div><div class="eyebrow">THE STORY AFTER PUBLISHING</div><h2 id="analytics-heading">Your videos, in numbers.</h2><p class="hint">Views across your channels, with growth recorded over time.</p></div><button type="button" id="analytics-close" class="quiet analytics-close" aria-label="Close analytics">&times;</button></header>
    <div class="analytics-toolbar"><p id="analytics-refresh-state" role="status" aria-live="polite">Loading your published videos...</p><button type="button" id="analytics-refresh" class="primary">Refresh views</button></div>
    <p id="analytics-error" class="publish-error" role="alert" hidden></p>
    <section class="analytics-overview" id="analytics-overview" aria-label="View totals"></section>
    <p class="analytics-total-note">Combined views add the reported platform counts. A viewer can count on more than one platform.</p>
    <section id="analytics-attention" class="analytics-attention" aria-label="Accounts needing attention" hidden></section>
    <section class="analytics-chart-card" aria-labelledby="analytics-chart-heading"><div class="analytics-section-heading"><div><div class="eyebrow">WATCH YOUR VIDEO GROW</div><h3 id="analytics-chart-heading">Views over time</h3></div><div class="analytics-range" role="group" aria-label="Chart time range"><button type="button" data-analytics-days="7" aria-pressed="true">7 days</button><button type="button" data-analytics-days="30" aria-pressed="false">30 days</button></div></div>
      <label class="field analytics-video-picker">Video<select id="analytics-video" aria-label="Video to chart"></select></label>
      <p id="analytics-chart-summary" class="analytics-chart-summary" role="status"></p><div id="analytics-chart" class="analytics-chart"></div><div id="analytics-legend" class="analytics-legend"></div>
      <p class="hint analytics-history-note">History starts with the first successful refresh. Each point is a saved count; changes include any corrections made by the platform.</p>
      <details id="analytics-history-table" class="analytics-history-table" hidden><summary>Recorded view counts</summary><div class="analytics-table-scroll"><table><caption class="analytics-table-caption">Latest saved counts for this video</caption><thead><tr><th scope="col">Recorded</th><th scope="col">Platform</th><th scope="col">Views</th></tr></thead><tbody id="analytics-samples"></tbody></table></div></details>
    </section>
    <section class="analytics-videos" aria-labelledby="analytics-videos-heading"><div class="analytics-section-heading"><div><h3 id="analytics-videos-heading">Published videos</h3><p id="analytics-video-count" class="hint"></p></div><label class="field analytics-search">Find a video<input id="analytics-search" type="search" placeholder="Search titles or project names"></label></div>
      <div class="analytics-table-scroll"><table class="analytics-video-table"><caption class="analytics-table-caption">Select a video title to see its recorded growth</caption><thead><tr><th scope="col">Video</th><th scope="col">YouTube</th><th scope="col">Instagram</th><th scope="col">Facebook</th><th scope="col">Combined views</th></tr></thead><tbody id="analytics-videos-list"></tbody></table></div>
      <p id="analytics-empty" class="analytics-empty" hidden>Upload a video through Video Turbo to start tracking its views.</p>
    </section>`;

  function allPosts() { return (view.data?.videos || []).flatMap(video=>video.posts); }
  function feedback(message) { $('analytics-error').textContent = message || ''; $('analytics-error').hidden = !message; }
  function lock(ready) {
    if (typeof ready === 'boolean') view.ready = ready;
    $('analytics-nav').disabled = !view.ready;
    dialog.querySelectorAll('button,input,select').forEach(element=> { element.disabled = !view.ready; });
    $('analytics-close').disabled = false;
    const refreshing = view.data?.job?.status === 'running';
    $('analytics-refresh').disabled = !view.ready || view.busy || refreshing;
    $('analytics-refresh').textContent = refreshing ? 'Refreshing views...' : 'Refresh views';
    $('analytics-video').disabled = !view.ready || !view.data?.videos?.length;
  }
  function renderRefresh() {
    const job = view.data?.job;
    $('analytics-refresh-state').textContent = job?.status === 'running' ? `Refreshing ${job.completed} of ${job.total} posts...` : job?.status === 'failed' ? 'Refresh interrupted. Saved counts remain available.' : 'Last refresh attempt: ' + stamp(view.data?.last_refresh) + ' \u00b7 Auto refresh every 15 minutes while Studio runs.';
    lock();
  }
  function renderOverview() {
    const posts = allPosts();
    $('analytics-overview').innerHTML = ['all',...Object.keys(labels)].map(platform=> {
      const group = platform === 'all' ? posts : posts.filter(post=>post.platform===platform);
      const available = group.filter(post=>post.views !== null && post.views !== undefined);
      const latest = Math.max(0,...available.map(post=>post.updated || 0));
      return `<article class="analytics-stat ${platform==='all'?'analytics-stat-total':''}"><span class="analytics-stat-label">${platform==='all'?'Combined reported views':labels[platform]}</span><strong>${format(sum(group))}</strong><small>${available.length} of ${group.length} posts have saved counts${latest?'<br>Last count: '+esc(stamp(latest)):''}</small></article>`;
    }).join('');
    const problems = Object.keys(labels).map(platform=> {
      const group = posts.filter(post=>post.platform===platform && !['ready','pending'].includes(post.status));
      if (!group.length) return '';
      const post = group.find(post=>['reconnect','permission'].includes(post.status)) || group[0];
      const instructions = platform === 'instagram' ? 'For a linked account, reconnect its Facebook Page. Analytics needs instagram_manage_insights and pages_read_engagement; Instagram Login uses instagram_business_manage_insights.' : platform === 'facebook_page' ? 'Use a fresh Page token with pages_read_engagement and, for Insights, read_insights.' : 'Reconnect your channel if the saved authorization cannot be renewed.';
      return `<article class="analytics-notice"><div><strong>${labels[platform]} &middot; ${esc(statuses[post.status] || 'Needs attention')}</strong><p>${esc(post.message)}</p><p class="hint">${esc(instructions)}</p></div><button type="button" class="outline small" data-analytics-setup="${platform}" data-analytics-project="${esc(post.project)}">Open account setup</button></article>`;
    }).join('');
    $('analytics-attention').innerHTML = problems; $('analytics-attention').hidden = !problems;
    const videos = view.data?.videos || [];
    if (!videos.some(video=>video.id===view.selected)) view.selected = videos[0]?.id || '';
    $('analytics-video').innerHTML = videos.map(video=>`<option value="${esc(video.id)}" ${video.id===view.selected?'selected':''}>${esc(video.title)}</option>`).join('') || '<option>No uploaded videos yet</option>';
    renderVideos();
  }
  function renderVideos() {
    const query = $('analytics-search').value.trim().toLocaleLowerCase();
    const videos = (view.data?.videos || []).filter(video=>(video.title+' '+video.project_name).toLocaleLowerCase().includes(query));
    $('analytics-video-count').textContent = videos.length + ' video' + (videos.length===1?'':'s') + ' \u00b7 Counts stay available after restarting Studio.';
    $('analytics-videos-list').innerHTML = videos.map(video=> {
      const cells = Object.keys(labels).map(platform=> {
        const posts = video.posts.filter(post=>post.platform===platform);
        const value = sum(posts); const problem = posts.find(post=>post.status!=='ready');
        const links = posts.map(post=> { const url=safeLink(post.url); return url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer" aria-label="Open ${labels[platform]} post">Open post &nearr;</a>`:''; }).join('');
        return `<td><strong>${format(value)}</strong><small>${esc(problem?statuses[problem.status]||'Needs attention':posts.length?'Updated':'Not uploaded')}</small>${links}</td>`;
      }).join('');
      return `<tr ${video.id===view.selected?'class="selected"':''}><th scope="row"><button type="button" data-analytics-video="${esc(video.id)}" class="analytics-video-title" ${video.id===view.selected?'aria-current="true"':''} dir="auto">${esc(video.title)}</button><small>${esc(stamp(video.published))}</small></th>${cells}<td class="analytics-total-cell"><strong>${format(sum(video.posts))}</strong></td></tr>`;
    }).join('');
    $('analytics-empty').hidden = videos.length > 0;
    $('analytics-empty').textContent = query ? 'No published videos match your search.' : 'Upload a video through Video Turbo to start tracking its views.';
    lock();
  }
  function renderChart() {
    const series = view.history?.series || [];
    const available = series.filter(item=>item.points.length);
    const growing = series.filter(item=>item.change !== null && item.change !== undefined);
    const delta = growing.length ? growing.reduce((total,item)=>total+item.change,0) : null;
    const first = Math.min(...available.flatMap(item=>item.points.map(point=>point.recorded)));
    $('analytics-chart-summary').textContent = available.length ? (delta===null?'Your first counts are saved.':'Observed change: '+(delta>=0?'+':'')+format(delta)+' views across '+growing.length+' tracked post'+(growing.length===1?'':'s')+'.') + ' Tracking since ' + stamp(first) + '.' : 'No view history yet. A successful refresh starts tracking.';
    const names = item=>labels[item.platform]+(item.account?' \u00b7 '+item.account:'');
    $('analytics-legend').innerHTML = available.map((item,index)=>`<span><svg width="28" height="10" aria-hidden="true"><path d="M0 5H28" stroke="var(--chart-${item.platform})" stroke-width="3" stroke-dasharray="${['','7 4','2 4'][index%3]}"/></svg>${esc(names(item))}</span>`).join('');
    const samples = series.flatMap(item=>item.points.slice(-20).map(point=>({...point,platform:names(item)}))).sort((a,b)=>b.recorded-a.recorded);
    $('analytics-samples').innerHTML = samples.map(point=>`<tr><td>${esc(stamp(point.recorded))}</td><td>${esc(point.platform)}</td><td>${format(point.views)}</td></tr>`).join('');
    $('analytics-history-table').hidden = !samples.length;
    if (!available.some(item=>item.points.length>=4)) {
      $('analytics-chart').innerHTML = `<div class="analytics-chart-empty"><strong>${available.length?'Your growth history is collecting.':'Your next view count starts here.'}</strong><p>${available.length?'The chart appears after four saved samples. Counts refresh every 15 minutes; you can inspect the first samples below.':'Refresh views after connecting analytics access. Recorded points will appear here as your videos grow.'}</p></div>`;
      return;
    }
    const width=900, left=60, right=875, top=20, bottom=235;
    const max=Math.max(4,Math.ceil(Math.max(...available.flatMap(item=>item.points.map(point=>point.views)))/4)*4);
    const start=Math.max(view.history.start,first); const end=Math.max(start+1,view.history.end);
    const x=time=>left+Math.max(0,Math.min(1,(time-start)/(end-start)))*(right-left);
    const y=value=>bottom-value/max*(bottom-top);
    const compact=value=>new Intl.NumberFormat(undefined,{notation:'compact',maximumFractionDigits:1}).format(value);
    const ticks=Array.from({length:5},(_,index)=> { const value=max*index/4;return `<line x1="${left}" x2="${right}" y1="${y(value)}" y2="${y(value)}" class="analytics-grid-line"/><text x="${left-12}" y="${y(value)+4}" text-anchor="end">${esc(compact(value))}</text>`; }).join('');
    const lines=available.map((item,index)=> {
      const path=item.points.map((point,i)=>(i?'L':'M')+x(point.recorded).toFixed(2)+' '+y(point.views).toFixed(2)).join(' ');
      const every=Math.max(1,Math.ceil(item.points.length/12));
      const dots=item.points.filter((_,i)=>i%every===0||i===item.points.length-1).map(point=>`<circle cx="${x(point.recorded)}" cy="${y(point.views)}" r="4" fill="var(--chart-${item.platform})" tabindex="0" role="img" aria-label="${esc(names(item)+': '+format(point.views)+' views, '+stamp(point.recorded))}"><title>${esc(names(item)+': '+format(point.views)+' views, '+stamp(point.recorded))}</title></circle>`).join('');
      return `<path d="${path}" stroke="var(--chart-${item.platform})" stroke-width="3" stroke-dasharray="${['','7 4','2 4'][index%3]}" fill="none"/>${dots}`;
    }).join('');
    const date=value=>new Intl.DateTimeFormat(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}).format(new Date(value*1000));
    $('analytics-chart').innerHTML = `<svg viewBox="0 0 ${width} 275" role="img" aria-label="Saved video views over time. A table of recorded counts is available below.">${ticks}${lines}<text x="${left}" y="263">${esc(date(start))}</text><text x="${right}" y="263" text-anchor="end">${esc(date(end))}</text></svg>`;
  }
  async function loadHistory() {
    const request=++view.historyRequest, video=view.selected, days=view.days;
    if (!video) { view.history=null;renderChart();return; }
    try {
      const data=await view.api('/api/analytics/history?video='+encodeURIComponent(video)+'&days='+days);
      if(request!==view.historyRequest)return;view.history=data;renderChart();
    } catch(error) { if(request===view.historyRequest)feedback(error.message); }
  }
  async function load() {
    if(!view.api||view.polling)return;
    view.polling=true;
    try {
      const data=await view.api('/api/analytics');view.data=data;
      const signature=JSON.stringify(data.videos);
      if(signature!==view.signature){view.signature=signature;renderOverview();await loadHistory();}
      renderRefresh();
    } catch(error) { feedback(error.message); }
    finally {view.polling=false;lock();}
  }
  async function open() {
    if(!view.api||!view.ready)return;
    if(!dialog.open)dialog.showModal();$('analytics-nav').setAttribute('aria-expanded','true');feedback('');
    await load();
    if(!view.timer)view.timer=setInterval(()=>{if(dialog.open)load();},4000);
  }
  $('analytics-close').onclick=()=>dialog.close();
  dialog.addEventListener('close',()=>{$('analytics-nav').setAttribute('aria-expanded','false');clearInterval(view.timer);view.timer=null;});
  $('analytics-nav').onclick=open;
  $('analytics-refresh').onclick=async()=>{
    if(view.busy||!view.ready)return;view.busy=true;lock();feedback('');
    try{const result=await view.api('/api/analytics/refresh',{});if(!result.started)feedback(result.message);await load();}
    catch(error){feedback(error.message);}finally{view.busy=false;lock();}
  };
  $('analytics-search').addEventListener('input',renderVideos);
  $('analytics-video').addEventListener('change',()=>{view.selected=$('analytics-video').value;renderVideos();loadHistory();});
  dialog.addEventListener('click',async event=>{
    const button=event.target.closest('button');if(!button||button.disabled)return;
    const {analyticsDays,analyticsVideo,analyticsSetup,analyticsProject}=button.dataset;
    if(analyticsDays){view.days=Number(analyticsDays);for(const item of dialog.querySelectorAll('[data-analytics-days]'))item.setAttribute('aria-pressed',String(item===button));loadHistory();}
    else if(analyticsVideo){view.selected=analyticsVideo;$('analytics-video').value=analyticsVideo;renderVideos();await loadHistory();$('analytics-chart-heading').scrollIntoView({block:'nearest',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});}
    else if(analyticsSetup){dialog.close();try{if(!await view.openPublishing(analyticsProject,analyticsSetup))await open();}catch(error){await open();feedback(error.message);}}
  });
  window.VideoTurboAnalytics={configure({api,openPublishing}){view.api=api;view.openPublishing=openPublishing;lock();},lock,open};
})();
