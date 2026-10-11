"""Concise, factual progress, never a model's private reasoning transcript."""
import time

from nicegui import ui


class RunProgress:
    def __init__(self):
        self.started = time.perf_counter()
        self.events = []
        self.expansion = ui.expansion('Working', icon='auto_awesome', value=False).classes('run-progress w-full')
        with self.expansion:
            self.detail = ui.column().classes('w-full gap-2')
        self.set_text('Starting your request')

    def reset(self):
        self.started = time.perf_counter()
        self.events.clear()
        self.detail.clear()
        self.expansion.visible = True
        self.expansion.set_value(False)
        self.set_text('Starting your request')

    def set_text(self, text):
        text = str(text)[:180]
        self.expansion.set_text(text)
        if text not in self.events:
            self.events.append(text)
            if len(self.events) <= 16:
                with self.detail:
                    ui.label(text).classes('text-xs muted')

    def finish(self, text='Writing your answer'):
        self.set_text(text)

    def snapshot(self):
        return {'seconds': round(time.perf_counter() - self.started, 1), 'steps': self.events[:16]}


def saved_progress(record):
    import json
    if not record:
        return
    data = json.loads(record['content'])
    with ui.expansion(f"Completed in {data['seconds']:g}s", icon='check', value=False).classes('run-progress w-full'):
        for text in data['steps']:
            ui.label(text).classes('text-xs muted')
