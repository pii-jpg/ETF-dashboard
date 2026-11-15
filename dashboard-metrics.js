// 计算层（加载顺序 2/3）：筛选、聚合、时间序列、排序、资金轮动与板块数据。
function zoomedChartData(labels,series,zoom,pan=0){
  if(!labels.length)return {labels,series,visible:0,canLeft:false,canRight:false,maxPan:0};
  const minimum=Math.min(12,labels.length),visible=zoom<=1?labels.length:Math.max(minimum,Math.ceil(labels.length/zoom)),maxStart=Math.max(0,labels.length-visible),offset=Math.min(maxStart,Math.max(0,Math.round(pan))),start=maxStart-offset;
  return {labels:labels.slice(start,start+visible),series:series.map(item=>({...item,values:item.values.slice(start,start+visible)})),visible,canLeft:start>0,canRight:start<maxStart,maxPan:maxStart};
}
function changeChartZoom(key,panKey,action){
  if(action==='reset')state[key]=1;
  else if(action==='in')state[key]=Math.min(12,state[key]*1.5);
  else state[key]=Math.max(1,state[key]/1.5);
  state[panKey]=0;
}
function changeChartPan(key,action,step,maxPan){state[key]=action==='left'?Math.min(maxPan,state[key]+step):Math.max(0,state[key]-step)}
function zoomLabel(value){return `${num(value,1)}×`}
function broadIndexOf(etf){
  const quote=etf.quote||etf||{};  // 资金流行为 { ...x, quote }；盘中行情行没有 quote 包装，直接读行顶层 index_code
  const disclosed=INDEX_ALIASES[String(quote.index_code||'').toUpperCase()]||String(quote.index_code||'').toUpperCase();
  if(disclosed)return BROAD_INDEX_MAP.has(disclosed)?disclosed:null;
  const name=etf.liveName||quote.name||etf.name||'';
  if(BROAD_INDEX_EXCLUDE.test(name))return null;
  if(/科创50|科创板50/.test(name))return '000688';
  if(/中证1000|1000ETF/.test(name))return '000852';
  if(/中证500/.test(name))return '000905';
  if(/沪深300|300ETF|HS300/.test(name))return '000300';
  if(/上证50|50ETF/.test(name))return '000016';
  if(/创业板ETF|创业ETF/.test(name))return '399006';
  return null;
}
const BROAD_COLORS=['#ffd166','#fb8500','#e63946','#2ec4b6','#4ea8de','#9b5de5'];
const BROAD_CHART_ORDER=['000300','000688','399006','000016','000905','000852'];
function broadShareSeries(){
  const {start:baseDate,end:latest}=periodRange(state.period);
  const indexOf=new Map(),base=new Map();
  for(const etf of flowRows(state.period,{ignoreSearch:true,ignoreFilters:true})){
    if(!etf.p)continue;
    const code=broadIndexOf(etf);if(!code)continue;
    indexOf.set(etf.code,code);
    base.set(code,(base.get(code)||0)+Number(etf.p.base_shares||0)/1e8);
  }
  const cumulative=new Map(base),dates=[];
  const series=BROAD_INDEXES.map((item,i)=>({code:item.code,name:item.name,color:BROAD_COLORS[i],kind:'cumulative',values:[]}));
  // 每日增减与累计份额同源：同一次遍历既累加水位，也留下当日流量，两图互为差分
  const dailyShares=series.map(item=>({...item,kind:'dailyShares',values:[]}));
  for(const point of (state.history?.points||[]).filter(x=>x.date>baseDate&&x.date<=latest)){
    const added=new Map();
    for(const [etfCode,deltaShares] of point.changes||[]){
      const code=indexOf.get(etfCode);if(!code)continue;
      added.set(code,(added.get(code)||0)+Number(deltaShares)/1e8);
    }
    for(const [code,value] of added)cumulative.set(code,(cumulative.get(code)||0)+value);
    dates.push(point.date);
    for(let i=0;i<series.length;i+=1){
      const code=series[i].code,known=cumulative.has(code);
      series[i].values.push(known?cumulative.get(code):null);
      dailyShares[i].values.push(known?(added.get(code)||0):null);
    }
  }
  return {dates,series,dailyShares};
}
function broadIndexStats(){
  const groups=new Map(BROAD_INDEXES.map(item=>[item.code,{code:item.code,name:item.name,etfs:0,shares:0,delta:0}]));
  for(const etf of flowRows(state.period,{ignoreSearch:true,ignoreFilters:true})){
    if(!etf.p)continue;
    const code=broadIndexOf(etf);if(!code)continue;
    const group=groups.get(code);group.etfs+=1;
    group.shares+=Number(etf.latest_shares||0)/1e8;
    group.delta+=Number(etf.p.delta_shares||0)/1e8;
  }
  return [...groups.values()];
}
function broadSelectedSet(){return Array.isArray(state.broadSelected)?state.broadSelected.map(String):null}
function broadIsOn(code){const selected=broadSelectedSet();return !selected||selected.includes(String(code))}
function flowRows(periodKey=state.period,{ignoreSearch=false,ignoreFilters=false}={}){
  if(!state.flows)return [];
  const qmap=new Map(state.quotes.map(x=>[x.code,x]));
  return state.flows.items.map(x=>{
    const p=x.periods[periodKey],q=qmap.get(x.code)||{};
    const price=Number.isFinite(Number(q.price))?Number(q.price):null;
    const delta=p?.delta_shares??null;
    return {...x,latest_shares:p?.end_shares??x.latest_shares,p,price,liveName:q.name||x.name,estimate:delta!=null&&price!=null?delta*price:null,quote:q};
  }).filter(x=>ignoreSearch||!state.search||`${x.code}${x.liveName}`.toLowerCase().includes(state.search))
    .filter(x=>ignoreFilters||!state.focus||focusName(x.liveName))
    .filter(x=>ignoreFilters||state.exchange==='all'||x.exchange===state.exchange);
}

