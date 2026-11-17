// Logic smoke check only. This is NOT a real browser/rendering test.
const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
const fixture=JSON.parse(fs.readFileSync('artifacts/sample-result.json','utf8'));
const nodes=new Map();
function el(id){if(!nodes.has(id))nodes.set(id,{innerHTML:'',textContent:'',hidden:false,disabled:false,value:'',classList:{add(){},toggle(){}},querySelectorAll(){return[];},querySelector(){return null;},removeAllListeners(){},on(){},click(){}});return nodes.get(id);}
let lastPlot;
const sandbox={console,structuredClone,URL,Blob,setTimeout,confirm:()=>true,
 document:{getElementById:el,querySelector:()=>({content:'test-token'}),createElement:()=>el('a')},
 window:{addEventListener(){}},Plotly:{react:(id,data,layout)=>{lastPlot={data,layout};}},
 fetch:async()=>({ok:true,json:async()=>structuredClone(fixture.model)})};
const ctx=vm.createContext(sandbox);
vm.runInContext('const RotorLimits = '+fs.readFileSync('limits.json','utf8'),ctx);
vm.runInContext(fs.readFileSync('static/numeric.js','utf8'),ctx);
vm.runInContext(fs.readFileSync('static/app.js','utf8'),ctx);
vm.runInContext(fs.readFileSync('static/sweep.js','utf8'),ctx);
const run=code=>vm.runInContext(code,ctx);
(async()=>{
 await new Promise(resolve=>setImmediate(resolve));
 assert.match(el('geometry').innerHTML,/svg/);
 sandbox.fixture=fixture;
 run('result=fixture;dirty=false;shapeIndex=result.operating_index;renderResults()');
 for(const name of ['campbell','response','stability','mode','orbit','static']){
  run(`tab='${name}';renderResults()`);
  assert.ok(lastPlot.data.length>0,name+' has traces');
  assert.ok(lastPlot.data.every(t=>t.x.length===t.y.length),name+' trace sizes');
 }
 run("tab='response';renderResults()");
 assert.ok(lastPlot.layout.yaxis2,'phase has its own axis');
 run('pinned=structuredClone(result);tab="campbell";renderResults()');
 assert.equal(lastPlot.data.length,fixture.frequency_hz[0].length*2+1,'case overlay');
 run('changed()');
 assert.ok(el('csv').disabled&&el('pin').disabled,'stale results cannot be exported or pinned');
 assert.equal(el('stale-result').hidden,false,'stale warning shown beside results');
 assert.match(el('dirty').textContent,/再解析/);
 assert.equal(run('esc("<script>")'),'&lt;script&gt;','model labels escaped');
 assert.match(run('inputValue(1000000,"kxx")'),/E\+6$/);
 const sourceRho=run('selectedMaterial(model.shafts[0]).rho');
 run('section="material";$("add").onclick();model.materials.at(-1).name="仮定材B";model.materials.at(-1).rho=4500;setCell(model.shafts[0],"material_id","仮定材B")');
 assert.equal(run('model.materials.length'),2,'materials registered in material screen');
 assert.equal(run('selectedMaterial(model.shafts[0]).rho'),4500,'selected material applies to element');
 assert.equal(run('selectedMaterial(model.shafts[1]).rho'),sourceRho,'other element keeps default');
 run('model.materials.at(-1).name="名称変更";model.materials.at(-1).rho=4600');
 assert.equal(run('selectedMaterial(model.shafts[0]).rho'),4600,'shared property edits use stable ID');
 assert.throws(()=>run('deleteMaterial(model.materials.at(-1).id)'),/使用中/);
 run('section="shafts";renderEditor()');
 assert.match(el('editor').innerHTML,/名称変更/,'shaft table has material choices');
 assert.match(el('editor').innerHTML,/select/);
 assert.ok(!el('editor').innerHTML.includes('data-common'),'old per-element material editor removed');
 run('model.shafts[0].material_id=null;deleteMaterial(model.materials.at(-1).id);section="material";renderEditor()');
 assert.equal(run('model.materials.length'),1,'unused material can be deleted');
 assert.match(el('editor').innerHTML,/材料名/);
 assert.match(el('editor').innerHTML,/出典/);
 assert.throws(()=>run('setCell(model.shafts[0],"material_id","未登録")'),/登録/);
 sandbox.sweepFixture={cases:[{index:1,status:'ok',model:fixture.model,parameters:[{bearing:0,coefficient:'kxx',value:1e6}],result:fixture},{index:2,status:'error',model:fixture.model,parameters:[{bearing:0,coefficient:'kxx',value:2e6}],error:'failed test case'}],total:2,success:1,failed:1,base_model:fixture.model};
 const sweepFixture=sandbox.sweepFixture;
 sweepFixture.cases[0].result={...fixture,lowest_frequency_hz:fixture.frequency_hz.map(row=>Math.min(...row))};
 delete sweepFixture.cases[0].result.frequency_hz;
 delete sweepFixture.cases[0].model;delete sweepFixture.cases[1].model;
 run('sweepResult=sweepFixture;sweepStamp=revision;renderSweepResults()');
 run('$("sweep-plot-kind").value="frequency";drawSweep()');
 assert.equal(lastPlot.data[0].y.length,fixture.rpm.length,'compact comparison curves');
 assert.match(el('sweep-table').innerHTML,/計算失敗/);
 assert.equal(lastPlot.data.length,1,'failed cases omitted from numeric curves');
 run('changed()');
 assert.equal(el('sweep-stale').hidden,false);
 assert.equal(el('sweep-csv').disabled,true);
 assert.match(run('sweepLabel({parameters:[{bearing:0,coefficient:"kxx",value:1234567.891234567}]},true)'),/1\.234567891234567E\+6/,'CSV parameters preserve original precision');
 run('section="shafts";model.shafts=Array.from({length:25},()=>structuredClone(defaults.shafts));render();$("add").onclick()');
 assert.equal(run('model.shafts.length'),26,'row addition passes old 24-element limit');
 run('section="analysis";renderEditor()');
 assert.match(el('editor').innerHTML,/1001/,'analysis labels use shared limit');
 sandbox.fetch=async(path,options)=>{
  assert.equal(path,'/api/mode');
  const body=JSON.parse(options.body);
  assert.equal(body.rpm,fixture.rpm[0]);
  return {ok:true,json:async()=>({mode_shapes:fixture.mode_shapes[0]})};
 };
 run('result=structuredClone(fixture);result.mode_shapes[0]=null;shapeIndex=0;shapeMode=0;tab="mode"');
 await run('loadModeShapes(result,0)');
 assert.equal(lastPlot.data.length,4,'on-demand shapes drawn after API response');
 assert.ok(run('result.mode_shapes[0]'),'on-demand response cached');
 console.log('UI logic smoke: 6 plot tabs, phase axis, overlay, stale state, escaping passed.');
 console.log('No browser layout, click, paste or download behavior has been verified by this check.');
})().catch(e=>{console.error(e);process.exitCode=1;});
