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
vm.runInContext(fs.readFileSync('static/app.js','utf8'),ctx);
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
 console.log('UI logic smoke: 6 plot tabs, phase axis, overlay, stale state, escaping passed.');
 console.log('No browser layout, click, paste or download behavior has been verified by this check.');
})().catch(e=>{console.error(e);process.exitCode=1;});
