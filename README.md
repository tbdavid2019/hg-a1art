# a1.art Gradio Webcam + API Proxy

這是一個 Gradio 應用，能用攝影機拍照或上傳圖片，呼叫 a1.art API 產生結果，並將每個使用者（含 Profile）歷史記錄儲存在本機。也額外提供 FastAPI 路由，讓其他應用可以直接呼叫同一流程。

## 安裝與啟動

```bash
cp .env.example .env   # 填入你的金鑰與 profiles
pip install -r requirements.txt
python app.py          # 啟動 uvicorn + Gradio
```

開啟 Gradio 網頁，允許攝影機，拍照或上傳圖片，選擇 Profile 後提交即可。

### Proxy API 金鑰（可選）

若要保護 `/api/generate`，在 `.env` 設定 `PROXY_API_KEY=你的值`，呼叫時在 header 帶 `X-API-KEY: 你的值`。預設空值不檢查，方便本機開發。

## Profiles（.env）

- 用 `A1_PROFILES` 列出 profile，例如：`A1_PROFILES=DEFAULT,ALT`
- 基礎預設值：
  - `A1_APP_ID`, `A1_API_KEY`, `A1_VERSION_ID`, `A1_CNET_ID`, `A1_CNET_PATH`
- 針對單一 profile（名稱需大寫）加上後綴覆蓋，例如 profile `ALT`：
  - `A1_APP_ID_ALT`, `A1_API_KEY_ALT`, `A1_VERSION_ID_ALT`, `A1_CNET_ID_ALT`, `A1_CNET_PATH_ALT`
- `A1_PROFILES` 中的第一個會成為 UI 與 API 的預設 profile。

---

Gradio app that captures a webcam photo, sends it to the a1.art API, polls for results, and keeps a per-user (per-profile) history on disk. Also exposes a FastAPI endpoint so other apps can trigger the same flow. The proxy follows the official flow: upload image to `/images/upload` to obtain `imageUrl`/`path`, then call `/images/generate` with those values.

## Setup

```bash
cp .env.example .env   # fill in your keys and profiles
pip install -r requirements.txt
python app.py          # starts uvicorn with Gradio mounted
```

Open the Gradio URL, allow webcam access, capture or upload an image, pick a profile, and submit.

### Proxy API key (optional)

To protect `/api/generate`, set `PROXY_API_KEY` in `.env` and send `X-API-KEY: <value>` with requests. Empty means no check (local dev).

## API endpoint for other apps

FastAPI is mounted at `/api/generate`.

Swagger UI: visit `/docs` (OpenAPI JSON at `/openapi.json`).

Request body:
```json
{
  "profile": "DEFAULT",          // optional, defaults to first profile
  "image_base64": "data:image/png;base64,...",  // required (or "image")
  "description": "optional prompt"              // sent as [{ "id": "description", "value": "..." }]
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

## a1.art 接通流程（附件說明）

1. 準備 API key：在 `.env` 的 profiles 填好 `A1_API_KEY`（或各 profile 的 `A1_API_KEY_<NAME>`）。本地 proxy 若有開 `PROXY_API_KEY`，額外在請求 header 帶 `X-API-KEY`。
2. 上傳圖片到 a1.art：proxy 會將 Gradio 上傳/拍攝的圖檔 POST 至 `https://a1.art/open-api/v1/a1/images/upload`，header 帶 `apiKey=<你的 a1.art key>`。成功回傳 `imageUrl` 與 `path`。
3. 呼叫生成：拿上一步的 `imageUrl`/`path`，組成 payload（含 `appId`、`versionId`、`cnet.id` 等 profile 參數，以及描述會轉成 `[{ "id": "description", "value": "<你的描述>" }]`），POST 至 `https://a1.art/open-api/v1/a1/images/generate`，同樣 header 帶 `apiKey=<你的 a1.art key>`。
4. 輪詢結果：proxy 會用回傳的 `taskId` GET `https://a1.art/open-api/v1/a1/tasks/{taskId}` 直到完成或逾時，並嘗試從 `data.images` / `data.result` / `data.imageUrl` 中取出圖片網址。
5. History：每個 Gradio session + profile 的輸入圖與結果 URL 會存到 `history/` 與 `history.json`，只保留在本地。
