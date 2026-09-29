"""The same result renderer is used in Studio and persisted chat messages."""
from nicegui import run, ui

from ..chat import citation_target
from ..data_tools import spreadsheet_bytes, suggested_chart
from .common import error_message


def data_view(data, kind='analytics'):
    with ui.column().classes('w-full gap-3'):
        ui.label(data['title']).classes('text-lg font-medium')
        ui.label(data.get('coverage', '')).classes('text-xs muted')
        chart = data.get('chart') or (suggested_chart(data) if kind == 'analytics' else None)
        if chart and kind == 'analytics':
            palette = ['#6c9fe8', '#8dc9b6', '#dfae6b', '#c3a0df', '#e88b9a', '#6bc9d8']
            series = {'type': chart['type'], 'name': chart['unit'] or chart['y']}
            options = {'animation': True, 'animationDuration': 500, 'animationEasing': 'cubicOut',
                       'color': palette, 'textStyle': {'color': '#8996a8'},
                       'tooltip': {'trigger': 'item' if chart['type'] == 'pie' else 'axis',
                                   'renderMode': 'richText', 'backgroundColor': '#1e2530',
                                   'borderColor': '#3a4252', 'textStyle': {'color': '#e1e6f0'},
                                   'axisPointer': {'type': 'shadow', 'shadowStyle': {'color': '#ffffff0d'}}},
                       'toolbox': {'feature': {'saveAsImage': {}}},
                       'aria': {'enabled': True}, 'series': [series]}
            if chart['type'] == 'pie':
                series.update(data=[{'name': label, 'value': value} for label, value in zip(chart['labels'], chart['values'])],
                              radius=['30%', '68%'], itemStyle={'borderRadius': 6, 'borderColor': '#141922', 'borderWidth': 2},
                              label={'color': '#c4cedd', 'fontSize': 12}, labelLine={'lineStyle': {'color': '#4a5568'}},
                              emphasis={'itemStyle': {'shadowBlur': 12, 'shadowColor': '#0006'}})
            else:
                series['data'] = chart['values']
                series['itemStyle'] = {'borderRadius': [8, 8, 0, 0] if not chart.get('horizontal') else [0, 8, 8, 0],
                                        'color': {'type': 'linear', 'x': 0, 'y': 0, 'x2': 0, 'y2': 1,
                                                  'colorStops': [{'offset': 0, 'color': '#6c9fe8'}, {'offset': 1, 'color': '#4d7bc4'}]}}
                series['emphasis'] = {'itemStyle': {'color': {'type': 'linear', 'x': 0, 'y': 0, 'x2': 0, 'y2': 1,
                                                               'colorStops': [{'offset': 0, 'color': '#82b3f5'}, {'offset': 1, 'color': '#5c8ed6'}]}}}
                series['label'] = {'show': len(chart['labels']) <= 10, 'position': 'top', 'color': '#c4cedd', 'fontSize': 11}
                options.update(xAxis={'type': 'category', 'data': chart['labels'], 'axisLabel': {'rotate': 25, 'color': '#8996a8'},
                                       'axisLine': {'lineStyle': {'color': '#3a4252'}}, 'axisTick': {'show': False}},
                               yAxis={'type': 'value', 'name': chart['unit'] or chart['y'],
                                      'axisLabel': {'color': '#8996a8'}, 'nameTextStyle': {'color': '#8996a8'},
                                      'axisLine': {'show': False}, 'axisTick': {'show': False},
                                      'splitLine': {'lineStyle': {'color': '#8996a833', 'type': 'dashed'}}},
                               grid={'containLabel': True, 'left': 20, 'right': 25, 'bottom': 55, 'top': 36})
                if len(chart['labels']) > 15:
                    options['dataZoom'] = [{'type': 'slider'}]
                if chart.get('horizontal'):
                    options['xAxis'], options['yAxis'] = options['yAxis'], options['xAxis']
                    options['yAxis']['inverse'] = True
                    options['yAxis']['axisLabel'].update(rotate=0, width=150, overflow='truncate')
                    if len(chart['labels']) > 15:
                        options['dataZoom'] = [{'type': 'slider', 'yAxisIndex': 0, 'start': 0, 'end': 100 * 15 / len(chart['labels'])}]
                    series['label'] = {'show': True, 'position': 'right', 'color': '#c4cedd', 'fontSize': 11}
                    series['itemStyle']['color'] = {'type': 'linear', 'x': 0, 'y': 0, 'x2': 1, 'y2': 0,
                                                     'colorStops': [{'offset': 0, 'color': '#4d7bc4'}, {'offset': 1, 'color': '#6c9fe8'}]}
            height = max(340, min(650, len(chart['labels']) * 36 + 90)) if chart.get('horizontal') else 360
            with ui.card().classes('w-full chart-card'):
                ui.echart(options, renderer='svg').classes('w-full').style(f'height: {height}px')
            if chart.get('note'):
                ui.label(chart['note']).classes('text-xs muted')
        columns = [{'name': f'c{i}', 'field': f'c{i}', 'label': col, 'align': 'left', 'sortable': True}
                   for i, col in enumerate(data['columns'])]
        rows = [{'_row': index, **{f'c{i}': value for i, value in enumerate(row)}}
                for index, row in enumerate(data['rows'][:500])]
        if chart and kind == 'analytics':
            with ui.expansion('View data', icon='table_view').classes('w-full'):
                ui.table(columns=columns, rows=rows, row_key='_row', pagination=10).classes('w-full').style('max-width: 100%; overflow-x: auto')
        else:
            ui.table(columns=columns, rows=rows, row_key='_row', pagination=10).classes('w-full').style('max-width: 100%; overflow-x: auto')
        if len(data['rows']) > 500:
            ui.label(f"Preview: first 500 of {len(data['rows']):,} rows. Downloads include every row.").classes('text-xs muted')
        async def download(extension):
            try:
                content = await run.io_bound(spreadsheet_bytes, data, extension)
                ui.download.content(content, f'data.{extension}',
                                    'text/csv' if extension == 'csv' else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            except Exception as exc:
                error_message(exc)
        with ui.row():
            ui.button('Download Excel', icon='download', on_click=lambda: download('xlsx')).props('flat')
            ui.button('CSV', on_click=lambda: download('csv')).props('flat')
        if data.get('statistics'):
            with ui.expansion('Calculated summaries', icon='functions').classes('w-full'):
                for column, stats in data['statistics'].items():
                    ui.label(f"{column}: " + ' · '.join(f'{key} {value:,.4g}' for key, value in stats.items())).classes('text-sm')
        if data.get('citations'):
            with ui.expansion('Data sources', icon='fact_check').classes('w-full'):
                for citation in data['citations']:
                    ui.link(f"[{citation.get('number', '')}] {citation['name']} · {citation['locator']}",
                            citation_target(citation), new_tab=True).classes('text-xs')


def mindmap_preview(data):
    """A small clickable card; the full draggable/zoomable map opens in a dialog."""
    import json
    from .artifacts import artifact_view

    def count_nodes(node):
        return 1 + sum(count_nodes(child) for child in node.get('children', []))
    topics = count_nodes(data['root'])
    artifact = {'kind': 'mindmap', 'title': data['title'],
                'content': json.dumps(data), 'citations': json.dumps(data.get('citations', []))}

    def open_map():
        artifact_view(artifact)
    with ui.card().classes('w-full mindmap-preview-card').props('role=button tabindex=0 aria-label="Open mind map"').on(
            'click', open_map).on('keydown.enter', open_map).on('keydown.space.prevent', open_map):
        with ui.row().classes('w-full items-center no-wrap'):
            ui.icon('hub').classes('mindmap-preview-icon')
            with ui.column().classes('gap-0 mindmap-preview-text'):
                ui.label(data['title']).classes('mindmap-preview-title')
                ui.label(f'{topics} topics · Click to explore').classes('mindmap-preview-sub')
            ui.space()
            ui.icon('open_in_full').classes('mindmap-preview-expand')


def message_results(message_id, text=None, render_text=None):
    import json
    from .. import storage as db
    saved = db.one('SELECT content FROM message_blocks WHERE message_id=?', (message_id,))
    if not saved:
        if text is not None:
            render_text(text)
        return
    blocks = json.loads(saved['content'])
    def render(block):
        if block['kind'] in {'analytics', 'spreadsheet'}:
            data_view(block['data'], block['kind'])
        elif block['kind'] == 'mindmap':
            mindmap_preview(block['data'])
        elif block['kind'] == 'text':
            ui.label(block['text']).classes('text-sm muted')
    if text is None:
        for block in blocks:
            render(block)
        return
    from ..agent import interleaved_answer
    for block in interleaved_answer(text, blocks):
        if block['kind'] == 'answer_text':
            render_text(block['text'])
        else:
            render(block)
