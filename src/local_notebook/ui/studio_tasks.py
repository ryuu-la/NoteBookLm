"""Client-scoped minimized Studio dialogs; hiding is distinct from cancellation."""
from nicegui import ui


def task_dock():
    client = ui.context.client
    client.studio_task_dock = ui.column().classes('w-full gap-2')


class StudioWindow:
    def __init__(self, dialog, title, cancel=None):
        self.dialog, self.title, self.cancel = dialog, title, cancel
        self.client = ui.context.client
        self.minimized = False
        self.row = None
        self.status = 'Ready to continue'
        self.open_result = None
        dialog.on('hide', self.hidden)

    def button(self):
        ui.button(icon='minimize', on_click=self.minimize).props(
            'flat round dense aria-label="Minimize tool"').tooltip('Minimize to Studio · keep working')

    def minimize(self):
        self.minimized = True
        dock = getattr(self.client, 'studio_task_dock', None)
        if dock is None:
            # Also usable on pages that open an artifact without the Studio panel.
            with self.client.content:
                dock = ui.column().classes('fixed bottom-4 right-4 z-50')
            self.client.studio_task_dock = dock
        if self.row is None:
            with dock:
                with ui.card().classes('w-full gap-1 p-2') as self.row:
                    with ui.row().classes('w-full items-center no-wrap'):
                        ui.button(self.title, icon='open_in_full', on_click=self.restore).props(
                            f'flat dense aria-label="Restore {self.title.replace(chr(34), chr(39))}"').classes('flex-1')
                        ui.button(icon='close', on_click=self.stop).props(
                            'flat round dense aria-label="Cancel minimized tool"').tooltip('Cancel / dismiss')
                    self.label = ui.label(self.status).classes('text-xs muted')
        self.dialog.close()

    def update(self, text):
        self.status = text
        if self.row is not None:
            self.label.set_text(text)

    def clear(self):
        if self.row is not None:
            self.row.delete()
            self.row = None

    def restore(self):
        # The restore button lives in the row being removed. Build the result
        # under a stable client slot, not the deleted button's parent.
        with self.client.content:
            self.minimized = False
            self.clear()
            if self.open_result:
                self.open_result()
            else:
                self.dialog.open()

    def hidden(self):
        if not self.minimized:
            self.clear()
            if self.cancel:
                self.cancel()

    def stop(self):
        if self.cancel:
            self.cancel()
        self.clear()
        self.minimized = False

    def finish(self, open_result):
        self.open_result = open_result
        if self.minimized:
            self.update('Complete · click to open')
            ui.notify(f'{self.title} is ready in Studio.', type='positive')
        else:
            self.dialog.close()
            open_result()
