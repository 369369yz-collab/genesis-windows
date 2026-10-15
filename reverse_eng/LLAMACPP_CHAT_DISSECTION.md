# LLAMACPP_CHAT_DISSECTION — کالبدشکافی اتصال چت به مدل محلی

**قانون:** مهندسی معکوس قبل از ساخت (YZ, 2026-10-15).
**هدف:** چطور یک اپ production-grade چت کاربر را به مدل محلیِ روی دستگاه می‌رساند — بدون cloud.
**تاریخ:** 2026-10-15

## Prior Art ۱: llama.cpp server (binary دقیق داخل installer ما)

- ما `llama-server.exe` از release **b11583** (ggml-org/llama.cpp) را پین کرده‌ایم — بیلد Vulkan ویندوز.
- این server یک HTTP API دارد که مستقیم روی آن می‌خوابد:
  - `GET /health` → `{"status":"ok"}` (همین را الان برای boot-check استفاده می‌کنیم)
  - `POST /v1/chat/completions` → OpenAI-compatible chat completions
  - `POST /completion` → legacy raw completion
- Request (تطابق OpenAI):
  ```json
  { "model": "genesis-brain", "messages": [{"role":"system","content":"..."},{"role":"user","content":"..."}],
    "stream": false, "n_predict": 256, "temperature": 0.7 }
  ```
- Response:
  ```json
  { "choices": [{"message": {"role":"assistant","content":"..."}}], "usage": {...} }
  ```
- چرا این مسیر: (۱) این باینری را همین الان در boot spawn می‌کنیم — اضافه کردن client یعنی صفر dependency جدید؛ (۲) استاندارد OpenAI یعنی اگر فردا backend عوض شد، contract همان می‌ماند.

## Prior Art ۲: Ollama (الگوی مرجع صنعت)

- Ollama هم `/api/chat` (native) و هم `/v1/chat/completions` (OpenAI-compatible) سرو می‌کند — یعنی این contract به قرارداد دوfacto صنعت تبدیل شده.
- درس معماری از Ollama: server جداگانه (child process) + client HTTP روی localhost + health-check قبل از هر inference + خطای صریح وقتی model آماده نیست.

## تصمیم‌های طراحی GENESIS

| # | تصمیم | دلیل |
|---|-------|------|
| 1 | client سمت Rust (Tauri command) نه مستقیم از JS | کلید/پورت در JS قابل‌دسترس؛ Rust fail-closed می‌شود؛ JS فقط نتیجه/خطا را می‌بیند |
| 2 | `stream: false` در v1 | سادگی و قابلیت تست؛ streaming بعداً |
| 3 | خطای صریح فارسی وقتی `llama_running=false` | قانون صداقت — هرگز پاسخ جعلی به‌جای inference |
| 4 | timeout ۳۰۰s، cap 256 token، temp 0.7 | روی runner CPU کند است؛ timeout باید inference واقعی را پوشش بدهد |
| 5 | system prompt ثابت «GENESIS — دختر YZ» | هویت شخصیت در prompt، نه در کد پراکنده |
| 6 | no history در v1 | تک‌پیام + system؛ history در فاز بعدی (memory واقعی) |

## چه چیزی وارد build می‌شود

1. ماژول Rust جدید `chat.rs`: `#[tauri::command] async fn chat_send(prompt) -> Result<String,String>` — با ureq (همین dependency فعلی) POST به 127.0.0.1:8080.
2. ثبت در `invoke_handler`.
3. frontend `main.js`: `sendChat()` → `invoke('chat_send')`؛ حذف کامل پاسخ از پیش‌تعیین‌شده‌ی «حتماً پدر — دارم روش کار می‌کنم.»؛ خطاها به‌صورت حباب خطای صادقانه.
