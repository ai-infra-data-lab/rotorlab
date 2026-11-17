'use strict';
// Display rounding never writes back to the numeric JSON model.
const RotorNumbers = (() => {
 const integerKeys = new Set(['node','probe_node','points','modes']);
 function parse(value) {
  const text=String(value).trim();
  if(!/^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eEdD][+-]?\d+)?$/.test(text))return null;
  const n=Number(text.replace(/[dD]/,'e'));
  return Number.isFinite(n)?n:null;
 }
 function format(value,mode='scientific',integer=false,editing=false) {
  if(typeof value!=='number'||!Number.isFinite(value))return '';
  if(integer||mode==='normal')return String(value);
  return value.toExponential(editing?undefined:6).replace('e','E');
 }
 function list(value) {
  const tokens=String(value).trim().split(/[\s,;、，]+/).filter(Boolean);
  if(!tokens.length)throw Error('剛性の候補値を入力してください。');
  const values=tokens.map(parse);
  if(values.some(v=>v===null))throw Error('候補値は 5E5, 1E6, 2E6 のように入力してください。');
  return values;
 }
 function combinations(spec) {
  const sizes=spec.parameters.map(p=>p.values.length);
  if(!sizes.length)return 0;
  return spec.mode==='paired'?Math.max(...sizes):sizes.reduce((a,b)=>a*b,1);
 }
 return {parse,format,list,integerKeys,combinations};
})();
if(typeof module!=='undefined')module.exports=RotorNumbers;
