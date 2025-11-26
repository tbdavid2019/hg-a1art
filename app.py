import base64
import io
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import gradio as gr
import requests
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field
from PIL import Image

load_dotenv()

# Default credentials provided by the user. Overridden by .env profiles and the UI fields.
DEFAULT_APP_ID = "1993493056371286017"
DEFAULT_API_KEY = "e89eaf5c77ba4f98906a27f761b1ba9d"
DEFAULT_VERSION_ID = "1993493056375480321"
DEFAULT_CNET_ID = "17641207566093602"
DEFAULT_CNET_PATH = "/assets/application/app_1993493056371286017/form/"

HISTORY_FILE = Path("history.json")
HISTORY_DIR = Path("history")
POLL_INTERVAL = 3
POLL_TIMEOUT = 45

UPLOAD_URL = "https://a1.art/open-api/v1/a1/images/upload"
GENERATE_URL = "https://a1.art/open-api/v1/a1/images/generate"


def decode_base64_image(data_str: str) -> Image.Image:
    """Accept a data URL or raw base64 string and return a PIL image."""
    _, _, payload = data_str.partition(",")
    raw_b64 = payload or data_str
    return Image.open(io.BytesIO(base64.b64decode(raw_b64)))


def upload_image(image: Image.Image, api_key: str) -> Tuple[Dict, str]:
    """
    Upload image to a1.art to obtain imageUrl/path usable in generation payload.
    Returns (data, error); error is None on success.
    """
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    files = {"file": ("upload.png", buffer, "image/png")}

    try:
        raw = requests.post(
            UPLOAD_URL,
            headers={"apiKey": api_key},
            data={},
            files=files,
            timeout=60,
        )
    except Exception as exc:  # pragma: no cover - network failure path
        return {}, f"圖片上傳失敗: {exc}"

    try:
        payload = raw.json()
    except Exception:
        return {}, f"圖片上傳回應非 JSON：{raw.text}"

    if payload.get("code") != 0 or "data" not in payload:
        return {}, f"圖片上傳失敗: {payload}"

    data = payload.get("data") or {}
    image_url = data.get("imageUrl")
    path = data.get("path")
    if not image_url or not path:
        return {}, f"上傳回應缺少 imageUrl/path: {payload}"

    return {"imageUrl": image_url, "path": path}, None


def load_history_store() -> Dict[str, List[Dict]]:
    if not HISTORY_FILE.exists():
        return {}
    try:
        return json.loads(HISTORY_FILE.read_text())
    except json.JSONDecodeError:
        return {}


def save_history_store(store: Dict[str, List[Dict]]) -> None:
    HISTORY_FILE.write_text(json.dumps(store, ensure_ascii=False, indent=2))


def get_session_id(request: gr.Request) -> str:
    # Gradio generates a unique session hash per connected client.
    return getattr(request, "session_hash", "anonymous")


def ensure_history_dir(user_id: str) -> Path:
    user_dir = HISTORY_DIR / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def persist_entry(user_id: str, entry: Dict) -> None:
    store = load_history_store()
    store.setdefault(user_id, [])
    store[user_id].insert(0, entry)
    save_history_store(store)


def build_history_table(entries: List[Dict]) -> List[List[str]]:
    table = []
    for item in entries:
        time_str = item.get("timestamp", "")
        task_id = item.get("task_id", "")
        input_img = item.get("input_image", "")
        result_urls = item.get("result_images", [])
        status = item.get("status", "")
        table.append(
            [
                time_str,
                task_id,
                status,
                "\n".join(result_urls) if result_urls else "",
                input_img,
            ]
        )
    return table


def env_or_default(key: str, default: str) -> str:
    value = os.getenv(key)
    return value if value else default


