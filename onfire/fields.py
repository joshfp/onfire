import torch
import numpy as np
from collections import OrderedDict
from sklearn.base import TransformerMixin, BaseEstimator
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler
from sklearn.impute import SimpleImputer
from abc import ABC, abstractmethod

from .transforms import (Projector, LabelEncoder, BasicTokenizer, TokensEncoder,
    ToTensor, MultiLabelEncoder)
from .models import ConcatEmbeddings, DummyModel, MeanOfEmbeddings

__all__ = [
    'CategoricalFeature',
    'TextFeature',
    'ContinuousFeature',
    'FeatureGroup',
    'SingleLabelTarget',
    'MultiLabelTarget',
    'ContinuousTarget',
]

class BaseField(ABC, TransformerMixin, BaseEstimator):
    def __init__(self, key, preprocessor, custom_tfms=None, dtype=None):
        tfms = []
        if key: tfms.append(Projector(key))
        if preprocessor: tfms.append(preprocessor)
        if custom_tfms: tfms.extend(custom_tfms)
        tfms.append(ToTensor(dtype=dtype))
        self.pipe = make_pipeline(*tfms)

    def transform(self, X):
        return self.pipe.transform(X)


class BaseFeature(BaseField):
    @abstractmethod
    def build_embedder(self):
        pass

    @abstractmethod
    def get_emb_dim(self):
        pass


class CategoricalFeature(BaseFeature):
    def __init__(self, key=None, preprocessor=None, emb_dim=None):
        self.key = key
        self.preprocessor = preprocessor
        self.emb_dim = emb_dim
        self.categorical_encoder = LabelEncoder()

        tfms = [self.categorical_encoder]
        super().__init__(self.key, self.preprocessor, tfms, dtype=torch.int64)

    def fit(self, X, y=None):
        self.pipe.fit(X)
        self.vocab = self.categorical_encoder.vocab
        self.emb_dim = self.emb_dim or min(len(self.vocab)//2, 50)
        return self

    def build_embedder(self):
        self.embedder = torch.nn.Embedding(len(self.vocab), self.emb_dim)
        return self.embedder

    def get_emb_dim(self):
        return self.emb_dim


class TextFeature(BaseFeature):
    def __init__(self, key=None, preprocessor=None, max_len=50, max_vocab=50000,
                 min_freq=3, emb_dim=100, tokenizer=None,embedder_cls=None,
                 embedder_vocab_size_argname='vocab_size', **kwargs):
        self.max_len = max_len
        self.max_vocab = max_vocab
        self.key = key
        self.preprocessor = preprocessor
        self.tokenizer = tokenizer or BasicTokenizer()
        self.min_freq = min_freq
        self.emb_dim = emb_dim
        self.token_encoder = TokensEncoder(self.max_len, self.max_vocab, self.min_freq)
        self.embedder_cls = embedder_cls or MeanOfEmbeddings
        self.embedder_vocab_size_argname = embedder_vocab_size_argname
        self.kwargs = kwargs or {}
        if self.embedder_cls == MeanOfEmbeddings:
            self.kwargs['emb_dim'] = self.emb_dim

        tfms = [self.tokenizer, self.token_encoder]
        super().__init__(self.key, self.preprocessor, tfms, dtype=torch.int64)

    def fit(self, X, y=None):
        self.pipe.fit(X)
        self.vocab = self.token_encoder.vocab
        self.kwargs[self.embedder_vocab_size_argname] = len(self.vocab)
        return self

    def build_embedder(self):
        self.embedder = self.embedder_cls(**self.kwargs)
        sample_input = torch.randint(len(self.vocab), (2, self.max_len))
        self.emb_dim = self.embedder(sample_input).shape[1]
        return self.embedder

    def get_emb_dim(self):
        return self.emb_dim


class ContinuousFeature(BaseFeature):
    def __init__(self, key=None, preprocessor=None, imputer=None, after_imputer=None, scaler=None):
        self.key = key
        self.preprocessor = preprocessor
        self.imputer = (imputer or SimpleImputer()) if (imputer!=False) else None
        self.after_imputer = after_imputer
        self.scaler = (scaler or StandardScaler()) if (scaler!=False) else None

        tfms = []
        tfms.append(FunctionTransformer(self.__to_2d_array))
        if self.imputer: tfms.append(self.imputer)
        if self.after_imputer: tfms.append(self.after_imputer)
        if self.scaler: tfms.append(self.scaler)
        super().__init__(self.key, self.preprocessor, tfms, dtype=torch.float32)

    def fit(self, X, y=None):
        self.pipe.fit(X)
        self.emb_dim = self.transform([X[0]]).shape[1]
        return self

    def build_embedder(self):
        self.embedder = DummyModel()
        return self.embedder

    def get_emb_dim(self):
        return self.emb_dim

    def __to_2d_array(self, x):
            return np.array(x, dtype=np.float32).reshape(len(x), -1)


class FeatureGroup(BaseFeature):
    def __init__(self, fields):
        self.fields = OrderedDict(fields)

    def fit(self, X, y=None):
        for field in self.fields.values():
            field.fit(X)
        return self

    def transform(self, X, y=None):
        return [field.transform(X) for field in self.fields.values()]

    def build_embedder(self):
        self.embedder = ConcatEmbeddings(self.fields)
        return self.embedder

    def get_emb_dim(self):
        return self.embedder.output_dim


class SingleLabelTarget(BaseField):
    def __init__(self, key=None, preprocessor=None):
        self.key = key
        self.preprocessor = preprocessor
        self.categorical_encoder = LabelEncoder(is_target=True)

        tfms = [self.categorical_encoder]
        super().__init__(self.key, self.preprocessor, tfms, dtype=torch.int64)

    def fit(self, X, y=None):
        self.pipe.fit(X)
        self.classes = self.categorical_encoder.vocab
        return self


class MultiLabelTarget(BaseField):
    def __init__(self, key=None, preprocessor=None):
        self.key = key
        self.preprocessor = preprocessor
        self.multi_label_encoder = MultiLabelEncoder()

        tfms = [self.multi_label_encoder]
        super().__init__(self.key, self.preprocessor, tfms, dtype=torch.int64)

    def fit(self, X, y=None):
        self.pipe.fit(X)
        self.classes = self.multi_label_encoder.vocab
        return self


class ContinuousTarget(BaseField):
    def __init__(self, key=None, preprocessor=None):
        self.key = key
        self.preprocessor = preprocessor
        super().__init__(self.key, self.preprocessor, dtype=torch.float32)

    def fit(self, X, y=None):
        self.pipe.fit(X)
        return self