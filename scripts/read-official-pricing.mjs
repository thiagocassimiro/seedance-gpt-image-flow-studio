const response = await fetch('https://docs.byteplus.com/en/docs/modelark/model-pricing');
const html = await response.text();
const parts = [...html.matchAll(/\\"insert\\":\\"((?:\\.|[^"\\])*?)\\"/g)].map(match => JSON.parse(`"${match[1]}"`));
const text = parts.join('');
console.log(`HTTP_STATUS=${response.status}`);
for (const term of ['Without video input', 'With video input', 'No video input', 'Video input']) {
  const index = text.indexOf(term);
  console.log(`TERM=${term} INDEX=${index}`);
  if (index >= 0) console.log(text.slice(Math.max(0, index - 700), index + 1800));
}
