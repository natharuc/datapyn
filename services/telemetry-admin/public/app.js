const $ = (id) => document.getElementById(id);
const numberFormat = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 });
const decimalFormat = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 });
const dateTimeFormat = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
const shortDateFormat = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit' });
const timeFormat = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit' });
const eventLabels = { app_start: 'Inicialização', execution_finished: 'Execução concluída', connection_recovery: 'Recuperação de conexão', runtime_error: 'Erro do runtime', ui_error: 'Erro da interface' };
const statusLabels = { succeeded: 'Sucesso', success: 'Sucesso', ready: 'Pronta', failed: 'Falha', error: 'Erro', blocked: 'Bloqueada', cancelled: 'Cancelada', canceled: 'Cancelada', started: 'Iniciada', starting: 'Iniciando', recovering: 'Recuperando', retrying: 'Nova tentativa', recovered: 'Recuperada', none: 'Nenhum' };
const platformLabels = { windows: 'Windows', macos: 'macOS', linux: 'Linux', other: 'Outro', unknown: 'Desconhecida' };
const databaseLabels = { sqlserver: 'SQL Server', postgresql: 'PostgreSQL', postgres: 'PostgreSQL', mysql: 'MySQL', mariadb: 'MariaDB', databricks: 'Databricks', sqlite: 'SQLite', oracle: 'Oracle', duckdb: 'DuckDB', none: 'Sem banco', unknown: 'Desconhecido', other: 'Outro' };
const errorLabels = { transport: 'Transporte', timeout: 'Tempo esgotado', authentication: 'Autenticação', syntax: 'Sintaxe', cancellation: 'Cancelamento', cancelled: 'Cancelamento', canceled: 'Cancelamento', unknown: 'Desconhecido', none: 'Nenhum' };
let dashboardData = null;
let activeRequest = 0;
let requestController = null;
let appliedFilters = new URLSearchParams({ period: '7d' });

function numeric(value) { return typeof value === 'number' && Number.isFinite(value) ? value : null; }
function count(value) { const parsed = numeric(value); return parsed === null ? '—' : numberFormat.format(parsed); }
function percent(value) { const parsed = numeric(value); return parsed === null ? '—' : `${decimalFormat.format(parsed * 100)}%`; }
function duration(value) {
  const parsed = numeric(value);
  if (parsed === null) return '—';
  if (parsed < 1000) return `${decimalFormat.format(parsed)} ms`;
  if (parsed < 60000) return `${decimalFormat.format(parsed / 1000)} s`;
  return `${decimalFormat.format(parsed / 60000)} min`;
}
function parseDate(value) {
  if (!value) return null;
  const normalized = typeof value === 'string' && /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(value) ? `${value.replace(' ', 'T')}Z` : value;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}
