// 数据层（加载顺序 1/3）：常量、全局状态、数值格式化、周期区间与取数。
const $ = (s, el=document) => el.querySelector(s);
const $$ = (s, el=document) => [...el.querySelectorAll(s)];
const PERIODS = ['day','week','1m','2m','3m','6m','ytd','12m','custom','range20240924_20260630'];
const FLOW_METRICS = {
  amount:{label:'金额(亿元)',unit:'亿元',dailyKey:'dailyAmount',dailyName:'每日估算净额',dailyTitle:'每日变化'},
  scale:{label:'规模(亿元)',unit:'亿元',dailyKey:'scale',dailyName:'每日估算总规模',dailyTitle:'每日规模'},
  shares:{label:'份额(亿份)',unit:'亿份',dailyKey:'dailyShares',dailyName:'每日份额变动',dailyTitle:'每日份额变化'}
};
const HISTORY_START='2024-01-01';  // 份额历史有效起点：早于此日的自选区间不再提供
const state = { view:'flow', period:'day', rotationPeriod:'day', starPeriod:'3m', chinextPeriod:'3m', starIndex:'000300', flowMetric:'amount', flowZoom:1, starZoom:1, chinextZoom:1, broadZoom:1, broadSelected:null, flowPan:0, starPan:0, chinextPan:0, broadPan:0, starPriceLoading:false, starPriceRequestKey:'', starPriceError:'', starPriceErrorKey:'', chinextPriceLoading:false, chinextPriceRequestKey:'', chinextPriceError:'', chinextPriceErrorKey:'', quoteSort:{key:'amount_100m',dir:'desc'}, search:'', focus:false, exchange:'all', quotes:[], quoteSummary:null, quoteSources:null, flows:null, history:null, weights:null, stockPriceHistory:{}, stockPriceLoading:false, stockPriceRequestKey:'', customBase:null, customLoading:false, customOpen:false, customDraft:{start:null,end:null}, loading:false };
let chartWidth=960;
function chartViewWidth(viewId,reserve=292){const el=$('#'+viewId),w=el&&el.clientWidth?el.clientWidth:1338;return Math.max(680,Math.round(w-reserve))}

const nfmt = new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2});
const compact = new Intl.NumberFormat('zh-CN',{notation:'compact',maximumFractionDigits:2});
function num(v,d=2){return Number.isFinite(Number(v))?Number(v).toLocaleString('zh-CN',{minimumFractionDigits:d,maximumFractionDigits:d}):'—'}
function signed(v,d=2,suffix=''){return Number.isFinite(Number(v))?`${v>0?'+':''}${num(v,d)}${suffix}`:'—'}
function cls(v){return v>0?'up':v<0?'down':''}
function dateTime(v){return v?String(v).replace('T',' ').slice(0,19):'—'}
function quoteTime(v){return v&&v.length>=14?`${v.slice(0,4)}-${v.slice(4,6)}-${v.slice(6,8)} ${v.slice(8,10)}:${v.slice(10,12)}:${v.slice(12,14)}`:'—'}
function axisLabel(v){return /^\d{4}-\d{2}-\d{2}$/.test(v)?v.slice(5):v}
function focusName(name=''){return ['沪深300','上证50','中证500','中证1000','创业板','科创50'].some(x=>name.includes(x))}
const INDEX_ALIASES={'399300':'000300','399905':'000905','399852':'000852','399510':'000510'};
const BROAD_INDEXES=[
  {code:'000300',name:'沪深300'},
  {code:'000016',name:'上证50'},
  {code:'000905',name:'中证500'},
  {code:'000852',name:'中证1000'},
  {code:'399006',name:'创业板指'},
  {code:'000688',name:'科创50'}
];
const BROAD_INDEX_MAP=new Map(BROAD_INDEXES.map(item=>[item.code,item]));
const BROAD_INDEX_EXCLUDE=/港股通50|恒生50|美国50|A50|红利低波50|科创创业|双创50|创业板50|创业50|标普|国证1000|国证2000|中证2000|2000ETF/;
function periodRange(key){const p=state.flows.periods[key]||{};return {start:p.base_date,end:p.end_date||state.flows.latest_date}}
function ensureCustomPeriod(){if(state.flows&&!state.flows.periods.custom)state.flows.periods.custom={label:'自选',base_date:null,end_date:null}}
function reapplyCustomPeriod(){
  const base=state.customBase;if(!base||!state.flows)return;
  const start=base.start,end=base.end;
  state.flows.periods.custom={label:'自选',start_date:state.customRequestedStart||start.date,base_date:start.date,end_date:end.date};
  for(const item of state.flows.items){
    const b=start.shares[item.code],e=end.shares[item.code];
    item.periods.custom=b&&e?{base_date:b.date,end_date:e.date,base_shares:b.shares,end_shares:e.shares,delta_shares:e.shares-b.shares,delta_pct:b.shares?(e.shares-b.shares)/b.shares:null}:null;
  }
}

async function fetchJson(url){const res=await fetch(url);const body=await res.json();if(!res.ok)throw new Error(body.error||`HTTP ${res.status}`);return body}
async function load(force=false){
  if(state.loading)return; state.loading=true; $('#refresh').disabled=true;
  try{
    // 三个数据文件走 ETag 协商：内容未变时服务端回 304，不再重复下载 11.8MB
    const [live,flows,history,weights]=await Promise.all([fetchJson(`/api/etfs${force?'?force=1':''}`),fetchJson('/data/etf_flow_periods.json'),fetchJson('/data/etf_flow_history.json').catch(()=>({points:[],coverage:{}})),fetchJson('/data/index_weights.json')]);
    state.quotes=live.items||[];state.quoteSummary=live.summary||{};state.quoteSources=live.sources||{};state.flows=flows;state.history=history;state.weights=weights;
    ensureCustomPeriod();reapplyCustomPeriod();
    $('#freshness').textContent=`盘中行情 ${quoteTime(state.quoteSummary.as_of)} · ETF份额 ${flows.latest_date} · 份额日频更新`;
    render(); if(force)toast('数据已刷新');
  }catch(err){showError(err.message)}finally{state.loading=false;$('#refresh').disabled=false}
}

function showError(msg){$('.view.active').innerHTML=`<div class="error"><h2>数据读取失败</h2><p>${msg}</p><button class="primary" onclick="load(true)">重新连接</button></div>`}