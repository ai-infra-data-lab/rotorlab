'use strict';

const balanceGradeValues = [0.4, 1, 2.5, 6.3, 16, 40, 100, 250, 630, 1600, 4000];
let balanceState;

function balanceSettings() {
  if (balanceState?.model === model) return balanceState;
  balanceState = {
    model,
    components: {shafts: new Set(), disks: new Set()},
    inputs: {plane_count: 2},
  };
  return balanceState;
}

function shiftBalanceSelection(key, removed) {
  if (balanceState?.model !== model || !balanceState?.components[key]) return;
  const rows = [...balanceState.components[key]];
  balanceState.components[key] = new Set(rows.filter(i => i !== removed).map(i => i > removed ? i - 1 : i));
}

function balanceNodePositions() {
  const positions = [0];
  for (const shaft of model.shafts) {
    positions.push(Number.isFinite(shaft.length_mm) ? positions.at(-1) + shaft.length_mm : NaN);
  }
  return positions;
}

function balanceValue(value) {
  if (!Number.isFinite(value)) return '—';
  if (numberMode === 'scientific' || (value !== 0 && Math.abs(value) < 0.001)) return value.toExponential(5);
  return Number(value).toLocaleString('ja-JP', {maximumSignificantDigits: 8});
}

function renderBalance() {
  const state = balanceSettings();
  const {inputs, components} = state;
  const nodes = balanceNodePositions();
  const bearings = [...new Set(model.bearings.map(b => b.node))].sort((a, b) => a - b);
  const twoPlanes = inputs.plane_count === 2;
  const field = (key, label) => `<label>${label}<input type="text" inputmode="decimal" data-balance-input="${key}" value="${esc(inputValue(inputs[key], key))}"></label>`;
  const componentList = (key, title, rowLabel) => `<fieldset><legend>${title}</legend><div class="balance-choices">${model[key].map((item, i) =>
    `<label><input type="checkbox" data-balance-component="${key}" value="${i}" ${components[key].has(i) ? 'checked' : ''}>${rowLabel(item, i)}</label>`).join('') || '<span>登録なし</span>'}</div></fieldset>`;

  $('editor').innerHTML = `<form id="balance-form" class="balance-form">
    <p class="formhint">剛性ロータの許容残留不釣合い。JIS B 0905:1992の箇条4、5に基づきます。座標の原点はモデルの節点0です。</p>
    <div class="actions"><button id="balance-select-all" type="button">すべて選択</button><button id="balance-clear" type="button">選択を解除</button><span id="balance-count" role="status"></span></div>
    <div class="balance-grid">
      ${componentList('shafts', '軸要素', (_, i) => `軸要素 ${i} · ${balanceValue(nodes[i])} ～ ${balanceValue(nodes[i + 1])} mm`)}
      ${componentList('disks', '円板', (disk, i) => `円板 ${i} · 節点 ${esc(disk.node)} · ${balanceValue(nodes[disk.node])} mm`)}
    </div>
    <div class="balance-grid">
      <label>釣合い良さの等級<select data-balance-input="grade"><option value="">選択してください</option>${balanceGradeValues.map(g => `<option value="${g}" ${g === inputs.grade ? 'selected' : ''}>G${g}</option>`).join('')}</select></label>
      ${field('max_rpm', '実用最高回転速度 [rpm]')}
      <label>釣合わせ<select data-balance-input="plane_count"><option value="1" ${twoPlanes ? '' : 'selected'}>1面</option><option value="2" ${twoPlanes ? 'selected' : ''}>2面</option></select></label>
      ${field('plane_i_mm', '修正面Iの位置 [mm]')}
      ${twoPlanes ? `${field('plane_ii_mm', '修正面IIの位置 [mm]')}
        ${field('bearing_a_mm', '使用時の軸受Aの位置 [mm]')}
        ${field('bearing_b_mm', '使用時の軸受Bの位置 [mm]')}
        ${field('plane_iii_mm', '修正面IIIの位置 [mm]（狭い2面間隔の場合）')}` : ''}
    </div>
    ${twoPlanes ? `<p class="formhint">軸受A→B、修正面I→IIは節点番号が増える方向に指定します。モデルに異なる2つの軸受位置がある場合は、その座標を入力欄に取り込めます。</p>
      <button id="balance-use-bearings" type="button" ${bearings.length === 2 && bearings.every(n => Number.isFinite(nodes[n])) ? '' : 'disabled'}>モデルの軸受位置を入力</button>` : ''}
    <div class="actions"><button id="balance-calculate" class="primary" type="submit">許容値を計算する</button></div>
    <p id="balance-status" role="status" aria-live="polite"></p>
    <div id="balance-result" class="scroll-table"></div>
  </form>`;

  $('balance-select-all').onclick = () => {
    for (const key of ['shafts', 'disks']) components[key] = new Set(model[key].keys());
    invalidateBalance(state);
    renderBalance();
  };
  $('balance-clear').onclick = () => {
    components.shafts.clear();
    components.disks.clear();
    invalidateBalance(state);
    renderBalance();
  };
  if (twoPlanes) $('balance-use-bearings').onclick = () => {
    [inputs.bearing_a_mm, inputs.bearing_b_mm] = bearings.map(n => nodes[n]);
    invalidateBalance(state);
    renderBalance();
  };
  const form = $('balance-form');
  form.querySelectorAll('[data-balance-component]').forEach(input => input.onchange = () => {
    const rows = components[input.dataset.balanceComponent];
    const index = Number(input.value);
    if (input.checked) rows.add(index);
    else rows.delete(index);
    invalidateBalance(state);
    renderBalanceResult(state);
  });
  form.querySelectorAll('[data-balance-input]').forEach(input => {
    const key = input.dataset.balanceInput;
    if (input.tagName !== 'SELECT') {
      input.onfocus = () => { input.value = inputValue(inputs[key], key, true); };
      input.onblur = () => { if (inputs[key] != null) input.value = inputValue(inputs[key], key); };
    }
    input.oninput = () => {
      inputs[key] = RotorNumbers.parse(input.value);
      invalidateBalance(state);
      if (key === 'plane_count') renderBalance();
      else renderBalanceResult(state);
    };
  });
  form.onsubmit = event => {
    event.preventDefault();
    runBalance(state);
  };
  renderBalanceResult(state);
}

