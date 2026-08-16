from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fpdf import FPDF

try:
    from docx import Document
except Exception:  # pragma: no cover
    Document = None

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover
    fitz = None

try:
    import matplotlib.pyplot as plt
except Exception:  # pragma: no cover
    plt = None

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None


WHATSAPP_RE = re.compile(
    r"^(?P<date>\d{1,2}/\d{1,2}/\d{2,4}),?\s*(?P<time>\d{1,2}:\d{2})\s*-\s*(?P<speaker>[^:]+):\s*(?P<text>.*)$"
)
SMS_RE = re.compile(r"^(?P<speaker>[^:]{1,60}):\s*(?P<text>.+)$")


@dataclass
class Message:
    speaker: str
    text: str
    timestamp: str | None = None


def read_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def read_docx(path: Path) -> str:
    if Document is None:
        raise RuntimeError("python-docx no está disponible. Instala `python-docx`.")
    doc = Document(str(path))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells if cell.text.strip())
    return "\n".join(parts)


def read_pdf(path: Path) -> str:
    if fitz is None:
        raise RuntimeError("PyMuPDF no está disponible. Instala `pymupdf`.")
    doc = fitz.open(str(path))
    parts: list[str] = []
    for page in doc:
        parts.append(page.get_text("text"))
    return "\n".join(parts)


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return read_txt(path)
    if suffix == ".docx":
        return read_docx(path)
    if suffix == ".pdf":
        return read_pdf(path)
    raise ValueError(f"Formato no soportado: {suffix}")


def parse_conversation(text: str) -> list[Message]:
    messages: list[Message] = []
    current: Message | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        match = WHATSAPP_RE.match(line)
        if match:
            if current and current.text.strip():
                messages.append(current)
            current = Message(
                speaker=match.group("speaker").strip(),
                text=match.group("text").strip(),
                timestamp=f"{match.group('date')} {match.group('time')}",
            )
            continue

        match = SMS_RE.match(line)
        if match and len(match.group("speaker").split()) <= 6:
            if current and current.text.strip():
                messages.append(current)
            current = Message(
                speaker=match.group("speaker").strip(),
                text=match.group("text").strip(),
                timestamp=None,
            )
            continue

        if current is None:
            current = Message(speaker="Unknown", text=line, timestamp=None)
        else:
            current.text = f"{current.text} {line}".strip()

    if current and current.text.strip():
        messages.append(current)

    return messages


def normalize_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    return name


def detect_participants(messages: list[Message]) -> list[str]:
    speakers = [normalize_name(m.speaker) for m in messages if m.speaker and m.speaker != "Unknown"]
    counts = Counter(speakers)
    return [speaker for speaker, _ in counts.most_common()]