function historyFlowSeries(){
  const {start:baseDate,end:latest}=periodRange(state.period);
  const periodRows=flowRows(state.period).filter(x=>x.p),eligible=new Set(periodRows.map(x=>x.code));
  const prices=new Map(state.quotes.map(x=>[x.code,Number(x.price)]));
  const baseScale=periodRows.reduce((sum,x)=>sum+(Number.isFinite(x.price)?Number(x.p.base_shares||0)*x.price:0),0)/1e8;
  let cumulativeAmount=0;
  return (state.history?.points||[]).filter(x=>x.date>baseDate&&x.date<=latest).map(point=>{
    let dailyAmount=0,dailyShares=0;
    for(const [code,deltaShares] of point.changes||[]){
      if(!eligible.has(code))continue;
      const delta=Number(deltaShares),price=prices.get(code);dailyShares+=delta;
      if(Number.isFinite(price))dailyAmount+=delta*price;
    }
    cumulativeAmount+=dailyAmount;
    return {date:point.date,dailyAmount:dailyAmount/1e8,dailyShares:dailyShares/1e8,scale:baseScale+cumulativeAmount/1e8};
  });
}


const ROTATION_CATEGORY_RULES = [
  ['货币',/货币|快线|现金|保证金|添富快钱|收益快线|场内货基|理财金/],
  ['债券',/债券|国债|政金债|信用债|可转债|转债|公司债|城投债|短融|地方债/],
  ['商品',/黄金|白银|豆粕|原油|商品ETF|有色金属期货|能源化工/],
  ['港股海外',/港股|恒生|H股|中概|纳指|标普|日经|海外|亚太|美国|日本|德国|法国|印度|越南|沙特|全球|沪港深|QDII/],
  ['医药',/医药|医疗|生物|创新药|疫苗|中药|器械|健康|养老/],
  ['金融地产',/证券|银行|金融|地产|房地产|保险|非银/],
  ['科技',/科技|人工智能|AI|芯片|半导体|计算机|软件|云计算|互联网|通信|电子|数字经济|大数据|信息技术|传媒|游戏|动漫|5G|物联网|卫星/],
  ['新能源制造',/新能源|光伏|电池|锂电|储能|汽车|智能车|机器人|高端装备|机械|工业母机|制造|军工|国防|航空|航天|船舶|新材料/],
  ['消费',/消费|食品|白酒|酒ETF|家电|农业|养殖|畜牧|旅游|美妆|零售|餐饮|教育/],
  ['周期资源',/煤炭|钢铁|有色|化工|资源|稀土|石油|油气|矿业|建材|建筑|基建|电力|公用事业|环保|水务|物流|交运/],
  ['红利价值',/红利|股息|价值|低波|高股息|央企|国企|治理/],
  ['宽基',/沪深\d+|上证(?:50|180|380|综指)|中证(?:A50|A100|A500|500|800|1000|2000)|创业板|科创(?:50|100|200|综指)|深证(?:50|100|成指)|北证|MSCI中国A|大盘|中盘|小盘|全指|宽基|国证(?:1000|2000)|中小100/],
  ['策略主题',/ESG|质量|成长|自由现金流|基本面|增强|龙头|盈利|高端人才/]
];

