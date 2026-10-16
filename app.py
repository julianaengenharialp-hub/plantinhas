import base64
import hashlib
import io
import json
import os
import re
import unicodedata
import uuid
from datetime import datetime
from html import escape
from urllib.parse import quote

import requests
import streamlit as st
from PIL import Image, ImageOps, ImageChops, ImageStat
from supabase import create_client

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer,
    Table, TableStyle, Image as PDFImage,
    PageBreak, KeepTogether
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# ============================================================
# CONFIGURAÇÃO
# ============================================================

st.set_page_config(
    page_title="Meu Jardim",
    page_icon="🪴",
    layout="wide"
)

API_GEMINI = "https://generativelanguage.googleapis.com/v1beta"
BUCKET = "fotos-plantas"

GRUPOS = ["Sol pleno", "Luz indireta", "Pouca luz"]
SOLOS = [
    "Bem drenado", "Orgânico", "Úmido",
    "Arenoso", "Outro", "Não definido"
]
TOXICIDADES = [
    "Não verificada",
    "Potencialmente tóxica",
    "Tóxica",
    "Sem toxicidade conhecida"
]
RARIDADES = ["Não avaliada", "Comum", "Incomum", "Rara"]
STATUS = ["Pendente", "No catálogo", "Arquivada"]

PREFERIDOS = [
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3-flash-preview",
    "gemini-flash-latest",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash"
]

CAMPOS_PLANTA = [
    "nome_comum", "nome_cientifico", "familia",
    "grupo", "solo_tipo", "toxicidade",
    "raridade", "justificativa_raridade",
    "status", "observacoes", "cuidados"
]


# ============================================================
# ESTILO
# ============================================================

st.markdown("""
<style>
.resumo-jardim {
    display: grid;
    grid-template-columns: repeat(3, minmax(0,1fr));
    gap: 10px;
    margin: 12px 0 24px;
}
.resumo-item {
    border: 1px solid rgba(128,128,128,.25);
    border-radius: 12px;
    padding: 12px 6px;
    text-align: center;
}
.resumo-numero {
    font-size: 30px;
    font-weight: 700;
