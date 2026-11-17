'use strict';
let sweepResult=null, sweepStamp=-1;
const sweepNames={kxx_kyy:'kxx + kyy（同じ値）',kxx:'kxx',kyy:'kyy',kxy:'kxy',kyx:'kyx'};
function sweepInvalidated(){
 if(!sweepResult)return;
 $('sweep-stale').hidden=false;
 $('sweep-csv').disabled=true;$('sweep-curves-csv').disabled=true;
}
function sweepSpec(){
 const s=model.sweep||{mode:'cartesian',parameters:[]};
 return {mode:s.mode,parameters:s.parameters.map(p=>({bearing:p.bearing,coefficient:p.coefficient,
  values:Array.isArray(p.values)?p.values:RotorNumbers.list(p.raw||'')}))};
}
function updateSweepCount(){
 try{const n=RotorNumbers.combinations(sweepSpec());$('sweep-count').textContent=`${n} ケース / 上限${RotorLimits.sweep_cases}`;}
 catch(e){$('sweep-count').textContent='候補値を確認してください';}
}
function renderSweep(){
 if(!model.sweep)model.sweep={mode:'cartesian',parameters:[{bearing:0,coefficient:'kxx_kyy',values:[5e5,1e6,2e6]}]};
 const spec=model.sweep;
 $('sweep-mode').value=spec.mode;
 $('sweep-editor').innerHTML=`<table><thead><tr><th>軸受番号（節点）</th><th>剛性成分</th><th>候補値 [N/m]（カンマ・空白区切り）</th><th></th></tr></thead><tbody>${spec.parameters.map((p,i)=>`<tr><td><select data-sweep-bearing="${i}" aria-label="パラメータ${i+1}の軸受">${model.bearings.map((b,j)=>`<option value="${j}" ${j===p.bearing?'selected':''}>軸受 ${j}（節点 ${esc(b.node)}）</option>`).join('')}</select></td><td><select data-sweep-coeff="${i}" aria-label="パラメータ${i+1}の剛性成分">${Object.entries(sweepNames).map(([key,label])=>`<option value="${key}" ${key===p.coefficient?'selected':''}>${label}</option>`).join('')}</select></td><td><input type="text" data-sweep-values="${i}" aria-label="パラメータ${i+1}の候補値" value="${esc(p.raw??p.values.map(v=>RotorNumbers.format(v,'scientific',false,true)).join(', '))}"></td><td><button data-sweep-delete="${i}" aria-label="パラメータ${i+1}を削除">×</button></td></tr>`).join('')}</tbody></table>`;
 $('sweep-editor').querySelectorAll('[data-sweep-bearing]').forEach(el=>el.onchange=()=>{spec.parameters[+el.dataset.sweepBearing].bearing=+el.value;changed();});
 $('sweep-editor').querySelectorAll('[data-sweep-coeff]').forEach(el=>el.onchange=()=>{spec.parameters[+el.dataset.sweepCoeff].coefficient=el.value;changed();});
 $('sweep-editor').querySelectorAll('[data-sweep-values]').forEach(el=>el.oninput=()=>{const p=spec.parameters[+el.dataset.sweepValues];try{p.values=RotorNumbers.list(el.value);delete p.raw;}catch(e){p.values=null;p.raw=el.value;}changed();updateSweepCount();});
 $('sweep-editor').querySelectorAll('[data-sweep-delete]').forEach(el=>el.onclick=()=>{spec.parameters.splice(+el.dataset.sweepDelete,1);changed();renderSweep();});
 updateSweepCount();
}
$('sweep-mode').onchange=()=>{model.sweep.mode=$('sweep-mode').value;changed();updateSweepCount();};
$('sweep-add').onclick=()=>{if(model.sweep.parameters.length>=RotorLimits.sweep_parameters)return fail(Error(`パラメータは最大${RotorLimits.sweep_parameters}行です。`));model.sweep.parameters.push({bearing:Math.min(model.sweep.parameters.length,model.bearings.length-1),coefficient:'kxx_kyy',values:[5e5,1e6,2e6]});changed();renderSweep();};
$('run-sweep').onclick=async()=>{
 if(busy)return;
 let spec;try{spec=sweepSpec();const n=RotorNumbers.combinations(spec);if(n<1||n>RotorLimits.sweep_cases)throw Error(`一括計算は1～${RotorLimits.sweep_cases}ケースにしてください。`);}catch(e){return fail(e);}
 const stamp=revision,base=structuredClone(model);
 busy=true;$('run-sweep').disabled=true;$('run').disabled=true;$('error').hidden=true;
 $('sweep-status').textContent=`${RotorNumbers.combinations(spec)}ケースを計算中…`;status('軸受剛性の一括計算を実行しています。');
 try{
  const response=await api('/api/sweep',{model:base,specification:spec});
  sweepResult=response;sweepStamp=stamp;$('sweep-output').hidden=false;
  const stale=stamp!==revision;$('sweep-stale').hidden=!stale;$('sweep-csv').disabled=stale;$('sweep-curves-csv').disabled=stale;
  $('sweep-status').textContent=`${response.total}ケース完了 · 成功 ${response.success} / 失敗 ${response.failed}${stale?' · 入力変更あり':''}`;
  renderSweepResults();status('一括計算が完了しました。結果一覧と重ね合わせグラフを確認できます。');
 }catch(e){$('sweep-status').textContent='計算条件を確認してください';fail(e);}
 finally{busy=false;$('run-sweep').disabled=false;$('run').disabled=false;}
};
function sweepLabel(c,exact=false){return c.parameters.map(p=>`軸受${p.bearing} ${p.coefficient}=${RotorNumbers.format(p.value,'scientific',false,exact)}`).join(' / ');}
function renderSweepResults(){
 if(!sweepResult)return;
 const rows=sweepResult.cases.map(c=>{
  const r=c.result;
  return `<tr><td>${c.index}</td><td>${esc(sweepLabel(c))}</td><td>${esc(r?r.stability:'計算失敗')}</td><td>${r?fmt(r.peak_um,4):'—'}</td><td>${r?fmt(r.peak_rpm,0):'—'}</td><td>${r&&r.critical_speeds.length?fmt(Math.min(...r.critical_speeds.map(s=>s.rpm)),1):'—'}</td><td>${r?`<button data-sweep-apply="${c.index}">モデルへ反映</button>`:esc(c.error)}</td></tr>`;
 });
 $('sweep-table').innerHTML=`<table><thead><tr><th>ケース</th><th>変更した剛性 [N/m]</th><th>確認回転数の安定性</th><th>最大片振幅 [µm]</th><th>ピーク [rpm]</th><th>最小1×交点 [rpm]</th><th>操作 / エラー</th></tr></thead><tbody>${rows.join('')}</tbody></table>`;
 $('sweep-table').querySelectorAll('[data-sweep-apply]').forEach(el=>el.onclick=()=>{const c=sweepResult.cases.find(c=>c.index===+el.dataset.sweepApply);model=structuredClone(sweepResult.base_model);for(const p of c.parameters){for(const key of p.coefficient==='kxx_kyy'?['kxx','kyy']:[p.coefficient])model.bearings[p.bearing][key]=p.value;}model.name=`${sweepResult.base_model.name} / ケース${c.index}`;changed();render();status('選択ケースをモデルへ反映しました。「解析する」でモード形状等の詳細を計算できます。');});
 drawSweep();
}
function drawSweep(){
 if(!sweepResult)return;
 const kind=$('sweep-plot-kind').value||'amplitude';
 const data=sweepResult.cases.filter(c=>c.status==='ok').map((c,i)=>{
  const r=c.result;const y=kind==='stability'?r.max_real_all_modes:kind==='frequency'?(r.lowest_frequency_hz||r.frequency_hz.map(row=>Math.min(...row))):r.amplitude_x_um.map((x,j)=>Math.max(x,r.amplitude_y_um[j]));
  return {x:r.rpm,y,name:`C${c.index}: ${sweepLabel(c)}`,mode:'lines',line:{color:colors[i%colors.length],dash:i<colors.length?'solid':'dash'}};
 });
 const ylabel=kind==='stability'?'全横モード 最大実部 [1/s]':kind==='frequency'?'表示モードの最低周波数 [Hz]':'max(|X|, |Y|) 片振幅 [µm]';
 Plotly.react('sweep-plot',data,{font:{family:'Segoe UI, Yu Gothic UI, sans-serif',size:11},margin:{l:70,r:25,t:30,b:60},xaxis:{title:{text:'回転数 [rpm]'}},yaxis:{title:{text:ylabel}},legend:{orientation:'h',y:-.25},shapes:kind==='stability'?[{type:'line',xref:'paper',yref:'y',x0:0,x1:1,y0:0,y1:0,line:{color:'#b64238',dash:'dot'}}]:[]},{responsive:true,displaylogo:false,modeBarButtonsToRemove:['lasso2d','select2d','sendChartToCloud']});
}
$('sweep-plot-kind').onchange=drawSweep;
function downloadCsv(name,rows){
 const quote=v=>'"'+String(v??'').replace(/"/g,'""')+'"';
 download(name,'\ufeff'+rows.map(row=>row.map(quote).join(',')).join('\r\n'),'text/csv;charset=utf-8');
}
$('sweep-csv').onclick=()=>{
 if(!sweepResult||sweepStamp!==revision)return;
 const header=['case','status','parameters_N_m','operating_rpm','probe_node','stability','peak_um','peak_rpm','min_1x_rpm','error'];
 const rows=sweepResult.cases.map(c=>{const r=c.result;return[c.index,c.status,sweepLabel(c,true),sweepResult.base_model.analysis.operating_rpm,sweepResult.base_model.analysis.probe_node,r?.stability,r?.peak_um,r?.peak_rpm,r?.critical_speeds.length?Math.min(...r.critical_speeds.map(s=>s.rpm)):null,c.error];});
 downloadCsv('rotor-sweep-summary.csv',[header,...rows]);
};
$('sweep-curves-csv').onclick=()=>{
 if(!sweepResult||sweepStamp!==revision)return;
 const rows=[['case','parameters_N_m','rpm','x_peak_um','y_peak_um','max_real_1_s','lowest_displayed_mode_Hz']];
 for(const c of sweepResult.cases){if(c.status!=='ok')continue;const r=c.result;r.rpm.forEach((rpm,i)=>rows.push([c.index,sweepLabel(c,true),rpm,r.amplitude_x_um[i],r.amplitude_y_um[i],r.max_real_all_modes[i],(r.lowest_frequency_hz?.[i]??Math.min(...r.frequency_hz[i]))]));}
 downloadCsv('rotor-sweep-curves.csv',rows);
};
if(typeof model!=='undefined'&&model)renderSweep();
