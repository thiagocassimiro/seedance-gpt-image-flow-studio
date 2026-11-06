const response = await fetch('https://docs.byteplus.com/en/docs/modelark/model-pricing');
const html = await response.text();
const parts = [...html.matchAll(/\\"insert\\":\\"((?:\\.|[^"\\])*?)\\"/g)].map(match => JSON.parse(`"${match[1]}"`));
const matches = parts.map((value, index) => ({ value, index })).filter(item => item.value.includes('Mini'));
console.log(`MATCHES=${JSON.stringify(matches.slice(0, 20))}`);
const exact = parts.map((value, index) => ({ value, index })).find(item => item.value.includes('Dreamina Seedance 2.0 Mini'));
const index = exact ? exact.index : -1;
console.log(`INDEX=${index}`);
if (index >= 0) console.log(parts.slice(Math.max(0, index - 140), index + 12).map((value, offset) => `${Math.max(0, index - 140) + offset}: ${JSON.stringify(value)}`).join('\n'));
