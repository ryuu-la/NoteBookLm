import pytest
from PIL import Image
from fpdf import FPDF

from local_notebook import storage as db, providers
from local_notebook.ingestion import jobs, media, parsers
from local_notebook.retrieval import search


def test_image_upload_is_rejected_before_saving(library):
    with pytest.raises(ValueError, match='Text-only mode'):
        jobs.add_file(library, 'image.png', b'Not used')
    assert not db.sources(library)


def test_pdf_indexes_only_native_text_without_rendering_or_ocr(library, monkeypatch):
    document = FPDF()
    document.add_page()
    document.set_font('Helvetica', size=12)
    document.text(10, 20, 'Native document text stays searchable.')
    document.image(Image.new('RGB', (50, 50), 'red'), x=10, y=30, w=60)
    document.add_page()
    document.image(Image.new('RGB', (50, 50), 'blue'), x=10, y=30, w=60)
    db.save_settings({'semantic': True})
    source = jobs.add_file(library, 'mixed.pdf', bytes(document.output()))
    def forbidden(*args, **kwargs):
        raise AssertionError('Text-only indexing must not run OCR')
    monkeypatch.setattr(parsers, 'ocr_image', forbidden)
    monkeypatch.setattr(parsers, 'ocr_pdf_page', forbidden)
    class Splitter:
        def split_text(self, text):
            return [text]
    monkeypatch.setattr(jobs, 'make_splitter', lambda semantic: Splitter())
    embedded = []
    monkeypatch.setattr(jobs.vectors, 'insert', embedded.extend)
    jobs.ingest(db.one('SELECT * FROM sources WHERE id=?', (source,)))
    assert len(embedded) == 1 and not embedded[0].get('image')
    assert 'Native document text' in embedded[0]['text']
    assert db.one('SELECT status FROM sources WHERE id=?', (source,))['status'] == 'ready'


def test_legacy_image_evidence_never_reaches_retrieval_or_answers(indexed, monkeypatch):
    book, source = indexed
    visual = {'id': 'old-image', 'source_id': source, 'notebook_id': book, 'ordinal': 99,
              'locator': 'Image', 'text': '', 'image': 'missing-image-file'}
    jobs.flush([visual], False)
    db.save_settings({'semantic': True})
    monkeypatch.setattr(search.vectors, 'search', lambda *args: [{'id': 'old-image', 'semantic_score': .99}])
    assert not search.retrieve(book, 'diagram').passages
    assert all(not p.get('image') for p in search.coverage(book).passages)
    assert media.answer_images([visual]) == []
    assert not providers.supports_images()


def test_multimodal_index_is_requeued_for_text_only_rebuild(indexed):
    _, source = indexed
    db.execute("UPDATE sources SET index_version=3 WHERE id=?", (source,))
    db.save_settings({'semantic': True})
    db.initialize()
    row = db.one('SELECT * FROM sources WHERE id=?', (source,))
    assert row['status'] == 'queued' and row['chunks'] == 0
