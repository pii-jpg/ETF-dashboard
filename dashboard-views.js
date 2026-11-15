// 视图层（加载顺序 3/3）：图表 SVG、六个页签渲染、事件绑定与启动。
function broadBarChart(labels,series,{unit='亿份',boxWidth=chartWidth,emptyText='暂无可绘制的每日份额数据',ariaLabel='六个重点宽基累计份额每日堆叠柱状图',showLegend=true,tickDigits=0}={}){
  const width=boxWidth,height=132,pad={l:74,r:24,t:10,b:24};
  if(!labels.length||!series.some(s=>s.values.some(Number.isFinite)))return `<div class="empty">${emptyText}</div>`;
  const stacks=labels.map((_,i)=>{let up=0,down=0;for(const s of series){const v=s.values[i];if(!Number.isFinite(v))continue;if(v>=0)up+=v;else down+=v}return {up,down}});
  let min=Math.min(0,...stacks.map(x=>x.down)),max=Math.max(0,...stacks.map(x=>x.up));
  if(min===max){min-=1;max+=1}
  const span=Math.max(max-min,1e-9),padded=span*.08;min=min<0?min-padded:0;max+=padded;
  const plotW=width-pad.l-pad.r,groupW=plotW/labels.length,barW=Math.min(28,Math.max(.8,groupW*.82));
  const y=v=>pad.t+(max-v)*(height-pad.t-pad.b)/(max-min),zero=y(0);
  const ticks=Array.from({length:5},(_,i)=>max-i*(max-min)/4),tickEvery=Math.max(1,Math.ceil(labels.length/8));
  const stackOrder=[...series].reverse();
  const bars=labels.map((label,i)=>{
    const bx=(pad.l+i*groupW+(groupW-barW)/2).toFixed(2);let upBase=0,downBase=0;
    return stackOrder.map(s=>{
      const v=s.values[i];if(!Number.isFinite(v)||v===0)return '';
      let top,h;
      if(v>0){const yBase=y(upBase);upBase+=v;top=y(upBase);h=yBase-top}
      else{const yBase=y(downBase);downBase+=v;top=yBase;h=y(downBase)-yBase}
      return `<rect x="${bx}" y="${top.toFixed(2)}" width="${barW.toFixed(2)}" height="${Math.max(.6,h).toFixed(2)}" fill="${v>=0?(s.positiveColor||s.color):(s.negativeColor||s.color)}"><title>${label} · ${s.name}：${signed(v,2,unit)}</title></rect>`;
    }).join('');
  }).join('');
  const targets=labels.map((_,i)=>`<rect class="trend-hover-target" data-star-point="${i}" data-star-x="${(pad.l+i*groupW+groupW/2).toFixed(2)}" x="${(pad.l+i*groupW).toFixed(2)}" y="${pad.t}" width="${Math.max(1,groupW).toFixed(2)}" height="${height-pad.t-pad.b}"/>`).join('');
  const legend=series.map(s=>`<span style="color:${s.color}"><i style="background:${s.color}"></i>${s.name}</span>`).join('');
  return `<div class="trend-wrap">${showLegend?`<div class="trend-legend">${legend}</div>`:''}<svg class="trend-chart multi-trend-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${ariaLabel}">${ticks.map(v=>`<line x1="${pad.l}" x2="${width-pad.r}" y1="${y(v)}" y2="${y(v)}" class="grid-line"/><text x="${pad.l-10}" y="${y(v)+4}" text-anchor="end">${num(v,tickDigits)}${unit}</text>`).join('')}<line x1="${pad.l}" x2="${width-pad.r}" y1="${zero}" y2="${zero}" class="zero-line"/>${bars}<line class="trend-hover-line" x1="0" x2="0" y1="${pad.t}" y2="${height-pad.b}" visibility="hidden"/>${targets}${labels.map((label,i)=>(i%tickEvery===0||i===labels.length-1)?`<text x="${(pad.l+i*groupW+groupW/2).toFixed(2)}" y="${height-8}" text-anchor="middle">${axisLabel(label)}</text>`:'').join('')}</svg><div class="trend-tooltip" role="status" hidden></div></div>`;
}
function broadChangePanel(){
  const all=broadIndexStats(),rows=all.filter(x=>broadIsOn(x.code)).sort((a,b)=>b.delta-a.delta),max=Math.max(1,...rows.map(x=>Math.abs(x.delta)));
  const periodLabel=state.flows.periods[state.period]?.label||'';
  const body=rows.length
    ?rows.map(x=>`<div class="broad-change-row"><span>${x.name}</span><i><em class="${x.delta>=0?'bar-up':'bar-down'}" style="width:${Math.max(2,Math.abs(x.delta)/max*100)}%"></em></i><strong class="${cls(x.delta)}">${signed(x.delta,2)}</strong></div>`).join('')
    :'<div class="empty">已取消全部宽基，右侧排行暂无数据</div>';
  return `<section class="panel broad-change-panel">
    <div class="panel-title"><h2>主要宽基增加份额</h2><span>${periodLabel}${rows.length<all.length?` · 已选 ${rows.length}/${all.length}`:''}</span></div>
    <div class="broad-change-list" style="justify-content:${rows.length>=4?'space-between':'flex-start'}">${body}</div>
    <div class="chart-data-note">区间内各指数全部跟踪ETF的份额变动合计（亿份）；无期初基期的ETF不计入；仅统计上方勾选的宽基。</div>
  </section>`;
}
function broadSharePanel(){
  const data=broadShareSeries();
  const zoomed=zoomedChartData(data.dates,data.series.concat(data.dailyShares),state.broadZoom,state.broadPan),panStep=Math.max(1,Math.floor(zoomed.visible/2));
  const cumulativeSeries=zoomed.series.filter(item=>item.kind==='cumulative');
  const byCode=new Map(cumulativeSeries.map(item=>[item.code,item]));
  // 宽基选择：null = 全部显示；数组 = 仅显示选中的
  const isOn=code=>broadIsOn(code);
  const allSeries=[...BROAD_CHART_ORDER.map(code=>byCode.get(code)).filter(Boolean),...cumulativeSeries.filter(item=>!BROAD_CHART_ORDER.includes(item.code))];
  const picked=allSeries.filter(item=>isOn(item.code));
  const visible={...zoomed,series:picked};
  // 每日增减与累计份额共用同一次切片（同一 labels 长度与 zoom/pan），两图窗口严格一致；每日柱按方向着色
  const dailyByCode=new Map(zoomed.series.filter(item=>item.kind==='dailyShares').map(item=>[item.code,item]));
  const dailySeries=picked.map(item=>dailyByCode.get(item.code)).filter(Boolean).map(item=>({...item,positiveColor:'#f05f66',negativeColor:'#33c58e'}));
  const daily={...zoomed,series:dailySeries};
  const picker=`<div class="broad-picker" role="group" aria-label="选择要显示的宽基指数">${allSeries.map(item=>`<label class="broad-chip${isOn(item.code)?' on':''}" style="--dot:${item.color}"><input type="checkbox" data-broad-toggle="${item.code}" ${isOn(item.code)?'checked':''} /><i></i><span>${item.name}</span></label>`).join('')}</div>`;
  const chart=picked.length&&visible.labels.length
    ?broadBarChart(visible.labels,visible.series,{unit:'亿份',boxWidth:chartViewWidth('flow-view'),emptyText:'当前周期没有可绘制的交易日',ariaLabel:'重点宽基累计份额每日堆叠柱状图',showLegend:false})
    :`<div class="empty">${allSeries.length?'已取消全部宽基，选中至少一项后可查看':'当前周期没有可绘制的交易日'}</div>`;
  const dailyValues=dailySeries.flatMap(item=>item.values).filter(Number.isFinite),dailyMax=Math.max(0,...dailyValues.map(v=>Math.abs(v)));
  const dailyChart=picked.length&&daily.labels.length
    ?broadBarChart(daily.labels,daily.series,{unit:'亿份',boxWidth:chartViewWidth('flow-view'),emptyText:'当前周期没有可绘制的每日份额数据',ariaLabel:'重点宽基每日增减堆叠柱状图（红=净申购，绿=净赎回）',showLegend:false,tickDigits:dailyMax>=10?0:(dailyMax>=1?1:2)})
    :`<div class="empty">${allSeries.length?'已取消全部宽基，选中至少一项后可查看':'当前周期没有可绘制的交易日'}</div>`;
  const pickedNames=picked.map(item=>item.name).join('、');
  return {visible,daily,html:`<section class="panel broad-share-panel">
    <div class="panel-title flow-history-head"><div class="flow-history-title"><h2>重点宽基累计份额</h2><small>${allSeries.length?`已选 ${picked.length}/${allSeries.length} 个宽基`:'暂无宽基'}</small></div><div class="chart-tools"><div class="chips chart-pan" aria-label="重点宽基份额柱状图左右移动"><button data-broad-pan="left" data-step="${panStep}" data-max="${visible.maxPan}" ${!visible.canLeft?'disabled':''}>← 左移</button><button data-broad-pan="right" data-step="${panStep}" data-max="${visible.maxPan}" ${!visible.canRight?'disabled':''}>右移 →</button></div><div class="chips chart-zoom" aria-label="重点宽基份额柱状图缩放"><button data-broad-zoom="out" ${state.broadZoom<=1?'disabled':''}>− 缩小</button><button data-broad-zoom="reset">${zoomLabel(state.broadZoom)}</button><button data-broad-zoom="in" ${visible.visible<=12?'disabled':''}>＋ 放大</button></div></div></div>
    ${picker}
    <div data-broad-chart="cumulative">${chart}</div>
    <div class="chart-data-note">累计份额 = 该指数全部跟踪ETF（含指数增强、指增产品）的交易所披露份额合计，每个交易日一个数值（自周期起点逐日累加披露变动）；同一交易日一根柱，自上而下按 ${pickedNames||'所选宽基'} 堆叠（图例同序），柱高为当日有披露的所选指数合计；取消勾选后其余宽基重新堆叠且不再计入柱高；归类以披露的跟踪指数代码为准，无代码时按名称匹配并排除境外、双创、国证等其他指数名；无起点披露的ETF不计入；不随上方筛选变化。</div>
    <div class="broad-daily-block" data-broad-chart="daily">
      <div class="broad-chart-sub"><span>重点宽基每日增减</span><div class="trend-legend" style="margin:0"><span><i style="background:#f05f66"></i>净申购</span><span><i style="background:#33c58e"></i>净赎回</span></div></div>
      ${dailyChart}
      <div class="chart-data-note">每日增减 = 该指数全部跟踪ETF当日披露的份额变动合计（亿份），红柱为净申购、绿柱为净赎回；与上方累计份额同源（逐日差分），某ETF当日无披露时其变动不计入当日、跨日差分归入再次披露当日。</div>
    </div>
  </section>`};
}
function toast(text){const el=$('#toast');el.textContent=text;el.classList.add('show');setTimeout(()=>el.classList.remove('show'),2200)}

