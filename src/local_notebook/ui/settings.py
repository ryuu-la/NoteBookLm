from nicegui import ui

from .. import providers, storage as db
from ..config import gemini_models
from .common import error_message


def settings_dialog():
    saved = db.settings()
    with ui.dialog() as dialog, ui.card().classes("modal-card settings-card"):
        with ui.row().classes("w-full items-center"):
            ui.icon("tune", size="24px")
            ui.label("Make yourself at home").classes("text-xl font-medium")
            ui.space()
            ui.button(icon="close", on_click=dialog.close).props('flat round dense aria-label="Close dialog"')
        ui.label("Your models. Your keys. Your workspace.").classes("muted")
        provider = ui.select(["Gemini", "Local / compatible"], value=saved["provider"], label="Model provider").props("outlined").classes("w-full")
        with ui.column().classes("w-full gap-2") as gemini_config:
            ui.label("Gemini is configured in the project .env file.").classes("text-sm")
            ui.label("API key configured" if providers.get_key("Gemini") else "API key missing: set GEMINI_API_KEY in .env").classes("text-sm muted")
            models = gemini_models()
            ui.label(f"Fast: {models['fast_model']}").classes("text-sm")
            ui.label(f"Main: {models['model']}").classes("text-sm")
            ui.label("Restart the server after editing .env. No automatic model switching.").classes("text-xs muted")
        gemini_config.bind_visibility_from(provider, 'value', backward=lambda value: value == 'Gemini')
        with ui.column().classes("w-full") as compatible_config:
            ui.label("Set NOTEBOOK_API_KEY in .env if your compatible endpoint needs authentication.").classes("text-xs muted")
            model = ui.input("Main model", value=saved["model"]).props("outlined").classes("w-full")
            fast = ui.input("Fast model", value=saved["fast_model"]).props("outlined").classes("w-full")
        compatible_config.bind_visibility_from(provider, 'value', backward=lambda value: value != 'Gemini')
        endpoint = ui.input("Compatible API base URL", value=saved["endpoint"]).props("outlined").classes("w-full")
        endpoint.bind_visibility_from(provider, "value", backward=lambda value: value != "Gemini")
        thinking = ui.select(["minimal", "low", "medium", "high"], value=saved["thinking_level"],
                             label="Main model thinking effort").props("outlined").classes("w-full")
        ui.label("Fast uses minimal thinking automatically. This setting applies to Main.").classes("text-xs muted")
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
                    if not model.value.strip() or not fast.value.strip():
                        raise ValueError("Enter main and fast model identifiers.")
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
            test_button.props("loading")
            test_button.disable()
            status.set_text("Testing your model…")
            try:
                await providers.complete("Reply with OK only.", "Connection test")
                status.set_text("Connected. Your model is ready.")
            except Exception as exc:
                status.set_text("Connection failed. Check the provider, model identifier, and key.")
                error_message(exc)
            finally:
                test_button.props(remove="loading")
                test_button.enable()

        with ui.row().classes("w-full items-center justify-between"):
            test_button = ui.button("Test connection", icon="cable", on_click=test).props("flat")
            ui.button("Save settings", on_click=lambda: save()).classes("primary-btn")
    dialog.open()
