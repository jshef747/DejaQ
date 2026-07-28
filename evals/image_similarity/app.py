"""Two-photo similarity comparer.

Run from server/ (reuses its venv):
    uv run python ../evals/image_similarity/app.py
Then open http://127.0.0.1:8010
"""
from __future__ import annotations

import base64
import io

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from PIL import Image
from pydantic import BaseModel

from clip_embed import cosine_distance, embed_images

app = FastAPI()


class CompareRequest(BaseModel):
    a: str  # base64-encoded image bytes
    b: str

INDEX_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Image Similarity Comparer</title>
<style>
  body { font-family: -apple-system, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; }
  h1 { font-size: 20px; }
  .drops { display: flex; gap: 20px; }
  .drop {
    flex: 1; height: 260px; border: 2px dashed #999; border-radius: 8px;
    display: flex; align-items: center; justify-content: center; position: relative;
    cursor: pointer; overflow: hidden; background: #fafafa;
  }
  .drop.over { border-color: #333; background: #f0f0f0; }
  .drop img { max-width: 100%; max-height: 100%; object-fit: contain; }
  .drop span { color: #888; }
  .drop input { display: none; }
  #result { margin-top: 24px; font-size: 16px; }
  #distance { font-size: 32px; font-weight: bold; }
  .bar { height: 24px; background: #eee; border-radius: 4px; position: relative; margin-top: 8px; }
  .bar .fill { height: 100%; border-radius: 4px; background: #4a90d9; }
  .marks { position: relative; height: 20px; margin-top: 2px; font-size: 11px; color: #666; }
  .marks span { position: absolute; transform: translateX(-50%); }
  #status { color: #888; margin-top: 10px; }
</style>
</head>
<body>
<h1>Image Similarity Comparer (CLIP ViT-B/32)</h1>
<p>Drop, paste, or click to pick two images. Comparison runs automatically once both are set.</p>
<div class="drops">
  <div class="drop" id="drop0"><span>Image A</span><input type="file" id="file0" accept="image/*"></div>
  <div class="drop" id="drop1"><span>Image B</span><input type="file" id="file1" accept="image/*"></div>
</div>
<div id="status"></div>
<div id="result" style="display:none">
  <div>Cosine distance: <span id="distance"></span></div>
  <div>Similarity: <span id="similarity"></span></div>
  <div class="bar"><div class="fill" id="fill"></div></div>
  <div class="marks">
    <span style="left:12.5%">0.05</span>
    <span style="left:25%">0.10</span>
    <span style="left:37.5%">0.15</span>
    <span style="left:50%">0.20</span>
  </div>
  <p id="verdict"></p>
</div>
<script>
const files = [null, null];

function setupDrop(i) {
  const drop = document.getElementById('drop' + i);
  const input = document.getElementById('file' + i);
  drop.onclick = () => input.click();
  input.onchange = () => { if (input.files[0]) setFile(i, input.files[0]); };
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add('over'); };
  drop.ondragleave = () => drop.classList.remove('over');
  drop.ondrop = (e) => {
    e.preventDefault(); drop.classList.remove('over');
    if (e.dataTransfer.files[0]) setFile(i, e.dataTransfer.files[0]);
  };
}

function setFile(i, file) {
  files[i] = file;
  const drop = document.getElementById('drop' + i);
  drop.innerHTML = '';
  const img = document.createElement('img');
  img.src = URL.createObjectURL(file);
  drop.appendChild(img);
  if (files[0] && files[1]) compare();
}

document.addEventListener('paste', (e) => {
  for (const item of e.clipboardData.items) {
    if (item.type.startsWith('image/')) {
      const slot = files[0] ? 1 : 0;
      setFile(slot, item.getAsFile());
    }
  }
});

setupDrop(0);
setupDrop(1);

function readAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(',')[1]);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

async function compare() {
  document.getElementById('status').textContent = 'Embedding...';
  document.getElementById('result').style.display = 'none';
  const [a, b] = await Promise.all([readAsBase64(files[0]), readAsBase64(files[1])]);
  const res = await fetch('/compare', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ a, b }),
  });
  const data = await res.json();
  document.getElementById('status').textContent = '';
  document.getElementById('distance').textContent = data.distance.toFixed(4);
  document.getElementById('similarity').textContent = (data.similarity * 100).toFixed(1) + '%';
  const pct = Math.min(data.distance / 0.40, 1) * 100;
  document.getElementById('fill').style.width = pct + '%';
  let verdict;
  if (data.distance <= 0.05) verdict = 'Very likely the same image (re-encoded/resized).';
  else if (data.distance <= 0.10) verdict = 'Near-duplicate (planned cache-gate default: 0.10).';
  else if (data.distance <= 0.20) verdict = 'Similar but noticeably different.';
  else verdict = 'Different image/content.';
  document.getElementById('verdict').textContent = verdict;
  document.getElementById('result').style.display = 'block';
}
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return INDEX_HTML


@app.post("/compare")
async def compare(req: CompareRequest) -> dict:
    img_a = Image.open(io.BytesIO(base64.b64decode(req.a))).convert("RGB")
    img_b = Image.open(io.BytesIO(base64.b64decode(req.b))).convert("RGB")
    vecs = embed_images([img_a, img_b])
    dist = cosine_distance(vecs[0], vecs[1])
    return {"distance": dist, "similarity": 1.0 - dist}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8010)