function periodButtons(activeKey,attr){
  return PERIODS.filter(k=>k==='custom'||state.flows.periods[k]).map(k=>k==='custom'?customPeriodControl(activeKey):`<button class="${activeKey===k?'active':''}" ${attr}="${k}">${state.flows.periods[k]?.label||k}</button>`).join('');
}
function customDateAddMonths(dateStr,months){const d=new Date(dateStr+'T00:00:00');d.setMonth(d.getMonth()+months);return d.toISOString().slice(0,10)}
const pad2=n=>String(n).padStart(2,'0');
function monthDays(y,m){return new Date(y,m,0).getDate()}
function clampDateStr(v,min,max){if(!v)return v;if(min&&v<min)return min;if(max&&v>max)return max;return v}
function dateSelects(which,value,min,max,dis){
  const v=clampDateStr(value||max,min,max)||max;
  const y=Number(v.slice(0,4)),minY=Number((min||max).slice(0,4)),maxY=Number(max.slice(0,4));
  const years=[];for(let i=minY;i<=maxY;i++)years.push(i);
  const months=[];for(let i=1;i<=12;i++)months.push(pad2(i));
  const days=[];for(let i=1;i<=monthDays(y,Number(v.slice(5,7)));i++)days.push(pad2(i));
  const opt=(list,sel)=>list.map(x=>`<option value="${x}"${x===sel?' selected':''}>${x}</option>`).join('');
  return `<span class="pc-date" data-date-group="${which}">`
    +`<select data-date-y="${which}" aria-label="年"${dis}>${opt(years.map(String),String(y))}</select>`
    +`<select data-date-m="${which}" aria-label="月"${dis}>${opt(months,v.slice(5,7))}</select>`
    +`<select data-date-d="${which}" aria-label="日"${dis}>${opt(days,v.slice(8,10))}</select>`
    +`</span>`;
}
function customPeriodControl(activeKey){
  const custom=state.flows.periods.custom||{},rawMin=state.history?.earliest_date||'',max=state.flows.latest_date||'';
  const min=rawMin&&rawMin<HISTORY_START?HISTORY_START:rawMin;
  const isActive=activeKey==='custom'&&!!custom.base_date;
  const rangeText=isActive?`${custom.start_date||custom.base_date} → ${custom.end_date||max}`:'选择区间';
  const dis=state.customLoading?' disabled':'';
  const dStart=state.customOpen&&state.customDraft.start?state.customDraft.start:(custom.base_date||'');
  const dEnd=state.customOpen&&state.customDraft.end?state.customDraft.end:(custom.end_date||max);
  const icon='<svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="3" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M3 10h18M8 3v4M16 3v4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
  const chev='<svg class="pc-chev" viewBox="0 0 24 24" width="10" height="10" aria-hidden="true"><path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const presets=[['all','全部数据']];
  return `<span class="period-custom${isActive?' active':''}${state.customOpen?' open':''}" data-custom-button>`
    + `<button type="button" class="pc-trigger" data-custom-trigger${dis}>${icon}<em>自选</em><b class="pc-range">${rangeText}</b>${chev}</button>`
    + `<div class="pc-pop" data-custom-pop${state.customOpen?'':' hidden'}>`
    + `<div class="pc-pop-head">自选区间<small>起始 → 截止</small></div>`
    + `<label class="pc-field"><span>起始</span>${dateSelects('start',dStart,min,max,dis)}</label>`
    + `<label class="pc-field"><span>截止</span>${dateSelects('end',dEnd,min,max,dis)}</label>`
    + `<div class="pc-presets">${presets.map(([k,l])=>`<button type="button" data-custom-preset="${k}">${l}</button>`).join('')}</div>`
    + `<div class="pc-actions"><button type="button" class="pc-cancel" data-custom-cancel>取消</button><button type="button" class="pc-apply" data-custom-apply>应用</button></div>`
    + `</div></span>`;
}
let customDocBound=false;
function closeCustomPops(){state.customOpen=false;$$('[data-custom-pop]').forEach(p=>{p.hidden=true;p.closest('.period-custom')?.classList.remove('open')})}
function bindCustomPeriod(periodKey){
  if(!customDocBound){
    document.addEventListener('click',closeCustomPops);
    document.addEventListener('keydown',e=>{if(e.key==='Escape')closeCustomPops()});
    customDocBound=true;
  }
  $$(`#${state.view}-view [data-custom-button]`).forEach(el=>{
    const trigger=el.querySelector('[data-custom-trigger]'),pop=el.querySelector('[data-custom-pop]');
    const startGroup=el.querySelector('[data-date-group="start"]'),endGroup=el.querySelector('[data-date-group="end"]');
    if(!trigger||!pop||!startGroup||!endGroup)return;
    const rawMin=state.history?.earliest_date||'',min=rawMin&&rawMin<HISTORY_START?HISTORY_START:rawMin,max=state.flows.latest_date||'';
    const close=()=>{state.customOpen=false;pop.hidden=true;el.classList.remove('open')};
    const read=g=>`${g.querySelector('[data-date-y]').value}-${g.querySelector('[data-date-m]').value}-${g.querySelector('[data-date-d]').value}`;
    const syncDays=g=>{
      const y=+g.querySelector('[data-date-y]').value,m=+g.querySelector('[data-date-m]').value,ds=g.querySelector('[data-date-d]');
      const keep=Math.min(Number(ds.value)||1,monthDays(y,m));
      ds.innerHTML=Array.from({length:monthDays(y,m)},(_,i)=>`<option value="${pad2(i+1)}"${i+1===keep?' selected':''}>${pad2(i+1)}</option>`).join('');
    };
    const setDate=(g,v)=>{
      const fixed=clampDateStr(v,min,max)||max,[y,m,d]=fixed.split('-').map(Number);
      g.querySelector('[data-date-y]').value=String(y);g.querySelector('[data-date-m]').value=pad2(m);
      syncDays(g);g.querySelector('[data-date-d]').value=pad2(Math.min(d,monthDays(y,m)));
    };
    const bindGroup=(g,key)=>{
      g.querySelectorAll('select').forEach(sel=>sel.onchange=()=>{syncDays(g);setDate(g,read(g));state.customDraft[key]=read(g)});
    };
    bindGroup(startGroup,'start');bindGroup(endGroup,'end');
    trigger.onclick=e=>{
      e.stopPropagation();
      if(state.customLoading)return;
      if(state.customOpen){closeCustomPops();return}
      const c=state.flows.periods.custom||{};
      state.customDraft={start:c.start_date||c.base_date||customDateAddMonths(max,-3),end:c.end_date||max};
      setDate(startGroup,state.customDraft.start);setDate(endGroup,state.customDraft.end);
      state.customOpen=true;
      closeCustomPops();state.customOpen=true;pop.hidden=false;el.classList.add('open');
    };
    pop.onclick=e=>e.stopPropagation();
    pop.querySelector('[data-custom-apply]')?.addEventListener('click',()=>{close();applyCustomRange(read(startGroup),read(endGroup),periodKey)});
    pop.querySelector('[data-custom-cancel]')?.addEventListener('click',close);
    pop.querySelectorAll('[data-custom-preset]').forEach(btn=>btn.addEventListener('click',()=>{
      const k=btn.dataset.customPreset;const end=max;let start=min;
      if(k==='all')start=min;
      if(min&&start<min)start=min;
      setDate(startGroup,start);setDate(endGroup,end);
      state.customDraft={start:read(startGroup),end:read(endGroup)};
      pop.querySelectorAll('[data-custom-preset]').forEach(b=>b.classList.toggle('active',b===btn));
    }));
  });
}
async function applyCustomRange(start,end,periodKey){
  if(state.customLoading)return;
  if(!start||!end){toast('请同时选择起日和止日');render();return}
  const min=state.history?.earliest_date&&state.history.earliest_date>HISTORY_START?state.history.earliest_date:HISTORY_START,max=state.flows.latest_date||'';
  let startUse=start,endUse=end,clamped=false;
  if(min&&startUse<min){startUse=min;clamped=true}
  if(max&&endUse>max){endUse=max;clamped=true}
  if(startUse>endUse){toast('自选起日不能晚于止日');render();return}
  if(clamped)toast(`区间已按可用数据范围调整：${startUse} → ${endUse}`);
  state.customLoading=true;render();
  try{
    const base=await fetchJson(`/api/shares-range?start=${encodeURIComponent(startUse)}&end=${encodeURIComponent(endUse)}`);
    state.customBase=base;
    state.customRequestedStart=startUse;
    reapplyCustomPeriod();
    state[periodKey]='custom';
    state.flowZoom=1;state.flowPan=0;state.starZoom=1;state.starPan=0;state.broadZoom=1;state.broadPan=0;
    const note=(base.start.requested===base.start.date?'':`；起日按 ${base.start.date}`)+(base.end.requested===base.end.date?'':`；止日按 ${base.end.date}`);
    toast(`自选区间：${base.start.date} → ${base.end.date}${note}`);
  }catch(err){toast(`自选区间读取失败：${err.message}`)}
  finally{state.customLoading=false;render()}
}
function cards(items){return `<div class="cards">${items.map(x=>`<article class="card"><span>${x.label}</span><strong class="${x.cls||''}">${x.value}</strong><small>${x.note||''}</small></article>`).join('')}</div>`}
function controls(extra=''){return `<div class="controls"><div class="chips"><button class="${!state.focus?'active':''}" data-focus="0">全部ETF</button><button class="${state.focus?'active':''}" data-focus="1">重点宽基</button></div><div class="chips"><button class="${state.exchange==='all'?'active':''}" data-exchange="all">全部市场</button><button class="${state.exchange==='SH'?'active':''}" data-exchange="SH">上交所</button><button class="${state.exchange==='SZ'?'active':''}" data-exchange="SZ">深交所</button></div>${extra}</div>`}

