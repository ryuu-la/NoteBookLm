"""Chunk with the embedding tokenizer so no indexed passage is silently truncated."""
import re


class EmbeddingSplitter:
    def __init__(self, tokenizer, size=512, overlap=64):
        from tokenizers import Tokenizer
        # The embedding model's tokenizer is shared with concurrent searches.
        # Clone it before disabling truncation/padding for full-document offsets.
        self.tokenizer = Tokenizer.from_str(tokenizer.to_str())
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        self.size, self.overlap = size, overlap

    def token_count(self, text):
        return len(self.tokenizer.encode(text, add_special_tokens=False).ids)

    def split_text(self, text):
        offsets = self.tokenizer.encode(text, add_special_tokens=False).offsets
        start = 0
        while start < len(offsets):
            end = min(start + self.size, len(offsets))
            if end < len(offsets):
                # Prefer a nearby sentence/paragraph ending, without making tiny chunks.
                for candidate in range(end, max(start + self.overlap + 1, end - 64), -1):
                    boundary = text[offsets[candidate - 1][0]:offsets[candidate][0]]
                    if re.search(r'[.!?]\s|\n', boundary):
                        end = candidate
                        break
            first = offsets[start][0] if start else 0
            last = offsets[end][0] if end < len(offsets) else len(text)
            chunk = text[first:last].strip()
            if chunk:
                yield chunk
            if end == len(offsets):
                break
            start = end - self.overlap


def make_splitter(semantic):
    if semantic:
        from ..config import MODEL_CACHE, EMBED_MODEL, EMBED_REVISION
        from tokenizers import Tokenizer
        tokenizer_path = (MODEL_CACHE / ('models--' + EMBED_MODEL.replace('/', '--'))
                          / 'snapshots' / EMBED_REVISION / 'tokenizer.json')
        if tokenizer_path.exists():
            # Reading the document must not wait for hundreds of MB of model weights.
            return EmbeddingSplitter(Tokenizer.from_file(str(tokenizer_path)))
        from ..retrieval.vectors import embedding_model
        return EmbeddingSplitter(embedding_model().tokenizer)
    from llama_index.core.node_parser import SentenceSplitter
    return SentenceSplitter(chunk_size=600, chunk_overlap=70)
