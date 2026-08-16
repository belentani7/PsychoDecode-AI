# PsychoDecode AI MVP

Analizador básico de conversaciones en `TXT`, `DOCX` y `PDF` para generar un informe PDF con:

- participantes detectados
- patrones de comunicación observables
- temas recurrentes
- resumen ejecutivo
- gráfico simple de intensidad por interlocutor

## Uso

```bash
python psychodecode.py "ruta/al/archivo.txt"
```

Salida:

- `output/analysis-*.json`
- `output/informe-*.pdf`
- `output/chart-*.png`

## Modos

- `local`: análisis heurístico sin API
- `openai`: usa `OPENAI_API_KEY` si existe

## Nota

El informe describe patrones textuales observables. No diagnostica trastornos ni sustituye evaluación profesional.