function shareTrendChart(labels,series,{unit='%',digits=4,percent=true,height=200,clampMin=true,emptyText='暂无可绘制的每日占比数据',ariaLabel='四个重点宽基的科创板权重占比每日趋势图'}={}){
  const width=chartWidth,pad={l:62,r:24,t:20,b:38};
  const values=series.flatMap(s=>s.values.filter(Number.isFinite));
  if(!values.length)return `<div class="empty">${emptyText}</div>`;
  let min=Math.min(...values),max=Math.max(...values);
  if(min===max){const step=percent?.5:Math.max(1,Math.abs(min)*.02);min=clampMin?Math.max(0,min-step):min-step;max=percent?Math.min(100,max+step):max+step}
  else{const padding=Math.max((max-min)*.12,percent?.08:Math.max(1,Math.abs(max)*.002));min=clampMin?Math.max(0,min-padding):min-padding;max=percent?Math.min(100,max+padding):max+padding}
  if(percent&&max-min<.2){const center=(min+max)/2;min=Math.max(0,center-.1);max=Math.min(100,center+.1)}
  const x=i=>labels.length===1?(pad.l+width-pad.r)/2:pad.l+i*(width-pad.l-pad.r)/(labels.length-1);
  const y=v=>pad.t+(max-v)*(height-pad.t-pad.b)/(max-min);
  const ticks=Array.from({length:5},(_,i)=>max-i*(max-min)/4),tickEvery=Math.max(1,Math.ceil(labels.length/8));
  const zeroLine=min<0&&max>0?`<line x1="${pad.l}" x2="${width-pad.r}" y1="${y(0)}" y2="${y(0)}" class="zero-line"/>`:'';
  const paths=series.map(s=>{
    const points=s.values.map((v,i)=>Number.isFinite(v)?`${x(i)},${y(v)}`:null).filter(Boolean);
    const dot=labels.length===1&&Number.isFinite(s.values[0])?`<circle cx="${x(0)}" cy="${y(s.values[0])}" r="3.5" fill="${s.color}"/>`:'';
    return `<polyline points="${points.join(' ')}" fill="none" stroke="${s.color}" stroke-width="2.5"/>${dot}`;
  }).join('');
  const hoverTargets=labels.map((_,i)=>{
    const left=i===0?pad.l:(x(i-1)+x(i))/2;
    const right=i===labels.length-1?width-pad.r:(x(i)+x(i+1))/2;
    return `<rect class="trend-hover-target" data-star-point="${i}" data-star-x="${x(i)}" x="${left}" y="${pad.t}" width="${Math.max(1,right-left)}" height="${height-pad.t-pad.b}"/>`;
  }).join('');
  const legend=series.map(s=>`<span><i style="background:${s.color}"></i>${s.name}</span>`).join('');
  return `<div class="trend-wrap"><div class="trend-legend">${legend}</div><svg class="trend-chart multi-trend-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${ariaLabel}">${ticks.map(v=>`<line x1="${pad.l}" x2="${width-pad.r}" y1="${y(v)}" y2="${y(v)}" class="grid-line"/><text x="${pad.l-10}" y="${y(v)+4}" text-anchor="end">${num(v,percent?2:0)}${unit}</text>`).join('')}${zeroLine}${paths}<line class="trend-hover-line" x1="0" x2="0" y1="${pad.t}" y2="${height-pad.b}" visibility="hidden"/>${hoverTargets}${labels.map((label,i)=>(i%tickEvery===0||i===labels.length-1)?`<text x="${x(i)}" y="${height-10}" text-anchor="middle">${axisLabel(label)}</text>`:'').join('')}</svg><div class="trend-tooltip" role="status" hidden></div></div>`;
}

function bindStarTrendTooltip(labels,series,{scope='#star-view',digits=4,unit='%',total=false}={}){
  const svg=$(`${scope} .multi-trend-chart`),tooltip=$(`${scope} .trend-tooltip`);
  if(!svg||!tooltip)return;
  const guide=$('.trend-hover-line',svg);
  const hide=()=>{tooltip.hidden=true;if(guide)guide.setAttribute('visibility','hidden')};
  const position=(clientX,clientY)=>{
    const gap=14,box=tooltip.getBoundingClientRect();
    let left=clientX+gap,top=clientY+gap;
    if(left+box.width>window.innerWidth-8)left=clientX-box.width-gap;
    if(top+box.height>window.innerHeight-8)top=clientY-box.height-gap;
    tooltip.style.left=`${Math.max(8,left)}px`;tooltip.style.top=`${Math.max(8,top)}px`;
  };
  const show=(target,event)=>{
    const index=Number(target.dataset.starPoint);
    const sum=total?series.reduce((acc,item)=>{const v=item.values[index];return acc+(Number.isFinite(v)?v:0)},0):0;
    tooltip.innerHTML=`<b>${labels[index]}</b>${series.map(item=>{
      const value=item.values[index];
      return `<span><i style="background:${item.color}"></i>${item.name}<strong>${Number.isFinite(value)?num(value,digits)+unit:'—'}</strong></span>`;
    }).join('')}${total?`<span class="tooltip-total"><i></i>合计<strong>${num(sum,digits)+unit}</strong></span>`:''}`;
    tooltip.hidden=false;
    if(guide){guide.setAttribute('x1',target.dataset.starX);guide.setAttribute('x2',target.dataset.starX);guide.setAttribute('visibility','visible')}
    position(event.clientX,event.clientY);
  };
  $$('.trend-hover-target',svg).forEach(target=>{
    target.onpointerenter=event=>show(target,event);
    target.onpointermove=event=>show(target,event);
    target.onclick=event=>show(target,event);
  });
  svg.onpointerleave=hide;
}