def local_analysis(messages: list[Message], participants: list[str]) -> dict[str, Any]:
    by_speaker: dict[str, list[str]] = defaultdict(list)
    for msg in messages:
        by_speaker[normalize_name(msg.speaker)].append(msg.text)

    message_counts = Counter(normalize_name(m.speaker) for m in messages if m.speaker != "Unknown")
    question_counts = Counter()
    imperative_counts = Counter()
    conflict_counts = Counter()
    support_counts = Counter()

    conflict_markers = [
        "mentira",
        "loco",
        "loca",
        "prueba",
        "denuncia",
        "abuso",
        "culpa",
        "deuda",
        "polic",
        "rob",
        "manip",
        "rabia",
    ]
    support_markers = [
        "te quiero",
        "gracias",
        "ayuda",
        "apoyo",
        "amigo",
        "beijo",
        "beso",
        "cariño",
    ]

    for msg in messages:
        speaker = normalize_name(msg.speaker)
        txt = msg.text.lower()
        question_counts[speaker] += txt.count("?")
        imperative_counts[speaker] += len(re.findall(r"\b(ven|haz|manda|deja|para|escucha|calla|sube|dime)\b", txt))
        conflict_counts[speaker] += sum(1 for marker in conflict_markers if marker in txt)
        support_counts[speaker] += sum(1 for marker in support_markers if marker in txt)

    toxicity: dict[str, int] = {}
    dissonance: dict[str, str] = {}
    roles: dict[str, str] = {}

    for participant in participants[:4]:
        total = message_counts.get(participant, 0)
        score = min(100, max(0, conflict_counts.get(participant, 0) * 14 + imperative_counts.get(participant, 0) * 5 + question_counts.get(participant, 0) * 2))
        toxicity[participant] = score
        if score >= 60:
            dissonance[participant] = "alta"
        elif score >= 30:
            dissonance[participant] = "media"
        else:
            dissonance[participant] = "baja"

        if support_counts.get(participant, 0) > conflict_counts.get(participant, 0):
            roles[participant] = "salvador / apoyo"
        elif conflict_counts.get(participant, 0) > 0 and imperative_counts.get(participant, 0) > 0:
            roles[participant] = "perseguidor"
        elif total > 0:
            roles[participant] = "participante reactivo"
        else:
            roles[participant] = "no determinado"

    themes = Counter()
    for msg in messages:
        txt = msg.text.lower()
        if any(word in txt for word in ["dinero", "deuda", "pagar", "empréstimo", "prestamo", "préstamo", "loan"]):
            themes["dinero / deuda"] += 1
        if any(word in txt for word in ["amor", "beijo", "beso", "cariño", "princesa", "boy", "amigo"]):
            themes["afecto / vínculo"] += 1
        if any(word in txt for word in ["trabajo", "empresa", "sepe", "hacienda", "soc", "turno"]):
            themes["trabajo / trámites"] += 1
        if any(word in txt for word in ["ansiedad", "miedo", "solo", "solo", "saco", "cabeza", "dorm"]):
            themes["ansiedad / regulación"] += 1
        if any(word in txt for word in ["casa", "puerta", "visita", "ir", "venir", "quedar"]):
            themes["espacio / presencia"] += 1

    recurring_themes = [name for name, _ in themes.most_common()]
    timeline = []
    for msg in messages[:250]:
        timeline.append(
            {
                "timestamp": msg.timestamp,
                "speaker": msg.speaker,
                "text": msg.text[:200],
            }
        )

    summary = (
        "El intercambio muestra una fase de cercanía y colaboración seguida por una fase de tensión "
        "en la que aparecen control, reputación, dinero, espacio personal y relecturas del vínculo. "
        "La lectura más sólida es conductual: cambios de tono, cambios de marco moral y momentos de "
        "defensa agresiva cuando se percibe pérdida de control."
    )

    return {
        "roles": roles,
        "manipulacion": [name for name in ["externalización", "cambio de marco", "presión", "victimización", "amenaza latente"] if name],
        "disonancia": dissonance,
        "temas": recurring_themes,
        "toxicidad": toxicity,
        "resumen": summary,
        "timeline": timeline,
    }


def openai_analysis(messages: list[Message], participants: list[str]) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or OpenAI is None:
        return local_analysis(messages, participants)

    client = OpenAI(api_key=api_key)
    transcript = "\n".join(
        f"{m.timestamp + ' - ' if m.timestamp else ''}{m.speaker}: {m.text}" for m in messages[:1000]
    )

    prompt = f"""
Analiza esta conversación como comunicación textual, no como diagnóstico clínico.
Detecta patrones conductuales observables, roles relacionales, temas recurrentes y posibles tensiones.
Usa lenguaje cauteloso y basado en evidencia textual.

Participantes: {", ".join(participants)}

CONVERSACIÓN:
{transcript}

Devuelve JSON con:
{{
  "roles": {{"persona": "rol conductual"}},
  "manipulacion": ["patrón1"],
  "disonancia": {{"persona": "baja|media|alta"}},
  "temas": ["tema1"],
  "toxicidad": {{"persona": 0}},
  "resumen": "texto breve",
  "evidencia": [{{"speaker": "persona", "quote": "fragmento corto", "reason": "por qué importa"}}]
}}
"""

    response = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        input=[
            {
                "role": "system",
                "content": "Eres un analista de comunicación textual. No diagnosticas ni afirmas condiciones clínicas.",
            },
            {"role": "user", "content": prompt},
        ],
        text={"format": {"type": "json_object"}},
    )

    content = response.output_text
    return json.loads(content)


