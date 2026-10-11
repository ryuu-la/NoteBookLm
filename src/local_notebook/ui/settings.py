import json

from nicegui import ui

from .. import providers, storage as db
from ..config import RUNINFRA_MODELS, gemini_models
from .common import error_message


def settings_dialog():
    saved = db.settings()
    compatible = {row['key']: json.loads(row['value']) for row in db.rows(
        "SELECT key,value FROM settings WHERE key IN ('model','fast_model','endpoint')")}
    with ui.dialog() as dialog, ui.card().classes("modal-card settings-card"):
        with ui.row().classes("w-full items-center"):
            ui.icon("tune", size="24px")
            ui.label("Make yourself at home").classes("text-xl font-medium")
            ui.space()
            ui.button(icon="close", on_click=dialog.close).props('flat round dense aria-label="Close dialog"')
        ui.label("Your models. Your keys. Your workspace.").classes("muted")
        provider = ui.select(["Gemini", "RunInfra", "Local / compatible"], value=saved["provider"], label="Model provider").props("outlined").classes("w-full")
        with ui.column().classes("w-full gap-2") as gemini_config:
            ui.label("Gemini is configured in the project .env file.").classes("text-sm")
            ui.label("API key configured" if providers.get_key("Gemini") else "API key missing: set GEMINI_API_KEY in .env").classes("text-sm muted")
            models = gemini_models()
            ui.label(f"Fast: {models['fast_model']}").classes("text-sm")
            ui.label(f"Main: {models['model']}").classes("text-sm")
            ui.label("Restart the server after editing .env. No automatic model switching.").classes("text-xs muted")
        gemini_config.bind_visibility_from(provider, 'value', backward=lambda value: value == 'Gemini')
        with ui.column().classes('w-full gap-2 provider-summary') as runinfra_config:
            ui.label('RunInfra').classes('text-base font-medium')
            ui.label('API key configured' if providers.get_key('RunInfra') else 'API key missing: set RUNINFRA_API_KEY in .env').classes('text-sm muted')
            runinfra_model = ui.select(RUNINFRA_MODELS, value=saved.get('runinfra_model', 'glm-5-3-flash'),
                                       label='RunInfra model').props('outlined').classes('w-full')
            ui.label('One model for chat and all Studio tools. Switch here or in the chat composer.').classes('text-sm')
            ui.label('https://api.runinfra.ai/v1').classes('text-xs muted')
            ui.label('Restart after editing .env, then test your connection below.').classes('text-xs muted')
        runinfra_config.bind_visibility_from(provider, 'value', backward=lambda value: value == 'RunInfra')
        with ui.column().classes("w-full") as compatible_config:
            ui.label("Set NOTEBOOK_API_KEY in .env if your compatible endpoint needs authentication.").classes("text-xs muted")
            model = ui.input("Main model", value=compatible.get("model", "")).props("outlined").classes("w-full")
            fast = ui.input("Fast model", value=compatible.get("fast_model", "")).props("outlined").classes("w-full")
        compatible_config.bind_visibility_from(provider, 'value', backward=lambda value: value == 'Local / compatible')
        endpoint = ui.input("Compatible API base URL", value=compatible.get("endpoint", "http://localhost:11434/v1")).props("outlined").classes("w-full")
        endpoint.bind_visibility_from(provider, "value", backward=lambda value: value == "Local / compatible")
        thinking = ui.select(["minimal", "low", "medium", "high"], value=saved["thinking_level"],
                             label="Main model thinking effort").props("outlined").classes("w-full")
        thinking.bind_visibility_from(provider, 'value', backward=lambda value: value == 'Gemini')
        ui.label("Fast uses minimal thinking automatically. This setting applies to Main.").classes("text-xs muted").bind_visibility_from(provider, 'value', backward=lambda value: value == 'Gemini')
        studio_fast = ui.switch("Use the fast model for Studio", value=saved["studio_fast"])
        studio_fast.bind_visibility_from(provider, 'value', backward=lambda value: value != 'RunInfra')
        ui.separator()
        ui.label("LOCAL RETRIEVAL").classes("eyebrow")
        semantic = ui.switch("Semantic + keyword search", value=saved["semantic"])
        ui.label("EmbeddingGemma 2 · local text search · no embedding API charges").classes("text-xs muted")
        ui.label("Your answer model receives the question and relevant document text. API fees depend on your provider.").classes("settings-hint")
        status = ui.label("").classes("text-sm muted")

        def save(close=True):
            try:
                values = {}
                if provider.value == 'RunInfra':
                    values['runinfra_model'] = runinfra_model.value
                if provider.value == "Local / compatible":
                    providers.validate_endpoint(endpoint.value)
                    if not model.value.strip() or not fast.value.strip():
                        raise ValueError("Enter main and fast model identifiers.")
                    values.update(model=model.value.strip(), fast_model=fast.value.strip(), endpoint=endpoint.value.strip())
                db.save_settings({"provider": provider.value, **values,
                                  "semantic": semantic.value,
                                  "thinking_level": thinking.value,
                                  **({'studio_fast': studio_fast.value} if provider.value != 'RunInfra' else {})})
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