def load_profiles_from_env() -> Tuple[List[str], Dict[str, Dict[str, str]]]:
    profile_names = [
        p.strip() for p in os.getenv("A1_PROFILES", "").split(",") if p.strip()
    ]
    if not profile_names:
        profile_names = ["DEFAULT"]

    profiles: Dict[str, Dict[str, str]] = {}
    base = {
        "appId": env_or_default("A1_APP_ID", DEFAULT_APP_ID),
        "apiKey": env_or_default("A1_API_KEY", DEFAULT_API_KEY),
        "versionId": env_or_default("A1_VERSION_ID", DEFAULT_VERSION_ID),
        "cnetId": env_or_default("A1_CNET_ID", DEFAULT_CNET_ID),
        "cnetPath": env_or_default("A1_CNET_PATH", DEFAULT_CNET_PATH),
    }

    for name in profile_names:
        suffix = name.upper()
        profiles[name] = {
            "appId": env_or_default(f"A1_APP_ID_{suffix}", base["appId"]),
            "apiKey": env_or_default(f"A1_API_KEY_{suffix}", base["apiKey"]),
            "versionId": env_or_default(f"A1_VERSION_ID_{suffix}", base["versionId"]),
            "cnetId": env_or_default(f"A1_CNET_ID_{suffix}", base["cnetId"]),
            "cnetPath": env_or_default(f"A1_CNET_PATH_{suffix}", base["cnetPath"]),
        }

    return profile_names, profiles


PROFILE_NAMES, PROFILE_MAP = load_profiles_from_env()
DEFAULT_PROFILE = PROFILE_NAMES[0] if PROFILE_NAMES else "DEFAULT"
PROXY_API_KEY = os.getenv("PROXY_API_KEY")


def poll_task(task_id: str, api_key: str) -> Tuple[Dict, List[str]]:
    """Poll the task endpoint until completion or timeout."""
    deadline = time.time() + POLL_TIMEOUT
    result_images: List[str] = []
    last_payload: Dict = {}

    while time.time() < deadline:
        response = requests.get(
            f"https://a1.art/open-api/v1/a1/tasks/{task_id}",
            headers={"apiKey": api_key},
            timeout=30,
        )
        try:
            last_payload = response.json()
        except Exception:
            last_payload = {"data": response.text}

        if not isinstance(last_payload, dict):
            last_payload = {"data": last_payload}

        data = last_payload.get("data", {})

        images: List[str] = []
        if isinstance(data, dict):
            candidate = data.get("images") or data.get("result")
            if isinstance(candidate, list):
                for item in candidate:
                    if isinstance(item, dict):
                        images.append(item.get("imageUrl", "") or item.get("url", ""))
                    elif isinstance(item, str):
                        images.append(item)
            elif isinstance(data.get("imageUrl"), str):
                images.append(data.get("imageUrl"))
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    images.append(item.get("imageUrl", "") or item.get("url", ""))
                elif isinstance(item, str):
                    images.append(item)
        elif isinstance(data, str):
            images.append(data)

        if images:
            result_images = [url for url in images if url]

        status = ""
        if isinstance(data, dict):
            status = data.get("status", "")
        if status and status.lower() in {"success", "finished", "done"}:
            break

        time.sleep(POLL_INTERVAL)

    return last_payload, result_images


def submit_generation(
    image,
    description,
    app_id,
    api_key,
    version_id,
    cnet_id,
    cnet_path,
    user_id: str,
):
    if image is None:
        return "請先拍照或上傳圖片。", None, {}, []

    user_dir = ensure_history_dir(user_id)
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")
    image_path = user_dir / f"{timestamp.replace(':', '-')}.png"
    image.save(image_path)

    effective_api_key = api_key or DEFAULT_API_KEY
    upload_result, upload_error = upload_image(image, effective_api_key)
    if upload_error:
        return upload_error, None, {}, []

    upload_image_url = upload_result.get("imageUrl")
    upload_path = upload_result.get("path")
    used_cnet_path = upload_path or cnet_path or DEFAULT_CNET_PATH

    description_payload = (
        [{"id": "description", "value": description}] if description else []
    )

    payload = {
        "appId": app_id or DEFAULT_APP_ID,
        "versionId": version_id or DEFAULT_VERSION_ID,
        "cnet": [
            {
                "id": cnet_id or DEFAULT_CNET_ID,
                "imageUrl": upload_image_url,
                "path": used_cnet_path,
            }
        ],
        "description": description_payload,
        "generateNum": 1,
    }

    try:
        raw = requests.post(
            GENERATE_URL,
            headers={"apiKey": effective_api_key},
            json=payload,
            timeout=30,
        )
        task = raw.json()
    except Exception as exc:  # pragma: no cover - network failure path
        return f"API 呼叫失敗: {exc}", None, {}, []

    if task.get("code") != 0 or "data" not in task:
        return f"建立任務失敗: {task}", None, task, []

    task_id = task["data"].get("taskId")
    if not task_id:
        return f"未取得 taskId，回應: {task}", None, task, []

    last_payload, images = poll_task(task_id, api_key or DEFAULT_API_KEY)

    entry = {
        "timestamp": timestamp,
        "task_id": task_id,
        "status": last_payload.get("data", {}).get("status", "unknown"),
        "input_image": str(image_path),
        "result_images": images,
    }
    persist_entry(user_id, entry)

    history_table = build_history_table(load_history_store().get(user_id, []))
    status_text = f"任務 {task_id} 已送出並輪詢完成。" if images else f"任務 {task_id} 已送出，請檢查回傳資料。"
    return status_text, images or None, last_payload, history_table


