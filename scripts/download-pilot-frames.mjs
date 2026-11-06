import fs from 'node:fs';
import path from 'node:path';

const assets = [
  ['https://ark-doc.tos-ap-southeast-1.bytepluses.com/doc_image/r2v_tea_pic1.jpg', 'projects/studio-selfcheck/frames/SHOT-001/first-v1.jpg'],
  ['https://ark-doc.tos-ap-southeast-1.bytepluses.com/doc_image/r2v_tea_pic2.jpg', 'projects/studio-selfcheck/frames/SHOT-001/last-v1.jpg'],
];
for (const [url, destination] of assets) {
  if (fs.existsSync(destination)) throw new Error(`Refusing to overwrite ${destination}`);
  const response = await fetch(url, { signal: AbortSignal.timeout(60000) });
  if (!response.ok) throw new Error(`HTTP ${response.status} for ${url}`);
  const bytes = Buffer.from(await response.arrayBuffer());
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.writeFileSync(destination, bytes, { flag: 'wx' });
  console.log(`${destination} ${bytes.length}`);
}