function groupedBarChart(labels,series,unit='亿元',showLatest=false,showSeriesSummary=true,height=212){
  const width=chartWidth,pad={l:62,r:24,t:12,b:28};
  const values=series.flatMap(s=>s.values.filter(Number.isFinite));
  if(!values.length)return '<div class="empty">暂无可绘制的实时数据</div>';
  let min=Math.min(0,...values),max=Math.max(0,...values);if(min===max){min-=1;max+=1}
  const span=max-min,padded=span*.08;min-=padded;max+=padded;
  const plotW=width-pad.l-pad.r,groupW=plotW/labels.length,barW=Math.min(24,groupW/(series.length+1));
  const y=v=>pad.t+(max-v)*(height-pad.t-pad.b)/(max-min),zero=y(0);
  const ticks=Array.from({length:5},(_,i)=>max-i*(max-min)/4);
  const bars=labels.map((label,i)=>series.map((s,j)=>{
    const v=s.values[i];if(!Number.isFinite(v))return '';
    const cx=pad.l+i*groupW+groupW/2+(j-(series.length-1)/2)*(barW+3),top=Math.min(y(v),zero),h=Math.max(1,Math.abs(y(v)-zero));
    const color=v>=0?(s.positiveColor||s.color):(s.negativeColor||s.color);
    return `<rect x="${cx-barW/2}" y="${top}" width="${Math.max(.8,barW)}" height="${h}" rx="1" fill="${color}"><title>${label} · ${s.name}：${signed(v,2,unit)}</title></rect>`;
  }).join('')).join('');
  const tickEvery=Math.max(1,Math.ceil(labels.length/8));
  const directionLegend=series.some(s=>s.positiveColor||s.negativeColor);
  const latestValue=s=>{for(let i=s.values.length-1;i>=0;i--)if(Number.isFinite(s.values[i]))return s.values[i]};
  const seriesSummary=showLatest?series.map(s=>`${s.name} ${signed(latestValue(s),2,unit)}`).join(' / '):series.map(s=>s.name).join(' / ');
  const legend=directionLegend?`<span><i style="background:#f05f66"></i>净申购</span><span><i style="background:#33c58e"></i>净赎回</span>${showSeriesSummary&&series.length>1?`<span class="series-order">${showLatest?'最新日':'同日柱序'}：${seriesSummary}</span>`:''}`:series.map(s=>`<span><i style="background:${s.color}"></i>${s.name}</span>`).join('');
  return `<div class="trend-wrap"><div class="trend-legend">${legend}</div><svg class="trend-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${unit}口径的所选周期每日柱状图">${ticks.map(v=>`<line x1="${pad.l}" x2="${width-pad.r}" y1="${y(v)}" y2="${y(v)}" class="grid-line"/><text x="${pad.l-10}" y="${y(v)+4}" text-anchor="end">${num(v,1)}</text>`).join('')}<line x1="${pad.l}" x2="${width-pad.r}" y1="${zero}" y2="${zero}" class="zero-line"/>${bars}${labels.map((label,i)=>{const last=i===labels.length-1;if(!(i%tickEvery===0||last))return '';const lx=last?width-pad.r:(i===0?pad.l:pad.l+i*groupW+groupW/2);return `<text x="${lx}" y="${height-22}" text-anchor="${last?'end':(i===0?'start':'middle')}">${axisLabel(label)}</text>`}).join('')}<text x="${pad.l}" y="11" text-anchor="middle" class="unit-label">${unit}</text></svg></div>`;
}

function flowHistoryChart(){
  const rows=historyFlowSeries(),label=state.flows.periods[state.period].label,dates=rows.map(x=>x.date),metric=FLOW_METRICS[state.flowMetric]||FLOW_METRICS.amount;
  const directionColors=state.flowMetric!=='scale'?{positiveColor:'#f05f66',negativeColor:'#33c58e'}:{};
  const fullSeries=[{name:metric.dailyName,color:'#4fd7e5',...directionColors,values:rows.map(x=>x[metric.dailyKey])}];
  const visible=zoomedChartData(dates,fullSeries,state.flowZoom,state.flowPan),panStep=Math.max(1,Math.floor(visible.visible/2));
  const chart=groupedBarChart(visible.labels,visible.series,metric.unit,false,true,132);
  const coverage=state.history?.coverage||{};
  return `<div class="panel trend-panel"><div class="panel-title flow-history-head"><div class="flow-history-title"><h2>${label}${metric.dailyTitle}</h2></div><div class="chart-tools"><div class="chips chart-pan" aria-label="每日柱状图左右移动"><button data-flow-pan="left" data-step="${panStep}" data-max="${visible.maxPan}" ${!visible.canLeft?'disabled':''}>← 左移</button><button data-flow-pan="right" data-step="${panStep}" data-max="${visible.maxPan}" ${!visible.canRight?'disabled':''}>右移 →</button></div><div class="chips chart-zoom" aria-label="每日柱状图缩放"><button data-flow-zoom="out" ${state.flowZoom<=1?'disabled':''}>− 缩小</button><button data-flow-zoom="reset">${zoomLabel(state.flowZoom)}</button><button data-flow-zoom="in" ${visible.visible<=12?'disabled':''}>＋ 放大</button></div></div></div>${chart}<div class="chart-data-note">上交所官方历史 ${coverage.sse_dates||0} 日；深交所官方历史 ${coverage.sz_dates||0} 日。缺失日期不补零、不插值。</div></div>`;
}

function renderFlow(){
  chartWidth=chartViewWidth('flow-view');
  const rows=flowRows();
  const valid=rows.filter(x=>x.p),known=rows.filter(x=>x.estimate!=null), net=known.reduce((s,x)=>s+x.estimate,0), grossIn=known.filter(x=>x.estimate>0).reduce((s,x)=>s+x.estimate,0), grossOut=known.filter(x=>x.estimate<0).reduce((s,x)=>s+x.estimate,0);
  const inc=valid.filter(x=>x.p.delta_shares>0).length,dec=valid.filter(x=>x.p.delta_shares<0).length;
  const period=state.flows.periods[state.period],isCustom=state.period==='custom',bounded=!!period.end_date;
  const sorted=[...rows].sort((a,b)=>Math.abs(b.estimate??b.p?.delta_shares??-1)-Math.abs(a.estimate??a.p?.delta_shares??-1));
  const coverageCard={label:'有效历史基期',value:nfmt.format(valid.length)+' / '+nfmt.format(rows.length)+' 只',note:valid.length<rows.length?(isCustom?'部分ETF在起日或止日无披露':'深市部分周期积累中'):'沪深数据均有基期'};
  const latestShares=valid.reduce((sum,x)=>sum+Number((bounded&&x.p.end_shares)||x.latest_shares||0),0),baseShares=valid.reduce((sum,x)=>sum+Number(x.p.base_shares||0),0),shareChange=latestShares-baseShares;
  const latestScale=known.reduce((sum,x)=>sum+Number((bounded&&x.p.end_shares)||x.latest_shares||0)*x.price,0),baseScale=known.reduce((sum,x)=>sum+Number(x.p.base_shares||0)*x.price,0),scaleChange=latestScale-baseScale;
  const metricCards=state.flowMetric==='scale'?[coverageCard,
    {label:isCustom||bounded?'止日估算规模':'当前估算规模',value:num(latestScale/1e8,2)+' 亿元',note:`${known.length}只可取得盘中价格`},
    {label:'区间起点估算规模',value:num(baseScale/1e8,2)+' 亿元',note:'按当前盘中价回算'},
    {label:'区间规模变动',value:signed(scaleChange/1e8,2,' 亿元'),cls:cls(scaleChange),note:isCustom||bounded?'止日规模较区间起点':'当前规模较区间起点'}
  ]:state.flowMetric==='shares'?[coverageCard,
    {label:isCustom||bounded?'止日ETF总份额':'当前ETF总份额',value:num(latestShares/1e8,2)+' 亿份',note:`${valid.length}只ETF`},
    {label:'区间起点总份额',value:num(baseShares/1e8,2)+' 亿份',note:'交易所日频披露'},
    {label:'区间份额变动',value:signed(shareChange/1e8,2,' 亿份'),cls:cls(shareChange),note:isCustom||bounded?'止日份额较区间起点':'当前份额较区间起点'}
  ]:[coverageCard,
    {label:'估算净申购/赎回',value:signed(net/1e8,2,' 亿元'),cls:cls(net),note:'可取得盘中价格的ETF'},
    {label:'估算申购金额',value:num(grossIn/1e8,2)+' 亿元',cls:'up',note:`${inc}只份额增加`},
    {label:'估算赎回金额',value:num(Math.abs(grossOut)/1e8,2)+' 亿元',cls:'down',note:`${dec}只份额减少`}
  ];
  const broad=broadSharePanel();
  $('#flow-view').innerHTML=`
    <div class="period-row"><div class="periods">${periodButtons(state.period,'data-period')}</div><div class="asof">统计区间：${period.start_date||period.base_date}${period.start_date&&period.base_date!==period.start_date?`（基准 ${period.base_date}）`:''} → ${periodRange(state.period).end}；估算金额按当前盘中价计算</div></div>
    ${controls()}
    <div class="flow-top-layout">
      ${flowHistoryChart()}
      <aside class="flow-side">
        <div class="chips chart-metric">${Object.entries(FLOW_METRICS).map(([key,metric])=>`<button class="${state.flowMetric===key?'active':''}" type="button" data-flow-metric="${key}" aria-pressed="${state.flowMetric===key}">${metric.label}</button>`).join('')}</div>
        ${cards(metricCards)}
      </aside>
    </div>
    <div class="flow-bottom-layout">
      ${broad.html}
      ${broadChangePanel()}
    </div>
    <div class="panel table-panel"><div class="panel-title"><h2>ETF份额变化明细</h2><span>${sorted.length}条</span></div><div class="table-scroll"><table><thead><tr><th>ETF</th><th>${isCustom||bounded?'止日份额':'最新份额'}</th><th>份额变化</th><th>变化率</th><th>盘中价</th><th>估算金额</th><th>起点日期</th></tr></thead><tbody>${sorted.map(x=>`<tr><td><b>${x.liveName}</b><small>${x.exchange} · ${x.code}${x.focus||focusName(x.liveName)?' · 重点':''}</small></td><td>${(isCustom||bounded)&&!x.p?'—':num((x.p&&x.p.end_shares||x.latest_shares)/1e8,2)+'亿份'}</td><td class="${cls(x.p?.delta_shares)}">${x.p?signed(x.p.delta_shares/1e8,2,'亿份'):'区间起点无披露'}</td><td class="${cls(x.p?.delta_pct)}">${x.p?signed((x.p.delta_pct||0)*100,2,'%'):'—'}</td><td>${num(x.price,3)}</td><td class="${cls(x.estimate)}">${x.estimate==null?'—':signed(x.estimate/1e8,2,'亿元')}</td><td>${x.p?.base_date||'—'}</td></tr>`).join('')}</tbody></table></div></div>`;
  bindFlow();
  if(broad.visible.labels.length)bindStarTrendTooltip(broad.visible.labels,broad.visible.series,{scope:'#flow-view [data-broad-chart="cumulative"]',digits:2,unit:'亿份',total:true});
  if(broad.daily.labels.length)bindStarTrendTooltip(broad.daily.labels,broad.daily.series,{scope:'#flow-view [data-broad-chart="daily"]',digits:2,unit:'亿份',total:true});
  // 窄屏下两图各自横向滚动，滚动位置同步，日期列才不会错位
  const wraps=$$('#flow-view .broad-share-panel .trend-wrap');if(wraps.length===2)wraps.forEach(w=>{const other=wraps.find(x=>x!==w);w.onscroll=()=>{if(other.scrollLeft!==w.scrollLeft)other.scrollLeft=w.scrollLeft}});
}