function rotationCategory(etf){
  const text=`${etf.liveName||etf.name||''} ${etf.quote?.index_name||''}`.toUpperCase();
  return ROTATION_CATEGORY_RULES.find(([,pattern])=>pattern.test(text))?.[0]||'其他';
}

function buildRotationData(){
  const rows=flowRows(state.rotationPeriod,{ignoreFilters:true});
  const known=rows.filter(x=>x.p&&x.estimate!=null);
  const groups=new Map();
  for(const etf of known){
    const name=rotationCategory(etf),old=groups.get(name)||{name,inflow:0,outflow:0,net:0,etfs:0};
    old.etfs++;old.net+=etf.estimate;
    if(etf.estimate>0)old.inflow+=etf.estimate;
    else if(etf.estimate<0)old.outflow+=Math.abs(etf.estimate);
    groups.set(name,old);
  }
  const categories=[...groups.values()];
  const incomingAll=categories.filter(x=>x.net>0).map(x=>({...x,amount:x.net})).sort((a,b)=>b.amount-a.amount);
  const outgoingAll=categories.filter(x=>x.net<0).map(x=>({...x,amount:Math.abs(x.net)})).sort((a,b)=>b.amount-a.amount);
  const grossIn=incomingAll.reduce((sum,x)=>sum+x.amount,0),grossOut=outgoingAll.reduce((sum,x)=>sum+x.amount,0),net=categories.reduce((sum,x)=>sum+x.net,0),incoming=incomingAll.slice(0,8),outgoing=outgoingAll.slice(0,8);
  const largest=[...categories].sort((a,b)=>Math.abs(b.net)-Math.abs(a.net))[0]||null;
  return {rows,known,categories,grossIn,grossOut,net,incoming,outgoing,incomingCount:incomingAll.length,outgoingCount:outgoingAll.length,largest};
}

function quoteSortValue(row,key){
  if(key==='quote_time')return String(row.quote_time||'');
  if(key==='high_low'){const high=Number(row.high),low=Number(row.low);return Number.isFinite(high)?high:Number.isFinite(low)?low:null}
  const value=Number(row[key]);return Number.isFinite(value)?value:null;
}
function quoteRows(){
  const {key,dir}=state.quoteSort;
  return state.quotes.filter(x=>!state.search||`${x.code}${x.name}`.toLowerCase().includes(state.search)).filter(x=>!state.focus||focusName(x.name)).filter(x=>state.exchange==='all'||x.exchange===state.exchange).sort((a,b)=>{
    const av=quoteSortValue(a,key),bv=quoteSortValue(b,key);if(av==null&&bv==null)return 0;if(av==null)return 1;if(bv==null)return -1;
    const comparison=typeof av==='string'?av.localeCompare(bv):av-bv;return dir==='asc'?comparison:-comparison;
  });
}
function quoteSummaryForRows(rows){
  const quoted=rows.filter(x=>x.price!=null&&x.price!==''&&Number.isFinite(Number(x.price))&&String(x.quote_time||''));
  const amount=quoted.reduce((sum,x)=>sum+(Number.isFinite(Number(x.amount_100m))?Number(x.amount_100m):0),0);
  const asOf=quoted.reduce((latest,x)=>String(x.quote_time)>latest?String(x.quote_time):latest,'')||state.quoteSummary.as_of;
  return {universe_count:rows.length,quote_count:quoted.length,coverage:rows.length?quoted.length/rows.length*100:0,amount_100m:amount,up:quoted.filter(x=>Number(x.pct)>0).length,down:quoted.filter(x=>Number(x.pct)<0).length,as_of:asOf};
}

