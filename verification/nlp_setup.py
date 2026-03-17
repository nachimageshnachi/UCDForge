"""
NLP model loading and setup for the UCD Verification module.

All heavy resources (NLTK, CrossEncoder) are cached with
``@st.cache_resource`` so they are loaded only once per Streamlit session.

Note: spaCy ``en_core_web_trf`` is loaded directly in ``text_tools.py``
(matching postag.py).  Flair and ``en_core_web_md`` are no longer used.
"""

import os
import nltk
from nltk.corpus import words
from nltk.stem import WordNetLemmatizer

import streamlit as st
from sentence_transformers import SentenceTransformer


# ---------------------------------------------------------------------------
# Cached resource loaders
# ---------------------------------------------------------------------------

@st.cache_resource
def setup_nltk():
    nltk_data_dir = os.path.join(os.path.expanduser('~'), 'nltk_data')
    os.makedirs(nltk_data_dir, exist_ok=True)

    for corpus in ('words', 'punkt', 'averaged_perceptron_tagger', 'wordnet', 'omw-1.4'):
        nltk.download(corpus, download_dir=nltk_data_dir, quiet=True)

    return nltk_data_dir


@st.cache_resource
def getSimilarityEncoder():
    return SentenceTransformer("all-MiniLM-L6-v2")


@st.cache_resource
def getLemmatizer():
    return WordNetLemmatizer()


# ---------------------------------------------------------------------------
# Module-level initialisation (runs once on first import)
# ---------------------------------------------------------------------------

setup_nltk()
lemmatizer = getLemmatizer()