function rotationBars(rows,tone,max){
  if(!rows.length)return '<div class="rotation-empty">当前周期暂无该方向资金</div>';
  return rows.map((x,index)=>{
    const value=x.amount,ratio=Math.max(3,value/max*100),signedValue=tone==='in'?signed(value/1e8,2):`-${num(value/1e8,2)}`;
    return `<div class="rotation-bar-row"><span class="rotation-rank">${index+1}</span><div class="rotation-bar-copy"><b>${x.name}</b><small>${x.etfs}只ETF</small></div><div class="rotation-track"><i class="rotation-fill rotation-fill-${tone}" style="width:${ratio}%"></i></div><strong class="${tone==='in'?'up':'down'}">${signedValue}</strong></div>`;
  }).join('');
}

function renderRotation(){
  const data=buildRotationData(),period=state.flows.periods[state.rotationPeriod];
  const largest=data.largest,largestIn=largest&&largest.net>=0,largestAmount=largest?Math.abs(largest.net):0;
  const max=Math.max(1,...data.incoming.map(x=>x.amount),...data.outgoing.map(x=>x.amount));
  const latestTime=quoteTime(state.quoteSummary.as_of).slice(5);
  $('#rotation-view').innerHTML=`
    <div class="panel rotation-panel">
      <div class="rotation-header">
        <div class="rotation-kpis">
          <div><span>流出合计</span><strong class="down">${num(data.grossOut/1e8,2)}</strong><small>${data.outgoingCount}个方向</small></div>
          <div><span>流入合计</span><strong class="up">${signed(data.grossIn/1e8,2)}</strong><small>${data.incomingCount}个方向</small></div>
          <div><span>净流入</span><strong class="${cls(data.net)}">${signed(data.net/1e8,2)}</strong><small>${data.known.length}只ETF可估算</small></div>
          <div><span>最大方向</span><strong class="${largestIn?'up':'down'}">${largest?.name||'—'}</strong><small>${largest?`${largestIn?'流入':'流出'} ${num(largestAmount/1e8,2)}亿元`:'暂无数据'}</small></div>
        </div>
      </div>
      <div class="rotation-period-row">
        <div class="periods">${periodButtons(state.rotationPeriod,'data-rotation-period')}</div>
        <div class="asof">统计区间：${period.base_date} → ${periodRange(state.rotationPeriod).end} · 盘中价 ${latestTime} 动态重算</div>
      </div>
      <div class="rotation-chart" role="img" aria-label="ETF主题资金流出和流入方向排名，单位亿元">
        <section class="rotation-direction rotation-direction-out"><div class="rotation-direction-title"><span>资金流出方向</span><small>由大到小</small></div>${rotationBars(data.outgoing,'out',max)}</section>
        <section class="rotation-direction rotation-direction-in"><div class="rotation-direction-title"><span>资金流入方向</span><small>由大到小</small></div>${rotationBars(data.incoming,'in',max)}</section>
      </div>
      <div class="rotation-notes">
        <div><b>1</b><span>先按方向汇总ETF估算金额；流入、流出为各方向净额的正负合计。</span></div>
        <div><b>2</b><span>同一ETF仅归入一个方向，优先识别资产类别，再识别行业与主题。</span></div>
        <div><b>3</b><span>分类依据ETF名称与跟踪指数名称；无法明确识别的ETF归入“其他”。</span></div>
      </div>
    </div>`;
  $$('[data-rotation-period]').forEach(button=>button.onclick=()=>{state.rotationPeriod=button.dataset.rotationPeriod;renderRotation()});
  bindCustomPeriod('rotationPeriod');
}

function quoteSortHeader(label,key){
  const active=state.quoteSort.key===key,direction=active?state.quoteSort.dir:'none',symbol=active?(direction==='asc'?'↑':'↓'):'↕';
  return `<th class="sortable" aria-sort="${direction==='asc'?'ascending':direction==='desc'?'descending':'none'}"><button type="button" data-quote-sort="${key}" aria-label="按${label}${direction==='asc'?'降序':'升序'}排列">${label}<span aria-hidden="true">${symbol}</span></button></th>`;
}
function renderQuote(){
  const rows=quoteRows(),s=quoteSummaryForRows(rows);
  $('#quote-view').innerHTML=`${cards([
    {label:'行情覆盖',value:`${s.quote_count||0}/${s.universe_count||0}`,note:`覆盖率 ${num(s.coverage,1)}%`},
    {label:'盘中成交额',value:num(s.amount_100m,2)+' 亿元',note:quoteTime(s.as_of)},
    {label:'上涨ETF',value:nfmt.format(s.up||0)+' 只',cls:'up',note:'盘中涨幅>0'},
    {label:'下跌ETF',value:nfmt.format(s.down||0)+' 只',cls:'down',note:'盘中涨幅<0'}
  ])}${controls('')}<div class="panel table-panel"><div class="table-scroll"><table><thead><tr><th>ETF</th>${quoteSortHeader('最新价','price')}${quoteSortHeader('涨跌幅','pct')}${quoteSortHeader('成交额','amount_100m')}${quoteSortHeader('成交量','volume_100m_shares')}${quoteSortHeader('规模','scale_100m')}${quoteSortHeader('最高/最低','high_low')}${quoteSortHeader('行情时间','quote_time')}</tr></thead><tbody>${rows.map(x=>`<tr><td><b>${x.name}</b><small>${x.exchange} · ${x.code}${focusName(x.name)?' · <span class="quote-focus-tag">重点</span>':''}</small></td><td>${num(x.price,3)}</td><td class="${cls(x.pct)}">${signed(x.pct,2,'%')}</td><td>${num(x.amount_100m,2)}亿元</td><td>${num(x.volume_100m_shares,2)}亿份</td><td>${num(x.scale_100m,2)}亿元</td><td>${num(x.high,3)} / ${num(x.low,3)}</td><td>${quoteTime(x.quote_time).slice(5)}</td></tr>`).join('')}</tbody></table></div></div>`;
  bindCommon();
  $$('[data-quote-sort]').forEach(button=>button.onclick=()=>{const key=button.dataset.quoteSort;state.quoteSort=state.quoteSort.key===key?{key,dir:state.quoteSort.dir==='asc'?'desc':'asc'}:{key,dir:'asc'};renderQuote()});
}