def get_profile_values(profile_name: str) -> Dict[str, str]:
    return PROFILE_MAP.get(profile_name, PROFILE_MAP.get(DEFAULT_PROFILE, {}))


def switch_profile(profile_name: str, profiles: Dict[str, Dict[str, str]], user_id: str):
    profile = profiles.get(profile_name) or get_profile_values(DEFAULT_PROFILE)
    history_entries = (
        load_history_store().get(f"{user_id}:{profile_name}", []) if user_id else []
    )
    history_table = build_history_table(history_entries)
    return (
        profile.get("appId", DEFAULT_APP_ID),
        profile.get("apiKey", DEFAULT_API_KEY),
        profile.get("versionId", DEFAULT_VERSION_ID),
        profile.get("cnetId", DEFAULT_CNET_ID),
        profile.get("cnetPath", DEFAULT_CNET_PATH),
        history_table,
    )


def generate_image(
    profile_name,
    image,
    description,
    app_id,
    api_key,
    version_id,
    cnet_id,
    cnet_path,
    user_id,
    request: gr.Request,
):
    user_id = (user_id or get_session_id(request)) + f":{profile_name}"
    return submit_generation(
        image,
        description,
        app_id,
        api_key,
        version_id,
        cnet_id,
        cnet_path,
        user_id,
    )


def init_session(request: gr.Request):
    user_id = get_session_id(request)
    history_entries = load_history_store().get(f"{user_id}:{DEFAULT_PROFILE}", [])
    history_table = build_history_table(history_entries)
    first_profile = get_profile_values(DEFAULT_PROFILE)
    return (
        user_id,
        history_table,
        first_profile.get("appId", DEFAULT_APP_ID),
        first_profile.get("apiKey", DEFAULT_API_KEY),
        first_profile.get("versionId", DEFAULT_VERSION_ID),
        first_profile.get("cnetId", DEFAULT_CNET_ID),
        first_profile.get("cnetPath", DEFAULT_CNET_PATH),
    )


