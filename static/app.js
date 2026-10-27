/* Local first; no CDN, telemetry or remote model uploads. */
'use strict';
const $ = id => document.getElementById(id);
const esc = x => String(x ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = (x, digits=2) => Number(x).toLocaleString('ja-JP',{maximumFractionDigits:digits});
let model, section='shafts', selected=-1, result=null, pinned=null, dirty=true, busy=false, tab='campbell', revision=0;
let shapeIndex=0, shapeMode=0;
const token=document.querySelector('meta[name=rotor-token]').content;
const coeffs=[['node','節点'],['kxx','kxx [N/m]'],['kyy','kyy [N/m]'],['kxy','kxy [N/m]'],['kyx','kyx [N/m]'],['cxx','cxx [N s/m]'],['cyy','cyy [N s/m]'],['cxy','cxy [N s/m]'],['cyx','cyx [N s/m]'],['source','係数の出典']];
const columns={shafts:[['length_mm','長さ [mm]'],['od_mm','外径 [mm]'],['id_mm','内径 [mm]']],disks:[['node','節点'],['mass_kg','質量 [kg]'],['Id_kgm2','直径まわり Id [kg m²]'],['Ip_kgm2','極慣性 Ip [kg m²]']],bearings:coeffs,seals:coeffs,unbalances:[['node','節点'],['g_mm','不釣合い [g mm]'],['phase_deg','位相 [deg]']]};
const labels={shafts:'軸要素',disks:'円板',bearings:'軸受',seals:'シール',unbalances:'不釣合い',material:'材料・注記',analysis:'解析条件'};
const defaults={shafts:{length_mm:100,od_mm:50,id_mm:0},disks:{node:1,mass_kg:10,Id_kgm2:.05,Ip_kgm2:.08},bearings:{node:0,kxx:1e6,kyy:1e6,kxy:0,kyx:0,cxx:500,cyy:500,cxy:0,cyx:0,source:'仮定値'},seals:{node:1,kxx:0,kyy:0,kxy:0,kyx:0,cxx:0,cyy:0,cxy:0,cyx:0,source:'仮定値'},unbalances:{node:1,g_mm:100,phase_deg:0}};
function status(s){$('status').textContent=s;}
function fail(e){$('error').textContent=e.message||String(e);$('error').hidden=false;status('入力または計算を確認してください');}
$('error').onclick=()=>{$('error').hidden=true;};
function changed(){dirty=true;revision++;$('dirty').textContent=result?'入力変更・再解析が必要':'未解析';$('dirty').classList.toggle('warn',!!result);$('stale-result').hidden=!result;$('csv').disabled=true;$('pin').disabled=true;status(result?'入力を変更しました。解析結果は前回の入力に対応しています。':'入力を変更しました。解析を実行してください。');}
async function api(path,data){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-RotorLab-Token':token},body:JSON.stringify(data)});const d=await response.json();if(!response.ok)throw Error(d.error||'処理に失敗しました');return d;}
function renderNav(){$('parts').innerHTML=Object.entries(labels).map(([key,title])=>`<button data-section="${key}" class="${key===section?'active':''}">${title}<span>${Array.isArray(model[key])?model[key].length:'›'}</span></button>`).join('');$('parts').querySelectorAll('button').forEach(b=>b.onclick=()=>{section=b.dataset.section;selected=-1;render();});}
function render(){renderNav();$('model-name').value=model.name;$('editor-title').textContent=labels[section];$('add').hidden=!columns[section];renderEditor();drawGeometry();}
function renderEditor(){
 if(columns[section]){
  const cols=columns[section];
  $('editor').innerHTML=`<table><thead><tr><th>#</th>${cols.map(c=>`<th>${c[1]}</th>`).join('')}<th></th></tr></thead><tbody>${model[section].map((row,i)=>`<tr data-row="${i}" class="${selected===i?'highlight':''}"><td>${i}</td>${cols.map(([k,label])=>`<td><input aria-label="${esc(labels[section])} ${i} ${esc(label)}" data-row="${i}" data-key="${k}" type="${k==='source'?'text':'number'}" ${k!=='source'?'step="any"':''} value="${esc(row[k])}"></td>`).join('')}<td><button data-delete="${i}" aria-label="行${i}を削除">×</button></td></tr>`).join('')}</tbody></table><p class="formhint">節点は0から始まります。軸要素 i は節点 i と i+1 を接続。Excelのタブ区切りデータを入力欄へ貼り付けできます。</p>`;
  $('editor').querySelectorAll('input').forEach(input=>{
   input.onfocus=()=>{selected=+input.dataset.row;$('editor').querySelectorAll('tr[data-row]').forEach(r=>r.classList.toggle('highlight',+r.dataset.row===selected));drawGeometry();};
   input.oninput=()=>{model[section][input.dataset.row][input.dataset.key]=input.type==='number'?(input.value===''?null:Number(input.value)):input.value;changed();drawGeometry();};
   input.onpaste=event=>{const text=event.clipboardData.getData('text');if(!text.includes('\t')&&!text.includes('\n'))return;event.preventDefault();const start=cols.findIndex(c=>c[0]===input.dataset.key);const rows=text.trimEnd().split(/\r?\n/);if(rows.length+Number(input.dataset.row)>40)return fail(Error('貼り付けは40行以内です。'));rows.forEach((line,j)=>{const n=Number(input.dataset.row)+j;if(!model[section][n])model[section][n]=structuredClone(defaults[section]);line.split('\t').forEach((v,k)=>{const key=cols[start+k]?.[0];if(key)model[section][n][key]=key==='source'?v:(v.trim()===''?null:Number(v));});});changed();render();};
  });
  $('editor').querySelectorAll('[data-delete]').forEach(b=>b.onclick=()=>{if(section==='shafts'&&!confirm('軸要素を削除すると後続の節点位置が変わります。円板・軸受などの節点番号を確認してください。削除しますか？'))return;model[section].splice(+b.dataset.delete,1);selected=-1;changed();render();});
 }else{
  const fields=section==='material'?[['rho','密度 [kg/m³]'],['E_GPa','ヤング率 E [GPa]'],['G_GPa','せん断弾性係数 G [GPa]']]:[['max_rpm','走査上限 [rpm]'],['operating_rpm','確認回転数 [rpm]'],['points','走査点数（11～121）'],['probe_node','計測節点'],['modes','表示モード数']];
  $('editor').innerHTML=`<div class="formgrid">${fields.map(([k,label])=>`<label>${label}<input data-field="${k}" type="number" step="any" value="${esc(model[section][k])}"></label>`).join('')}${section==='material'?`<label style="grid-column:1/-1">モデルの注記・データの出典<textarea id="model-note" rows="2">${esc(model.note)}</textarea></label>`:''}</div><p class="formhint">${section==='material'?'全軸要素に共通の等方性材料。ν = E/(2G) − 1。':'確認回転数は走査点に追加されます。静止支持の地面基準で計測します。回転は +z 軸まわり x→y。'}</p>`;
  $('editor').querySelectorAll('[data-field]').forEach(i=>i.oninput=()=>{model[section][i.dataset.field]=i.value===''?null:Number(i.value);changed();});
  if($('model-note'))$('model-note').oninput=()=>{model.note=$('model-note').value;changed();};
 }
}
function drawGeometry(){
 const shafts=model.shafts;let nodes=[0];for(const s of shafts)nodes.push(nodes.at(-1)+Math.max(0,Number(s.length_mm)||0));const len=nodes.at(-1)||1;
 const maxDia=Math.max(50,...shafts.map(s=>Number(s.od_mm)||0));const X=x=>55+790*x/len,Y=90,sy=64/maxDia;
 let svg=`<svg viewBox="0 0 900 200" role="img" aria-label="ロータ断面図"><line x1="30" y1="${Y}" x2="870" y2="${Y}" stroke="#b5c7d6" stroke-dasharray="5 4"/>`;
 shafts.forEach((s,i)=>{let height=Math.max(2,(Number(s.od_mm)||0)*sy),hole=(Number(s.id_mm)||0)*sy;svg+=`<g data-part="shafts" data-index="${i}" class="shape"><rect x="${X(nodes[i])}" y="${Y-height/2}" width="${Math.max(1,X(nodes[i+1])-X(nodes[i]))}" height="${height}" fill="#b6c9d9" stroke="#688aa4" class="${section==='shafts'&&selected===i?'selected':''}"/>${hole>0?`<rect x="${X(nodes[i])}" y="${Y-hole/2}" width="${X(nodes[i+1])-X(nodes[i])}" height="${hole}" fill="#fff" stroke="#c0d1de"/>`:''}</g>`;});
 model.disks.forEach((d,i)=>{if(nodes[d.node]===undefined)return;svg+=`<rect data-part="disks" data-index="${i}" class="shape ${section==='disks'&&selected===i?'selected':''}" x="${X(nodes[d.node])-9}" y="27" width="18" height="126" rx="3" fill="#317e9e" stroke="#1c5b78"/>`;});
 model.bearings.forEach((b,i)=>{if(nodes[b.node]===undefined)return;const x=X(nodes[b.node]);svg+=`<g data-part="bearings" data-index="${i}" class="shape"><path class="${section==='bearings'&&selected===i?'selected':''}" d="M${x-16} 132 L${x} 105 L${x+16} 132 Z" fill="#13a4a6" stroke="#088182"/><line x1="${x-20}" y1="136" x2="${x+20}" y2="136" stroke="#088182" stroke-width="3"/></g>`;});
 model.seals.forEach((b,i)=>{if(nodes[b.node]!==undefined)svg+=`<rect data-part="seals" data-index="${i}" class="shape ${section==='seals'&&selected===i?'selected':''}" x="${X(nodes[b.node])-5}" y="45" width="10" height="90" fill="none" stroke="#af8153" stroke-width="3" stroke-dasharray="3 2"/>`;});
 model.unbalances.forEach((b,i)=>{if(nodes[b.node]!==undefined)svg+=`<text data-part="unbalances" data-index="${i}" class="shape" x="${X(nodes[b.node])}" y="20" text-anchor="middle" fill="#cd842a" font-size="20">↓</text>`;});
 nodes.forEach((v,i)=>{svg+=`<text x="${X(v)}" y="168" text-anchor="middle" fill="#526e85" font-size="11">${i}</text>`;});
 svg+=`<line x1="55" y1="184" x2="845" y2="184" stroke="#cedbe5"/><text x="450" y="198" text-anchor="middle" fill="#6a8196" font-size="11">全長 ${fmt(len)} mm · 節点 0–${shafts.length} · 円板の描画寸法は記号</text></svg>`;
 $('geometry').innerHTML=svg;$('geometry').querySelectorAll('[data-part]').forEach(s=>s.onclick=()=>{section=s.dataset.part;selected=+s.dataset.index;render();$('editor').querySelector(`tr[data-row="${selected}"]`)?.scrollIntoView({block:'nearest'});});
}
function download(name,text,type){const url=URL.createObjectURL(new Blob([text],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('model-name').oninput=()=>{model.name=$('model-name').value;changed();};
$('add').onclick=()=>{if(model[section].length>=40)return;model[section].push(structuredClone(defaults[section]));changed();render();};
$('save').onclick=()=>download('rotor-model.json',JSON.stringify(model,null,2),'application/json');
$('load').onclick=()=>{$('file').value='';$('file').click();};
$('file').onchange=async()=>{try{const file=$('file').files[0];if(!file)return;if(file.size>300000)throw Error('300KB以内のモデルを選択してください。');const data=JSON.parse(await file.text());const checked=await api('/api/validate',data);model=checked.model;changed();selected=-1;render();status('モデルを読み込みました。解析を実行してください。');}catch(e){fail(e);}};
$('sample').onclick=async()=>{if(!confirm('現在の入力をサンプルへ置き換えます。必要なら先に保存してください。続けますか？'))return;await loadSample();};
async function loadSample(){model=await(await fetch('/api/sample')).json();changed();selected=-1;render();status('架空サンプルを読み込みました。解析を実行できます。');}
$('validate').onclick=async()=>{try{await api('/api/validate',model);status('入力チェック完了。形式・寸法・節点・係数の範囲に問題はありません。実機妥当性は別途確認が必要です。');$('error').hidden=true;}catch(e){fail(e);}};
$('run').onclick=async()=>{
 if(busy)return;busy=true;$('run').disabled=true;$('error').hidden=true;status('計算中… 固有値・MAC追跡・同期応答を計算しています。初回は準備に時間がかかります。');
 const stamp=revision;
 try{const r=await api('/api/analyze',structuredClone(model));result=r;dirty=stamp!==revision;shapeIndex=r.operating_index;shapeMode=0;$('dirty').textContent=dirty?'入力変更・再解析が必要':'解析済み';$('dirty').classList.toggle('warn',dirty);$('stale-result').hidden=!dirty;$('pin').disabled=dirty;$('csv').disabled=dirty;$('empty').hidden=true;$('result-content').hidden=false;renderResults();status(dirty?'計算完了後に入力が変更されています。再解析してください。':`解析完了 · ${r.engine} · ${r.rpm.length}回転数点`);}catch(e){fail(e);}finally{busy=false;$('run').disabled=false;}
};
const tabs={campbell:'Campbell線図',response:'振幅・位相',stability:'安定性',mode:'モード形状',orbit:'軌道',static:'静たわみ・反力'};
const colors=['#176b91','#13a1a4','#a56fbb','#cf8d36','#5874b7','#b35c74','#597c47','#8c6d43','#333333','#9f5c21','#487b92','#888888'];
function traces(r,key){return r.frequency_hz[0].map((_,j)=>({x:r.rpm,y:r[key].map(row=>row[j]),name:`M${j+1}`,mode:'lines',line:{color:colors[j%colors.length],width:2}}));}
function renderResults(){
 const r=result;
 $('metrics').innerHTML=[['総質量',fmt(r.mass_kg),'kg'],['1×交点・最小',r.critical_speeds.length?fmt(Math.min(...r.critical_speeds.map(x=>x.rpm)),0):'範囲内なし','rpm'],[`計測節点 ${r.model.analysis.probe_node} の応答最大`,fmt(r.peak_um),'µm / 片振幅'],[`${fmt(r.model.analysis.operating_rpm,0)} rpm の安定性`,r.stability,'全横モード']].map(([label,value,unit])=>`<div class="metric"><small>${esc(label)}</small><strong>${esc(value)}<em>${esc(unit)}</em></strong></div>`).join('');
 $('tabs').innerHTML=Object.entries(tabs).map(([key,label])=>`<button data-tab="${key}" class="${key===tab?'active':''}">${label}</button>`).join('');$('tabs').querySelectorAll('button').forEach(b=>b.onclick=()=>{tab=b.dataset.tab;renderResults();});
 $('notes').innerHTML=r.notes.map(n=>`<p>${esc(n)}</p>`).join('');
 $('provenance').textContent=`${r.model.name} · ${r.engine} · ${r.model.note||'注記なし'}${pinned?' · 比較ケース: '+pinned.model.name:''}`;
 drawResult();
}
function table(headers,rows){return `<table><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(v=>`<td>${esc(v)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;}
function drawResult(){
 const r=result;let data=[],layout={font:{family:'Segoe UI, Yu Gothic UI, sans-serif',color:'#536a80',size:11},margin:{l:65,r:35,t:32,b:50},paper_bgcolor:'#fff',plot_bgcolor:'#fff',xaxis:{gridcolor:'#edf2f6',title:{text:'回転数 [rpm]'}},yaxis:{gridcolor:'#edf2f6'},legend:{orientation:'h',y:1.15},hovermode:'closest'};
 $('result-tools').innerHTML='';$('detail').innerHTML='';
 if(tab==='campbell'){
  data=traces(r,'frequency_hz');data.push({x:r.rpm,y:r.rpm.map(x=>x/60),name:'1×',line:{color:'#a1aeba',dash:'dash'}});
  if(pinned)traces(pinned,'frequency_hz').forEach(t=>{t.name='比較 '+t.name;t.line={...t.line,dash:'dot',width:1};data.push(t);});
  layout.yaxis.title={text:'減衰固有振動数 [Hz]'};
  $('result-tools').textContent='曲線の点をクリックすると、その回転数・モードの形状を表示します。';
  $('detail').innerHTML=table(['モード','1×交点 [rpm]（補間値）'],r.critical_speeds.map(c=>[`M${c.mode}`,fmt(c.rpm,1)]));
 }else if(tab==='response'){
  ['x','y'].forEach((axis,i)=>{data.push({x:r.rpm,y:r[`amplitude_${axis}_um`],name:axis.toUpperCase()+' 片振幅',line:{color:colors[i]}});data.push({x:r.rpm,y:r[`phase_${axis}_deg`],name:axis.toUpperCase()+' 位相',yaxis:'y2',line:{color:colors[i],dash:'dot'}});});
  if(pinned)['x','y'].forEach((axis,i)=>data.push({x:pinned.rpm,y:pinned[`amplitude_${axis}_um`],name:`比較 ${axis.toUpperCase()} (節点${pinned.model.analysis.probe_node})`,line:{color:colors[i],dash:'dash'}}));
  layout.yaxis.title={text:'片振幅 [µm]'};layout.yaxis2={title:{text:'位相 [deg]'},overlaying:'y',side:'right',range:[-180,180],showgrid:false};layout.margin.r=70;
  $('result-tools').textContent=`計測節点 ${r.model.analysis.probe_node} · 離散点最大 ${fmt(r.peak_um)} µm @ ${fmt(r.peak_rpm,0)} rpm · 位相は exp(iωt) 基準`;
  $('detail').innerHTML=table(['軸受節点',`X 動反力 [N] @ ${fmt(r.model.analysis.operating_rpm,0)} rpm`,'Y 動反力 [N]'],r.model.bearings.map((b,i)=>[b.node,...r.dynamic_reactions_N[r.operating_index][i].map(v=>fmt(v,3))]));
 }else if(tab==='stability'){
  data=traces(r,'log_dec');data.push({x:r.rpm,y:r.rpm.map(()=>0),name:'境界 δ=0',line:{color:'#b64238',dash:'dash'}});layout.yaxis.title={text:'対数減衰率 δ'};
  $('result-tools').textContent='δ > 0: 減衰 / δ < 0: 不安定。表示モード以外を含む全横モードの最大実部も確認。';
  $('detail').innerHTML=table(['回転数 [rpm]','全横モード 最大実部 [1/s]','判定'],r.rpm.filter((_,i)=>i%Math.max(1,Math.floor(r.rpm.length/10))===0||i===r.operating_index).map(rpm=>{let i=r.rpm.indexOf(rpm);return[fmt(rpm,0),fmt(r.max_real_all_modes[i],5),r.max_real_all_modes[i]>1e-7?'不安定':r.max_real_all_modes[i]<-1e-7?'漸近安定':'中立/境界'];}));
 }else if(tab==='mode'){
  const index=shapeIndex,j=shapeMode,s=r.mode_shapes[index][j];
  $('result-tools').innerHTML=`<label>モード <select id="shape-mode">${r.frequency_hz[0].map((_,i)=>`<option value="${i}" ${i===j?'selected':''}>M${i+1}</option>`).join('')}</select></label><label>回転数 <input id="shape-speed" type="range" min="0" max="${r.rpm.length-1}" value="${index}"></label><span>${fmt(r.rpm[index],0)} rpm · ${fmt(r.frequency_hz[index][j])} Hz · ${esc(r.whirl[index][j])} · MAC ${fmt(r.mac[index][j],3)}</span>`;
  $('shape-mode').onchange=e=>{shapeMode=+e.target.value;drawResult();};$('shape-speed').oninput=e=>{shapeIndex=+e.target.value;drawResult();};
  data=[{x:r.node_mm,y:s.x_re,name:'X 実部',line:{color:colors[0]}},{x:r.node_mm,y:s.y_re,name:'Y 実部',line:{color:colors[1]}},{x:r.node_mm,y:s.x_im,name:'X 虚部',line:{color:colors[0],dash:'dot'}},{x:r.node_mm,y:s.y_im,name:'Y 虚部',line:{color:colors[1],dash:'dot'}}];layout.xaxis.title={text:'軸方向位置 [mm]'};layout.yaxis.title={text:'正規化変位（節点値）'};
 }else if(tab==='orbit'){
  data=[{x:r.orbit_x_um,y:r.orbit_y_um,name:'同期軌道',line:{color:colors[0]}},{x:[r.orbit_x_um[0]],y:[r.orbit_y_um[0]],name:'位相 0°',mode:'markers',marker:{color:'#cf8d36',size:9}}];layout.xaxis.title={text:'X [µm]'};layout.yaxis={...layout.yaxis,title:{text:'Y [µm]'},scaleanchor:'x',scaleratio:1};
  $('result-tools').textContent=`節点 ${r.model.analysis.probe_node} · ${fmt(r.model.analysis.operating_rpm,0)} rpm · 地面基準の絶対変位 · 静たわみを除く`;
 }else if(tab==='static'){
  data=[{x:r.node_mm,y:r.static_y_um,name:'Y 静たわみ',line:{color:colors[0]}},{x:r.node_mm,y:r.static_x_um,name:'X 静たわみ',line:{color:colors[1]}}];layout.xaxis.title={text:'軸方向位置 [mm]'};layout.yaxis.title={text:'静変位 [µm]'};
  $('detail').innerHTML=table(['軸受節点','X 支持反力 [N]','Y 支持反力 [N]'],r.reactions.map(b=>[b.node,fmt(b.fx_N,3),fmt(b.fy_N,3)]));
  $('result-tools').textContent=`重力 −Y · 重量 ${fmt(r.mass_kg*9.80665)} N · Y支持反力合計 ${fmt(r.reactions.reduce((sum,b)=>sum+b.fy_N,0))} N`;
 }
 layout.shapes=['campbell','response','stability'].includes(tab)?[{type:'line',xref:'x',yref:'paper',x0:r.model.analysis.operating_rpm,x1:r.model.analysis.operating_rpm,y0:0,y1:1,line:{color:'#d6a24e',width:1,dash:'dot'}}]:[];
 Plotly.react('plot',data,layout,{responsive:true,displaylogo:false,modeBarButtonsToRemove:['lasso2d','select2d','sendChartToCloud']});
 $('plot').removeAllListeners?.('plotly_click');
 if(tab==='campbell')$('plot').on('plotly_click',e=>{const p=e.points[0];if(p.curveNumber>=r.frequency_hz[0].length)return;shapeIndex=p.pointIndex;shapeMode=p.curveNumber;tab='mode';renderResults();});
}
$('pin').onclick=()=>{if(!result||dirty)return;pinned=structuredClone(result);$('clear-pin').disabled=false;status('現在の解析結果を比較用に保持しました。入力を変更して再解析すると重ねて表示できます。');renderResults();};
$('clear-pin').onclick=()=>{pinned=null;$('clear-pin').disabled=true;renderResults();};
$('csv').onclick=()=>{if(!result||dirty)return;const r=result;const header=['rpm','x_peak_um','y_peak_um','phase_x_deg','phase_y_deg','all_modes_max_real_1_s',...r.frequency_hz[0].flatMap((_,j)=>[`mode${j+1}_Hz`,`mode${j+1}_logdec`,`mode${j+1}_real_1_s`])];const rows=r.rpm.map((rpm,i)=>[rpm,r.amplitude_x_um[i],r.amplitude_y_um[i],r.phase_x_deg[i],r.phase_y_deg[i],r.max_real_all_modes[i],...r.frequency_hz[i].flatMap((f,j)=>[f,r.log_dec[i][j],r.real_part[i][j]])]);download('rotor-results.csv','\ufeff'+[header,...rows].map(row=>row.join(',')).join('\r\n'),'text/csv;charset=utf-8');};
window.addEventListener('beforeunload',e=>{if(dirty&&revision>1){e.preventDefault();e.returnValue='';}});
loadSample().catch(fail);