const BOARD_VIEWS={
  star:{key:'star',viewId:'star-view',board:'科创板',prefix:/^(688|689)/,prefixText:'688/689',
    indexes:[{code:'000300',name:'沪深300'},{code:'000016',name:'上证50'},{code:'000905',name:'中证500'},{code:'000852',name:'中证1000'}]},
  chinext:{key:'chinext',viewId:'chinext-view',board:'创业板',prefix:/^(300|301|302)/,prefixText:'300/301/302',
    indexes:[{code:'000300',name:'沪深300'},{code:'399001',name:'深证成指'},{code:'000905',name:'中证500'},{code:'000852',name:'中证1000'}]}
};
const BOARD_INDEX_MAPS=new Map(Object.entries(BOARD_VIEWS).map(([key,cfg])=>[key,new Map(cfg.indexes.map(item=>[item.code,item.name]))]));
function etfIndex(etf){
  const quote=typeof etf==='object'?(etf.quote||etf):{};
  const disclosed=INDEX_ALIASES[String(quote.index_code||'').toUpperCase()]||String(quote.index_code||'').toUpperCase();
  if(disclosed)return disclosed;
  const name=typeof etf==='string'?etf:(etf.liveName||quote.name||'');
  // 先排除境外/非 A 股指数，再按具体指数逐条识别（顺序即优先级）
  if(/恒生|港股|H股|中概|纳斯达克|标普|日经|德国|法国|东南亚|沙特|越南|亚太|海外|美国/.test(name))return null;
  if(/科创创业|双创/.test(name))return state.weights.indexes['931643']?'931643':null;
  if(/科创50|科创板50/.test(name))return '000688';
  if(/创业板50|^创50/.test(name))return '399673';
  if(/深证主板50|深证50/.test(name))return state.weights.indexes['399850']?'399850':null;
  if(/^创业板指|^创业板(指)?ETF/.test(name))return '399006';
  if(/A50/.test(name))return state.weights.indexes['930050']?'930050':null;
  if(/深证成指|深成指/.test(name))return '399001';
  if(/中证A500|A500ETF|A500基金/.test(name))return null;
  if(/中证1000|1000ETF/.test(name))return '000852';
  if(/中证2000|2000ETF/.test(name))return '932000';
  if(/中证500|500ETF/.test(name))return '000905';
  if(/沪深300|300ETF|HS300ETF/.test(name))return '000300';
  if(/上证50|50ETF/.test(name))return '000016';
  return null;
}

const normalizedIndexCache=new WeakMap();
function normalizedConstituents(index){
  if(!index)return [];
  if(normalizedIndexCache.has(index))return normalizedIndexCache.get(index);
  const merged=new Map();
  for(const stock of index.constituents||[]){
    const weight=Number(stock.weight);if(!Number.isFinite(weight))continue;
    // 官方只公开部分权重时保留全部成分（权重 0 也保留），仅用于展示成分与板块只数
    if(weight<=0&&!index.weight_partial)continue;
    const old=merged.get(stock.code)||{...stock,weight:0};old.weight+=weight;
    if(stock.price)old.price=stock.price;merged.set(stock.code,old);
  }
  const total=Number(index.weight_total)||[...merged.values()].reduce((s,x)=>s+x.weight,0);
  const rows=[...merged.values()].map(x=>({...x,fraction:total?x.weight/total:0}));
  normalizedIndexCache.set(index,rows);return rows;
}

function buildBoardShareData(cfg){
  const indexMap=BOARD_INDEX_MAPS.get(cfg.key),etfCounts=new Map();
  for(const etf of flowRows('day',{ignoreSearch:true,ignoreFilters:true})){
    const code=etfIndex(etf);
    if(indexMap.has(code))etfCounts.set(code,(etfCounts.get(code)||0)+1);
  }
  const uniqueBoardStocks=new Set(),rows=[];
  for(const {code,name:label} of cfg.indexes){
    const index=state.weights.indexes[code];if(!index)continue;
    const constituents=normalizedConstituents(index);
    const boardStocks=constituents.filter(x=>cfg.prefix.test(x.code)).sort((a,b)=>b.fraction-a.fraction);
    boardStocks.forEach(x=>uniqueBoardStocks.add(x.code));
    const partial=!!index.weight_partial;
    rows.push({
      code,name:label,source:index.source||'—',etfCount:etfCounts.get(code)||0,
      constituentCount:constituents.length,boardCount:boardStocks.length,partial,
      weightCoverage:index.weight_coverage,
      share:partial?null:boardStocks.reduce((sum,x)=>sum+x.fraction,0),boardStocks,topStocks:boardStocks.slice(0,5)
    });
  }
  return {rows,uniqueBoardCount:uniqueBoardStocks.size};
}

function priceHistoryItemReady(key,start,end){
  const item=state.stockPriceHistory[key];
  return Boolean(item&&item.start<=start&&item.end>=end&&Array.isArray(item.prices)&&item.prices.length);
}

function mergeStockPriceHistoryItems(items){
  for(const [key,item] of Object.entries(items||{})){
    state.stockPriceHistory[key]={...(state.stockPriceHistory[key]||{}),...item};
  }
}

function boardHistoryReady(cfg,row){
  if(!row||!Number.isFinite(row.share)||row.share<1e-8||row.share>.99999999)return true;
  const {start,end}=periodRange(state[cfg.key+'Period']);
  return priceHistoryItemReady(`index:${row.code}`,start,end)&&row.boardStocks.every(stock=>priceHistoryItemReady(stock.code,start,end));
}