with gr.Blocks(title="a1.art Webcam Generator") as demo:
    gr.Markdown(
        "# a1.art Webcam Generator\n"
        "- Docs (Swagger): `/docs` | OpenAPI JSON: `/openapi.json`\n"
        "拍照或上傳圖片，提交至 a1.art API，並為每個使用者保留本地歷史。\n\n"
        "- 金鑰與設定來源：.env 內的 profile，或於 UI 中調整\n"
        "- 下方 API 設定會隨 Profile 選擇更新，仍可手動修改"
    )

    user_id_state = gr.State()
    profile_state = gr.State(PROFILE_MAP)

    with gr.Row():
        with gr.Column():
            profile_dropdown = gr.Dropdown(
                label="Profile (.env)",
                choices=PROFILE_NAMES,
                value=DEFAULT_PROFILE,
            )
            image_input = gr.Image(
                label="拍照或上傳",
                sources=["webcam", "upload"],
                type="pil",
                height=320,
            )
            description_input = gr.Textbox(label="描述 (可選)", placeholder="描述希望生成的效果")
            with gr.Accordion("API 設定", open=False):
                app_id_input = gr.Textbox(label="appId", value=DEFAULT_APP_ID)
                api_key_input = gr.Textbox(label="apiKey", value=DEFAULT_API_KEY, type="password")
                version_id_input = gr.Textbox(label="versionId", value=DEFAULT_VERSION_ID)
                cnet_id_input = gr.Textbox(label="cnet id", value=DEFAULT_CNET_ID)
                cnet_path_input = gr.Textbox(label="cnet path", value=DEFAULT_CNET_PATH)
            submit_btn = gr.Button("提交")

        with gr.Column():
            status_output = gr.Textbox(label="狀態", interactive=False)
            gallery_output = gr.Gallery(label="生成結果", show_label=True)
            json_output = gr.JSON(label="原始回應")

    gr.Markdown("## 歷史 (僅儲存在本機伺服器)")
    history_table_output = gr.Dataframe(
        headers=["時間 (UTC)", "taskId", "狀態", "結果 URLs", "輸入圖片路徑"],
        datatype=["str", "str", "str", "str", "str"],
        interactive=False,
        wrap=True,
    )

    profile_dropdown.change(
        switch_profile,
        inputs=[profile_dropdown, profile_state, user_id_state],
        outputs=[
            app_id_input,
            api_key_input,
            version_id_input,
            cnet_id_input,
            cnet_path_input,
            history_table_output,
        ],
    )

    submit_btn.click(
        generate_image,
        inputs=[
            profile_dropdown,
            image_input,
            description_input,
            app_id_input,
            api_key_input,
            version_id_input,
            cnet_id_input,
            cnet_path_input,
            user_id_state,
        ],
        outputs=[status_output, gallery_output, json_output, history_table_output],
    )

    demo.load(
        init_session,
        inputs=None,
        outputs=[
            user_id_state,
            history_table_output,
            app_id_input,
            api_key_input,
            version_id_input,
            cnet_id_input,
            cnet_path_input,
        ],
    )


fastapi_app = FastAPI(
    title="a1.art proxy",
    description=(
        "Proxy API for a1.art image generation. Flow: upload image to a1.art, then call /images/generate with the returned imageUrl/path. "
        "Swagger UI at /docs, OpenAPI JSON at /openapi.json."
    ),
    version="1.0.0",
)


def require_proxy_key(x_api_key: str | None = Header(default=None, convert_underscores=False)):
    if PROXY_API_KEY and x_api_key != PROXY_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-KEY",
        )


class GenerateRequest(BaseModel):
    profile: str | None = Field(
        None,
        description="Profile name from .env (A1_PROFILES). Defaults to the first profile.",
    )
    image_base64: str | None = Field(
        None,
        description="Image as data URL or raw base64 string. Required unless image is provided.",
    )
    image: str | None = Field(
        None, description="Alias for image_base64 (data URL or raw base64 string)."
    )
    description: str | None = Field(
        None,
        description='Optional description. Sent as [{"id": "description", "value": <text>}].',
    )


class GenerateResponse(BaseModel):
    status: str
    images: List[str]
    raw: Dict


@fastapi_app.post(
    "/api/generate",
    response_model=GenerateResponse,
    summary="Upload image then generate via a1.art",
    tags=["a1.art"],
)
def api_generate(payload: GenerateRequest, _auth=Depends(require_proxy_key)):
    profile_name = payload.profile or DEFAULT_PROFILE
    profile = get_profile_values(profile_name)
    if not profile:
        raise HTTPException(status_code=400, detail=f"Unknown profile: {profile_name}")

    image_data = payload.image_base64 or payload.image
    description = payload.description or ""
    if not image_data:
        raise HTTPException(status_code=400, detail="image_base64 is required")

    try:
        image = decode_base64_image(image_data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image_base64: {exc}") from exc

    status_text, images, raw_payload, _ = submit_generation(
        image,
        description,
        profile.get("appId"),
        profile.get("apiKey"),
        profile.get("versionId"),
        profile.get("cnetId"),
        profile.get("cnetPath"),
        user_id=f"api-{profile_name}",
    )
    return GenerateResponse(status=status_text, images=images or [], raw=raw_payload)


app = gr.mount_gradio_app(fastapi_app, demo, path="/")


if __name__ == "__main__":
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=7860)