function renderBoard(cfg){
  chartWidth=chartViewWidth(cfg.viewId);
  const data=buildBoardShareData(cfg),scored=data.rows.filter(row=>Number.isFinite(row.share)),highest=[...scored].sort((a,b)=>b.share-a.share)[0];
  const average=scored.length?scored.reduce((sum,x)=>sum+x.share,0)/scored.length:null;
  const period=state.flows.periods[state[cfg.key+'Period']],colors=['#4fd7e5','#f3b65c','#f05f66','#33c58e'];
  const histories=data.rows.map(row=>({row,ready:boardHistoryReady(cfg,row),points:boardHistorySeries(cfg,row)}));
  const ready=histories.every(item=>item.ready),pending=histories.find(item=>!item.ready);
  const dates=[...new Set(histories.flatMap(item=>item.points.map(point=>point.date)))].sort();
  const valueMaps=new Map(histories.map(item=>[item.row.code,new Map(item.points.map(point=>[point.date,point.share]))]));
  const fullSeries=data.rows.map((row,index)=>({name:row.name,color:colors[index],values:dates.map(date=>valueMaps.get(row.code).get(date)??null)}));
  const visible=zoomedChartData(dates,fullSeries,state[cfg.key+'Zoom'],state[cfg.key+'Pan']),panStep=Math.max(1,Math.floor(visible.visible/2));
  const dailyRows=dates.map(date=>({date,values:new Map(data.rows.map(row=>[row.code,valueMaps.get(row.code).get(date)]))}));
  const chart=ready
    ?shareTrendChart(visible.labels,visible.series)
    :`<div class="empty">${state[cfg.key+'PriceError']?'每日占比加载失败：'+state[cfg.key+'PriceError']:`正在加载${pending?.row.name||'重点宽基'}的${cfg.board}成分股及指数历史收盘价…`}</div>`;
  const summaryCards=cards([
    {label:'重点宽基指数',value:data.rows.length+' 个',note:cfg.indexes.map(item=>item.name).join('、')},
     {label:'最高权重占比',value:highest?num(highest.share*100,2)+'%':'—',note:highest?`${highest.name} · ${highest.boardCount}只${cfg.board}股票`:'暂无数据'},
     {label:'平均权重占比',value:average==null?'—':num(average*100,2)+'%',note:`按指数简单平均，不按ETF规模加权${scored.length<data.rows.length?'（不含权重未公开的指数）':''}`},
    {label:'覆盖'+cfg.board+'股票',value:nfmt.format(data.uniqueBoardCount)+' 只',note:'重点宽基成分去重'}
  ]);
  document.getElementById(cfg.viewId).innerHTML=`
    <div class="period-row"><div class="periods">${periodButtons(state[cfg.key+'Period'],'data-board-period')}</div><div class="asof">每日回溯区间：${period.base_date} → ${periodRange(state[cfg.key+'Period']).end}</div></div>
    <div class="star-trend-layout">
      <div class="panel trend-panel star-history-panel">
        <div class="panel-title flow-history-head"><div class="flow-history-title"><h2>重点宽基${cfg.board}权重占比 · 每日</h2><small>四指数同图 · 显示 ${visible.visible}/${dates.length} 个交易日 · 历史行情本地缓存，仅补新增交易日</small></div><div class="chart-tools"><div class="chips chart-pan" aria-label="${cfg.board}占比趋势图左右移动"><button data-board-pan="left" data-step="${panStep}" data-max="${visible.maxPan}" ${!visible.canLeft?'disabled':''}>← 左移</button><button data-board-pan="right" data-step="${panStep}" data-max="${visible.maxPan}" ${!visible.canRight?'disabled':''}>右移 →</button></div><div class="chips chart-zoom" aria-label="${cfg.board}占比趋势图缩放"><button data-board-zoom="out" ${state[cfg.key+'Zoom']<=1?'disabled':''}>− 缩小</button><button data-board-zoom="reset">${zoomLabel(state[cfg.key+'Zoom'])}</button><button data-board-zoom="in" ${visible.visible<=12?'disabled':''}>＋ 放大</button></div></div></div>
        ${chart}
        <div class="chart-data-note">四种颜色依次对应${cfg.indexes.map(item=>item.name).join('、')}。权重占比 = Σ（${cfg.board}成分股权重）÷ Σ（全部成分股权重）；最新交易日为指数公司披露的实际权重值，历史每日以该权重为锚、按成分股与指数未复权收盘价相对锚定日的变动回溯估算，未还原历史调仓与历史自由流通股本变化。</div>
      </div>
      ${summaryCards}
    </div>
    <div class="panel table-panel star-daily-table"><div class="panel-title"><h2>四大宽基每日数据</h2><span>${dailyRows.length}个交易日</span></div><div class="table-scroll"><table><thead><tr><th>日期</th>${data.rows.map(row=>`<th>${row.name}</th>`).join('')}</tr></thead><tbody>${[...dailyRows].reverse().map(day=>`<tr><td>${day.date}</td>${data.rows.map(row=>{const value=day.values.get(row.code);return `<td><b>${Number.isFinite(value)?num(value,4)+'%':'—'}</b></td>`}).join('')}</tr>`).join('')}</tbody></table></div></div>
    <div class="asof">最新权重日期：${state.weights.generated_at.slice(0,10)}；口径为权重占比（${cfg.board}股票按证券代码 ${cfg.prefixText} 开头识别）</div>
    <div class="panel table-panel star-detail-table"><div class="panel-title"><h2>指数明细</h2><span>${data.rows.length}个重点宽基${data.rows.some(r=>r.partial)?' · 部分指数仅公开前十大权重，占比显示 —':''}</span></div><div class="table-scroll"><table><thead><tr><th>指数</th><th>跟踪ETF</th><th>全部成分股</th><th>${cfg.board}股票</th><th>${cfg.board}权重占比</th><th>${cfg.board}权重前5</th><th>权重来源</th></tr></thead><tbody>${data.rows.map(row=>`<tr><td><b>${row.name}</b><small>${row.code}</small></td><td>${row.etfCount}只</td><td>${row.constituentCount}只</td><td>${row.boardCount}只</td><td>${row.partial?`<b>—</b><small>仅公开前十大（${num(row.weightCoverage||0,2)}%）</small>`:`<b>${num(row.share*100,2)}%</b>`}</td><td>${row.topStocks.length?row.topStocks.map(x=>`${x.name} ${num(x.fraction*100,2)}%`).join('；'):'—'}</td><td>${row.source}</td></tr>`).join('')}</tbody></table></div></div>`;
  $$('#'+cfg.viewId+' [data-board-period]').forEach(button=>button.onclick=()=>{state[cfg.key+'Period']=button.dataset.boardPeriod;state[cfg.key+'Zoom']=1;state[cfg.key+'Pan']=0;state[cfg.key+'PriceError']='';renderBoard(cfg)});
  bindCustomPeriod(cfg.key+'Period');
  $$('#'+cfg.viewId+' [data-board-zoom]').forEach(button=>button.onclick=()=>{changeChartZoom(cfg.key+'Zoom',cfg.key+'Pan',button.dataset.boardZoom);renderBoard(cfg)});
  $$('#'+cfg.viewId+' [data-board-pan]').forEach(button=>button.onclick=()=>{changeChartPan(cfg.key+'Pan',button.dataset.boardPan,Number(button.dataset.step),Number(button.dataset.max));renderBoard(cfg)});
  bindStarTrendTooltip(visible.labels,visible.series,{scope:'#'+cfg.viewId});
  if(pending)void ensureBoardPriceHistory(cfg,pending.row);
}
function renderStar(){renderBoard(BOARD_VIEWS.star)}
function renderChiNext(){renderBoard(BOARD_VIEWS.chinext)}


