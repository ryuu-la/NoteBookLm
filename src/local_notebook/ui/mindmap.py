from nicegui.element import Element


class MindMapCanvas(Element, component="mindmap.js"):
    """A local, keyboard-accessible topic tree with independent branch controls."""

    def __init__(self, root: dict, citations: list[dict]):
        super().__init__()
        self._props["root"] = root
        self._props["citations"] = [
            {key: citation.get(key, "") for key in ("number", "id", "name", "locator")}
            for citation in citations
        ]
        self.classes("mindmap-explorer")
