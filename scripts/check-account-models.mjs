import fs from 'node:fs';
import path from 'node:path';

const key = process.env.ARK_API_KEY;
if (!key) {
  console.error('ARK_API_KEY_NOT_DEFINED');
  process.exit(2);
}
const targetIds = [
  'dreamina-seedance-2-0-mini-260615',
  'dreamina-seedance-2-0-fast-260128',
  'dreamina-seedance-2-5-260628',
];
const endpoint = 'https://ark.ap-southeast.bytepluses.com/api/v3/models';
const output = path.join(process.cwd(), 'projects', 'studio-selfcheck', 'reports', 'account-models.json');
const response = await fetch(endpoint, {
  headers: { Authorization: `Bearer ${key}` },
  signal: AbortSignal.timeout(60000),
});
const text = await response.text();
console.log(`HTTP_STATUS=${response.status}`);
if (!response.ok) {
  console.error(text.slice(0, 2000));
  process.exit(1);
}
const body = JSON.parse(text);
const found = new Map();
function visit(value) {
  if (Array.isArray(value)) {
    for (const item of value) visit(item);
    return;
  }
  if (!value || typeof value !== 'object') return;
  const id = value.id ?? value.model ?? value.model_id;
  if (targetIds.includes(id) && !found.has(id)) found.set(id, value);
  for (const item of Object.values(value)) visit(item);
}
visit(body);
const matches = targetIds.filter(id => found.has(id)).map(id => ({
  id,
  available_in_model_list: true,
  details: found.get(id),
}));
const report = {
  checked_at: new Date().toISOString(),
  endpoint,
  http_status: response.status,
  paid_task_created: false,
  matches,
};
fs.mkdirSync(path.dirname(output), { recursive: true });
fs.writeFileSync(output, JSON.stringify(report, null, 2) + '\n', 'utf8');
console.log(JSON.stringify({ matches, report: output }, null, 2));
if (!matches.some(item => item.id === targetIds[0])) process.exit(3);