function label(mapping, value) { return mapping[value] || value || '—'; }
function element(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined) node.textContent = value;
  return node;
}
function feedback(state, message, login = false) {
  $('feedback').dataset.state = state;
  $('feedback-text').textContent = state === 'error' && dashboardData ? `${message} Exibindo a última consulta concluída.` : message;
  $('login-link').hidden = !login;
}
function loading(value) {
  $('dashboard').setAttribute('aria-busy', String(value));
  $('refresh').disabled = value;
  $('apply').disabled = value;
  $('filters').querySelectorAll('select').forEach(select => { select.disabled = value; });
}
function updateOptions(id, values, mapping = {}) {
  const select = $(id);
  const selected = select.value;
  const options = Array.from(new Set(Array.isArray(values) ? values : [])).filter(value => typeof value === 'string' && value !== 'dev');
  if (selected && !options.includes(selected)) options.push(selected);
  select.replaceChildren(select.options[0]);
  options.forEach(value => { const option = element('option', '', label(mapping, value)); option.value = value; select.append(option); });
  select.value = selected;
}
function renderSummary(summary) {
  $('metric-executions').textContent = count(summary.executions);
  $('metric-failures').textContent = count(summary.failures);
  $('metric-failures-note').textContent = summary.failureRate === null ? 'Sem execuções no período' : `${percent(summary.failureRate)} das execuções`;
  $('metric-duration').textContent = duration(summary.averageDurationMs);
  $('metric-recovery').textContent = percent(summary.recoverySuccessRate);
  $('metric-recovery-note').textContent = `${count(summary.recoveries)} resultados de recuperação`;
  $('runtime-errors').textContent = count(summary.runtimeErrors);
  $('ui-errors').textContent = count(summary.uiErrors);
}
function svgElement(tag, attributes = {}, value) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  Object.entries(attributes).forEach(([key, entry]) => node.setAttribute(key, String(entry)));
  if (value !== undefined) node.textContent = value;
  return node;
}
function renderSeries(series) {
  const container = $('activity-chart');
  container.replaceChildren();
  const valid = Array.isArray(series) ? series.filter(point => parseDate(point.timestamp)).sort((a, b) => parseDate(a.timestamp) - parseDate(b.timestamp)) : [];
  const tableBody = $('activity-values');
  tableBody.replaceChildren();
  valid.forEach(point => { const row = element('tr'); [dateTimeFormat.format(parseDate(point.timestamp)), count(point.executions), count(point.failures), duration(point.averageDurationMs)].forEach(value => row.append(element('td', '', value))); tableBody.append(row); });
  if (!valid.length || !valid.some(point => (numeric(point.executions) || 0) + (numeric(point.failures) || 0) > 0)) {
    container.append(element('p', 'chart-placeholder', 'Nenhuma execução neste período.'));
    if (!valid.length) { const row = element('tr'); const cell = element('td', 'empty-cell', 'Nenhum valor no período.'); cell.colSpan = 4; row.append(cell); tableBody.append(row); }
    return;
  }
  const width = Math.max(320, container.clientWidth - 34), height = 230, left = 40, right = 15, top = 13, bottom = 32;
  const plotWidth = width - left - right, plotHeight = height - top - bottom;
  const highest = Math.max(1, ...valid.flatMap(point => [numeric(point.executions) || 0, numeric(point.failures) || 0]));
  const power = 10 ** Math.floor(Math.log10(highest));
  const max = Math.ceil(highest / power) * power;
  const firstTime = parseDate(valid[0].timestamp).getTime(), lastTime = parseDate(valid.at(-1).timestamp).getTime();
  const x = (point, index) => left + (lastTime === firstTime ? plotWidth / 2 : (parseDate(point.timestamp).getTime() - firstTime) / (lastTime - firstTime) * plotWidth);
  const y = value => top + plotHeight - (numeric(value) || 0) / max * plotHeight;
  const svg = svgElement('svg', { viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-labelledby': 'activity-title activity-description' });
  svg.append(svgElement('title', { id: 'activity-title' }, 'Execuções e falhas no período'));
  svg.append(svgElement('desc', { id: 'activity-description' }, `${valid.length} intervalos. Maior volume de ${count(highest)} eventos por intervalo. Os valores estão disponíveis na tabela abaixo.`));
  for (let tick = 0; tick <= 4; tick++) {
    const value = max * tick / 4, position = y(value);
    svg.append(svgElement('line', { x1: left, y1: position, x2: width - right, y2: position, stroke: '#e8ede7', 'stroke-width': 1, 'stroke-dasharray': tick ? '3 4' : '0' }));
    svg.append(svgElement('text', { x: left - 11, y: position + 4, 'text-anchor': 'end', fill: '#718078', 'font-size': 10, 'font-family': 'Segoe UI, sans-serif' }, numberFormat.format(value)));
  }
  const labelCount = Math.min(5, valid.length);
  const indices = new Set(Array.from({ length: labelCount }, (_, index) => Math.round(index * (valid.length - 1) / Math.max(1, labelCount - 1))));
  indices.forEach(index => {
    const point = valid[index];
    const value = $('period').value === '24h' ? timeFormat.format(parseDate(point.timestamp)) : shortDateFormat.format(parseDate(point.timestamp));
    svg.append(svgElement('text', { x: x(point, index), y: height - 9, 'text-anchor': 'middle', fill: '#718078', 'font-size': 10, 'font-family': 'Segoe UI, sans-serif' }, value));
  });
  [{ key: 'executions', color: '#14755f', title: 'Execuções' }, { key: 'failures', color: '#bb493c', title: 'Falhas' }].forEach(metric => {
    const path = valid.map((point, index) => `${index ? 'L' : 'M'}${x(point, index).toFixed(2)} ${y(point[metric.key]).toFixed(2)}`).join(' ');
    svg.append(svgElement('path', { d: path, fill: 'none', stroke: metric.color, 'stroke-width': 2, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'vector-effect': 'non-scaling-stroke' }));
    valid.forEach((point, index) => {
      const marker = svgElement('circle', { cx: x(point, index), cy: y(point[metric.key]), r: valid.length > 40 ? 1.5 : 2.6, fill: metric.color });
      marker.append(svgElement('title', {}, `${dateTimeFormat.format(parseDate(point.timestamp))} · ${metric.title}: ${count(point[metric.key])}`));
      svg.append(marker);
    });
  });
  container.append(svg);
}
function renderDistribution() {
  const type = $('distribution').value;
  const mapping = type === 'databases' ? databaseLabels : type === 'errors' ? errorLabels : {};
  $('distribution-caption').textContent = { databases: 'Execuções por banco de dados', errors: 'Eventos por categoria de erro', versions: 'Eventos por versão' }[type];
  const rows = (dashboardData?.breakdowns?.[type] || []).filter(row => numeric(row.count) !== null && row.count > 0 && (type !== 'errors' || row.name !== 'none')).sort((a, b) => b.count - a.count).slice(0, 5);
  const container = $('distribution-chart');
  container.replaceChildren();
  if (!rows.length) { container.append(element('p', 'chart-placeholder', type === 'errors' ? 'Nenhum erro neste período.' : 'Nenhum evento neste período.')); return; }
  const maximum = Math.max(...rows.map(row => row.count));
  rows.forEach(row => {
    const item = element('div', 'bar-row');
    const heading = element('div', 'bar-label');
    heading.append(element('span', 'name', label(mapping, row.name)), element('span', 'count', count(row.count)));
    const track = element('div', 'bar-track'); track.setAttribute('aria-hidden', 'true');
    const fill = element('div', 'bar-fill'); fill.style.width = `${row.count / maximum * 100}%`; track.append(fill);
    item.append(heading, track); container.append(item);
  });
}
function renderEvents(events, meta) {
  const rows = Array.isArray(events) ? events : [];
  const body = $('events-body'); body.replaceChildren();
  $('events-count').textContent = `${count(rows.length)} pontos`;
  $('events-subtitle').textContent = `Até ${count(meta.eventLimit || 100)} pontos amostrados mais recentes`;
  if (!rows.length) { const row = element('tr'); const cell = element('td', 'empty-cell', 'Nenhum evento para os filtros selecionados.'); cell.colSpan = 11; row.append(cell); body.append(row); return; }
  rows.forEach(event => {
    const row = element('tr'); const date = parseDate(event.timestamp);
    const dateCell = element('td'); const time = element('time', '', date ? dateTimeFormat.format(date) : '—');
    if (date) { time.dateTime = date.toISOString(); time.title = date.toLocaleString('pt-BR', { timeZoneName: 'short' }); } dateCell.append(time); row.append(dateCell);
    const name = element('td', 'event-name', label(eventLabels, event.event)); name.title = event.event || ''; row.append(name);
    const status = element('td'); const statusStyle = ['failed', 'error', 'blocked'].includes(event.status) ? 'bad' : ['success', 'succeeded', 'ready', 'recovered'].includes(event.status) ? 'good' : 'neutral';
    const tag = element('span', `tag ${statusStyle}`, label(statusLabels, event.status)); tag.title = event.status || ''; status.append(tag); row.append(status);
    row.append(element('td', '', event.version || '—'), element('td', '', label(platformLabels, event.platform)), element('td', '', label(databaseLabels, event.dbType)), element('td', 'number', duration(event.durationMs)), element('td', '', label(errorLabels, event.errorCode)), element('td', '', event.rowsBucket === 'none' ? '—' : event.rowsBucket || '—'), element('td', 'number', count(event.attempt)), element('td', 'number', count(event.sampleWeight)));
    body.append(row);
  });
}
function render(data) {
  dashboardData = data;
  renderSummary(data.summary || {});
  updateOptions('version', data.filters?.versions);
  updateOptions('platform', data.filters?.platforms, platformLabels);
  updateOptions('database', data.filters?.databases, databaseLabels);
  renderSeries(data.series);
  renderDistribution();
  renderEvents(data.events, data.meta || {});
  const generated = parseDate(data.meta?.generatedAt), start = parseDate(data.meta?.start), end = parseDate(data.meta?.end);
  $('updated-at').textContent = generated ? `Atualizado às ${timeFormat.format(generated)}` : 'Consulta atualizada';
  $('chart-range').textContent = start && end ? `${shortDateFormat.format(start)} a ${shortDateFormat.format(end)} · horário local` : 'Execuções ao longo do tempo';
}
async function load(params) {
  requestController?.abort();
  const controller = new AbortController();
  requestController = controller;
  const requestId = ++activeRequest;
  loading(true);
  feedback('loading', 'Consultando telemetria…');
  const timeout = setTimeout(() => controller.abort(), 25000);
  try {
    const response = await fetch(`/api/dashboard?${params}`, { method: 'GET', headers: { Accept: 'application/json' }, credentials: 'same-origin', redirect: 'manual', signal: controller.signal });
    if (response.type === 'opaqueredirect' || [301, 302, 303, 307, 308, 401, 403].includes(response.status)) { feedback('error', 'Sua sessão expirou ou sua identidade não tem acesso ao painel.', true); return; }
    if (!response.headers.get('content-type')?.includes('application/json')) { feedback('error', 'Não foi possível validar sua sessão. Entre novamente.', true); return; }
    const data = await response.json();
    if (requestId !== activeRequest) return;
    if (!response.ok) {
      const messages = { configuration_required: 'O painel aguarda a configuração de acesso e consulta na Cloudflare.', invalid_filters: 'Os filtros informados não são válidos. Ajuste a seleção e tente novamente.', analytics_unavailable: 'A consulta de telemetria está indisponível. Tente atualizar em instantes.', access_denied: 'Sua identidade não tem acesso ao painel.' };
      feedback('error', messages[data.error] || 'Não foi possível consultar a telemetria. Tente novamente.', data.error === 'access_denied');
      return;
    }
    if (!data.summary || !data.meta || !Array.isArray(data.events)) throw new Error('invalid_response');
    render(data);
    appliedFilters = new URLSearchParams(params);
    const hasData = numeric(data.summary.events) > 0;
    feedback('ready', hasData ? `Consulta concluída · ${count(data.summary.events)} eventos estimados no período.` : 'Nenhum evento para os filtros selecionados.');
  } catch (error) {
    if (requestId !== activeRequest) return;
    feedback('error', error.name === 'AbortError' ? 'A consulta demorou mais que o esperado. Tente atualizar.' : 'Não foi possível conectar ao painel. Tente atualizar.');
  } finally {
    clearTimeout(timeout);
    if (requestId === activeRequest) loading(false);
  }
}
function selectedFilters() {
  const params = new URLSearchParams();
  ['period', 'version', 'platform', 'database'].forEach(key => { if ($(key).value) params.set(key, $(key).value); });
  return params;
}
$('filters').addEventListener('submit', event => {
  event.preventDefault();
  void load(selectedFilters());
});
$('refresh').addEventListener('click', () => { void load(selectedFilters()); });
$('distribution').addEventListener('change', renderDistribution);
let resizeTimer;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (dashboardData) renderSeries(dashboardData.series); }, 120);
});
void load(appliedFilters);
