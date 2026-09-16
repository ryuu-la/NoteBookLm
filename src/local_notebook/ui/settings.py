from nicegui import ui

from .. import providers, storage as db
from .common import error_message


def settings_dialog():
    saved = db.settings()
    with ui.dialog() as dialog, ui.card().classes("modal-card settings-card"):
        with ui.row().classes("w-full items-center"):
            ui.icon("tune", size="24px")
            ui.label("Make yourself at home").classes("text-xl font-medium")
            ui.space()
            ui.button(icon="close", on_click=dialog.close).props("flat round dense")
        ui.label("Your models. Your keys. Your workspace.").classes("muted")
        provider = ui.select(["Gemini", "Local / compatible"], value=saved["provider"], label="Model provider").props("outlined").classes("w-full")
        key = ui.input("API key", password=True, password_toggle_button=True,
                       placeholder="Leave blank to keep your saved key").props("outlined").classes("w-full")
        remember = ui.checkbox("Remember key in this computer’s credential store", value=False)
        with ui.row().classes("w-full gap-3"):
            model = ui.input("Main model", value=saved["model"]).props("outlined").classes("flex-1")
            fast = ui.input("Fast model", value=saved["fast_model"]).props("outlined").classes("flex-1")
        endpoint = ui.input("Compatible API base URL", value=saved["endpoint"]).props("outlined").classes("w-full")
        endpoint.bind_visibility_from(provider, "value", backward=lambda value: value != "Gemini")
        thinking = ui.select(["minimal", "low", "medium", "high"], value=saved["thinking_level"],
                             label="Gemini Flash thinking effort").props("outlined").classes("w-full")
        ui.label("Minimal starts answers sooner. Higher effort takes longer for complex reasoning.").classes("text-xs muted")
        studio_fast = ui.switch("Use the fast model for Studio", value=saved["studio_fast"])
        ui.separator()
        ui.label("LOCAL RETRIEVAL").classes("eyebrow")
        semantic = ui.switch("Semantic + keyword search", value=saved["semantic"])
        ui.label("BGE small · local ONNX embeddings · no embedding API charges").classes("text-xs muted")
        rerank = ui.switch("Rerank passages for stronger relevance", value=saved["rerank"])
        candidates = ui.select({16: "Fast · 16 candidates", 40: "Broader search · 40 candidates"},
                               value=saved["rerank_candidates"], label="Reranking shortlist").props("outlined").classes("w-full")
        ui.label("MiniLM cross-encoder · adds local processing time").classes("text-xs muted")
        ui.label("Changing semantic search requires reindexing existing sources. Cloud models receive your question and retrieved passages. API fees depend on your provider.").classes("settings-hint")
        status = ui.label("").classes("text-sm muted")

        def save(close=True):
            try:
                if provider.value != "Gemini":
                    providers.validate_endpoint(endpoint.value)
                if not model.value.strip():
                    raise ValueError("Enter a model identifier.")
                if key.value.strip():
                    providers.set_key(provider.value, key.value, remember.value)
                db.save_settings({"provider": provider.value, "model": model.value.strip(),
                                  "fast_model": fast.value.strip(), "endpoint": endpoint.value.strip(),
                                  "semantic": semantic.value, "rerank": rerank.value,
                                  "thinking_level": thinking.value, "studio_fast": studio_fast.value,
                                  "rerank_candidates": candidates.value})
                if close:
                    dialog.close()
                    ui.notify("Settings saved on this computer", type="positive")
                return True
            except Exception as exc:
                error_message(exc)
                return False

        async def test():
            if not save(False):
                return
            status.set_text("Testing your model…")
            try:
                await providers.complete("Reply with OK only.", "Connection test")
                status.set_text("Connected. Your model is ready.")
            except Exception as exc:
                status.set_text("Connection failed. Check the provider, model identifier, and key.")
                error_message(exc)

        with ui.row().classes("w-full items-center justify-between"):
            ui.button("Test connection", icon="cable", on_click=test).props("flat")
            ui.button("Save settings", on_click=lambda: save()).classes("primary-btn")
    dialog.open()
