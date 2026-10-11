"""Run the unchanged Gemma text encoder as a cached, full-precision CPU graph."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from ..config import EMBED_REVISION, EMBED_THREADS, MODEL_CACHE


class CpuEncoder:
    def __init__(self, snapshot: Path):
        import openvino as ov
        from transformers import AutoTokenizer

        directory = MODEL_CACHE / 'embeddinggemma2-openvino-f32-v1' / EMBED_REVISION
        directory.mkdir(parents=True, exist_ok=True)
        model_path = directory / 'model.xml'
        if not model_path.exists():
            self.export(snapshot, model_path)
        self.tokenizer = AutoTokenizer.from_pretrained(str(snapshot), local_files_only=True)
        self.prompts = json.loads((snapshot / 'config_sentence_transformers.json').read_text())['prompts']
        self.max_seq_length = 8192
        self.compiled = ov.Core().compile_model(str(model_path), 'CPU', {
            'INFERENCE_PRECISION_HINT': 'f32', 'INFERENCE_NUM_THREADS': EMBED_THREADS,
            'PERFORMANCE_HINT': 'LATENCY', 'CACHE_DIR': str(directory / 'compiled'),
        })

    @staticmethod
    def export(snapshot, model_path):
        import openvino as ov
        import torch
        from sentence_transformers import SentenceTransformer

        encoder = SentenceTransformer(str(snapshot), device='cpu', local_files_only=True,
                                      config_kwargs={'vision_config': None, 'audio_config': None},
                                      model_kwargs={'torch_dtype': torch.float32})
        encoder.eval()

        class TextGraph(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.encoder = encoder

            def forward(self, input_ids, attention_mask):
                return self.encoder({'input_ids': input_ids, 'attention_mask': attention_mask,
                                     'modality': 'message'})['sentence_embedding']

        features = encoder.preprocess(['title: none | text: A source document.',
                                       'title: none | text: Another longer source document.'])
        with torch.no_grad():
            model = ov.convert_model(TextGraph().eval(),
                                     example_input=(features['input_ids'], features['attention_mask']),
                                     input=[('input_ids', [-1, -1]), ('attention_mask', [-1, -1])])
        # Interrupted conversion must never publish a partial model as reusable.
        with TemporaryDirectory(dir=model_path.parent) as temporary:
            staged = Path(temporary) / 'model.xml'
            ov.save_model(model, staged, compress_to_fp16=False)
            staged.with_suffix('.bin').replace(model_path.with_suffix('.bin'))
            staged.replace(model_path)

    def encode(self, inputs, *, prompt_name=None, **kwargs):
        if not all(isinstance(value, str) for value in inputs):
            raise ValueError('The CPU text encoder accepts text only.')
        prompt = self.prompts[prompt_name] if prompt_name else ''
        tokens = self.tokenizer([prompt + value for value in inputs], padding=True, truncation=True,
                                max_length=self.max_seq_length, return_tensors='np')
        values = self.compiled({key: tokens[key] for key in ('input_ids', 'attention_mask')})[0]
        return np.array(values, dtype=np.float32, copy=True)