function invalidateBalance(state) {
  state.pending = null;
  state.result = null;
  state.error = '';
}

async function runBalance(state) {
  if (state.pending?.revision === revision) return;
  invalidateBalance(state);
  const pending = {revision};
  state.pending = pending;
  renderBalanceResult(state);
  try {
    const result = await api('/api/balance', {
      model,
      settings: {...state.inputs, shaft_indices: [...state.components.shafts], disk_indices: [...state.components.disks]},
    });
    if (state.pending === pending) state.result = result;
  } catch (error) {
    if (state.pending === pending) state.error = error.message;
  } finally {
    if (state.pending === pending) {
      state.pending = null;
      state.resultRevision = pending.revision;
      if (section === 'balance' && state === balanceState) renderBalanceResult(state);
    }
  }
}

function renderBalanceResult(state) {
  const current = state.resultRevision === revision;
  const pending = state.pending?.revision === revision;
  const {shafts, disks} = state.components;
  $('balance-count').textContent = `選択中 · 軸要素 ${shafts.size} / 円板 ${disks.size}`;
  $('balance-calculate').disabled = pending || shafts.size + disks.size === 0;
  $('balance-status').textContent = pending ? '計算中…' : (current ? state.error : '') || '';
  const result = current && state.result;
  if (!result) {
    $('balance-result').innerHTML = '';
    return;
  }
  const d = result.details;
  const geometry = d.bearing_span_mm === undefined ? '' : `<p>軸受間 ${balanceValue(d.bearing_span_mm)} mm · 修正面間 ${balanceValue(d.correction_span_mm)} mm · 重心→I ${balanceValue(d.center_to_i_mm)} mm · 重心→II ${balanceValue(d.center_to_ii_mm)} mm</p>`;
  const settings = d.k === undefined ? '' : `<p>軸受Aの動荷重分担率 k = ${balanceValue(d.k)} · 修正面の許容値比 II/I = ${balanceValue(d.ratio)}</p>`;
  const couple = d.couple_phase_deg === undefined ? '' : `<p>修正面I・IIは位相差180°の偶不釣合い。修正面IIIは静・準静成分で、遠い軸受まで ${balanceValue(d.far_bearing_mm)} mm。</p>`;
  $('balance-result').innerHTML = `<h4>${esc(result.standard)} ${esc(result.clause)}</h4>
    <p>対象質量 <strong>${balanceValue(result.mass_kg)} kg</strong> · 軸方向重心 <strong>${balanceValue(result.center_mm)} mm</strong></p>
    <p>許容残留比不釣合い ${balanceValue(result.specific_um)} µm · 配分前の許容値 <strong>${balanceValue(result.total_g_mm)} g·mm</strong></p>
    ${geometry}${settings}${couple}${table(['修正面', '位置 [mm]', '許容残留不釣合い [g·mm]'], result.planes.map(plane =>
      [plane.name, balanceValue(plane.position_mm), balanceValue(plane.limit_g_mm)]))}`;
}