function renderMethod(){
  const p=state.flows;
  $('#method-view').innerHTML=`<div class="method-grid">
    <article class="panel"><h2>数据更新</h2><dl><dt>盘中行情</dt><dd>交易时段实时刷新，当前快照 ${quoteTime(state.quoteSummary.as_of)}</dd><dt>ETF基金份额</dt><dd>日频，最新完整日期 ${p.latest_date}</dd><dt>历史周期</dt><dd>${PERIODS.map(k=>`${p.periods[k].label}：${p.periods[k].base_date?p.periods[k].base_date+(p.periods[k].end_date?' → '+p.periods[k].end_date:''):'未选择'}`).join('；')}</dd></dl></article>
    <article class="panel"><h2>计算口径</h2><dl><dt>份额变化</dt><dd>预置周期：最新披露基金份额 − 周期起点最近可用交易日基金份额；自选区间：止日（或之前最近披露日）份额 − 起日（或之前最近披露日）份额，所选日期无披露时自动回退；起日早于本地历史起点或止日晚于最新数据时，按可用范围自动收敛（起日早于深交所缓存的极少数情况会退回最早可用快照，否则深市 ETF 会整组缺失）</dd><dt>估算金额</dt><dd>份额变化 × 当前盘中价格</dd><dt>重点宽基累计份额</dt><dd>六个重点宽基按交易所披露的跟踪指数代码归类，仅在没有披露代码时按名称模式匹配并排除境外、双创、国证等其他指数名；累计份额为该指数全部跟踪 ETF（含指数增强、指增产品）的交易所披露份额合计（自周期起点逐日累加披露变动）；图中同一交易日一根柱，自上而下按 沪深300、科创50、创业板指、上证50、中证500、中证1000 堆叠，柱高为当日有披露的各指数合计；无起点披露的 ETF 不计入</dd><dt>重点宽基每日增减</dt><dd>每日增减为该指数全部跟踪 ETF 当日披露的份额变动合计，红柱为净申购、绿柱为净赎回，与累计份额同源（逐日差分）；某 ETF 当日无披露时其变动不计入当日，跨日差分归入再次披露当日</dd><dt>科创板 / 创业板权重占比</dt><dd>权重占比 = 该板块成分股（科创板：证券代码 688/689 开头；创业板：300/301/302 开头）权重之和 ÷ 全部成分股权重之和；科创板跟踪沪深300、上证50、中证500、中证1000，创业板跟踪沪深300、深证成指、中证500、中证1000；最新交易日为指数公司披露的实际权重值，历史每日以该权重为锚、按成分股与指数未复权收盘价相对锚定日的变动回溯估算，未还原历史调仓与历史自由流通股本变化</dd><dt>方向</dt><dd>正数为净申购，负数为净赎回</dd><dt>资金轮动</dt><dd>按ETF名称及跟踪指数名称，将估算金额归入宽基、科技、医药、消费、金融地产、周期资源、新能源制造、红利价值、债券、商品、货币、港股海外等互斥方向；无法明确识别的归入“其他”。</dd><dt>重点宽基</dt><dd>沪深300、上证50、中证500、中证1000、创业板和科创50相关ETF。按ETF名称或预设标签筛选，仅用于聚合展示，不代表国家队持仓认定。</dd></dl></article>
    <article class="panel warning"><h2>重要限制</h2><p>ETF资金流不能识别具体申购账户，因此不能直接确认是否来自中央汇金、证金或其他国家队机构。沪深两市均采用交易所官方日频份额；累计份额只统计能确认跟踪上述六个宽基指数的ETF，债券、商品和境外指数不计入。</p></article>
    <article class="panel"><h2>数据源</h2><p><a href="${p.sources.sse}" target="_blank" rel="noreferrer">上交所ETF基金份额</a></p><p><a href="${p.sources.szse}" target="_blank" rel="noreferrer">深交所ETF基金规模</a></p><p>指数权重：中证指数、国证指数；盘中价格、成交及成分股未复权日线收盘价：腾讯证券行情接口</p><p class="muted">网页显示的是公开数据代理指标，不构成投资建议。</p></article>
  </div>`;
}

function bindCommon(){
  $$('[data-focus]').forEach(b=>b.onclick=()=>{state.focus=b.dataset.focus==='1';render()});
  $$('[data-exchange]').forEach(b=>b.onclick=()=>{state.exchange=b.dataset.exchange;render()});
}
function bindFlow(){bindCommon();bindCustomPeriod('period');$$('[data-broad-toggle]').forEach(cb=>cb.onchange=()=>{const all=[...document.querySelectorAll('[data-broad-toggle]')];const on=all.filter(x=>x.checked).map(x=>x.dataset.broadToggle);state.broadSelected=on.length===all.length?null:on;renderFlow()});$$('[data-period]').forEach(b=>b.onclick=()=>{state.period=b.dataset.period;state.flowZoom=1;state.flowPan=0;state.broadZoom=1;state.broadPan=0;renderFlow()});$$('[data-flow-metric]').forEach(b=>b.onclick=()=>{state.flowMetric=b.dataset.flowMetric;state.flowZoom=1;state.flowPan=0;renderFlow()});$$('[data-flow-zoom]').forEach(b=>b.onclick=()=>{changeChartZoom('flowZoom','flowPan',b.dataset.flowZoom);renderFlow()});$$('[data-flow-pan]').forEach(b=>b.onclick=()=>{changeChartPan('flowPan',b.dataset.flowPan,Number(b.dataset.step),Number(b.dataset.max));renderFlow()});$$('[data-broad-zoom]').forEach(b=>b.onclick=()=>{changeChartZoom('broadZoom','broadPan',b.dataset.broadZoom);renderFlow()});$$('[data-broad-pan]').forEach(b=>b.onclick=()=>{changeChartPan('broadPan',b.dataset.broadPan,Number(b.dataset.step),Number(b.dataset.max));renderFlow()})}
function render(){
  if(!state.flows||!state.history||!state.quoteSummary||!state.weights)return;
  if(state.view==='flow')renderFlow();else if(state.view==='rotation'){renderRotation();renderSector()}else if(state.view==='quote')renderQuote();else if(state.view==='star')renderStar();else if(state.view==='chinext')renderChiNext();else renderMethod()
}
function switchView(v){if(state.view!==v){state.search='';$('#search').value='';clearTimeout(searchTimer)}state.view=v;$$('.view').forEach(x=>x.classList.toggle('active',x.id===`${v}-view`));$$('[data-view]').forEach(x=>x.classList.toggle('active',x.dataset.view===v));render()}

$$('[data-view]').forEach(b=>b.onclick=()=>switchView(b.dataset.view));
$('#refresh').onclick=()=>load(true);
let searchTimer=0;
$('#search').oninput=e=>{state.search=e.target.value.trim().toLowerCase();clearTimeout(searchTimer);searchTimer=setTimeout(render,200)};
load();setInterval(()=>load(false),30000);

/* ======================= 板块资金流视图 ======================= */
const SECTOR_URL='data/weekly.json';
let secCache=null,secWeek=-1,secPick='',secKey='net',secDir=-1;

function secYi(v){return (v>=0?'+':'')+(v/1e8).toFixed(2);}

function secLoad(done){
  if(secCache){done();return;}
  fetch(SECTOR_URL).then(r=>r.json()).then(d=>{secCache=d;secWeek=d.weeks.length-1;done()})
    .catch(e=>{$('#sector-view').innerHTML='<div class="sec-card"><p class="sec-hint">板块数据读取失败：'+e.message+'</p></div>'});
}

function secRankMap(wi){
  const list=[];
  for(const b of secCache.blocks){
    if(b.l!==2)continue;
    const c=b.t[wi];if(!c)continue;
    list.push({code:b.c,net:c[0]});
  }
  list.sort((a,b)=>b.net-a.net);
  const m={};list.forEach((x,i)=>m[x.code]=i+1);
  return m;
}

function secRows(){
  const d=secCache,wi=secWeek,out=[];
  const prevRankMap=wi>0?secRankMap(wi-1):null;
  for(const b of d.blocks){
    if(b.l!==2)continue;
    const cell=b.t[wi];if(!cell)continue;
    const prev=wi>0?b.t[wi-1]:null;
    out.push({code:b.c,l1:b.p||b.n,l2:b.l===2?b.n:'—',net:cell[0],chg:cell[1],up:cell[2],days:cell[3],
      prevNet:prev?prev[0]:null,delta:prev?cell[0]-prev[0]:null,
      prevRank:prevRankMap?(prevRankMap[b.c]||null):null});
  }
  return out;
}

function secSorted(rows){
  const k=secKey,dir=secDir;
  return rows.slice().sort((a,b)=>{
    const x=a[k],y=b[k];
    if(typeof x==='string')return x.localeCompare(y,'zh-CN')*dir;
    if(x===null)return 1;if(y===null)return -1;
    return (x-y)*dir;
  });
}

function secBar(list,cls){
  const max=Math.max.apply(null,list.map(r=>Math.abs(r.net)).concat([1]));
  return list.map((r,i)=>{
    const w=Math.abs(r.net)/max*100;
    return '<div class="sec-rank-row" data-sec-pick="'+r.code+'">'+
      '<span class="sec-rank-idx">'+(i+1)+'</span>'+
      '<span class="sec-rank-name"><span class="sec-l1">'+r.l1+'</span><span class="sec-sep">·</span>'+r.l2+'</span>'+
      '<span class="sec-rank-track"><i class="sec-rank-bar '+cls+'" style="width:'+w.toFixed(1)+'%"></i></span>'+
      '<span class="sec-rank-val '+cls+'">'+secYi(r.net)+'亿</span></div>';
  }).join('');
}

