# a1.art Gradio Webcam + API Proxy

這是一個 Gradio 應用，能用攝影機拍照或上傳圖片，呼叫 a1.art API 產生結果，並將每個使用者（含 Profile）歷史記錄儲存在本機。也額外提供 FastAPI 路由，讓其他應用可以直接呼叫同一流程。

## 安裝與啟動

```bash
cp .env.example .env   # 填入你的金鑰與 profiles
pip install -r requirements.txt
python app.py          # 啟動 uvicorn + Gradio
```

開啟 Gradio 網頁，允許攝影機，拍照或上傳圖片，選擇 Profile 後提交即可。

## Profiles（.env）

- 用 `A1_PROFILES` 列出 profile，例如：`A1_PROFILES=DEFAULT,ALT`
- 基礎預設值：
  - `A1_APP_ID`, `A1_API_KEY`, `A1_VERSION_ID`, `A1_CNET_ID`, `A1_CNET_PATH`
- 針對單一 profile（名稱需大寫）加上後綴覆蓋，例如 profile `ALT`：
  - `A1_APP_ID_ALT`, `A1_API_KEY_ALT`, `A1_VERSION_ID_ALT`, `A1_CNET_ID_ALT`, `A1_CNET_PATH_ALT`
- `A1_PROFILES` 中的第一個會成為 UI 與 API 的預設 profile。

---

Gradio app that captures a webcam photo, sends it to the a1.art API, polls for results, and keeps a per-user (per-profile) history on disk. Also exposes a FastAPI endpoint so other apps can trigger the same flow.

## Setup

```bash
cp .env.example .env   # fill in your keys and profiles
pip install -r requirements.txt
python app.py          # starts uvicorn with Gradio mounted
```

Open the Gradio URL, allow webcam access, capture or upload an image, pick a profile, and submit.

## API endpoint for other apps

FastAPI is mounted at `/api/generate`.

Swagger UI: visit `/docs` (OpenAPI JSON at `/openapi.json`).

Request body:
```json
{
  "profile": "DEFAULT",          // optional, defaults to first profile
  "image_base64": "data:image/png;base64,...",  // required
  "description": "optional prompt"
}
```

Response:
```json
{
  "status": "任務 ...",
  "images": ["https://..."],  // may be empty if API returns no URLs
  "raw": { "code": 0, "data": {...} }  // full task polling payload
}
```

## Notes

- History is stored under `history.json` plus per-profile images under `history/`. Gradio sessions are separated by browser tab and profile.
- The code tries to extract image URLs from the task response; the raw JSON response is shown so you can adjust parsing if the API response shape differs.