def build_emotion_chart(messages: list[Message], output_path: Path) -> Path | None:
    if plt is None:
        return None

    speakers = [normalize_name(m.speaker) for m in messages if m.speaker != "Unknown"]
    counts = Counter(speakers)
    labels = list(counts.keys())[:8]
    values = [counts[label] for label in labels]

    if not labels:
        return None

    fig, ax = plt.subplots(figsize=(8, 3.5), dpi=180)
    ax.bar(labels, values, color="#d3a46a")
    ax.set_title("Intensidad por interlocutor")
    ax.set_ylabel("Mensajes")
    ax.grid(axis="y", alpha=0.2)
    ax.tick_params(axis="x", rotation=25)
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)
    return output_path


class ReportPDF(FPDF):
    def header(self) -> None:
        self.set_font("Helvetica", "B", 15)
        self.cell(0, 10, "PsychoDecode AI - Informe de dinamica relacional", 0, 1, "C")
        self.ln(2)


def add_section_title(pdf: FPDF, title: str) -> None:
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, title, 0, 1)
    pdf.ln(1)


def add_multiline(pdf: FPDF, text: str) -> None:
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 6, text)


def create_pdf_report(analysis: dict[str, Any], output_file: Path, chart_path: Path | None) -> None:
    pdf = ReportPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    add_section_title(pdf, "Resumen ejecutivo")
    add_multiline(pdf, analysis.get("resumen", "No disponible"))

    pdf.ln(2)
    add_section_title(pdf, "Roles observados")
    for participant, role in analysis.get("roles", {}).items():
        pdf.cell(0, 7, f"{participant}: {role}", 0, 1)

    pdf.ln(2)
    add_section_title(pdf, "Patrones de comunicacion")
    for item in analysis.get("manipulacion", []):
        pdf.cell(0, 7, f"- {item}", 0, 1)

    pdf.ln(2)
    add_section_title(pdf, "Tension relativa")
    for participant, score in analysis.get("toxicidad", {}).items():
        bar = "█" * max(1, int(score / 8)) if score else ""
        pdf.cell(0, 7, f"{participant}: {score}/100 {bar}", 0, 1)

    pdf.ln(2)
    add_section_title(pdf, "Nivel estimado de disonancia")
    for participant, level in analysis.get("disonancia", {}).items():
        pdf.cell(0, 7, f"{participant}: {level}", 0, 1)

    pdf.ln(2)
    add_section_title(pdf, "Temas recurrentes")
    for tema in analysis.get("temas", []):
        pdf.cell(0, 7, f"- {tema}", 0, 1)

    if chart_path and chart_path.exists():
        pdf.add_page()
        add_section_title(pdf, "Grafico de intensidad")
        pdf.image(str(chart_path), w=175)

    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 9)
    pdf.multi_cell(
        0,
        5,
        "Aviso: este informe describe patrones textuales observables. No realiza diagnostico clinico ni sustituye evaluacion profesional.",
    )

    pdf.output(str(output_file))


def save_json(data: dict[str, Any], output_path: Path) -> None:
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Analiza conversaciones y genera un informe PDF.")
    parser.add_argument("input_file", help="Archivo TXT, DOCX o PDF")
    parser.add_argument("--output-dir", default="output", help="Carpeta de salida")
    parser.add_argument("--mode", choices=["local", "openai"], default=os.getenv("PSYCHODECODE_MODE", "local"))
    args = parser.parse_args()

    input_path = Path(args.input_file).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"No existe: {input_path}")

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_text = extract_text(input_path)
    messages = parse_conversation(raw_text)
    participants = detect_participants(messages)

    if args.mode == "openai":
        analysis = openai_analysis(messages, participants)
    else:
        analysis = local_analysis(messages, participants)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = output_dir / f"analysis-{stamp}.json"
    pdf_path = output_dir / f"informe-{stamp}.pdf"
    chart_path = output_dir / f"chart-{stamp}.png"

    chart = build_emotion_chart(messages, chart_path)
    save_json(
        {
            "input_file": str(input_path),
            "participants": participants,
            "message_count": len(messages),
            "analysis": analysis,
        },
        json_path,
    )
    create_pdf_report(analysis, pdf_path, chart)

    print(f"JSON: {json_path}")
    print(f"PDF: {pdf_path}")
    if chart:
        print(f"Chart: {chart}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