async function ensureBoardPriceHistory(cfg,row){
  const loadingKey=cfg.key+'PriceLoading',reqKey=cfg.key+'PriceRequestKey',errorKey=cfg.key+'PriceError',failKey=cfg.key+'PriceErrorKey';
  if(!row||!Number.isFinite(row.share)||row.share<1e-8||row.share>.99999999||state[loadingKey])return;
  const {start,end}=periodRange(state[cfg.key+'Period']),indexKey=`index:${row.code}`;
  const missingStocks=[...new Set(row.boardStocks.filter(stock=>!priceHistoryItemReady(stock.code,start,end)).map(stock=>stock.code))];
  const missingIndex=priceHistoryItemReady(indexKey,start,end)?[]:[row.code];
  if(!missingStocks.length&&!missingIndex.length)return;
  const key=`${start}|${end}|${row.code}|${missingStocks.slice().sort().join(',')}`;
  if(state[failKey]===key)return;
  state[loadingKey]=true;state[reqKey]=key;state[errorKey]='';
  try{
    const batches=[];
    for(let i=0;i<missingStocks.length;i+=60)batches.push(missingStocks.slice(i,i+60));
    if(!batches.length)batches.push([]);
    for(let i=0;i<batches.length;i++){
      const params=new URLSearchParams({codes:batches[i].join(','),start,end});
      if(i===0&&missingIndex.length)params.set('indexes',missingIndex.join(','));
      const payload=await fetchJson(`/api/stock-price-history?${params}`);
      mergeStockPriceHistoryItems(payload.items);
      const failed=Object.entries(payload.items||{}).filter(([,item])=>item.error&&!(item.prices||[]).length);
      if(failed.length)throw new Error(failed.map(([itemKey,item])=>`${itemKey}：${item.error}`).join('；'));
    }
  }catch(err){
    state[errorKey]=`${err.message}；如本地看板服务尚未重启，请重启后重试`;
    state[failKey]=key;
  }finally{
    state[loadingKey]=false;
    if(state.view===cfg.key)renderBoard(cfg);
  }
}

function boardHistorySeries(cfg,row){
  const {start,end}=periodRange(state[cfg.key+'Period']);
  const fallbackDates=(state.history?.points||[]).map(x=>x.date).filter(date=>date>=start&&date<=end);
  if(!Number.isFinite(row.share))return fallbackDates.map((date,i)=>({date,share:null,changeBp:null,coverage:0}));
  if(row.share<1e-8)return fallbackDates.map((date,i)=>({date,share:0,changeBp:i?0:null,coverage:100}));
  if(row.share>.99999999)return fallbackDates.map((date,i)=>({date,share:100,changeBp:i?0:null,coverage:100}));
  if(!boardHistoryReady(cfg,row))return [];
  const indexRows=(state.stockPriceHistory[`index:${row.code}`]?.prices||[]).map(x=>[String(x[0]),Number(x[1])]).filter(x=>x[0]>=start&&x[0]<=end&&Number.isFinite(x[1])&&x[1]>0);
  if(!indexRows.length)return [];
  const indexAnchor=indexRows[indexRows.length-1][1];
  const stocks=row.boardStocks.map(stock=>{
    const prices=(state.stockPriceHistory[stock.code]?.prices||[]).map(x=>[String(x[0]),Number(x[1])]).filter(x=>Number.isFinite(x[1])&&x[1]>0);
    let anchor=null;
    for(const priceRow of prices)if(priceRow[0]<=end)anchor=priceRow[1];
    return {...stock,prices,anchor,cursor:0,dayPrice:null};
  });
  const result=[];let previous=null;
  for(const [date,indexPrice] of indexRows){
    let numerator=0,coveredWeight=0;
    for(const stock of stocks){
      while(stock.cursor<stock.prices.length&&stock.prices[stock.cursor][0]<=date){stock.dayPrice=stock.prices[stock.cursor][1];stock.cursor++}
      if(Number.isFinite(stock.dayPrice)&&Number.isFinite(stock.anchor)&&stock.anchor>0){
        numerator+=stock.fraction*stock.dayPrice/stock.anchor;
        coveredWeight+=stock.fraction;
      }
    }
    const denominator=indexPrice/indexAnchor,share=denominator>0?numerator/denominator*100:null;
    if(!Number.isFinite(share))continue;
    result.push({date,share,changeBp:previous==null?null:(share-previous)*100,coverage:row.share?coveredWeight/row.share*100:100});
    previous=share;
  }
  return result;
}