function secTrendHtml(row){
  const block=secCache.blocks.find(b=>b.c===row.code);
  const vals=block?block.t.map(x=>x?x[0]/1e8:0):[];
  const inSum=vals.filter(v=>v>0).reduce((a,b)=>a+b,0);
  const outSum=vals.filter(v=>v<0).reduce((a,b)=>a+b,0);
  const inCnt=vals.filter(v=>v>0).length;
  const outCnt=vals.filter(v=>v<0).length;
  const netSum=inSum+outSum;
  const stats='<div class="sec-trend-stats">'+
    '<span>累计净额 <b class="'+(netSum>=0?'up':'down')+'">'+(netSum>=0?'+':'')+netSum.toFixed(2)+' 亿</b></span>'+
    '<span>流入合计 <b class="up">+'+inSum.toFixed(2)+' 亿</b>（'+inCnt+' 周）</span>'+
    '<span>流出合计 <b class="down">'+outSum.toFixed(2)+' 亿</b>（'+outCnt+' 周）</span>'+
    '</div>';
  return '<div class="sec-trend"><div class="sec-trend-head"><strong>'+row.l1+' · '+row.l2+'</strong>'+
    '<span class="sec-hint">近 '+secCache.weeks.length+' 周主力净额（亿元）· 红涨绿跌</span>'+
    '<button class="sec-close" data-sec-close="1">×</button></div>'+
    stats+
    '<canvas id="secChart" height="200"></canvas></div>';
}

function secDrawTrend(row){
  const cv=document.getElementById('secChart');if(!cv)return;
  const block=secCache.blocks.find(b=>b.c===row.code);if(!block)return;
  const dpr=window.devicePixelRatio||1;
  const W=cv.clientWidth||760,H=88;
  cv.width=W*dpr;cv.height=H*dpr;
  const ctx=cv.getContext('2d');ctx.scale(dpr,dpr);ctx.clearRect(0,0,W,H);
  const vals=block.t.map(x=>x?x[0]/1e8:0);
  const max=Math.max.apply(null,vals.map(Math.abs).concat([1]));
  const padL=8,padR=8,mid=H/2,span=H/2-18;
  const bw=(W-padL-padR)/vals.length;
  ctx.strokeStyle='rgba(255,255,255,.15)';ctx.beginPath();ctx.moveTo(padL,mid);ctx.lineTo(W-padR,mid);ctx.stroke();
  vals.forEach((v,i)=>{
    const bh=Math.abs(v)/max*span;
    const x=padL+i*bw+bw*0.18,w=bw*0.64;
    ctx.fillStyle=v>=0?'#e5484d':'#30a46c';
    ctx.fillRect(x,v>=0?mid-bh:mid,w,bh);
  });
  ctx.fillStyle='rgba(255,255,255,.5)';ctx.font='11px system-ui,sans-serif';
  ctx.fillText(secCache.weeks[0].k,padL,H-3);
  ctx.fillText(secCache.weeks[secCache.weeks.length-1].k,W-62,H-3);
}

function renderSector(){
  const view=$('#rotation-view');if(!view)return;
  let host=document.getElementById('sector-slot');
  if(!host){host=document.createElement('div');host.id='sector-slot';view.appendChild(host);}
  secLoad(function(){
    const d=secCache,wi=secWeek,week=d.weeks[wi];
    const rows=secRows();
    const inflow=rows.filter(r=>r.net>0).sort((a,b)=>b.net-a.net).slice(0,10);
    const outflow=rows.filter(r=>r.net<0).sort((a,b)=>a.net-b.net).slice(0,10);
    const ranked=rows.slice().sort((a,b)=>b.net-a.net);
    const rankNow={};ranked.forEach((r,i)=>{rankNow[r.code]=i+1});
    rows.forEach(r=>{r.rankShift=(r.prevRank!=null&&rankNow[r.code]!=null)?(r.prevRank-rankNow[r.code]):null});
    const picked=rows.find(r=>r.code===secPick);
    const sorted=secSorted(rows);
    const heads=[['l1','一级'],['l2','二级'],['net','本周净额'],['chg','本周涨跌'],['up','净流入天数'],['prevNet','上周净额'],['delta','环比变化'],['rankShift','排名变化']];
    const th=heads.map(h=>{
      const on=secKey===h[0]?' on':'';
      return '<th class="sec-th'+on+'" data-sec-key="'+h[0]+'">'+h[1]+(secKey===h[0]?(secDir<0?' ↓':' ↑'):'')+'</th>';
    }).join('');
    const tb=sorted.map((r,i)=>{
      const sel=secPick===r.code?' sel':'';
      const prevTxt=r.prevNet===null?'—':secYi(r.prevNet)+'亿';
      return '<tr class="sec-row'+sel+'" data-sec-pick="'+r.code+'">'+
        '<td class="sec-num">'+(i+1)+'</td><td>'+r.l1+'</td><td>'+r.l2+'</td>'+
        '<td class="sec-num '+(r.net>=0?'up':'down')+'">'+secYi(r.net)+'亿</td>'+
        '<td class="sec-num '+(r.chg>=0?'up':'down')+'">'+(r.chg>=0?'+':'')+r.chg.toFixed(2)+'%</td>'+
        '<td class="sec-num">'+r.up+'/'+r.days+'</td><td class="sec-num">'+prevTxt+'</td>'+
        '<td class="sec-num '+(r.delta>=0?'up':'down')+'">'+(r.delta===null?'—':secYi(r.delta)+'亿')+'</td>'+
        '<td class="sec-num">'+(r.rankShift===null?'—':(r.rankShift>0?'↑'+r.rankShift:(r.rankShift<0?'↓'+Math.abs(r.rankShift):'—')))+'</td></tr>';
    }).join('');

    host.innerHTML=
      '<div class="sec-section-title">板块资金流 · 按申万行业</div>'+
      '<div class="sec-cards">'+
        '<div class="sec-card"><span class="sec-card-k">统计周</span><span class="sec-card-v">'+week.k+'</span><span class="sec-hint">'+week.s+' ~ '+week.e+' · '+week.n+' 个交易日</span></div>'+
        '<div class="sec-card"><span class="sec-card-k">净流入</span><span class="sec-card-v up">'+rows.filter(r=>r.net>0).length+'</span><span class="sec-hint">个二级行业</span></div>'+
        '<div class="sec-card"><span class="sec-card-k">净流出</span><span class="sec-card-v down">'+rows.filter(r=>r.net<0).length+'</span><span class="sec-hint">个二级行业</span></div>'+
        '<div class="sec-card"><span class="sec-card-k">净流入居首</span><span class="sec-card-v">'+(ranked[0]?ranked[0].l2:'—')+'</span><span class="sec-hint">'+(ranked[0]?secYi(ranked[0].net)+' 亿元':'')+'</span></div>'+
      '</div>'+
      '<div class="sec-weekbar"><label class="sec-hint">选择周</label><select id="secWeek">'+
        d.weeks.map((w,i)=>'<option value="'+i+'"'+(i===wi?' selected':'')+'>'+w.k+'（'+w.s+' ~ '+w.e+'）</option>').join('')+
      '</select></div>'+
      (picked?secTrendHtml(picked):'')+
      '<div class="sec-boards">'+
        '<div class="sec-card"><div class="sec-card-head"><strong>本周净流入 Top 10</strong><span class="sec-hint">主力净额，单位亿元</span></div>'+secBar(inflow,'up')+'</div>'+
        '<div class="sec-card"><div class="sec-card-head"><strong>本周净流出 Top 10</strong><span class="sec-hint">主力净额，单位亿元</span></div>'+secBar(outflow,'down')+'</div>'+
      '</div>'+
      '<div class="sec-card"><div class="sec-card-head"><strong>全部二级行业</strong><span class="sec-hint">'+rows.length+' 个</span></div>'+
      '<div class="sec-tablewrap"><table class="sec-table"><thead><tr><th class="sec-th">#</th>'+th+'</tr></thead><tbody>'+tb+'</tbody></table></div></div>';

    if(picked)secDrawTrend(picked);

    const sel=$('#secWeek');
    if(sel)sel.onchange=function(){secWeek=Number(sel.value);renderSector()};
    $$('[data-sec-pick]').forEach(el=>{el.onclick=function(){secPick=el.dataset.secPick;renderSector()}});
    $$('[data-sec-key]').forEach(el=>{el.onclick=function(){
      const k=el.dataset.secKey;
      if(secKey===k)secDir=-secDir;else{secKey=k;secDir=(k==='l1'||k==='l2')?1:-1}
      renderSector();
    }});
    const close=$('[data-sec-close]');
    if(close)close.onclick=function(){secPick='';renderSector()};
  });
}
